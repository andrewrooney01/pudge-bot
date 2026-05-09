import errno
import shutil
import tempfile
import time
from pathlib import Path

import mlx_whisper

from config import WHISPER_MODEL

_ICLOUD_DIR = Path.home() / "Library" / "Mobile Documents"
_SYNC_RETRIES = 6
_SYNC_RETRY_DELAY = 5.0  # seconds; bird usually releases within 10-30s


def _icloud_safe_copy(src: Path, dst: Path) -> None:
    # Uses read/write instead of fcopyfile() to avoid iCloud's sync lock.
    #
    # Two distinct EDEADLK causes:
    #   1. Missing Full Disk Access — permanent failure; add the real Python
    #      binary (not the venv symlink) to System Settings → Privacy &
    #      Security → Full Disk Access.
    #   2. bird actively syncing the file — transient; retry until it yields.
    for attempt in range(_SYNC_RETRIES):
        try:
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)
            return
        except OSError as e:
            if e.errno != errno.EDEADLK:
                raise
            if attempt == _SYNC_RETRIES - 1:
                raise PermissionError(
                    f"iCloud sync lock on {src} did not release after "
                    f"{_SYNC_RETRIES} retries. If this is a new file, "
                    "wait longer. If it persists on old files, check Full "
                    "Disk Access for the Python binary in System Settings."
                ) from e
            time.sleep(_SYNC_RETRY_DELAY)


def _is_icloud_path(path: Path) -> bool:
    try:
        path.relative_to(_ICLOUD_DIR)
        return True
    except ValueError:
        return False


def transcribe(audio_path: Path) -> dict:
    with tempfile.NamedTemporaryFile(
        suffix=audio_path.suffix, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _icloud_safe_copy(audio_path, tmp_path)
        result = mlx_whisper.transcribe(
            str(tmp_path),
            path_or_hf_repo=WHISPER_MODEL,
            verbose=False,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "text": result["text"].strip(),
        "language": result.get("language", "en"),
        "segments": result.get("segments", []),
    }
