import errno
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import mlx_whisper

from config import WHISPER_MODEL

_ICLOUD_DIR = Path.home() / "Library" / "Mobile Documents"
_SYNC_RETRIES = 8
_SYNC_RETRY_DELAY = 5.0  # seconds; bird usually releases within 10-30s


def _brctl_download(src: Path) -> None:
    # Ask bird to fully materialise the file before we read it.
    # brctl download is idempotent — safe to call on already-local files.
    subprocess.run(["/usr/bin/brctl", "download", str(src)], capture_output=True)
    # Give bird a moment to release its write lock after the download
    time.sleep(2.0)


def _icloud_safe_copy(src: Path, dst: Path) -> None:
    # iCloud files get EDEADLK from the launchd daemon's process context when
    # bird holds a sync lock, even with Full Disk Access granted.
    # Force bird to fully download/commit the file first, then copy.
    _brctl_download(src)

    for attempt in range(_SYNC_RETRIES):
        try:
            result = subprocess.run(
                ["/bin/cp", str(src), str(dst)],
                capture_output=True,
            )
            if result.returncode == 0:
                return
            stderr = result.stderr.decode(errors="replace").strip()
            if "Resource deadlock" not in stderr:
                raise OSError(f"cp failed: {stderr}")
        except OSError:
            raise

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
                    f"{_SYNC_RETRIES} retries. Check Full Disk Access for "
                    "the Python binary in System Settings → Privacy & Security."
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
