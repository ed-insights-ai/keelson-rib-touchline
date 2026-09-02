"""The box-vs-fixture check has a second source and goes red on a planted error."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_box_scores import compare


def _home(tmp_path: Path, fixture: dict, box: dict) -> Path:
    (tmp_path / "data" / "fixtures").mkdir(parents=True)
    (tmp_path / "data" / "matches").mkdir(parents=True)
    (tmp_path / "data" / "fixtures" / "2025-men-gac.json").write_text(
        json.dumps({"fixtures": [fixture]})
    )
    (tmp_path / "data" / "matches" / "2025-men-gac.json").write_text(
        json.dumps({"matches": {fixture["id"]: box}})
    )
    return tmp_path


FIXTURE = {
    "id": "sidearm:rogers-state:7263",
    "date": "2025-09-13",
    "home": "oklahoma-christian",
    "away": "rogers-state",
    "home_score": 0,
    "away_score": 1,
    "status": "final",
}
# The box names its teams. Rogers St. is listed first and is the away side,
# so the right home_index is 1; it is deliberately WRONG here (0) to prove the
# comparison never consults it, and that the disagreement is itself named.
BOX = {
    "home_index": 0,
    "teams": [
        {"name": "Rogers St.", "score": 1},
        {"name": "Okla. Christian", "score": 0},
    ],
}


def test_agreeing_box_and_fixture_pass_by_name_and_the_bad_home_index_is_named(
    tmp_path: Path,
) -> None:
    out = compare(_home(tmp_path, FIXTURE, BOX))
    assert out["counts"]["compared"] == 1
    assert out["counts"]["reversed"] == 0 and out["counts"]["differs"] == 0
    assert out["counts"]["home_index"] == 1
    assert any(line.startswith("HOME_INDEX") for line in out["findings"])


def test_a_planted_reversal_goes_red(tmp_path: Path) -> None:
    # The tl-b39 shape: the fixture stores OC 1-0 when RSU won 1-0, and the
    # box's home_index was derived from that fixture so it agrees with it.
    reversed_fixture = {**FIXTURE, "home_score": 1, "away_score": 0}
    # Matching scores to the reversed fixture puts Rogers St. (score 1) at
    # home_score 1: home_index 0, wrong, and self-consistent with the error.
    agreeing_box = {**BOX, "home_index": 0}
    out = compare(_home(tmp_path, reversed_fixture, agreeing_box))
    assert out["counts"]["reversed"] == 1
    assert any(
        line.startswith("REVERSED") and "sidearm:rogers-state:7263" in line
        for line in out["findings"]
    )


def test_a_different_score_is_named_as_different_not_reversed(tmp_path: Path) -> None:
    out = compare(_home(tmp_path, {**FIXTURE, "away_score": 2}, BOX))
    assert out["counts"]["differs"] == 1 and out["counts"]["reversed"] == 0


def test_unresolvable_names_are_counted_not_passed(tmp_path: Path) -> None:
    box = {
        "teams": [{"name": "Nobody FC", "score": 1}, {"name": "Someone SC", "score": 0}]
    }
    out = compare(_home(tmp_path, FIXTURE, box))
    assert out["counts"]["compared"] == 0
    assert out["counts"]["unresolved"] == 1
