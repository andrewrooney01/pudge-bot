# the orb

<p align="center">
  <img src="assets/orb.jpg" alt="the orb" width="600">
</p>

<p align="center">
  <em>A private oracle for your inner monologue. Think out loud. The orb thinks back.</em>
</p>

<p align="center">
  <a href="#use-cases">Use cases</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#setup">Setup</a>
</p>

---

The orb watches for new voice notes, transcribes them on-device, analyzes the acoustics, and texts you back within a minute — with mood, patterns, and one open question worth sitting with. Reply in the same thread to query your full reflection history. Over time it cross-references every voice note against a personal ontology you build (values, goals across every horizon, worldview, principles) and flags inconsistencies between who you say you are and what you actually said today.

It is a self-coaching system, a memory augment, and a small piece of personal infrastructure that runs quietly on your own machine.

---

## Use cases

**Daily reflection without writing.** Voice is faster and more honest than typing. Speak for two minutes on your walk to work; get back a structured read of what you actually said — mood, themes, a question — before you sit down at your desk.

**Pattern detection across weeks.** "Third time this week optionality vs. commitment has come up." The orb surfaces the loops you'd otherwise miss. Speaking rate, pause ratio, and pitch variance get tracked as quietly-rich signals about how you're actually doing — not just what you said.

**Decision support grounded in your own history.** *"Have I mentioned wanting to leave my job?"* *"What did I say last time I was considering a big move?"* — every answer comes from your own past reflections, not generic advice.

**Values-vs-behavior audit.** You write down what you value. The orb watches what you actually talk about. When the two diverge, it flags it and proposes an ontology update — forcing you to either change behavior or update the story you tell yourself.

**Long-horizon coherence.** Your goals file holds today, this week, this month, this year, 3-year, 10-year, 20-year, and 50-year horizons. Each daily reflection gets evaluated against all of them. Drift becomes visible.

---

## How it works

1. Record a voice note on your iPhone using **Just Press Record** (iCloud sync on)
2. Within ~60 seconds, you get a Telegram message back:

```
orb · focused

Talked through a work decision — tension between moving fast and trusting
the compounding logic. Leaning toward patience but second-guessing it.
Energy was high, pace deliberate.

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
- **Ad-hoc queries** — reply in the Telegram chat, get answers grounded in your history
- **Fully private** — runs on your Mac, data stays local, only the text prompt reaches the Claude API

---

## Status

Personal use. Single user, Apple Silicon Mac. Not packaged for general distribution — but straightforward to clone and run if you follow the setup below.

> **Privacy note:** Your Telegram bot tokens and chat id live in `src/config_local.py` (gitignored) — they never touch the repo.

> [!NOTE]
> The ontology files ship as tracked `*.md.example` templates. Your live `config/ontology/*.md` files — the ones you actually fill in — are gitignored, so your personal content stays on your machine and never gets pushed. Sync them across devices with Obsidian (see below), not git.

---

## Tech stack

```
iPhone (Just Press Record) → iCloud → Mac
  launchd polls every 60s
    → mlx-whisper  transcription (local, Apple Silicon)
    → librosa       acoustic features
    → Claude API    insights + ad-hoc queries
    → Telegram Bot API  message delivery + reply ingest
  SQLite            stores everything
```

---

## Setup

### What you need

- Apple Silicon Mac (M1 or later) — Whisper runs via MLX, which requires Apple Silicon
- iPhone with [Just Press Record](https://www.openplanetsoftware.com/just-press-record/) installed, iCloud sync enabled
- A Telegram account, and a bot created via [@BotFather](https://t.me/BotFather)
- [Claude Code](https://claude.ai/code) installed and authenticated (`claude` available in your terminal)
- Python 3.12+

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/the-orb.git
cd the-orb
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create your Telegram bot

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts. Copy the **bot token** it gives you (looks like `123456:ABC-DEF...`).
2. Open a chat with your new bot and **send it any message** — a bot can't message you until you've talked to it first.

### 3. Configure

```bash
cp src/config_local.py.example src/config_local.py
```

Find your **chat id** by running the setup helper with your token:

```bash
python src/telegram_setup.py <your-bot-token>
```

It long-polls for the message you just sent and prints your `chat_id`. Paste both into `src/config_local.py`:

```python
TELEGRAM_BOTS = {
    "pudge": {"token": "123456:ABC-DEF...", "chat_id": 987654321},
    # add more bots here — each is independent
}
```

`config_local.py` is gitignored — your bot tokens and chat id never touch the repo. (If a token ever leaks, send `/revoke` to @BotFather and swap in a fresh one.)

### 4. Fill in your ontology

Copy the templates to live files (the live `*.md` files are gitignored, so your content stays local):

```bash
for f in config/ontology/*.md.example; do cp -n "$f" "${f%.example}"; done
```

Then open the files in `config/ontology/` and fill in what you know today. Start with `values.md` and `goals.md` — even partial content activates inconsistency detection. You'll iterate over time.

**Read and edit them in Obsidian (optional).** `config/ontology/` doubles as an [Obsidian](https://obsidian.md) vault — in Obsidian, *Open folder as vault* and point it at `config/ontology/`. The orb reads these as plain markdown, so editing in Obsidian is safe. To use them on both Mac and iOS, turn on **Obsidian Sync with end-to-end encryption** — that syncs the vault between devices without going through git (keeping your personal content out of the repo). Obsidian's own `.obsidian/` config folder is gitignored.

### 5. Set up the launchd job

The plists ship as `*.plist.example` templates with a path placeholder. Copy them to live `*.plist` files (gitignored, per-machine) and swap the placeholder for your home directory:

```bash
cp config/com.theorb.daemon.plist.example config/com.theorb.daemon.plist
cp config/com.theorb.autopull.plist.example config/com.theorb.autopull.plist
sed -i '' "s|/Users/PLACEHOLDER|$HOME|g" config/com.theorb.daemon.plist config/com.theorb.autopull.plist
```

Then load it:

```bash
cp config/com.theorb.daemon.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.theorb.daemon.plist
```

The daemon runs continuously: a long-poll connection to Telegram (so chat
replies are sub-second) and a 60s background scan for new voice notes and
Apple Notes. launchd's `KeepAlive` restarts it if it ever crashes.

### 6. Grant Full Disk Access

The launchd job needs to read your iCloud voice-note files. (Delivery now goes
over the Telegram Bot API, so the Messages database and its Full Disk Access
requirement are no longer involved.)

**System Settings → Privacy & Security → Full Disk Access** — add the Python binary inside your venv:

```bash
# Find the path to add:
echo $(pwd)/.venv/bin/python
```

### 7. Test it

Send `/help` to your bot in Telegram — you should get a sub-second reply
listing the available commands. Then record a voice note in Just Press
Record; the background scanner picks it up within 60s.

Check logs if nothing arrives:

```bash
tail -f logs/orb.log
```

---

## Repo layout

```
src/          pipeline code
config/       launchd plists, lens prompt, ontology files
config/ontology/  (*.md.example = tracked templates; live *.md are gitignored, also an Obsidian vault)
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

---

## License

This repository is published for portfolio viewing only. All rights reserved. See [LICENSE](LICENSE).

For licensing inquiries: you@icloud.com
