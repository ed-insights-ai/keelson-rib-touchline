"""collect-board refuses a conference whose NCAA level is not the data home's.

The rib's touchline_collect tool and the collect/backfill workflows refuse
first; this is the same rule held at the collector's own door, before the
membership mirror is written or any page fetched.
"""

from __future__ import annotations

import json
import sys

import pytest

from scripts import collect_board
from src import membership


def _conference_at(level: str) -> str:
    for code, profile in membership.conference_profiles().items():
        if profile.level == level:
            return code
    raise AssertionError(f"the shipped record profiles no {level} conference")


def _run(
    monkeypatch,
    tmp_path,
    conference: str,
    *,
    season: str = "2026",
    programmes: str = "nobody",
    collect=None,
) -> int:
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
            season,
            "--programmes",
            programmes,
        ],
    )

    def no_fetch(**_kwargs):
        raise AssertionError("collect() ran: the guard let a fetch through")

    monkeypatch.setattr(collect_board, "collect", collect or no_fetch)
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


# ── every programme of the final, widened list at the home's level ──────────


def _mark(tmp_path, level: str) -> None:
    (tmp_path / "touchline-data.yaml").write_text(
        f"kind: touchline-data\nversion: 1\nlevel: {level}\n", encoding="utf-8"
    )


def test_a_programme_of_another_level_is_refused_though_its_conference_passes(
    monkeypatch, tmp_path, capsys
):
    """The reviewer's case: GAC is d2, so the conference guard passes, and
    Pitt's covering ACC window passes the uncovered-season check; Pitt is
    Division I and must not be fetched into a Division II home."""
    _mark(tmp_path, "d2")
    assert _run(monkeypatch, tmp_path, "GAC", programmes="pitt") == 2
    err = capsys.readouterr().err
    assert (
        f"REFUSED: the data home {tmp_path.resolve()} collects d2, and these men "
        "programmes are at another NCAA level for 2026: pitt (d1 in 2026)."
    ) in err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["touchline-data.yaml"]


def _stored_psac(tmp_path, season: int) -> tuple[object, str]:
    fixtures = tmp_path / "data" / "fixtures" / f"{season}-men-psac.json"
    fixtures.parent.mkdir(parents=True)
    stored = json.dumps(
        {"programmes": [{"slug": "gannon"}, {"slug": "mercyhurst"}], "fixtures": []}
    )
    fixtures.write_text(stored, encoding="utf-8")
    return fixtures, stored


def test_a_programme_restored_by_widening_is_held_to_the_home_level(
    monkeypatch, tmp_path, capsys
):
    """A 2026 PSAC shard that lists Mercyhurst (NEC, Division I, from 2024)
    widens a Gannon ask to it; the widened programme is refused by name,
    said to come from the stored shard, and the shard is left as it was."""
    _mark(tmp_path, "d2")
    fixtures, stored = _stored_psac(tmp_path, 2026)
    assert _run(monkeypatch, tmp_path, "PSAC", programmes="gannon") == 2
    err = capsys.readouterr().err
    assert (
        "programmes are at another NCAA level for 2026: mercyhurst (d1 in 2026)" in err
    )
    assert "mercyhurst came from this data home's existing 2026-men-psac files" in err
    assert fixtures.read_text(encoding="utf-8") == stored
    # nothing synced or fetched: the home holds only the marker and the shard
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data", "touchline-data.yaml"]
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == ["fixtures"]


def test_mercyhursts_last_division_ii_season_still_widens_and_collects(
    monkeypatch, tmp_path
):
    """2023 is Mercyhurst's last PSAC season, so the same widening is at the
    home's level and reaches the collect."""
    _mark(tmp_path, "d2")
    _stored_psac(tmp_path, 2023)
    reached: list[list[str]] = []

    class Reached(Exception):
        pass

    def record(**kwargs):
        reached.append(kwargs["wanted"])
        raise Reached

    with pytest.raises(Reached):
        _run(
            monkeypatch,
            tmp_path,
            "PSAC",
            season="2023",
            programmes="gannon",
            collect=record,
        )
    assert reached == [["gannon", "mercyhurst"]]


def test_a_structural_collect_is_held_to_the_home_level_by_programme(
    monkeypatch, tmp_path, capsys
):
    """independent carries no level, so the conference guard passes it; its
    programmes are each held to the home's level."""
    _mark(tmp_path, "d1")
    assert (
        _run(
            monkeypatch,
            tmp_path,
            "independent",
            season="2025",
            programmes="utrgv,harding",
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "harding (d2 in 2025)" in err and "utrgv" not in err
