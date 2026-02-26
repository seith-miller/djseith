#!/usr/bin/env python3
"""
DJ Seith Track Audition Server

Local web UI for auditioning tracks: click YouTube search links,
pick the right version, paste the video URL back. Saves to to_get.md.

Usage: python audition.py
"""

import html
import json
import re
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

QUEUE_FILE = Path(__file__).parent.parent / "to_get.md"
PORT = 8713


def parse_queue():
    """Parse to_get.md into structured data."""
    if not QUEUE_FILE.exists():
        return {"pending": [], "downloaded": []}

    content = QUEUE_FILE.read_text()
    pending = []
    downloaded = []

    current_section = None
    current_title = None

    for line in content.splitlines():
        line = line.rstrip()
        if "## To Download" in line:
            current_section = "pending"
        elif "## Downloaded" in line:
            current_section = "done"
        elif line.startswith("## "):
            current_section = None
        elif line.startswith("- "):
            text = line[2:].strip()
            if text.startswith("http"):
                if current_section == "pending":
                    pending.append({"title": None, "url": text})
                elif current_section == "done":
                    downloaded.append({"title": None, "url": text})
            else:
                current_title = text
        elif line.strip().startswith("http"):
            url = line.strip()
            if current_section == "pending":
                pending.append({"title": current_title, "url": url})
                current_title = None
            elif current_section == "done":
                downloaded.append({"title": current_title, "url": url})
                current_title = None

    # Leftover title with no URL
    if current_title and current_section == "pending":
        pending.append({"title": current_title, "url": None})

    return {"pending": pending, "downloaded": downloaded}


def save_queue(pending, downloaded):
    """Write structured data back to to_get.md."""
    lines = ["# Track Queue", "", "## To Download", ""]
    for track in pending:
        title = track.get("title")
        url = track.get("url")
        if title:
            lines.append(f"- {title}")
            if url:
                lines.append(f"  {url}")
        elif url:
            lines.append(f"- {url}")
    lines.extend(["", "## Downloaded", ""])
    for track in downloaded:
        title = track.get("title")
        url = track.get("url")
        if title:
            lines.append(f"- {title}")
        if url:
            lines.append(f"  {url}")
    lines.append("")
    QUEUE_FILE.write_text("\n".join(lines))


def is_search_url(url):
    return url and "youtube.com/results" in url


def is_video_url(url):
    return url and ("watch?v=" in url or "youtu.be/" in url)


def parse_title(title_str):
    """Extract artist, track name, and duration from title string."""
    if not title_str:
        return {"artist": "", "track": title_str or "", "duration": ""}
    m = re.match(r"^(.+?)\s*\((\d+:\d+)\)\s*$", title_str)
    duration = m.group(2) if m else ""
    name = m.group(1).strip() if m else title_str
    parts = name.split(" - ", 1)
    if len(parts) == 2:
        return {"artist": parts[0].strip(), "track": parts[1].strip(), "duration": duration}
    return {"artist": "", "track": name, "duration": duration}


PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DJ Seith - Track Audition</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0a0a0a; color: #e0e0e0;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    padding: 20px; max-width: 1100px; margin: 0 auto;
  }
  h1 { color: #c0c0c0; font-size: 1.4em; margin-bottom: 4px; font-weight: 400; }
  .subtitle { color: #666; font-size: 0.85em; margin-bottom: 20px; }
  .stats {
    display: flex; gap: 20px; margin-bottom: 24px;
    font-size: 0.85em; color: #888;
  }
  .stats span { display: inline-flex; align-items: center; gap: 6px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot-pending { background: #555; }
  .dot-ready { background: #4a9; }
  .dot-done { background: #346; }

  .track {
    border: 1px solid #1a1a1a; border-radius: 6px;
    padding: 12px 16px; margin-bottom: 8px;
    display: grid; grid-template-columns: 1fr auto;
    gap: 8px; align-items: center;
    transition: border-color 0.2s;
  }
  .track:hover { border-color: #333; }
  .track.ready { border-left: 3px solid #4a9; }
  .track.pending { border-left: 3px solid #555; }

  .track-info { min-width: 0; }
  .track-artist { color: #888; font-size: 0.8em; }
  .track-name { color: #ddd; font-size: 0.95em; margin: 2px 0; }
  .track-duration { color: #555; font-size: 0.75em; }

  .track-actions {
    display: flex; align-items: center; gap: 8px;
    flex-shrink: 0;
  }

  .url-input {
    background: #141414; border: 1px solid #2a2a2a; border-radius: 4px;
    color: #ccc; padding: 6px 10px; font-family: inherit; font-size: 0.8em;
    width: 340px; outline: none; transition: border-color 0.2s;
  }
  .url-input:focus { border-color: #4a9; }
  .url-input.has-video { border-color: #4a9; color: #4a9; }

  a.search-btn {
    display: inline-flex; align-items: center; gap: 4px;
    background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 4px;
    color: #aaa; padding: 6px 12px; font-size: 0.8em;
    text-decoration: none; white-space: nowrap;
    transition: background 0.2s, color 0.2s;
  }
  a.search-btn:hover { background: #222; color: #ddd; }

  .btn-remove {
    background: none; border: 1px solid #2a2a2a; border-radius: 4px;
    color: #644; padding: 6px 8px; cursor: pointer; font-size: 0.8em;
    transition: color 0.2s, border-color 0.2s;
  }
  .btn-remove:hover { color: #a66; border-color: #a66; }

  .save-bar {
    position: sticky; bottom: 0;
    background: #0a0a0a; border-top: 1px solid #1a1a1a;
    padding: 12px 0; display: flex; align-items: center; gap: 16px;
  }
  .btn-save {
    background: #1a3a2a; border: 1px solid #2a5a3a; border-radius: 4px;
    color: #6c6; padding: 8px 24px; cursor: pointer;
    font-family: inherit; font-size: 0.9em;
    transition: background 0.2s;
  }
  .btn-save:hover { background: #2a4a3a; }
  .btn-save:disabled { opacity: 0.4; cursor: default; }
  .save-status { color: #555; font-size: 0.8em; }

  .section-header {
    color: #555; font-size: 0.8em; text-transform: uppercase;
    letter-spacing: 1px; margin: 24px 0 8px; padding-bottom: 4px;
    border-bottom: 1px solid #1a1a1a;
  }
  .downloaded-list { margin-top: 8px; }
  .downloaded-item {
    color: #446; font-size: 0.8em; padding: 4px 0;
    border-bottom: 1px solid #0f0f0f;
  }
</style>
</head>
<body>

<h1>DJ Seith - Track Audition</h1>
<p class="subtitle">Click search to find the right version, paste the video URL</p>

<div class="stats">
  <span><span class="dot dot-ready"></span> <span id="stat-ready">0</span> ready</span>
  <span><span class="dot dot-pending"></span> <span id="stat-pending">0</span> pending</span>
  <span><span class="dot dot-done"></span> <span id="stat-done">0</span> downloaded</span>
</div>

<div id="tracks"></div>

<div class="save-bar">
  <button class="btn-save" id="save-btn" onclick="save()">Save</button>
  <span class="save-status" id="save-status"></span>
</div>

<div class="section-header" id="downloaded-header" style="display:none">Downloaded</div>
<div class="downloaded-list" id="downloaded"></div>

<script>
const DATA = __DATA__;

let dirty = false;

function render() {
  const container = document.getElementById('tracks');
  container.innerHTML = '';

  let readyCount = 0, pendingCount = 0;

  DATA.pending.forEach((t, i) => {
    const info = parseTitle(t.title);
    const hasVideo = isVideo(t.url);
    if (hasVideo) readyCount++; else pendingCount++;

    const div = document.createElement('div');
    div.className = 'track ' + (hasVideo ? 'ready' : 'pending');
    div.innerHTML = `
      <div class="track-info">
        ${info.artist ? `<div class="track-artist">${esc(info.artist)}</div>` : ''}
        <div class="track-name">${esc(info.track)}</div>
        ${info.duration ? `<div class="track-duration">${esc(info.duration)}</div>` : ''}
      </div>
      <div class="track-actions">
        ${t.searchUrl ? `<a class="search-btn" href="${esc(t.searchUrl)}" target="_blank">Search</a>` : ''}
        <input class="url-input ${hasVideo ? 'has-video' : ''}"
               placeholder="paste video URL"
               value="${esc(t.url && !isSearch(t.url) ? t.url : '')}"
               data-idx="${i}"
               onchange="updateUrl(this)" onpaste="setTimeout(()=>updateUrl(this),0)">
        <button class="btn-remove" onclick="removeTrack(${i})" title="Remove">&times;</button>
      </div>
    `;
    container.appendChild(div);
  });

  document.getElementById('stat-ready').textContent = readyCount;
  document.getElementById('stat-pending').textContent = pendingCount;
  document.getElementById('stat-done').textContent = DATA.downloaded.length;

  // Downloaded section
  const dlContainer = document.getElementById('downloaded');
  const dlHeader = document.getElementById('downloaded-header');
  if (DATA.downloaded.length) {
    dlHeader.style.display = '';
    dlContainer.innerHTML = DATA.downloaded.map(t =>
      `<div class="downloaded-item">${esc(t.title || t.url || '?')}</div>`
    ).join('');
  } else {
    dlHeader.style.display = 'none';
    dlContainer.innerHTML = '';
  }
}

function parseTitle(s) {
  if (!s) return {artist: '', track: '', duration: ''};
  const m = s.match(/^(.+?)\\s*\\((\\d+:\\d+)\\)\\s*$/);
  const dur = m ? m[2] : '';
  const name = m ? m[1].trim() : s;
  const parts = name.split(' - ');
  if (parts.length >= 2) return {artist: parts[0].trim(), track: parts.slice(1).join(' - ').trim(), duration: dur};
  return {artist: '', track: name, duration: dur};
}

function isSearch(url) { return url && url.includes('youtube.com/results'); }
function isVideo(url) { return url && (url.includes('watch?v=') || url.includes('youtu.be/')); }

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function updateUrl(el) {
  const idx = parseInt(el.dataset.idx);
  const val = el.value.trim();
  if (val) {
    DATA.pending[idx].url = val;
  } else {
    // Restore search URL if cleared
    DATA.pending[idx].url = DATA.pending[idx].searchUrl || null;
  }
  dirty = true;
  document.getElementById('save-status').textContent = 'unsaved changes';
  render();
}

function removeTrack(idx) {
  DATA.pending.splice(idx, 1);
  dirty = true;
  document.getElementById('save-status').textContent = 'unsaved changes';
  render();
}

function save() {
  const btn = document.getElementById('save-btn');
  const status = document.getElementById('save-status');
  btn.disabled = true;
  status.textContent = 'saving...';

  fetch('/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(DATA)
  })
  .then(r => r.json())
  .then(d => {
    dirty = false;
    status.textContent = 'saved';
    btn.disabled = false;
    setTimeout(() => { if (!dirty) status.textContent = ''; }, 2000);
  })
  .catch(e => {
    status.textContent = 'save failed: ' + e;
    btn.disabled = false;
  });
}

// Warn on close with unsaved changes
window.addEventListener('beforeunload', e => {
  if (dirty) { e.preventDefault(); e.returnValue = ''; }
});

// Pre-process: separate search URLs from video URLs for display
DATA.pending.forEach(t => {
  if (isSearch(t.url)) {
    t.searchUrl = t.url;
    t.url = null;
  } else {
    // Generate search URL from title for the search button
    if (t.title) {
      const name = t.title.replace(/\\s*\\(\\d+:\\d+\\)\\s*$/, '');
      t.searchUrl = 'https://www.youtube.com/results?search_query=' + encodeURIComponent(name);
    }
  }
});

render();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        data = parse_queue()
        page = PAGE_HTML.replace("__DATA__", json.dumps(data))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())

    def do_POST(self):
        if self.path != "/save":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        data = json.loads(body)
        save_queue(data.get("pending", []), data.get("downloaded", []))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def log_message(self, fmt, *args):
        pass  # Quiet


def main():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Audition server at {url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
