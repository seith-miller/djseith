"""Unit tests for PyTorch compositing operations."""

import numpy as np
import pytest
import torch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "visuals"))
from compositing import (
    screen_blend, alpha_composite, apply_brightness,
    apply_brightness_white, apply_contrast, apply_pillarbox,
)


@pytest.fixture
def device():
    return torch.device("cpu")


# ── screen_blend ─────────────────────────────────────────────────────────────

class TestScreenBlend:
    def test_black_overlay_is_identity(self):
        base = torch.rand(4, 4, 3)
        black = torch.zeros(4, 4, 3)
        result = screen_blend(base, black, opacity=1.0)
        assert torch.allclose(result, base, atol=1e-6)

    def test_white_overlay_is_white(self):
        base = torch.rand(4, 4, 3)
        white = torch.ones(4, 4, 3)
        result = screen_blend(base, white, opacity=1.0)
        assert torch.allclose(result, torch.ones(4, 4, 3), atol=1e-6)

    def test_self_blend(self):
        base = torch.full((4, 4, 3), 0.5)
        result = screen_blend(base, base, opacity=1.0)
        expected = 1.0 - (1.0 - 0.5) * (1.0 - 0.5)  # 0.75
        assert torch.allclose(result, torch.full((4, 4, 3), expected), atol=1e-6)

    def test_zero_opacity(self):
        base = torch.full((4, 4, 3), 0.3)
        overlay = torch.ones(4, 4, 3)
        result = screen_blend(base, overlay, opacity=0.0)
        assert torch.allclose(result, base, atol=1e-6)

    def test_output_range(self):
        base = torch.rand(16, 16, 3)
        overlay = torch.rand(16, 16, 3)
        result = screen_blend(base, overlay, opacity=0.7)
        assert result.min() >= 0.0
        assert result.max() <= 1.0


# ── alpha_composite ──────────────────────────────────────────────────────────

class TestAlphaComposite:
    def test_fully_opaque_overlay(self):
        base = torch.zeros(4, 4, 3)
        overlay = torch.ones(2, 2, 4)  # fully opaque white
        result = alpha_composite(base, overlay, x=1, y=1)
        assert torch.allclose(result[1:3, 1:3, :], torch.ones(2, 2, 3), atol=1e-6)
        assert torch.allclose(result[0, 0, :], torch.zeros(3), atol=1e-6)

    def test_fully_transparent_overlay(self):
        base = torch.full((4, 4, 3), 0.5)
        overlay = torch.zeros(2, 2, 4)  # fully transparent
        result = alpha_composite(base, overlay, x=0, y=0)
        assert torch.allclose(result, base, atol=1e-6)

    def test_half_alpha(self):
        base = torch.zeros(4, 4, 3)
        overlay = torch.tensor([[[1.0, 1.0, 1.0, 0.5]]])  # 1x1 white, 50% alpha
        result = alpha_composite(base, overlay, x=0, y=0)
        assert torch.allclose(result[0, 0, :], torch.full((3,), 0.5), atol=1e-6)

    def test_negative_position_clips(self):
        base = torch.zeros(4, 4, 3)
        overlay = torch.ones(2, 2, 4)
        result = alpha_composite(base, overlay, x=-1, y=-1)
        # Only bottom-right pixel of overlay should appear at (0,0)
        assert torch.allclose(result[0, 0, :], torch.ones(3), atol=1e-6)
        assert torch.allclose(result[1, 0, :], torch.zeros(3), atol=1e-6)

    def test_out_of_bounds_returns_base(self):
        base = torch.full((4, 4, 3), 0.5)
        overlay = torch.ones(2, 2, 4)
        result = alpha_composite(base, overlay, x=10, y=10)
        assert torch.allclose(result, base, atol=1e-6)


# ── apply_brightness ─────────────────────────────────────────────────────────

class TestBrightness:
    def test_zero_is_black(self):
        frame = torch.rand(4, 4, 3)
        result = apply_brightness(frame, 0.0)
        assert torch.allclose(result, torch.zeros(4, 4, 3), atol=1e-6)

    def test_one_is_identity(self):
        frame = torch.rand(4, 4, 3)
        result = apply_brightness(frame, 1.0)
        assert torch.allclose(result, frame, atol=1e-6)

    def test_half_brightness(self):
        frame = torch.full((4, 4, 3), 0.8)
        result = apply_brightness(frame, 0.5)
        assert torch.allclose(result, torch.full((4, 4, 3), 0.4), atol=1e-6)


# ── apply_brightness_white ───────────────────────────────────────────────────

class TestBrightnessWhite:
    def test_zero_is_identity(self):
        frame = torch.rand(4, 4, 3)
        result = apply_brightness_white(frame, 0.0)
        assert torch.allclose(result, frame, atol=1e-6)

    def test_one_is_white(self):
        frame = torch.rand(4, 4, 3)
        result = apply_brightness_white(frame, 1.0)
        assert torch.allclose(result, torch.ones(4, 4, 3), atol=1e-6)


# ── apply_contrast ───────────────────────────────────────────────────────────

class TestContrast:
    def test_midgray_stays_near_mid(self):
        frame = torch.full((4, 4, 3), 0.5)
        result = apply_contrast(frame, contrast=2.2, brightness_offset=0.0)
        assert torch.allclose(result, torch.full((4, 4, 3), 0.5), atol=1e-6)

    def test_increases_range(self):
        frame = torch.full((4, 4, 3), 0.7)
        result = apply_contrast(frame, contrast=2.2, brightness_offset=0.0)
        assert result[0, 0, 0].item() > 0.7  # brighter pixels get brighter

    def test_clamps_output(self):
        frame = torch.rand(4, 4, 3)
        result = apply_contrast(frame, contrast=5.0, brightness_offset=0.5)
        assert result.min() >= 0.0
        assert result.max() <= 1.0


# ── apply_pillarbox ──────────────────────────────────────────────────────────

class TestPillarbox:
    def test_bars_are_black(self):
        frame = torch.ones(4, 10, 3)
        result = apply_pillarbox(frame, bar_w=2, color=0.0)
        assert torch.allclose(result[:, :2, :], torch.zeros(4, 2, 3), atol=1e-6)
        assert torch.allclose(result[:, -2:, :], torch.zeros(4, 2, 3), atol=1e-6)
        assert torch.allclose(result[:, 2:-2, :], torch.ones(4, 6, 3), atol=1e-6)

    def test_white_bars(self):
        frame = torch.zeros(4, 10, 3)
        result = apply_pillarbox(frame, bar_w=2, color=1.0)
        assert torch.allclose(result[:, :2, :], torch.ones(4, 2, 3), atol=1e-6)

    def test_zero_bar_width_is_identity(self):
        frame = torch.rand(4, 10, 3)
        result = apply_pillarbox(frame, bar_w=0)
        assert torch.allclose(result, frame, atol=1e-6)
