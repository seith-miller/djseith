#!/usr/bin/env python3
"""Generate a color-block video from phrase detection output.

Each detected section gets a distinct color. The section number is
displayed on screen. Audio from the original track is muxed in.
Use this to visually verify phrase detection quality.

Usage:
    python visuals/section_viz.py <phrases.json> <audio.wav> [-o output.mp4]
"""

import argparse, json, subprocess, tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30

# visually distinct palette (max ~20, then cycles)
PALETTE = [
    (30, 30, 30),      # near-black (intro)
    (180, 40, 40),     # red
    (40, 120, 180),    # blue
    (180, 160, 40),    # gold
    (40, 160, 80),     # green
    (140, 60, 160),    # purple
    (200, 100, 40),    # orange
    (60, 140, 140),    # teal
    (160, 60, 100),    # rose
    (80, 80, 180),     # indigo
    (180, 180, 60),    # yellow
    (60, 180, 120),    # mint
    (120, 40, 40),     # dark red
    (40, 80, 120),     # dark blue
    (120, 120, 40),    # olive
    (100, 40, 120),    # plum
    (180, 140, 100),   # tan
    (80, 120, 80),     # sage
    (140, 100, 60),    # brown
    (60, 60, 100),     # slate
]


def format_time(s):
    m, sec = divmod(s, 60)
    return f"{int(m)}:{sec:05.2f}"


def generate(phrases_path: str, audio_path: str, output_path: str):
    with open(phrases_path) as f:
        data = json.load(f)

    sections = data['sections']
    duration = data['duration']
    tempo = data['tempo']
    total_frames = int(duration * FPS)

    print(f"Generating {total_frames} frames at {FPS}fps ({format_time(duration)})")
    print(f"{len(sections)} sections, {tempo} BPM")

    # try to load a monospace font
    font_large = None
    font_small = None
    for fp in ["/System/Library/Fonts/Menlo.ttc",
               "/System/Library/Fonts/Monaco.dfont",
               "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]:
        try:
            font_large = ImageFont.truetype(fp, 120)
            font_small = ImageFont.truetype(fp, 36)
            break
        except:
            continue
    if not font_large:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # pipe frames to ffmpeg
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "pipe:0",
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for frame_idx in range(total_frames):
        t = frame_idx / FPS

        # find current section
        sec_idx = 0
        for i, s in enumerate(sections):
            if t >= s['start_time']:
                sec_idx = i

        sec = sections[sec_idx]
        color = PALETTE[sec_idx % len(PALETTE)]

        # flash white briefly at section transitions (first 3 frames)
        frames_into_section = int((t - sec['start_time']) * FPS)
        if frames_into_section < 3 and sec_idx > 0:
            color = (255, 255, 255)

        img = Image.new('RGB', (W, H), color)
        draw = ImageDraw.Draw(img)

        # section number
        label = f"Section {sec_idx + 1}"
        bbox = draw.textbbox((0, 0), label, font=font_large)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, H // 2 - 100), label, fill=(255, 255, 255), font=font_large)

        # info line
        info = (f"{format_time(sec['start_time'])} - {format_time(sec['end_time'])}  "
                f"|  {sec['bars']} bars  |  energy: {sec['energy']:.2f}")
        bbox2 = draw.textbbox((0, 0), info, font=font_small)
        tw2 = bbox2[2] - bbox2[0]
        draw.text(((W - tw2) // 2, H // 2 + 40), info, fill=(200, 200, 200), font=font_small)

        # timecode
        tc = format_time(t)
        draw.text((30, H - 60), tc, fill=(150, 150, 150), font=font_small)

        # beat indicator
        beat_period = 60.0 / tempo
        beat_phase = (t % beat_period) / beat_period
        indicator_r = int(20 * (1 - beat_phase))
        cx, cy = W - 60, H - 60
        draw.ellipse([cx - indicator_r, cy - indicator_r, cx + indicator_r, cy + indicator_r],
                     fill=(255, 255, 255))

        proc.stdin.write(np.array(img).tobytes())

        if frame_idx % (FPS * 5) == 0:
            print(f"  {format_time(t)} / {format_time(duration)}")

    proc.stdin.close()
    proc.wait()
    print(f"\nSaved: {output_path}")


def main():
    ap = argparse.ArgumentParser(description="Generate section visualization video")
    ap.add_argument("phrases", help="Path to phrases JSON from phrase_detect.py")
    ap.add_argument("audio", help="Path to audio file")
    ap.add_argument("-o", "--output", default=None, help="Output video path")
    args = ap.parse_args()

    if not args.output:
        stem = Path(args.audio).stem
        args.output = str(Path(args.phrases).parent / f"{stem}_sections.mp4")

    generate(args.phrases, args.audio, args.output)


if __name__ == "__main__":
    main()
