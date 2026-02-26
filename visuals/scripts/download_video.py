#!/usr/bin/env python3
"""
Visual Asset Video Downloader

Downloads video from YouTube URLs using yt-dlp.
Same workflow as the audio downloader — queue file + direct URL support.
"""

import argparse
import subprocess
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses" / "source" / "video"
QUEUE_FILE = Path(__file__).parent.parent / "video_queue.md"


def get_video_title(url: str, use_cookies: bool = False) -> str:
    cmd = ["yt-dlp", "--get-title"]
    if use_cookies:
        cmd.extend(["--cookies-from-browser", "chrome"])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def download_video(url: str, output_dir: Path = ASSETS_DIR, use_cookies: bool = False) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
    ]
    if use_cookies:
        cmd.extend(["--cookies-from-browser", "chrome"])
    cmd.extend(["-o", str(output_dir / "%(title)s.%(ext)s"), url])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error downloading: {result.stderr}")
        return None

    output = result.stdout + result.stderr

    for line in output.split('\n'):
        if '[Merger] Merging formats into' in line:
            filename = line.split('into "')[1].rstrip('"')
            return Path(filename)
        if '[download] Destination:' in line:
            filename = line.split('Destination:')[1].strip()
            return Path(filename)

    for line in output.split('\n'):
        if 'has already been downloaded' in line:
            path_part = line.split('[download]')[1].split('has already been downloaded')[0].strip()
            return Path(path_part)

    # Fallback: find most recent mp4 in output dir
    mp4s = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if mp4s:
        return mp4s[0]

    return None


def is_downloadable_url(url: str) -> bool:
    return 'youtube.com/results' not in url and url.startswith('http')


def parse_queue_file() -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
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
            not_ready.append((current_title, None))
            current_title = None

    if current_title and current_section == 'pending':
        not_ready.append((current_title, None))

    return ready, not_ready, downloaded


def write_queue_file(ready, not_ready, downloaded):
    lines = ["# Video Asset Queue", "", "## To Download", ""]
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
    ready, not_ready, downloaded = parse_queue_file()

    if not_ready:
        print(f"{len(not_ready)} video(s) still need URLs")

    if not ready:
        if not_ready:
            print("No videos ready to download. Add YouTube URLs first.")
        else:
            print("No videos in queue.")
        return

    print(f"{len(ready)} video(s) ready to download\n")

    for orig_title, url in ready[:]:
        title = orig_title or get_video_title(url, use_cookies)
        print(f"Downloading: {title or url}")
        result = download_video(url, use_cookies=use_cookies)
        if result:
            print(f"  Saved: {result.name}")
            ready.remove((orig_title, url))
            downloaded.append((title or result.stem, url))
            write_queue_file(ready, not_ready, downloaded)
        else:
            print(f"  Failed!")

    print(f"\nDone. {len(downloaded)} downloaded, {len(ready)} failed, {len(not_ready)} awaiting URLs.")


def main():
    parser = argparse.ArgumentParser(description="Download video assets from YouTube")
    parser.add_argument("urls", nargs="*", help="YouTube URLs to download")
    parser.add_argument("--queue", "-q", action="store_true",
                        help="Download all from video_queue.md")
    parser.add_argument("--cookies", "-c", action="store_true",
                        help="Use Chrome cookies (for age-restricted videos)")
    parser.add_argument("--output", "-o", type=Path, default=ASSETS_DIR,
                        help="Output directory (default: project source/video)")
    args = parser.parse_args()

    if args.queue or not args.urls:
        download_from_queue(use_cookies=args.cookies)
        return

    for url in args.urls:
        print(f"Downloading: {url}")
        title = get_video_title(url, args.cookies)
        result = download_video(url, output_dir=args.output, use_cookies=args.cookies)
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
