import json
import logging
import urllib.error
import urllib.parse
import urllib.request

import db
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger("orb.telegram")

API_BASE = "https://api.telegram.org/bot{token}/{method}"
STATE_KEY = "telegram_offset"
TIMEOUT_SECS = 30


def _api(method: str, params: dict) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (see config_local.py)")
    url = API_BASE.format(token=TELEGRAM_BOT_TOKEN, method=method)
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
        payload = json.loads(resp.read().decode())
    if not payload.get("ok"):
        raise RuntimeError(f"telegram {method} failed: {payload}")
    return payload["result"]


def send(message: str, chat_id: str = TELEGRAM_CHAT_ID) -> None:
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set (see config_local.py)")
    # Plain text only — the orb's output contains no markup, so we skip
    # parse_mode to avoid Telegram's markdown/HTML escaping pitfalls.
    _api("sendMessage", {"chat_id": chat_id, "text": message})


def poll() -> list[dict]:
    """Return new Telegram messages from the owner since the last poll.

    Uses getUpdates long-polling with a stored offset as the cursor. Only
    text messages from TELEGRAM_CHAT_ID are returned; the bot never sees its
    own outgoing messages, so there's no self-message filtering to do.

    On first run, drains any backlog and seeds the cursor so historical
    messages aren't replayed (mirrors the iMessage inbox poller).
    """
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set; skipping telegram poll")
        return []

    last_seen = db.get_state(STATE_KEY)
    params = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
    if last_seen is not None:
        params["offset"] = int(last_seen) + 1

    try:
        updates = _api("getUpdates", params)
    except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
        log.warning("telegram getUpdates failed: %s", e)
        return []

    if not updates:
        return []

    max_update_id = max(u["update_id"] for u in updates)

    if last_seen is None:
        db.set_state(STATE_KEY, str(max_update_id))
        log.info("telegram cursor initialized at update_id %d", max_update_id)
        return []

    msgs = []
    for u in updates:
        msg = u.get("message") or {}
        text = msg.get("text")
        chat = msg.get("chat") or {}
        if not text:
            continue
        if str(chat.get("id")) != str(TELEGRAM_CHAT_ID):
            continue
        sender = chat.get("username") or str(chat.get("id"))
        msgs.append({"rowid": u["update_id"], "text": text, "sender": sender})

    db.set_state(STATE_KEY, str(max_update_id))
    return msgs
