"""Where the shot library lives — answered in one place.

Every pipeline script used to hard-code ``projects/funeral_parade_of_roses``.
The library root and the default project now resolve here, from the
environment, so the same scripts serve any project — and, next, one act-level
library outside the repo. Media stays out of git either way.

    DJSEITH_LIBRARY   directory holding <project>/{source,shots,data,output,stills}
                      default: <repo>/projects
    DJSEITH_PROJECT   the project scripts default to
                      default: funeral_parade_of_roses

Scripts import this the way they import ``config``/``compositing``::

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from paths import add_project_arg, shots_dir, catalog_path

Layout under a project (unchanged from before):

    <project>/source/video/   downloaded source films
    <project>/shots/<slug>/   split shots, one folder per source
    <project>/data/           shot_catalog.json, review_state.json, reports
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = "funeral_parade_of_roses"


def library_root() -> Path:
    """The directory that holds every project. ``DJSEITH_LIBRARY`` or ``<repo>/projects``."""
    raw = os.environ.get("DJSEITH_LIBRARY")
    return Path(raw).expanduser().resolve() if raw else REPO / "projects"


def default_project() -> str:
    """The project a script works on when ``--project`` is not given."""
    return os.environ.get("DJSEITH_PROJECT") or DEFAULT_PROJECT


def project_dir(project: str | None = None) -> Path:
    return library_root() / (project or default_project())


def source_video_dir(project: str | None = None) -> Path:
    return project_dir(project) / "source" / "video"


def shots_dir(project: str | None = None) -> Path:
    return project_dir(project) / "shots"


def data_dir(project: str | None = None) -> Path:
    return project_dir(project) / "data"


def catalog_path(project: str | None = None) -> Path:
    return data_dir(project) / "shot_catalog.json"


def review_state_path(project: str | None = None) -> Path:
    return data_dir(project) / "review_state.json"


def report_dir(project: str | None = None) -> Path:
    """Where find_duplicates writes its report + hash cache."""
    return data_dir(project) / "duplicate_report"


def add_project_arg(parser: argparse.ArgumentParser) -> None:
    """Give a script the standard ``--project`` flag, defaulted from the env."""
    parser.add_argument(
        "--project",
        default=default_project(),
        help=(
            f"Project folder under the library root "
            f"(default {default_project()}; root {library_root()})"
        ),
    )
