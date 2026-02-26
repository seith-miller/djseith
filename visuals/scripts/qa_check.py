#!/usr/bin/env python3
"""QA checks for flyer: text contrast and text occlusion."""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.parent / "projects" / "funeral_parade_of_roses"
import numpy as np

SRC = PROJECT_DIR / "source"
OUT = PROJECT_DIR / "output"

W, H = 1080, 1350  # 4:5 feed post

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

def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except:
        return ImageFont.load_default()

def srgb_to_linear(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def relative_luminance(r, g, b):
    return 0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g) + 0.0722 * srgb_to_linear(b)

def contrast_ratio(l1, l2):
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

def build_background():
    canvas = Image.new("RGB", (W, H), (0, 0, 0))

    THIRD = H // 3  # 450

    # Hero eyes centered at 1/3 mark
    hero = load("image4.png")
    hero_bw = make_bw(hero, contrast=1.5, brightness=1.2)
    hero_ratio = hero_bw.width / hero_bw.height
    hero_w = int(W * 0.75)
    hero_h = int(hero_w / hero_ratio)
    hero_bw = hero_bw.resize((hero_w, hero_h), Image.LANCZOS)
    hero_rgb = Image.merge("RGB", [hero_bw, hero_bw, hero_bw])
    hero_x = center_x(hero_w, W)
    hero_y = THIRD - hero_h // 2

    vignette = radial_vignette(hero_w, hero_h, hero_w // 2, hero_h // 2, 150, 350)
    hero_arr = np.array(hero_rgb).astype(float)
    for c in range(3):
        hero_arr[:, :, c] *= vignette
    hero_vignetted = Image.fromarray(hero_arr.clip(0, 255).astype(np.uint8))
    canvas.paste(hero_vignetted, (hero_x, hero_y))

    frame = load("image3.png")
    frame_white = invert_to_white_on_transparent(frame)
    frame_white = frame_white.resize((W - 60, H - 60), Image.LANCZOS)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(frame_white, (30, 30), frame_white)

    frame_alpha = np.array(frame_white)[:, :, 3]
    frame_mask_full = np.zeros((H, W), dtype=np.uint8)
    fh, fw = frame_alpha.shape
    frame_mask_full[30:30+fh, 30:30+fw] = frame_alpha

    return canvas_rgba.convert("RGB"), frame_mask_full

def get_text_elements():
    """Compute text positions matching make_flyer.py layout exactly."""
    DIDOT = "/System/Library/Fonts/Supplemental/Didot.ttc"
    BODONI = "/System/Library/Fonts/Supplemental/Bodoni 72.ttc"
    BODONI_SC = "/System/Library/Fonts/Supplemental/Bodoni 72 Smallcaps Book.ttf"
    BASKERVILLE = "/System/Library/Fonts/Supplemental/Baskerville.ttc"

    title_font = font(BODONI_SC, 86)
    numeral_font = font(DIDOT, 48)
    theme_font = font(DIDOT, 46)
    subtitle_font = font(BODONI, 38)
    body_font = font(BASKERVILLE, 30)
    small_font = font(BASKERVILLE, 26)

    # Need a temp draw for measuring
    from PIL import Image as _Img
    _tmp = _Img.new("RGB", (1, 1))
    _draw = ImageDraw.Draw(_tmp)

    def th(text, fnt):
        bbox = _draw.textbbox((0, 0), text, font=fnt)
        return bbox[3] - bbox[1]

    elements = []

    # Title at 1/4 mark (has black stroke)
    QUARTER = H // 4
    title_h = th("INTERZONE", title_font)
    numeral_h = th("XV", numeral_font)
    title_block = title_h + 8 + numeral_h
    title_y = QUARTER - title_block // 2
    elements.append(("INTERZONE", title_y, title_font, (255, 255, 255), "title_stroke"))
    elements.append(("XV", title_y + title_h + 8, numeral_font, (200, 200, 200), "numeral_stroke"))

    # Text block in lower half — evenly distributed
    TEXT_TOP = H // 2 + 5
    TEXT_BOT = 1260

    lines = [
        ("Funeral Parade of Roses", theme_font, (220, 220, 220), "theme"),
        (None, None, None, "sep"),
        ("DJs", small_font, (140, 140, 140), "djs_label"),
        ("SEITH  ·  Sister Malady", subtitle_font, (255, 255, 255), "djs"),
        ("Performances", small_font, (140, 140, 140), "perf_label"),
        ("Rita Repulsive  ·  Mimento", subtitle_font, (255, 255, 255), "performers"),
        (None, None, None, "sep"),
        ("Eleventh Hour Vendors Market", body_font, (180, 180, 180), "vendors"),
        ("Saturday, March 21, 2026", subtitle_font, (255, 255, 255), "date"),
        ("Al's Bar  ·  21+  ·  $10", body_font, (200, 200, 200), "venue"),
        ("Music 8 PM  ·  Performances 10 PM", small_font, (160, 160, 160), "times"),
    ]

    heights = []
    for text, fnt, _, kind in lines:
        if kind == "sep":
            heights.append(1)
        else:
            heights.append(th(text, fnt))

    total_content = sum(heights)
    n_gaps = len(lines) - 1
    gap = (TEXT_BOT - TEXT_TOP - total_content) / n_gaps

    y = float(TEXT_TOP)
    for i, (text, fnt, fill, kind) in enumerate(lines):
        if kind != "sep":
            elements.append((text, int(y), fnt, fill, kind))
        y += heights[i] + gap

    return elements

def run_checks():
    print("Building background (no text)...\n")
    bg, frame_mask = build_background()
    bg_arr = np.array(bg)
    draw = ImageDraw.Draw(bg)

    elements = get_text_elements()

    print("=" * 60)
    print("CHECK 1: Text Contrast (WCAG AA minimum 4.5:1)")
    print("=" * 60)

    all_pass = True
    for text, y, fnt, fill, label in elements:
        # Stroked text has guaranteed contrast via black outline
        if label.endswith("_stroke"):
            print(f"  [{label}] \"{text}\" — SKIP (has black stroke outline)")
            continue

        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = center_x(tw, W)

        y_start = max(0, y)
        y_end = min(H, y + th)
        x_start = max(0, x)
        x_end = min(W, x + tw)

        region = bg_arr[y_start:y_end, x_start:x_end]
        if region.size == 0:
            print(f"  [{label}] SKIP — text outside canvas")
            continue

        avg_r = float(np.mean(region[:, :, 0]))
        avg_g = float(np.mean(region[:, :, 1]))
        avg_b = float(np.mean(region[:, :, 2]))

        max_r = float(np.max(region[:, :, 0]))
        max_g = float(np.max(region[:, :, 1]))
        max_b = float(np.max(region[:, :, 2]))

        text_lum = relative_luminance(np.array(fill[0]), np.array(fill[1]), np.array(fill[2]))
        bg_avg_lum = relative_luminance(np.array(avg_r), np.array(avg_g), np.array(avg_b))
        bg_max_lum = relative_luminance(np.array(max_r), np.array(max_g), np.array(max_b))

        cr_avg = contrast_ratio(float(text_lum), float(bg_avg_lum))
        cr_worst = contrast_ratio(float(text_lum), float(bg_max_lum))

        status_avg = "PASS" if cr_avg >= 4.5 else "FAIL"
        status_worst = "PASS" if cr_worst >= 4.5 else "FAIL"

        if status_avg == "FAIL" or status_worst == "FAIL":
            all_pass = False

        print(f"  [{label}] \"{text}\"")
        print(f"    text color: {fill}  |  bg avg: ({avg_r:.0f},{avg_g:.0f},{avg_b:.0f})  |  bg brightest: ({max_r:.0f},{max_g:.0f},{max_b:.0f})")
        print(f"    avg contrast: {cr_avg:.1f}:1 [{status_avg}]  |  worst contrast: {cr_worst:.1f}:1 [{status_worst}]")

    print()
    print("=" * 60)
    print("CHECK 2: Text Occlusion (frame/overlay covering text)")
    print("=" * 60)

    for text, y, fnt, fill, label in elements:
        if label.endswith("_stroke"):
            print(f"  [{label}] SKIP (has black stroke outline)")
            continue

        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = center_x(tw, W)

        y_start = max(0, y)
        y_end = min(H, y + th)
        x_start = max(0, x)
        x_end = min(W, x + tw)

        region_mask = frame_mask[y_start:y_end, x_start:x_end]
        if region_mask.size == 0:
            print(f"  [{label}] SKIP — text outside canvas")
            continue

        occluded_pixels = np.sum(region_mask > 128)
        total_pixels = region_mask.size
        occluded_pct = (occluded_pixels / total_pixels) * 100 if total_pixels > 0 else 0

        status = "PASS" if occluded_pct < 1.0 else "FAIL"
        if status == "FAIL":
            all_pass = False

        print(f"  [{label}] frame overlap: {occluded_pct:.1f}% ({occluded_pixels}/{total_pixels} px) [{status}]")

    print()
    print("=" * 60)
    if all_pass:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED — see above")
    print("=" * 60)

if __name__ == "__main__":
    run_checks()
