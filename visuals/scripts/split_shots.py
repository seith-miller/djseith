#!/usr/bin/env python3
"""Split videos into individual shots using PySceneDetect."""

import argparse, os, re, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from scenedetect import open_video, SceneManager, ContentDetector

VIDEO_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses"
SHOTS_DIR = VIDEO_DIR / "shots"


def slugify(name: str) -> str:
    """Convert filename to a clean folder name."""
    name = Path(name).stem
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s-]+", "_", name).strip("_").lower()
    # truncate long names
    return name[:60]


def _encode_shot(args):
    """Encode one shot segment — called in parallel."""
    video_path, start_sec, duration_sec, out_file = args
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_sec),
        "-i", str(video_path),
        "-t", str(duration_sec),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-an",
        "-movflags", "+faststart",
        str(out_file),
    ]
    subprocess.run(cmd, check=True)


def detect_and_split(video_path: Path, threshold: float = 27.0, min_len: float = 0.5,
                     workers: int = 4, frame_skip: int = 1):
    """Detect scenes and split video into shot files."""
    slug = slugify(video_path.name)
    out_dir = SHOTS_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # skip if already processed
    existing = list(out_dir.glob("shot_*.mp4"))
    if existing:
        print(f"  SKIP {slug}/ ({len(existing)} shots already exist)")
        return len(existing)

    print(f"  Detecting scenes in: {video_path.name}  (frame_skip={frame_skip})")
    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=int(min_len * video.frame_rate)))
    sm.detect_scenes(video, show_progress=True, frame_skip=frame_skip)
    scene_list = sm.get_scene_list()

    if not scene_list:
        # no cuts detected — treat whole file as one shot
        scene_list = [(video.base_timecode, video.duration)]

    print(f"  Found {len(scene_list)} shots — encoding ({workers} parallel)...")

    jobs = [
        (video_path, start.get_seconds(), end.get_seconds() - start.get_seconds(),
         out_dir / f"shot_{i:03d}.mp4")
        for i, (start, end) in enumerate(scene_list, 1)
    ]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_encode_shot, jobs))

    print(f"  Wrote {len(scene_list)} shots to {out_dir}/")
    return len(scene_list)


def main():
    ap = argparse.ArgumentParser(description="Split videos into shots")
    ap.add_argument("-t", "--threshold", type=float, default=27.0,
                    help="Content detector threshold (lower = more sensitive, default 27)")
    ap.add_argument("-m", "--min-length", type=float, default=0.5,
                    help="Minimum shot length in seconds (default 0.5)")
    ap.add_argument("-w", "--workers", type=int, default=4,
                    help="Parallel ffmpeg workers for encoding (default 4)")
    ap.add_argument("--frame-skip", type=int, default=1,
                    help="Frames to skip during detection: 1=every other frame (default 1)")
    ap.add_argument("files", nargs="*", help="Specific files to process (default: all mp4 in source/video/)")
    args = ap.parse_args()

    if args.files:
        videos = [Path(f) for f in args.files]
    else:
        videos = sorted(VIDEO_DIR.glob("*.mp4"))

    if not videos:
        print("No videos found.")
        return

    print(f"Processing {len(videos)} videos (threshold={args.threshold}, min_length={args.min_length}s)\n")
    total = 0
    for v in videos:
        n = detect_and_split(v, threshold=args.threshold, min_len=args.min_length,
                             workers=args.workers, frame_skip=args.frame_skip)
        total += n
        print()

    print(f"Done. {total} total shots across {len(videos)} videos.")


if __name__ == "__main__":
    main()
