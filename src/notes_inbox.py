"""Apple Notes ingest — picks up notes from the configured folder once they go quiet.

Two-pass design:
  1. List (id, title, modified_at) for every note in the folder via AppleScript.
  2. Filter to notes that (a) have been untouched for >= NOTE_QUIET_SECS and
     (b) aren't already ingested at this modification timestamp.
  3. Fetch body HTML only for survivors and convert to plaintext.

Re-ingest semantics: each distinct (note_id, modified_at) pair is treated as
its own reflection. Edit a note days later, the orb picks up the new version
and runs a fresh insight pass — you see how the thinking evolved.
"""
import html
import logging
import re
import subprocess
import time
from datetime import datetime

from config import NOTES_FOLDER, NOTE_QUIET_SECS

log = logging.getLogger("orb.notes")


_LIST_SCRIPT = """
tell application "Notes"
  set out to ""
  repeat with n in notes of folder "{folder}"
    set out to out & (id of n) & tab & (name of n) & tab & ((modification date of n) as «class isot» as string) & linefeed
  end repeat
  return out
end tell
"""


_BODY_SCRIPT = """
tell application "Notes"
  return body of note id "{note_id}"
end tell
"""


def _osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout


def _html_to_text(body: str) -> str:
    # Apple Notes returns HTML like <div>...<br></div>. Treat block-level
    # boundaries as newlines, then strip remaining tags and unescape entities.
    s = re.sub(r"</(div|p|h[1-6]|li|tr)>", "\n", body, flags=re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    # Collapse 3+ newlines to 2; strip trailing whitespace per line
    s = re.sub(r"\n{3,}", "\n\n", s)
    return "\n".join(line.rstrip() for line in s.splitlines()).strip()


def _parse_modified_at(s: str) -> datetime:
    # AppleScript «class isot» yields e.g. "2026-05-23T16:35:58"
    return datetime.fromisoformat(s)


def list_notes() -> list[dict]:
    """Return [{id, title, modified_at (str), modified_dt (datetime)}, ...]."""
    out = _osascript(_LIST_SCRIPT.format(folder=NOTES_FOLDER))
    notes = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            log.warning("unparseable notes line: %r", line)
            continue
        note_id, title, mtime_str = parts
        try:
            mtime_dt = _parse_modified_at(mtime_str)
        except ValueError:
            log.warning("unparseable mtime for note %s: %r", note_id, mtime_str)
            continue
        notes.append({
            "id": note_id,
            "title": title,
            "modified_at": mtime_str,
            "modified_dt": mtime_dt,
        })
    return notes


def fetch_body(note_id: str) -> str:
    """Fetch the body of a single note as plaintext."""
    raw = _osascript(_BODY_SCRIPT.format(note_id=note_id))
    return _html_to_text(raw)


def find_ready_notes(already_processed) -> list[dict]:
    """Notes that have gone quiet and aren't yet ingested at this revision.

    `already_processed(note_id, modified_at)` is injected so this module
    stays decoupled from the db layer (keeps it easy to test).
    """
    now = time.time()
    ready = []
    for n in list_notes():
        age = now - n["modified_dt"].timestamp()
        if age < NOTE_QUIET_SECS:
            continue
        if already_processed(n["id"], n["modified_at"]):
            continue
        ready.append(n)
    return ready
