import shutil
import tempfile
from pathlib import Path

import mlx_whisper

from config import WHISPER_MODEL


def _icloud_safe_copy(src: Path, dst: Path) -> None:
    # macOS's shutil.copy2 → _fastcopy_fcopyfile path uses the fcopyfile()
    # syscall, which trips EDEADLK against iCloud's sync lock the same way
    # ffmpeg does. A plain read/write loop uses ordinary read() syscalls
    # and avoids the lock contention.
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)


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
