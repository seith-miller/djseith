#!/usr/bin/env python3
"""Web interface to tag shots with descriptive labels.

Shows reviewed shots (favorites first, then ok) one at a time.
Toggle tags with number keys 1-9. Press Space/Enter to advance.

Tags are stored in review_state.json under "tags": {"shot.mp4": ["eddie", "night"], ...}
"""

import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote

SHOTS_DIR  = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses" / "shots"
STATE_FILE = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses" / "data" / "review_state.json"
PORT = 8112

TAG_VOCAB = [
    "eddie",    # 1
    "dancing",  # 2
    "white",    # 3
    "black",    # 4
    "night",    # 5
    "day",      # 6
    "street",   # 7
    "horror",   # 8
    "sex",      # 9
]


def load_state() -> dict:
    defaults = {"reviewed": {}, "to_resplit": [], "trashed": [], "favorites": [], "tags": {}}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        for k, v in defaults.items():
            state.setdefault(k, v)
        return state
    return defaults


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_taggable_shots(state: dict) -> list[str]:
    """Return shots eligible for tagging: favorites first, then ok."""
    reviewed = state["reviewed"]
    favs = sorted(k for k, v in reviewed.items() if v == "favorite")
    oks  = sorted(k for k, v in reviewed.items() if v == "ok")
    return favs + oks


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Shot Tagger</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #111; color: #eee; font-family: monospace;
         display: flex; flex-direction: column; align-items: center;
         height: 100vh; padding: 20px; }
  h1 { font-size: 16px; color: #888; margin-bottom: 8px; }
  #progress { color: #f90; margin-bottom: 6px; font-size: 14px; }
  #filename { color: #aaa; margin-bottom: 8px; font-size: 13px;
              word-break: break-all; max-width: 80vw; text-align: center; }
  #status-badge { font-size: 12px; margin-bottom: 8px; }
  .fav { color: #c90; }
  .ok-badge { color: #2a2; }
  video { max-width: 90vw; max-height: 45vh; background: #000;
          border: 2px solid #333; border-radius: 4px; }
  .tags { display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap;
          justify-content: center; max-width: 800px; }
  .tag { padding: 10px 18px; font-size: 15px; font-family: monospace;
         border: 2px solid #444; border-radius: 6px; cursor: pointer;
         transition: all 0.15s; user-select: none; background: #222; color: #888; }
  .tag:hover { border-color: #666; }
  .tag.active { background: #0a5; color: #fff; border-color: #0c7; }
  .tag .key { color: #f90; font-weight: bold; margin-right: 6px; }
  .tag.active .key { color: #fff; }
  .nav { margin-top: 16px; display: flex; gap: 12px; align-items: center; }
  .nav button { padding: 10px 24px; font-size: 15px; font-family: monospace;
                border: none; border-radius: 6px; cursor: pointer;
                background: #36a; color: #fff; }
  .nav button:hover { background: #47b; }
  .nav button:active { transform: scale(0.95); }
  .nav button.skip { background: #555; }
  .nav button.skip:hover { background: #666; }
  #count { color: #666; font-size: 13px; margin-top: 8px; }
  #done { display: none; font-size: 24px; color: #0f0; margin-top: 40px; }
  #flash { position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%);
           font-size: 48px; font-weight: bold; opacity: 0; pointer-events: none;
           transition: opacity 0.15s; text-shadow: 0 0 20px rgba(0,0,0,0.8); }
  .filter-row { margin-bottom: 12px; display: flex; gap: 8px; align-items: center; }
  .filter-row label { color: #888; font-size: 13px; }
  .filter-row select { background: #222; color: #eee; border: 1px solid #444;
                        padding: 4px 8px; font-family: monospace; border-radius: 4px; }
</style>
</head>
<body>
  <h1>Shot Tagger</h1>
  <div class="filter-row">
    <label>Show:</label>
    <select id="filter" onchange="applyFilter()">
      <option value="all">All reviewed</option>
      <option value="untagged">Untagged only</option>
      <option value="tagged">Tagged only</option>
    </select>
    <label id="filter-count" style="color:#f90"></label>
  </div>
  <div id="progress"></div>
  <div id="filename"></div>
  <div id="status-badge"></div>
  <video id="player" autoplay loop muted playsinline></video>
  <div class="tags" id="tag-buttons"></div>
  <div class="nav">
    <button class="skip" onclick="go(-1)">&larr; Prev</button>
    <button onclick="go(1)">Next &rarr;</button>
  </div>
  <div id="count"></div>
  <div id="done">All shots tagged!</div>
  <div id="flash"></div>

<script>
const allShots = __SHOTS_JSON__;
const tags     = __TAGS_JSON__;
const reviewed = __REVIEWED_JSON__;
const vocab    = __VOCAB_JSON__;

let filtered = [...allShots];
let idx = 0;

function applyFilter() {
  const f = document.getElementById('filter').value;
  if (f === 'untagged') {
    filtered = allShots.filter(s => !tags[s] || tags[s].length === 0);
  } else if (f === 'tagged') {
    filtered = allShots.filter(s => tags[s] && tags[s].length > 0);
  } else {
    filtered = [...allShots];
  }
  idx = 0;
  document.getElementById('filter-count').textContent = filtered.length + ' shots';
  render();
}

function flash(text, color) {
  const el = document.getElementById('flash');
  el.textContent = text;
  el.style.color = color;
  el.style.opacity = 1;
  setTimeout(() => { el.style.opacity = 0; }, 250);
}

function buildTagButtons() {
  const container = document.getElementById('tag-buttons');
  container.innerHTML = '';
  vocab.forEach((tag, i) => {
    const el = document.createElement('div');
    el.className = 'tag';
    el.id = 'tag-' + tag;
    el.innerHTML = '<span class="key">' + (i+1) + '</span>' + tag;
    el.onclick = () => toggleTag(tag);
    container.appendChild(el);
  });
}

function render() {
  const total = filtered.length;
  const tagged = allShots.filter(s => tags[s] && tags[s].length > 0).length;
  document.getElementById('progress').textContent =
    tagged + ' / ' + allShots.length + ' tagged';

  if (filtered.length === 0) {
    document.getElementById('player').style.display = 'none';
    document.querySelector('.tags').style.display = 'none';
    document.querySelector('.nav').style.display = 'none';
    document.getElementById('filename').textContent = 'No shots match filter';
    return;
  }

  document.getElementById('player').style.display = '';
  document.querySelector('.tags').style.display = '';
  document.querySelector('.nav').style.display = '';

  if (idx < 0) idx = 0;
  if (idx >= filtered.length) idx = filtered.length - 1;

  const shot = filtered[idx];
  document.getElementById('filename').textContent = shot;
  document.getElementById('count').textContent = (idx+1) + ' / ' + filtered.length;

  const rv = reviewed[shot] || '';
  const badge = document.getElementById('status-badge');
  if (rv === 'favorite') {
    badge.innerHTML = '<span class="fav">&#9733; favorite</span>';
  } else if (rv === 'ok') {
    badge.innerHTML = '<span class="ok-badge">&#10003; ok</span>';
  } else {
    badge.textContent = rv;
  }

  const player = document.getElementById('player');
  player.pause();
  player.src = '/video/' + shot.split('/').map(encodeURIComponent).join('/');
  player.load();
  player.play().catch(() => {});

  // Update tag button states
  const active = tags[shot] || [];
  vocab.forEach(tag => {
    const el = document.getElementById('tag-' + tag);
    if (el) el.className = active.includes(tag) ? 'tag active' : 'tag';
  });
}

function toggleTag(tag) {
  if (filtered.length === 0) return;
  const shot = filtered[idx];
  if (!tags[shot]) tags[shot] = [];
  const i = tags[shot].indexOf(tag);
  if (i >= 0) {
    tags[shot].splice(i, 1);
    flash('-' + tag, '#c33');
  } else {
    tags[shot].push(tag);
    flash('+' + tag, '#0a5');
  }
  // Save to server
  fetch('/tag', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'shot=' + encodeURIComponent(shot) + '&tags=' + encodeURIComponent(JSON.stringify(tags[shot]))
  });
  render();
}

function go(delta) {
  idx += delta;
  render();
}

document.addEventListener('keydown', (e) => {
  const num = parseInt(e.key);
  if (num >= 1 && num <= vocab.length) {
    e.preventDefault();
    toggleTag(vocab[num - 1]);
    return;
  }
  if (e.key === ' ' || e.key === 'Enter' || e.key === 'ArrowRight') {
    e.preventDefault(); go(1);
  }
  if (e.key === 'ArrowLeft') {
    e.preventDefault(); go(-1);
  }
});

buildTagButtons();
document.getElementById('filter-count').textContent = filtered.length + ' shots';
render();
</script>
</body>
</html>"""


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            state = load_state()
            shots = get_taggable_shots(state)
            html = HTML_TEMPLATE.replace("__SHOTS_JSON__", json.dumps(shots))
            html = html.replace("__TAGS_JSON__", json.dumps(state["tags"]))
            html = html.replace("__REVIEWED_JSON__", json.dumps(state["reviewed"]))
            html = html.replace("__VOCAB_JSON__", json.dumps(TAG_VOCAB))
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        elif self.path.startswith("/video/"):
            rel = unquote(self.path[7:])
            fpath = SHOTS_DIR / rel
            if not fpath.exists():
                self.send_error(404)
                return
            size = fpath.stat().st_size
            range_header = self.headers.get("Range")
            if range_header:
                start, end = 0, size - 1
                match = range_header.replace("bytes=", "").split("-")
                start = int(match[0]) if match[0] else 0
                end = int(match[1]) if match[1] else size - 1
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
            else:
                start, length = 0, size
                self.send_response(200)
                self.send_header("Content-Length", str(size))
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(fpath, "rb") as f:
                f.seek(start)
                self.wfile.write(f.read(length))
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/tag":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            params = parse_qs(body)
            shot = params.get("shot", [""])[0]
            tag_list = json.loads(params.get("tags", ["[]"])[0])

            state = load_state()
            state["tags"][shot] = tag_list
            save_state(state)

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_error(404)


def main():
    state = load_state()
    shots = get_taggable_shots(state)
    tagged = sum(1 for s in shots if state["tags"].get(s))
    print(f"Shots: {len(shots)} taggable, {tagged} already tagged")
    print(f"Tags: {', '.join(TAG_VOCAB)}")
    print(f"Open http://localhost:{PORT}")
    print("Keys: 1-9 = toggle tags, Space/Right = next, Left = prev")
    print("Ctrl+C to stop\n")
    server = ThreadingHTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        state = load_state()
        tag_counts = {}
        for tag_list in state["tags"].values():
            for t in tag_list:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        total = sum(1 for v in state["tags"].values() if v)
        print(f"\n{total} shots tagged")
        if tag_counts:
            for t, c in sorted(tag_counts.items(), key=lambda x: -x[1]):
                print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
