# the-orb

A personal reflection loop over iMessage. Speak a thought into your phone; the orb mirrors it back with sentiment, patterns, and a question.

## Workflow

1. Record a voice note on iPhone using **Just Press Record**. Recordings happen ad hoc — any time of day, no schedule.
2. Within a few minutes, the orb sends an iMessage back:
   - **Mood** (1–2 words)
   - **Summary** (2–3 sentences)
   - **Themes** (physical / emotional / mental / professional)
   - **Pattern** observed across recent reflections
   - **Open question** to sit with
   - **Acoustic signals** (speaking rate, pause ratio)

## Bi-directional (in progress)

Reply in the same thread to query your history:
- _"what was my latest recording?"_
- _"give me my last three, analyze the sentiment"_

The orb answers using the full stored history.

## Status

Proof of concept. Single user, runs on the user's Mac.

## Roadmap

- Weekly digest reports
- Richer ad-hoc queries
- Evolving personal philosophy built from reflections
- "Silence" mode — skip the reply when there's nothing useful to add

## Layout

- `src/` — pipeline code
- `config/` — launchd plists, lens prompt
- `data/`, `logs/` — gitignored
