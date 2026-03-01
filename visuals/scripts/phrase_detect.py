#!/usr/bin/env python3
"""Detect musical phrases/transitions in an audio track using spectral analysis.

Combines four signals into an "impact" score at each beat:
  - Structural novelty: chroma + MFCC recurrence matrix checkerboard
  - Energy contrast: RMS delta before vs after each beat
  - Spectral flux: brightness (centroid) delta before vs after each beat
  - Rhythmic flux: change in sub-beat onset pattern (via HPSS percussive component)

Peaks in the impact curve = likely section boundaries.
"""

import argparse, json
import numpy as np
import librosa

try:
    import essentia.standard as es
    HAS_ESSENTIA = True
except ImportError:
    HAS_ESSENTIA = False

def snap_to_bar(beat_idx, total_beats, bar_len=4):
    """Snap a beat index to the nearest bar boundary."""
    bar = round(beat_idx / bar_len)
    snapped = bar * bar_len
    return max(0, min(snapped, total_beats - 1))


def quantize_sections(peaks, total_beats, bar_len=4, phrase_bars=4):
    """Snap peaks to a phrase grid (default: every 4 bars).

    In electronic music, sections almost always start on 4-bar or 8-bar
    boundaries. This snaps each peak to the nearest grid line, so every
    section is a multiple of phrase_bars bars long.
    """
    grid_beats = bar_len * phrase_bars  # e.g. 16 beats for 4-bar phrases
    max_grid = total_beats // grid_beats

    snapped = set()
    for p in peaks:
        grid_pos = round(p / grid_beats)
        grid_pos = max(1, min(grid_pos, max_grid - 1))
        snapped.add(grid_pos * grid_beats)

    return sorted(snapped)


def analyze(audio_path: str, bpm: float = None, n_sections: int = None,
            bar_snap: bool = False):
    print(f"Loading: {audio_path}")
    y, sr = librosa.load(audio_path, sr=44100, mono=True)  # 44100 for Essentia
    duration = len(y) / sr
    print(f"Duration: {duration:.1f}s  SR: {sr}")

    # beat tracking: Essentia if available, else librosa
    if HAS_ESSENTIA:
        print("  Beat tracking (Essentia RhythmExtractor2013)...")
        rhythm = es.RhythmExtractor2013(method="multifeature")
        if bpm:
            bpm_tol = bpm * 0.02
            tempo_est, beat_times_es, _, _, _ = rhythm(y)
            if abs(tempo_est - bpm) > bpm_tol * 2:
                print(f"  Essentia tempo {tempo_est:.1f} differs from --bpm {bpm}, using librosa")
                beat_times_arr = librosa.beat.beat_track(y=y, sr=sr, bpm=bpm, units='time')[1]
                beat_times = np.array(beat_times_arr)
                tempo = bpm
            else:
                beat_times = np.array(beat_times_es)
                tempo = float(tempo_est)
        else:
            tempo_est, beat_times_es, _, _, _ = rhythm(y)
            beat_times = np.array(beat_times_es)
            tempo = float(tempo_est)
    else:
        print("  Beat tracking (librosa)...")
        if bpm:
            tempo = bpm
            _, beat_frames_lib = librosa.beat.beat_track(y=y, sr=sr, bpm=bpm)
        else:
            tempo_est, beat_frames_lib = librosa.beat.beat_track(y=y, sr=sr)
            tempo = float(tempo_est.item() if hasattr(tempo_est, 'item') else tempo_est)
        beat_times = librosa.frames_to_time(beat_frames_lib, sr=sr)

    beat_frames = librosa.time_to_frames(beat_times, sr=sr)
    print(f"  Tempo: {tempo:.1f} BPM, {len(beat_times)} beats detected")

    # features: chroma (harmony) + MFCCs (timbre)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)

    # beat-synchronize features
    chroma_sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
    mfcc_sync = librosa.util.sync(mfcc, beat_frames, aggregate=np.median)

    # stack into combined feature matrix
    features = np.vstack([
        librosa.util.normalize(chroma_sync, norm=2, axis=0),
        librosa.util.normalize(mfcc_sync, norm=2, axis=0),
    ])

    # self-similarity via recurrence matrix
    R = librosa.segment.recurrence_matrix(
        features, width=4, mode='affinity', sym=True
    )

    # novelty curve via checkerboard kernel on the recurrence matrix
    # (librosa 0.11 removed segment.novelty, so we compute it manually)
    kern_size = 16
    half = kern_size // 2
    kernel = np.ones((kern_size, kern_size))
    kernel[:half, :half] = -1
    kernel[half:, half:] = -1  # checkerboard: +/- quadrants
    n = R.shape[0]
    novelty = np.zeros(n)
    for i in range(half, n - half):
        patch = R[i - half:i + half, i - half:i + half]
        novelty[i] = np.sum(patch * kernel)

    # RMS energy per beat
    rms = librosa.feature.rms(y=y)[0]
    rms_sync = librosa.util.sync(rms.reshape(1, -1), beat_frames, aggregate=np.mean)[0]
    rms_norm = rms_sync / (rms_sync.max() + 1e-8)

    # spectral centroid per beat (brightness)
    cent = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    cent_sync = librosa.util.sync(cent.reshape(1, -1), beat_frames, aggregate=np.mean)[0]

    # --- rhythmic flux via HPSS + sub-beat fingerprints ---
    # Separate percussive component, then capture onset strength at 4 sub-beat
    # positions per beat (16th note resolution). Cosine distance between
    # averaged patterns before/after each beat = rhythmic flux.
    print("  Computing rhythmic flux (HPSS + sub-beat fingerprints)...")
    _, y_perc = librosa.effects.hpss(y)
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr)

    n_sub = 4  # sub-beat positions (16th notes)
    fingerprints = np.zeros((len(beat_frames), n_sub))
    for i, bf in enumerate(beat_frames):
        next_bf = int(beat_frames[i + 1]) if i + 1 < len(beat_frames) else len(onset_env)
        beat_len = max(next_bf - int(bf), 1)
        for j in range(n_sub):
            pos = int(bf) + int(j * beat_len / n_sub)
            if pos < len(onset_env):
                fingerprints[i, j] = onset_env[pos]

    # L2-normalize each fingerprint so cosine distance = 1 - dot
    fp_norms = np.linalg.norm(fingerprints, axis=1, keepdims=True) + 1e-8
    fingerprints = fingerprints / fp_norms

    # ensure novelty and beat_times align
    min_len = min(len(novelty), len(beat_times))
    novelty = novelty[:min_len]
    fingerprints = fingerprints[:min_len]

    # --- combined impact score ---
    # Compare 4-beat windows before/after each beat for all signals.
    window = 4
    energy_contrast = np.zeros(min_len)
    spec_flux = np.zeros(min_len)
    rhythmic_flux = np.zeros(min_len)
    for i in range(window, min_len - window):
        energy_contrast[i] = abs(
            np.mean(rms_sync[i:i+window]) - np.mean(rms_sync[i-window:i])
        )
        spec_flux[i] = abs(
            np.mean(cent_sync[i:i+window]) - np.mean(cent_sync[i-window:i])
        )
        # cosine distance between avg rhythmic pattern before vs after
        before_fp = fingerprints[i-window:i].mean(axis=0)
        after_fp  = fingerprints[i:i+window].mean(axis=0)
        rhythmic_flux[i] = 1.0 - np.dot(before_fp, after_fp)

    # normalize each signal to [0, 1]
    novelty_norm = novelty / (novelty.max() + 1e-8)
    energy_contrast  /= (energy_contrast.max()  + 1e-8)
    spec_flux        /= (spec_flux.max()        + 1e-8)
    rhythmic_flux    /= (rhythmic_flux.max()    + 1e-8)

    # multiply: a beat scores high only when multiple signals agree
    impact = (novelty_norm
              * (1 + energy_contrast)
              * (1 + spec_flux)
              * (1 + rhythmic_flux))
    impact /= (impact.max() + 1e-8)
    print("  Impact score computed (novelty × energy × spectral × rhythmic)")

    # find section boundaries
    if n_sections:
        n_peaks = max(1, n_sections - 1)
    else:
        threshold = np.mean(impact) + 1.5 * np.std(impact)
        n_peaks = max(1, int(np.sum(impact > threshold)))

    from scipy.signal import find_peaks as scipy_peaks
    peaks, props = scipy_peaks(impact, distance=16, prominence=0.05)

    # sort by impact prominence, take top N
    if len(peaks) > n_peaks:
        prom_order = np.argsort(props['prominences'])[::-1]
        peaks = np.sort(peaks[prom_order[:n_peaks]])

    # build sections
    boundaries = [0] + list(peaks) + [min_len - 1]
    sections = []
    for i in range(len(boundaries) - 1):
        start_beat = boundaries[i]
        end_beat = boundaries[i + 1]
        start_time = beat_times[start_beat] if start_beat < len(beat_times) else duration
        end_time = beat_times[end_beat] if end_beat < len(beat_times) else duration

        # characterize section
        section_rms = float(np.mean(rms_norm[start_beat:end_beat+1])) if end_beat > start_beat else 0
        section_brightness = float(np.mean(cent_sync[start_beat:end_beat+1])) if end_beat > start_beat else 0
        n_beats = end_beat - start_beat
        n_bars = n_beats / 4

        sections.append({
            'index': i,
            'start_time': round(float(start_time), 2),
            'end_time': round(float(end_time), 2),
            'duration': round(float(end_time - start_time), 2),
            'start_beat': int(start_beat),
            'end_beat': int(end_beat),
            'beats': int(n_beats),
            'bars': round(float(n_bars), 1),
            'energy': round(section_rms, 3),
            'brightness': round(float(section_brightness), 1),
        })

    return {
        'file': audio_path,
        'duration': round(duration, 2),
        'tempo': round(tempo, 1),
        'total_beats': len(beat_times),
        'sections': sections,
        'beat_times': [round(float(t), 3) for t in beat_times],
        'novelty': [round(float(v), 4) for v in novelty_norm],
        'impact': [round(float(v), 4) for v in impact],
        'rhythmic_flux': [round(float(v), 4) for v in rhythmic_flux],
        'energy_per_beat': [round(float(e), 4) for e in rms_norm],
    }


def format_time(s):
    m, s = divmod(s, 60)
    return f"{int(m)}:{s:05.2f}"


def print_report(result):
    print(f"\n{'='*60}")
    print(f"PHRASE ANALYSIS: {result['file']}")
    print(f"Duration: {format_time(result['duration'])}  "
          f"Tempo: {result['tempo']} BPM  "
          f"Beats: {result['total_beats']}")
    print(f"{'='*60}\n")

    print(f"{'Section':<10} {'Time':<18} {'Dur':>6} {'Beats':>6} {'Bars':>6} {'Energy':>8} {'Bright':>8}")
    print('-' * 62)
    for s in result['sections']:
        label = f"  [{s['index']+1}]"
        time_range = f"{format_time(s['start_time'])} - {format_time(s['end_time'])}"
        energy_bar = '#' * int(s['energy'] * 10)
        print(f"{label:<10} {time_range:<18} {s['duration']:>5.1f}s {s['beats']:>5}  {s['bars']:>5.1f} "
              f"{energy_bar:<8} {s['brightness']:>7.0f}")

    print(f"\nTransition points:")
    for i, s in enumerate(result['sections'][1:], 1):
        print(f"  {format_time(s['start_time'])}  (beat {s['start_beat']}, bar {s['start_beat']//4+1})")


def main():
    ap = argparse.ArgumentParser(description="Detect musical phrases/sections")
    ap.add_argument("audio", help="Path to audio file")
    ap.add_argument("--bpm", type=float, help="Override BPM (skip beat detection)")
    ap.add_argument("-n", "--sections", type=int, help="Force N sections (default: auto)")
    ap.add_argument("-o", "--output", help="Save JSON results to file")
    ap.add_argument("--bar-snap", action="store_true",
                    help="Snap section boundaries to bar lines (2/4/8 bar phrases)")
    args = ap.parse_args()

    result = analyze(args.audio, bpm=args.bpm, n_sections=args.sections,
                     bar_snap=args.bar_snap)
    print_report(result)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
