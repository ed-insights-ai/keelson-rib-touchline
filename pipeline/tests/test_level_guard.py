"""collect-board refuses a conference whose NCAA level is not the data home's.

The rib's touchline_collect tool and the collect/backfill workflows refuse
first; this is the same rule held at the collector's own door, before the
membership mirror is written or any page fetched.
"""

from __future__ import annotations

import sys

import pytest

from scripts import collect_board
from src import membership


def _conference_at(level: str) -> str:
    for code, profile in membership.conference_profiles().items():
        if profile.level == level:
            return code
    raise AssertionError(f"the shipped record profiles no {level} conference")


def _run(monkeypatch, tmp_path, conference: str) -> int:
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect-board",
            "--conference",
            conference,
            "--gender",
            "men",
            "--season",
            "2026",
            "--programmes",
            "nobody",
        ],
    )

    def no_fetch(**_kwargs):
        raise AssertionError("collect() ran: the guard let a fetch through")

    monkeypatch.setattr(collect_board, "collect", no_fetch)
    return collect_board.main()


@pytest.mark.parametrize(("home", "conference_level"), [("d2", "d1"), ("d1", "d2")])
def test_a_conference_of_another_level_is_refused_before_anything_is_written(
    monkeypatch, tmp_path, capsys, home, conference_level
):
    (tmp_path / "touchline-data.yaml").write_text(
        f"kind: touchline-data\nversion: 1\nlevel: {home}\n", encoding="utf-8"
    )
    conference = _conference_at(conference_level)
    assert _run(monkeypatch, tmp_path, conference) == 2
    err = capsys.readouterr().err
    assert (
        f"REFUSED: {conference} is a {conference_level} conference and the data "
        f"home {tmp_path.resolve()} collects {home} (declared in its marker)."
    ) in err
    # nothing landed: not even the membership mirror
    assert sorted(p.name for p in tmp_path.iterdir()) == ["touchline-data.yaml"]


def test_a_marker_with_no_level_is_d2_and_says_so(monkeypatch, tmp_path, capsys):
    (tmp_path / "touchline-data.yaml").write_text(
        "kind: touchline-data\nversion: 1\n", encoding="utf-8"
    )
    conference = _conference_at("d1")
    assert _run(monkeypatch, tmp_path, conference) == 2
    out = capsys.readouterr()
    assert "declares no level, so it is read as d2" in out.out
    assert "collects d2 (assumed: its marker declares no level)" in out.err
