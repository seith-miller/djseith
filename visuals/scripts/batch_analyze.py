#!/usr/bin/env python3
"""Batch analysis: run phrase detection + snare detection for all tracks.

Walks audio/library/<TrackName>/ directories and writes metadata alongside
the audio files:
  - phrases.json   (phrase/beat/section data from phrase_detect.py)
  - snare.json     (snare hit times from detect_snare.py)

Metadata lives with the audio, not in git.  Both sync to R2 together.

Usage:
  python visuals/scripts/batch_analyze.py                  # all tracks
  python visuals/scripts/batch_analyze.py --track BlueMonday_130_Em
  python visuals/scripts/batch_analyze.py --force           # overwrite existing
  python visuals/scripts/batch_analyze.py --phrases-only    # skip snare
  python visuals/scripts/batch_analyze.py --snare-only      # skip phrases
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent so we can import sibling modules
sys.path.insert(0, str(Path(__file__).parent))

from phrase_detect import analyze as phrase_analyze
from detect_snare import detect_snare

import numpy as np

DEFAULT_LIBRARY = Path(__file__).parent.parent.parent / "audio" / "library"


def find_stem(track_dir: Path, prefix: str) -> Path | None:
    """Find a stem WAV by prefix (e.g. '3_Drums', '4_Mix')."""
    matches = list(track_dir.glob(f"{prefix}_*.wav"))
    return matches[0] if matches else None


def run_phrases(track_dir: Path, track_name: str, bpm: int | None,
                force: bool) -> dict | None:
    """Run phrase detection on the mix stem. Returns phrase data or None."""
    out = track_dir / "phrases.json"
    if out.exists() and not force:
        print(f"  [skip] {track_name}/phrases.json exists (use --force)")
        return json.loads(out.read_text())

    mix = find_stem(track_dir, "4_Mix")
    if not mix:
        print(f"  [warn] {track_name}: no 4_Mix stem, skipping phrases")
        return None

    print(f"  Analyzing phrases: {mix.name}")
    result = phrase_analyze(str(mix), bpm=bpm)

    out.write_text(json.dumps(result, indent=2))
    n_sections = len(result.get("sections", []))
    print(f"  -> {out.name}: {n_sections} sections, "
          f"{result['total_beats']} beats")
    return result


def run_snare(track_dir: Path, track_name: str, phrases: dict,
              force: bool) -> None:
    """Run snare detection on the drum stem."""
    out = track_dir / "snare.json"
    if out.exists() and not force:
        print(f"  [skip] {track_name}/snare.json exists (use --force)")
        return

    drums = find_stem(track_dir, "3_Drums")
    if not drums:
        print(f"  [warn] {track_name}: no 3_Drums stem, skipping snare")
        return

    beat_times = np.array(phrases["beat_times"])
    beat_interval = float(np.median(np.diff(beat_times)))

    print(f"  Detecting snare: {drums.name}")
    times, snare_idx = detect_snare(str(drums), beat_interval, beat_times)

    out.write_text(json.dumps({
        "snare_times": times,
        "n_hits": len(times),
        "drum_stem": str(drums),
        "method": "nmf_pcen",
        "snare_component": snare_idx,
    }, indent=2))
    print(f"  -> {out.name}: {len(times)} hits")


def parse_bpm(track_name: str) -> int | None:
    """Extract BPM from track directory name like 'BlueMonday_130_Em'."""
    parts = track_name.rsplit("_", 2)
    if len(parts) >= 3:
        try:
            return int(parts[-2])
        except ValueError:
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description="Batch phrase + snare analysis")
    ap.add_argument("--library", type=Path, default=DEFAULT_LIBRARY,
                    help=f"Audio library path (default: {DEFAULT_LIBRARY})")
    ap.add_argument("--track", help="Analyze only this track dir name")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing metadata")
    ap.add_argument("--phrases-only", action="store_true",
                    help="Run phrase detection only (skip snare)")
    ap.add_argument("--snare-only", action="store_true",
                    help="Run snare detection only (skip phrases)")
    args = ap.parse_args()

    library = args.library.resolve()
    if not library.exists():
        raise SystemExit(f"Audio library not found: {library}")

    # Collect track directories
    if args.track:
        track_dirs = [library / args.track]
        if not track_dirs[0].is_dir():
            raise SystemExit(f"Track not found: {track_dirs[0]}")
    else:
        track_dirs = sorted(
            d for d in library.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    print(f"Batch analysis: {len(track_dirs)} tracks in {library}\n")

    stats = {"phrases": 0, "snare": 0, "skipped": 0, "errors": 0}

    for track_dir in track_dirs:
        name = track_dir.name
        bpm = parse_bpm(name)
        print(f"\n[{name}]  BPM={bpm or '?'}")

        try:
            # Phrase detection
            phrases = None
            if not args.snare_only:
                phrases = run_phrases(track_dir, name, bpm, args.force)
                if phrases:
                    stats["phrases"] += 1

            # Snare detection (needs phrases for beat grid)
            if not args.phrases_only:
                if phrases is None:
                    # Try loading existing phrases.json for snare-only mode
                    pf = track_dir / "phrases.json"
                    if pf.exists():
                        phrases = json.loads(pf.read_text())

                if phrases and "beat_times" in phrases:
                    run_snare(track_dir, name, phrases, args.force)
                    stats["snare"] += 1
                elif not args.phrases_only:
                    print(f"  [skip] No phrase data for snare detection")
                    stats["skipped"] += 1

        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            stats["errors"] += 1

    print(f"\n{'='*50}")
    print(f"Done. phrases={stats['phrases']}  snare={stats['snare']}  "
          f"skipped={stats['skipped']}  errors={stats['errors']}")


if __name__ == "__main__":
    main()
