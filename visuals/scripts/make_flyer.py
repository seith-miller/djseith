#!/usr/bin/env python3
"""Generate Interzone XV: Funeral Parade of Roses flyer.

Format: 1080x1350 (4:5) — Instagram feed post / carousel.
Design: Eyes hero image in upper half, text block in lower half (black bg).
All text over black only. Phone-readable font sizes.
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses"
import numpy as np

SRC = PROJECT_DIR / "source"
OUT = PROJECT_DIR / "output"
OUT.mkdir(exist_ok=True)

W, H = 1080, 1350  # 4:5 Instagram feed

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

def build_flyer():
    canvas = Image.new("RGB", (W, H), (0, 0, 0))

    # === Fonts ===
    DIDOT = "/System/Library/Fonts/Supplemental/Didot.ttc"
    BODONI = "/System/Library/Fonts/Supplemental/Bodoni 72.ttc"
    BODONI_SC = "/System/Library/Fonts/Supplemental/Bodoni 72 Smallcaps Book.ttf"
    BASKERVILLE = "/System/Library/Fonts/Supplemental/Baskerville.ttc"

    def font(path, size):
        try:
            return ImageFont.truetype(path, size)
        except:
            return ImageFont.load_default()

    title_font = font(BODONI_SC, 86)
    numeral_font = font(DIDOT, 48)
    theme_font = font(DIDOT, 46)
    subtitle_font = font(BODONI, 38)
    body_font = font(BASKERVILLE, 30)
    small_font = font(BASKERVILLE, 26)

    # === Layout grid ===
    # Eyes centered at 1/3 mark, title at 1/4 mark overlapping forehead
    THIRD = H // 3       # 450
    QUARTER = H // 4     # 337

    # === Hero: Eyes centered at 1/3 mark ===
    hero = load("image4.png")
    hero_bw = make_bw(hero, contrast=1.5, brightness=1.2)
    hero_ratio = hero_bw.width / hero_bw.height
    hero_w = int(W * 0.75)
    hero_h = int(hero_w / hero_ratio)
    hero_bw = hero_bw.resize((hero_w, hero_h), Image.LANCZOS)
    hero_rgb = Image.merge("RGB", [hero_bw, hero_bw, hero_bw])
    hero_x = center_x(hero_w, W)
    hero_y = THIRD - hero_h // 2  # center eyes at 1/3

    vignette = radial_vignette(hero_w, hero_h, hero_w // 2, hero_h // 2, 150, 350)
    hero_arr = np.array(hero_rgb).astype(float)
    for c in range(3):
        hero_arr[:, :, c] *= vignette
    hero_vignetted = Image.fromarray(hero_arr.clip(0, 255).astype(np.uint8))
    canvas.paste(hero_vignetted, (hero_x, hero_y))

    # === Rose frame overlay ===
    frame = load("image3.png")
    frame_white = invert_to_white_on_transparent(frame)
    frame_white = frame_white.resize((W - 60, H - 60), Image.LANCZOS)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(frame_white, (30, 30), frame_white)

    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    def draw_centered(text, y, fnt, fill=(255, 255, 255)):
        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        draw.text((center_x(tw, W), y), text, fill=fill, font=fnt)

    def draw_centered_outlined(text, y, fnt, fill=(255, 255, 255), stroke_width=3):
        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        x = center_x(tw, W)
        draw.text((x, y), text, fill=(0, 0, 0), font=fnt,
                  stroke_width=stroke_width, stroke_fill=(0, 0, 0))
        draw.text((x, y), text, fill=fill, font=fnt)

    def text_height(text, fnt):
        bbox = draw.textbbox((0, 0), text, font=fnt)
        return bbox[3] - bbox[1]

    # === Title "INTERZONE XV" at 1/4 mark — overlaps forehead ===
    title_h = text_height("INTERZONE", title_font)
    numeral_h = text_height("XV", numeral_font)
    title_block = title_h + 8 + numeral_h  # 8px gap between lines
    title_y = QUARTER - title_block // 2
    draw_centered_outlined("INTERZONE", title_y, title_font)
    draw_centered_outlined("XV", title_y + title_h + 8, numeral_font, (200, 200, 200))

    # === Text block — evenly spaced in lower half ===
    # Lower half: y = H/2 (675) to y = 1260 (safe from frame bottom)
    TEXT_TOP = H // 2 + 5   # 680
    TEXT_BOT = 1260

    # Measure all text heights
    lines = [
        ("Funeral Parade of Roses", theme_font, (220, 220, 220), "theme"),
        ("SEP1", None, None, "sep"),
        ("DJs", small_font, (140, 140, 140), "label"),
        ("SEITH  ·  Sister Malady", subtitle_font, (255, 255, 255), "names"),
        ("Performances", small_font, (140, 140, 140), "label"),
        ("Rita Repulsive  ·  Mimento", subtitle_font, (255, 255, 255), "names"),
        ("SEP2", None, None, "sep"),
        ("Eleventh Hour Vendors Market", body_font, (180, 180, 180), "detail"),
        ("Saturday, March 21, 2026", subtitle_font, (255, 255, 255), "detail"),
        ("Al's Bar  ·  21+  ·  $10", body_font, (200, 200, 200), "detail"),
        ("Music 8 PM  ·  Performances 10 PM", small_font, (160, 160, 160), "detail"),
    ]

    # Calculate total content height (seps are 1px)
    heights = []
    for text, fnt, _, kind in lines:
        if kind == "sep":
            heights.append(1)
        else:
            heights.append(text_height(text, fnt))
    total_content = sum(heights)

    # Distribute remaining space as even gaps
    n_gaps = len(lines) - 1
    total_gap = TEXT_BOT - TEXT_TOP - total_content
    gap = total_gap / n_gaps

    # Draw
    y = TEXT_TOP
    for i, (text, fnt, fill, kind) in enumerate(lines):
        if kind == "sep":
            draw.line([(200, int(y)), (W - 200, int(y))], fill=(80, 80, 80), width=1)
        else:
            draw_centered(text, int(y), fnt, fill)
        y += heights[i] + gap

    output_path = OUT / "flyer_v10_feed.png"
    canvas.save(output_path, quality=95)
    print(f"saved: {output_path}")

if __name__ == "__main__":
    build_flyer()
