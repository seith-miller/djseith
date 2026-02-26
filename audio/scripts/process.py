#!/usr/bin/env python3
"""
DJ Seith Audio Processor

Processes audio files:
1. Detects BPM and key signature
2. Renames with convention: Title_BPM_Key.ext
3. Splits into stems using demucs
"""

import argparse
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

STAGING_DIR = Path(__file__).parent.parent / "staging"
OUTPUT_DIR = Path(__file__).parent.parent / "library"

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

    # Correlate with major and minor profiles for each possible root
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


def shorten_title(filename: str) -> str:
    """Create shortened title from filename."""
    import re
    # Remove extension and clean up
    title = Path(filename).stem
    # Remove parenthetical content like (OFFICIAL VIDEO), (Remix), etc.
    title = re.sub(r'\([^)]*\)', '', title)
    title = re.sub(r'\[[^\]]*\]', '', title)
    # Remove common prefixes/suffixes, extra spaces
    title = title.replace("-", " ").replace("_", " ")
    # Remove non-alphanumeric except spaces
    title = re.sub(r'[^a-zA-Z0-9\s]', '', title)
    # Collapse multiple spaces
    title = " ".join(title.split())
    # Convert to CamelCase, limit length
    words = title.split()
    shortened = "".join(word.capitalize() for word in words[:4])
    return shortened[:30] if len(shortened) > 30 else shortened


STEM_PREFIXES = {
    'vocals': '0_Vox',
    'other': '1_Other',
    'bass': '2_Bass',
    'drums': '3_Drums',
}


def run_demucs(audio_path: Path, output_dir: Path, base_name: str) -> None:
    """Run demucs stem separation and rename stems."""
    cmd = [
        sys.executable, "-m", "demucs",
        "-o", str(output_dir),
        str(audio_path)
    ]
    subprocess.run(cmd, check=True)

    # Rename stems with prefix convention
    stems_dir = output_dir / "htdemucs" / audio_path.stem
    if stems_dir.exists():
        for stem_file in stems_dir.glob("*.wav"):
            instrument = stem_file.stem  # bass, drums, vocals, other
            prefix = STEM_PREFIXES.get(instrument, instrument)
            new_stem_name = f"{prefix}_{base_name}.wav"
            stem_file.rename(stems_dir / new_stem_name)


def process_file(audio_path: Path, target_bpm: int | None = None, no_stems: bool = False) -> None:
    """Process a single audio file."""
    print(f"\nProcessing: {audio_path.name}")

    # Load audio
    y, sr = librosa.load(audio_path, sr=None)

    # Detect BPM and key
    print("  Detecting BPM...")
    original_bpm = detect_bpm(audio_path)
    print(f"  Original BPM: {original_bpm}")

    print("  Detecting key...")
    key = detect_key(audio_path)
    print(f"  Key: {key}")

    # Determine final BPM
    if target_bpm and target_bpm != original_bpm:
        bpm = target_bpm
    else:
        bpm = original_bpm

    # Generate base name and create output directory
    title = shorten_title(audio_path.name)
    base_name = f"{title}_{bpm}_{key}"
    track_dir = OUTPUT_DIR / base_name
    track_dir.mkdir(exist_ok=True)
    print(f"  Output dir: {track_dir}")

    # Save initial WAV
    output_path = track_dir / f"{base_name}.wav"
    sf.write(output_path, y, sr)

    # Time-stretch with rubberband if target BPM specified
    if target_bpm and target_bpm != original_bpm:
        print(f"  Stretching {original_bpm} → {target_bpm} BPM (rubberband)...")
        temp_path = track_dir / f"{base_name}_temp.wav"
        output_path.rename(temp_path)
        cmd = [
            "rubberband",
            "--tempo", f"{original_bpm}:{target_bpm}",
            str(temp_path),
            str(output_path)
        ]
        subprocess.run(cmd, check=True)
        temp_path.unlink()

    print(f"  Saved to: {output_path}")

    if no_stems:
        # Just rename mix file, skip stem separation
        if output_path.exists():
            output_path.rename(track_dir / f"4_Mix_{base_name}.wav")
        print("  Done (stems skipped).")
    else:
        # Run stem separation
        print("  Running stem separation...")
        run_demucs(output_path, track_dir, base_name)

        # Move stems from htdemucs subdirectory up to track directory
        stems_subdir = track_dir / "htdemucs" / base_name
        if stems_subdir.exists():
            for stem_file in stems_subdir.glob("*.wav"):
                stem_file.rename(track_dir / stem_file.name)
            # Clean up empty directories
            stems_subdir.rmdir()
            (track_dir / "htdemucs").rmdir()

        # Rename mix file with prefix
        if output_path.exists():
            output_path.rename(track_dir / f"4_Mix_{base_name}.wav")

        print("  Stems complete.")


def get_audio_files(paths: list[str] | None) -> list[Path]:
    """Get list of audio files to process."""
    audio_extensions = {'.mp3', '.wav', '.flac', '.aiff', '.m4a', '.ogg'}

    if paths:
        return [Path(p) for p in paths if Path(p).suffix.lower() in audio_extensions]

    # No paths specified - process all in input directory
    return [f for f in STAGING_DIR.iterdir() if f.suffix.lower() in audio_extensions]


def main():
    parser = argparse.ArgumentParser(description="Process audio files for DJ use")
    parser.add_argument("files", nargs="*", help="Audio files to process (default: all in input/)")
    parser.add_argument("--bpm", type=int, help="Target BPM (time-stretch to this tempo)")
    parser.add_argument("--no-stems", action="store_true", help="Skip stem separation")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    files = get_audio_files(args.files)

    if not files:
        print("No audio files found to process.")
        return

    print(f"Found {len(files)} file(s) to process")
    if args.bpm:
        print(f"Target BPM: {args.bpm}")

    for audio_file in files:
        process_file(audio_file, target_bpm=args.bpm, no_stems=args.no_stems)

    print("\nAll files processed.")


if __name__ == "__main__":
    main()
