# orb — product spec

> Living doc of what the orb _does_ for the user. Intentionally separate from
> the technical implementation so the plot stays clear.

## Concept

A personal reflection loop over iMessage. Speak a thought into your phone;
the orb mirrors it back with sentiment, patterns, and a question.

## Workflow (current)

1. Record a voice note on iPhone using **Just Press Record**. Recordings
   happen ad hoc — any time of day, no schedule.
2. Within a few minutes, the orb sends an iMessage back containing:
   - **Mood** (1–2 words)
   - **Summary** (2–3 sentences mirroring the reflection)
   - **Themes** (physical / emotional / mental / professional)
   - **Pattern** observed across recent reflections
   - **Open question** to sit with
   - **Acoustic signals** (speaking rate, pause ratio)

## Workflow (in progress — bi-directional)

Reply to any orb message in the same iMessage thread to ask ad-hoc questions
of your reflection history:

- _"what was my latest recording?"_
- _"give me my last three recordings, analyze the sentiment"_
- _"what patterns have you seen this week?"_

The orb answers in the same thread using the full stored history.

## Status

Proof of concept. Single user, single recipient. Runs on the user's Mac.

## Roadmap

- Weekly / periodic digest reports.
- Richer analytical queries over the reflection history.
- Evolving personal philosophy that updates from reflections over time.
- A "silence" mood — let the orb skip a reply when there's nothing useful to add.

## Non-goals

- Multi-user, accounts, web UI, mobile app.
- Cloud-hosted service.
- Replacing therapy, journaling apps, or daily standups.
