#!/usr/bin/env python3
"""Evaluate snare detection quality using beat-alignment as a proxy metric.

We don't have manual ground truth, so we use three complementary signals:

  1. Beat-alignment precision
       For each detected hit, find the nearest beat from the phrase data.
       Good detections should land close to a beat; hi-hat/noise hits will be
       scattered across the beat grid. Reports % within a tolerance window.

  2. Snare-beat recall
       We estimate which beats are "snare-expected" by measuring bandpass energy
       (2-8 kHz) at each beat position in the drum stem. Even-numbered beats in
       a 4/4 pattern (2 and 4) will show consistently higher mid-frequency
       energy than odd beats (kick-dominated). We then ask: what fraction of
       those snare-expected beats have a detected hit nearby?

  3. Inter-hit interval distribution
       A true snare pattern at 130 BPM fires every ~0.923 s (every other beat).
       A histogram of gaps between detected hits should peak strongly near that
       interval. A flat or multi-peaked distribution indicates noisy detections.

Usage:
  python visuals/scripts/eval_snare.py \\
      --snare  projects/funeral_parade_of_roses/data/blue_monday_snare.json \\
      --drums  audio/library/BlueMonday_130_Em/3_Drums_BlueMonday_130_Em.wav \\
      --phrases projects/funeral_parade_of_roses/data/blue_monday_phrases_impact.json
"""

import argparse, json, sys
from pathlib import Path

import numpy as np
import librosa
from scipy.signal import butter, sosfilt


# ── helpers ───────────────────────────────────────────────────────────────────

def bandpass(audio, sr, low_hz, high_hz, order=5):
    nyq = sr / 2.0
    sos = butter(order, [low_hz / nyq, high_hz / nyq], btype="band", output="sos")
    return sosfilt(sos, audio)


def beat_energy(y_bp, sr, beat_times, window_s=0.04):
    """RMS energy in the bandpass signal within ±window_s of each beat."""
    win = int(window_s * sr)
    energies = []
    for t in beat_times:
        c = int(t * sr)
        chunk = y_bp[max(0, c - win): min(len(y_bp), c + win)]
        energies.append(float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0)
    return np.array(energies)


def identify_snare_beats(beat_times, energies):
    """Label each beat as snare-expected or not.

    Strategy: split beats into two interleaved phases (odd/even index).
    The phase with the higher median bandpass energy is the snare phase.
    Returns boolean array, same length as beat_times.
    """
    even_e = energies[0::2]
    odd_e  = energies[1::2]
    snare_phase = 1 if np.median(odd_e) > np.median(even_e) else 0

    labels = np.zeros(len(beat_times), dtype=bool)
    labels[snare_phase::2] = True
    return labels


# ── metrics ───────────────────────────────────────────────────────────────────

def beat_alignment(hits, beats, tol_s):
    """For each hit, distance to nearest beat. Returns array of distances."""
    if len(hits) == 0:
        return np.array([])
    dists = np.array([np.min(np.abs(beats - h)) for h in hits])
    return dists


def snare_beat_recall(hits, snare_beats, tol_s):
    """Fraction of snare-expected beats that have a hit within tolerance."""
    if len(hits) == 0 or len(snare_beats) == 0:
        return 0.0
    covered = sum(np.min(np.abs(hits - b)) <= tol_s for b in snare_beats)
    return covered / len(snare_beats)


def ihi_stats(hits, beat_interval_s):
    """Inter-hit interval analysis. Returns (intervals, peak_ratio).

    peak_ratio: fraction of intervals that land near an integer multiple of
    beat_interval_s (within ±15%). Higher = more periodic = more snare-like.
    """
    if len(hits) < 2:
        return np.array([]), 0.0
    ihi = np.diff(np.sort(hits))
    # Count intervals close to 1× or 2× beat interval
    multiples = np.array([1, 2, 3, 4]) * beat_interval_s
    tol = beat_interval_s * 0.15
    on_grid = sum(np.any(np.abs(iv - multiples) < tol) for iv in ihi)
    return ihi, on_grid / len(ihi)


# ── report ────────────────────────────────────────────────────────────────────

def report(label, hits, beats, snare_beats, beat_interval_s, tol_ms=50):
    tol = tol_ms / 1000.0
    dists = beat_alignment(hits, beats, tol)
    prec  = (dists <= tol).mean() if len(dists) else 0.0
    rec   = snare_beat_recall(hits, snare_beats, tol)
    ihi, grid_ratio = ihi_stats(hits, beat_interval_s)

    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(f"  Detected hits        : {len(hits)}")
    print(f"  Snare-expected beats : {len(snare_beats)}")
    print(f"  All beats            : {len(beats)}")
    print()
    print(f"  Precision proxy  (% hits within {tol_ms}ms of any beat): {prec:.1%}")
    print(f"  Recall proxy     (% snare beats covered):               {rec:.1%}")
    print(f"  IHI on-grid rate (% intervals near beat multiple):      {grid_ratio:.1%}")
    print()
    if len(dists):
        print(f"  Distance to nearest beat:")
        print(f"    mean   {dists.mean()*1000:6.1f} ms")
        print(f"    median {np.median(dists)*1000:6.1f} ms")
        print(f"    p75    {np.percentile(dists,75)*1000:6.1f} ms")
        print(f"    p90    {np.percentile(dists,90)*1000:6.1f} ms")
    if len(ihi):
        print(f"\n  Inter-hit interval (s):")
        print(f"    beat interval  {beat_interval_s:.3f} s  (snare period {beat_interval_s*2:.3f} s)")
        print(f"    mean   {ihi.mean():.3f} s")
        print(f"    median {np.median(ihi):.3f} s")

        # Simple text histogram bucketed to beat interval
        bins = np.arange(0, min(ihi.max() + beat_interval_s, 5), beat_interval_s / 4)
        counts, edges = np.histogram(ihi, bins=bins)
        peak = counts.max()
        print(f"\n  IHI histogram (bucket = {beat_interval_s/4*1000:.0f} ms):")
        for i, c in enumerate(counts[:24]):         # show first 24 buckets
            bar = "█" * int(30 * c / peak) if peak else ""
            lo = edges[i]
            mark = " ← 1 beat" if abs(lo - beat_interval_s) < beat_interval_s*0.15 else \
                   " ← 2 beats" if abs(lo - beat_interval_s*2) < beat_interval_s*0.15 else ""
            print(f"    {lo:.3f}s  {bar} {c}{mark}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snare",   required=True, help="Snare JSON from detect_snare.py")
    ap.add_argument("--drums",   required=True, help="Drum stem WAV")
    ap.add_argument("--phrases", required=True, help="Phrases JSON with beat_times")
    ap.add_argument("--tol",     type=int, default=50, help="Tolerance in ms (default 50)")
    args = ap.parse_args()

    # Load data
    snare_data = json.loads(Path(args.snare).read_text())
    hits       = np.array(snare_data["snare_times"])

    phrases    = json.loads(Path(args.phrases).read_text())
    beats      = np.array(phrases["beat_times"])
    duration   = phrases["duration"]

    # Estimate beat interval from median gap between consecutive beats
    beat_interval = float(np.median(np.diff(beats)))
    bpm = 60.0 / beat_interval
    print(f"\nSong: {duration:.1f}s  |  {bpm:.1f} BPM  |  beat interval {beat_interval*1000:.1f} ms")

    # Load drum stem and compute bandpass energy at each beat
    print("Loading drum stem for snare-beat identification...")
    y, sr = librosa.load(args.drums, sr=22050, mono=True)
    y_bp  = bandpass(y, sr, 2000, 8000)

    energies    = beat_energy(y_bp, sr, beats)
    snare_mask  = identify_snare_beats(beats, energies)
    snare_beats = beats[snare_mask]

    phase_0_med = np.median(energies[0::2])
    phase_1_med = np.median(energies[1::2])
    print(f"  Beat phase energies: phase-0 median={phase_0_med:.4f}  phase-1 median={phase_1_med:.4f}")
    print(f"  Snare phase identified as: {'odd beats (1,3,5,…)' if snare_mask[1] else 'even beats (0,2,4,…)'}")

    report(
        f"Snare detection — {Path(args.snare).name}",
        hits, beats, snare_beats, beat_interval, tol_ms=args.tol,
    )


if __name__ == "__main__":
    main()
