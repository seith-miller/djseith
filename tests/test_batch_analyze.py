"""Tests for batch analysis script and metadata resolution."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "visuals" / "scripts"))

from batch_analyze import parse_bpm, find_stem


class TestParseBpm:
    def test_standard_format(self):
        assert parse_bpm("BlueMonday_130_Em") == 130

    def test_three_digit_bpm(self):
        assert parse_bpm("CrystalCastlesVsHealth_148_Em") == 148

    def test_two_digit_bpm(self):
        assert parse_bpm("SomeTrack_90_Am") == 90

    def test_no_bpm(self):
        assert parse_bpm("JustAName") is None

    def test_non_numeric(self):
        assert parse_bpm("Track_fast_Em") is None


class TestFindStem:
    def test_finds_matching_stem(self, tmp_path):
        (tmp_path / "3_Drums_Track.wav").touch()
        assert find_stem(tmp_path, "3_Drums") is not None

    def test_returns_none_if_missing(self, tmp_path):
        (tmp_path / "4_Mix_Track.wav").touch()
        assert find_stem(tmp_path, "3_Drums") is None


class TestResolveTrackMetadata:
    def test_finds_metadata_in_track_dir(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent / "visuals" / "scripts"))
        from generate_video import resolve_track_metadata

        # Create a fake track dir with audio and metadata
        audio = tmp_path / "4_Mix_Track.wav"
        audio.touch()
        phrases = tmp_path / "phrases.json"
        phrases.write_text('{"sections": []}')
        snare = tmp_path / "snare.json"
        snare.write_text('{"snare_times": []}')

        p, s = resolve_track_metadata(str(audio))
        assert p is not None
        assert s is not None
        assert p.name == "phrases.json"
        assert s.name == "snare.json"

    def test_returns_none_when_no_metadata(self, tmp_path):
        from generate_video import resolve_track_metadata

        audio = tmp_path / "4_Mix_Track.wav"
        audio.touch()

        p, s = resolve_track_metadata(str(audio))
        assert p is None
        assert s is None
