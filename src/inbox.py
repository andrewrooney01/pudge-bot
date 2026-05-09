import logging
import sqlite3

import db
from config import CHAT_DB_PATH, OWNER_HANDLE

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
    """Return new received iMessages since the last poll.

    On first run, seeds the cursor at the current max ROWID so historical
    messages aren't replayed. Subsequent runs return only messages newer
    than the last seen ROWID, restricted to ones the user sent (is_from_me=0).
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

        rows = c.execute(
            """SELECT m.ROWID AS rowid, m.text, m.date, h.id AS sender
               FROM message m
               JOIN handle h ON m.handle_id = h.ROWID
               WHERE m.ROWID > ?
                 AND m.is_from_me = 0
                 AND m.text IS NOT NULL
                 AND m.text != ''
                 AND h.id = ?
               ORDER BY m.ROWID ASC""",
            (int(last_seen), OWNER_HANDLE),
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
