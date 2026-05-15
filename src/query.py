import json
import subprocess

import ontology
from config import LENS_PATH
from db import reflections_snapshot


def _build_prompt(question: str) -> str:
    lens = LENS_PATH.read_text() if LENS_PATH.exists() else ""
    onto = ontology.load()
    snapshot = reflections_snapshot(limit=20)

    onto_section = onto if onto else "(not yet populated)"

    return f"""You are the orb, answering an ad-hoc question from Andrew over iMessage.
The orb's lens, Andrew's ontology (canonical self-model), and a snapshot of recent
reflections are below. Use them to answer truthfully and concisely.

## Lens

{lens}

---

## Andrew's ontology
{onto_section}

---

## Recent reflections (most recent first, as JSON)

{json.dumps(snapshot, indent=2, default=str)}

---

## Andrew's question

\"\"\"
{question}
\"\"\"

Respond with a plain-text iMessage reply. No JSON, no code blocks, no preamble.
Keep it under 600 characters. If the data above doesn't contain what's needed
to answer, say so plainly rather than guessing."""


def answer(question: str) -> tuple[str, str]:
    prompt = _build_prompt(question)
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr}")
    raw = result.stdout
    return raw.strip(), raw
