"""The season unit: a collect run's scope only ever widens.

The season files are rewritten wholesale by each run, so the guard under test
is what stops "refresh Harding" from silently discarding the other six
programmes of an already-collected conference.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.collect_board import widen_to_existing_scope


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_no_existing_files_leaves_the_ask_alone(tmp_path: Path) -> None:
    wanted, added = widen_to_existing_scope(
        ["harding"], tmp_path / "fx.json", tmp_path / "ro.json"
    )
    assert wanted == ["harding"]
    assert added == []


def test_narrower_ask_absorbs_the_existing_conference(tmp_path: Path) -> None:
    fx = _write(
        tmp_path / "fx.json",
        {
            "programmes": [
                {"slug": "harding"},
                {"slug": "rogers-state"},
                {"slug": "newman"},
            ],
            "missing": ["northeastern-state"],
        },
    )
    wanted, added = widen_to_existing_scope(["harding"], fx, tmp_path / "ro.json")
    # The requested slug keeps its place; the absorbed scope is appended sorted.
    assert wanted == ["harding", "newman", "northeastern-state", "rogers-state"]
    assert added == ["newman", "northeastern-state", "rogers-state"]


def test_roster_only_history_still_widens(tmp_path: Path) -> None:
    # A past season carries rosters and no fixtures file; collecting another
    # school's 2019 roster must not shrink the 2019 roster file.
    ro = _write(
        tmp_path / "ro.json",
        {"rosters": {"harding": {}, "ouachita": {}}, "missing": ["newman"]},
    )
    wanted, added = widen_to_existing_scope(["rogers-state"], tmp_path / "fx.json", ro)
    assert wanted == ["rogers-state", "harding", "newman", "ouachita"]
    assert added == ["harding", "newman", "ouachita"]


def test_equal_or_wider_ask_adds_nothing(tmp_path: Path) -> None:
    fx = _write(tmp_path / "fx.json", {"programmes": [{"slug": "harding"}]})
    wanted, added = widen_to_existing_scope(
        ["harding", "rogers-state"], fx, tmp_path / "ro.json"
    )
    assert wanted == ["harding", "rogers-state"]
    assert added == []


def test_a_malformed_file_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    bad = tmp_path / "fx.json"
    bad.write_text("{ not json", encoding="utf-8")
    wanted, added = widen_to_existing_scope(["harding"], bad, tmp_path / "ro.json")
    assert wanted == ["harding"]
    assert added == []
