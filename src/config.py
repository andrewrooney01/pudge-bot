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
PROJECT = Path(__file__).resolve().parent.parent

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

# VAULT_DIR is the Obsidian-side root: ontology files at the top, plus
# auto-maintained journal/ and entities/ subtrees the orb writes into.
# Default picks config/pudge-bot/ if it's populated with a live identity.md
# (the user's actual vault), falling back to config/ontology/ for fresh
# clones. Override in config_local.py to point elsewhere.
def _default_vault() -> Path:
    candidate = CONFIG_DIR / "pudge-bot"
    if (candidate / "identity.md").exists():
        return candidate
    return CONFIG_DIR / "ontology"

VAULT_DIR = _default_vault()
ONTOLOGY_DIR = VAULT_DIR
ARTIFACTS_DIR = VAULT_DIR / "artifacts"
JOURNAL_DIR = VAULT_DIR / "journal"
ENTITIES_DIR = VAULT_DIR / "entities"

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

for d in (DATA_DIR, LOGS_DIR, CONFIG_DIR, VAULT_DIR, ARTIFACTS_DIR, JOURNAL_DIR, ENTITIES_DIR):
    d.mkdir(parents=True, exist_ok=True)
