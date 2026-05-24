"""Slash-command router for the orb's Telegram surface (pudge bot).

Any reply starting with `/` is dispatched here. Tier 1 commands are pure
DB reads + ontology writes — fast, deterministic, no LLM. Tier 2/3
commands land in later PRs.

The router returns the reply text. `None` means "not a command — fall
through to the free-form query path in orb.answer_question".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import db
from config import ONTOLOGY_DIR

log = logging.getLogger("orb.commands")

MAX_REPLY_CHARS = 3500  # Telegram allows 4096; keep margin for safety.
SPARK = "▁▂▃▄▅▆▇█"
COVERAGE_AREAS = ("physical", "emotional", "mental", "professional")


def dispatch(text: str) -> str | None:
    """Route a Telegram message. Returns the reply, or None if not a command."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return None

    head, _, rest = text.partition(" ")
    cmd = head[1:].lower()
    arg = rest.strip()

    handler = _ROUTES.get(cmd)
    if handler is None:
        return f"unknown command: /{cmd}\ntry /help"
    try:
        reply = handler(arg)
    except Exception as e:
        log.exception("command /%s failed", cmd)
        return f"/{cmd} failed: {e}"
    if reply and len(reply) > MAX_REPLY_CHARS:
        reply = reply[:MAX_REPLY_CHARS - 20] + "\n… (truncated)"
    return reply or "(no output)"


# ---------------------------------------------------------------------------
# Window commands: /today /week /month
# ---------------------------------------------------------------------------

def _first_sentence(text: str, hard_cap: int = 140) -> str:
    """First sentence of `text`, capped. Keeps window/search views scannable."""
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return ""
    for sep in (". ", "? ", "! "):
        idx = text.find(sep)
        if 0 < idx < hard_cap:
            return text[: idx + 1].strip()
    if len(text) <= hard_cap:
        return text
    return text[:hard_cap].rstrip() + "…"


def _window(days: int, header: str, empty_msg: str) -> str:
    now = datetime.now()
    if days == 0:  # /today = since midnight
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=days)
    end = now + timedelta(seconds=1)
    rows = db.reflections_between(start, end)
    if not rows:
        return empty_msg

    lines = [f"{header} · {len(rows)} reflection{'s' if len(rows) != 1 else ''}", ""]
    current_day = None
    for r in rows:
        day = r["recorded_at"][:10]
        if day != current_day:
            if current_day is not None:
                lines.append("")
            lines.append(f"— {day} —")
            current_day = day
        hhmm = r["recorded_at"][11:16]
        mood = r["mood"] or "?"
        summary = _first_sentence(r["summary"] or "")
        src = "📓 " if r["source"] == "note" else ""
        lines.append(f"{hhmm} · {src}{mood}")
        if summary:
            lines.append(f"  {summary}")
    return "\n".join(lines)


def cmd_today(_arg: str) -> str:
    return _window(0, "today", "no reflections today.")


def cmd_week(_arg: str) -> str:
    return _window(7, "last 7 days", "no reflections this week.")


def cmd_month(_arg: str) -> str:
    return _window(30, "last 30 days", "no reflections this month.")


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

def cmd_stats(_arg: str) -> str:
    s = db.overall_stats()
    total = s["total"] or 0
    if total == 0:
        return "no reflections yet."
    minutes = (s["total_sec"] or 0) / 60
    avg_wpm = s["avg_wpm"]
    first = (s["first_at"] or "")[:10]
    last = (s["last_at"] or "")[:10]
    today = datetime.now().date().isoformat()
    last_disp = "today" if last == today else last
    return (
        "the orb · stats\n\n"
        f"{total} reflections ({s['voice_count'] or 0} voice, {s['note_count'] or 0} notes)\n"
        f"{minutes:.0f} minutes spoken total\n"
        f"avg {avg_wpm:.0f} wpm\n\n"
        f"first: {first}\n"
        f"last:  {last_disp}"
    )


# ---------------------------------------------------------------------------
# /themes (with last-touched, folds in /silent)
# ---------------------------------------------------------------------------

def cmd_themes(_arg: str) -> str:
    stats = db.theme_stats()
    today = datetime.now().date()
    lines = ["coverage by area", ""]
    for s in stats:
        if s["last_seen"]:
            last_date = datetime.fromisoformat(s["last_seen"]).date()
            delta = (today - last_date).days
            last_str = "today" if delta == 0 else f"{delta}d ago"
        else:
            last_str = "never"
        flag = "  ⚠️" if s["last_seen"] is None or (today - datetime.fromisoformat(s["last_seen"]).date()).days > 7 else ""
        lines.append(f"  {s['area']:13s} {s['count']:3d}   last {last_str}{flag}")
    lines.append("")
    lines.append("⚠️ = dormant >7 days")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /mood
# ---------------------------------------------------------------------------

def cmd_mood(_arg: str) -> str:
    days = 14
    series = db.mood_series(days)
    wpms = [d["avg_wpm"] for d in series if d["avg_wpm"] is not None]
    if not wpms:
        return "no mood data yet — record a few reflections first."

    lo, hi = min(wpms), max(wpms)
    span = hi - lo or 1

    def bar(v):
        if v is None:
            return "·"
        idx = int(round((v - lo) / span * (len(SPARK) - 1)))
        return SPARK[max(0, min(len(SPARK) - 1, idx))]

    spark = "".join(bar(d["avg_wpm"]) for d in series)
    avg = sum(wpms) / len(wpms)

    lines = [f"mood · last {days} days", "", f"wpm  {spark}  (avg {avg:.0f})", ""]
    for d in series[-7:]:  # show per-day moods for last 7 to keep it scannable
        day_dt = datetime.fromisoformat(d["day"])
        dow = day_dt.strftime("%a").lower()
        if d["moods"]:
            uniq = []
            for m in d["moods"].split("/"):
                m = m.strip()
                if m and m not in uniq:
                    uniq.append(m)
            mood = ", ".join(uniq[:2])
            if len(uniq) > 2:
                mood += f" (+{len(uniq) - 2})"
        else:
            mood = "—"
        lines.append(f"  {dow} {d['day'][5:]}  {mood}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /search /snippets
# ---------------------------------------------------------------------------

def cmd_search(arg: str) -> str:
    if not arg:
        return "usage: /search <phrase>"
    rows = db.search_transcripts(arg, limit=10)
    if not rows:
        return f'no matches for "{arg}".'
    lines = [f'search "{arg}" · {len(rows)} result{"s" if len(rows) != 1 else ""}', ""]
    for r in rows:
        date = r["recorded_at"][:10]
        mood = r["mood"] or "—"
        summary = _first_sentence(r["summary"] or "(no summary)")
        src = "📓 " if r["source"] == "note" else ""
        lines.append(f"[{date}] {src}{mood}")
        lines.append(f"  {summary}")
    return "\n".join(lines)


def cmd_snippets(arg: str) -> str:
    if not arg:
        return "usage: /snippets <phrase>"
    rows = db.snippet_transcripts(arg, limit=10)
    if not rows:
        return f'no matches for "{arg}".'
    lines = [f'snippets "{arg}" · {len(rows)} hit{"s" if len(rows) != 1 else ""}', ""]
    for r in rows:
        date = r["recorded_at"][:10]
        lines.append(f"[{date}] {r['frag']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /proposals /accept /dismiss
# ---------------------------------------------------------------------------

def cmd_proposals(_arg: str) -> str:
    rows = db.pending_proposals(limit=20)
    if not rows:
        return "no pending proposals."
    lines = [f"pending proposals · {len(rows)}", ""]
    for r in rows:
        file = r["file"] or "?"
        section = r["section"] or "?"
        text = (r["proposal"] or "").replace("\n", " ")
        lines.append(f"#{r['id']} {file} / {section}")
        lines.append(f"  {text}")
        lines.append("")
    lines.append("reply /accept <id> or /dismiss <id>")
    return "\n".join(lines)


def cmd_accept(arg: str) -> str:
    if not arg.isdigit():
        return "usage: /accept <id>"
    prop_id = int(arg)
    prop = db.get_proposal(prop_id)
    if not prop:
        return f"no proposal #{prop_id}."
    if prop["status"] != "pending":
        return f"#{prop_id} is already {prop['status']}."

    file = (prop["file"] or "").strip()
    section = (prop["section"] or "").strip()
    text = (prop["proposal"] or "").strip()
    if not file or not text:
        return f"#{prop_id} is incomplete (missing file or text)."

    target = ONTOLOGY_DIR / file
    if not target.exists():
        return f"ontology file {file!r} does not exist."

    applied = _append_to_ontology(target, section, text)
    db.set_proposal_status(prop_id, "accepted")
    log.info("accepted proposal #%d into %s/%s", prop_id, file, section)
    return (
        f"✓ accepted #{prop_id}\n"
        f"appended to {file} / {section or '(end)'}:\n"
        f'  "{text}"\n\n'
        f"{applied}"
    )


def cmd_dismiss(arg: str) -> str:
    if not arg.isdigit():
        return "usage: /dismiss <id>"
    prop_id = int(arg)
    prop = db.get_proposal(prop_id)
    if not prop:
        return f"no proposal #{prop_id}."
    if prop["status"] != "pending":
        return f"#{prop_id} is already {prop['status']}."
    db.set_proposal_status(prop_id, "dismissed")
    log.info("dismissed proposal #%d", prop_id)
    return f"✓ dismissed #{prop_id}"


def _append_to_ontology(path, section: str, text: str) -> str:
    """Append `text` as a bullet under the named section, or add the section.

    Returns a short human-readable note about where it landed.
    """
    body = path.read_text()
    bullet = f"- {text}"
    if section:
        # Look for a markdown heading whose text matches the section (case-insensitive).
        heading_idx = -1
        heading_level = 0
        lines = body.splitlines()
        for i, line in enumerate(lines):
            stripped = line.lstrip("#").strip()
            if line.startswith("#") and stripped.lower() == section.lower():
                heading_idx = i
                heading_level = len(line) - len(line.lstrip("#"))
                break
        if heading_idx >= 0:
            # Find the end of this section (next heading at same-or-higher level, or EOF).
            insert_at = len(lines)
            for j in range(heading_idx + 1, len(lines)):
                if lines[j].startswith("#"):
                    level = len(lines[j]) - len(lines[j].lstrip("#"))
                    if level <= heading_level:
                        insert_at = j
                        break
            # Insert at end of section, preserving a blank line before next heading.
            while insert_at > heading_idx + 1 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            lines.insert(insert_at, bullet)
            path.write_text("\n".join(lines) + ("\n" if body.endswith("\n") else ""))
            return f"(inserted under existing ## {section})"

    # No section, or section not found — append at end with a new heading.
    suffix = ""
    if not body.endswith("\n"):
        suffix += "\n"
    if section:
        suffix += f"\n## {section}\n\n{bullet}\n"
        note = f"(created new ## {section} at end)"
    else:
        suffix += f"\n{bullet}\n"
        note = "(appended at end)"
    path.write_text(body + suffix)
    return note


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

def cmd_help(_arg: str) -> str:
    return (
        "the orb · commands\n\n"
        "— now —\n"
        "/today        reflections from today\n"
        "/week         last 7 days, grouped\n"
        "/month        last 30 days\n"
        "/stats        totals: count, minutes, wpm\n"
        "/themes       coverage tally + last touched\n"
        "/mood         14-day mood + wpm sparkline\n"
        "/search X     transcript hits for X\n"
        "/snippets X   verbatim fragments around X\n"
        "/proposals    pending ontology proposals\n"
        "/accept N     apply proposal N\n"
        "/dismiss N    drop proposal N\n"
        "/help         this list\n\n"
        "— coming —\n"
        "/digest /drift /loops /contradict\n"
        "/anomaly /replay\n\n"
        "anything not starting with / is a free-form question."
    )


_ROUTES = {
    "today": cmd_today,
    "week": cmd_week,
    "month": cmd_month,
    "stats": cmd_stats,
    "themes": cmd_themes,
    "mood": cmd_mood,
    "search": cmd_search,
    "snippets": cmd_snippets,
    "proposals": cmd_proposals,
    "accept": cmd_accept,
    "dismiss": cmd_dismiss,
    "help": cmd_help,
}
