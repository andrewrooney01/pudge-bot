from pathlib import Path

import mlx_whisper

from config import WHISPER_MODEL


def transcribe(audio_path: Path) -> dict:
    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=WHISPER_MODEL,
        verbose=False,
    )
    return {
        "text": result["text"].strip(),
        "language": result.get("language", "en"),
        "segments": result.get("segments", []),
    }
