import shutil
import tempfile
from pathlib import Path

import mlx_whisper

from config import WHISPER_MODEL


def transcribe(audio_path: Path) -> dict:
    # Files in iCloud Drive can fail ffmpeg's open() with EDEADLK
    # ("Resource deadlock avoided") while iCloud holds a sync lock, and
    # may still be a .icloud placeholder. Copying out forces materialization
    # and breaks the lock contention.
    with tempfile.NamedTemporaryFile(
        suffix=audio_path.suffix, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        shutil.copy2(audio_path, tmp_path)
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
