#!/usr/bin/env python3
"""Generate Interzone XV flyer — variant B: urinal tableau + blue roses."""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses"
import numpy as np

SRC = PROJECT_DIR / "source"
OUT = PROJECT_DIR / "output"
OUT.mkdir(exist_ok=True)

W, H = 1080, 1620

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

def elliptical_vignette(w, h, cx, cy, strength=1.0):
    """Elliptical vignette that fades edges to black."""
    Y, X = np.ogrid[:h, :w]
    dx = (X - cx) / (w * 0.45)
    dy = (Y - cy) / (h * 0.45)
    dist = np.sqrt(dx**2 + dy**2)
    mask = np.clip(1.0 - (dist - 0.4) * strength, 0, 1)
    return mask

def build_flyer():
    canvas = Image.new("RGB", (W, H), (0, 0, 0))

    # === Hero: Urinal tableau (image5) — 1742x1260, iconic composition ===
    hero = load("image5.png")
    hero_bw = make_bw(hero, contrast=1.6, brightness=1.1)
    # Scale to fill width
    hero_ratio = hero_bw.width / hero_bw.height
    hero_w = W
    hero_h = int(hero_w / hero_ratio)
    hero_bw = hero_bw.resize((hero_w, hero_h), Image.LANCZOS)
    hero_rgb = Image.merge("RGB", [hero_bw, hero_bw, hero_bw])
    # Vignette
    vig = elliptical_vignette(hero_w, hero_h, hero_w // 2, hero_h // 2, strength=1.2)
    hero_arr = np.array(hero_rgb).astype(float)
    for c in range(3):
        hero_arr[:, :, c] *= vig
    hero_vignetted = Image.fromarray(hero_arr.clip(0, 255).astype(np.uint8))
    hero_y = 60
    canvas.paste(hero_vignetted, (0, hero_y))

    # === Blue roses (image1) as accent at bottom — tinted ===
    roses = load("image1.jpeg")
    roses_w = 500
    roses_ratio = roses.width / roses.height
    roses_h = int(roses_w / roses_ratio)
    roses = roses.resize((roses_w, roses_h), Image.LANCZOS)
    # Desaturate slightly and darken
    roses_bw = roses.convert("L")
    roses_tinted = Image.merge("RGB", [
        roses_bw,  # R channel (dim)
        roses_bw,  # G channel (dim)
        ImageEnhance.Brightness(roses_bw).enhance(1.4),  # B channel (brighter = blue tint)
    ])
    roses_tinted = ImageEnhance.Brightness(roses_tinted).enhance(0.4)
    # Vignette the roses
    vig_r = elliptical_vignette(roses_w, roses_h, roses_w // 2, roses_h // 2, strength=1.8)
    roses_arr = np.array(roses_tinted).astype(float)
    for c in range(3):
        roses_arr[:, :, c] *= vig_r
    roses_final = Image.fromarray(roses_arr.clip(0, 255).astype(np.uint8))
    roses_x = center_x(roses_w, W)
    roses_y = H - roses_h - 30
    canvas.paste(roses_final, (roses_x, roses_y))

    # === Rose frame overlay ===
    frame = load("image3.png")
    frame_white = invert_to_white_on_transparent(frame)
    frame_white = frame_white.resize((W - 60, H - 60), Image.LANCZOS)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(frame_white, (30, 30), frame_white)

    # === Rose medallion at top ===
    medallion = load("image0.jpeg")
    med_white = invert_to_white_on_transparent(medallion)
    med_size = 100
    med_white = med_white.resize((med_size, med_size), Image.LANCZOS)
    canvas_rgba.paste(med_white, (center_x(med_size, W), 32), med_white)

    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    # === Fonts ===
    DIDOT = "/System/Library/Fonts/Supplemental/Didot.ttc"
    BODONI_SC = "/System/Library/Fonts/Supplemental/Bodoni 72 Smallcaps Book.ttf"
    BODONI = "/System/Library/Fonts/Supplemental/Bodoni 72.ttc"
    BASKERVILLE = "/System/Library/Fonts/Supplemental/Baskerville.ttc"

    def font(path, size):
        try:
            return ImageFont.truetype(path, size)
        except:
            return ImageFont.load_default()

    title_font = font(BODONI_SC, 54)
    theme_font = font(DIDOT, 34)
    subtitle_font = font(BODONI, 28)
    body_font = font(BASKERVILLE, 22)
    small_font = font(BASKERVILLE, 18)
    tag_font = font(DIDOT, 17)

    def draw_centered(text, y, fnt, fill=(255, 255, 255)):
        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        draw.text((center_x(tw, W), y), text, fill=fill, font=fnt)

    # Text block starts below hero
    y = 820

    draw_centered("INTERZONE XV", y, title_font); y += 68
    draw_centered("Funeral Parade of Roses", y, theme_font, (220, 220, 220)); y += 50
    draw_centered("An irregular dance party for irregular people", y, tag_font, (150, 150, 150)); y += 45

    draw.line([(220, y), (W - 220, y)], fill=(70, 70, 70), width=1); y += 22

    draw_centered("DJs", y, small_font, (120, 120, 120)); y += 28
    draw_centered("SEITH  ·  Sister Malady", y, subtitle_font); y += 44

    draw_centered("Performances by", y, small_font, (120, 120, 120)); y += 28
    draw_centered("Rita Repulsive  ·  Mimento", y, subtitle_font); y += 50

    draw.line([(220, y), (W - 220, y)], fill=(70, 70, 70), width=1); y += 22

    draw_centered("Eleventh Hour Vendors Market", y, body_font, (170, 170, 170)); y += 42
    draw_centered("Saturday, March 21, 2026", y, subtitle_font); y += 38
    draw_centered("Al's Bar  ·  21+  ·  $10", y, body_font, (190, 190, 190)); y += 34
    draw_centered("Music at 8 PM  ·  Performances at 10 PM", y, small_font, (140, 140, 140))

    output_path = OUT / "flyer_v4b.png"
    canvas.save(output_path, quality=95)
    print(f"saved: {output_path}")

if __name__ == "__main__":
    build_flyer()
