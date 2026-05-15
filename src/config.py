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

CHAT_DB_PATH = HOME / "Library" / "Messages" / "chat.db"

DATA_DIR = PROJECT / "data"
LOGS_DIR = PROJECT / "logs"
CONFIG_DIR = PROJECT / "config"

DB_PATH = DATA_DIR / "orb.db"
LENS_PATH = CONFIG_DIR / "lens.md"
ONTOLOGY_DIR = CONFIG_DIR / "ontology"
ARTIFACTS_DIR = ONTOLOGY_DIR / "artifacts"

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

IMESSAGE_RECIPIENT = "+1XXXXXXXXXX"

# Only messages from these iMessage handles are treated as questions for the orb.
OWNER_HANDLES = ("+1XXXXXXXXXX", "you@icloud.com")

for d in (DATA_DIR, LOGS_DIR, CONFIG_DIR, ONTOLOGY_DIR, ARTIFACTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
