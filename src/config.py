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

# Eight Sleep — override in src/config_local.py (gitignored)
EIGHT_SLEEP_EMAIL = ""
EIGHT_SLEEP_PASSWORD = ""
EIGHT_SLEEP_TIMEZONE = "America/New_York"

# Apple Health export directory — iOS Shortcut writes YYYY-MM-DD.json files here.
# See config/health_shortcut.md for setup. Override in config_local.py if needed.
HEALTH_EXPORT_DIR = HOME / "Library" / "Mobile Documents" / \
    "com~apple~CloudDocs" / "Health"

# Personal values — override in src/config_local.py (gitignored)
IMESSAGE_RECIPIENT = "+1XXXXXXXXXX"
OWNER_HANDLES = ("+1XXXXXXXXXX",)

# Apple ID handle to send iMessages FROM. None = use first available iMessage
# service (default macOS behavior, may flip between handles). Set to a specific
# handle (e.g. "pudgebot@icloud.com") to lock in a consistent sender identity.
IMESSAGE_SENDER = None

try:
    from config_local import *  # noqa: F401, F403
except ImportError:
    pass

for d in (DATA_DIR, LOGS_DIR, CONFIG_DIR, ONTOLOGY_DIR, ARTIFACTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
