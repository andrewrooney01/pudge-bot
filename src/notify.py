"""Outgoing messages — sends to a Telegram bot.

Replaces the previous AppleScript / iMessage delivery path. Each call
identifies the target bot by name (default "pudge") and dispatches via
the Telegram Bot API.
"""
import logging

import bots
from telegram_client import TelegramClient

log = logging.getLogger("orb.notify")


def format_message(parsed: dict, acoustic: dict) -> str:
    """Render an insight dict + acoustic features as a chat message.

    Plain text; Telegram displays unicode and emoji natively. No markdown
    escaping pain.
    """
    rate = acoustic.get("speaking_rate_wpm")
    pause = acoustic.get("pause_ratio")
    rate_str = f"{rate:.0f} wpm" if rate is not None else "—"
    pause_str = f"{pause:.0%} pauses" if pause is not None else "—"

    return (
        f"orb · {parsed.get('mood', '?')}\n\n"
        f"{parsed.get('summary', '')}\n\n"
        f"themes: {parsed.get('themes', '—')}\n"
        f"pattern: {parsed.get('pattern', '—')}\n\n"
        f"q: {parsed.get('question', '—')}\n\n"
        f"⏱ {rate_str} · {pause_str}"
    )


def format_note_message(parsed: dict, title: str | None) -> str:
    """Same shape as format_message, but with a note footer instead of acoustics."""
    title_str = title if title else "untitled"
    return (
        f"orb · {parsed.get('mood', '?')}\n\n"
        f"{parsed.get('summary', '')}\n\n"
        f"themes: {parsed.get('themes', '—')}\n"
        f"pattern: {parsed.get('pattern', '—')}\n\n"
        f"q: {parsed.get('question', '—')}\n\n"
        f"📓 note · \"{title_str}\""
    )


def send(message: str, bot: str = "pudge") -> None:
    """Send `message` to the named bot's chat."""
    b = bots.get(bot)
    client = TelegramClient(b.token)
    client.send_message(b.chat_id, message)
    log.debug("sent to bot=%s chat_id=%s len=%d", b.name, b.chat_id, len(message))
