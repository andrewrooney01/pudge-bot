import json
import re
import subprocess

import ontology
from config import LENS_PATH
from db import recent_insights


def _build_prompt(transcript: str, acoustic: dict) -> str:
    lens = LENS_PATH.read_text() if LENS_PATH.exists() else ""
    onto = ontology.load()

    history_rows = recent_insights(limit=7)
    history = "\n".join(
        f"- {r['recorded_at'][:10]} [{r['mood']}] {r['summary']}"
        for r in history_rows
    ) or "(no prior reflections yet)"

    wpm = acoustic.get("speaking_rate_wpm")
    std = acoustic.get("pitch_std")
    pause = acoustic.get("pause_ratio")
    acoustic_blurb = (
        f"speaking_rate={wpm:.0f} wpm, "
        f"pitch_std={std:.1f}, "
        f"pause_ratio={pause:.2f}"
        if wpm is not None and std is not None and pause is not None
        else "(acoustic features unavailable)"
    )

    onto_section = onto if onto else "(not yet populated)"

    return f"""{lens}

---

## Andrew's ontology (canonical self-model)
{onto_section}

---

## Recent reflections (most recent first)
{history}

---

## Today's reflection

Acoustic signal: {acoustic_blurb}

Transcript:
\"\"\"
{transcript}
\"\"\"

Respond with the JSON object now."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text[:200]}")
    return json.loads(match.group(0))


def generate(transcript: str, acoustic: dict) -> tuple[dict, str]:
    prompt = _build_prompt(transcript, acoustic)
    result = subprocess.run(
        ["claude", "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr}")
    raw = result.stdout
    parsed = _extract_json(raw)
    return parsed, raw
