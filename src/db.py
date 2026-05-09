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
