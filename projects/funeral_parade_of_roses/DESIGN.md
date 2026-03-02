# Interzone XV: Funeral Parade of Roses — Visual Design

## Event
- **Name:** Interzone XV: Funeral Parade of Roses
- **Venue:** Al's Bar
- **Date:** Saturday, March 21, 2026
- **Cover:** $10 / 21+

## Film Reference

**薔薇の葬列 (Funeral Parade of Roses)** — Toshio Matsumoto, 1969.
Japanese avant-garde / experimental film. High-contrast B&W, Tokyo underground nightlife, trans/queer themes, Oedipus Rex inversion. The film's Japanese title (verified correct, appears on original Japanese posters and releases) is used as a title card asset.

---

## Render Command

```bash
venv/bin/python visuals/scripts/generate_video.py \
  --audio audio/library/BlueMonday_130_Em/4_Mix_BlueMonday_130_Em.wav \
  --output projects/funeral_parade_of_roses/output/live-visuals/blue_monday_v1.mp4 \
  --snare projects/funeral_parade_of_roses/data/blue_monday_snare.json \
  --stills \
    projects/funeral_parade_of_roses/stills/chrysanthemum_photo_transparent.png \
    projects/funeral_parade_of_roses/stills/image0_bw.png \
    projects/funeral_parade_of_roses/stills/image1_bw.png \
    projects/funeral_parade_of_roses/stills/image11_bw.png \
    projects/funeral_parade_of_roses/stills/kanji_chi.png \
    projects/funeral_parade_of_roses/stills/kanji_kodomo.png \
    projects/funeral_parade_of_roses/stills/kanji_maboroshi.png \
    projects/funeral_parade_of_roses/stills/kanji_maigo.png \
    projects/funeral_parade_of_roses/stills/kanji_okami.png \
    projects/funeral_parade_of_roses/stills/kanji_shofu.png \
    projects/funeral_parade_of_roses/stills/kanji_unmei.png \
    projects/funeral_parade_of_roses/stills/title_funeral_parade.png \
    projects/funeral_parade_of_roses/stills/title_interzone_xv.png \
  --favorites-only

# Add --preview for fast 854x480 draft
```

---

## Layer Composition (back → front)

1. **Black base** — always
2. **Up to 3 video layers** — screen-blended; count driven by section energy
3. **One 2D still** — alpha overlay; only one on screen at a time
4. **Pillarbox bars** — black bars masking to Academy ratio; always topmost

---

## Design Modes

A design mode is a coherent set of rules governing brightness, color, and framing. Each mode produces a distinct visual character from the same source material. Select with `--white-mode` (default is black mode).

### Black Mode (default)

| Element | Rule |
|---|---|
| Brightness blend | `multiply` — silence → black, loud → full brightness |
| Envelope floor | 0.0 (true black in silence) |
| Pillarbox bars | Black |
| Snare flash | contrast=2.2, brightness=+0.06, 80ms |
| Layer blend | `screen` at 0.45 opacity (layer 2 at 0.6× = 0.27) |
| Cultural ref | High-contrast B&W film noir; darkness as negative space |

### White Mode (`--white-mode`)

| Element | Rule |
|---|---|
| Brightness blend | None — envelope disabled; video plays at full brightness |
| Envelope floor | N/A |
| Pillarbox bars | Black (same as all modes) |
| Snare flash | Same as black mode (contrast=2.2, brightness=+0.06, 80ms) |
| Layer blend | Same as black mode (`screen` at 0.45 opacity) |
| Cultural ref | White as Japanese mourning color; overexposed / high-key aesthetic |

### Shared across all modes

- Exponential release (default 1.0s) — volume drops decay gradually, not instantly
- 2D stills are **not** affected by the brightness envelope — overlaid after brightness stage
- Strobe modulation (if enabled) applies to the envelope before mode-specific remapping
- Smoothing window (if set) applies before strobe

CLI: `--brightness-release 1.0` / `--no-brightness` / `--white-mode`

---

## 2D Stills — Scheduling Rules

- Enter **hard** on phrase/section transition moments
- Exit **on a beat** — last beat within the on-screen window
- **Max on-screen:** 15 seconds
- **Min gap between stills:** 20 seconds
- **Only one still at a time**
- **First slot** always uses a title card (Interzone XV or 薔薇の葬列)
- Subsequent slots: random from full pool

---

## 2D Stills — Per-Asset Placement Rules

| Asset | Placement | Motion |
|---|---|---|
| `title_interzone_xv.png` | Dead center (fixed) | Static |
| `title_funeral_parade.png` | Dead center (fixed) | Static |
| `image1_bw.png` | Fixed at x=0,y=0 (as-is) | Static |
| `image11_bw.png` | Fixed at x=0,y=0 (as-is) | Static |
| `chrysanthemum_photo_transparent.png` | Random position (±W/4, ±H/4), different each render | Static |
| `image0_bw.png` | Random position (±W/4, ±H/4), different each render | Static |
| `kanji_*.png` | Starts off-screen, travels through center, exits far side | Animated pan |

**Kanji pan directions** (random each occurrence, 8 options):
`l2r`, `r2l`, `t2b`, `b2t`, `tl2br`, `tr2bl`, `bl2tr`, `br2tl`

**Kanji scale:** Rendered at 2× canvas size (3840×2160) so text appears twice as large on the 1920×1080 output.

---

## Snare Detection

NMF+PCEN snare detection via `detect_snare.py`. 200 hits identified, 100% precision.
Effect: contrast boost (`eq=contrast=2.2`) for 80ms on each hit.
Data: `projects/funeral_parade_of_roses/data/blue_monday_snare.json`

---

## Asset Inventory — `projects/funeral_parade_of_roses/stills/`

### Title Cards

| File | Content | Notes |
|---|---|---|
| `title_interzone_xv.png` | "INTERZONE XV" | Rockwell font, rotated 12° CCW, cropped to 1920×1080. White on transparent. |
| `title_funeral_parade.png` | 薔薇の葬列 | Hiragino Mincho ProN W6. Japanese title of film. White on transparent. |

### Photographic

| File | Content | Notes |
|---|---|---|
| `chrysanthemum_photo_transparent.png` | White chrysanthemum flower | Real photo, rembg background removal, desaturated (B&W), contrast boosted. Japanese funeral flower. |
| `image0_bw.png` | — | B&W still |
| `image1_bw.png` | — | B&W still |
| `image11_bw.png` | — | B&W still |

### Kanji Assets (character describing Eddie, protagonist)

All: Hiragino Mincho ProN, pointsize 300, white with black outline, 1920×1080 transparent background.

| File | Kanji | Reading | Meaning |
|---|---|---|---|
| `kanji_kodomo.png` | 子供 | kodomo | child |
| `kanji_shofu.png` | 娼婦 | shōfu | prostitute |
| `kanji_maigo.png` | 迷子 | maigo | lost child |
| `kanji_maboroshi.png` | 幻 | maboroshi | phantom, illusion |
| `kanji_chi.png` | 血 | chi | blood |
| `kanji_unmei.png` | 運命 | unmei | fate, destiny |
| `kanji_okami.png` | 女将 | okami | proprietress/madame (woman who runs the establishment) |

**Note:** Single-character kanji (幻, 血) appear smaller than multi-character ones at the same pointsize. Consider regenerating at ~600pt if visual weight feels uneven.

---

## Japanese Funeral Imagery — Cultural Notes

Symbols used or considered for this project:
- **白菊 (shiragiku)** — white chrysanthemum; primary Japanese funeral flower (used ✓)
- **薔薇の葬列** — the film title itself
- **White** — traditional Japanese mourning color (not black); informs the B&W high-key aesthetic

---

## Pillarbox

Academy ratio mask applied via `drawbox` in ffmpeg. Width: `(1920 - 1080 × PILLARBOX_RATIO) / 2` pixels on each side. Config in `visuals/config.py`.
