# the-orb

Personal reflection loop over iMessage. Record a voice note; get a sentiment-aware text back a few minutes later.

## Workflow

1. Record on iPhone via **Just Press Record**. Syncs to iCloud.
2. Within a few minutes, the orb texts back: mood, summary, themes, pattern, an open question, and acoustic signals (wpm, pause ratio).
3. Reply to that thread to ask ad-hoc questions — _"latest recording?"_, _"sentiment over the last three?"_ — answered in the same thread. _(in progress on `claude/inbound-query`)_

## Status

Proof of concept. Single user, runs on the user's Mac.

## Layout

- `src/` — pipeline code
- `config/` — launchd plists, lens prompt
- `data/`, `logs/` — gitignored
