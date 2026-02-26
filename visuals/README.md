# Visuals Pipeline

Programmatic video and image generation tools for DJ SEITH live visuals and event promotion. Python-based — no Photoshop, no After Effects.

## QA Standards

- **Text contrast** — WCAG AA minimum (4.5:1) measured at actual render positions
- **Text occlusion** — No text obscured by frames, images, or overlays

## Video Tools

### download_video.py
Download YouTube videos as source material.

```bash
python visuals/scripts/download_video.py -q              # process queue
python visuals/scripts/download_video.py "https://..."    # single URL
```

Queue file: `visuals/video_queue.md` | Output: `projects/<project>/source/video/`

### split_shots.py
Split videos into individual shots via PySceneDetect.

```bash
python visuals/scripts/split_shots.py                 # all videos
python visuals/scripts/split_shots.py -t 20           # more sensitive
python visuals/scripts/split_shots.py path/to/file    # specific file
```

Output: `shots/<source_slug>/shot_NNN.mp4` — audio stripped, h264 CRF 18.

### review_shots.py
Web UI at `localhost:8111` for manually reviewing shots.

| Key | Action |
|-----|--------|
| J / Left | One Shot (correct) |
| K / Right | Cut Into Smaller Shots |
| Down | Trash |
| Up | Favorite |

State: `review_state.json` — saved every click, resume anytime.

### tag_shots.py
Web UI at `localhost:8112` for tagging shots with descriptive labels. Shows favorites first, then ok shots.

```bash
python visuals/scripts/tag_shots.py
```

| Key | Action |
|-----|--------|
| 1-9 | Toggle tag (eddie, dancing, white, black, night, day, street, horror, sex) |
| Space / Right | Next shot |
| Left | Previous shot |

Filter dropdown: All / Untagged / Tagged. State saved to `review_state.json` under `"tags"`.

### find_duplicates.py
Perceptual hash deduplication across all shots.

```bash
python visuals/scripts/find_duplicates.py             # report only
python visuals/scripts/find_duplicates.py --dry-run   # preview deletions
python visuals/scripts/find_duplicates.py --delete    # delete dupes
python visuals/scripts/find_duplicates.py -t 12       # stricter matching
```

Uses pHash (16x16) across 3 frames per shot. Report: `duplicate_report/report.html`.

### phrase_detect.py
Detect musical sections/transitions in audio via spectral analysis.

```bash
python visuals/scripts/phrase_detect.py audio.wav --bpm 130 -o phrases.json
python visuals/scripts/phrase_detect.py audio.wav -n 10    # force 10 sections
```

Pipeline: beat tracking → beat-synced chroma + MFCC → recurrence matrix → checkerboard novelty → peak detection. Outputs per-section timing, energy, brightness.

### section_viz.py
Color-block video for verifying phrase detection. Each section = distinct color, white flash at transitions.

```bash
python visuals/scripts/section_viz.py phrases.json audio.wav [-o output.mp4]
```

### generate_video.py
Beat-synced video collage generator. Composites multiple shot layers with audio-reactive brightness, 2D still overlays, snare contrast flash, and pillarbox masking.

```bash
# Full render (favorites only, all features)
python visuals/scripts/generate_video.py \
  --audio audio/library/BlueMonday_130_Em/4_Mix_BlueMonday_130_Em.wav \
  --output projects/funeral_parade_of_roses/output/live-visuals/blue_monday_v1.mp4 \
  --snare projects/funeral_parade_of_roses/data/blue_monday_snare.json \
  --stills projects/funeral_parade_of_roses/stills/*.png \
  --favorites-only

# Fast 854×480 draft
python visuals/scripts/generate_video.py --audio ... --preview
```

**Key flags:**

| Flag | Default | Description |
|---|---|---|
| `--audio` | required | Mix WAV file |
| `--output` | `output/blue_monday_v1.mp4` | Output path |
| `--snare` | none | Snare JSON from detect_snare.py |
| `--stills` | none | PNG assets to overlay (space-separated) |
| `--stills-max-dur` | 15.0 | Max seconds a still stays on screen |
| `--stills-min-gap` | 20.0 | Min seconds between stills |
| `--favorites-only` | off | Use only favorited shots |
| `--tags` | none | Filter to shots matching ANY specified tag (e.g. `--tags eddie night`) |
| `--brightness-release` | 1.0 | Audio envelope release time (seconds) |
| `--no-brightness` | off | Disable audio-reactive brightness |
| `--blend` | screen | Layer blend mode |
| `--opacity` | 0.45 | Overlay layer opacity |
| `--seed` | 42 | RNG seed for reproducible output |
| `--preview` | off | Render at 854×480 for speed |

**Pipeline stages (in order):**
1. Composite video layers (screen blend, no pillarbox yet)
2. Audio-reactive brightness envelope (silence → black, with exponential release)
3. 2D stills overlay + pillarbox bars
4. Snare contrast flash (if `--snare`)

**Still placement rules** — determined automatically by filename. See `projects/funeral_parade_of_roses/DESIGN.md` for full spec.

### detect_snare.py
NMF+PCEN snare detection. Outputs JSON of snare hit times for use with `--snare`.

```bash
python visuals/scripts/detect_snare.py audio.wav -o output/snare.json
```

### analyze_shots.py
Compute motion scores for all shots in the catalog.

```bash
python visuals/scripts/analyze_shots.py
```

## Flyer / Promo Tools

In `projects/funeral_parade_of_roses/`:

- **make_flyer.py** — 1080x1350 (4:5) event flyer with composition grid (1/3 rule, 1/4 rule, even text distribution)
- **make_video.py** — Beat-synced 1080x1920 (9:16) reveal video
- **qa_check.py** — Automated contrast + occlusion checks

## Dependencies

```
pip install Pillow librosa scenedetect[opencv] imagehash yt-dlp
```

Requires `ffmpeg` and `ffprobe` on PATH.
