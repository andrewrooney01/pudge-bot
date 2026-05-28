#!/usr/bin/env python3
"""One-shot ontology seeder.

Distills the user's accumulated reflections (insights, pending proposals,
inconsistencies, top-signal transcripts) into first-draft markdown for the
five primary ontology files. After seeding, the user reviews and edits in
Obsidian; the orb picks up edits on the next reflection.

The seed writes to gitignored personal files only. Nothing personal leaves
the machine except the Claude CLI prompt (same network posture as the
existing insights pipeline).

Usage:
    python scripts/seed_ontology.py --dry-run    # preview prompt + outputs
    python scripts/seed_ontology.py              # write files + mark proposals
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import ONTOLOGY_DIR, TEMPLATES_DIR, LENS_PATH, DB_PATH  # noqa: E402
from db import conn  # noqa: E402
from insights import _extract_json  # noqa: E402

SEED_TARGETS = ["values.md", "goals.md", "identity.md", "principles.md", "worldview.md"]
SKIP_FILES = {"inspirations.md"}  # user-authored; never overwrite
TRANSCRIPT_PROMPT_LIMIT = 5
CLAUDE_TIMEOUT = 600


def collect_db_material() -> dict:
    with conn() as c:
        insights = c.execute(
            """SELECT r.recorded_at, i.summary, i.mood, i.themes
               FROM insights i
               JOIN recordings r ON r.id = i.recording_id
               WHERE i.summary IS NOT NULL
               ORDER BY r.recorded_at ASC"""
        ).fetchall()
        proposals = c.execute(
            """SELECT id, file, section, proposal
               FROM philosophy_proposals
               WHERE status = 'pending'
               ORDER BY file, section, id"""
        ).fetchall()
        inconsistencies = c.execute(
            """SELECT text FROM inconsistencies
               WHERE status = 'open'
               ORDER BY surfaced_at DESC LIMIT 50"""
        ).fetchall()
        # Pick top-signal transcripts: most distinct themes tagged.
        top_transcripts = c.execute(
            """SELECT r.recorded_at, t.text, i.themes, i.mood
               FROM transcripts t
               JOIN recordings r ON r.id = t.recording_id
               JOIN insights i ON i.recording_id = r.id
               WHERE i.themes IS NOT NULL AND i.themes != ''
               ORDER BY length(i.themes) DESC, length(t.text) DESC
               LIMIT ?""",
            (TRANSCRIPT_PROMPT_LIMIT,),
        ).fetchall()

    return {
        "insights": [dict(r) for r in insights],
        "proposals": [dict(r) for r in proposals],
        "inconsistencies": [dict(r) for r in inconsistencies],
        "top_transcripts": [dict(r) for r in top_transcripts],
    }


def load_templates() -> dict:
    out = {}
    for fname in SEED_TARGETS:
        path = TEMPLATES_DIR / f"{fname}.example"
        if not path.exists():
            raise SystemExit(f"missing template: {path}")
        out[fname] = path.read_text()
    return out


def template_h2_headings(text: str) -> list[str]:
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def _heading_base(heading: str) -> str:
    """Strip date/year qualifiers so `Today — 2026-05-15` matches `Today — 2026-05-27`."""
    return re.split(r"\s+[—\-]|\s+\(", heading, maxsplit=1)[0].strip().lower()


def has_meaningful_content(path: Path) -> bool:
    """True if file has non-comment, non-blank content under any heading."""
    if not path.exists():
        return False
    in_html_comment = False
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if "<!--" in line:
            in_html_comment = True
        if in_html_comment:
            if "-->" in line:
                in_html_comment = False
            continue
        if line.startswith("#") or line.startswith("---"):
            continue
        # Skip the empty template `[Value]` placeholder bullets in values.md.
        if re.match(r"^\d+\.\s+\*\*\[Value\]\*\*\s*—\s*$", line):
            continue
        return True
    return False


def backup_existing(targets: list[Path]) -> Path | None:
    have_content = [p for p in targets if has_meaningful_content(p)]
    if not have_content:
        return None
    stamp = int(time.time())
    backup_dir = ONTOLOGY_DIR / f".seed-backup-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for p in have_content:
        shutil.copy2(p, backup_dir / p.name)
    return backup_dir


def build_prompt(material: dict, templates: dict) -> str:
    lens = LENS_PATH.read_text() if LENS_PATH.exists() else ""

    insights_block = "\n".join(
        f"- [{r['recorded_at'][:10]}] [{r['mood'] or '-'}] {r['summary']}"
        + (f"  ({r['themes']})" if r.get('themes') else "")
        for r in material["insights"]
    ) or "(none)"

    by_file: dict = {}
    for p in material["proposals"]:
        key = (p["file"] or "?", p["section"] or "?")
        by_file.setdefault(key, []).append(p["proposal"])
    proposals_block = "\n".join(
        f"### {f} / {sec}\n" + "\n".join(f"- {t}" for t in items)
        for (f, sec), items in sorted(by_file.items())
    ) or "(none)"

    inconsistencies_block = "\n".join(f"- {r['text']}" for r in material["inconsistencies"]) or "(none)"

    transcripts_block = "\n\n".join(
        f"### {r['recorded_at'][:10]} [{r['mood'] or '-'}] (themes: {r['themes']})\n{r['text']}"
        for r in material["top_transcripts"]
    ) or "(none)"

    templates_block = "\n\n".join(
        f"### Template: {fname}\n```\n{body}\n```"
        for fname, body in templates.items()
    )

    return f"""You are seeding a personal ontology from accumulated reflection data.

The user has 43 reflections collected over time. You will distill them into
first-draft markdown for five ontology files: values.md, goals.md, identity.md,
principles.md, worldview.md. The user will then review and curate in Obsidian.

## Lens (analytical framework)

{lens}

---

## Templates (match this structure exactly — same H1, same H2s)

{templates_block}

---

## Source material

### Insights (43 reflections, oldest first)

{insights_block}

### Pending proposals (already-stratified LLM drafts, grouped by file/section)

{proposals_block}

### Open inconsistencies (tensions worth surfacing in worldview/principles)

{inconsistencies_block}

### High-signal transcripts (top {TRANSCRIPT_PROMPT_LIMIT} by theme breadth, verbatim)

{transcripts_block}

---

## Instructions

Produce a single JSON object with exactly these five keys:
  "values.md", "goals.md", "identity.md", "principles.md", "worldview.md"

For each key, the value is the FULL markdown body of that file:
- Start with the template's H1 (e.g. `# Values`)
- Include every H2 from the template, in the same order
- Fill each H2 with bullet content distilled from the source material
- Keep the user's voice — mirror, don't invent. If the source doesn't support a claim, leave the section sparse rather than fabricate
- Quote-attribute non-obvious claims inline: `- Curiosity over certainty *(2024-11-03)*`
- For `goals.md` specifically: prepend the body (after the H1) with this exact line:
  `> *Draft seeded from reflections. Curate or replace in Obsidian.*`
  Goals are time-sensitive; the banner reminds the user to review aggressively.
- Do NOT include `<!-- comments -->` from the templates — those are author-time hints
- Do NOT use ``` code fences anywhere in the output bodies
- Do NOT add stray `---` separator lines except where the template has them

Respond with a single JSON object, no markdown fences, no preamble.
"""


def validate(parsed: dict, templates: dict) -> list[str]:
    errors = []
    for fname in SEED_TARGETS:
        if fname not in parsed:
            errors.append(f"{fname}: missing from response")
            continue
        body = parsed[fname]
        if not isinstance(body, str):
            errors.append(f"{fname}: not a string")
            continue
        expected_h1 = next((l for l in templates[fname].splitlines() if l.startswith("# ")), None)
        if expected_h1 and not body.lstrip().startswith(expected_h1):
            errors.append(f"{fname}: must start with `{expected_h1}`")
        expected_h2s = template_h2_headings(templates[fname])
        body_h2_bases = {_heading_base(l[3:].strip()) for l in body.splitlines() if l.startswith("## ")}
        for h2 in expected_h2s:
            if _heading_base(h2) not in body_h2_bases:
                errors.append(f"{fname}: missing H2 matching `## {h2}` (base `{_heading_base(h2)}`)")
        if "```" in body:
            errors.append(f"{fname}: contains a triple-backtick fence")
        if fname == "goals.md" and "*Draft seeded from reflections" not in body:
            errors.append("goals.md: missing required draft banner")
    return errors


def call_claude(prompt: str) -> str:
    print(f"  prompt size: {len(prompt):,} chars", file=sys.stderr)
    print("  calling claude CLI (this can take 1–3 min)…", file=sys.stderr)
    t0 = time.time()
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
    )
    elapsed = time.time() - t0
    print(f"  claude returned in {elapsed:.1f}s", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(f"claude CLI failed: {result.stderr}")
    return result.stdout


def mark_proposals_seeded() -> int:
    with conn() as c:
        cursor = c.execute(
            "UPDATE philosophy_proposals SET status = 'seeded' WHERE status = 'pending'"
        )
        return cursor.rowcount


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print prompt + outputs without writing")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")
    if shutil.which("claude") is None:
        raise SystemExit("claude CLI not on PATH")

    print("collecting DB material…", file=sys.stderr)
    material = collect_db_material()
    print(
        f"  {len(material['insights'])} insights, "
        f"{len(material['proposals'])} proposals, "
        f"{len(material['inconsistencies'])} inconsistencies, "
        f"{len(material['top_transcripts'])} top transcripts",
        file=sys.stderr,
    )

    templates = load_templates()
    targets = [ONTOLOGY_DIR / f for f in SEED_TARGETS]

    if args.dry_run:
        prompt = build_prompt(material, templates)
        print("\n========== DRY RUN — PROMPT ==========\n")
        print(prompt)
        print("\n========== DRY RUN — TARGETS ==========\n")
        for p in targets:
            status = "WOULD BACKUP" if has_meaningful_content(p) else "empty — will overwrite"
            print(f"  {p}: {status}")
        print(f"\n  proposals to mark 'seeded': {sum(1 for _ in material['proposals'])}")
        print("\n(no files written, no DB changes)")
        return 0

    backup = backup_existing(targets)
    if backup:
        print(f"backed up existing content → {backup}", file=sys.stderr)

    prompt = build_prompt(material, templates)
    raw = call_claude(prompt)

    try:
        parsed = _extract_json(raw)
    except Exception as e:
        Path("/tmp/seed_ontology_raw.txt").write_text(raw)
        raise SystemExit(f"failed to parse JSON: {e}. raw response saved to /tmp/seed_ontology_raw.txt")

    errors = validate(parsed, templates)
    if errors:
        Path("/tmp/seed_ontology_raw.txt").write_text(raw)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        raise SystemExit("validation failed; raw response saved to /tmp/seed_ontology_raw.txt")

    for fname in SEED_TARGETS:
        path = ONTOLOGY_DIR / fname
        body = parsed[fname]
        if not body.endswith("\n"):
            body += "\n"
        path.write_text(body)
        print(f"  wrote {path.relative_to(ROOT)} ({len(body):,} chars)", file=sys.stderr)

    n = mark_proposals_seeded()
    print(f"  marked {n} proposals as 'seeded'", file=sys.stderr)

    print("\n✓ seed complete. Open config/pudge-bot/ in Obsidian to review.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
