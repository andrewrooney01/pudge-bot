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
PHILOSOPHY_PATH = PROJECT / "philosophy.md"
LENS_PATH = CONFIG_DIR / "lens.md"

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

IMESSAGE_RECIPIENT = "you@icloud.com"

for d in (DATA_DIR, LOGS_DIR, CONFIG_DIR):
    d.mkdir(parents=True, exist_ok=True)
