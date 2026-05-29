import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from config import JPR_DIR, LOGS_DIR, NOTE_MIN_BODY_CHARS

import db
import transcribe
import acoustic
import insights
import notify
import inbox
import notes_inbox
import query
import commands
import vault


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "orb.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("orb")


SYNC_QUIET_SECS = 30


def find_new_recordings() -> list[Path]:
    if not JPR_DIR.exists():
        log.warning("JPR directory not found: %s", JPR_DIR)
        return []

    new_files = []
    for path in sorted(JPR_DIR.rglob("*.m4a")):
        if path.name.startswith("."):
            continue
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            continue
        if time.time() - mtime < SYNC_QUIET_SECS:
            continue
        if db.already_processed(path):
            continue
        new_files.append(path)
    return new_files


def _recorded_at_from_path(path: Path) -> datetime:
    try:
        date_str = path.parent.name
        time_str = path.stem.replace("-", ":")
        return datetime.fromisoformat(f"{date_str}T{time_str}")
    except Exception:
        return datetime.fromtimestamp(path.stat().st_mtime)


def process(audio_path: Path) -> None:
    log.info("Processing %s", audio_path.name)

    log.info("  transcribing...")
    t = transcribe.transcribe(audio_path)
    log.info("  transcript: %d chars, lang=%s", len(t["text"]), t["language"])

    log.info("  analyzing acoustics...")
    a = acoustic.analyze(audio_path, t["text"])
    log.info(
        "  duration=%.1fs, wpm=%s, pause=%s",
        a["duration_sec"],
        f"{a['speaking_rate_wpm']:.0f}" if a["speaking_rate_wpm"] else "?",
        f"{a['pause_ratio']:.2f}" if a["pause_ratio"] else "?",
    )

    log.info("  generating insights...")
    parsed, raw = insights.generate(t["text"], a)
    log.info("  insight: [%s] %s", parsed.get("mood"), parsed.get("summary", "")[:80])
    if parsed.get("inconsistencies"):
        for tension in parsed["inconsistencies"]:
            log.info("  ⚡ inconsistency: %s", tension)

    log.info("  sending message...")
    msg = notify.format_message(parsed, a)
    notify.send(msg)

    # Persist only after the full pipeline succeeds so a failed run is retried
    rec_id = db.insert_recording(
        audio_path,
        _recorded_at_from_path(audio_path),
        a["duration_sec"],
    )
    db.save_transcript(rec_id, t["text"], t["language"])
    db.save_acoustic(rec_id, a)
    db.save_insights(rec_id, parsed, raw)
    inconsistencies = parsed.get("inconsistencies") if isinstance(parsed.get("inconsistencies"), list) else []
    db.save_inconsistencies(rec_id, [x for x in inconsistencies if isinstance(x, str)])
    proposals = parsed.get("proposals") if isinstance(parsed.get("proposals"), list) else []
    for prop in proposals:
        if isinstance(prop, dict):
            db.save_proposal(rec_id, prop.get("file", ""), prop.get("section", ""), prop.get("proposal", ""))
    if proposals:
        log.info("  %d ontology proposal(s) queued", len(proposals))

    entities_raw = parsed.get("entities") if isinstance(parsed.get("entities"), list) else []
    entities = db.save_entities(rec_id, entities_raw)
    if entities:
        log.info("  %d entit%s extracted", len(entities), "y" if len(entities) == 1 else "ies")

    try:
        vault.write_reflection(
            rec_id=rec_id,
            recorded_at=_recorded_at_from_path(audio_path),
            source="voice",
            transcript=t["text"],
            parsed=parsed,
            entities=entities,
            acoustic=a,
        )
    except Exception:
        log.warning("vault write failed for rec=%s", rec_id, exc_info=True)

    log.info("✓ done: %s", audio_path.name)


def process_note(note: dict) -> None:
    """Ingest a single Apple Note: fetch body, run insights, notify, persist."""
    log.info("Processing note %s (%s)", note["id"][-8:], note["title"])

    body = notes_inbox.fetch_body(note["id"])
    if len(body.strip()) < NOTE_MIN_BODY_CHARS:
        log.info("  note body too short (%d chars), skipping", len(body.strip()))
        return
    log.info("  body: %d chars", len(body))

    log.info("  generating insights...")
    parsed, raw = insights.generate(body, acoustic=None, source="note", title=note["title"])
    log.info("  insight: [%s] %s", parsed.get("mood"), parsed.get("summary", "")[:80])
    if parsed.get("inconsistencies"):
        for tension in parsed["inconsistencies"]:
            log.info("  ⚡ inconsistency: %s", tension)

    log.info("  sending message...")
    msg = notify.format_note_message(parsed, note["title"])
    notify.send(msg)

    rec_id = db.insert_note_reflection(
        note["id"],
        note["title"],
        note["modified_at"],
        note["modified_dt"],
    )
    db.save_transcript(rec_id, body, "en")
    db.save_insights(rec_id, parsed, raw)
    inconsistencies = parsed.get("inconsistencies") if isinstance(parsed.get("inconsistencies"), list) else []
    db.save_inconsistencies(rec_id, [x for x in inconsistencies if isinstance(x, str)])
    proposals = parsed.get("proposals") if isinstance(parsed.get("proposals"), list) else []
    for prop in proposals:
        if isinstance(prop, dict):
            db.save_proposal(rec_id, prop.get("file", ""), prop.get("section", ""), prop.get("proposal", ""))
    if proposals:
        log.info("  %d ontology proposal(s) queued", len(proposals))

    entities_raw = parsed.get("entities") if isinstance(parsed.get("entities"), list) else []
    entities = db.save_entities(rec_id, entities_raw)
    if entities:
        log.info("  %d entit%s extracted", len(entities), "y" if len(entities) == 1 else "ies")

    try:
        vault.write_reflection(
            rec_id=rec_id,
            recorded_at=note["modified_dt"],
            source="note",
            transcript=body,
            parsed=parsed,
            entities=entities,
            acoustic=None,
            note_title=note["title"],
        )
    except Exception:
        log.warning("vault write failed for note rec=%s", rec_id, exc_info=True)

    log.info("✓ done: note %s", note["title"])


def answer_question(msg: dict) -> None:
    text = msg["text"]
    bot = msg.get("bot", "pudge")
    log.info("Answering (bot=%s): %s", bot, text[:80])

    # Slash-commands are deterministic and skip the LLM path entirely.
    command_reply = commands.dispatch(text)
    if command_reply is not None:
        notify.send(command_reply, bot=bot)
        db.save_query(text, command_reply, command_reply, sender=msg.get("sender"))
        log.info("✓ handled command (update_id=%s)", msg.get("update_id"))
        return

    reply, raw = query.answer(text)
    notify.send(reply, bot=bot)
    db.save_query(text, reply, raw, sender=msg.get("sender"))
    log.info("✓ answered (update_id=%s)", msg.get("update_id"))


def main() -> int:
    db.init()
    failures = 0

    new = find_new_recordings()
    if new:
        log.info("found %d new recording(s)", len(new))
        for path in new:
            try:
                process(path)
            except Exception:
                failures += 1
                log.error("failed processing %s\n%s", path, traceback.format_exc())
    else:
        log.debug("no new recordings")

    try:
        ready_notes = notes_inbox.find_ready_notes(db.already_processed_note)
    except Exception:
        ready_notes = []
        log.error("failed listing notes\n%s", traceback.format_exc())
    if ready_notes:
        log.info("found %d ready note(s)", len(ready_notes))
        for note in ready_notes:
            try:
                process_note(note)
            except Exception:
                failures += 1
                log.error("failed processing note %s\n%s", note.get("id"), traceback.format_exc())

    questions = inbox.poll_all()
    if questions:
        log.info("found %d new message(s)", len(questions))
        for msg in questions:
            try:
                answer_question(msg)
            except Exception:
                failures += 1
                log.error(
                    "failed answering update_id=%s\n%s",
                    msg.get("update_id"),
                    traceback.format_exc(),
                )

    return failures


if __name__ == "__main__":
    sys.exit(main())
