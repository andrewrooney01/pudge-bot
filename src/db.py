import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
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

CREATE TABLE IF NOT EXISTS inconsistencies (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id),
    text TEXT NOT NULL,
    surfaced_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS idx_inconsistencies_rec ON inconsistencies(recording_id);

-- One row per (reflection, entity mention). `slug` is the canonical
-- lookup key (lowercased + safe chars); `name` preserves the display form
-- as the user said it; `kind` is one of person/project/concept/decision.
CREATE TABLE IF NOT EXISTS entity_mentions (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id),
    kind TEXT NOT NULL,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    context TEXT,
    seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_rec  ON entity_mentions(recording_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_slug ON entity_mentions(kind, slug);
"""

# FTS5 mirror over transcripts.text. Kept in sync via triggers below. rowid
# matches recording_id so we can join back without a separate column.
#
# Bumped when the FTS schema/tokenizer changes — init() drops and rebuilds
# the virtual table when this disagrees with state.
FTS_VERSION = "2"
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    text,
    content='transcripts',
    content_rowid='recording_id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, text) VALUES (new.recording_id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, text)
    VALUES ('delete', old.recording_id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, text)
    VALUES ('delete', old.recording_id, old.text);
    INSERT INTO transcripts_fts(rowid, text) VALUES (new.recording_id, new.text);
END;
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
            "ALTER TABLE recordings ADD COLUMN source TEXT NOT NULL DEFAULT 'voice'",
            "ALTER TABLE recordings ADD COLUMN note_id TEXT",
            "ALTER TABLE recordings ADD COLUMN note_title TEXT",
            "ALTER TABLE recordings ADD COLUMN note_modified_at TEXT",
        ]:
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass

        _ensure_fts(c)
        _backfill_inconsistencies(c)


def _ensure_fts(c: sqlite3.Connection) -> None:
    """Create FTS if missing; rebuild if FTS_VERSION changed."""
    current = c.execute(
        "SELECT value FROM state WHERE key = 'fts_version'"
    ).fetchone()
    needs_rebuild = not current or current["value"] != FTS_VERSION
    if needs_rebuild:
        c.executescript(
            "DROP TRIGGER IF EXISTS transcripts_ai;"
            "DROP TRIGGER IF EXISTS transcripts_ad;"
            "DROP TRIGGER IF EXISTS transcripts_au;"
            "DROP TABLE IF EXISTS transcripts_fts;"
        )
    c.executescript(FTS_SCHEMA)
    row = c.execute("SELECT COUNT(*) AS n FROM transcripts_fts").fetchone()
    if not row or row["n"] == 0:
        c.execute(
            "INSERT INTO transcripts_fts(rowid, text) "
            "SELECT recording_id, text FROM transcripts"
        )
    c.execute(
        "INSERT INTO state (key, value) VALUES ('fts_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (FTS_VERSION,),
    )


def _backfill_inconsistencies(c: sqlite3.Connection) -> None:
    """Lift inconsistencies out of historical insights.raw_response JSON.

    Runs once — skipped if any rows already exist. After this, the ingest
    pipeline writes directly via save_inconsistencies.
    """
    row = c.execute("SELECT COUNT(*) AS n FROM inconsistencies").fetchone()
    if row and row["n"] > 0:
        return
    rows = c.execute(
        "SELECT recording_id, raw_response FROM insights "
        "WHERE raw_response IS NOT NULL AND raw_response != ''"
    ).fetchall()
    for r in rows:
        raw = r["raw_response"] or ""
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            continue
        items = parsed.get("inconsistencies") or []
        for item in items:
            if isinstance(item, str) and item.strip():
                c.execute(
                    "INSERT INTO inconsistencies (recording_id, text) VALUES (?, ?)",
                    (r["recording_id"], item.strip()),
                )


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


def already_processed_note(note_id: str, modified_at: str) -> bool:
    """A given (note_id, modified_at) snapshot is ingested at most once."""
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM recordings "
            "WHERE source = 'note' AND note_id = ? AND note_modified_at = ?",
            (note_id, modified_at),
        ).fetchone()
        return row is not None


def insert_note_reflection(
    note_id: str,
    title: str,
    modified_at: str,
    recorded_at: datetime,
) -> int:
    """Persist a note ingest as a row in recordings with source='note'.

    audio_path is synthetic (`note:<id>@<modified_at>`) so the existing
    UNIQUE NOT NULL constraint still holds without a schema migration.
    """
    synthetic_path = f"note:{note_id}@{modified_at}"
    with conn() as c:
        cur = c.execute(
            "INSERT INTO recordings "
            "(audio_path, recorded_at, source, note_id, note_title, note_modified_at) "
            "VALUES (?, ?, 'note', ?, ?, ?)",
            (synthetic_path, recorded_at.isoformat(), note_id, title, modified_at),
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


def save_inconsistencies(rec_id: int, items: list[str]) -> None:
    if not items:
        return
    with conn() as c:
        for item in items:
            if isinstance(item, str) and item.strip():
                c.execute(
                    "INSERT INTO inconsistencies (recording_id, text) VALUES (?, ?)",
                    (rec_id, item.strip()),
                )


# ---------------------------------------------------------------------------
# Entity mentions — populated from insights JSON, materialized into the
# vault by src/vault.py as one markdown file per (kind, slug) entity.
# ---------------------------------------------------------------------------

_ENTITY_KINDS = ("person", "project", "concept", "decision")


def entity_slug(name: str) -> str:
    """Stable filesystem-safe slug. Lowercased, spaces → '-', strip junk."""
    import re
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unnamed"


def save_entities(rec_id: int, items: list[dict]) -> list[dict]:
    """Persist entity mentions; return the cleaned list actually saved."""
    saved: list[dict] = []
    if not items:
        return saved
    with conn() as c:
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = (item.get("type") or "").strip().lower()
            name = (item.get("name") or "").strip()
            ctx = (item.get("context") or "").strip()
            if kind not in _ENTITY_KINDS or not name:
                continue
            slug = entity_slug(name)
            c.execute(
                "INSERT INTO entity_mentions (recording_id, kind, slug, name, context) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec_id, kind, slug, name, ctx),
            )
            saved.append({"kind": kind, "slug": slug, "name": name, "context": ctx})
    return saved


def entity_timeline(kind: str | None, slug: str, limit: int = 200) -> list[dict]:
    """Every mention of an entity, oldest first. `kind=None` searches across kinds."""
    sql = """SELECT em.kind, em.name, em.context, r.id AS recording_id,
                    r.recorded_at, r.source, r.note_title,
                    i.mood, i.summary
             FROM entity_mentions em
             JOIN recordings r ON r.id = em.recording_id
             LEFT JOIN insights i ON i.recording_id = r.id
             WHERE em.slug = ?"""
    args: list = [slug]
    if kind:
        sql += " AND em.kind = ?"
        args.append(kind)
    sql += " ORDER BY r.recorded_at ASC LIMIT ?"
    args.append(limit)
    with conn() as c:
        rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]


def entity_search(query: str, limit: int = 20) -> list[dict]:
    """Fuzzy entity lookup by name substring. Returns one row per distinct entity."""
    q = f"%{(query or '').strip().lower()}%"
    with conn() as c:
        rows = c.execute(
            """SELECT em.kind, em.slug,
                      MAX(em.name) AS name,
                      COUNT(*)     AS mentions,
                      MIN(r.recorded_at) AS first_seen,
                      MAX(r.recorded_at) AS last_seen
               FROM entity_mentions em
               JOIN recordings r ON r.id = em.recording_id
               WHERE LOWER(em.name) LIKE ? OR em.slug LIKE ?
               GROUP BY em.kind, em.slug
               ORDER BY mentions DESC, last_seen DESC
               LIMIT ?""",
            (q, q, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def entities_for_recording(rec_id: int) -> list[dict]:
    """All entities mentioned in a single reflection."""
    with conn() as c:
        rows = c.execute(
            "SELECT kind, slug, name, context FROM entity_mentions "
            "WHERE recording_id = ? ORDER BY id",
            (rec_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def recordings_without_entities() -> list[int]:
    """Recording ids whose transcript has never been run through entity extraction.

    Used by the backfill script. A recording with zero entities is treated as
    "never processed" — at worst this re-extracts for genuinely empty ones,
    which is cheap and idempotent (we wipe + re-insert per recording).
    """
    with conn() as c:
        rows = c.execute(
            """SELECT r.id
               FROM recordings r
               LEFT JOIN entity_mentions em ON em.recording_id = r.id
               WHERE em.id IS NULL
               ORDER BY r.recorded_at ASC"""
        ).fetchall()
        return [r["id"] for r in rows]


def clear_entities_for_recording(rec_id: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM entity_mentions WHERE recording_id = ?", (rec_id,))


def reflections_between(start: datetime, end: datetime) -> list[dict]:
    """Reflections with recorded_at in [start, end). Newest first."""
    with conn() as c:
        rows = c.execute(
            """SELECT r.id, r.recorded_at, r.source, r.note_title,
                      r.duration_sec,
                      i.summary, i.mood, i.themes, i.question,
                      a.speaking_rate_wpm
               FROM recordings r
               LEFT JOIN insights i ON i.recording_id = r.id
               LEFT JOIN acoustic a ON a.recording_id = r.id
               WHERE r.recorded_at >= ? AND r.recorded_at < ?
               ORDER BY r.recorded_at DESC""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [dict(r) for r in rows]


def overall_stats() -> dict:
    """Totals: reflections, total minutes, avg wpm, voice/note split."""
    with conn() as c:
        row = c.execute(
            """SELECT
                 COUNT(*)                                       AS total,
                 COALESCE(SUM(r.duration_sec), 0)               AS total_sec,
                 SUM(CASE WHEN r.source = 'voice' THEN 1 ELSE 0 END) AS voice_count,
                 SUM(CASE WHEN r.source = 'note'  THEN 1 ELSE 0 END) AS note_count,
                 MIN(r.recorded_at)                             AS first_at,
                 MAX(r.recorded_at)                             AS last_at
               FROM recordings r"""
        ).fetchone()
        wpm_row = c.execute(
            "SELECT AVG(speaking_rate_wpm) AS avg_wpm FROM acoustic "
            "WHERE speaking_rate_wpm IS NOT NULL"
        ).fetchone()
        return {
            **dict(row),
            "avg_wpm": wpm_row["avg_wpm"],
        }


def theme_stats() -> list[dict]:
    """Per-coverage-area count + most-recent recorded_at."""
    AREAS = ("physical", "emotional", "mental", "professional")
    with conn() as c:
        rows = c.execute(
            """SELECT i.themes, r.recorded_at
               FROM insights i JOIN recordings r ON r.id = i.recording_id
               WHERE i.themes IS NOT NULL AND i.themes != ''"""
        ).fetchall()
    counts = {a: 0 for a in AREAS}
    last_seen: dict[str, str] = {}
    for row in rows:
        themes = [t.strip().lower() for t in (row["themes"] or "").split(",")]
        for area in AREAS:
            if area in themes:
                counts[area] += 1
                if area not in last_seen or row["recorded_at"] > last_seen[area]:
                    last_seen[area] = row["recorded_at"]
    return [
        {"area": a, "count": counts[a], "last_seen": last_seen.get(a)}
        for a in AREAS
    ]


def mood_series(days: int = 14) -> list[dict]:
    """One row per day for the last `days` days: date, avg wpm, mood words.

    Days with multiple reflections collapse moods into a "/"-joined string.
    Days with no reflection appear with mood=None, wpm=None — caller decides
    how to render the gap.
    """
    cutoff = (datetime.now() - timedelta(days=days)).date()
    with conn() as c:
        rows = c.execute(
            """SELECT date(r.recorded_at) AS day,
                      GROUP_CONCAT(i.mood, '/') AS moods,
                      AVG(a.speaking_rate_wpm)  AS avg_wpm
               FROM recordings r
               LEFT JOIN insights i ON i.recording_id = r.id
               LEFT JOIN acoustic a ON a.recording_id = r.id
               WHERE date(r.recorded_at) >= ?
               GROUP BY date(r.recorded_at)
               ORDER BY day ASC""",
            (cutoff.isoformat(),),
        ).fetchall()
    by_day = {r["day"]: dict(r) for r in rows}
    out = []
    for i in range(days, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date().isoformat()
        if d in by_day:
            out.append(by_day[d])
        else:
            out.append({"day": d, "moods": None, "avg_wpm": None})
    return out


def search_transcripts(phrase: str, limit: int = 10) -> list[dict]:
    """FTS5 search — newest matches first. Returns id, date, summary, mood."""
    with conn() as c:
        rows = c.execute(
            """SELECT r.id, r.recorded_at, r.source, r.note_title,
                      i.summary, i.mood
               FROM transcripts_fts f
               JOIN recordings r  ON r.id = f.rowid
               LEFT JOIN insights i ON i.recording_id = r.id
               WHERE transcripts_fts MATCH ?
               ORDER BY r.recorded_at DESC
               LIMIT ?""",
            (phrase, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def snippet_transcripts(phrase: str, limit: int = 10) -> list[dict]:
    """FTS5 snippet() — returns text fragments around each match.

    Snippet window is ~30 tokens with ‹…› markers around the match.
    """
    with conn() as c:
        rows = c.execute(
            """SELECT r.id, r.recorded_at,
                      snippet(transcripts_fts, 0, '«', '»', '…', 16) AS frag
               FROM transcripts_fts f
               JOIN recordings r ON r.id = f.rowid
               WHERE transcripts_fts MATCH ?
               ORDER BY r.recorded_at DESC
               LIMIT ?""",
            (phrase, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def inconsistencies_recent(days: int = 30, limit: int = 50) -> list[dict]:
    """Inconsistencies surfaced for reflections recorded in the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with conn() as c:
        rows = c.execute(
            """SELECT inc.id, inc.text, inc.surfaced_at, r.recorded_at
               FROM inconsistencies inc
               JOIN recordings r ON r.id = inc.recording_id
               WHERE r.recorded_at >= ?
               ORDER BY r.recorded_at DESC
               LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def acoustic_baseline() -> dict:
    """Mean + std of speaking_rate_wpm, pitch_std, pause_ratio across all voice recordings."""
    with conn() as c:
        row = c.execute(
            """SELECT
                 AVG(speaking_rate_wpm) AS wpm_mean,
                 AVG(pitch_std)         AS pitch_std_mean,
                 AVG(pause_ratio)       AS pause_ratio_mean,
                 COUNT(*)               AS n
               FROM acoustic
               WHERE speaking_rate_wpm IS NOT NULL
                 AND pitch_std IS NOT NULL
                 AND pause_ratio IS NOT NULL"""
        ).fetchone()
        base = dict(row) if row else {}
        # sqlite has no STDEV — compute in Python.
        rows = c.execute(
            """SELECT speaking_rate_wpm, pitch_std, pause_ratio
               FROM acoustic
               WHERE speaking_rate_wpm IS NOT NULL
                 AND pitch_std IS NOT NULL
                 AND pause_ratio IS NOT NULL"""
        ).fetchall()
    n = base.get("n") or 0
    if n < 2:
        return {**base, "wpm_std": None, "pitch_std_std": None, "pause_ratio_std": None}

    def _std(values, mean):
        return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5

    wpms = [r["speaking_rate_wpm"] for r in rows]
    pitches = [r["pitch_std"] for r in rows]
    pauses = [r["pause_ratio"] for r in rows]
    return {
        **base,
        "wpm_std": _std(wpms, base["wpm_mean"]),
        "pitch_std_std": _std(pitches, base["pitch_std_mean"]),
        "pause_ratio_std": _std(pauses, base["pause_ratio_mean"]),
    }


def acoustic_in_window(days: int = 30) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with conn() as c:
        rows = c.execute(
            """SELECT r.id, r.recorded_at,
                      a.speaking_rate_wpm, a.pitch_std, a.pause_ratio,
                      i.summary, i.mood
               FROM acoustic a
               JOIN recordings r ON r.id = a.recording_id
               LEFT JOIN insights i ON i.recording_id = r.id
               WHERE r.recorded_at >= ?
                 AND a.speaking_rate_wpm IS NOT NULL
                 AND a.pitch_std IS NOT NULL
                 AND a.pause_ratio IS NOT NULL
               ORDER BY r.recorded_at DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def reflection_full(rec_id: int) -> dict | None:
    """Everything needed to replay a single reflection."""
    with conn() as c:
        row = c.execute(
            """SELECT r.id, r.recorded_at, r.source, r.note_title, r.duration_sec,
                      t.text AS transcript, t.language,
                      i.summary, i.mood, i.themes, i.pattern, i.question,
                      i.raw_response,
                      a.pitch_mean, a.pitch_std, a.energy_mean,
                      a.speaking_rate_wpm, a.pause_ratio
               FROM recordings r
               LEFT JOIN transcripts t ON t.recording_id = r.id
               LEFT JOIN insights i    ON i.recording_id = r.id
               LEFT JOIN acoustic a    ON a.recording_id = r.id
               WHERE r.id = ?""",
            (rec_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        inc_rows = c.execute(
            "SELECT text FROM inconsistencies WHERE recording_id = ? ORDER BY id",
            (rec_id,),
        ).fetchall()
        result["inconsistencies"] = [r["text"] for r in inc_rows]
        return result


def get_proposal(prop_id: int) -> dict | None:
    with conn() as c:
        row = c.execute(
            "SELECT id, file, section, proposal, status FROM philosophy_proposals "
            "WHERE id = ?",
            (prop_id,),
        ).fetchone()
        return dict(row) if row else None


def set_proposal_status(prop_id: int, status: str) -> bool:
    """Returns True if a row was updated."""
    with conn() as c:
        cur = c.execute(
            "UPDATE philosophy_proposals SET status = ? WHERE id = ?",
            (status, prop_id),
        )
        return cur.rowcount > 0


def reflections_snapshot(limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """SELECT r.id, r.recorded_at, r.duration_sec,
                      r.source, r.note_title,
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
