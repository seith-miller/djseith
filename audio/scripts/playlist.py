#!/usr/bin/env python3
"""
DJ Seith Playlist Manager

Manage playlists as markdown files in playlists/ directory.
Each playlist references tracks by their output folder name (e.g. BlueMonday_130_Em).
"""

import argparse
import re
import sys
from pathlib import Path

import librosa

PLAYLISTS_DIR = Path(__file__).parent.parent / "playlists"
OUTPUT_DIR = Path(__file__).parent.parent / "library"


def slugify(name: str) -> str:
    """Convert playlist name to filename slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    return slug


def find_playlist(name: str) -> Path | None:
    """Find a playlist file by name or slug match."""
    # Exact filename match
    exact = PLAYLISTS_DIR / f"{name}.md"
    if exact.exists():
        return exact

    # Search by slug substring
    slug = slugify(name)
    for f in PLAYLISTS_DIR.glob("*.md"):
        if slug in f.stem:
            return f

    return None


def parse_playlist(path: Path) -> dict:
    """Parse a playlist markdown file into structured data."""
    text = path.read_text()
    result = {"title": "", "date": "", "venue": "", "notes": "", "tracks": [], "path": path}

    # Title from first heading
    title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    if title_match:
        result["title"] = title_match.group(1).strip()

    # Metadata fields
    date_match = re.search(r'\*\*Date:\*\*\s*(.+)', text)
    if date_match:
        result["date"] = date_match.group(1).strip()

    venue_match = re.search(r'\*\*Venue:\*\*\s*(.+)', text)
    if venue_match:
        result["venue"] = venue_match.group(1).strip()

    notes_match = re.search(r'\*\*Notes:\*\*\s*(.+)', text)
    if notes_match:
        result["notes"] = notes_match.group(1).strip()

    # Tracks - numbered list items
    for match in re.finditer(r'^\d+\.\s+(.+)$', text, re.MULTILINE):
        result["tracks"].append(match.group(1).strip())

    return result


def write_playlist(path: Path, data: dict) -> None:
    """Write playlist data back to markdown file."""
    lines = [f"# {data['title']}", ""]

    if data.get("date"):
        lines.append(f"- **Date:** {data['date']}")
    if data.get("venue"):
        lines.append(f"- **Venue:** {data['venue']}")
    if data.get("notes"):
        lines.append(f"- **Notes:** {data['notes']}")

    if any(data.get(k) for k in ("date", "venue", "notes")):
        lines.append("")

    lines.append("## Tracks")
    lines.append("")

    for i, track in enumerate(data["tracks"], 1):
        lines.append(f"{i}. {track}")

    lines.append("")
    path.write_text("\n".join(lines))


def get_track_duration(track_name: str) -> float | None:
    """Get duration in seconds for a track by finding its mix WAV."""
    track_dir = OUTPUT_DIR / track_name
    if not track_dir.exists():
        return None

    mix_file = track_dir / f"4_Mix_{track_name}.wav"
    if not mix_file.exists():
        # Try finding any WAV
        wavs = list(track_dir.glob("*.wav"))
        if not wavs:
            return None
        mix_file = wavs[0]

    y, sr = librosa.load(mix_file, sr=None, duration=None)
    return len(y) / sr


def cmd_new(args):
    """Create a new playlist."""
    PLAYLISTS_DIR.mkdir(exist_ok=True)

    slug = slugify(args.name)
    if args.date:
        filename = f"{args.date}_{slug}.md"
    else:
        filename = f"{slug}.md"

    path = PLAYLISTS_DIR / filename

    if path.exists():
        print(f"Playlist already exists: {path}")
        sys.exit(1)

    data = {
        "title": args.name,
        "date": args.date or "",
        "venue": args.venue or "",
        "notes": args.notes or "",
        "tracks": [],
    }
    write_playlist(path, data)
    print(f"Created: {path}")


def cmd_add(args):
    """Add a track to a playlist."""
    path = find_playlist(args.playlist)
    if not path:
        print(f"Playlist not found: {args.playlist}")
        sys.exit(1)

    # Validate track exists
    track_dir = OUTPUT_DIR / args.track
    if not track_dir.exists():
        print(f"Track not found in output: {args.track}")
        sys.exit(1)

    data = parse_playlist(path)

    if args.track in data["tracks"]:
        print(f"Track already in playlist: {args.track}")
        return

    if args.position and 1 <= args.position <= len(data["tracks"]) + 1:
        data["tracks"].insert(args.position - 1, args.track)
    else:
        data["tracks"].append(args.track)

    write_playlist(path, data)
    print(f"Added {args.track} to {data['title']}")


def cmd_remove(args):
    """Remove a track from a playlist."""
    path = find_playlist(args.playlist)
    if not path:
        print(f"Playlist not found: {args.playlist}")
        sys.exit(1)

    data = parse_playlist(path)

    if args.track not in data["tracks"]:
        print(f"Track not in playlist: {args.track}")
        sys.exit(1)

    data["tracks"].remove(args.track)
    write_playlist(path, data)
    print(f"Removed {args.track} from {data['title']}")


def cmd_list(args):
    """List all playlists."""
    PLAYLISTS_DIR.mkdir(exist_ok=True)
    playlists = sorted(PLAYLISTS_DIR.glob("*.md"))

    if not playlists:
        print("No playlists found.")
        return

    for p in playlists:
        data = parse_playlist(p)
        track_count = len(data["tracks"])
        meta = []
        if data["date"]:
            meta.append(data["date"])
        if data["venue"]:
            meta.append(data["venue"])
        meta_str = f" ({', '.join(meta)})" if meta else ""
        print(f"  {p.stem}  {data['title']}{meta_str}  [{track_count} tracks]")


def cmd_show(args):
    """Show playlist details with track durations."""
    path = find_playlist(args.playlist)
    if not path:
        print(f"Playlist not found: {args.playlist}")
        sys.exit(1)

    data = parse_playlist(path)

    print(f"\n  {data['title']}")
    if data["date"]:
        print(f"  Date:  {data['date']}")
    if data["venue"]:
        print(f"  Venue: {data['venue']}")
    if data["notes"]:
        print(f"  Notes: {data['notes']}")
    print()

    total_seconds = 0
    for i, track in enumerate(data["tracks"], 1):
        duration = get_track_duration(track)
        if duration:
            total_seconds += duration
            mins = int(duration // 60)
            secs = int(duration % 60)
            # Extract key from track name
            parts = track.rsplit("_", 1)
            key = parts[-1] if len(parts) > 1 else "?"
            print(f"  {i:3d}. {track:<45s}  {mins}:{secs:02d}  {key}")
        else:
            print(f"  {i:3d}. {track:<45s}  --:--  MISSING")

    total_mins = int(total_seconds // 60)
    total_secs = int(total_seconds % 60)
    print(f"\n  {len(data['tracks'])} tracks, {total_mins}:{total_secs:02d} total")


def cmd_validate(args):
    """Check all tracks in a playlist exist in output."""
    path = find_playlist(args.playlist)
    if not path:
        print(f"Playlist not found: {args.playlist}")
        sys.exit(1)

    data = parse_playlist(path)
    missing = []

    for track in data["tracks"]:
        track_dir = OUTPUT_DIR / track
        if not track_dir.exists():
            missing.append(track)
            print(f"  MISSING: {track}")
        else:
            mix = track_dir / f"4_Mix_{track}.wav"
            if not mix.exists():
                print(f"  NO MIX: {track}")
            else:
                print(f"      OK: {track}")

    if missing:
        print(f"\n{len(missing)} track(s) missing from output/")
        sys.exit(1)
    else:
        print(f"\nAll {len(data['tracks'])} tracks validated.")


def main():
    parser = argparse.ArgumentParser(description="Manage DJ playlists")
    sub = parser.add_subparsers(dest="command")

    p_new = sub.add_parser("new", help="Create a new playlist")
    p_new.add_argument("name", help="Playlist name")
    p_new.add_argument("--date", help="Event date (YYYY-MM-DD)")
    p_new.add_argument("--venue", help="Venue name")
    p_new.add_argument("--notes", help="Notes/theme description")

    p_add = sub.add_parser("add", help="Add a track to a playlist")
    p_add.add_argument("playlist", help="Playlist name or slug")
    p_add.add_argument("track", help="Track name (output folder name)")
    p_add.add_argument("--position", type=int, help="Insert at position N")

    p_rm = sub.add_parser("remove", help="Remove a track from a playlist")
    p_rm.add_argument("playlist", help="Playlist name or slug")
    p_rm.add_argument("track", help="Track name to remove")

    sub.add_parser("list", help="List all playlists")

    p_show = sub.add_parser("show", help="Show playlist with durations")
    p_show.add_argument("playlist", help="Playlist name or slug")

    p_val = sub.add_parser("validate", help="Validate all tracks exist")
    p_val.add_argument("playlist", help="Playlist name or slug")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "new": cmd_new,
        "add": cmd_add,
        "remove": cmd_remove,
        "list": cmd_list,
        "show": cmd_show,
        "validate": cmd_validate,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
