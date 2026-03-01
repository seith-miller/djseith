"""PyTorch-based compositing engine for frame-level video processing.

Replaces ffmpeg filter graphs for:
  - Screen blending (multi-layer)
  - Audio-reactive brightness modulation
  - Snare contrast boost
  - Still alpha overlay
  - Pillarbox masking

Runs on MPS (Mac), CUDA (NVIDIA), or CPU fallback.
"""

import subprocess

import numpy as np
import torch


def get_device() -> torch.device:
    """Select best available device: MPS > CUDA > CPU."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


# ── frame decode / encode ────────────────────────────────────────────────────

class FrameDecoder:
    """Streaming video decoder — reads one frame at a time via ffmpeg pipe.

    Memory-efficient: only one frame per layer is in memory at any time,
    instead of loading the entire video (~12 GB per layer at 1080p).
    """

    def __init__(self, video_path: str, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self._frame_size = width * height * 3
        self._last_frame = None

        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-v", "error",
            "-"
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)

    def read_frame(self) -> torch.Tensor:
        """Read the next frame. Returns (H, W, 3) float [0, 1].

        If the stream ends, returns the last frame (hold).
        """
        raw = self._proc.stdout.read(self._frame_size)
        if len(raw) == self._frame_size:
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(
                self.height, self.width, 3)
            self._last_frame = torch.from_numpy(arr.copy()).float() / 255.0
        elif self._last_frame is None:
            self._last_frame = torch.zeros(self.height, self.width, 3)
        return self._last_frame

    def close(self):
        self._proc.stdout.close()
        self._proc.terminate()
        self._proc.wait()


def decode_still(path: str, width: int, height: int) -> torch.Tensor:
    """Decode a PNG still with alpha channel.

    Returns tensor of shape (H, W, 4) with float32 values in [0, 1].
    """
    cmd = [
        "ffmpeg", "-i", str(path),
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{width}x{height}",
        "-v", "error",
        "-"
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"decode still failed for {path}: {result.stderr.decode()[-500:]}")

    raw = result.stdout
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
    return torch.from_numpy(arr.copy()).float() / 255.0


class FrameEncoder:
    """Pipe raw frames to ffmpeg for encoding."""

    def __init__(self, output_path: str, width: int, height: int, fps: int,
                 audio_path: str = None, crf: int = 26):
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
        ]
        if audio_path:
            cmd += ["-i", str(audio_path)]

        # Select encoder: VideoToolbox on Mac, NVENC on NVIDIA, libx264 fallback
        encoder = _select_encoder()
        if encoder == "h264_videotoolbox":
            cmd += ["-c:v", encoder, "-q:v", str(max(40, 65 - crf))]
        elif encoder == "h264_nvenc":
            cmd += ["-c:v", encoder, "-cq", str(crf), "-preset", "p4"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf)]

        cmd += ["-pix_fmt", "yuv420p"]
        if audio_path:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-map", "0:v", "-map", "1:a"]
        cmd += ["-shortest", str(output_path)]

        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)

    def write_frame(self, frame: torch.Tensor):
        """Write a single frame tensor (H, W, 3) float [0,1] to the encoder."""
        rgb = (frame.clamp(0, 1) * 255).byte().cpu().numpy()
        self._proc.stdin.write(rgb.tobytes())

    def close(self):
        self._proc.stdin.close()
        self._proc.wait()
        if self._proc.returncode != 0:
            err = self._proc.stderr.read().decode()[-500:]
            raise RuntimeError(f"encode failed: {err}")


def _select_encoder() -> str:
    """Probe available hardware encoders."""
    for enc in ["h264_videotoolbox", "h264_nvenc"]:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True,
        )
        if enc in r.stdout:
            return enc
    return "libx264"


# ── compositing operations ───────────────────────────────────────────────────

def screen_blend(base: torch.Tensor, overlay: torch.Tensor,
                 opacity: float = 1.0) -> torch.Tensor:
    """Screen blend: result = 1 - (1 - base) * (1 - overlay * opacity).

    Both inputs are (H, W, 3) float [0, 1].
    """
    return 1.0 - (1.0 - base) * (1.0 - overlay * opacity)


def alpha_composite(base: torch.Tensor, overlay_rgba: torch.Tensor,
                    x: int = 0, y: int = 0) -> torch.Tensor:
    """Alpha-composite an RGBA overlay onto an RGB base at position (x, y).

    base: (H, W, 3) float [0, 1]
    overlay_rgba: (oh, ow, 4) float [0, 1]

    Handles negative x/y and clipping to canvas bounds.
    """
    H, W, _ = base.shape
    oh, ow, _ = overlay_rgba.shape

    # Source region (within overlay)
    sx = max(0, -x)
    sy = max(0, -y)
    # Destination region (within base)
    dx = max(0, x)
    dy = max(0, y)
    # Clipped dimensions
    cw = min(ow - sx, W - dx)
    ch = min(oh - sy, H - dy)

    if cw <= 0 or ch <= 0:
        return base

    result = base.clone()
    src = overlay_rgba[sy:sy+ch, sx:sx+cw]
    alpha = src[:, :, 3:4]
    rgb = src[:, :, :3]
    dst = result[dy:dy+ch, dx:dx+cw]
    result[dy:dy+ch, dx:dx+cw] = dst * (1.0 - alpha) + rgb * alpha
    return result


def apply_brightness(frame: torch.Tensor, level: float) -> torch.Tensor:
    """Multiply frame brightness by level [0, 1]."""
    return frame * level


def apply_brightness_white(frame: torch.Tensor, level: float) -> torch.Tensor:
    """White-mode brightness: screen-blend with a uniform white level.

    level=0 → no change, level=1 → fully white.
    """
    return 1.0 - (1.0 - frame) * (1.0 - level)


def apply_contrast(frame: torch.Tensor, contrast: float = 2.2,
                   brightness_offset: float = 0.06) -> torch.Tensor:
    """Apply contrast boost (matching ffmpeg eq=contrast=C:brightness=B).

    contrast: multiplier around mid-gray
    brightness_offset: added after contrast
    """
    result = (frame - 0.5) * contrast + 0.5 + brightness_offset
    return result.clamp(0.0, 1.0)


def apply_pillarbox(frame: torch.Tensor, bar_w: int,
                    color: float = 0.0) -> torch.Tensor:
    """Zero out (or white out) pillarbox columns."""
    if bar_w <= 0:
        return frame
    result = frame.clone()
    result[:, :bar_w, :] = color
    result[:, -bar_w:, :] = color
    return result


# ── full-frame compositor ────────────────────────────────────────────────────

def composite_frame(
    layer_frames: list,
    frame_idx: int,
    blend_mode: str,
    opacity: float,
    envelope: np.ndarray = None,
    still_schedule: list = None,
    still_cache: dict = None,
    snare_times: list = None,
    flash_dur: float = 0.08,
    bar_w: int = 0,
    fps: int = 30,
    width: int = 1920,
    height: int = 1080,
    white_mode: bool = False,
    device: torch.device = None,
) -> torch.Tensor:
    """Composite a single output frame from all layers and effects.

    Args:
        layer_frames: list of (H, W, 3) tensors, one per video layer (current frame)
        frame_idx: current frame index
        blend_mode: 'screen' (only screen supported for now)
        opacity: blend opacity for layer 1 (layer 2 uses opacity * 0.6)
        envelope: brightness envelope array (n_frames,)
        still_schedule: list of {path, start, end, placement} dicts
        still_cache: dict mapping path → decoded RGBA tensor
        snare_times: list of snare hit timestamps
        flash_dur: snare flash duration in seconds
        bar_w: pillarbox bar width in pixels
        fps: frames per second
        width, height: output dimensions
        white_mode: use white brightness mode
        device: torch device

    Returns:
        (H, W, 3) float tensor
    """
    t = frame_idx / fps

    # Start with layer 0
    result = layer_frames[0].to(device)

    # Screen blend additional layers
    for li in range(1, len(layer_frames)):
        layer_frame = layer_frames[li].to(device)
        op = opacity if li == 1 else round(opacity * 0.6, 2)
        result = screen_blend(result, layer_frame, op)

    # Brightness envelope
    if envelope is not None and frame_idx < len(envelope):
        level = float(envelope[frame_idx])
        if white_mode:
            level = 0.15 + 0.85 * level
            result = apply_brightness_white(result, level)
        else:
            result = apply_brightness(result, level)

    # Still overlays
    if still_schedule and still_cache:
        for item in still_schedule:
            if item['start'] <= t <= item['end']:
                still_rgba = still_cache.get(item['_cache_key'])
                if still_rgba is not None:
                    still_rgba = still_rgba.to(device)
                    x, y = _compute_still_xy(item, t, width, height)
                    result = alpha_composite(result, still_rgba, x, y)
                break  # only one still at a time

    # Pillarbox
    pb_color = 1.0 if white_mode else 0.0
    result = apply_pillarbox(result, bar_w, color=pb_color)

    # Snare contrast flash
    if snare_times:
        for st in snare_times:
            if st <= t <= st + flash_dur:
                result = apply_contrast(result)
                break

    return result


def _compute_still_xy(item: dict, t: float, width: int, height: int) -> tuple:
    """Compute (x, y) position for a still at time t.

    Mirrors the logic from _overlay_xy in generate_video.py.
    """
    placement = item['placement']
    kind = placement['type']

    if kind == 'fixed':
        return 0, 0

    if kind == 'random':
        return placement['x'], placement['y']

    # Pan: linear motion across screen
    d = placement['direction']
    SW = placement.get('img_w', width)
    SH = placement.get('img_h', height)
    cx = (width - SW) // 2
    cy = (height - SH) // 2
    ts, te = item['start'], item['end']
    dur = te - ts
    if dur <= 0:
        return cx, cy
    progress = (t - ts) / dur  # 0 at entry, 1 at exit

    x_map = {
        'l2r':   -SW + (width + SW) * progress,
        'r2l':   width - (width + SW) * progress,
        't2b':   cx,
        'b2t':   cx,
        'tl2br': -SW + (width + SW) * progress,
        'tr2bl': width - (width + SW) * progress,
        'bl2tr': -SW + (width + SW) * progress,
        'br2tl': width - (width + SW) * progress,
    }
    y_map = {
        'l2r':   cy,
        'r2l':   cy,
        't2b':   -SH + (height + SH) * progress,
        'b2t':   height - (height + SH) * progress,
        'tl2br': -SH + (height + SH) * progress,
        'tr2bl': -SH + (height + SH) * progress,
        'bl2tr': height - (height + SH) * progress,
        'br2tl': height - (height + SH) * progress,
    }

    return int(x_map[d]), int(y_map[d])
