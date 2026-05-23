import os
from pathlib import Path

HOME = Path.home()

# launchd starts processes with a stripped PATH; ensure subprocesses
# (notably the `claude` CLI used by insights/query) can be resolved.
os.environ["PATH"] = os.pathsep.join([
    str(HOME / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    os.environ.get("PATH", ""),
])
PROJECT = HOME / "Projects" / "the-orb"

JPR_DIR = HOME / "Library" / "Mobile Documents" / \
    "iCloud~com~openplanetsoftware~just-press-record" / "Documents"

# Apple Notes ingest — orb picks up notes from this folder once they go quiet.
NOTES_FOLDER = "Ideas"
NOTE_QUIET_SECS = 3600  # ingest a note (or a fresh edit) once it's been untouched this long
NOTE_MIN_BODY_CHARS = 20  # skip stub notes (title-only or single-word) below this

DATA_DIR = PROJECT / "data"
LOGS_DIR = PROJECT / "logs"
CONFIG_DIR = PROJECT / "config"

DB_PATH = DATA_DIR / "orb.db"
LENS_PATH = CONFIG_DIR / "lens.md"
ONTOLOGY_DIR = CONFIG_DIR / "ontology"
ARTIFACTS_DIR = ONTOLOGY_DIR / "artifacts"

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

# Telegram bot registry. Each entry is {token, chat_id}. Override the whole
# dict in `config_local.py` (gitignored) — do not put real tokens here.
# Adding a new bot: drop a new entry into this dict; the rest of the pipeline
# picks it up via `bots.get("name")`.
TELEGRAM_BOTS: dict = {
    "pudge": {"token": "", "chat_id": 0},
}

try:
    from config_local import *  # noqa: F401, F403
except ImportError:
    pass

for d in (DATA_DIR, LOGS_DIR, CONFIG_DIR, ONTOLOGY_DIR, ARTIFACTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
