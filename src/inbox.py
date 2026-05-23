"""Incoming messages — polls Telegram for new replies.

Replaces the previous chat.db-based inbox. No more FDA, no more
self-Apple-ID heuristics, no more destination_caller_id parsing.

Each bot has its own update offset stored in the orb's state table.
On every poll, we ask Telegram for updates with id > last_offset, filter
to messages from the bot's owner (the configured chat_id), advance the
offset to the last update seen, and return the new messages.
"""
import logging

import bots
import db
from telegram_client import TelegramClient

log = logging.getLogger("orb.inbox")


def _state_key(bot_name: str) -> str:
    return f"telegram_offset_{bot_name}"


def poll(bot: str = "pudge") -> list[dict]:
    """Return new messages sent to the named bot since the last poll.

    Returned dicts have shape:
        {"update_id": int, "text": str, "sender": str, "bot": str}
    """
    b = bots.get(bot)
    client = TelegramClient(b.token)

    state_key = _state_key(bot)
    last_offset_str = db.get_state(state_key)
    offset = int(last_offset_str) + 1 if last_offset_str else None

    try:
        updates = client.get_updates(offset=offset, timeout=0)
    except Exception as e:
        log.warning("getUpdates failed for bot=%s: %s", bot, e)
        return []

    if not updates:
        return []

    messages = []
    max_seen_id = None
    for u in updates:
        max_seen_id = u["update_id"]
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue
        chat = msg.get("chat", {})
        if chat.get("id") != b.chat_id:
            # Messages from other chats are ignored (shouldn't happen with
            # a private bot, but defensive).
            continue
        text = msg.get("text")
        if not text:
            continue
        sender = (
            msg.get("from", {}).get("username")
            or str(msg.get("from", {}).get("id"))
            or "unknown"
        )
        messages.append({
            "update_id": u["update_id"],
            "text": text,
            "sender": sender,
            "bot": bot,
        })

    # Advance the cursor past everything Telegram returned, even non-message
    # updates, so we don't re-fetch them on the next poll.
    if max_seen_id is not None:
        db.set_state(state_key, str(max_seen_id))

    return messages


def poll_all() -> list[dict]:
    """Poll every configured bot. Returned messages carry their `bot` name."""
    out = []
    for b in bots.all_bots():
        out.extend(poll(b.name))
    return out
