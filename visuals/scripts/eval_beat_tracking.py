#!/usr/bin/env python3
"""Evaluate librosa vs essentia beat tracking quality.

Runs both beat trackers on a set of tracks and compares:
  - Beat count and tempo estimation
  - Beat grid alignment (timing offsets)
  - Downstream section boundaries (via full phrase analysis)

Usage:
  python eval_beat_tracking.py --library /path/to/audio/library
  python eval_beat_tracking.py --library /path/to/audio/library --tracks BlueMonday_130_Em,BelaLugosisDead_120_D
"""

import argparse, json, os, time, glob
import numpy as np
import librosa

# Try importing essentia — it may not be available everywhere
try:
    import essentia.standard as es
    HAS_ESSENTIA = True
except ImportError:
    HAS_ESSENTIA = False
    print("WARNING: essentia not available, will only run librosa backend")


# Default evaluation set: 8 tracks across 120/130/148 BPM, diverse genres
DEFAULT_TRACKS = [
    "BlueMonday_130_Em",           # synth-pop, very clean grid
    "BelaLugosisDead_120_D",       # goth rock, sparse drums
    "AtariTeenageRiotSpeed_148_Em", # digital hardcore, chaotic
    "JoyDivisionShesLost_120_Dm",  # post-punk, live drums
    "Front242Headhunter_130_F",    # EBM, machine drums
    "NineInchNailsHead_120_E",     # industrial, distorted
    "TheCureAForest_120_Am",       # new wave, live drums
    "LambriniGirlsFeatPeaches_148_F#", # punk, fast & loose
]


def find_mix_file(library_path, track_name):
    """Find the 4_Mix wav file for a track."""
    pattern = os.path.join(library_path, track_name, "4_Mix_*.wav")
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def beat_track_essentia(y, sr, bpm_hint=None):
    """Beat tracking via Essentia RhythmExtractor2013."""
    rhythm = es.RhythmExtractor2013(method="multifeature")
    tempo_est, beat_times, _, _, _ = rhythm(y)
    return float(tempo_est), np.array(beat_times)


def beat_track_librosa(y, sr, bpm_hint=None):
    """Beat tracking via librosa."""
    if bpm_hint:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, bpm=bpm_hint)
    else:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    # tempo may be an array in some librosa versions
    if hasattr(tempo, '__len__'):
        tempo = float(tempo[0]) if len(tempo) > 0 else 0.0
    return float(tempo), np.array(beat_times)


def compute_beat_alignment(beats_a, beats_b, tolerance_ms=50):
    """Compare two beat grids. For each beat in A, find nearest beat in B.

    Returns:
        matched: number of beats in A that have a match in B within tolerance
        mean_offset_ms: mean timing offset for matched beats
        std_offset_ms: std of timing offsets
        extra_a: beats in A with no match in B
        extra_b: beats in B with no match in A
    """
    tolerance_s = tolerance_ms / 1000.0

    offsets = []
    matched_b = set()

    for t_a in beats_a:
        diffs = np.abs(beats_b - t_a)
        nearest_idx = np.argmin(diffs)
        if diffs[nearest_idx] <= tolerance_s:
            offsets.append((beats_b[nearest_idx] - t_a) * 1000)  # ms
            matched_b.add(nearest_idx)

    matched = len(offsets)
    extra_a = len(beats_a) - matched
    extra_b = len(beats_b) - len(matched_b)

    return {
        'matched': matched,
        'total_a': len(beats_a),
        'total_b': len(beats_b),
        'match_rate': matched / max(len(beats_a), 1),
        'mean_offset_ms': float(np.mean(offsets)) if offsets else 0,
        'std_offset_ms': float(np.std(offsets)) if offsets else 0,
        'max_offset_ms': float(np.max(np.abs(offsets))) if offsets else 0,
        'extra_a': extra_a,
        'extra_b': extra_b,
    }


def compute_sections(beat_times, y, sr, n_sections=None):
    """Simplified section detection (same logic as phrase_detect.py).

    Returns list of section boundary beat indices.
    """
    beat_frames = librosa.time_to_frames(beat_times, sr=sr)
    if len(beat_frames) < 10:
        return []

    # features
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    chroma_sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
    mfcc_sync = librosa.util.sync(mfcc, beat_frames, aggregate=np.median)

    features = np.vstack([
        librosa.util.normalize(chroma_sync, norm=2, axis=0),
        librosa.util.normalize(mfcc_sync, norm=2, axis=0),
    ])

    R = librosa.segment.recurrence_matrix(features, width=4, mode='affinity', sym=True)

    # novelty via checkerboard kernel
    kern_size = 16
    half = kern_size // 2
    kernel = np.ones((kern_size, kern_size))
    kernel[:half, :half] = -1
    kernel[half:, half:] = -1
    n = R.shape[0]
    novelty = np.zeros(n)
    for i in range(half, n - half):
        patch = R[i - half:i + half, i - half:i + half]
        novelty[i] = np.sum(patch * kernel)

    # RMS
    rms = librosa.feature.rms(y=y)[0]
    rms_sync = librosa.util.sync(rms.reshape(1, -1), beat_frames, aggregate=np.mean)[0]

    # energy contrast
    min_len = min(len(novelty), len(beat_times))
    novelty = novelty[:min_len]
    rms_sync = rms_sync[:min_len]

    window = 4
    energy_contrast = np.zeros(min_len)
    for i in range(window, min_len - window):
        energy_contrast[i] = abs(
            np.mean(rms_sync[i:i+window]) - np.mean(rms_sync[i-window:i])
        )

    novelty_norm = novelty / (novelty.max() + 1e-8)
    energy_contrast /= (energy_contrast.max() + 1e-8)
    impact = novelty_norm * (1 + energy_contrast)
    impact /= (impact.max() + 1e-8)

    from scipy.signal import find_peaks as scipy_peaks
    peaks, _ = scipy_peaks(impact, distance=16, prominence=0.05)

    if n_sections and len(peaks) > n_sections - 1:
        # take top by impact value
        top_idx = np.argsort(impact[peaks])[::-1][:n_sections - 1]
        peaks = np.sort(peaks[top_idx])

    return list(peaks)


def compare_sections(sections_a, sections_b, beat_times_a, beat_times_b, tolerance_beats=4):
    """Compare two sets of section boundaries.

    Converts boundaries to time, then checks how many align within tolerance.
    """
    if not sections_a or not sections_b:
        return {'boundaries_a': len(sections_a), 'boundaries_b': len(sections_b),
                'matched': 0, 'note': 'one or both empty'}

    # convert to times
    times_a = [float(beat_times_a[min(b, len(beat_times_a)-1)]) for b in sections_a]
    times_b = [float(beat_times_b[min(b, len(beat_times_b)-1)]) for b in sections_b]

    # tolerance in seconds: tolerance_beats * avg beat duration
    avg_beat_dur = np.median(np.diff(beat_times_a)) if len(beat_times_a) > 1 else 0.5
    tol_s = tolerance_beats * avg_beat_dur

    matched = 0
    used_b = set()
    for t_a in times_a:
        for j, t_b in enumerate(times_b):
            if j not in used_b and abs(t_a - t_b) <= tol_s:
                matched += 1
                used_b.add(j)
                break

    return {
        'boundaries_a': len(times_a),
        'boundaries_b': len(times_b),
        'matched': matched,
        'match_rate_a': matched / max(len(times_a), 1),
        'tolerance_beats': tolerance_beats,
        'tolerance_seconds': round(tol_s, 2),
    }


def evaluate_track(audio_path, track_name, bpm_hint=None):
    """Run full evaluation on a single track.

    Runs three beat trackers:
      - essentia (no BPM hint — it doesn't accept one)
      - librosa_free (no BPM hint — apples-to-apples with essentia)
      - librosa_hinted (with BPM hint — shows value of known BPM)
    """
    print(f"\n{'='*60}")
    print(f"  {track_name}")
    print(f"{'='*60}")

    y, sr = librosa.load(audio_path, sr=44100, mono=True)
    duration = len(y) / sr
    print(f"  Duration: {duration:.1f}s")

    results = {'track': track_name, 'duration': round(duration, 1), 'bpm_hint': bpm_hint}

    # --- Librosa FREE (no hint) ---
    print("  [librosa-free] Beat tracking (no BPM hint)...")
    t0 = time.time()
    lib_free_tempo, lib_free_beats = beat_track_librosa(y, sr, bpm_hint=None)
    lib_free_time = time.time() - t0
    print(f"  [librosa-free] {lib_free_tempo:.1f} BPM, {len(lib_free_beats)} beats ({lib_free_time:.1f}s)")
    results['librosa_free'] = {
        'tempo': round(lib_free_tempo, 1),
        'n_beats': len(lib_free_beats),
        'time_s': round(lib_free_time, 1),
    }

    # --- Librosa HINTED ---
    if bpm_hint:
        print(f"  [librosa-hinted] Beat tracking (BPM hint={bpm_hint})...")
        t0 = time.time()
        lib_hint_tempo, lib_hint_beats = beat_track_librosa(y, sr, bpm_hint=bpm_hint)
        lib_hint_time = time.time() - t0
        print(f"  [librosa-hinted] {lib_hint_tempo:.1f} BPM, {len(lib_hint_beats)} beats ({lib_hint_time:.1f}s)")
        results['librosa_hinted'] = {
            'tempo': round(lib_hint_tempo, 1),
            'n_beats': len(lib_hint_beats),
            'time_s': round(lib_hint_time, 1),
        }

    # --- Essentia ---
    if HAS_ESSENTIA:
        print("  [essentia] Beat tracking...")
        t0 = time.time()
        ess_tempo, ess_beats = beat_track_essentia(y, sr, bpm_hint)
        ess_time = time.time() - t0
        print(f"  [essentia] {ess_tempo:.1f} BPM, {len(ess_beats)} beats ({ess_time:.1f}s)")
        results['essentia'] = {
            'tempo': round(ess_tempo, 1),
            'n_beats': len(ess_beats),
            'time_s': round(ess_time, 1),
        }

        # --- Beat grid alignment: essentia vs librosa-free (fair comparison) ---
        print("  Comparing: essentia vs librosa-free...")
        align_fair = compute_beat_alignment(ess_beats, lib_free_beats)
        results['alignment_ess_vs_lib_free'] = align_fair
        print(f"    Match: {align_fair['match_rate']:.1%} "
              f"({align_fair['matched']}/{align_fair['total_a']})  "
              f"offset: {align_fair['mean_offset_ms']:+.1f}ms "
              f"(std: {align_fair['std_offset_ms']:.1f}ms)")

        # --- Beat grid alignment: essentia vs librosa-hinted ---
        if bpm_hint:
            print("  Comparing: essentia vs librosa-hinted...")
            align_hint = compute_beat_alignment(ess_beats, lib_hint_beats)
            results['alignment_ess_vs_lib_hinted'] = align_hint
            print(f"    Match: {align_hint['match_rate']:.1%} "
                  f"({align_hint['matched']}/{align_hint['total_a']})  "
                  f"offset: {align_hint['mean_offset_ms']:+.1f}ms "
                  f"(std: {align_hint['std_offset_ms']:.1f}ms)")

        # --- Section boundary comparison (essentia vs librosa-free) ---
        print("  Computing sections (essentia beats)...")
        ess_sections = compute_sections(ess_beats, y, sr)
        print(f"  [essentia] {len(ess_sections)} section boundaries")

        print("  Computing sections (librosa-free beats)...")
        lib_free_sections = compute_sections(lib_free_beats, y, sr)
        print(f"  [librosa-free] {len(lib_free_sections)} section boundaries")

        section_cmp = compare_sections(ess_sections, lib_free_sections, ess_beats, lib_free_beats)
        results['section_comparison'] = section_cmp
        print(f"  Section boundary match: {section_cmp['matched']}/{section_cmp['boundaries_a']} "
              f"(within {section_cmp.get('tolerance_beats', '?')} beats)")
    else:
        print("  [essentia] Skipped (not installed)")
        lib_free_sections = compute_sections(lib_free_beats, y, sr)
        results['librosa_free_sections'] = len(lib_free_sections)

    return results


def print_summary(all_results):
    """Print a summary table of all track comparisons."""
    print(f"\n\n{'='*90}")
    print("  EVALUATION SUMMARY")
    print(f"{'='*90}\n")

    if not HAS_ESSENTIA:
        print("Essentia not available — only librosa results collected.")
        for r in all_results:
            lib = r.get('librosa_free', {})
            print(f"  {r['track']:<40} {lib.get('tempo', '?'):>6.1f} BPM  "
                  f"{lib.get('n_beats', '?'):>4} beats")
        return

    # --- Table 1: Tempo estimation ---
    print("  TEMPO ESTIMATION")
    print(f"  {'Track':<33} {'Known':>6} {'Essentia':>9} {'Lib-free':>9} {'Lib-hint':>9}")
    print('  ' + '-' * 68)
    for r in all_results:
        ess = r.get('essentia', {})
        lib_f = r.get('librosa_free', {})
        lib_h = r.get('librosa_hinted', {})
        hint = r.get('bpm_hint')
        hint_str = f"{hint:.0f}" if hint else "?"
        print(f"  {r['track']:<33} {hint_str:>6} {ess.get('tempo', 0):>8.1f} "
              f"{lib_f.get('tempo', 0):>8.1f} {lib_h.get('tempo', 0):>8.1f}")

    # --- Table 2: Fair comparison (essentia vs librosa-free) ---
    print(f"\n  BEAT ALIGNMENT: essentia vs librosa (no hint) — fair comparison")
    print(f"  {'Track':<33} {'Ess#':>5} {'Lib#':>5} {'Match%':>7} {'Offset':>8} {'Std':>6}")
    print('  ' + '-' * 66)

    fair_match_rates = []
    fair_offsets = []
    for r in all_results:
        ess = r.get('essentia', {})
        lib_f = r.get('librosa_free', {})
        align = r.get('alignment_ess_vs_lib_free', {})
        mr = align.get('match_rate', 0)
        fair_match_rates.append(mr)
        fair_offsets.append(abs(align.get('mean_offset_ms', 0)))
        print(f"  {r['track']:<33} {ess.get('n_beats', 0):>5} {lib_f.get('n_beats', 0):>5} "
              f"{mr:>6.1%} {align.get('mean_offset_ms', 0):>+7.1f} "
              f"{align.get('std_offset_ms', 0):>5.1f}")

    print(f"\n  Average match rate: {np.mean(fair_match_rates):.1%}  "
          f"Mean offset: {np.mean(fair_offsets):.1f}ms")

    # --- Table 3: Hinted comparison (essentia vs librosa-hinted) ---
    hint_match_rates = []
    hint_offsets = []
    has_hinted = any(r.get('alignment_ess_vs_lib_hinted') for r in all_results)
    if has_hinted:
        print(f"\n  BEAT ALIGNMENT: essentia vs librosa (with BPM hint)")
        print(f"  {'Track':<33} {'Ess#':>5} {'Lib#':>5} {'Match%':>7} {'Offset':>8} {'Std':>6}")
        print('  ' + '-' * 66)
        for r in all_results:
            align = r.get('alignment_ess_vs_lib_hinted', {})
            if not align:
                continue
            ess = r.get('essentia', {})
            lib_h = r.get('librosa_hinted', {})
            mr = align.get('match_rate', 0)
            hint_match_rates.append(mr)
            hint_offsets.append(abs(align.get('mean_offset_ms', 0)))
            print(f"  {r['track']:<33} {ess.get('n_beats', 0):>5} {lib_h.get('n_beats', 0):>5} "
                  f"{mr:>6.1%} {align.get('mean_offset_ms', 0):>+7.1f} "
                  f"{align.get('std_offset_ms', 0):>5.1f}")

        print(f"\n  Average match rate: {np.mean(hint_match_rates):.1%}  "
              f"Mean offset: {np.mean(hint_offsets):.1f}ms")

    # --- Table 4: Section boundaries ---
    print(f"\n  SECTION BOUNDARIES: essentia vs librosa-free")
    print(f"  {'Track':<33} {'Ess':>5} {'Lib':>5} {'Match':>8}")
    print('  ' + '-' * 53)
    section_matches = []
    for r in all_results:
        sec = r.get('section_comparison', {})
        if sec.get('boundaries_a', 0) > 0:
            section_matches.append(sec.get('match_rate_a', 0))
        print(f"  {r['track']:<33} {sec.get('boundaries_a', '?'):>5} {sec.get('boundaries_b', '?'):>5} "
              f"{sec.get('matched', '?'):>5}/{sec.get('boundaries_a', '?')}")

    if section_matches:
        print(f"\n  Average section boundary agreement: {np.mean(section_matches):.1%}")

    # --- Verdict ---
    print(f"\n{'='*90}")
    avg_fair = np.mean(fair_match_rates)
    avg_hint = np.mean(hint_match_rates) if hint_match_rates else 0
    avg_offset_fair = np.mean(fair_offsets)

    print(f"  Fair comparison (no hints):   {avg_fair:.1%} match, {avg_offset_fair:.1f}ms offset")
    if hint_match_rates:
        print(f"  With BPM hints:              {avg_hint:.1%} match, {np.mean(hint_offsets):.1f}ms offset")

    if avg_fair >= 0.90 and avg_offset_fair < 15:
        verdict = "Librosa is a strong match — consider dropping essentia"
    elif avg_fair >= 0.80 and avg_offset_fair < 25:
        verdict = "Librosa is acceptable for CI — use essentia locally for best quality"
    else:
        verdict = "Significant differences — essentia preferred for quality"
    print(f"\n  VERDICT: {verdict}")
    print(f"{'='*90}")


def main():
    ap = argparse.ArgumentParser(description="Evaluate librosa vs essentia beat tracking")
    ap.add_argument("--library", required=True, help="Path to audio library directory")
    ap.add_argument("--tracks", help="Comma-separated track names (default: built-in eval set)")
    ap.add_argument("-o", "--output", help="Save JSON results to file")
    args = ap.parse_args()

    if args.tracks:
        track_names = [t.strip() for t in args.tracks.split(",")]
    else:
        track_names = DEFAULT_TRACKS

    # verify tracks exist
    valid_tracks = []
    for name in track_names:
        audio = find_mix_file(args.library, name)
        if audio:
            valid_tracks.append((name, audio))
        else:
            print(f"  SKIP: {name} — no mix file found")

    if not valid_tracks:
        print("No valid tracks found. Check --library path.")
        return

    print(f"Evaluating {len(valid_tracks)} tracks...")
    if HAS_ESSENTIA:
        print("Backends: essentia (RhythmExtractor2013) vs librosa (beat_track)")
    else:
        print("Backend: librosa only (essentia not available)")

    # extract BPM hints from track names
    all_results = []
    for name, audio_path in valid_tracks:
        parts = name.rsplit('_', 2)
        bpm_hint = None
        if len(parts) >= 3:
            try:
                bpm_hint = float(parts[-2])
            except ValueError:
                pass
        result = evaluate_track(audio_path, name, bpm_hint)
        all_results.append(result)

    print_summary(all_results)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(all_results, f, indent=2)
        print(f"\nDetailed results saved to {args.output}")


if __name__ == "__main__":
    main()
