#!/usr/bin/env python3
"""
DJ Seith Audio Analyzer

Analyzes audio files in staging to detect BPM and key.
"""

import argparse
from pathlib import Path

import librosa
import numpy as np

STAGING_DIR = Path(__file__).parent.parent / "staging"

# Key profiles for detection (Krumhansl-Schmuckler)
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def detect_bpm(audio_path: Path) -> int:
    """Detect BPM of audio file."""
    y, sr = librosa.load(audio_path, sr=None, duration=60)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    return int(round(tempo.item() if hasattr(tempo, 'item') else float(tempo)))


def detect_key(audio_path: Path) -> str:
    """Detect musical key of audio file."""
    y, sr = librosa.load(audio_path, sr=None, duration=60)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_avg = np.mean(chroma, axis=1)

    max_corr = -1
    best_key = "C"

    for i in range(12):
        major_corr = np.corrcoef(np.roll(MAJOR_PROFILE, i), chroma_avg)[0, 1]
        minor_corr = np.corrcoef(np.roll(MINOR_PROFILE, i), chroma_avg)[0, 1]

        if major_corr > max_corr:
            max_corr = major_corr
            best_key = KEY_NAMES[i]
        if minor_corr > max_corr:
            max_corr = minor_corr
            best_key = f"{KEY_NAMES[i]}m"

    return best_key


def get_audio_files() -> list[Path]:
    """Get list of audio files in staging."""
    audio_extensions = {'.mp3', '.wav', '.flac', '.aiff', '.m4a', '.ogg'}
    return sorted([f for f in STAGING_DIR.iterdir()
                   if f.suffix.lower() in audio_extensions])


def main():
    parser = argparse.ArgumentParser(description="Analyze audio files in staging")
    parser.add_argument("--bpm-only", action="store_true", help="Only show BPM")
    args = parser.parse_args()

    files = get_audio_files()

    if not files:
        print("No audio files in staging/")
        return

    print(f"\n{'File':<50} {'BPM':>5} {'Key':>5}")
    print("-" * 62)

    for audio_file in files:
        name = audio_file.name[:48] + ".." if len(audio_file.name) > 50 else audio_file.name
        bpm = detect_bpm(audio_file)
        if args.bpm_only:
            print(f"{name:<50} {bpm:>5}")
        else:
            key = detect_key(audio_file)
            print(f"{name:<50} {bpm:>5} {key:>5}")

    print()


if __name__ == "__main__":
    main()
