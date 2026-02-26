#!/usr/bin/env python3
"""
DJ Seith Audio Downloader

Downloads audio from YouTube URLs using yt-dlp.
"""

import argparse
import subprocess
from pathlib import Path

STAGING_DIR = Path(__file__).parent.parent / "staging"
QUEUE_FILE = Path(__file__).parent.parent / "to_get.md"


def get_video_title(url: str, use_cookies: bool = False) -> str:
    """Get video title from URL using yt-dlp."""
    cmd = ["yt-dlp", "--get-title"]
    if use_cookies:
        cmd.extend(["--cookies-from-browser", "chrome"])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def download_audio(url: str, output_dir: Path = STAGING_DIR, use_cookies: bool = False) -> Path | None:
    """Download audio from URL using yt-dlp."""
    output_dir.mkdir(exist_ok=True)

    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
    ]
    if use_cookies:
        cmd.extend(["--cookies-from-browser", "chrome"])
    cmd.extend(["-o", str(output_dir / "%(title)s.%(ext)s"), url])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error downloading: {result.stderr}")
        return None

    output = result.stdout + result.stderr

    # Check for new download
    for line in output.split('\n'):
        if '[ExtractAudio] Destination:' in line:
            filename = line.split('Destination:')[1].strip()
            return Path(filename)

    # Check for already downloaded
    for line in output.split('\n'):
        if 'has already been downloaded' in line:
            # Extract path from: [download] /path/to/file.mp3 has already been downloaded
            path_part = line.split('[download]')[1].split('has already been downloaded')[0].strip()
            return Path(path_part)

    return None


def is_downloadable_url(url: str) -> bool:
    """Check if URL is a downloadable video (not a search page)."""
    return 'youtube.com/results' not in url and url.startswith('http')


def parse_queue_file() -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    """Parse to_get.md and return (ready, not_ready, downloaded) lists of (title, url).

    ready: tracks with downloadable video URLs
    not_ready: tracks with search URLs or no URL (need user audition)
    downloaded: completed tracks
    """
    if not QUEUE_FILE.exists():
        return [], [], []

    content = QUEUE_FILE.read_text()
    ready = []
    not_ready = []
    downloaded = []

    current_section = None
    current_title = None

    for line in content.splitlines():
        line = line.rstrip()
        if '## To Download' in line:
            current_section = 'pending'
        elif '## Downloaded' in line:
            current_section = 'done'
        elif line.startswith('## '):
            current_section = None
        elif line.startswith('- '):
            text = line[2:].strip()
            if text.startswith('http'):
                if current_section == 'pending':
                    if is_downloadable_url(text):
                        ready.append((None, text))
                    else:
                        not_ready.append((None, text))
            else:
                current_title = text
        elif line.strip().startswith('http'):
            url = line.strip()
            if current_section == 'pending':
                if is_downloadable_url(url):
                    ready.append((current_title, url))
                else:
                    not_ready.append((current_title, url))
                current_title = None
            elif current_section == 'done':
                downloaded.append((current_title, url))
                current_title = None
        elif current_title and current_section == 'pending' and not line.strip():
            # Title with no URL yet
            not_ready.append((current_title, None))
            current_title = None

    # Leftover title with no URL
    if current_title and current_section == 'pending':
        not_ready.append((current_title, None))

    return ready, not_ready, downloaded


def write_queue_file(ready: list[tuple[str, str]], not_ready: list[tuple[str, str]],
                     downloaded: list[tuple[str, str]]):
    """Write updated queue file."""
    lines = ["# Track Queue", "", "## To Download", ""]
    # Write ready-to-download entries first, then not-ready
    for title, url in ready + not_ready:
        if title:
            lines.append(f"- {title}")
            if url:
                lines.append(f"  {url}")
        elif url:
            lines.append(f"- {url}")
    lines.extend(["", "## Downloaded", ""])
    for title, url in downloaded:
        lines.append(f"- {title}")
        lines.append(f"  {url}")
    lines.append("")
    QUEUE_FILE.write_text('\n'.join(lines))


def download_from_queue(use_cookies: bool = False):
    """Download all pending tracks from queue file."""
    ready, not_ready, downloaded = parse_queue_file()

    if not_ready:
        print(f"{len(not_ready)} track(s) still need audition (search URLs or no URL)")

    if not ready:
        if not_ready:
            print("No tracks ready to download. Replace search URLs with video URLs first.")
        else:
            print("No tracks in queue.")
        return

    print(f"{len(ready)} track(s) ready to download\n")

    for orig_title, url in ready[:]:
        title = orig_title or get_video_title(url, use_cookies)
        print(f"Downloading: {title or url}")
        result = download_audio(url, use_cookies=use_cookies)
        if result:
            print(f"  Saved: {result.name}")
            ready.remove((orig_title, url))
            downloaded.append((title or result.stem, url))
            write_queue_file(ready, not_ready, downloaded)
        else:
            print(f"  Failed!")

    print(f"\nDone. {len(downloaded)} downloaded, {len(ready)} failed, {len(not_ready)} awaiting audition.")


def main():
    parser = argparse.ArgumentParser(description="Download audio from YouTube")
    parser.add_argument("urls", nargs="*", help="YouTube URLs to download")
    parser.add_argument("--queue", "-q", action="store_true",
                        help="Download all from to_get.md queue")
    parser.add_argument("--cookies", "-c", action="store_true",
                        help="Use Chrome cookies (for age-restricted videos)")
    args = parser.parse_args()

    if args.queue or not args.urls:
        download_from_queue(use_cookies=args.cookies)
        return

    # Direct URL download
    for url in args.urls:
        print(f"Downloading: {url}")
        title = get_video_title(url, args.cookies)
        result = download_audio(url, use_cookies=args.cookies)
        if result:
            print(f"  Saved: {result.name}")
            if QUEUE_FILE.exists():
                ready, not_ready, downloaded = parse_queue_file()
                ready = [(t, u) for t, u in ready if u != url]
                not_ready = [(t, u) for t, u in not_ready if u != url]
                if not any(u == url for _, u in downloaded):
                    downloaded.append((title or result.stem, url))
                write_queue_file(ready, not_ready, downloaded)


if __name__ == "__main__":
    main()
