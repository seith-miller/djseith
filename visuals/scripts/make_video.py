#!/usr/bin/env python3
"""Generate Interzone XV Instagram video — beat-synced reveals with audio.

Format: 1080x1920 (9:16) — Instagram Reels / Stories / TikTok.
Safe zone: top 250px, bottom 320px clear of critical content.
Content zone: y=250 to y=1600.

Design rules:
  - White text ONLY over black backgrounds. Text and images never overlap.
  - Font sizes phone-readable (1080px / 2.8 downscale).
  - Generous vertical spacing.
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses"
import numpy as np
import subprocess
import tempfile
import shutil

SRC = PROJECT_DIR / "source"
ASSETS = Path(__file__).parent.parent / "assets"
OUT = PROJECT_DIR / "output"
OUT.mkdir(exist_ok=True)

W, H = 1080, 1920  # 9:16 Reels/Stories/TikTok
FPS = 30

# Safe zone boundaries (UI overlays)
SAFE_TOP = 250
SAFE_BOTTOM = 320
# Content zone: y=250 to y=1600

# === Tempo grid ===
BPM = 172.88
BEAT = 60.0 / BPM
MEASURE = BEAT * 4
TOTAL = MEASURE * 16

def beat(n):
    return n * BEAT

def bar(n):
    return n * MEASURE

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
    """Center content vertically within the safe zone."""
    safe_h = H - SAFE_TOP - SAFE_BOTTOM
    return SAFE_TOP + (safe_h - content_h) // 2

def invert_to_white_on_transparent(img):
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    gray = np.array(img.convert("L"))
    orig_alpha = arr[:, :, 3]
    new_alpha = np.minimum(orig_alpha, (255 - gray).astype(np.uint8))
    result = np.zeros_like(arr)
    result[:, :, :3] = 255
    result[:, :, 3] = new_alpha
    return Image.fromarray(result, "RGBA")

def radial_vignette(w, h, cx, cy, inner_r, outer_r):
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

    # Frame (spans full canvas — decorative border)
    frame = load("image3.png")
    frame_white = invert_to_white_on_transparent(frame)
    frame_white = frame_white.resize((W - 60, H - 60), Image.LANCZOS)
    frame_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    frame_layer.paste(frame_white, (30, 30), frame_white)
    layers["frame"] = frame_layer

    # Hero eyes (image4) — centered in safe zone
    hero = load("image4.png")
    hero_bw = make_bw(hero, contrast=1.5, brightness=1.2)
    hero_ratio = hero_bw.width / hero_bw.height
    hero_w = W
    hero_h = int(hero_w / hero_ratio)
    hero_bw = hero_bw.resize((hero_w, hero_h), Image.LANCZOS)
    hero_rgb = Image.merge("RGB", [hero_bw, hero_bw, hero_bw])
    hero_y = center_y(hero_h)
    vig = radial_vignette(hero_w, hero_h, hero_w // 2, hero_h // 2, 300, 600)
    hero_arr = np.array(hero_rgb).astype(float)
    for c in range(3):
        hero_arr[:, :, c] *= vig
    hero_alpha = (vig * 255).clip(0, 255).astype(np.uint8)
    hero_rgba_arr = np.zeros((hero_h, hero_w, 4), dtype=np.uint8)
    hero_rgba_arr[:, :, :3] = hero_arr.clip(0, 255).astype(np.uint8)
    hero_rgba_arr[:, :, 3] = hero_alpha
    hero_rgba = Image.fromarray(hero_rgba_arr, "RGBA")
    hero_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hero_layer.paste(hero_rgba, (0, hero_y), hero_rgba)
    layers["eyes"] = hero_layer

    # Urinal tableau (image5) — centered in safe zone
    alt = load("image5.png")
    alt_bw = make_bw(alt, contrast=1.6, brightness=1.1)
    alt_ratio = alt_bw.width / alt_bw.height
    alt_w = W
    alt_h = int(alt_w / alt_ratio)
    alt_bw = alt_bw.resize((alt_w, alt_h), Image.LANCZOS)
    alt_rgb = Image.merge("RGB", [alt_bw, alt_bw, alt_bw])
    alt_y = H - alt_h - SAFE_BOTTOM  # lower portion, clear of bottom UI
    vig_alt = radial_vignette(alt_w, alt_h, alt_w // 2, alt_h // 2, 300, 600)
    alt_arr = np.array(alt_rgb).astype(float)
    for c in range(3):
        alt_arr[:, :, c] *= vig_alt
    alt_alpha = (vig_alt * 255).clip(0, 255).astype(np.uint8)
    alt_rgba_arr = np.zeros((alt_h, alt_w, 4), dtype=np.uint8)
    alt_rgba_arr[:, :, :3] = alt_arr.clip(0, 255).astype(np.uint8)
    alt_rgba_arr[:, :, 3] = alt_alpha
    alt_rgba = Image.fromarray(alt_rgba_arr, "RGBA")
    alt_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    alt_layer.paste(alt_rgba, (0, alt_y), alt_rgba)
    layers["tableau"] = alt_layer

    # === Text layers (all positioned within safe zone, over black) ===
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

    def make_text_layer(text, y, fnt, fill):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        draw.text((center_x(tw, W), y), text, fill=fill + (255,), font=fnt)
        return layer

    # "INTERZONE XV" — two lines, vertically centered in safe zone
    title_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_t = ImageDraw.Draw(title_layer)
    bbox1 = draw_t.textbbox((0, 0), "INTERZONE", font=title_font)
    tw1, th1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
    bbox2 = draw_t.textbbox((0, 0), "XV", font=theme_font)
    tw2, th2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
    gap = 24
    block_h = th1 + gap + th2
    ty = center_y(block_h)
    draw_t.text((center_x(tw1, W), ty), "INTERZONE", fill=(255, 255, 255, 255), font=title_font)
    draw_t.text((center_x(tw2, W), ty + th1 + gap), "XV", fill=(200, 200, 200, 255), font=theme_font)
    layers["title"] = title_layer

    # "Funeral Parade of Roses" + 薔薇の葬列 — shown together, centered in safe zone
    theme_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_theme = ImageDraw.Draw(theme_layer)
    bbox_en = draw_theme.textbbox((0, 0), "Funeral Parade of Roses", font=theme_font)
    tw_en, th_en = bbox_en[2] - bbox_en[0], bbox_en[3] - bbox_en[1]
    bbox_jp = draw_theme.textbbox((0, 0), "薔薇の葬列", font=jp_font)
    tw_jp, th_jp = bbox_jp[2] - bbox_jp[0], bbox_jp[3] - bbox_jp[1]
    theme_gap = 30
    theme_block_h = th_en + theme_gap + th_jp
    theme_y = center_y(theme_block_h)
    draw_theme.text((center_x(tw_en, W), theme_y), "Funeral Parade of Roses", fill=(220, 220, 220, 255), font=theme_font)
    draw_theme.text((center_x(tw_jp, W), theme_y + th_en + theme_gap), "薔薇の葬列", fill=(200, 200, 200, 255), font=jp_font)
    layers["theme"] = theme_layer

    # DJs — centered with label above names
    dj_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_dj = ImageDraw.Draw(dj_layer)
    dj_block_h = 32 + 20 + 48  # label + gap + names
    dj_y = center_y(dj_block_h)
    bbox = draw_dj.textbbox((0, 0), "DJs", font=small_font)
    draw_dj.text((center_x(bbox[2] - bbox[0], W), dj_y), "DJs", fill=(150, 150, 150, 255), font=small_font)
    bbox = draw_dj.textbbox((0, 0), "SEITH  ·  Sister Malady", font=subtitle_font)
    draw_dj.text((center_x(bbox[2] - bbox[0], W), dj_y + 52), "SEITH  ·  Sister Malady", fill=(255, 255, 255, 255), font=subtitle_font)
    layers["djs"] = dj_layer

    # Performers — centered
    perf_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_perf = ImageDraw.Draw(perf_layer)
    perf_block_h = 32 + 20 + 48
    perf_y = center_y(perf_block_h)
    bbox = draw_perf.textbbox((0, 0), "Performances", font=small_font)
    draw_perf.text((center_x(bbox[2] - bbox[0], W), perf_y), "Performances", fill=(150, 150, 150, 255), font=small_font)
    bbox = draw_perf.textbbox((0, 0), "Rita Repulsive  ·  Mimento", font=subtitle_font)
    draw_perf.text((center_x(bbox[2] - bbox[0], W), perf_y + 52), "Rita Repulsive  ·  Mimento", fill=(255, 255, 255, 255), font=subtitle_font)
    layers["performers"] = perf_layer

    # Event details — stacked, centered in safe zone
    details_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_det = ImageDraw.Draw(details_layer)
    lines = [
        ("Eleventh Hour Vendors Market", body_font, (180, 180, 180)),
        ("Saturday, March 21, 2026", subtitle_font, (255, 255, 255)),
        ("Al's Bar  ·  21+  ·  $10", body_font, (200, 200, 200)),
        ("Music 8 PM  ·  Performances 10 PM", small_font, (160, 160, 160)),
    ]
    line_gap = 48
    # Calculate total block height
    total_h = 0
    line_heights = []
    for text, fnt, _ in lines:
        bbox = draw_det.textbbox((0, 0), text, font=fnt)
        lh = bbox[3] - bbox[1]
        line_heights.append(lh)
        total_h += lh + line_gap
    total_h -= line_gap  # no gap after last line
    det_y = center_y(total_h)
    for i, (text, fnt, fill) in enumerate(lines):
        bbox = draw_det.textbbox((0, 0), text, font=fnt)
        draw_det.text((center_x(bbox[2] - bbox[0], W), det_y), text, fill=fill + (255,), font=fnt)
        det_y += line_heights[i] + line_gap
    layers["details"] = details_layer

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
    """Text and images NEVER overlap. Strict alternation.

    Bars 1-2:   Frame only
    Bars 3-4:   INTERZONE XV (text only)
    Bars 5-6:   Eyes (image only)
    Bars 7-8:   Theme + 薔薇の葬列 (text only, shown together)
    Bars 9-10:  DJs (text only)
    Bars 11-12: Tableau (image only)
    Bars 13-14: Performers (text only)
    Bars 15-16: Event details (text only)
    """
    fade = BEAT

    return [
        # Frame persists throughout
        ("frame",      bar(0),  bar(0) + fade,  bar(15),  bar(16)),

        # Bars 3-4: INTERZONE XV (text only)
        ("title",      bar(2),  bar(2) + fade,  bar(4) - fade,  bar(4)),

        # Bars 5-6: Eyes (image only)
        ("eyes",       bar(4),  bar(4) + fade*2,  bar(6) - fade,  bar(6)),

        # Bars 7-8: Theme + Japanese title (text only, together)
        ("theme",      bar(6),  bar(6) + fade,  bar(8) - fade,  bar(8)),

        # Bars 9-10: DJs (text only)
        ("djs",        bar(8),  bar(8) + fade,  bar(10) - fade,  bar(10)),

        # Bars 11-12: Tableau (image only)
        ("tableau",    bar(10), bar(10) + fade*2,  bar(12) - fade,  bar(12)),

        # Bars 13-14: Performers (text only)
        ("performers", bar(12), bar(12) + fade,  bar(14) - fade,  bar(14)),

        # Bars 15-16: Details (text only — the closer)
        ("details",    bar(14), bar(14) + fade,  bar(16) - fade,  bar(16)),
    ]


def blend_layer(base_arr, layer, opacity):
    if opacity <= 0:
        return base_arr
    layer_arr = np.array(layer).astype(float)
    alpha = (layer_arr[:, :, 3] / 255.0) * opacity
    for c in range(3):
        base_arr[:, :, c] = base_arr[:, :, c] * (1 - alpha) + layer_arr[:, :, c] * alpha
    return base_arr


def render_video():
    print("Preparing layers...")
    layers = prepare_layers()
    timeline = build_timeline()

    total_frames = int(TOTAL * FPS)
    print(f"Tempo: {BPM} BPM | Beat: {BEAT:.3f}s | Measure: {MEASURE:.3f}s")
    print(f"Duration: {TOTAL:.2f}s | Frames: {total_frames}")
    print(f"Canvas: {W}x{H} (9:16) | Safe zone: y={SAFE_TOP}-{H - SAFE_BOTTOM}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="flyer_video_"))
    print(f"Rendering {total_frames} frames to {tmp_dir}...")

    for frame_idx in range(total_frames):
        t = frame_idx / FPS
        canvas = np.zeros((H, W, 3), dtype=float)

        for entry in timeline:
            name, fi, hs, he, fo = entry
            opacity = envelope(t, fi, hs, he, fo)
            if opacity > 0 and name in layers:
                canvas = blend_layer(canvas, layers[name], opacity)

        frame_img = Image.fromarray(canvas.clip(0, 255).astype(np.uint8))
        frame_img.save(tmp_dir / f"frame_{frame_idx:05d}.png")

        if frame_idx % (FPS * 2) == 0:
            print(f"  {frame_idx}/{total_frames} ({t:.1f}s / bar {t / MEASURE:.1f})")

    audio_path = ASSETS / "interzon_XV_buck_tick 2026-02-18 2340.wav"
    # Auto-version
    existing = sorted(OUT.glob("flyer_reveal_v*.mp4"))
    if existing:
        last = existing[-1].stem
        next_v = int(last.split("_v")[-1]) + 1
    else:
        next_v = 1
    output_path = OUT / f"flyer_reveal_v{next_v}.mp4"

    print(f"Encoding video with audio → {output_path.name}...")
    subprocess.run([
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(tmp_dir / "frame_%05d.png"),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-preset", "slow",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path),
    ], check=True)

    shutil.rmtree(tmp_dir)
    print(f"saved: {output_path}")

if __name__ == "__main__":
    render_video()
