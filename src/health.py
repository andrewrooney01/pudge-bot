"""Parse Apple Health JSON exports from iCloud Drive and persist to the orb database.

The expected source is the iOS Shortcut (see config/health_shortcut.md), which
writes one JSON file per day to iCloud Drive at:

    ~/Library/Mobile Documents/com~apple~CloudDocs/Health/YYYY-MM-DD.json

File format:
{
  "date": "2024-01-15",
  "exported_at": "2024-01-15T23:59:00",
  "metrics": {
    "steps": 8534,
    "active_energy_kcal": 423.5,
    "exercise_minutes": 42,
    "stand_hours": 10,
    "resting_heart_rate": 58.0,
    "hrv_ms": 45.2,
    "respiratory_rate": 14.5
  },
  "workouts": [
    {
      "type": "Walking",
      "start": "2024-01-15T08:00:00-07:00",
      "end": "2024-01-15T09:00:00-07:00",
      "duration_min": 60.0,
      "distance_km": 4.2,
      "active_energy_kcal": 280.0,
      "route": [
        {"lat": 37.7749, "lon": -122.4194, "timestamp": "2024-01-15T08:00:00-07:00"}
      ]
    }
  ]
}

Run directly to import all available JSON files:
    python health.py
"""
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import db
from config import HEALTH_EXPORT_DIR

log = logging.getLogger(__name__)


def _parse_and_store(path: Path) -> bool:
    """Parse one JSON file and upsert into the database. Returns True on success."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Skipping %s: %s", path.name, e)
        return False

    day = data.get("date")
    if not day:
        log.warning("No 'date' key in %s, skipping", path.name)
        return False

    metrics = data.get("metrics", {})
    db.upsert_health_daily(
        {
            "date": day,
            "steps": metrics.get("steps"),
            "active_energy_kcal": metrics.get("active_energy_kcal"),
            "exercise_minutes": metrics.get("exercise_minutes"),
            "stand_hours": metrics.get("stand_hours"),
            "resting_heart_rate": metrics.get("resting_heart_rate"),
            "hrv_ms": metrics.get("hrv_ms"),
            "respiratory_rate": metrics.get("respiratory_rate"),
            "source": "health_shortcut",
        }
    )
    log.info("Stored health daily for %s (%d steps)", day, metrics.get("steps") or 0)

    for wo in data.get("workouts", []):
        route = wo.get("route", [])
        first_point = route[0] if route else {}
        db.upsert_workout(
            {
                "workout_type": wo.get("type"),
                "start_time": wo.get("start"),
                "end_time": wo.get("end"),
                "duration_min": wo.get("duration_min"),
                "distance_km": wo.get("distance_km"),
                "active_energy_kcal": wo.get("active_energy_kcal"),
                "location_start_lat": first_point.get("lat"),
                "location_start_lon": first_point.get("lon"),
                "raw_json": json.dumps(wo),
            }
        )
        log.info(
            "Stored workout %s on %s (%.0f min)",
            wo.get("type"),
            day,
            wo.get("duration_min") or 0,
        )

    return True


def sync(days_back: int = 7) -> int:
    """Import health JSON files from iCloud Drive for the last N days.

    Returns the number of days successfully imported.
    """
    if not HEALTH_EXPORT_DIR.exists():
        log.warning(
            "Health export directory not found: %s\n"
            "See config/health_shortcut.md for setup instructions.",
            HEALTH_EXPORT_DIR,
        )
        return 0

    imported = 0
    today = date.today()
    for delta in range(days_back):
        day = today - timedelta(days=delta)
        path = HEALTH_EXPORT_DIR / f"{day.isoformat()}.json"
        if path.exists() and _parse_and_store(path):
            imported += 1

    return imported


def sync_all() -> int:
    """Import every JSON file found in HEALTH_EXPORT_DIR."""
    if not HEALTH_EXPORT_DIR.exists():
        log.warning(
            "Health export directory not found: %s\n"
            "See config/health_shortcut.md for setup instructions.",
            HEALTH_EXPORT_DIR,
        )
        return 0

    imported = 0
    for path in sorted(HEALTH_EXPORT_DIR.glob("????-??-??.json")):
        if _parse_and_store(path):
            imported += 1
    return imported


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    db.init()

    all_flag = "--all" in sys.argv
    count = sync_all() if all_flag else sync()
    print(f"Imported {count} day(s) of health data from {HEALTH_EXPORT_DIR}")
