import errno
import os
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import mlx_whisper

from config import WHISPER_MODEL

_ICLOUD_DIR = Path.home() / "Library" / "Mobile Documents"
_SYNC_TIMEOUT = 300.0  # max seconds to wait for iCloud to release the lock


def _wait_for_icloud_update(path: Path, timeout: float) -> None:
    # Open the file O_NONBLOCK so we don't block on the iCloud lock at open().
    # Then register a kqueue vnode watch — bird will trigger NOTE_WRITE or
    # NOTE_ATTRIB when it finishes syncing, waking us immediately.
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        time.sleep(min(timeout, 5))
        return
    try:
        kq = select.kqueue()
        ev = select.kevent(
            fd,
            filter=select.KQ_FILTER_VNODE,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_ATTRIB | select.KQ_NOTE_EXTEND,
        )
        kq.control([ev], 1, timeout)
        kq.close()
    finally:
        os.close(fd)


def _icloud_safe_copy(src: Path, dst: Path) -> None:
    # Background launchd daemons (ProcessType=Background) get EDEADLK when
    # Python's read() hits bird's iCloud sync lock, even with Full Disk Access
    # granted. Spawning /bin/cp as a child process sidesteps the lock because
    # the child inherits FDA but runs in a fresh process context that bird
    # doesn't hold a conflicting lock against.
    #
    # brctl download kicks iCloud to prioritize syncing this file. Then instead
    # of sleeping fixed intervals, we use kqueue to block until bird actually
    # writes or updates the file, so we retry the instant the lock releases.
    subprocess.run(["brctl", "download", str(src)], capture_output=True, timeout=10)

    deadline = time.monotonic() + _SYNC_TIMEOUT
    while True:
        result = subprocess.run(["/bin/cp", str(src), str(dst)], capture_output=True)
        if result.returncode == 0:
            return
        stderr = result.stderr.decode(errors="replace").strip()
        if "Resource deadlock" not in stderr:
            raise OSError(f"cp failed: {stderr}")

        try:
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)
            return
        except OSError as e:
            if e.errno != errno.EDEADLK:
                raise

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PermissionError(
                f"iCloud sync lock on {src} did not release after "
                f"{_SYNC_TIMEOUT:.0f}s."
            )
        _wait_for_icloud_update(src, timeout=min(remaining, 30))


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
