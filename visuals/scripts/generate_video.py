#!/usr/bin/env python3
"""Generate a beat-synced video collage from shot catalog + musical section data.

Assembly logic:
  - Section energy → cut frequency (every 2/4/8 beats) and layer count (1/2/3)
  - Shot motion score matched to section energy
  - Favorited shots get a selection boost
  - Higher layers blend over primary via ffmpeg blend filter

Usage:
  python visuals/generate_video.py \\
      --audio audio/library/BlueMonday_130_Em/4_Mix_BlueMonday_130_Em.wav \\
      --preview   # fast 480p draft
"""

import argparse, json, os, random, subprocess, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import sys; sys.path.insert(0, str(Path(__file__).parent.parent))
from config import RESOLUTION, FPS, PILLARBOX_RATIO
from compositing import (
    get_device, ClipDecoder, FrameDecoder, decode_still,
    FrameEncoder, composite_frame,
)

W, H = RESOLUTION

_PROJECT        = Path(__file__).parent.parent.parent / "projects/funeral_parade_of_roses"
SHOTS_DIR       = _PROJECT / "shots"
DEFAULT_CATALOG = _PROJECT / "data/shot_catalog.json"
DEFAULT_PHRASES = _PROJECT / "data/blue_monday_phrases_impact.json"
DEFAULT_REVIEW  = _PROJECT / "data/review_state.json"
DEFAULT_OUTPUT  = _PROJECT / "output/live-visuals/blue_monday_v1.mp4"

# motion range from analyze_shots summary (0 – 0.243)
MOTION_MAX = 0.243


def resolve_track_metadata(audio_path: str) -> tuple[Path | None, Path | None]:
    """Auto-resolve phrases.json and snare.json from the track directory.

    If --audio points to a file inside audio/library/<TrackName>/,
    look for phrases.json and snare.json alongside the audio.
    Returns (phrases_path, snare_path) — either may be None.
    """
    audio = Path(audio_path).resolve()
    track_dir = audio.parent

    phrases = track_dir / "phrases.json"
    snare = track_dir / "snare.json"

    return (
        phrases if phrases.exists() else None,
        snare if snare.exists() else None,
    )


# ── section characterization ──────────────────────────────────────────────────

def compute_thresholds(sections):
    """Derive per-track energy breakpoints using percentiles.

    Splits the track's actual energy range into thirds so that every song —
    regardless of absolute loudness — has low/mid/high sections.
    Returns (low, high) thresholds for 1→2 and 2→3 layer transitions.
    """
    energies = np.array([s['energy'] for s in sections])
    return float(np.percentile(energies, 33)), float(np.percentile(energies, 66))


def section_params(energy, thresholds):
    """Return (beats_per_cut, n_layers) based on per-track energy thresholds."""
    low, high = thresholds
    if energy <= low:
        return 8, 1   # quiet:  slow cuts, single layer
    elif energy <= high:
        return 4, 2   # mid:    medium cuts, 2 layers
    else:
        return 2, 3   # loud:   fast cuts, 3 layers


# ── shot selection ────────────────────────────────────────────────────────────

def load_shots(catalog_path):
    data = json.loads(Path(catalog_path).read_text())
    shots = list(data.values())
    return [s for s in shots if s.get('duration', 0) >= 0.3]


def load_favorites(review_path):
    """Return set of shot filenames for favorited shots."""
    if not Path(review_path).exists():
        return set()
    state = json.loads(Path(review_path).read_text())
    return {Path(rel).name for rel in state.get('favorites', [])}


def load_tags(review_path):
    """Return dict mapping shot filename → set of tags."""
    if not Path(review_path).exists():
        return {}
    state = json.loads(Path(review_path).read_text())
    raw = state.get('tags', {})
    return {Path(rel).name: set(tag_list) for rel, tag_list in raw.items() if tag_list}


def score_shot(shot, target_motion, min_dur, favorites, recently_used, slowdown=1.0):
    if shot['duration'] < (min_dur / slowdown) * 0.5:
        return 0.0
    motion_err  = abs(shot['motion'] - target_motion) / (MOTION_MAX + 1e-6)
    motion_score = max(0.0, 1.0 - motion_err)
    fav_boost    = 0.3 if Path(shot['path']).name in favorites else 0.0
    recency_pen  = 0.7 if shot['path'] in recently_used else 0.0
    return max(0.0, motion_score + fav_boost - recency_pen)


def pick_shot(shots, target_motion, min_dur, favorites, recently_used, rng):
    scored = sorted(
        ((score_shot(s, target_motion, min_dur, favorites, recently_used), s)
         for s in shots),
        key=lambda x: x[0], reverse=True
    )
    # pick randomly from top 12 candidates to avoid repetition
    candidates = [s for sc, s in scored[:12] if sc > 0]
    if not candidates:
        candidates = shots  # last resort fallback
    return rng.choice(candidates)


def pick_inpoint(shot, needed, slowdown, rng):
    src_needed = needed / slowdown
    slack = shot['duration'] - src_needed
    return round(rng.uniform(0, max(0.0, slack)), 4)


# ── timeline builder ──────────────────────────────────────────────────────────

def build_layer(layer_idx, sections, beat_times, shots, favorites, total_duration, thresholds, rng):
    """Return list of clip events: [{path, inpoint, duration}]."""
    beat_arr     = np.array(beat_times)
    clips        = []
    recently_used = []
    max_recent   = 10

    def add_clip(shot, needed, slowdown=1.0):
        inpoint = pick_inpoint(shot, needed, slowdown, rng)
        clips.append({
            'path': shot['path'],
            'inpoint': inpoint,
            'duration': needed,
            'file_duration': shot['duration'],
            'slowdown': slowdown,
        })
        recently_used.append(shot['path'])
        if len(recently_used) > max_recent:
            recently_used.pop(0)

    for sec in sections:
        t_start = sec['start_time']
        t_end   = sec['end_time']
        energy  = sec['energy']
        beats_per_cut, n_layers = section_params(energy, thresholds)

        # target motion for this layer: primary tracks energy, overlays use contrast
        if layer_idx == 0:
            target_motion = energy * MOTION_MAX
        elif layer_idx == 1:
            target_motion = (1.0 - energy) * MOTION_MAX * 0.5  # calmer overlay
        else:
            target_motion = MOTION_MAX * 0.05  # very calm background

        if layer_idx >= n_layers:
            # layer inactive this section — output black so screen blend is transparent
            clips.append({
                'path': 'black',
                'inpoint': 0,
                'duration': t_end - t_start,
                'file_duration': float('inf'),
                'slowdown': 1.0,
            })
            continue

        # layer 0 cuts on beats; higher layers cut once per section
        if layer_idx == 0:
            mask      = (beat_arr >= t_start) & (beat_arr < t_end)
            sec_beats = beat_arr[mask]
            if len(sec_beats) == 0:
                sec_beats = np.array([t_start])
            cut_times = list(sec_beats[::beats_per_cut]) + [t_end]
        else:
            cut_times = [t_start, t_end]

        for i in range(len(cut_times) - 1):
            needed = cut_times[i + 1] - cut_times[i]
            if needed < 0.05:
                continue
            # low-energy sections: randomly slow down some clips
            if energy < 0.35 and layer_idx == 0 and rng.random() < 0.4:
                slowdown = rng.choice([1.5, 2.0])
            else:
                slowdown = 1.0
            shot = pick_shot(shots, target_motion, needed, favorites, recently_used, rng)
            add_clip(shot, needed, slowdown)

    # pad to full duration if needed
    total = sum(c['duration'] for c in clips)
    gap   = total_duration - total
    if gap > 0.05:
        shot = rng.choice(shots)
        add_clip(shot, gap)

    return clips


def inject_solos(clips, solos, layer_idx):
    """Splice forced solo clips into a layer timeline.

    For layer 0: replaces the collage with the solo source video.
    For layers 1+: replaces the solo window with black (transparent under blend).

    Each solo is {time, path, duration}.  clips are [{path, inpoint, duration, ...}].
    """
    if not solos:
        return clips

    result = []
    t = 0.0  # running position in timeline

    # sort solos by time
    solos = sorted(solos, key=lambda s: s['time'])
    solo_idx = 0

    for clip in clips:
        clip_start = t
        clip_end   = t + clip['duration']
        remaining  = dict(clip)  # copy we'll trim from

        while solo_idx < len(solos):
            solo = solos[solo_idx]
            solo_start = solo['time']
            solo_end   = solo['time'] + solo['duration']

            # solo is entirely past this clip
            if solo_start >= clip_end - 0.01:
                break

            # solo is entirely before current position (already handled)
            if solo_end <= clip_start + 0.01:
                solo_idx += 1
                continue

            # emit portion before solo starts (if any)
            pre = solo_start - clip_start
            if pre > 0.05:
                pre_clip = dict(remaining)
                pre_clip['duration'] = pre
                result.append(pre_clip)

            # emit the solo clip (or black for overlay layers)
            solo_dur_here = min(solo_end, clip_end) - max(solo_start, clip_start)
            if solo_dur_here > 0.01:
                if layer_idx == 0:
                    # play the forced source video from beginning
                    solo_inpoint = max(0, clip_start - solo_start) if clip_start > solo_start else 0
                    result.append({
                        'path': solo['path'],
                        'inpoint': solo_inpoint,
                        'duration': solo_dur_here,
                        'file_duration': solo['duration'],
                        'slowdown': 1.0,
                    })
                else:
                    result.append({
                        'path': 'black',
                        'inpoint': 0,
                        'duration': solo_dur_here,
                        'file_duration': float('inf'),
                        'slowdown': 1.0,
                    })

            # advance clip_start past this solo
            consumed = max(solo_start, clip_start) + solo_dur_here - clip_start
            clip_start += consumed
            # adjust remaining clip's inpoint
            if remaining['path'] != 'black':
                remaining['inpoint'] = remaining['inpoint'] + consumed / remaining.get('slowdown', 1.0)
            remaining['duration'] = clip_end - clip_start

            if solo_end <= clip_end + 0.01:
                solo_idx += 1

            if remaining['duration'] < 0.05:
                break

        # emit whatever's left of the clip after all solos
        if remaining['duration'] > 0.05 and clip_start < clip_end - 0.01:
            remaining['duration'] = clip_end - clip_start
            result.append(remaining)

        t = clip_end

    return result


# ── ffmpeg helpers ────────────────────────────────────────────────────────────

def _render_segment(args):
    """Render one clip segment to a temp file. Called in a thread pool."""
    path, inpoint, src_duration, out_duration, slowdown, out_path, width, height, fps = args

    if path == 'black':
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=black:size={width}x{height}:rate={fps}",
            "-t", str(src_duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-an",
            str(out_path),
        ]
    else:
        setpts = f"{slowdown:.4f}*(PTS-STARTPTS)" if slowdown != 1.0 else "PTS-STARTPTS"
        vf = (
            f"trim=start={inpoint:.6f}:duration={src_duration:.6f},"
            f"setpts={setpts},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps={fps},format=yuv420p"
        )
        cmd = [
            "ffmpeg", "-y", "-i", path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-an",
            str(out_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"segment render failed for {path}:\n{result.stderr[-500:]}")


def render_layer(clips, out_path, width, height, fps, tmpdir, layer_idx):
    """Pre-trim each clip with trim+setpts (accurate), then concat the segments."""
    # Expand clips into segments (each clip may loop if source is shorter than needed)
    segments = []
    for c in clips:
        file_dur  = c['file_duration']
        remaining = c['duration']
        cur_in    = c['inpoint']
        slowdown  = c.get('slowdown', 1.0)
        while remaining > 0.01:
            src_available = file_dur - cur_in
            src_needed    = remaining / slowdown
            src_play      = min(src_available, src_needed)
            out_play      = src_play * slowdown
            segments.append((c['path'], cur_in, src_play, out_play, slowdown))
            remaining -= out_play
            cur_in = 0.0

    seg_paths = [Path(tmpdir) / f"L{layer_idx}_seg{i:05d}.mp4" for i in range(len(segments))]
    jobs = [(path, inp, src_dur, out_dur, slow, seg_paths[i], width, height, fps)
            for i, (path, inp, src_dur, out_dur, slow) in enumerate(segments)]

    print(f"    rendering {len(jobs)} segments (parallel)...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(_render_segment, jobs))

    # Concat pre-trimmed segments (no inpoint/outpoint needed — durations are baked in)
    concat_path = Path(tmpdir) / f"L{layer_idx}_concat.txt"
    lines = ["ffconcat version 1.0"] + [f"file '{p}'" for p in seg_paths]
    concat_path.write_text("\n".join(lines))

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-c", "copy",
        str(out_path),
    ]
    print(f"    ffmpeg concat → {Path(out_path).name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFMPEG ERROR:\n", result.stderr[-2000:])
        raise RuntimeError("ffmpeg concat failed")


def composite_layers(layer_paths, audio_path, output_path, blend_mode, opacity, width, height,
                      apply_pillarbox=True, crf=26):
    inputs = []
    for p in layer_paths:
        inputs += ["-i", str(p)]
    inputs += ["-i", str(audio_path)]

    n = len(layer_paths)
    audio_idx = n

    # Pillarbox bar width for Academy ratio mask (uses actual output dimensions)
    bar_w = int((width - height * PILLARBOX_RATIO) / 2)

    # Convert to planar RGB before blending so blend math is in linear RGB space.
    # In YUV, neutral chroma ≠ 0, so screen/overlay push colors toward pink/green.
    pillarbox = (
        f"drawbox=x=0:y=0:w={bar_w}:h=ih:color=black:t=fill,"
        f"drawbox=x=iw-{bar_w}:y=0:w={bar_w}:h=ih:color=black:t=fill"
    )
    pb = f",{pillarbox}" if apply_pillarbox else ""

    if n == 1:
        filt = f"[0:v]format=gbrp,format=yuv420p{pb}[out]"
    elif n == 2:
        filt = (
            f"[0:v]format=gbrp[v0];[1:v]format=gbrp[v1];"
            f"[v0][v1]blend=all_mode={blend_mode}:all_opacity={opacity:.2f}[tmp];"
            f"[tmp]format=yuv420p{pb}[out]"
        )
    else:
        op2 = round(opacity * 0.6, 2)
        filt = (
            f"[0:v]format=gbrp[v0];[1:v]format=gbrp[v1];[2:v]format=gbrp[v2];"
            f"[v0][v1]blend=all_mode={blend_mode}:all_opacity={opacity:.2f}[tmp1];"
            f"[tmp1]format=gbrp[tmp1p];"
            f"[tmp1p][v2]blend=all_mode={blend_mode}:all_opacity={op2:.2f}[tmp2];"
            f"[tmp2]format=yuv420p{pb}[out]"
        )

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filt,
        "-map", "[out]",
        "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    print(f"    ffmpeg composite → {Path(output_path).name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFMPEG ERROR:\n", result.stderr[-2000:])
        raise RuntimeError("ffmpeg composite failed")


# ── audio-reactive brightness envelope ───────────────────────────────────────

def compute_brightness_envelope(audio_path: str, n_frames: int, fps: int,
                                 release_s: float = 1.0) -> np.ndarray:
    """Per-frame brightness envelope derived from audio RMS + exponential release.

    Returns array of n_frames values in [0, 1]:
      0 = black (silence), 1 = full brightness (peak loudness).

    The release smoothing means a sudden drop in volume decays gradually
    rather than cutting to black instantly.
    """
    import librosa
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    hop = max(1, int(sr / fps))

    rms = librosa.feature.rms(y=y, frame_length=hop * 4, hop_length=hop)[0]

    # Trim / pad to exact frame count
    if len(rms) >= n_frames:
        rms = rms[:n_frames]
    else:
        rms = np.pad(rms, (0, n_frames - len(rms)))

    # Normalise: 95th-percentile RMS → 1.0  (so the loudest sections are fully bright)
    peak = float(np.percentile(rms, 95))
    levels = np.clip(rms / (peak + 1e-9), 0.0, 1.0)

    # Exponential release: level[t] = max(rms[t], level[t-1] × r)
    r = float(np.exp(-1.0 / (release_s * fps)))
    env = np.zeros(n_frames)
    env[0] = float(levels[0])
    for i in range(1, n_frames):
        env[i] = max(float(levels[i]), env[i - 1] * r)

    return env


def smooth_envelope(env: np.ndarray, fps: int, window_s: float) -> np.ndarray:
    """Low-pass filter via centered moving average.

    Removes rapid luminance swings that cause PSE flash triggers.
    window_s is the smoothing window in seconds (e.g. 0.5 = half-second average).
    """
    if window_s <= 0:
        return env
    win = max(3, int(window_s * fps) | 1)  # odd window size
    kernel = np.ones(win) / win
    # Pad edges to avoid boundary artifacts
    padded = np.pad(env, win // 2, mode='edge')
    smoothed = np.convolve(padded, kernel, mode='valid')[:len(env)]
    return np.clip(smoothed, 0.0, 1.0)


def apply_strobe(envelope: np.ndarray, fps: int, strobe_hz: float,
                 strobe_depth: float, strobe_limit: float,
                 sections: list, strobe_mode: str,
                 thresholds: tuple) -> np.ndarray:
    """Modulate the brightness envelope with a strobe square wave.

    Args:
        envelope:      per-frame brightness [0,1]
        fps:           frames per second
        strobe_hz:     desired strobe frequency (flashes/sec)
        strobe_depth:  0.0 = no effect, 1.0 = full on/off
        strobe_limit:  hard safety cap (Hz), strobe_hz gets clamped
        sections:      phrase sections with start_time, end_time, energy
        strobe_mode:   'high' = only high-energy sections,
                       'all'  = every section,
                       'none' = disabled
        thresholds:    (low, high) energy thresholds from compute_thresholds

    Returns modified envelope with strobe modulation applied.
    """
    if strobe_mode == 'none' or strobe_hz <= 0 or strobe_depth <= 0:
        return envelope

    hz = min(strobe_hz, strobe_limit)
    if hz != strobe_hz:
        print(f"    Strobe clamped: {strobe_hz} Hz → {hz} Hz "
              f"(limit {strobe_limit})")

    env = envelope.copy()
    n = len(env)
    _, high_thresh = thresholds

    # Build strobe mask: 1.0 = strobe active, 0.0 = no strobe
    mask = np.zeros(n, dtype=np.float64)
    for sec in sections:
        if strobe_mode == 'all' or (
            strobe_mode == 'high' and sec['energy'] > high_thresh
        ):
            f_start = int(sec['start_time'] * fps)
            f_end   = min(int(sec['end_time'] * fps), n)
            mask[f_start:f_end] = 1.0

    # Square wave: alternates between 1.0 and (1 - depth)
    # Period = fps / hz frames, half-period for on/off
    half_period = max(1, int(fps / (2 * hz)))
    wave = np.ones(n)
    for i in range(n):
        cycle_pos = (i % (2 * half_period))
        if cycle_pos >= half_period:
            wave[i] = 1.0 - strobe_depth

    # Apply: where mask is active, modulate envelope by wave
    env = env * (1.0 - mask) + env * wave * mask

    active_frames = int(mask.sum())
    active_secs = active_frames / fps
    print(f"    Strobe: {hz:.1f} Hz, depth={strobe_depth:.0%}, "
          f"{active_secs:.1f}s active")

    return env


def apply_post_composite(
    in_path,
    out_path,
    width: int,
    height: int,
    fps: int,
    bar_w: int,
    crf: int = 26,
    envelope: np.ndarray = None,
    schedule: list = None,
    snare_times: list = None,
    flash_dur: float = 0.08,
    white_mode: bool = False,
) -> None:
    """Single-pass post-composite: brightness envelope + stills overlay + pillarbox + snare flash.

    Merges what were previously 2-3 sequential encode passes into one ffmpeg call,
    saving significant wall-clock time on longer videos.

    Input indices:
      0          → composite.mp4
      1          → 2×2 grayscale envelope (piped via stdin), only when envelope is not None
      2..N+1     → still PNG paths (one per schedule entry)
    """
    pb_color = "black"
    pillarbox = (
        f"drawbox=x=0:y=0:w={bar_w}:h=ih:color={pb_color}:t=fill,"
        f"drawbox=x=iw-{bar_w}:y=0:w={bar_w}:h=ih:color={pb_color}:t=fill"
    )
    schedule  = schedule  or []
    snare_times = snare_times or []

    # ── build envelope frame data ─────────────────────────────────────────────
    frame_data = None
    env_inputs = []
    if envelope is not None:
        n = len(envelope)
        if white_mode:
            # Remap: silence → small screen boost, loud → big boost
            # screen(base, v) brightens: v=0 → no change, v=255 → white
            envelope = 0.15 + 0.85 * envelope
            print(f"    White mode envelope: {n} frames  "
                  f"mean={envelope.mean():.2f}  "
                  f"min={envelope.min():.2f}  "
                  f"max={envelope.max():.2f}")
        else:
            print(f"    Brightness envelope: {n} frames  "
                  f"mean={envelope.mean():.2f}  "
                  f"min={envelope.min():.2f}  "
                  f"max={envelope.max():.2f}")
        raw = bytearray(n * 4)
        for i, level in enumerate(envelope):
            v = min(255, int(level * 255))
            raw[i * 4:(i + 1) * 4] = bytes([v, v, v, v])
        frame_data = bytes(raw)
        env_inputs = [
            "-f", "rawvideo", "-pixel_format", "gray",
            "-video_size", "2x2", "-framerate", str(fps),
            "-i", "pipe:0",
        ]

    # ── build still inputs ────────────────────────────────────────────────────
    still_inputs = []
    for item in schedule:
        still_inputs += ["-i", str(item['path'])]

    # ── build filter_complex ──────────────────────────────────────────────────
    filter_parts = []

    # index offsets: 0=composite, 1=envelope (optional), 2..=stills
    env_idx   = 1 if envelope is not None else None
    still_off = (2 if envelope is not None else 1)

    # step 1: brightness envelope (or passthrough)
    if envelope is not None:
        blend = "screen" if white_mode else "multiply"
        filter_parts.append(
            f"[0:v]format=gbrp[base];"
            f"[{env_idx}:v]scale={width}:{height}:flags=neighbor,"
            f"format=gbrp[env];"
            f"[base][env]blend=all_mode={blend}[brightened];"
            f"[brightened]format=yuv420p[after_bright]"
        )
        prev = "after_bright"
    else:
        prev = "0:v"

    # step 2: scale each still
    if schedule:
        print(f"    Stills overlay: {len(schedule)} appearances")
        for i, item in enumerate(schedule):
            dur = item['end'] - item['start']
            print(f"      {Path(item['path']).name:40s}  {item['start']:.1f}s – {item['end']:.1f}s  ({dur:.1f}s)")
            sw = item['placement'].get('img_w', width)
            sh = item['placement'].get('img_h', height)
            filter_parts.append(
                f"[{still_off + i}:v]format=rgba,"
                f"scale={sw}:{sh}:force_original_aspect_ratio=decrease,"
                f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=black@0,"
                f"format=rgba[s{i}]"
            )

        # step 3: chain overlay filters
        for i, item in enumerate(schedule):
            nxt    = f"ov{i}"
            enable = f"between(t,{item['start']:.4f},{item['end']:.4f})"
            x_expr, y_expr = _overlay_xy(item['placement'], item, width, height)
            filter_parts.append(
                f"[{prev}][s{i}]overlay=x='{x_expr}':y='{y_expr}':eval=frame:enable='{enable}'[{nxt}]"
            )
            prev = nxt

    # step 4: pillarbox bars
    filter_parts.append(f"[{prev}]{pillarbox}[after_pb]")
    prev = "after_pb"

    # step 5: snare contrast flash
    if snare_times:
        print(f"    Snare contrast: {len(snare_times)} hits  flash={flash_dur*1000:.0f}ms")
        enable_parts = [f"between(t,{t:.4f},{t + flash_dur:.4f})" for t in snare_times]
        enable_expr  = "+".join(enable_parts)
        filter_parts.append(
            f"[{prev}]eq=contrast=2.2:brightness=0.06:enable='gt({enable_expr},0)'[out]"
        )
        prev = "out"
    else:
        filter_parts.append(f"[{prev}]null[out]")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_path),
        *env_inputs,
        *still_inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[out]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-c:a", "copy",
        str(out_path),
    ]
    print(f"    ffmpeg post-composite → {Path(out_path).name}")
    result = subprocess.run(cmd, input=frame_data, capture_output=True)
    if result.returncode != 0:
        print("FFMPEG ERROR:\n", result.stderr.decode()[-2000:])
        raise RuntimeError("post-composite pass failed")


# ── 2D stills placement rules ─────────────────────────────────────────────────

_PAN_DIRECTIONS = ['l2r', 'r2l', 't2b', 'b2t', 'tl2br', 'tr2bl', 'bl2tr', 'br2tl']


def _still_placement(path: str, rng, width: int, height: int) -> dict:
    """Return placement metadata for a still based on its filename.

    Rules:
      kanji_*            → pan: starts off-screen, travels through center, exits far side
      chrysanthemum / image0 → random static position each occurrence
      image1 / image11   → fixed: overlay at x=0,y=0 (as-is)
      title_*            → fixed: overlay at x=0,y=0 (centered in canvas)
    """
    name = Path(path).name.lower()
    if name.startswith('kanji_'):
        sw, sh = width * 2, height * 2   # render at 2× so text is twice as large
        return {'type': 'pan', 'direction': rng.choice(_PAN_DIRECTIONS),
                'img_w': sw, 'img_h': sh}
    elif 'chrysanthemum' in name or name == 'image0_bw.png':
        max_x = width  // 4
        max_y = height // 4
        return {
            'type': 'random',
            'x': rng.randint(-max_x, max_x),
            'y': rng.randint(-max_y, max_y),
        }
    else:
        # image1_bw.png, image11_bw.png, title_*.png → fixed/centered as-is
        return {'type': 'fixed'}


def _overlay_xy(placement: dict, item: dict, width: int, height: int) -> tuple:
    """Return (x_expr, y_expr) strings for ffmpeg overlay filter.

    For pan: image starts fully off one edge, passes through screen center,
    exits off the opposite edge.  `t` is the frame timestamp in seconds.
    """
    W, H = width, height
    ts, te = item['start'], item['end']
    kind   = placement['type']

    if kind == 'fixed':
        return '0', '0'

    if kind == 'random':
        return str(placement['x']), str(placement['y'])

    # pan — linear motion: off-screen → through center → off-screen
    d   = placement['direction']
    SW  = placement.get('img_w', W)   # actual image dimensions (may differ from canvas)
    SH  = placement.get('img_h', H)
    cx  = (W - SW) // 2              # x that centres image horizontally on canvas
    cy  = (H - SH) // 2              # y that centres image vertically on canvas
    dur = f"({te:.4f}-{ts:.4f})"
    prg = f"(t-{ts:.4f})/{dur}"      # 0 at entry, 1 at exit

    # General formula:
    #   off-screen left  → x = -SW      (right edge of image at canvas x=0)
    #   centred          → x = cx       (image centre = canvas centre)
    #   off-screen right → x = W        (left edge of image at canvas right edge)
    #   total x travel   = W + SW
    x_lr  = f"({-SW}+({W}+{SW})*{prg})"
    x_rl  = f"({W}-({W}+{SW})*{prg})"
    y_tb  = f"({-SH}+({H}+{SH})*{prg})"
    y_bt  = f"({H}-({H}+{SH})*{prg})"

    x_map = {
        'l2r':   x_lr, 'r2l':   x_rl,
        't2b':   str(cx), 'b2t': str(cx),
        'tl2br': x_lr, 'tr2bl': x_rl,
        'bl2tr': x_lr, 'br2tl': x_rl,
    }
    y_map = {
        'l2r':   str(cy), 'r2l':  str(cy),
        't2b':   y_tb,    'b2t':  y_bt,
        'tl2br': y_tb,    'tr2bl': y_tb,
        'bl2tr': y_bt,    'br2tl': y_bt,
    }
    return x_map[d], y_map[d]


# ── 2D stills scheduling + overlay ───────────────────────────────────────────

def schedule_stills(
    section_starts: list,
    beat_times,
    still_paths: list,
    max_dur: float = 15.0,
    min_gap: float = 20.0,
    rng=None,
    width: int = 1920,
    height: int = 1080,
) -> list:
    """Schedule 2D still overlays at phrase/section transitions.

    Rules (per user spec):
    - Enter hard on a phrase transition (section start time)
    - Exit on a beat — last beat within max_dur seconds of entry
    - Max on-screen time: max_dur seconds
    - Minimum gap between stills: min_gap seconds
    - Only one still on screen at a time (schedule is non-overlapping by construction)
    """
    if not still_paths:
        return []

    # Separate title cards from image stills
    title_keywords = ("title_interzone", "title_funeral")
    titles = [p for p in still_paths if any(k in Path(p).name.lower() for k in title_keywords)]
    others = [p for p in still_paths if p not in titles]

    # First slot: pick a title card at random (if any); subsequent slots: full random pool
    if rng:
        rng.shuffle(titles)
        rng.shuffle(others)
    first_pool = titles if titles else list(still_paths)
    rest_pool  = list(still_paths)  # full pool, random each time

    schedule = []
    last_end  = -min_gap   # allow first still immediately
    beat_arr  = np.asarray(beat_times)
    slot      = 0

    for t_start in sorted(section_starts):
        if t_start - last_end < min_gap:
            continue
        window = beat_arr[(beat_arr > t_start) & (beat_arr <= t_start + max_dur)]
        if len(window) == 0:
            continue
        t_end = float(window[-1])
        if slot == 0:
            path = first_pool[0]
        else:
            path = rng.choice(rest_pool) if rng else rest_pool[slot % len(rest_pool)]
        schedule.append({
            'path':      str(path),
            'start':     float(t_start),
            'end':       t_end,
            'placement': _still_placement(str(path), rng, width, height),
        })
        last_end = t_end
        slot += 1

    return schedule


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Generate beat-synced video collage")
    ap.add_argument("--phrases",  default=str(DEFAULT_PHRASES))
    ap.add_argument("--catalog",  default=str(DEFAULT_CATALOG))
    ap.add_argument("--audio",    required=True)
    ap.add_argument("--output",   default=str(DEFAULT_OUTPUT))
    ap.add_argument("--review",   default=str(DEFAULT_REVIEW))
    ap.add_argument("--blend",    default="screen",
                    choices=["screen", "overlay", "multiply", "lighten", "darken"])
    ap.add_argument("--opacity",  type=float, default=0.45,
                    help="Overlay opacity [0-1] (default 0.45)")
    ap.add_argument("--seed",     type=int, default=42)
    ap.add_argument("--preview",       action="store_true",
                    help="Render at 854x480 for quick preview")
    ap.add_argument("--favorites-only", action="store_true",
                    help="Use only favorited shots")
    ap.add_argument("--tags",            nargs="+", default=None, metavar="TAG",
                    help="Filter shots to those matching ANY of the specified tags")
    ap.add_argument("--snare",           default=None,
                    help="Path to snare JSON from detect_snare.py (adds white circle flash)")
    ap.add_argument("--stills",          nargs="*", default=None, metavar="PNG",
                    help="2D still PNG assets to overlay (space-separated paths)")
    ap.add_argument("--stills-max-dur",  type=float, default=15.0,
                    help="Max seconds a still stays on screen (default 15)")
    ap.add_argument("--stills-min-gap",  type=float, default=20.0,
                    help="Min seconds between stills (default 20)")
    ap.add_argument("--brightness-release", type=float, default=1.0,
                    help="Audio brightness release time in seconds (default 1.0)")
    ap.add_argument("--brightness-smooth", type=float, default=0.0,
                    help="Low-pass smoothing window in seconds (reduces strobing, e.g. 0.5)")
    ap.add_argument("--no-brightness",   action="store_true",
                    help="Disable audio-reactive brightness modulation")
    ap.add_argument("--white-mode",      action="store_true",
                    help="White brightness: silence=white, loud=blown-out")
    ap.add_argument("--dark-mode",       action="store_true",
                    help="Dark mode: only use dark + neutral assets")
    ap.add_argument("--stills-tags",     default=None,
                    help="Path to stills brightness tags JSON (for light/dark filtering)")
    ap.add_argument("--strobe-hz",       type=float, default=0.0,
                    help="Strobe frequency in Hz (0=off, e.g. 2.5)")
    ap.add_argument("--strobe-limit",    type=float, default=1.5,
                    help="Hard safety cap for strobe Hz (default 1.5)")
    ap.add_argument("--strobe-depth",    type=float, default=0.8,
                    help="Strobe depth 0-1 (0=subtle, 1=full, default 0.8)")
    ap.add_argument("--strobe-sections", default="high",
                    choices=["high", "all", "none"],
                    help="Which sections strobe: high-energy, all, none")
    ap.add_argument("--solo",            nargs="+", default=None, metavar="TIME:PATH",
                    help="Force a solo clip at TIME (seconds). Format: 60:/path/to/clip.mp4")
    ap.add_argument("--crf",             type=int, default=26,
                    help="H.264 CRF quality (0=lossless, 26=default, higher=smaller file)")
    ap.add_argument("--legacy",          action="store_true",
                    help="Use legacy ffmpeg filter graph pipeline instead of PyTorch")
    args = ap.parse_args()

    t_start = time.monotonic()
    timings = {}
    rng = random.Random(args.seed)
    w, h = (854, 480) if args.preview else (W, H)

    # Auto-resolve metadata from track directory if not explicitly provided
    auto_phrases, auto_snare = resolve_track_metadata(args.audio)
    if args.phrases == str(DEFAULT_PHRASES) and auto_phrases:
        print(f"  Auto-resolved phrases: {auto_phrases}")
        args.phrases = str(auto_phrases)
    if args.snare is None and auto_snare:
        print(f"  Auto-resolved snare: {auto_snare}")
        args.snare = str(auto_snare)

    t_phase = time.monotonic()
    print("Loading data...")
    phrases    = json.loads(Path(args.phrases).read_text())
    shots      = load_shots(args.catalog)
    favorites  = load_favorites(args.review)
    shot_tags  = load_tags(args.review) if args.tags else {}

    if args.favorites_only:
        shots = [s for s in shots if Path(s['path']).name in favorites]
        if not shots:
            raise SystemExit("No favorited shots found — run the review UI first.")

    if args.tags:
        required = set(args.tags)
        before = len(shots)
        shots = [s for s in shots
                 if required & shot_tags.get(Path(s['path']).name, set())]
        if not shots:
            raise SystemExit(f"No shots match tags {args.tags} — tag shots first with tag_shots.py")
        print(f"  Tag filter {args.tags}: {before} → {len(shots)} shots")

    # Filter shots by brightness mode
    if args.white_mode or args.dark_mode:
        mode_tag = "light" if args.white_mode else "dark"
        before = len(shots)
        shots = [s for s in shots
                 if s.get('brightness_tag', 'dark') in (mode_tag, 'neutral')]
        print(f"  Brightness filter ({mode_tag}+neutral): {before} → {len(shots)} shots")

    # Filter stills by brightness mode
    if args.stills and args.stills_tags and (args.white_mode or args.dark_mode):
        stills_tags = json.loads(Path(args.stills_tags).read_text())
        mode_tag = "light" if args.white_mode else "dark"
        before = len(args.stills)
        args.stills = [p for p in args.stills
                       if stills_tags.get(Path(p).name, 'neutral') in (mode_tag, 'neutral')]
        print(f"  Stills filter ({mode_tag}+neutral): {before} → {len(args.stills)} stills")

    sections   = phrases['sections']
    beat_times = phrases['beat_times']
    duration   = phrases['duration']

    print(f"  {len(sections)} sections, {len(beat_times)} beats")
    print(f"  {len(shots)} shots{' (favorites only)' if args.favorites_only else ''}, {len(favorites)} favorites")
    print(f"  Output: {'preview 854x480' if args.preview else '1920x1080'}")

    thresholds = compute_thresholds(sections)
    max_layers = max(section_params(s['energy'], thresholds)[1] for s in sections)
    print(f"  Energy thresholds: 1-layer ≤ {thresholds[0]:.3f}, 2-layer ≤ {thresholds[1]:.3f}, 3-layer above")
    print(f"  Max layers needed: {max_layers}")

    # ── parse solo clips ────────────────────────────────────────────────────
    solos = []
    if args.solo:
        for spec in args.solo:
            sep = spec.index(':')
            t = float(spec[:sep])
            path = spec[sep + 1:]
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path],
                capture_output=True, text=True,
            )
            dur = float(probe.stdout.strip())
            solos.append({'time': t, 'path': path, 'duration': dur})
            print(f"  Solo @ {t:.1f}s: {Path(path).name} ({dur:.1f}s)")

    timings['load'] = time.monotonic() - t_phase

    # ── compute shared data (both paths need this) ───────────────────────
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bar_w = int((w - h * PILLARBOX_RATIO) / 2)

    t_phase = time.monotonic()
    envelope = None
    if not args.no_brightness and not args.white_mode:
        print("\nComputing brightness envelope...")
        n_frames = int(np.ceil(duration * FPS)) + 4
        envelope = compute_brightness_envelope(
            args.audio, n_frames, FPS, args.brightness_release,
        )
        if args.brightness_smooth > 0:
            envelope = smooth_envelope(envelope, FPS, args.brightness_smooth)
            print(f"    Smoothed envelope (window={args.brightness_smooth}s): "
                  f"mean={envelope.mean():.2f}  min={envelope.min():.2f}  "
                  f"max={envelope.max():.2f}")
        if args.strobe_hz > 0:
            envelope = apply_strobe(
                envelope, FPS, args.strobe_hz,
                args.strobe_depth, args.strobe_limit,
                sections, args.strobe_sections, thresholds,
            )

    still_schedule = []
    if args.stills:
        section_starts = [s['start_time'] for s in sections]
        still_schedule = schedule_stills(
            section_starts, beat_times, args.stills,
            max_dur=args.stills_max_dur,
            min_gap=args.stills_min_gap,
            rng=rng,
            width=w, height=h,
        )
        print(f"\n  Still schedule: {len(still_schedule)} appearances "
              f"(max_dur={args.stills_max_dur}s, min_gap={args.stills_min_gap}s)")

    snare_times = []
    # Snare flash disabled globally for now
    # if args.snare:
    #     snare_data  = json.loads(Path(args.snare).read_text())
    #     snare_times = snare_data["snare_times"]

    timings['precompute'] = time.monotonic() - t_phase

    # ── build clip lists for all layers ──────────────────────────────────
    t_phase = time.monotonic()
    all_layer_clips = []
    for li in range(max_layers):
        print(f"\nLayer {li}:")
        clips = build_layer(li, sections, beat_times, shots,
                            favorites, duration, thresholds, rng)
        if solos:
            clips = inject_solos(clips, solos, li)
        n_cuts = len(clips)
        total  = sum(c['duration'] for c in clips)
        print(f"  {n_cuts} clips, {total:.1f}s")
        all_layer_clips.append(clips)

    timings['clip_build'] = time.monotonic() - t_phase

    t_phase = time.monotonic()
    if args.legacy:
        # ── LEGACY: ffmpeg subprocess pipeline ───────────────────────────
        print("\n[legacy mode] Using ffmpeg filter graph pipeline")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            layer_paths = []
            for li, clips in enumerate(all_layer_clips):
                layer_mp4 = tmpdir / f"layer{li}.mp4"
                render_layer(clips, layer_mp4, w, h, FPS, tmpdir, li)
                layer_paths.append(layer_mp4)

            composite_mp4 = tmpdir / "composite.mp4"
            composite_layers(layer_paths, args.audio, composite_mp4,
                             args.blend, args.opacity, w, h, apply_pillarbox=False, crf=28)

            print("\nApplying post-composite (brightness + stills + pillarbox + snare)...")
            apply_post_composite(
                composite_mp4, Path(args.output),
                width=w, height=h, fps=FPS, bar_w=bar_w, crf=args.crf,
                envelope=envelope,
                schedule=still_schedule,
                snare_times=snare_times,
                white_mode=args.white_mode,
            )
    else:
        # ── PYTORCH: single-pass GPU render (no intermediate files) ──────
        device = get_device()
        print(f"\n[PyTorch] Single-pass render on {device}")

        # Open ClipDecoders — one per layer, reads source clips directly
        print("  Opening clip decoders...")
        decoders = []
        for li, clips in enumerate(all_layer_clips):
            print(f"    Layer {li}: {len(clips)} clips")
            decoders.append(ClipDecoder(clips, w, h, FPS))

        # Pre-decode and cache still assets (small — a few MB total)
        still_cache = {}
        if still_schedule:
            print(f"  Decoding {len(still_schedule)} still assets...")
            for item in still_schedule:
                sw = item['placement'].get('img_w', w)
                sh = item['placement'].get('img_h', h)
                cache_key = f"{item['path']}_{sw}x{sh}"
                if cache_key not in still_cache:
                    still_cache[cache_key] = decode_still(item['path'], sw, sh)
                item['_cache_key'] = cache_key

        # Compute total frames
        total_frames = int(np.ceil(duration * FPS))
        print(f"  Compositing {total_frames} frames...")

        # Open encoder
        encoder = FrameEncoder(
            str(args.output), w, h, FPS,
            audio_path=args.audio, crf=args.crf,
        )

        try:
            for fi in range(total_frames):
                if fi % (FPS * 10) == 0:
                    pct = fi / total_frames * 100
                    print(f"    frame {fi}/{total_frames} ({pct:.0f}%)")

                # Read one frame from each layer's clip decoder
                layer_frames = [dec.read_frame() for dec in decoders]

                frame = composite_frame(
                    layer_frames=layer_frames,
                    frame_idx=fi,
                    blend_mode=args.blend,
                    opacity=args.opacity,
                    envelope=envelope,
                    still_schedule=still_schedule,
                    still_cache=still_cache,
                    snare_times=snare_times,
                    bar_w=bar_w,
                    fps=FPS,
                    width=w,
                    height=h,
                    white_mode=args.white_mode,
                    device=device,
                )
                encoder.write_frame(frame)
        finally:
            encoder.close()
            for dec in decoders:
                dec.close()

        print(f"  Encode complete → {args.output}")

    timings['render'] = time.monotonic() - t_phase
    t_total = time.monotonic() - t_start

    # ── performance summary ──────────────────────────────────────────────
    import resource
    rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
    self_rusage = resource.getrusage(resource.RUSAGE_SELF)
    peak_mb = (self_rusage.ru_maxrss + rusage.ru_maxrss) / (1024 * 1024)
    if sys.platform == 'linux':
        # Linux ru_maxrss is in KB
        peak_mb = (self_rusage.ru_maxrss + rusage.ru_maxrss) / 1024
    output_size = Path(args.output).stat().st_size / (1024 * 1024)
    total_frames = int(np.ceil(duration * FPS))

    print(f"\n{'=' * 60}")
    print(f"RENDER SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Output:      {args.output}")
    print(f"  Resolution:  {w}x{h}  {'(preview)' if args.preview else '(full)'}")
    print(f"  Frames:      {total_frames}  ({duration:.1f}s @ {FPS} fps)")
    print(f"  Pipeline:    {'legacy ffmpeg' if args.legacy else f'PyTorch ({get_device()})'}")
    print(f"  File size:   {output_size:.1f} MB")
    print(f"")
    print(f"  Timings:")
    print(f"    Load data:     {timings['load']:6.1f}s")
    print(f"    Precompute:    {timings['precompute']:6.1f}s")
    print(f"    Clip build:    {timings['clip_build']:6.1f}s")
    print(f"    Render:        {timings['render']:6.1f}s")
    print(f"    Total:         {t_total:6.1f}s")
    print(f"")
    render_fps = total_frames / timings['render'] if timings['render'] > 0 else 0
    print(f"  Throughput:  {render_fps:.1f} fps  "
          f"({timings['render'] / duration:.2f}x realtime)")
    print(f"  Peak memory: {peak_mb:.0f} MB")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
