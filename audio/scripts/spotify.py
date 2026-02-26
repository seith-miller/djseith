#!/usr/bin/env python3
"""
Spotify Playlist Importer

Scrapes public Spotify playlist pages to get track info.
Adds tracks to to_get.md queue, skipping any already in queue or output/.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

STAGING_DIR = Path(__file__).parent.parent / "staging"
OUTPUT_DIR = Path(__file__).parent.parent / "library"
QUEUE_FILE = Path(__file__).parent.parent / "to_get.md"
PLAYLISTS_FILE = Path(__file__).parent.parent / "playlists.md"


def get_playlists_from_file() -> list[str]:
    """Read playlist URLs from playlists.md (Active section only)."""
    if not PLAYLISTS_FILE.exists():
        return []

    content = PLAYLISTS_FILE.read_text()
    urls = []
    in_active = False

    for line in content.split("\n"):
        line = line.strip()
        if line == "## Active":
            in_active = True
            continue
        if line.startswith("## ") and in_active:
            break
        if in_active and line.startswith("- ") and "spotify.com" in line:
            url = line[2:].strip()
            urls.append(url)

    return urls


def scrape_playlist(playlist_url: str) -> list[dict]:
    """Scrape track info from Spotify's embed endpoint (no auth needed)."""
    # Convert playlist URL to embed URL
    playlist_id = playlist_url.rstrip("/").split("/")[-1].split("?")[0]
    embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"

    req = urllib.request.Request(embed_url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    })
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")

    # Parse __NEXT_DATA__ which contains full track list
    nd = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not nd:
        return []

    data = json.loads(nd.group(1))
    track_list = (data.get("props", {}).get("pageProps", {})
                  .get("state", {}).get("data", {}).get("entity", {})
                  .get("trackList", []))

    tracks = []
    for t in track_list:
        duration_ms = t.get("duration", 0)
        duration_s = duration_ms // 1000 if duration_ms else 0
        mins = duration_s // 60
        secs = duration_s % 60
        tracks.append({
            "name": t.get("title", ""),
            "artist": t.get("subtitle", ""),
            "duration": f"{mins}:{secs:02d}",
            "duration_ms": duration_ms,
        })

    return tracks


def get_existing_tracks() -> set[str]:
    """Get normalized names of tracks already in output/ or to_get.md."""
    existing = set()

    # From output directory names
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name != "emergency":
                # Output names are like "BlueMonday_130_Em" - extract the title part
                parts = d.name.rsplit("_", 2)
                if len(parts) >= 3:
                    existing.add(_normalize(parts[0]))

    # From to_get.md entries
    if QUEUE_FILE.exists():
        content = QUEUE_FILE.read_text()
        for line in content.splitlines():
            if line.startswith("- ") and not line.strip().startswith("- http"):
                track_name = line[2:].strip()
                existing.add(_normalize(track_name))

    return existing


def _normalize(name: str) -> str:
    """Normalize a track/artist name for fuzzy matching."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = ' '.join(name.split())
    return name


def is_already_acquired(artist: str, track_name: str, existing: set[str]) -> bool:
    """Check if a track is already acquired (fuzzy match)."""
    # Check various combinations
    checks = [
        _normalize(f"{artist} {track_name}"),
        _normalize(track_name),
        _normalize(artist),
    ]

    for existing_name in existing:
        for check in checks[:2]:  # artist+track and track alone
            # Check if the existing name contains the key words
            if check and existing_name and (
                check in existing_name or existing_name in check
            ):
                return True

    return False


def add_to_queue(tracks: list[dict], existing: set[str]) -> int:
    """Add tracks to to_get.md queue file, skipping already-acquired tracks."""
    if QUEUE_FILE.exists():
        content = QUEUE_FILE.read_text()
    else:
        content = "# Track Queue\n\n## To Download\n\n\n## Downloaded\n"

    lines = content.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## To Download":
            insert_idx = i + 1
            while insert_idx < len(lines) and lines[insert_idx].strip() == "":
                insert_idx += 1
            break

    if insert_idx is None:
        print("Could not find '## To Download' section in queue file")
        return 0

    added = 0
    skipped = 0
    new_entries = []
    for track in tracks:
        name = track.get("name", "Unknown")
        artist = track.get("artist", "Unknown")
        duration = track.get("duration", "")

        if is_already_acquired(artist, name, existing):
            print(f"  SKIP (acquired): {artist} - {name}")
            skipped += 1
            continue

        dur_str = f" ({duration})" if duration else ""
        search_query = urllib.parse.quote_plus(f"{artist} - {name}")
        search_url = f"https://www.youtube.com/results?search_query={search_query}"
        entry = f"- {artist} - {name}{dur_str}\n  {search_url}"
        new_entries.append(entry)
        added += 1
        print(f"  NEW:  {artist} - {name}{dur_str}")

    if new_entries:
        new_content = "\n".join(new_entries)
        lines.insert(insert_idx, new_content + "\n")
        QUEUE_FILE.write_text("\n".join(lines))

    if skipped:
        print(f"\n  Skipped {skipped} already-acquired track(s)")

    return added


def process_playlist(playlist_url: str) -> int:
    """Scrape a Spotify playlist and add new tracks to queue."""
    print(f"Fetching: {playlist_url}")
    tracks = scrape_playlist(playlist_url)

    if not tracks:
        print("No tracks found (playlist may be private or page structure changed)")
        return 0

    print(f"Found {len(tracks)} tracks in playlist\n")

    existing = get_existing_tracks()
    print(f"Already acquired: {len(existing)} tracks\n")

    added = add_to_queue(tracks, existing)
    return added


def main():
    parser = argparse.ArgumentParser(description="Import tracks from Spotify playlist")
    parser.add_argument("playlist_url", nargs="?",
                        help="Spotify playlist URL (reads from playlists.md if omitted)")
    args = parser.parse_args()

    if args.playlist_url:
        urls = [args.playlist_url]
    else:
        urls = get_playlists_from_file()
        if not urls:
            print("No playlists found. Add URLs to playlists.md or pass one as argument.")
            return
        print(f"Found {len(urls)} playlist(s) in playlists.md\n")

    total_added = 0
    for url in urls:
        added = process_playlist(url)
        total_added += added
        print()

    print(f"Total: added {total_added} new tracks to queue")
    if total_added:
        print("Run 'python audio/scripts/download.py' to download them")


if __name__ == "__main__":
    main()
