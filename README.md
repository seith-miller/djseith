# DJ Seith - Audio Processing Pipeline

ETL pipeline for preparing DJ sets: download, analyze, time-stretch, and stem-separate tracks.

## Workflow

```
┌───────────────┐
│ playlists.md  │  (Spotify playlist URLs)
└───────────────┘
        │
        ▼
┌─────────────┐     ┌─────────────┐
│ spotify.py  │────▶│ to_get.md   │  (track queue + YouTube search URLs)
└─────────────┘     └─────────────┘
                          │
                          ▼
                    ┌──────────────┐
                    │ audition.py  │  (web UI: pick correct versions)
                    └──────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │ download.py │
                    └─────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │  staging/   │  (raw audio)
                    └─────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │ analyze.py  │  (BPM/key detection)
                    └─────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │ process.py  │  (time-stretch + stems)
                    └─────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │   output/   │
                    └─────────────┘
                          │
                          ▼
                    ┌──────────────┐
                    │ playlist.py  │  (organize into sets)
                    └──────────────┘
                          │
                          ▼
                    ┌──────────────┐
                    │  playlists/  │  (per-event markdown files)
                    └──────────────┘
```

## Scripts

### spotify.py - Import from Spotify
```bash
# Import all playlists from playlists.md
python spotify.py

# Import a specific playlist
python spotify.py https://open.spotify.com/playlist/YOUR_PLAYLIST_ID

# Download directly to staging/
python spotify.py --download https://open.spotify.com/playlist/YOUR_PLAYLIST_ID
```

### audition.py - Pick Correct Versions
```bash
# Opens browser with track list, YouTube search links, and paste boxes
python audition.py
```

### download.py - Download from YouTube
```bash
# Download all tracks with video URLs (skips search URLs)
python download.py

# Use cookies for age-restricted videos
python download.py --cookies
```

### analyze.py - Analyze BPM and Key
```bash
# Show BPM and key of all staged tracks
python analyze.py
```

### process.py - Time-stretch and Stem Separate
```bash
# Process all staged tracks at target BPM
python process.py --bpm 130

# Process specific files
python process.py --bpm 130 staging/track1.mp3 staging/track2.mp3

# Skip stem separation (mix only)
python process.py --bpm 120 --no-stems staging/track.mp3
```

### playlist.py - Manage Playlists
```bash
# Create a new playlist
python playlist.py new "Friday Goth Night" --date 2026-03-01 --venue "The Coffin Club"

# Add tracks (by output folder name)
python playlist.py add friday-goth BlueMonday_130_Em
python playlist.py add friday-goth ShePastAwayRitel_120_Am --position 1

# Remove a track
python playlist.py remove friday-goth BlueMonday_130_Em

# List all playlists
python playlist.py list

# Show playlist with durations and keys
python playlist.py show friday-goth

# Validate all tracks exist in output/
python playlist.py validate friday-goth
```

Playlists live in `playlists/` as markdown files you can also edit by hand.

## Output Structure

```
output/
└── TrackName_130_Am/
    ├── 0_Vox_TrackName_130_Am.wav
    ├── 1_Other_TrackName_130_Am.wav
    ├── 2_Bass_TrackName_130_Am.wav
    ├── 3_Drums_TrackName_130_Am.wav
    └── 4_Mix_TrackName_130_Am.wav
```

## Dependencies

```bash
pip install yt-dlp librosa soundfile demucs
brew install rubberband
```
