#!/usr/bin/env python3
"""Download images from URLs into a project's source directory."""

import sys
import os
import requests
from urllib.parse import urlparse
from pathlib import Path

def fetch_images(project_name, urls):
    source_dir = Path(__file__).parent.parent.parent / "projects" / project_name / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    existing = list(source_dir.iterdir())
    start_index = len(existing)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    }

    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue

        ext = Path(urlparse(url).path).suffix or ".jpg"
        filename = f"image{start_index + i}{ext}"
        filepath = source_dir / filename

        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            filepath.write_bytes(r.content)
            print(f"  saved {filename} ({len(r.content) // 1024}kb)")
        except Exception as e:
            print(f"  FAILED {url}: {e}")

    print(f"\ndone. {source_dir}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python fetch_images.py <project_name> <url1> [url2] ...")
        sys.exit(1)

    project = sys.argv[1]
    urls = sys.argv[2:]
    fetch_images(project, urls)
