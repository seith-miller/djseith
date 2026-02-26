#!/usr/bin/env python3
"""Generate Interzone XV Instagram video — INVERTED: white bg, black text, black funeral border.

Usage:
  python make_video_white.py              # full quality render
  python make_video_white.py --preview    # fast 10fps preview (~15s)

Format: 1080x1920 (9:16) — Instagram Reels / Stories / TikTok.
Safe zone: top 250px, bottom 320px clear of critical content.
Content zone: y=250 to y=1600.
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path
import argparse
import json
import sys

PROJECT_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses"
import numpy as np
import subprocess
import cv2

SRC = PROJECT_DIR / "source" / "stills"
OUT = PROJECT_DIR / "output" / "promo"
OUT.mkdir(parents=True, exist_ok=True)

AUDIO_PATH = Path("/Users/smiller/Claude-Workspace/DJ_SEITH/audio/loops/Einstürzende Neubauten  - Feurio (loop).wav")

W, H = 1080, 1920  # 9:16 Reels/Stories/TikTok

# Safe zone boundaries (UI overlays)
SAFE_TOP = 250
SAFE_BOTTOM = 320

# === Load detected beat times ===
BEAT_DATA = json.load(open("/tmp/feurio_beats.json"))
BEAT_TIMES = BEAT_DATA["beat_times"]
DURATION = BEAT_DATA["duration"]

def beat_t(n):
    if n < len(BEAT_TIMES):
        return BEAT_TIMES[n]
    return DURATION

def bar_t(n):
    return beat_t((n - 1) * 4)

AVG_BEAT = (BEAT_TIMES[-1] - BEAT_TIMES[0]) / (len(BEAT_TIMES) - 1) if len(BEAT_TIMES) > 1 else 0.466


def load(name):
    return Image.open(SRC / name)

def make_bw(img, contrast=1.5, brightness=1.0):
    bw = img.convert("L")
    bw = ImageEnhance.Contrast(bw).enhance(contrast)
    if brightness != 1.0:
        bw = ImageEnhance.Brightness(bw).enhance(brightness)
    return bw

def center_x(img_w, canvas_w):
    return (canvas_w - img_w) // 2

def center_y(content_h):
    safe_h = H - SAFE_TOP - SAFE_BOTTOM
    return SAFE_TOP + (safe_h - content_h) // 2

def make_black_on_transparent(img):
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    gray = np.array(img.convert("L"))
    orig_alpha = arr[:, :, 3]
    darkness = (255 - gray).astype(np.uint8)
    new_alpha = np.minimum(orig_alpha, darkness)
    result = np.zeros_like(arr)
    result[:, :, :3] = 0
    result[:, :, 3] = new_alpha
    return Image.fromarray(result, "RGBA")

def radial_vignette_white(w, h, cx, cy, inner_r, outer_r):
    Y, X = np.ogrid[:h, :w]
    rx = outer_r * (w / max(w, h))
    ry = outer_r * (h / max(w, h))
    dist = np.sqrt(((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2)
    mask = np.ones((h, w), dtype=float)
    fade_zone = dist > 0.5
    mask[fade_zone] = np.clip(1.0 - (dist[fade_zone] - 0.5) / 0.5, 0, 1)
    return mask

def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except:
        return ImageFont.load_default()


def prepare_layers():
    layers = {}

    # === Image layers ===

    # Frame — black funeral border
    frame = load("image3.png")
    frame_black = make_black_on_transparent(frame)
    frame_black = frame_black.resize((W - 60, H - 60), Image.LANCZOS)
    frame_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    frame_layer.paste(frame_black, (30, 30), frame_black)
    layers["frame"] = frame_layer

    # (static image layers removed — using video clips instead)

    # === Text layers ===
    DIDOT = "/System/Library/Fonts/Supplemental/Didot.ttc"
    BODONI = "/System/Library/Fonts/Supplemental/Bodoni 72.ttc"
    BODONI_SC = "/System/Library/Fonts/Supplemental/Bodoni 72 Smallcaps Book.ttf"
    BASKERVILLE = "/System/Library/Fonts/Supplemental/Baskerville.ttc"

    title_font = font(BODONI_SC, 96)
    theme_font = font(DIDOT, 56)
    subtitle_font = font(BODONI, 48)
    body_font = font(BASKERVILLE, 36)
    small_font = font(BASKERVILLE, 32)
    jp_font = font("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 72)

    # "ONE WEEK UNTIL THE FUNERAL" — headstone style, one word per line
    # Equal spacing: rose ornament → ONE = ONE → WEEK = WEEK → UNTIL etc.
    ORNAMENT_BOTTOM = 150   # where top rose ornament ends
    BORDER_INNER_BOTTOM = 250

    headstone_font = font(BODONI_SC, 120)
    countdown_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_cd = ImageDraw.Draw(countdown_layer)
    cd_words = ["ONE", "WEEK", "UNTIL", "THE", "FUNERAL"]
    cd_heights = []
    cd_widths = []
    for word in cd_words:
        bbox = draw_cd.textbbox((0, 0), word, font=headstone_font)
        cd_widths.append(bbox[2] - bbox[0])
        cd_heights.append(bbox[3] - bbox[1])
    total_text_h = sum(cd_heights)
    # N words need N gaps (1 top margin + N-1 between words)
    available = (H - BORDER_INNER_BOTTOM) - ORNAMENT_BOTTOM
    n_gaps = len(cd_words)
    cd_gap = (available - total_text_h) / n_gaps
    cd_y = ORNAMENT_BOTTOM + cd_gap  # first gap = top margin
    for i, word in enumerate(cd_words):
        draw_cd.text((center_x(cd_widths[i], W), int(cd_y)), word, fill=(0, 0, 0, 255), font=headstone_font)
        cd_y += cd_heights[i] + cd_gap
    layers["countdown"] = countdown_layer

    # "INTERZONE XV / SATURDAY / MARCH 21" — evenly spaced inside border
    big_font = font(BODONI_SC, 130)
    all_lines = ["INTERZONE", "XV", "SATURDAY", "MARCH 21"]

    # Title layer (top 2 lines) and date layer (bottom 2 lines)
    # share the same even spacing within the border
    line_heights = []
    line_widths = []
    tmp_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp_img)
    for line in all_lines:
        bbox = tmp_draw.textbbox((0, 0), line, font=big_font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])
    total_text_h = sum(line_heights)
    available = (H - BORDER_INNER_BOTTOM) - ORNAMENT_BOTTOM
    n_gaps = len(all_lines) + 1  # 1 top + 3 between + 1 bottom = 5 equal gaps
    td_gap = (available - total_text_h) / n_gaps
    td_y = ORNAMENT_BOTTOM + td_gap

    # Compute y positions for all 4 lines
    y_positions = []
    cur_y = td_y
    for i in range(len(all_lines)):
        y_positions.append(int(cur_y))
        cur_y += line_heights[i] + td_gap

    # Title layer: INTERZONE + XV
    title_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_t = ImageDraw.Draw(title_layer)
    for i in range(2):
        draw_t.text((center_x(line_widths[i], W), y_positions[i]), all_lines[i], fill=(0, 0, 0, 255), font=big_font)
    layers["title"] = title_layer

    # Date layer: SATURDAY + MARCH 21
    date_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_date = ImageDraw.Draw(date_layer)
    for i in range(2, 4):
        draw_date.text((center_x(line_widths[i], W), y_positions[i]), all_lines[i], fill=(0, 0, 0, 255), font=big_font)
    layers["date"] = date_layer

    # "FUNERAL PARADE OF ROSES" + 薔薇の葬列 — top half of frame (headstone style)
    # Use same even-spacing rule within the top zone of the border
    top_zone_h = (H - SAFE_TOP - SAFE_BOTTOM) // 2  # top half of content area
    theme_font_big = font(BODONI_SC, 100)
    jp_theme_font = font("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc", 110)
    theme_lines = ["FUNERAL", "PARADE", "OF ROSES"]
    theme_jp = "薔薇の葬列"

    theme_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_theme = ImageDraw.Draw(theme_layer)

    # Measure all lines (English + kanji)
    th_heights = []
    th_widths = []
    for line in theme_lines:
        bbox = draw_theme.textbbox((0, 0), line, font=theme_font_big)
        th_widths.append(bbox[2] - bbox[0])
        th_heights.append(bbox[3] - bbox[1])
    bbox_jp = draw_theme.textbbox((0, 0), theme_jp, font=jp_theme_font)
    jp_w = bbox_jp[2] - bbox_jp[0]
    jp_h = bbox_jp[3] - bbox_jp[1]
    th_widths.append(jp_w)
    th_heights.append(jp_h)

    all_theme_lines = theme_lines + [theme_jp]
    all_theme_fonts = [theme_font_big] * len(theme_lines) + [jp_theme_font]
    total_theme_h = sum(th_heights)
    # Even spacing within top zone of the border
    theme_available = top_zone_h - (ORNAMENT_BOTTOM - SAFE_TOP)
    n_theme_gaps = len(all_theme_lines) + 1
    theme_gap = (theme_available - total_theme_h) / n_theme_gaps
    cur_y = ORNAMENT_BOTTOM + theme_gap
    for i, line in enumerate(all_theme_lines):
        fill = (0, 0, 0, 255) if i < len(theme_lines) else (50, 50, 50, 255)
        draw_theme.text((center_x(th_widths[i], W), int(cur_y)), line, fill=fill, font=all_theme_fonts[i])
        cur_y += th_heights[i] + theme_gap
    layers["theme"] = theme_layer

    # DJs — headstone style, evenly spaced within border
    # SISTER/MALADY grouped tight; DJS, SEITH, and the pair are 3 evenly-spaced items
    dj_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_dj = ImageDraw.Draw(dj_layer)

    dj_items = ["DJS", "SEITH"]  # standalone lines
    dj_pair = ["SISTER", "MALADY"]  # grouped tight
    pair_line_gap = 10  # tight gap between SISTER and MALADY

    # Measure standalone items
    item_heights = []
    item_widths = []
    for line in dj_items:
        bbox = draw_dj.textbbox((0, 0), line, font=headstone_font)
        item_widths.append(bbox[2] - bbox[0])
        item_heights.append(bbox[3] - bbox[1])

    # Measure pair as a single block
    pair_heights = []
    pair_widths = []
    for line in dj_pair:
        bbox = draw_dj.textbbox((0, 0), line, font=headstone_font)
        pair_widths.append(bbox[2] - bbox[0])
        pair_heights.append(bbox[3] - bbox[1])
    pair_block_h = sum(pair_heights) + pair_line_gap

    # 3 logical items (DJS, SEITH, SISTER+MALADY) → 4 equal gaps
    total_content_h = sum(item_heights) + pair_block_h
    dj_available = (H - BORDER_INNER_BOTTOM) - ORNAMENT_BOTTOM
    n_gaps = 3 + 1  # 3 items, 4 gaps
    dj_gap = (dj_available - total_content_h) / n_gaps
    dj_y = ORNAMENT_BOTTOM + dj_gap

    # Draw standalone items
    for i, line in enumerate(dj_items):
        draw_dj.text((center_x(item_widths[i], W), int(dj_y)), line, fill=(0, 0, 0, 255), font=headstone_font)
        dj_y += item_heights[i] + dj_gap

    # Draw pair (tight)
    for i, line in enumerate(dj_pair):
        draw_dj.text((center_x(pair_widths[i], W), int(dj_y)), line, fill=(0, 0, 0, 255), font=headstone_font)
        dj_y += pair_heights[i] + pair_line_gap
    layers["djs"] = dj_layer

    # Performers — headstone style, top half (eyes video plays in bottom)
    # RITA/REPULSIVE grouped tight like SISTER/MALADY
    perf_font = font(BODONI_SC, 100)  # smaller so PERFORMANCES fits in border
    perf_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_perf = ImageDraw.Draw(perf_layer)

    perf_items = ["PERFORMANCES", "MIMENTO"]  # standalone lines
    perf_pair = ["RITA", "REPULSIVE"]  # grouped tight
    perf_pair_gap = 10

    # Measure standalone items
    pi_heights = []
    pi_widths = []
    for line in perf_items:
        bbox = draw_perf.textbbox((0, 0), line, font=perf_font)
        pi_widths.append(bbox[2] - bbox[0])
        pi_heights.append(bbox[3] - bbox[1])

    # Measure pair as a single block
    pp_heights = []
    pp_widths = []
    for line in perf_pair:
        bbox = draw_perf.textbbox((0, 0), line, font=perf_font)
        pp_widths.append(bbox[2] - bbox[0])
        pp_heights.append(bbox[3] - bbox[1])
    pp_block_h = sum(pp_heights) + perf_pair_gap

    # 3 logical items → 4 equal gaps
    total_perf_h = sum(pi_heights) + pp_block_h
    perf_available = top_zone_h - (ORNAMENT_BOTTOM - SAFE_TOP)
    n_perf_gaps = 3 + 1
    perf_gap = (perf_available - total_perf_h) / n_perf_gaps
    perf_y = ORNAMENT_BOTTOM + perf_gap

    # PERFORMANCES
    draw_perf.text((center_x(pi_widths[0], W), int(perf_y)), perf_items[0], fill=(0, 0, 0, 255), font=perf_font)
    perf_y += pi_heights[0] + perf_gap

    # RITA / REPULSIVE (tight)
    for i, line in enumerate(perf_pair):
        draw_perf.text((center_x(pp_widths[i], W), int(perf_y)), line, fill=(0, 0, 0, 255), font=perf_font)
        perf_y += pp_heights[i] + perf_pair_gap
    perf_y += perf_gap - perf_pair_gap  # switch back to big gap after pair

    # MIMENTO
    draw_perf.text((center_x(pi_widths[1], W), int(perf_y)), perf_items[1], fill=(0, 0, 0, 255), font=perf_font)
    layers["performers"] = perf_layer

    # Vendors / details — headstone style, top half
    det_lines = ["AL'S BAR", "Music @ 8", "Performances @ 10", "21+ $10"]
    det_font = font(BODONI_SC, 100)  # same as performers — long lines need room
    det_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_det = ImageDraw.Draw(det_layer)
    det_heights = []
    det_widths = []
    for line in det_lines:
        bbox = draw_det.textbbox((0, 0), line, font=det_font)
        det_widths.append(bbox[2] - bbox[0])
        det_heights.append(bbox[3] - bbox[1])
    total_det_h = sum(det_heights)
    det_available = top_zone_h - (ORNAMENT_BOTTOM - SAFE_TOP)
    n_det_gaps = len(det_lines) + 1
    det_gap = (det_available - total_det_h) / n_det_gaps
    det_y = ORNAMENT_BOTTOM + det_gap
    for i, line in enumerate(det_lines):
        draw_det.text((center_x(det_widths[i], W), int(det_y)), line, fill=(0, 0, 0, 255), font=det_font)
        det_y += det_heights[i] + det_gap
    layers["details"] = det_layer

    return layers


def envelope(t, fade_in, hold_start, hold_end, fade_out):
    if t < fade_in:
        return 0.0
    elif t < hold_start:
        return (t - fade_in) / (hold_start - fade_in)
    elif t < hold_end:
        return 1.0
    elif t < fade_out:
        return 1.0 - (t - hold_end) / (fade_out - hold_end)
    else:
        return 0.0


def build_timeline():
    """Timeline synced to detected beat positions.

    Bars 1-2:   Frame + "ONE WEEK UNTIL THE FUNERAL"
    Bars 3-4:   INTERZONE XV
    Bars 5-6:   Eyes
    Bars 7-8:   Theme + 薔薇の葬列
    Bars 9-10:  DJs
    Bars 11-12: Tableau
    Bars 13-14: Performers
    Bars 15-16: Event details
    """
    fade = AVG_BEAT

    return [
        ("frame",      0.0,       0.0,               bar_t(15),         bar_t(16) + fade),
        ("countdown",  0.0,       0.0,               bar_t(3) - fade,   bar_t(3)),
        ("date",       bar_t(3),  bar_t(3) + fade,  bar_t(5) - fade,   bar_t(5)),
        ("title",      bar_t(4),  bar_t(4) + fade,  bar_t(7) - fade,   bar_t(7)),
        ("shower",     bar_t(5),  bar_t(5) + fade,   bar_t(9) - fade,  bar_t(9)),
        ("theme",      bar_t(7),  bar_t(7) + fade,  bar_t(9) - fade,   bar_t(9)),
        ("djs",        bar_t(9),  bar_t(9) + fade,  bar_t(11) - fade,  bar_t(11)),
        ("eyes",       bar_t(11), bar_t(11) + fade,  DURATION,          DURATION),
        ("performers", bar_t(11), bar_t(11) + fade, bar_t(13) - fade,  bar_t(13)),
        ("details",    bar_t(13), bar_t(13) + fade, bar_t(15) - fade,  bar_t(15)),
    ]


def blend_layer_on_white(base_arr, layer, opacity):
    if opacity <= 0:
        return base_arr
    layer_arr = np.array(layer).astype(float)
    alpha = (layer_arr[:, :, 3] / 255.0) * opacity
    for c in range(3):
        base_arr[:, :, c] = base_arr[:, :, c] * (1 - alpha) + layer_arr[:, :, c] * alpha
    return base_arr


def load_video_clip(path, target_w, target_h, target_y, skip_start=0, trim_end=0, speed=0.5):
    """Load all frames from a video clip, scale to fit target area, B&W, vignetted to white.

    skip_start: number of leading frames to skip
    trim_end: number of trailing frames to remove
    speed: playback speed multiplier (0.5 = half speed)
    """
    cap = cv2.VideoCapture(str(path))
    clip_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    use_end = total_frames - trim_end
    raw_frames = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        idx += 1
        if idx <= skip_start or idx > use_end:
            continue
        # Convert BGR to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Scale to fit target width
        src_h, src_w = gray.shape
        scale = target_w / src_w
        new_w = target_w
        new_h = int(src_h * scale)
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        # Increase contrast
        gray = np.clip(gray.astype(float) * 1.4 - 40, 0, 255).astype(np.uint8)
        # Vignette to white
        vig = radial_vignette_white(new_w, new_h, new_w // 2, new_h // 2, 300, 600)
        blended = gray.astype(float) * vig + 255.0 * (1.0 - vig)
        alpha = (vig * 255).clip(0, 255).astype(np.uint8)
        # Build RGBA on full canvas
        canvas = np.zeros((H, W, 4), dtype=np.uint8)
        b = blended.clip(0, 255).astype(np.uint8)
        canvas[target_y:target_y+new_h, :new_w, 0] = b
        canvas[target_y:target_y+new_h, :new_w, 1] = b
        canvas[target_y:target_y+new_h, :new_w, 2] = b
        canvas[target_y:target_y+new_h, :new_w, 3] = alpha
        raw_frames.append(Image.fromarray(canvas, "RGBA"))
    cap.release()
    # Effective fps after speed change (half speed = half the fps for frame lookup)
    effective_fps = clip_fps * speed
    print(f"  Loaded {len(raw_frames)} frames from {Path(path).name} "
          f"(src {clip_fps:.1f} fps, playback {effective_fps:.1f} fps = {speed}x speed)")
    return raw_frames, effective_fps


def render_video(preview=False):
    fps = 10 if preview else 30
    crf = "28" if preview else "18"
    preset = "ultrafast" if preview else "slow"
    tag = "_preview" if preview else ""

    print("Preparing layers...")
    layers = prepare_layers()
    timeline = build_timeline()

    # Load video clips for bottom half
    bottom_zone_top = SAFE_TOP + (H - SAFE_TOP - SAFE_BOTTOM) // 2
    bottom_h = H - bottom_zone_top - SAFE_BOTTOM

    SHOWER_PATH = PROJECT_DIR / "source" / "video" / "funaral_edit_2(shower grafic).mp4"
    shower_frames, shower_fps = load_video_clip(SHOWER_PATH, W, bottom_h, bottom_zone_top,
                                                 skip_start=2, speed=0.5)

    EYES_PATH = PROJECT_DIR / "source" / "video" / "funaral_edit_3(she got eyes).mp4"
    eyes_frames, eyes_fps = load_video_clip(EYES_PATH, W, bottom_h, bottom_zone_top,
                                             trim_end=24, speed=0.625)

    total_frames = int(DURATION * fps)
    print(f"{'PREVIEW ' if preview else ''}Render: {fps} FPS, {total_frames} frames, {DURATION:.1f}s")

    # Auto-version
    existing = sorted(OUT.glob(f"flyer_reveal_white{tag}_v*.mp4"))
    if existing:
        last = existing[-1].stem
        next_v = int(last.split("_v")[-1]) + 1
    else:
        next_v = 1
    output_path = OUT / f"flyer_reveal_white{tag}_v{next_v}.mp4"

    # Pipe frames directly to ffmpeg — no temp files
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{W}x{H}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "-",
        "-i", str(AUDIO_PATH),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", crf,
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]

    print(f"Piping to ffmpeg -> {output_path.name}")
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    for frame_idx in range(total_frames):
        t = frame_idx / fps
        canvas = np.ones((H, W, 3), dtype=float) * 255.0

        for entry in timeline:
            name, fi, hs, he, fo = entry
            opacity = envelope(t, fi, hs, he, fo)
            if opacity <= 0:
                continue
            if name == "shower":
                clip_t = t - fi
                idx = int(clip_t * shower_fps) % len(shower_frames)
                canvas = blend_layer_on_white(canvas, shower_frames[idx], opacity)
            elif name == "eyes":
                clip_t = t - fi
                idx = min(int(clip_t * eyes_fps), len(eyes_frames) - 1)
                canvas = blend_layer_on_white(canvas, eyes_frames[idx], opacity)
            elif name in layers:
                canvas = blend_layer_on_white(canvas, layers[name], opacity)

        proc.stdin.write(canvas.clip(0, 255).astype(np.uint8).tobytes())

        if frame_idx % (fps * 5) == 0:
            print(f"  {frame_idx}/{total_frames} ({t:.1f}s)")

    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        print(f"ffmpeg error:\n{proc.stderr.read().decode()}", file=sys.stderr)
        sys.exit(1)

    print(f"Saved: {output_path}")
    return output_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="Fast 10fps preview")
    args = ap.parse_args()
    path = render_video(preview=args.preview)
    subprocess.run(["open", str(path)])
