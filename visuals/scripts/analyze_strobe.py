#!/usr/bin/env python3
"""Analyze a video for photosensitive epilepsy (PSE) strobe risk.

Measures frame-to-frame luminance transitions and flags sequences
that exceed the Harding test threshold (>3 flashes/sec by default).

A "flash" is a luminance swing where the frame-mean brightness changes
by more than --threshold (default 0.10 = 10% of full range) between
consecutive frames.

Usage:
  python visuals/scripts/analyze_strobe.py video.mp4
  python visuals/scripts/analyze_strobe.py video.mp4 --limit 3 --threshold 0.10
"""

import argparse
import subprocess
import struct
import sys
from pathlib import Path

import numpy as np


def extract_brightness(video_path: str, width: int = 160) -> tuple:
    """Extract per-frame mean brightness via ffmpeg.

    Downscales to `width` px wide grayscale for speed.
    Returns (brightness_array, fps, n_frames).
    """
    # Probe FPS and duration
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,nb_frames,duration",
         "-show_entries", "format=duration",
         "-of", "csv=p=0",
         video_path],
        capture_output=True, text=True,
    )
    lines = [l.strip() for l in probe.stdout.strip().split('\n') if l.strip()]

    # Parse FPS from first line (format: "30/1" or "30000/1001")
    fps_str = lines[0].split(',')[0]
    if '/' in fps_str:
        num, den = fps_str.split('/')
        fps = float(num) / float(den)
    else:
        fps = float(fps_str)

    # Extract raw grayscale frames
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"scale={width}:-1,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray",
        "-v", "error",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[-500:]}")

    raw = result.stdout
    # Infer height from data size
    frame_w = width
    # Each frame = width * height bytes (gray8)
    # We need to figure out height from aspect ratio
    probe2 = subprocess.run(
        ["ffprobe", "-v", "error",
         "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0",
         video_path],
        capture_output=True, text=True,
    )
    orig_w, orig_h = [int(x) for x in probe2.stdout.strip().split(',')]
    frame_h = round(frame_w * orig_h / orig_w)
    # Make even
    if frame_h % 2:
        frame_h += 1

    frame_size = frame_w * frame_h
    n_frames = len(raw) // frame_size

    frames = np.frombuffer(raw[:n_frames * frame_size], dtype=np.uint8)
    frames = frames.reshape(n_frames, frame_h, frame_w)

    # Mean brightness per frame, normalized to [0, 1]
    brightness = frames.mean(axis=(1, 2)) / 255.0

    return brightness, fps, n_frames


def detect_flashes(brightness: np.ndarray, threshold: float = 0.10):
    """Detect frame pairs where brightness swings exceed threshold.

    Returns array of (frame_index, delta) for each flash transition.
    """
    deltas = np.abs(np.diff(brightness))
    flash_indices = np.where(deltas > threshold)[0]
    return list(zip(flash_indices.tolist(), deltas[flash_indices].tolist()))


def measure_flash_rate(flashes: list, fps: float, window_sec: float = 1.0):
    """Sliding window flash rate measurement.

    Returns list of (time_sec, flash_count_in_window) for each flash.
    Also returns the maximum flash rate found.
    """
    if not flashes:
        return [], 0.0

    flash_times = [f[0] / fps for f, _ in zip(flashes, range(len(flashes)))]
    flash_times = [idx / fps for idx, _ in flashes]

    rates = []
    max_rate = 0.0

    for i, t in enumerate(flash_times):
        # Count flashes in [t, t + window_sec]
        count = sum(1 for t2 in flash_times if t <= t2 < t + window_sec)
        rate = count / window_sec
        rates.append((t, count, rate))
        max_rate = max(max_rate, rate)

    return rates, max_rate


def find_violations(rates: list, limit: float):
    """Find time windows that exceed the flash rate limit.

    Returns list of (start_time, flash_count, rate) for violations.
    """
    return [(t, count, rate) for t, count, rate in rates if rate > limit]


def main():
    ap = argparse.ArgumentParser(
        description="Analyze video for PSE strobe risk")
    ap.add_argument("video", help="Path to video file")
    ap.add_argument("--limit", type=float, default=3.0,
                    help="Max allowed flashes/sec (default 3.0, Harding test)")
    ap.add_argument("--threshold", type=float, default=0.10,
                    help="Min brightness delta to count as flash (default 0.10)")
    ap.add_argument("--window", type=float, default=1.0,
                    help="Measurement window in seconds (default 1.0)")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Print all flash transitions")
    args = ap.parse_args()

    print(f"Analyzing: {args.video}")
    print(f"Limit: {args.limit} flashes/sec, threshold: {args.threshold}")

    brightness, fps, n_frames = extract_brightness(args.video)
    duration = n_frames / fps
    print(f"  {n_frames} frames, {fps:.1f} fps, {duration:.1f}s")

    # Overall brightness stats
    print(f"  Brightness: mean={brightness.mean():.3f}  "
          f"min={brightness.min():.3f}  max={brightness.max():.3f}")

    # Frame-to-frame deltas
    deltas = np.abs(np.diff(brightness))
    print(f"  Frame deltas: mean={deltas.mean():.4f}  "
          f"max={deltas.max():.4f}  "
          f"p95={np.percentile(deltas, 95):.4f}  "
          f"p99={np.percentile(deltas, 99):.4f}")

    # Detect flashes
    flashes = detect_flashes(brightness, args.threshold)
    print(f"\n  Flash transitions (delta > {args.threshold}): {len(flashes)}")

    if args.verbose and flashes:
        for idx, delta in flashes[:50]:
            t = idx / fps
            print(f"    {t:7.2f}s  frame {idx:5d}  delta={delta:.4f}")
        if len(flashes) > 50:
            print(f"    ... +{len(flashes) - 50} more")

    # Measure flash rate
    rates, max_rate = measure_flash_rate(flashes, fps, args.window)
    print(f"  Max flash rate: {max_rate:.1f} flashes/sec")

    # Find violations
    violations = find_violations(rates, args.limit)

    if violations:
        print(f"\n  VIOLATIONS: {len(violations)} windows exceed "
              f"{args.limit} flashes/sec")
        # Group into contiguous violation periods
        seen = set()
        periods = []
        for t, count, rate in violations:
            t_round = round(t, 1)
            if t_round not in seen:
                seen.add(t_round)
                periods.append((t, count, rate))

        for t, count, rate in periods[:20]:
            mm, ss = divmod(int(t), 60)
            print(f"    {mm:02d}:{ss:02d}  {rate:.1f} flashes/sec "
                  f"({count} in {args.window}s window)")
        if len(periods) > 20:
            print(f"    ... +{len(periods) - 20} more")

        # Summary by minute
        print(f"\n  Violations by minute:")
        minute_counts = {}
        for t, _, _ in violations:
            m = int(t // 60)
            minute_counts[m] = minute_counts.get(m, 0) + 1
        for m in sorted(minute_counts):
            print(f"    {m:02d}:00 – {m:02d}:59  "
                  f"{minute_counts[m]} violation windows")

        print(f"\n  RESULT: FAIL — video exceeds PSE safety limit")
        return 1
    else:
        print(f"\n  RESULT: PASS — within {args.limit} flashes/sec limit")
        return 0


if __name__ == "__main__":
    sys.exit(main())
