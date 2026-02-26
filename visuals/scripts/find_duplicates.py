#!/usr/bin/env python3
"""Find duplicate shots across split video folders using perceptual hashing.

Pass 1: Hash all shots, find duplicate clusters, generate visual report.
Pass 2: Delete confirmed duplicates (run with --delete after reviewing report).
"""

import argparse, json, subprocess, sys
from collections import defaultdict
from pathlib import Path

import imagehash
from PIL import Image

SHOTS_DIR = Path(__file__).parent.parent / "assets" / "video" / "shots"
REPORT_DIR = Path(__file__).parent.parent / "assets" / "video" / "duplicate_report"
HASH_CACHE = REPORT_DIR / "hashes.json"


def extract_frames(video: Path, count: int = 3) -> list[Image.Image]:
    """Extract frames at 25%, 50%, 75% of duration."""
    dur_out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True
    )
    duration = float(dur_out.stdout.strip())
    frames = []
    for frac in [0.25, 0.50, 0.75]:
        ts = duration * frac
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{ts:.3f}", "-i", str(video),
            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and result.stdout:
            from io import BytesIO
            frames.append(Image.open(BytesIO(result.stdout)).convert("RGB"))
    return frames


def hash_shot(video: Path) -> list[str]:
    """Get perceptual hashes for a shot (multiple frames for robustness)."""
    frames = extract_frames(video)
    return [str(imagehash.phash(f, hash_size=16)) for f in frames]


def hamming(h1: str, h2: str) -> int:
    """Hamming distance between two hex hash strings."""
    a = imagehash.hex_to_hash(h1)
    b = imagehash.hex_to_hash(h2)
    return a - b


def build_hashes(shots: list[Path]) -> dict[str, list[str]]:
    """Hash all shots, with disk cache."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cache = {}
    if HASH_CACHE.exists():
        cache = json.loads(HASH_CACHE.read_text())

    results = {}
    for i, s in enumerate(shots, 1):
        key = str(s.relative_to(SHOTS_DIR))
        if key in cache:
            results[key] = cache[key]
        else:
            print(f"  Hashing [{i}/{len(shots)}] {key}")
            try:
                results[key] = hash_shot(s)
            except Exception as e:
                print(f"    ERROR: {e}")
                results[key] = []
        cache[key] = results[key]

    HASH_CACHE.write_text(json.dumps(cache, indent=2))
    return results


def find_clusters(hashes: dict[str, list[str]], threshold: int = 18) -> list[list[str]]:
    """Find clusters of duplicate shots. Uses average distance across frame hashes."""
    keys = [k for k, v in hashes.items() if v]
    n = len(keys)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    print(f"\n  Comparing {n} shots ({n*(n-1)//2} pairs)...")
    for i in range(n):
        for j in range(i + 1, n):
            h_i, h_j = hashes[keys[i]], hashes[keys[j]]
            # compare matching frame positions, take average
            dists = []
            for a, b in zip(h_i, h_j):
                dists.append(hamming(a, b))
            if dists and (sum(dists) / len(dists)) <= threshold:
                union(i, j)

    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(keys[i])

    # only return clusters with actual duplicates
    return [v for v in clusters.values() if len(v) > 1]


def make_thumbnail(video: Path, out: Path, size: int = 320):
    """Extract a single thumbnail from a shot."""
    dur_out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True
    )
    duration = float(dur_out.stdout.strip())
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{duration * 0.5:.3f}", "-i", str(video),
        "-frames:v", "1", "-vf", f"scale={size}:-1",
        str(out)
    ]
    subprocess.run(cmd, check=True)


def generate_report(clusters: list[list[str]]):
    """Generate an HTML report with thumbnails for each duplicate cluster."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    thumbs_dir = REPORT_DIR / "thumbs"
    thumbs_dir.mkdir(exist_ok=True)

    html_parts = [
        "<html><head><style>",
        "body { background: #111; color: #eee; font-family: monospace; padding: 20px; }",
        ".cluster { border: 1px solid #444; margin: 20px 0; padding: 15px; border-radius: 8px; }",
        ".cluster h3 { color: #f90; }",
        ".shots { display: flex; flex-wrap: wrap; gap: 15px; }",
        ".shot { text-align: center; }",
        ".shot img { border: 2px solid #333; border-radius: 4px; }",
        ".shot p { font-size: 11px; max-width: 320px; word-wrap: break-word; }",
        ".keep { border-color: #0f0 !important; }",
        "</style></head><body>",
        f"<h1>Duplicate Shot Report</h1>",
        f"<p>{len(clusters)} clusters found</p>",
    ]

    total_dupes = 0
    for ci, cluster in enumerate(clusters, 1):
        html_parts.append(f'<div class="cluster"><h3>Cluster {ci} ({len(cluster)} shots)</h3>')
        html_parts.append('<div class="shots">')

        # sort by folder name so we can prefer keeping from richer sources
        cluster.sort()
        for si, shot_key in enumerate(cluster):
            video_path = SHOTS_DIR / shot_key
            thumb_name = shot_key.replace("/", "__").replace(".mp4", ".jpg")
            thumb_path = thumbs_dir / thumb_name
            if not thumb_path.exists():
                try:
                    make_thumbnail(video_path, thumb_path)
                except Exception:
                    continue

            css_class = "shot keep" if si == 0 else "shot"
            label = "KEEP" if si == 0 else "duplicate"
            html_parts.append(f'<div class="{css_class}">')
            html_parts.append(f'<img src="thumbs/{thumb_name}" width="320">')
            html_parts.append(f'<p><b>[{label}]</b><br>{shot_key}</p>')
            html_parts.append('</div>')

        total_dupes += len(cluster) - 1
        html_parts.append('</div></div>')

    html_parts.append(f"<p>Total duplicates to remove: <b>{total_dupes}</b></p>")
    html_parts.append("</body></html>")

    report_path = REPORT_DIR / "report.html"
    report_path.write_text("\n".join(html_parts))
    print(f"\n  Report: {report_path}")
    print(f"  {len(clusters)} clusters, {total_dupes} duplicates flagged for removal")
    return total_dupes


def delete_duplicates(clusters: list[list[str]], dry_run: bool = True):
    """Delete duplicate shots, keeping the first in each cluster."""
    count = 0
    for cluster in clusters:
        cluster.sort()
        for shot_key in cluster[1:]:  # skip first (keep)
            path = SHOTS_DIR / shot_key
            if path.exists():
                if dry_run:
                    print(f"  WOULD DELETE: {shot_key}")
                else:
                    path.unlink()
                    print(f"  DELETED: {shot_key}")
                count += 1
    action = "would delete" if dry_run else "deleted"
    print(f"\n  {count} files {action}")


def main():
    ap = argparse.ArgumentParser(description="Find and remove duplicate shots")
    ap.add_argument("-t", "--threshold", type=int, default=18,
                    help="Hamming distance threshold (lower = stricter, default 18)")
    ap.add_argument("--delete", action="store_true",
                    help="Actually delete duplicates (keeps first in each cluster)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be deleted without deleting")
    args = ap.parse_args()

    shots = sorted(SHOTS_DIR.rglob("shot_*.mp4"))
    print(f"Found {len(shots)} shots\n")

    if not shots:
        return

    print("Pass 1: Hashing shots...")
    hashes = build_hashes(shots)

    print("Pass 2: Finding duplicates...")
    clusters = find_clusters(hashes, threshold=args.threshold)

    if not clusters:
        print("\nNo duplicates found!")
        return

    print(f"\nPass 3: Generating report...")
    generate_report(clusters)

    if args.delete:
        print("\nPass 4: Deleting duplicates...")
        delete_duplicates(clusters, dry_run=False)
    elif args.dry_run:
        print("\nDry run:")
        delete_duplicates(clusters, dry_run=True)
    else:
        print("\nReview the report, then run with --delete to remove duplicates.")
        print("  Or use --dry-run to preview what would be deleted.")


if __name__ == "__main__":
    main()
