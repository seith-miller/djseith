#!/usr/bin/env python3
"""Web interface to review shot splits. Plays one clip at a time.
Four actions via keyboard or buttons:
  J / Left  = One Shot (keep as-is)
  K / Right = Cut Into Smaller Shots (needs re-splitting)
  Down      = Trash (delete this shot)
  Up        = Favorite (flag for heavy use)
"""

import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote

SHOTS_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses" / "shots"
STATE_FILE = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses" / "data" / "review_state.json"
PORT = 8111


def get_all_shots() -> list[str]:
    shots = sorted(SHOTS_DIR.rglob("*.mp4"))
    return [str(s.relative_to(SHOTS_DIR)) for s in shots]


def load_state() -> dict:
    defaults = {"reviewed": {}, "to_resplit": [], "trashed": [], "favorites": []}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        for k, v in defaults.items():
            state.setdefault(k, v)
        return state
    return defaults


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Shot Review</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #111; color: #eee; font-family: monospace;
         display: flex; flex-direction: column; align-items: center;
         height: 100vh; padding: 20px; }
  h1 { font-size: 16px; color: #888; margin-bottom: 10px; }
  #progress { color: #f90; margin-bottom: 10px; font-size: 14px; }
  #filename { color: #aaa; margin-bottom: 10px; font-size: 13px; word-break: break-all; max-width: 80vw; text-align: center; }
  video { max-width: 90vw; max-height: 55vh; background: #000;
          border: 2px solid #333; border-radius: 4px; }
  .buttons { display: flex; gap: 16px; margin-top: 20px; flex-wrap: wrap; justify-content: center; }
  .btn-wrap { text-align: center; }
  button { padding: 14px 28px; font-size: 16px; font-family: monospace;
           border: none; border-radius: 6px; cursor: pointer;
           transition: transform 0.1s; min-width: 160px; }
  button:active { transform: scale(0.95); }
  #btn-ok { background: #2a2; color: #fff; }
  #btn-ok:hover { background: #3b3; }
  #btn-cut { background: #c33; color: #fff; }
  #btn-cut:hover { background: #d44; }
  #btn-trash { background: #555; color: #fff; }
  #btn-trash:hover { background: #777; }
  #btn-fav { background: #c90; color: #111; }
  #btn-fav:hover { background: #da0; }
  #done { display: none; font-size: 24px; color: #0f0; margin-top: 40px; }
  .key-hint { font-size: 11px; color: #666; margin-top: 4px; }
  #flash { position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%);
           font-size: 48px; font-weight: bold; opacity: 0; pointer-events: none;
           transition: opacity 0.15s; text-shadow: 0 0 20px rgba(0,0,0,0.8); }
</style>
</head>
<body>
  <h1>Shot Review</h1>
  <div id="progress"></div>
  <div id="filename"></div>
  <video id="player" autoplay loop muted playsinline></video>
  <div class="buttons">
    <div class="btn-wrap">
      <button id="btn-ok" onclick="decide('ok')">One Shot</button>
      <div class="key-hint">[ J ] or [ &larr; ]</div>
    </div>
    <div class="btn-wrap">
      <button id="btn-cut" onclick="decide('resplit')">Cut Smaller</button>
      <div class="key-hint">[ K ] or [ &rarr; ]</div>
    </div>
    <div class="btn-wrap">
      <button id="btn-trash" onclick="decide('trash')">Trash</button>
      <div class="key-hint">[ &darr; ]</div>
    </div>
    <div class="btn-wrap">
      <button id="btn-fav" onclick="decide('favorite')">Favorite</button>
      <div class="key-hint">[ &uarr; ]</div>
    </div>
  </div>
  <div id="done">All done! You can close this tab.</div>
  <div id="flash"></div>

<script>
let shots = __SHOTS_JSON__;
let reviewed = __REVIEWED_JSON__;
let idx = 0;
let busy = false;

while (idx < shots.length && reviewed[shots[idx]]) idx++;

function flash(text, color) {
  const el = document.getElementById('flash');
  el.textContent = text;
  el.style.color = color;
  el.style.opacity = 1;
  setTimeout(() => { el.style.opacity = 0; }, 300);
}

function render() {
  const total = shots.length;
  const done = Object.keys(reviewed).length;
  document.getElementById('progress').textContent =
    done + ' / ' + total + ' reviewed';

  if (idx >= shots.length) {
    document.getElementById('player').style.display = 'none';
    document.querySelector('.buttons').style.display = 'none';
    document.getElementById('filename').style.display = 'none';
    document.getElementById('done').style.display = 'block';
    return;
  }

  const shot = shots[idx];
  document.getElementById('filename').textContent = shot;
  const player = document.getElementById('player');
  player.pause();
  player.src = '/video/' + shot.split('/').map(encodeURIComponent).join('/');
  player.load();
  player.play().catch(() => {});
}

function decide(action) {
  if (busy || idx >= shots.length) return;
  busy = true;

  const shot = shots[idx];
  reviewed[shot] = action;

  const labels = {ok: 'OK', resplit: 'CUT', trash: 'TRASH', favorite: 'FAV'};
  const colors = {ok: '#2a2', resplit: '#c33', trash: '#888', favorite: '#c90'};
  flash(labels[action], colors[action]);

  fetch('/decide', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'shot=' + encodeURIComponent(shot) + '&action=' + action
  }).then(() => {
    idx++;
    while (idx < shots.length && reviewed[shots[idx]]) idx++;
    render();
    busy = false;
  }).catch(() => { busy = false; });
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'j' || e.key === 'J' || e.key === 'ArrowLeft')  { e.preventDefault(); decide('ok'); }
  if (e.key === 'k' || e.key === 'K' || e.key === 'ArrowRight') { e.preventDefault(); decide('resplit'); }
  if (e.key === 'ArrowDown')  { e.preventDefault(); decide('trash'); }
  if (e.key === 'ArrowUp')    { e.preventDefault(); decide('favorite'); }
});

render();
</script>
</body>
</html>"""


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            shots = get_all_shots()
            state = load_state()
            html = HTML_TEMPLATE.replace("__SHOTS_JSON__", json.dumps(shots))
            html = html.replace("__REVIEWED_JSON__", json.dumps(state["reviewed"]))
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
            # Support range requests for smooth video playback
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
        if self.path == "/decide":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            params = parse_qs(body)
            shot = params.get("shot", [""])[0]
            action = params.get("action", [""])[0]

            state = load_state()
            state["reviewed"][shot] = action
            if action == "resplit" and shot not in state["to_resplit"]:
                state["to_resplit"].append(shot)
            if action == "trash" and shot not in state["trashed"]:
                state["trashed"].append(shot)
            if action == "favorite" and shot not in state["favorites"]:
                state["favorites"].append(shot)
            save_state(state)

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_error(404)


def main():
    shots = get_all_shots()
    state = load_state()
    remaining = len(shots) - len(state["reviewed"])
    print(f"Shots: {len(shots)} total, {len(state['reviewed'])} reviewed, {remaining} remaining")
    print(f"Open http://localhost:{PORT}")
    print("Keys: J/Left = One Shot, K/Right = Cut, Down = Trash, Up = Favorite")
    print("Ctrl+C to stop\n")
    server = ThreadingHTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        state = load_state()
        r = state["reviewed"]
        counts = {}
        for v in r.values():
            counts[v] = counts.get(v, 0) + 1
        print(f"\n{len(r)} reviewed: {counts}")
        if state["to_resplit"]:
            print(f"{len(state['to_resplit'])} to re-split")
        if state["trashed"]:
            print(f"{len(state['trashed'])} trashed")
        if state["favorites"]:
            print(f"{len(state['favorites'])} favorites")


if __name__ == "__main__":
    main()
