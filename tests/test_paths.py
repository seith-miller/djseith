"""visuals/paths.py — the library root and project resolution."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "visuals"))
import paths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def test_defaults_are_the_old_layout(monkeypatch):
    monkeypatch.delenv("DJSEITH_LIBRARY", raising=False)
    monkeypatch.delenv("DJSEITH_PROJECT", raising=False)
    assert paths.library_root() == REPO / "projects"
    assert paths.default_project() == "funeral_parade_of_roses"
    assert paths.shots_dir() == REPO / "projects" / "funeral_parade_of_roses" / "shots"
    assert paths.catalog_path() == (
        REPO / "projects" / "funeral_parade_of_roses" / "data" / "shot_catalog.json"
    )


def test_env_moves_the_library_root(monkeypatch, tmp_path):
    monkeypatch.setenv("DJSEITH_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setenv("DJSEITH_PROJECT", "jax")
    assert paths.library_root() == (tmp_path / "lib").resolve()
    assert paths.project_dir() == (tmp_path / "lib").resolve() / "jax"
    assert paths.source_video_dir() == paths.project_dir() / "source" / "video"
    assert paths.review_state_path() == paths.project_dir() / "data" / "review_state.json"
    assert paths.report_dir() == paths.project_dir() / "data" / "duplicate_report"


def test_explicit_project_beats_env(monkeypatch):
    monkeypatch.setenv("DJSEITH_PROJECT", "jax")
    assert paths.project_dir("gay_industrial").name == "gay_industrial"
    assert paths.shots_dir("gay_industrial").parent.name == "gay_industrial"


def test_library_root_expands_tilde(monkeypatch):
    monkeypatch.setenv("DJSEITH_LIBRARY", "~/somewhere")
    assert "~" not in str(paths.library_root())
    assert paths.library_root().is_absolute()


def test_add_project_arg_defaults_from_env(monkeypatch):
    monkeypatch.setenv("DJSEITH_PROJECT", "jax")
    ap = argparse.ArgumentParser()
    paths.add_project_arg(ap)
    assert ap.parse_args([]).project == "jax"
    assert ap.parse_args(["--project", "other"]).project == "other"
