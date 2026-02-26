#!/usr/bin/env python3
"""Analyze visual characteristics of each shot for use in video generation.

Per-shot metrics:
  - duration        seconds
  - brightness      mean luminance [0-1]
  - contrast        std dev of luminance [0-1]
  - motion          mean inter-frame pixel delta [0-1]  (high = lots of movement)
  - hue             dominant hue in HSV space [0-360]
  - saturation      mean saturation [0-1]
  - dominant_color  [R, G, B] of most common color cluster

Outputs a JSON catalog at projects/funeral_parade_of_roses/data/shot_catalog.json.
Results are cached — re-run is fast if shots haven't changed.
"""

import argparse, json, subprocess, sys
from pathlib import Path

import cv2
import numpy as np

SHOTS_DIR   = Path(__file__).parent.parent.parent / "projects/funeral_parade_of_roses/shots"
CATALOG_OUT = Path(__file__).parent.parent.parent / "projects/funeral_parade_of_roses/data/shot_catalog.json"

# how many evenly-spaced frames to sample per shot
N_SAMPLE_FRAMES = 16


def probe_duration(path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def analyze_shot(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps          = cap.get(cv2.CAP_PROP_FPS) or 30
    duration     = total_frames / fps

    if total_frames < 2:
        cap.release()
        return None

    # sample frames evenly
    indices = np.linspace(0, total_frames - 1, min(N_SAMPLE_FRAMES, total_frames), dtype=int)
    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()

    if not frames:
        return None

    # --- brightness & contrast (luminance channel) ---
    lums = []
    for f in frames:
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(float) / 255.0
        lums.append(gray)
    lum_stack = np.stack(lums)
    brightness = float(np.mean(lum_stack))
    contrast   = float(np.std(lum_stack))

    # --- motion: mean absolute diff between consecutive sampled frames ---
    diffs = []
    for a, b in zip(frames[:-1], frames[1:]):
        diff = cv2.absdiff(a, b).astype(float) / 255.0
        diffs.append(np.mean(diff))
    motion = float(np.mean(diffs)) if diffs else 0.0

    # --- color: dominant hue & saturation via HSV ---
    hsv_frames = [cv2.cvtColor(f, cv2.COLOR_BGR2HSV).astype(float) for f in frames]
    hue_vals = np.concatenate([h[:, :, 0].flatten() for h in hsv_frames])
    sat_vals = np.concatenate([h[:, :, 1].flatten() / 255.0 for h in hsv_frames])
    saturation = float(np.mean(sat_vals))

    # circular mean of hue (hue wraps at 180 in OpenCV → convert to radians)
    hue_rad = hue_vals * (np.pi / 90.0)  # 0-180 → 0-2π
    hue_mean = float(np.arctan2(np.mean(np.sin(hue_rad)), np.mean(np.cos(hue_rad)))
                     * (180.0 / np.pi) % 360)

    # --- dominant color via simple k=1 mean in BGR → convert to RGB ---
    all_pixels = np.concatenate([f.reshape(-1, 3) for f in frames], axis=0).astype(float)
    dominant_bgr = np.mean(all_pixels, axis=0)
    dominant_rgb = [int(dominant_bgr[2]), int(dominant_bgr[1]), int(dominant_bgr[0])]

    return {
        "duration":       round(duration, 3),
        "brightness":     round(brightness, 4),
        "contrast":       round(contrast, 4),
        "motion":         round(motion, 4),
        "hue":            round(hue_mean, 1),
        "saturation":     round(saturation, 4),
        "dominant_color": dominant_rgb,
    }


def main():
    ap = argparse.ArgumentParser(description="Analyze visual characteristics of all shots")
    ap.add_argument("--shots-dir", default=str(SHOTS_DIR))
    ap.add_argument("-o", "--output",  default=str(CATALOG_OUT))
    ap.add_argument("--force", action="store_true", help="Re-analyze even if cached")
    args = ap.parse_args()

    shots_dir  = Path(args.shots_dir)
    output     = Path(args.output)

    # load existing catalog for cache
    catalog = {}
    if output.exists() and not args.force:
        catalog = json.loads(output.read_text())
        print(f"Loaded {len(catalog)} cached entries from {output}")

    # collect all shot paths
    shot_paths = sorted(shots_dir.rglob("*.mp4"))
    print(f"Found {len(shot_paths)} shots in {shots_dir}")

    new_count = 0
    for i, path in enumerate(shot_paths):
        key = str(path.relative_to(shots_dir))
        if key in catalog and not args.force:
            continue

        result = analyze_shot(path)
        if result is None:
            print(f"  [{i+1}/{len(shot_paths)}] SKIP (unreadable): {key}")
            continue

        result["path"] = str(path)
        catalog[key]   = result
        new_count += 1

        # progress every 10 shots
        if new_count % 10 == 0 or i == len(shot_paths) - 1:
            print(f"  [{i+1}/{len(shot_paths)}] analyzed {new_count} new shots...")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, indent=2))
    print(f"\nCatalog saved: {output}  ({len(catalog)} shots total)")

    # quick summary
    motions    = [v["motion"]     for v in catalog.values()]
    brightness = [v["brightness"] for v in catalog.values()]
    durations  = [v["duration"]   for v in catalog.values()]
    print(f"\nSummary:")
    print(f"  Duration:   {min(durations):.1f}s – {max(durations):.1f}s  (mean {np.mean(durations):.1f}s)")
    print(f"  Brightness: {min(brightness):.3f} – {max(brightness):.3f}  (mean {np.mean(brightness):.3f})")
    print(f"  Motion:     {min(motions):.4f} – {max(motions):.4f}  (mean {np.mean(motions):.4f})")


if __name__ == "__main__":
    main()
