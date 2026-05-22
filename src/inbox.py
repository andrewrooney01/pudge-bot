import logging
import sqlite3

import db
from config import CHAT_DB_PATH, MAC_SENDER_HANDLES, OWNER_HANDLES

log = logging.getLogger("orb.inbox")

STATE_KEY = "last_chat_rowid"


def _open_chat_db() -> sqlite3.Connection | None:
    if not CHAT_DB_PATH.exists():
        log.warning("chat.db not found at %s", CHAT_DB_PATH)
        return None
    try:
        # Read-only; chat.db is owned by Messages.app and Full Disk Access
        # is required for the launchd job to read it.
        c = sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c
    except sqlite3.OperationalError as e:
        log.warning("can't open chat.db (Full Disk Access required?): %s", e)
        return None


def _max_rowid(c: sqlite3.Connection) -> int:
    row = c.execute("SELECT MAX(ROWID) AS m FROM message").fetchone()
    return row["m"] or 0


def poll() -> list[dict]:
    """Return new iMessages worth responding to since the last poll.

    A "query" is any message that:
      - involves one of the user's own handles (sender or recipient), AND
      - was NOT sent from this Mac itself (i.e., not an orb output).

    Distinguishing self-Apple-ID messages: when the user texts from their
    iPhone to their iCloud email, iMessage marks `is_from_me=1` because the
    sender is the same Apple ID, even though it physically came from a
    different device. We use `destination_caller_id` (which records the
    *sending handle*, not the device) to tell them apart:
      - Mac-sent (orb output): destination_caller_id ∈ MAC_SENDER_HANDLES
      - iPhone-sent (query):   destination_caller_id ∉ MAC_SENDER_HANDLES

    On first run, seeds the cursor at the current max ROWID so historical
    messages aren't replayed.
    """
    c = _open_chat_db()
    if c is None:
        return []
    try:
        last_seen = db.get_state(STATE_KEY)
        if last_seen is None:
            current = _max_rowid(c)
            db.set_state(STATE_KEY, str(current))
            log.info("inbox cursor initialized at ROWID %d", current)
            return []

        owner_placeholders = ",".join("?" * len(OWNER_HANDLES))
        mac_placeholders = ",".join("?" * len(MAC_SENDER_HANDLES)) if MAC_SENDER_HANDLES else "''"
        rows = c.execute(
            f"""SELECT m.ROWID AS rowid, m.text, m.date, h.id AS sender
               FROM message m
               JOIN handle h ON m.handle_id = h.ROWID
               WHERE m.ROWID > ?
                 AND m.text IS NOT NULL
                 AND m.text != ''
                 AND h.id IN ({owner_placeholders})
                 AND (
                   m.is_from_me = 0
                   OR (m.is_from_me = 1
                       AND COALESCE(m.destination_caller_id, '') NOT IN ({mac_placeholders}))
                 )
               ORDER BY m.ROWID ASC""",
            (int(last_seen), *OWNER_HANDLES, *MAC_SENDER_HANDLES),
        ).fetchall()

        msgs = [dict(r) for r in rows]
        # Advance cursor to current DB max so non-owner messages aren't
        # re-scanned on every poll.
        current = _max_rowid(c)
        if current > int(last_seen):
            db.set_state(STATE_KEY, str(current))
        return msgs
    finally:
        c.close()
