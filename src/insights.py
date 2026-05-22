import json
import re
import subprocess

import ontology
from config import LENS_PATH
from db import recent_insights, recent_sleep, recent_health, recent_workouts


def _fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h{m:02d}m"


def _sleep_blurb(rows: list[dict]) -> str:
    if not rows:
        return "(no sleep data)"
    lines = []
    for r in rows[:3]:
        bd = _fmt_duration(
            (r.get("duration_light_sec") or 0)
            + (r.get("duration_deep_sec") or 0)
            + (r.get("duration_rem_sec") or 0)
        )
        deep = _fmt_duration(r.get("duration_deep_sec"))
        rem = _fmt_duration(r.get("duration_rem_sec"))
        score = r.get("sleep_score")
        hr = r.get("heart_rate_avg")
        line = (
            f"  {r['session_date']}: score={score}  sleep={bd}  "
            f"deep={deep}  rem={rem}"
        )
        if hr:
            line += f"  hr={hr:.0f}bpm"
        lines.append(line)
    return "\n".join(lines)


def _health_blurb(health_rows: list[dict], workout_rows: list[dict]) -> str:
    if not health_rows and not workout_rows:
        return "(no health data)"
    parts = []
    for r in health_rows[:3]:
        steps = r.get("steps")
        cal = r.get("active_energy_kcal")
        ex = r.get("exercise_minutes")
        hrv = r.get("hrv_ms")
        hr_rest = r.get("resting_heart_rate")
        line = f"  {r['date']}: steps={steps}"
        if cal:
            line += f"  active_cal={cal:.0f}"
        if ex:
            line += f"  exercise={ex}min"
        if hrv:
            line += f"  hrv={hrv:.0f}ms"
        if hr_rest:
            line += f"  rhr={hr_rest:.0f}bpm"
        parts.append(line)
    if workout_rows:
        parts.append("  Recent workouts:")
        for w in workout_rows[:5]:
            dist = f"  {w['distance_km']:.1f}km" if w.get("distance_km") else ""
            parts.append(
                f"    {w['start_time'][:10]} {w['workout_type']} "
                f"{w['duration_min']:.0f}min{dist}"
            )
    return "\n".join(parts) if parts else "(no health data)"


def _build_prompt(transcript: str, acoustic: dict) -> str:
    lens = LENS_PATH.read_text() if LENS_PATH.exists() else ""
    onto = ontology.load(include_books=False)

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
    sleep_section = _sleep_blurb(recent_sleep(days=7))
    health_section = _health_blurb(recent_health(days=7), recent_workouts(days=7))

    return f"""{lens}

---

## Andrew's ontology (canonical self-model)
{onto_section}

---

## Recent reflections (most recent first)
{history}

---

## Recent sleep (Eight Sleep, last 3 nights)
{sleep_section}

## Recent health & movement (last 3 days)
{health_section}

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
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr}")
    raw = result.stdout
    parsed = _extract_json(raw)
    return parsed, raw
