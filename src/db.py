import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY,
    audio_path TEXT UNIQUE NOT NULL,
    recorded_at TEXT NOT NULL,
    duration_sec REAL,
    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transcripts (
    recording_id INTEGER PRIMARY KEY REFERENCES recordings(id),
    text TEXT NOT NULL,
    language TEXT
);

CREATE TABLE IF NOT EXISTS acoustic (
    recording_id INTEGER PRIMARY KEY REFERENCES recordings(id),
    pitch_mean REAL,
    pitch_std REAL,
    energy_mean REAL,
    speaking_rate_wpm REAL,
    pause_ratio REAL
);

CREATE TABLE IF NOT EXISTS insights (
    recording_id INTEGER PRIMARY KEY REFERENCES recordings(id),
    summary TEXT,
    mood TEXT,
    themes TEXT,
    pattern TEXT,
    question TEXT,
    raw_response TEXT
);

CREATE TABLE IF NOT EXISTS philosophy_proposals (
    id INTEGER PRIMARY KEY,
    proposed_at TEXT NOT NULL DEFAULT (datetime('now')),
    section TEXT,
    proposal TEXT,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    sender TEXT,
    question TEXT NOT NULL,
    answer TEXT,
    raw_response TEXT
);

CREATE TABLE IF NOT EXISTS health_daily (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    steps INTEGER,
    active_energy_kcal REAL,
    exercise_minutes INTEGER,
    stand_hours INTEGER,
    resting_heart_rate REAL,
    hrv_ms REAL,
    respiratory_rate REAL,
    source TEXT DEFAULT 'health_export',
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workout_sessions (
    id INTEGER PRIMARY KEY,
    workout_type TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_min REAL,
    distance_km REAL,
    active_energy_kcal REAL,
    location_start_lat REAL,
    location_start_lon REAL,
    raw_json TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(start_time, workout_type)
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        # Columns added after initial schema — safe to run repeatedly
        for ddl in [
            "ALTER TABLE philosophy_proposals ADD COLUMN file TEXT",
            "ALTER TABLE philosophy_proposals ADD COLUMN recording_id INTEGER",
        ]:
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass


def already_processed(audio_path: Path) -> bool:
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM recordings WHERE audio_path = ?",
            (str(audio_path),),
        ).fetchone()
        return row is not None


def insert_recording(audio_path: Path, recorded_at: datetime, duration: float) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO recordings (audio_path, recorded_at, duration_sec) VALUES (?, ?, ?)",
            (str(audio_path), recorded_at.isoformat(), duration),
        )
        return cur.lastrowid


def save_transcript(rec_id: int, text: str, language: str):
    with conn() as c:
        c.execute(
            "INSERT INTO transcripts (recording_id, text, language) VALUES (?, ?, ?)",
            (rec_id, text, language),
        )


def save_acoustic(rec_id: int, features: dict):
    with conn() as c:
        c.execute(
            """INSERT INTO acoustic
               (recording_id, pitch_mean, pitch_std, energy_mean, speaking_rate_wpm, pause_ratio)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                rec_id,
                features.get("pitch_mean"),
                features.get("pitch_std"),
                features.get("energy_mean"),
                features.get("speaking_rate_wpm"),
                features.get("pause_ratio"),
            ),
        )


def save_insights(rec_id: int, parsed: dict, raw: str):
    with conn() as c:
        c.execute(
            """INSERT INTO insights
               (recording_id, summary, mood, themes, pattern, question, raw_response)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                rec_id,
                parsed.get("summary"),
                parsed.get("mood"),
                parsed.get("themes"),
                parsed.get("pattern"),
                parsed.get("question"),
                raw,
            ),
        )


def recent_insights(limit: int = 10):
    with conn() as c:
        rows = c.execute(
            """SELECT r.recorded_at, i.summary, i.mood, i.themes
               FROM insights i JOIN recordings r ON r.id = i.recording_id
               ORDER BY r.recorded_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_state(key: str) -> str | None:
    with conn() as c:
        row = c.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def save_query(question: str, answer: str, raw: str, sender: str | None = None) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO queries (sender, question, answer, raw_response) "
            "VALUES (?, ?, ?, ?)",
            (sender, question, answer, raw),
        )


def save_proposal(recording_id: int, file: str, section: str, proposal: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO philosophy_proposals (file, section, proposal, recording_id) "
            "VALUES (?, ?, ?, ?)",
            (file, section, proposal, recording_id),
        )


def upsert_health_daily(record: dict) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO health_daily
               (date, steps, active_energy_kcal, exercise_minutes, stand_hours,
                resting_heart_rate, hrv_ms, respiratory_rate, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 steps=excluded.steps,
                 active_energy_kcal=excluded.active_energy_kcal,
                 exercise_minutes=excluded.exercise_minutes,
                 stand_hours=excluded.stand_hours,
                 resting_heart_rate=excluded.resting_heart_rate,
                 hrv_ms=excluded.hrv_ms,
                 respiratory_rate=excluded.respiratory_rate,
                 source=excluded.source,
                 fetched_at=datetime('now')""",
            (
                record.get("date"),
                record.get("steps"),
                record.get("active_energy_kcal"),
                record.get("exercise_minutes"),
                record.get("stand_hours"),
                record.get("resting_heart_rate"),
                record.get("hrv_ms"),
                record.get("respiratory_rate"),
                record.get("source", "health_export"),
            ),
        )


def upsert_workout(workout: dict) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO workout_sessions
               (workout_type, start_time, end_time, duration_min, distance_km,
                active_energy_kcal, location_start_lat, location_start_lon, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(start_time, workout_type) DO UPDATE SET
                 end_time=excluded.end_time,
                 duration_min=excluded.duration_min,
                 distance_km=excluded.distance_km,
                 active_energy_kcal=excluded.active_energy_kcal,
                 location_start_lat=excluded.location_start_lat,
                 location_start_lon=excluded.location_start_lon,
                 raw_json=excluded.raw_json,
                 fetched_at=datetime('now')""",
            (
                workout.get("workout_type"),
                workout.get("start_time"),
                workout.get("end_time"),
                workout.get("duration_min"),
                workout.get("distance_km"),
                workout.get("active_energy_kcal"),
                workout.get("location_start_lat"),
                workout.get("location_start_lon"),
                workout.get("raw_json"),
            ),
        )


def recent_health(days: int = 7) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """SELECT date, steps, active_energy_kcal, exercise_minutes,
                      stand_hours, resting_heart_rate, hrv_ms, respiratory_rate
               FROM health_daily
               ORDER BY date DESC LIMIT ?""",
            (days,),
        ).fetchall()
        return [dict(r) for r in rows]


def recent_workouts(days: int = 7) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """SELECT workout_type, start_time, duration_min, distance_km,
                      active_energy_kcal
               FROM workout_sessions
               WHERE date(start_time) >= date('now', ?)
               ORDER BY start_time DESC""",
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]


def pending_proposals(limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """SELECT p.id, p.proposed_at, p.file, p.section, p.proposal,
                      r.recorded_at AS source_recorded_at
               FROM philosophy_proposals p
               LEFT JOIN recordings r ON r.id = p.recording_id
               WHERE p.status = 'pending'
               ORDER BY p.proposed_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def reflections_snapshot(limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """SELECT r.id, r.recorded_at, r.duration_sec,
                      t.text AS transcript,
                      i.summary, i.mood, i.themes, i.pattern, i.question,
                      a.speaking_rate_wpm, a.pause_ratio
               FROM recordings r
               LEFT JOIN transcripts t ON t.recording_id = r.id
               LEFT JOIN insights i    ON i.recording_id = r.id
               LEFT JOIN acoustic a    ON a.recording_id = r.id
               ORDER BY r.recorded_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
