"""Bot registry.

Each bot is a (name, token, chat_id) triple. Configured in `config_local.py`
via the `TELEGRAM_BOTS` dict. Adding a new bot is a matter of dropping a
new entry into that dict and pointing the relevant pipeline code at its name.

    TELEGRAM_BOTS = {
        "pudge": {"token": "...", "chat_id": 12345},
        "habit": {"token": "...", "chat_id": 12345},
    }
"""
from __future__ import annotations

from dataclasses import dataclass

from config import TELEGRAM_BOTS


@dataclass(frozen=True)
class Bot:
    name: str
    token: str
    chat_id: int


def get(name: str) -> Bot:
    if name not in TELEGRAM_BOTS:
        raise KeyError(
            f"Bot {name!r} not found in TELEGRAM_BOTS. "
            f"Available: {sorted(TELEGRAM_BOTS.keys())}"
        )
    cfg = TELEGRAM_BOTS[name]
    token = cfg.get("token", "").strip()
    chat_id = cfg.get("chat_id")
    if not token:
        raise ValueError(f"Bot {name!r} has empty token; check config_local.py")
    if not chat_id:
        raise ValueError(f"Bot {name!r} has no chat_id; run telegram_setup.py")
    return Bot(name=name, token=token, chat_id=int(chat_id))


def all_bots() -> list[Bot]:
    return [get(name) for name in TELEGRAM_BOTS]
