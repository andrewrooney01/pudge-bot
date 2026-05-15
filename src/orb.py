import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from config import JPR_DIR, LOGS_DIR

import db
import transcribe
import acoustic
import insights
import notify
import inbox
import query


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

    log.info("  sending iMessage...")
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
    for prop in parsed.get("proposals", []):
        db.save_proposal(rec_id, prop.get("file", ""), prop.get("section", ""), prop.get("proposal", ""))
    if parsed.get("proposals"):
        log.info("  %d ontology proposal(s) queued", len(parsed["proposals"]))

    log.info("✓ done: %s", audio_path.name)


def answer_question(msg: dict) -> None:
    text = msg["text"]
    log.info("Answering: %s", text[:80])
    reply, raw = query.answer(text)
    notify.send(reply)
    db.save_query(text, reply, raw, sender=msg.get("sender"))
    log.info("✓ answered (rowid=%s)", msg.get("rowid"))


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

    questions = inbox.poll()
    if questions:
        log.info("found %d new message(s)", len(questions))
        for msg in questions:
            try:
                answer_question(msg)
            except Exception:
                failures += 1
                log.error(
                    "failed answering rowid=%s\n%s",
                    msg.get("rowid"),
                    traceback.format_exc(),
                )

    return failures


if __name__ == "__main__":
    sys.exit(main())
