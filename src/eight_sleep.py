"""Fetch sleep data from Eight Sleep API and persist to the orb database.

Credentials are read from config_local.py:
    EIGHT_SLEEP_EMAIL = "you@example.com"
    EIGHT_SLEEP_PASSWORD = "..."
    EIGHT_SLEEP_TIMEZONE = "America/New_York"   # optional, defaults to UTC

Run directly to sync the last two nights:
    python eight_sleep.py
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from pyeight.eight import EightSleep

import db
from config import EIGHT_SLEEP_EMAIL, EIGHT_SLEEP_PASSWORD, EIGHT_SLEEP_TIMEZONE

log = logging.getLogger(__name__)


def _seconds_of(breakdown: dict | None, stage: str) -> int | None:
    if not breakdown:
        return None
    return breakdown.get(stage)


def _extract_session(user, interval_num: int, fitness_num: int) -> dict | None:
    """Build a normalized dict from a pyeight user interval."""
    vals = user.last_values if interval_num == 1 else user.current_values
    fit = user.last_fitness_values if fitness_num == 1 else user.current_fitness_values

    session_dt: datetime | None = vals.get("date")
    if session_dt is None:
        return None

    session_date = session_dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    session_start = session_dt.isoformat()
    breakdown = vals.get("breakdown") or {}

    raw = {
        "values": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in vals.items()},
        "fitness": fit,
    }

    return {
        "session_date": session_date,
        "bed_side": user.side,
        "session_start": session_start,
        "sleep_score": vals.get("score"),
        "fitness_score": fit.get("score"),
        "heart_rate_avg": vals.get("heart_rate"),
        "resp_rate_avg": vals.get("resp_rate"),
        "toss_turns": vals.get("tnt"),
        "bed_temp_avg": vals.get("bed_temp"),
        "room_temp_avg": vals.get("room_temp"),
        "duration_light_sec": _seconds_of(breakdown, "light"),
        "duration_deep_sec": _seconds_of(breakdown, "deep"),
        "duration_rem_sec": _seconds_of(breakdown, "rem"),
        "duration_awake_sec": _seconds_of(breakdown, "awake"),
        "duration_score": fit.get("duration"),
        "wakeup_consistency_score": fit.get("wakeup"),
        "raw_json": json.dumps(raw),
    }


async def _fetch_and_store() -> list[dict]:
    eight = EightSleep(
        EIGHT_SLEEP_EMAIL,
        EIGHT_SLEEP_PASSWORD,
        EIGHT_SLEEP_TIMEZONE,
    )
    await eight.start()
    saved = []
    try:
        for user in eight.users:
            await user.update_user()

            for interval_num, fitness_num in [(1, 1), (0, 0)]:
                session = _extract_session(user, interval_num, fitness_num)
                if session and session.get("sleep_score") is not None:
                    db.upsert_sleep_session(session)
                    saved.append(session)
                    log.info(
                        "Saved sleep session %s (side=%s, score=%s)",
                        session["session_date"],
                        session["bed_side"],
                        session["sleep_score"],
                    )
    finally:
        await eight.stop()
    return saved


def sync() -> list[dict]:
    """Fetch recent Eight Sleep sessions and persist them. Returns saved records."""
    return asyncio.run(_fetch_and_store())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init()
    records = sync()
    print(f"Synced {len(records)} Eight Sleep session(s).")
    for r in records:
        total_sleep = sum(
            (r.get(k) or 0)
            for k in ("duration_light_sec", "duration_deep_sec", "duration_rem_sec")
        )
        print(
            f"  {r['session_date']} [{r['bed_side']}] "
            f"score={r['sleep_score']}  "
            f"sleep={total_sleep // 3600}h{(total_sleep % 3600) // 60}m  "
            f"hr={r['heart_rate_avg']:.0f}bpm" if r.get("heart_rate_avg") else
            f"  {r['session_date']} [{r['bed_side']}] score={r['sleep_score']}"
        )
