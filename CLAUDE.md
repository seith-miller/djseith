# Working with DJ SEITH

## Project Overview

DJ SEITH is SEITH's performance toolkit: audio processing pipeline (BPM, stems, time-stretch) + live visual generation system for events.

Current active event: **Interzone XV: Funeral Parade of Roses** — Al's Bar, March 21, 2026.

---

## Working Style

**Be concise.** Short responses, no preamble. Don't narrate what you're about to do — just do it.

**Iterative and preview-driven.** SEITH reviews outputs and gives feedback. Render in the background when possible so the conversation can continue. Open previews automatically with `open`.

**Background tasks.** Use `run_in_background=True` for video renders and other long operations. Notify when done. Don't block the conversation waiting for them.

---

## Voice-to-Text Quirks

SEITH often dictates rather than types. Read intent, not literal transcription. Common substitutions:

| What's spoken | What's meant |
|---|---|
| "congee" | **kanji** (Japanese characters) |
| "TD assets" / "skills" | **2D stills** / still image assets |
| "pillar boxing" | pillarbox |
| "conjuring" | kanji |
| "246 tracks" | 246 seconds (track duration) |
| "image zero / one / eleven" | `image0_bw.png`, `image1_bw.png`, `image11_bw.png` |

---

## Python Environment

Project uses **Python 3.12** via `venv/` (rebuilt from `/opt/homebrew/bin/python3.12`). pip works normally.

| Task | Use |
|---|---|
| Run pipeline scripts | `venv/bin/python visuals/scripts/generate_video.py ...` |
| pip install | `venv/bin/pip install <package>` |
| rembg (background removal) | `/opt/homebrew/bin/python3` — installed system-wide |

**PyTorch compositing:** The render pipeline uses PyTorch for GPU-accelerated compositing (MPS on Mac, CUDA on NVIDIA, CPU fallback). Use `--legacy` flag to fall back to the old ffmpeg filter graph pipeline.

---

## Asset Generation

### Kanji (Japanese characters)
Use ImageMagick with Hiragino Mincho ProN. Must use file path — the font name doesn't resolve:

```bash
magick -size 1920x1080 xc:transparent \
  -font "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc" -pointsize 300 \
  -fill black -stroke black -strokewidth 20 -gravity Center -annotate 0 "漢字" \
  -fill white -stroke none -gravity Center -annotate 0 "漢字" \
  projects/funeral_parade_of_roses/stills/kanji_name.png
```

Single-character kanji (e.g. 血, 幻) appear smaller than multi-character words at the same pointsize. Consider using a larger pointsize (e.g. 600) for single-character assets.

### Background removal (rembg)
```python
from rembg import remove
from PIL import Image
result = remove(Image.open('input.jpg'))
result.save('output.png')
```
Model (u2net.onnx, 176 MB) downloads to `~/.u2net/` on first use.

### SVG → PNG with transparency
```bash
magick -background none input.svg -resize 1920x1080 -gravity Center -extent 1920x1080 output.png
```

---

## Video Encoding Settings

| Setting | Value | Notes |
|---|---|---|
| CRF | **26** | Chosen for disk space. ~7 MB/20s at 1920×1080. Easier on playback than lower CRF. |
| Codec | libx264 | Hardware-accelerated decode in DJ software |
| Resolution | 1920×1080 | Full HD |

---

## Key File Locations

| What | Where |
|---|---|
| Audio mix files | `audio/library/<TrackName_BPM_Key>/4_Mix_*.wav` |
| Audio scripts | `audio/scripts/` |
| Audio staging | `audio/staging/` |
| Audio playlists | `audio/playlists/` |
| Event design doc | `projects/funeral_parade_of_roses/DESIGN.md` |
| Shot catalog | `projects/funeral_parade_of_roses/data/shot_catalog.json` |
| Review state (favorites + tags) | `projects/funeral_parade_of_roses/data/review_state.json` |
| Phrase/beat data | `projects/funeral_parade_of_roses/data/blue_monday_phrases_impact.json` |
| Snare detection data | `projects/funeral_parade_of_roses/data/blue_monday_snare.json` |
| Still assets | `projects/funeral_parade_of_roses/stills/` |
| Live visuals output | `projects/funeral_parade_of_roses/output/live-visuals/` |
| Flyer output | `projects/funeral_parade_of_roses/output/flyers/` |
| Promo output | `projects/funeral_parade_of_roses/output/promo/` |
| Main render script | `visuals/scripts/generate_video.py` |
| Shot tagging UI | `visuals/scripts/tag_shots.py` |
