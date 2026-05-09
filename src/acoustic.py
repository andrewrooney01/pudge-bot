from pathlib import Path

import librosa
import numpy as np


def analyze(audio_path: Path, transcript_text: str) -> dict:
    y, sr = librosa.load(str(audio_path), sr=22050)
    duration_sec = len(y) / sr

    f0, voiced_flag, _ = librosa.pyin(
        y, fmin=80, fmax=400, sr=sr, frame_length=2048
    )
    voiced = f0[~np.isnan(f0)]
    pitch_mean = float(np.mean(voiced)) if voiced.size else None
    pitch_std = float(np.std(voiced)) if voiced.size else None

    rms = librosa.feature.rms(y=y)[0]
    energy_mean = float(np.mean(rms))

    pause_ratio = (
        float(np.sum(~voiced_flag) / len(voiced_flag))
        if voiced_flag.size
        else None
    )

    word_count = len(transcript_text.split()) if transcript_text else 0
    minutes = duration_sec / 60.0
    speaking_rate_wpm = (word_count / minutes) if minutes > 0 else None

    return {
        "duration_sec": duration_sec,
        "pitch_mean": pitch_mean,
        "pitch_std": pitch_std,
        "energy_mean": energy_mean,
        "speaking_rate_wpm": speaking_rate_wpm,
        "pause_ratio": pause_ratio,
    }
