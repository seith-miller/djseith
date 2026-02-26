#!/usr/bin/env python3
"""Detect snare drum hits from a drum stem WAV file.

Method (NMF on PCEN-normalised spectrogram):
  1. Compute mel spectrogram and apply PCEN (Per-Channel Energy Normalisation).
     PCEN uses an adaptive gain control per frequency band so that quiet
     high-frequency content (snare crack) gets equal weight to loud
     low-frequency content (kick). Without this, NMF just decomposes the kick
     in N slightly different ways.
  2. Factorise with NMF into N components — each gets a spectral template (W)
     and a time activation (H).
  3. Automatically identify the snare component:
       a. Exclude templates with centroid below kick_max_hz  (kick)
       b. Exclude templates with centroid above hihat_min_hz (hi-hat)
       c. Among survivors, pick the one with the strongest autocorrelation at
          the 2-beat lag — that is the component firing periodically like a snare.
  4. Run onset detection on the snare component's activation curve.

Usage:
  python visuals/scripts/detect_snare.py \\
      --drums   audio/library/BlueMonday_130_Em/3_Drums_BlueMonday_130_Em.wav \\
      --phrases projects/funeral_parade_of_roses/data/blue_monday_phrases_impact.json \\
      --output  projects/funeral_parade_of_roses/data/blue_monday_snare.json
"""

import argparse, json, warnings
from pathlib import Path

import numpy as np
import librosa


# ── spectrogram + NMF ─────────────────────────────────────────────────────────

def pcen_melspec(y: np.ndarray, sr: int, hop: int = 512, n_mels: int = 128) -> np.ndarray:
    """Mel spectrogram with PCEN normalisation applied.

    PCEN normalises each mel band with an adaptive time-varying gain, making
    quiet transient events (snare, hi-hat) comparable in magnitude to louder
    steady-state or low-frequency events (kick).
    """
    S = librosa.feature.melspectrogram(
        y=y, sr=sr, hop_length=hop, n_mels=n_mels, fmin=50, fmax=11000, power=1,
    )
    # PCEN expects a power=1 (magnitude) spectrogram scaled to [0, 2^31)
    return librosa.pcen(S * (2 ** 31), sr=sr, hop_length=hop)


def nmf_decompose(S: np.ndarray, n_components: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """NMF factorisation. Returns (W, H) where W=(n_mels, k), H=(k, n_frames)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # suppress ConvergenceWarning
        W, H = librosa.decompose.decompose(
            S, n_components=n_components, sort=True,
            transformer=None,
        )
    # Override with sklearn NMF for more iterations
    from sklearn.decomposition import NMF
    model = NMF(n_components=n_components, max_iter=1000, random_state=0)
    H_sk = model.fit_transform(S.T).T   # sklearn: samples × features, so transpose
    W_sk = model.components_.T          # (n_mels, k)
    return W_sk, H_sk


# ── component identification ──────────────────────────────────────────────────

def spectral_centroid(W_col: np.ndarray, mel_freqs: np.ndarray) -> float:
    w = W_col / (W_col.sum() + 1e-9)
    return float(np.dot(w, mel_freqs))


def autocorr_at_lag(signal: np.ndarray, lag: int) -> float:
    if lag >= len(signal):
        return 0.0
    a, b = signal[lag:], signal[:len(signal) - lag]
    denom = np.std(a) * np.std(b)
    return float(np.corrcoef(a, b)[0, 1]) if denom > 1e-9 else 0.0


def identify_snare_component(
    W: np.ndarray,
    H: np.ndarray,
    mel_freqs: np.ndarray,
    beat_interval_s: float,
    hop: int,
    sr: int,
    kick_max_hz: float = 600.0,
    hihat_min_hz: float = 7000.0,
) -> int:
    n = W.shape[1]
    centroids = [spectral_centroid(W[:, i], mel_freqs) for i in range(n)]
    two_beat_lag = int(round(2 * beat_interval_s * sr / hop))

    def ac2(i):
        return autocorr_at_lag(H[i], two_beat_lag)

    # Filter to snare-frequency range; relax progressively if needed
    for lo, hi in [
        (kick_max_hz, hihat_min_hz),
        (300.0,       hihat_min_hz),
        (300.0,       11000.0),
        (0.0,         11000.0),
    ]:
        candidates = [i for i, c in enumerate(centroids) if lo < c < hi]
        if candidates:
            break

    chosen = max(candidates, key=ac2)

    print(f"  NMF components ({n}):")
    for i, c in enumerate(centroids):
        tag = " ← snare" if i == chosen else \
              " (kick?)"  if c < kick_max_hz else \
              " (hihat?)" if c > hihat_min_hz else ""
        print(f"    [{i}] centroid {c:6.0f} Hz  2-beat ac={ac2(i):.3f}{tag}")

    return chosen


# ── onset detection ───────────────────────────────────────────────────────────

def detect_from_activation(
    activation: np.ndarray,
    sr: int,
    hop: int,
    min_gap_s: float = 0.35,
    delta: float = 0.10,
) -> list[float]:
    wait = max(1, int(min_gap_s * sr / hop))
    frames = librosa.onset.onset_detect(
        onset_envelope=activation,
        sr=sr, hop_length=hop,
        delta=delta, wait=wait,
        backtrack=True, units="frames",
    )
    return sorted(librosa.frames_to_time(frames, sr=sr, hop_length=hop).tolist())


def snap_to_beats(
    hits: list[float],
    beats: np.ndarray,
    snap_tol_s: float = 0.15,
) -> list[float]:
    """Snap each hit to the nearest beat if within tolerance; discard the rest.

    Two hits that snap to the same beat collapse to one (keeps the one
    already closest to the beat, which after snapping is the same position).
    """
    snapped = {}   # beat_time → True (deduplicate via dict key)
    kept = rejected = 0
    for h in hits:
        dists = np.abs(beats - h)
        nearest_idx = int(np.argmin(dists))
        if dists[nearest_idx] <= snap_tol_s:
            snapped[float(beats[nearest_idx])] = True
            kept += 1
        else:
            rejected += 1
    result = sorted(snapped.keys())
    print(f"  Beat-snap: {kept} hits snapped, {rejected} rejected  → {len(result)} unique beats")
    return result


# ── public entry point ────────────────────────────────────────────────────────

def detect_snare(
    drum_path: str,
    beat_interval_s: float,
    beat_times: np.ndarray,
    n_components: int = 6,
    min_gap_s: float = 0.35,
    delta: float = 0.10,
    kick_max_hz: float = 600.0,
    hihat_min_hz: float = 7000.0,
    snap_tol_s: float = 0.15,
) -> tuple[list[float], int]:
    sr_target = 22050
    hop = 512

    print(f"  Loading {Path(drum_path).name}...")
    y, sr = librosa.load(drum_path, sr=sr_target, mono=True)

    print("  PCEN mel spectrogram...")
    S = pcen_melspec(y, sr, hop=hop)

    print(f"  NMF decomposition ({n_components} components)...")
    W, H = nmf_decompose(S, n_components=n_components)
    mel_freqs = librosa.mel_frequencies(n_mels=W.shape[0], fmin=50, fmax=11000)

    snare_idx = identify_snare_component(
        W, H, mel_freqs, beat_interval_s, hop, sr, kick_max_hz, hihat_min_hz,
    )

    print(f"  Onset detection on component [{snare_idx}]...")
    times = detect_from_activation(H[snare_idx], sr, hop, min_gap_s, delta)

    print(f"  Snapping {len(times)} raw hits to beat grid (tol={snap_tol_s*1000:.0f}ms)...")
    times = snap_to_beats(times, beat_times, snap_tol_s)

    return times, snare_idx


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Detect snare hits via NMF + PCEN")
    ap.add_argument("--drums",      required=True,  help="Drum stem WAV")
    ap.add_argument("--phrases",    required=True,  help="Phrases JSON (beat_times)")
    ap.add_argument("--output",     required=True,  help="Output JSON path")
    ap.add_argument("--components", type=int,   default=6,      help="NMF components (default 6)")
    ap.add_argument("--gap",        type=float, default=0.35,   help="Min gap between hits in s (default 0.35)")
    ap.add_argument("--delta",      type=float, default=0.10,   help="Onset delta threshold (default 0.10)")
    ap.add_argument("--kick-max",   type=float, default=600.0,  help="Kick centroid ceiling Hz (default 600)")
    ap.add_argument("--hihat-min",  type=float, default=7000.0, help="Hi-hat centroid floor Hz (default 7000)")
    ap.add_argument("--snap-tol",   type=float, default=0.15,   help="Beat-snap tolerance in s (default 0.15)")
    args = ap.parse_args()

    phrases = json.loads(Path(args.phrases).read_text())
    beats   = np.array(phrases["beat_times"])
    beat_interval_s = float(np.median(np.diff(beats)))
    print(f"  Beat interval {beat_interval_s*1000:.1f} ms  ({60/beat_interval_s:.1f} BPM)")

    times, snare_idx = detect_snare(
        args.drums, beat_interval_s, beats,
        n_components=args.components,
        min_gap_s=args.gap,
        delta=args.delta,
        kick_max_hz=args.kick_max,
        hihat_min_hz=args.hihat_min,
        snap_tol_s=args.snap_tol,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps({
        "snare_times":     times,
        "n_hits":          len(times),
        "drum_stem":       str(args.drums),
        "method":          "nmf_pcen",
        "snare_component": snare_idx,
        "n_components":    args.components,
    }, indent=2))
    print(f"  {len(times)} snare hits → {args.output}")


if __name__ == "__main__":
    main()
