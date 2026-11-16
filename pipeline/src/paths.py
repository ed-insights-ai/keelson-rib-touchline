"""Data-root resolution — the single seam between pipeline code and disk.

All durable data (the raw page archive, season JSON files, reference
artifacts, error reports) lives in a consumer-owned data directory — never
inside this package. Resolution order:

  1. TOUCHLINE_DATA_DIR environment variable
  2. the current working directory (workflow runs execute with cwd = the
     data repo)

Everything here is a function, not a constant, so a test or caller that
changes the environment sees the change at call time. Code-like config
(config/schools.toml) deliberately stays package-relative — see
src/config.py DEFAULT_CONFIG.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


def data_root() -> Path:
    """The consumer-owned data directory."""
    return Path(os.environ.get("TOUCHLINE_DATA_DIR", ".")).resolve()


def reference_dir() -> Path:
    return data_root() / "data" / "reference"


def membership_path() -> Path:
    """The data home's mirrored membership copy — a deployment artifact.

    The source of record is ``packaged_membership_path()``; collect mirrors
    it here (scripts/collect_board.py) so the data repo stays self-describing.
    """
    return reference_dir() / "membership.json"


def programmes_path() -> Path:
    """The data home's mirrored programmes reference — a deployment artifact.

    The source of record is ``packaged_programmes_path()``; collect mirrors
    it here beside membership.json.
    """
    return reference_dir() / "programmes.json"


def package_root() -> Path:
    """The rib package root — the parent of pipeline/.

    Resolved from this module's own location (pipeline/src/paths.py), the
    same way the rib's ``packageDir()`` works in src/datahome.ts, so a
    checkout and an installed package resolve alike (uv installs this
    project editable, so ``__file__`` stays inside the real tree).
    """
    return Path(__file__).resolve().parents[2]


def packaged_membership_path() -> Path:
    """The rib's own authored membership.json — the source of record.

    Membership is authored, reviewed data that ships with the rib, like
    config/schools.toml — not durable collected data — so this path is
    package-relative on purpose: the one deliberate exception to this
    module's data-home charter. The data home's copy (``membership_path()``)
    is a deployment artifact mirrored from this file by collect; loaders
    prefer this copy and fall back to the data home's only when an install
    carries no packaged data tree.
    """
    return package_root() / "data" / "reference" / "membership.json"


def errors_dir() -> Path:
    return data_root() / "data" / "errors"


def packaged_programmes_path() -> Path:
    """The rib's built programmes reference — the source of record.

    Built from config/schools.toml by ``uv run build-programmes`` and
    reviewed in the PR that changes it; package-relative for the same reason
    ``packaged_membership_path()`` is.
    """
    return package_root() / "data" / "reference" / "programmes.json"


#: The file that makes a directory a Touchline data home (src/datahome.ts).
MARKER_FILE = "touchline-data.yaml"

#: The NCAA levels a home can collect, the same three as
#: ``membership.LEVELS`` (kept here so this seam imports nothing).
HOME_LEVELS = ("d1", "d2", "d3")

#: What a marker with no ``level`` line means. Every data home made before
#: levels existed is Division II: until the Division I men's conferences were
#: onboarded the membership record held Division II conferences only, so
#: nothing could have been collected into such a home at another level. That
#: is the one place d2 is provably the answer, and every reader says it
#: assumed it (``HomeLevel.declared``) rather than swallowing it. The rib's
#: src/datahome.ts reads the marker by the same rule.
UNDECLARED_HOME_LEVEL = "d2"


class MarkerError(ValueError):
    """A marker that is not a usable Touchline marker: a foreign ``kind``, or
    a ``level`` that is not d1, d2 or d3. Refused, never guessed past."""


@dataclass(frozen=True)
class HomeLevel:
    """The NCAA level a data home collects, and whether its marker states it."""

    level: str
    declared: bool


def marker_path() -> Path:
    return data_root() / MARKER_FILE


def home_level() -> HomeLevel | None:
    """The data root's level per its marker; None when it carries no marker.

    The pipeline has never required a marker (the rib and the workflows
    refuse an unmarked folder before they call it), so an unmarked root is
    no level to check, not a refusal. A marker with no ``level`` is the d2
    every pre-level home is, ``declared=False``.
    """
    try:
        text = marker_path().read_text(encoding="utf-8")
    except OSError:
        return None
    kind = re.search(r"^\s*kind:\s*(\S+)\s*$", text, re.MULTILINE)
    if kind is None or kind.group(1) != "touchline-data":
        raise MarkerError(
            f"{marker_path()} is not a Touchline marker "
            f"(kind: {kind.group(1) if kind else '(absent)'})"
        )
    level = re.search(r"^\s*level:\s*(\S+)\s*$", text, re.MULTILINE)
    if level is None:
        return HomeLevel(UNDECLARED_HOME_LEVEL, declared=False)
    value = level.group(1).lower()
    if value not in HOME_LEVELS:
        raise MarkerError(
            f"{marker_path()} states level: {level.group(1)}, "
            f"which is not one of {', '.join(HOME_LEVELS)}"
        )
    return HomeLevel(value, declared=True)
