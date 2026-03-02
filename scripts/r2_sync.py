#!/usr/bin/env python3
"""Sync assets to/from Cloudflare R2.

R2 is S3-compatible, so we use boto3 with a custom endpoint.

Bucket layout mirrors local structure:
  audio/library/<TrackName>/4_Mix_<TrackName>.wav
  audio/library/<TrackName>/3_Drums_<TrackName>.wav
  audio/library/<TrackName>/phrases.json
  audio/library/<TrackName>/snare.json
  projects/<event>/shots/<shot>.mp4
  projects/<event>/stills/<still>.png

Environment variables (or .env file):
  R2_ACCESS_KEY_ID      — Cloudflare R2 API token access key
  R2_SECRET_ACCESS_KEY  — Cloudflare R2 API token secret key
  R2_ENDPOINT           — https://<account_id>.r2.cloudflarestorage.com
  R2_BUCKET             — bucket name (default: djseith-assets)

Usage:
  # Upload everything
  python scripts/r2_sync.py push

  # Upload only audio library
  python scripts/r2_sync.py push --audio-only

  # Download everything (for CI or new machine)
  python scripts/r2_sync.py pull

  # Download a single track
  python scripts/r2_sync.py pull --track BlueMonday_130_Em

  # List bucket contents
  python scripts/r2_sync.py ls

  # Dry run (show what would be uploaded)
  python scripts/r2_sync.py push --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("boto3 required: pip install boto3")
    sys.exit(1)

ROOT = Path(__file__).parent.parent
DEFAULT_BUCKET = "djseith-assets"

# Asset directories to sync (relative to project root)
SYNC_DIRS = [
    "audio/library",
    "projects/funeral_parade_of_roses/shots",
    "projects/funeral_parade_of_roses/stills",
]

# File extensions worth syncing
SYNC_EXTENSIONS = {
    ".wav", ".mp3", ".flac",     # audio
    ".mp4", ".mov",               # video
    ".png", ".jpg", ".jpeg",      # images
    ".json",                      # metadata
}


def get_client():
    """Create an S3 client configured for Cloudflare R2."""
    endpoint = os.environ.get("R2_ENDPOINT")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")

    if not all([endpoint, access_key, secret_key]):
        missing = []
        if not endpoint: missing.append("R2_ENDPOINT")
        if not access_key: missing.append("R2_ACCESS_KEY_ID")
        if not secret_key: missing.append("R2_SECRET_ACCESS_KEY")
        raise SystemExit(
            f"Missing env vars: {', '.join(missing)}\n"
            "Set them or create a .env file. See script docstring for details."
        )

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def get_bucket():
    return os.environ.get("R2_BUCKET", DEFAULT_BUCKET)


def collect_local_files(track: str = None, audio_only: bool = False) -> list[tuple[Path, str]]:
    """Collect files to sync. Returns list of (local_path, r2_key) tuples."""
    files = []

    dirs = ["audio/library"] if audio_only else SYNC_DIRS

    for sync_dir in dirs:
        local_dir = ROOT / sync_dir
        if not local_dir.exists():
            continue

        for path in sorted(local_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SYNC_EXTENSIONS:
                continue

            # Filter to specific track if requested (audio only)
            if track:
                if sync_dir == "audio/library":
                    rel = path.relative_to(local_dir)
                    if rel.parts[0] != track:
                        continue
                else:
                    # --track means audio only, skip shots/stills
                    continue

            r2_key = str(path.relative_to(ROOT))
            files.append((path, r2_key))

    return files


def list_remote_keys(client, bucket: str, prefix: str = "") -> dict[str, int]:
    """List all objects in the bucket. Returns {key: size}."""
    objects = {}
    paginator = client.get_paginator("list_objects_v2")
    kwargs = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix

    for page in paginator.paginate(**kwargs):
        for obj in page.get("Contents", []):
            objects[obj["Key"]] = obj["Size"]

    return objects


def cmd_push(args):
    """Upload local assets to R2."""
    client = get_client()
    bucket = get_bucket()
    files = collect_local_files(track=args.track, audio_only=args.audio_only)

    if not files:
        print("No files to upload.")
        return

    # Get remote state for skip-existing logic
    remote = {}
    if not args.force:
        print("Checking remote state...")
        remote = list_remote_keys(client, bucket)

    uploaded = skipped = 0
    total_bytes = 0

    for local_path, r2_key in files:
        local_size = local_path.stat().st_size

        # Skip if remote file exists with same size
        if r2_key in remote and remote[r2_key] == local_size and not args.force:
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [would upload] {r2_key} ({local_size / 1024 / 1024:.1f} MB)")
            uploaded += 1
            total_bytes += local_size
            continue

        print(f"  Uploading {r2_key} ({local_size / 1024 / 1024:.1f} MB)...")
        client.upload_file(str(local_path), bucket, r2_key)
        uploaded += 1
        total_bytes += local_size

    action = "Would upload" if args.dry_run else "Uploaded"
    print(f"\n{action}: {uploaded} files ({total_bytes / 1024 / 1024:.1f} MB)  "
          f"Skipped: {skipped}")


def cmd_pull(args):
    """Download assets from R2 to local."""
    client = get_client()
    bucket = get_bucket()

    prefix = ""
    if args.track:
        prefix = f"audio/library/{args.track}/"
    elif args.audio_only:
        prefix = "audio/library/"

    print(f"Listing remote objects{f' (prefix: {prefix})' if prefix else ''}...")
    remote = list_remote_keys(client, bucket, prefix=prefix)

    if not remote:
        print("No remote files found.")
        return

    downloaded = skipped = 0
    total_bytes = 0

    for r2_key, remote_size in sorted(remote.items()):
        local_path = ROOT / r2_key

        # Skip if local file exists with same size
        if local_path.exists() and local_path.stat().st_size == remote_size and not args.force:
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [would download] {r2_key} ({remote_size / 1024 / 1024:.1f} MB)")
            downloaded += 1
            total_bytes += remote_size
            continue

        print(f"  Downloading {r2_key} ({remote_size / 1024 / 1024:.1f} MB)...")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, r2_key, str(local_path))
        downloaded += 1
        total_bytes += remote_size

    action = "Would download" if args.dry_run else "Downloaded"
    print(f"\n{action}: {downloaded} files ({total_bytes / 1024 / 1024:.1f} MB)  "
          f"Skipped: {skipped}")


def cmd_ls(args):
    """List bucket contents."""
    client = get_client()
    bucket = get_bucket()

    prefix = args.prefix or ""
    remote = list_remote_keys(client, bucket, prefix=prefix)

    if not remote:
        print("Bucket is empty." if not prefix else f"No objects with prefix '{prefix}'.")
        return

    total = 0
    for key, size in sorted(remote.items()):
        print(f"  {size / 1024 / 1024:8.1f} MB  {key}")
        total += size

    print(f"\n{len(remote)} objects, {total / 1024 / 1024:.1f} MB total")


def main():
    # Load .env if present
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

    ap = argparse.ArgumentParser(description="Sync assets to/from Cloudflare R2")
    sub = ap.add_subparsers(dest="command", required=True)

    # push
    push_p = sub.add_parser("push", help="Upload local assets to R2")
    push_p.add_argument("--track", help="Upload only this track")
    push_p.add_argument("--audio-only", action="store_true",
                        help="Upload only audio library (skip shots/stills)")
    push_p.add_argument("--force", action="store_true",
                        help="Upload even if remote file exists with same size")
    push_p.add_argument("--dry-run", action="store_true",
                        help="Show what would be uploaded")

    # pull
    pull_p = sub.add_parser("pull", help="Download assets from R2")
    pull_p.add_argument("--track", help="Download only this track")
    pull_p.add_argument("--audio-only", action="store_true",
                        help="Download only audio library")
    pull_p.add_argument("--force", action="store_true",
                        help="Download even if local file exists with same size")
    pull_p.add_argument("--dry-run", action="store_true",
                        help="Show what would be downloaded")

    # ls
    ls_p = sub.add_parser("ls", help="List bucket contents")
    ls_p.add_argument("prefix", nargs="?", help="Optional key prefix filter")

    args = ap.parse_args()

    if args.command == "push":
        cmd_push(args)
    elif args.command == "pull":
        cmd_pull(args)
    elif args.command == "ls":
        cmd_ls(args)


if __name__ == "__main__":
    main()
