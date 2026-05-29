"""Goal pulse — score each horizon in goals.md by recent surface area.

Reads the live ``goals.md`` (markdown horizon sections), extracts each
horizon's keyword fingerprint (proper-noun phrases + cross-referenced
entity names), and scores how often the user has actually talked about
each horizon in their recent reflections.

The point: long horizons don't surface naturally — they go dormant for
weeks unless something pulls them up. /horizons makes the dormancy
visible so the user can either change behavior or update the horizon.

No LLM calls — all FTS + entity-table lookups + in-memory aggregation.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

import db
from config import ONTOLOGY_DIR

_GOALS_PATH = ONTOLOGY_DIR / "goals.md"

# Natural cadence per horizon — how recently we'd expect the user to
# have surfaced it. Anything beyond this counts as drift and gets a flag.
_CADENCE_DAYS = {
    "today":     1,
    "this week": 7,
    "this month": 21,
    "this year": 90,
    "3 years":   180,
    "10 years":  365,
    "20 years":  365,
    "50 years":  365,
}

# Window we scan reflections in to compute mentions/last-seen.
_LOOKBACK_DAYS = 180

# Anything in this set is filtered out of the auto-extracted keyword fingerprint —
# common Title-cased words that aren't proper nouns and would over-match.
_STOPWORDS = {
    "i", "the", "a", "and", "or", "but", "if", "then", "so", "not",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "today", "tomorrow", "yesterday",
    "focus", "why", "success", "current state", "matters",
    "pending", "proposal",
}


def _normalize_horizon_name(raw: str) -> str:
    """Strip dates / parens from a heading so '## Today — 2026-05-27' → 'today'."""
    # Drop any em-dash-or-paren tail.
    name = re.split(r"\s+[—–-]\s+", raw, maxsplit=1)[0]
    name = re.sub(r"\s*\([^)]+\)\s*$", "", name)
    return name.strip().lower()


def parse_goals(text: str) -> "OrderedDict[str, dict]":
    """Parse goals.md into an ordered dict of horizon → {raw_heading, body}."""
    horizons: "OrderedDict[str, dict]" = OrderedDict()
    current_key: str | None = None
    current_raw: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current_key is not None:
                horizons[current_key] = {
                    "raw_heading": current_raw,
                    "body": "\n".join(current_lines).strip(),
                }
            current_raw = m.group(1).strip()
            current_key = _normalize_horizon_name(current_raw)
            current_lines = []
            continue
        if current_key is None:
            continue
        current_lines.append(line)
    if current_key is not None:
        horizons[current_key] = {
            "raw_heading": current_raw,
            "body": "\n".join(current_lines).strip(),
        }
    return horizons


# Multi-word Title Case ("Arena Physica", "Deployment Strategist"). Single-word
# capitalized tokens are too noisy — sentence-starts catch "Build", "Find", etc.
# Single-word names get in via the entity-table cross-reference instead.
_MULTIWORD_TITLE_RE = re.compile(
    r"\b("
    r"[A-Z][A-Za-z0-9]+"
    r"(?:\s+(?:of|the|and|for|in|to)\s+[A-Z][A-Za-z0-9]+|\s+[A-Z][A-Za-z0-9]+){1,3}"
    r")\b"
)

# All-caps acronyms like "FDE", "UP", "Argent" with 2+ chars and ≤6 chars.
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})\b")


def keyword_fingerprint(body: str, known_entity_names: set[str]) -> list[str]:
    """Extract the keyword set for one horizon.

    Three sources, de-duplicated and lowercased:
      a) Multi-word Title-cased proper-noun phrases ("Arena Physica")
      b) ALL-CAPS acronyms (FDE, UP)
      c) Any tracked entity name (any case) appearing as substring

    Single-word Title-cased tokens are intentionally excluded — they
    over-match sentence starts like "Build", "Find", "Current".
    """
    found: set[str] = set()
    for m in _MULTIWORD_TITLE_RE.finditer(body):
        phrase = m.group(1).strip()
        if phrase.lower() in _STOPWORDS:
            continue
        found.add(phrase.lower())
    for m in _ACRONYM_RE.finditer(body):
        token = m.group(1)
        if token.lower() in _STOPWORDS:
            continue
        found.add(token.lower())
    body_lower = body.lower()
    for ent in known_entity_names:
        if len(ent) < 3:
            continue
        if ent.lower() in _STOPWORDS:
            continue
        if ent.lower() in body_lower:
            found.add(ent.lower())
    return sorted(found)


def _load_known_entity_names() -> set[str]:
    """All distinct entity names already in the DB, for cross-reference."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT DISTINCT name FROM entity_mentions"
        ).fetchall()
        return {row["name"] for row in rows if row["name"]}


def score() -> list[dict]:
    """Compute the per-horizon scorecard. Pure read; no side effects."""
    if not _GOALS_PATH.exists():
        return []
    horizons = parse_goals(_GOALS_PATH.read_text())
    if not horizons:
        return []

    known_entities = _load_known_entity_names()
    fingerprints = {
        key: keyword_fingerprint(meta["body"], known_entities)
        for key, meta in horizons.items()
    }

    cutoff = (datetime.now() - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    end = (datetime.now() + timedelta(seconds=1)).isoformat()

    with db.conn() as c:
        reflections = c.execute(
            """SELECT r.id, r.recorded_at,
                      LOWER(COALESCE(t.text, '')) AS body,
                      LOWER(COALESCE(i.summary, '')) AS sum,
                      LOWER(COALESCE(i.themes, '')) AS themes
               FROM recordings r
               LEFT JOIN transcripts t ON t.recording_id = r.id
               LEFT JOIN insights i    ON i.recording_id = r.id
               WHERE r.recorded_at >= ? AND r.recorded_at < ?
               ORDER BY r.recorded_at DESC""",
            (cutoff, end),
        ).fetchall()
        reflections = [dict(r) for r in reflections]

    today = datetime.now().date()
    output: list[dict] = []
    for key, meta in horizons.items():
        fp = fingerprints[key]
        if not fp:
            output.append({
                "horizon": meta["raw_heading"],
                "key": key,
                "fingerprint": [],
                "mentions": 0,
                "last_seen": None,
                "days_since": None,
                "cadence_days": _CADENCE_DAYS.get(key, 365),
                "drift": False,
            })
            continue

        matched: list[dict] = []
        for r in reflections:
            blob = " ".join((r["body"], r["sum"], r["themes"]))
            if any(kw in blob for kw in fp):
                matched.append(r)

        last_seen = matched[0]["recorded_at"] if matched else None
        days_since = None
        if last_seen:
            try:
                days_since = (today - datetime.fromisoformat(last_seen).date()).days
            except ValueError:
                days_since = None

        cadence = _CADENCE_DAYS.get(key, 365)
        drift = (days_since is None) or (days_since > cadence)

        output.append({
            "horizon": meta["raw_heading"],
            "key": key,
            "fingerprint": fp,
            "mentions": len(matched),
            "last_seen": last_seen,
            "days_since": days_since,
            "cadence_days": cadence,
            "drift": drift,
        })
    return output


def render_for_telegram(rows: list[dict]) -> str:
    if not rows:
        return "no goals.md found, or no horizons parsed."

    lines = ["horizons · last 180d", ""]
    for r in rows:
        days = r["days_since"]
        if days is None:
            last_str = "never surfaced"
        elif days == 0:
            last_str = "today"
        else:
            last_str = f"{days}d ago"
        flag = " ⚠️" if r["drift"] else ""
        head = r["horizon"]
        # Trim parenthetical from heading for tighter rendering.
        head_short = re.sub(r"\s*\(.*\)$", "", head)
        lines.append(f"— {head_short} —")
        lines.append(f"  {r['mentions']:2d} mention{'s' if r['mentions']!=1 else ' '} · last {last_str}{flag}")
        if r["fingerprint"]:
            preview = ", ".join(r["fingerprint"][:4])
            if len(r["fingerprint"]) > 4:
                preview += f" (+{len(r['fingerprint']) - 4})"
            lines.append(f"  keys: {preview}")
        lines.append("")
    lines.append("⚠️ = mentioned less recently than the horizon's natural cadence")
    return "\n".join(lines).rstrip()
