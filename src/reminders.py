import json
import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone

import db
import notify

log = logging.getLogger("orb.reminders")


EXTRACT_PROMPT = """You extract reminder intents from something Andrew said or typed.

Text:
\"\"\"
{text}
\"\"\"

Return a JSON object: {{"reminders": [...]}}. Each reminder has:
  - "text": short imperative description ("call mom", "follow up with Pat")
  - "due_in_minutes": integer minutes from now until it should fire

Only extract explicit reminder requests ("remind me to ...", "in a couple
of days nudge me about ...", "tomorrow morning ping me to ..."). If no
reminder is requested, return {{"reminders": []}}.

Time hints:
  "in an hour" -> 60
  "in a few hours" -> 240
  "tomorrow" -> 1440
  "in a couple of days" -> 2880
  "in a few days" -> 4320
  "next week" -> 10080

Respond with the JSON object only. No prose, no code fences."""


def _call_claude(prompt: str) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr}")
    return result.stdout


def _parse(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return []
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    items = obj.get("reminders") or []
    return items if isinstance(items, list) else []


def extract_and_save(
    text: str,
    source: str,
    source_id: int | None = None,
) -> list[int]:
    """Detect reminder intents in text and persist them. Returns ids saved."""
    if not text or not text.strip():
        return []
    raw = _call_claude(EXTRACT_PROMPT.format(text=text))
    items = _parse(raw)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    saved = []
    for item in items:
        body = (item.get("text") or "").strip()
        minutes = item.get("due_in_minutes")
        if not body or not isinstance(minutes, (int, float)):
            continue
        minutes = int(minutes)
        if minutes < 1:
            continue
        due_at = now + timedelta(minutes=minutes)
        rid = db.add_reminder(body, due_at, source, source_id)
        saved.append(rid)
        log.info("scheduled reminder #%d for %s: %s", rid, due_at.isoformat(), body)
    return saved


def _format(reminder: dict) -> str:
    return f"orb · reminder\n\n{reminder['text']}"


def fire_due() -> int:
    """Send any reminders whose due time has passed. Returns count sent."""
    rows = db.due_reminders()
    sent = 0
    for r in rows:
        try:
            notify.send(_format(r))
        except Exception:
            log.exception("failed firing reminder %s", r["id"])
            continue
        db.mark_reminder_sent(r["id"])
        sent += 1
    return sent
