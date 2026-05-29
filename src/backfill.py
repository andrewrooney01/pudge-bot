"""Backfill the world model from existing reflections.

For each recording in the DB:
  1. If it has no entity mentions, re-run extraction over its transcript
     and persist via db.save_entities.
  2. Regenerate the daily-note block and touch each referenced entity file.

Safe to re-run. Each reflection's daily-note block is fenced + re-emitted
on every pass, so manual edits between the fences are overwritten while
anything outside the fences is preserved.

Usage:
  python src/backfill.py                  # full pass over all reflections
  python src/backfill.py --limit 5        # try with a small batch first
  python src/backfill.py --skip-extract   # only redraw vault files; skip LLM
  python src/backfill.py --ids 12,17,22   # specific recording ids
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime

import db
import ontology
import vault
from config import LENS_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("backfill")

EXTRACTION_TIMEOUT_SECS = 180


# ---------------------------------------------------------------------------
# Entity-only extraction (cheaper + narrower than the full insights pass)
# ---------------------------------------------------------------------------

ENTITY_PROMPT = """You are extracting entities from one of the user's past reflections so they can be tracked across time.

The user's canonical self-model (ontology) is below for naming context — use the same names the user uses for people, projects, and recurring concepts.

## User ontology (canonical self-model)
{onto}

---

## Reflection to extract from

Source: {source}{title_line}
Date: {date}

\"\"\"
{transcript}
\"\"\"

Return a single JSON object, no markdown fences, no preamble:

{{
  "entities": [
    {{"type": "person|project|concept|decision", "name": "stable canonical name", "context": "≤140 char snippet of how it appeared in this reflection"}}
  ]
}}

Rules:
- Use canonical names — same person across reflections must get the same name. Prefer the form the user used in the text.
- Skip one-off names with no tracking value (random brand names, addresses, etc.).
- "decision" is for active deliberations or made decisions, not generic actions.
- "concept" is for recurring framings/ideas, not common words.
- If nothing qualifies, return an empty list. Do NOT invent entities.
"""


def extract_entities(transcript: str, *, source: str, title: str | None, date: str) -> list[dict]:
    onto = ontology.load(include_books=False) or "(empty)"
    title_line = f"\nTitle: {title}" if title else ""
    prompt = ENTITY_PROMPT.format(
        onto=onto,
        source=source,
        title_line=title_line,
        date=date,
        transcript=transcript[:8000],  # cap pathological transcripts
    )
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=EXTRACTION_TIMEOUT_SECS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr.strip()[:300]}")
    raw = result.stdout.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in entity-extraction response: {raw[:200]}")
    parsed = json.loads(m.group(0))
    ents = parsed.get("entities") or []
    return [e for e in ents if isinstance(e, dict)]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _load_recording(rec_id: int) -> dict | None:
    """Pull the full reflection row + transcript + entities for vault render."""
    full = db.reflection_full(rec_id)
    if not full:
        return None
    full["entities"] = db.entities_for_recording(rec_id)
    return full


def backfill_one(rec_id: int, *, skip_extract: bool) -> tuple[bool, int]:
    """Process a single reflection. Returns (extracted?, n_entities)."""
    r = _load_recording(rec_id)
    if not r:
        log.warning("rec=%s not found", rec_id)
        return (False, 0)
    if not (r.get("transcript") or "").strip():
        log.info("rec=%s has no transcript, skipping", rec_id)
        return (False, 0)

    extracted = False
    if not skip_extract and not r["entities"]:
        date = (r.get("recorded_at") or "")[:10]
        try:
            new_ents = extract_entities(
                r["transcript"],
                source=r.get("source") or "voice",
                title=r.get("note_title"),
                date=date,
            )
        except Exception as e:
            log.error("rec=%s extraction failed: %s", rec_id, e)
            new_ents = []
        if new_ents:
            # Idempotent: wipe + reinsert so retries don't double up.
            db.clear_entities_for_recording(rec_id)
            db.save_entities(rec_id, new_ents)
            extracted = True
        r = _load_recording(rec_id)

    # Always rewrite the daily-note block + entity files (cheap, no LLM).
    parsed_for_vault = {
        "summary": r.get("summary"),
        "mood": r.get("mood"),
        "themes": r.get("themes"),
        "pattern": r.get("pattern"),
        "question": r.get("question"),
        "inconsistencies": r.get("inconsistencies") or [],
        "proposals": [],  # historical proposals already lived through /accept|/dismiss; don't re-surface
    }
    acoustic = None
    if r.get("source") != "note":
        acoustic = {
            "speaking_rate_wpm": r.get("speaking_rate_wpm"),
            "pitch_std": r.get("pitch_std"),
            "pause_ratio": r.get("pause_ratio"),
            "duration_sec": r.get("duration_sec"),
        }
    try:
        recorded_at = datetime.fromisoformat(r["recorded_at"])
    except (TypeError, ValueError):
        log.error("rec=%s has invalid recorded_at=%r", rec_id, r.get("recorded_at"))
        return (extracted, len(r["entities"]))

    try:
        vault.write_reflection(
            rec_id=rec_id,
            recorded_at=recorded_at,
            source=r.get("source") or "voice",
            transcript=r["transcript"],
            parsed=parsed_for_vault,
            entities=r["entities"],
            acoustic=acoustic,
            note_title=r.get("note_title"),
        )
    except Exception as e:
        log.error("rec=%s vault write failed: %s", rec_id, e)
    return (extracted, len(r["entities"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="backfill the orb's world model")
    ap.add_argument("--limit", type=int, default=None, help="cap number of reflections")
    ap.add_argument("--skip-extract", action="store_true", help="redraw vault files only; no LLM calls")
    ap.add_argument("--ids", type=str, default=None, help="comma-separated recording ids")
    ap.add_argument("--all", action="store_true",
                    help="re-extract entities even for reflections that already have some")
    args = ap.parse_args()

    db.init()

    if args.ids:
        rec_ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.all:
        with db.conn() as c:
            rec_ids = [r["id"] for r in c.execute(
                "SELECT id FROM recordings ORDER BY recorded_at ASC"
            ).fetchall()]
    else:
        # Default: every recording that has at least one transcript and no entities yet.
        with db.conn() as c:
            rec_ids = [r["id"] for r in c.execute(
                """SELECT r.id FROM recordings r
                   JOIN transcripts t ON t.recording_id = r.id
                   LEFT JOIN entity_mentions em ON em.recording_id = r.id
                   WHERE em.id IS NULL
                   ORDER BY r.recorded_at ASC"""
            ).fetchall()]

    if args.limit:
        rec_ids = rec_ids[: args.limit]

    log.info("backfilling %d reflection(s) (skip_extract=%s)", len(rec_ids), args.skip_extract)
    start = time.time()
    n_extracted = 0
    n_entities_total = 0
    for i, rec_id in enumerate(rec_ids, 1):
        log.info("[%d/%d] rec=%s", i, len(rec_ids), rec_id)
        extracted, n = backfill_one(rec_id, skip_extract=args.skip_extract)
        if extracted:
            n_extracted += 1
        n_entities_total += n
    elapsed = time.time() - start
    log.info(
        "done · %d reflections processed · %d freshly extracted · %d entity mentions total · %.1fs",
        len(rec_ids), n_extracted, n_entities_total, elapsed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
