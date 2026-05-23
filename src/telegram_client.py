"""Telegram Bot API client.

Stateless HTTP wrapper around the public Telegram Bot API. Owns no
identity — pass the token when constructing. One client instance per bot.

Reference: https://core.telegram.org/bots/api
"""
import logging
from typing import Any

import requests

log = logging.getLogger("orb.telegram")


TELEGRAM_MAX_MESSAGE_CHARS = 4096


class TelegramError(RuntimeError):
    """Raised when the Telegram Bot API returns a non-OK response."""


class TelegramClient:
    def __init__(self, token: str, timeout: int = 30):
        if not token:
            raise ValueError("TelegramClient requires a non-empty bot token")
        self._token = token
        self._base = f"https://api.telegram.org/bot{token}"
        self._timeout = timeout

    # ---------- low-level ----------

    def _call(self, method: str, **params) -> Any:
        url = f"{self._base}/{method}"
        try:
            resp = requests.post(url, json=params, timeout=self._timeout)
        except requests.RequestException as e:
            raise TelegramError(f"network error calling {method}: {e}") from e

        try:
            body = resp.json()
        except ValueError as e:
            raise TelegramError(
                f"{method} returned non-JSON (status={resp.status_code}): {resp.text[:200]}"
            ) from e

        if not body.get("ok"):
            raise TelegramError(
                f"{method} failed: {body.get('description', 'unknown error')} "
                f"(error_code={body.get('error_code')})"
            )
        return body["result"]

    # ---------- public API ----------

    def get_me(self) -> dict:
        """Return the bot's own identity. Useful for validating tokens."""
        return self._call("getMe")

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        disable_notification: bool = False,
    ) -> dict:
        """Send a message. Splits oversized messages into multiple sends.

        Returns the last sent message's metadata (chat_id, message_id, ...).
        """
        if not text:
            raise ValueError("cannot send empty text")

        # Split into 4096-char chunks at paragraph boundaries when possible.
        chunks = _split_for_telegram(text)
        last = None
        for chunk in chunks:
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_notification": disable_notification,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            last = self._call("sendMessage", **payload)
        return last or {}

    def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 0,
        allowed_updates: list[str] | None = None,
    ) -> list[dict]:
        """Poll for new updates.

        `offset` skips updates with ID < offset. After processing, pass the
        last update_id + 1 as the next offset to ack and avoid replay.
        `timeout=0` is short-poll (returns immediately); >0 is long-poll.
        """
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        if allowed_updates is not None:
            params["allowed_updates"] = allowed_updates
        return self._call("getUpdates", **params)


def _split_for_telegram(text: str, limit: int = TELEGRAM_MAX_MESSAGE_CHARS) -> list[str]:
    """Split a long string into chunks that fit Telegram's per-message limit.

    Prefers to break on double-newlines, then single newlines, then spaces.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        # Try to split on a paragraph break first.
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit  # hard split as last resort
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
