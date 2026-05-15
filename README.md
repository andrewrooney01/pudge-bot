# the orb

Speak your thoughts on a walk. Get back a mirror.

The orb watches for new voice notes, transcribes them, analyzes the acoustics, and sends you an iMessage with mood, patterns, and a question — automatically, within a minute of recording. Reply in the same thread to query your history. Over time it cross-references your reflections against a personal ontology you build: your values, goals across every time horizon, worldview, and principles.

---

## How it works

1. Record a voice note on your iPhone using **Just Press Record** (iCloud sync on)
2. Within ~60 seconds, you get an iMessage back:

```
orb · focused

Talked through the decision to stay patient on the Hadrian opportunity.
Noted tension between wanting to move fast and trusting the compounding
logic. Energy was high, pace deliberate.

themes: professional, emotional
pattern: third time this week optionality vs. commitment has come up
q: what would it look like to fully commit, and what are you protecting by not?

⏱ 142 wpm · 18% pauses
```

3. Reply with any question and the orb answers from your full history:
   > *"what's been my dominant mood this month?"*
   > *"have I mentioned sleep in the last two weeks?"*

---

## Features

- **Transcription** — Whisper running locally on-device, no audio leaves your Mac
- **Acoustic analysis** — speaking rate, pitch variance, pause ratio on every note
- **Insights** — mood, summary, themes, cross-reflection patterns, one open question
- **Ontology** — a canonical self-model you fill in over time: identity, values, principles, worldview, goals (today → 50-year), and point-in-time artifacts (jobs, projects, phases)
- **Inconsistency detection** — flags when a reflection contradicts your stated values or goals; queues proposed ontology edits for your review
- **Ad-hoc queries** — reply to the iMessage thread, get answers grounded in your history
- **Fully private** — runs on your Mac, data stays local, only the text prompt reaches the Claude API

---

## Status

Personal use. Single user, Apple Silicon Mac. Not packaged for general distribution — but straightforward to clone and run if you follow the setup below.

---

## Tech stack

```
iPhone (Just Press Record) → iCloud → Mac
  launchd polls every 60s
    → mlx-whisper  transcription (local, Apple Silicon)
    → librosa       acoustic features
    → Claude API    insights + ad-hoc queries
    → osascript     iMessage delivery
  SQLite            stores everything
```

---

## Setup

### What you need

- Apple Silicon Mac (M1 or later) — Whisper runs via MLX, which requires Apple Silicon
- iPhone with [Just Press Record](https://www.openplanetsoftware.com/just-press-record/) installed, iCloud sync enabled
- [Claude Code](https://claude.ai/code) installed and authenticated (`claude` available in your terminal)
- Python 3.12+

### 1. Clone and install

```bash
git clone https://github.com/andrewrooney01/the-orb.git
cd the-orb
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Edit `src/config.py` — two lines to update:

```python
IMESSAGE_RECIPIENT = "+1XXXXXXXXXX"   # your phone number
OWNER_HANDLES = ("+1XXXXXXXXXX", "you@icloud.com")  # same number + Apple ID email
```

### 3. Fill in your ontology

Open the files in `config/ontology/` and fill in what you know today. Start with `values.md` and `goals.md` — even partial content activates inconsistency detection. You'll iterate over time.

### 4. Set up the launchd job

The plist in `config/com.theorb.watcher.plist` has hardcoded paths — update them to match your setup:

```bash
# Replace every occurrence of /Users/PLACEHOLDER with your home directory
sed -i '' "s|/Users/PLACEHOLDER|$HOME|g" config/com.theorb.watcher.plist
```

Then load it:

```bash
cp config/com.theorb.watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.theorb.watcher.plist
```

### 5. Grant Full Disk Access

The launchd job needs to read iCloud files and your Messages database.

**System Settings → Privacy & Security → Full Disk Access** — add the Python binary inside your venv:

```bash
# Find the path to add:
echo $(pwd)/.venv/bin/python
```

### 6. Test it

Record a voice note in Just Press Record. Wait 60–90 seconds. You should get an iMessage.

Check logs if nothing arrives:

```bash
tail -f logs/orb.log
```

---

## Repo layout

```
src/          pipeline code
config/       launchd plists, lens prompt, ontology files
config/ontology/
  identity.md       who you are, how you operate
  values.md         ranked values with explanations
  principles.md     rules you actually live by
  worldview.md      where the world is going, where you fit
  goals.md          today → 50-year horizon (same template throughout)
  inspirations.md   thinkers and works that shaped your thinking
  artifacts/        point-in-time snapshots (jobs, projects, phases)
data/         SQLite database (gitignored)
logs/         runtime logs (gitignored)
```
