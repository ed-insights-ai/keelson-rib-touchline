"""snapshot/agree.py gates a release on the site and the desk showing the same
program figures, and only reports player-line differences."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "snapshot_agree", Path(__file__).resolve().parents[2] / "snapshot" / "agree.py"
)
agree = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agree)

KEY = ("d2", "men", 2026)
RECORD = {
    "won": 10,
    "drawn": 2,
    "lost": 5,
    "goalsFor": 30,
    "goalsAgainst": 18,
    "played": 17,
}
TEAM_ROW = {
    "kind": "team",
    "division": "d2",
    "gender": "men",
    "season": 2026,
    "team": "rogers-state",
    "won": 10,
    "drawn": 2,
    "lost": 5,
    "goals_for": 30,
    "goals_against": 18,
    "played": 17,
}
PLAYER = {
    "name": "Sam Field",
    "gp": 17,
    "gs": 16,
    "goals": 7,
    "assists": 3,
    "shots": 40,
}
KEEPER = {
    "name": "Kim Keeper",
    "gp": None,
    "keeper": {"gp": 17, "saves": 60, "goals_against": 18},
}
PLAYER_ROWS = [
    {
        "kind": "player",
        "division": "d2",
        "gender": "men",
        "season": 2026,
        "team": "rogers-state",
        "name": "Sam Field",
        "gp": 17,
        "gs": 16,
        "goals": 7,
        "assists": 3,
        "shots": 40,
        "k_gp": None,
        "k_saves": None,
        "k_ga": None,
    },
    {
        "kind": "player",
        "division": "d2",
        "gender": "men",
        "season": 2026,
        "team": "rogers-state",
        "name": "Kim Keeper",
        "gp": 17,
        "gs": 17,
        "goals": 0,
        "assists": 0,
        "shots": 0,
        "k_gp": 17,
        "k_saves": 60,
        "k_ga": 18,
    },
]


def _figures(record=RECORD, players=(PLAYER, KEEPER), programmes=True) -> dict:
    progs = (
        {
            "rogers-state": {
                "name": "Rogers State",
                "record": dict(record),
                "players": [copy.deepcopy(p) for p in players],
            }
        }
        if programmes
        else {}
    )
    return {
        "schema": "touchline.figures/1",
        "division": "d2",
        "gender": "men",
        "season": 2026,
        "conferences": {"gac": {"name": "GAC", "programmes": progs}},
    }


def _desk(team_rows=(TEAM_ROW,), player_rows=PLAYER_ROWS, extra_rows=()) -> dict:
    return {
        "schema": "touchline.desk-figures/2",
        "rows": [
            *map(dict, team_rows),
            *map(dict, player_rows),
            *map(dict, extra_rows),
        ],
    }


EXTRA = {
    "kind": "extra",
    "division": "d2",
    "gender": "men",
    "season": 2026,
    "team": "rogers-state",
    "goals_for": 2,
    "goals_against": 1,
    "date": "2026-08-20",
    "opponent": "newman",
    "why": "not on its own schedule",
}


def _run(tmp_path: Path, desk: dict, *figures: dict) -> int:
    d = tmp_path / "desk.json"
    d.write_text(json.dumps(desk))
    paths = []
    for i, f in enumerate(figures):
        p = tmp_path / f"fig-{i}.json"
        p.write_text(json.dumps(f))
        paths.append(str(p))
    return agree.main(["agree.py", str(d), *paths])


def test_matching_records_and_lines_pass(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _desk(), _figures()) == 0
    out = capsys.readouterr().out
    assert "Every program's record, goals and games agree." in out
    assert "player-line difference" not in out


@pytest.mark.parametrize("field", list(RECORD))
def test_each_team_field_mismatch_fails(tmp_path: Path, capsys, field: str) -> None:
    record = {**RECORD, field: RECORD[field] + 1}
    assert _run(tmp_path, _desk(), _figures(record=record)) == 1
    assert f"rogers-state) {field}: site" in capsys.readouterr().out


def test_a_missing_desk_record_is_zero_and_fails(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _desk(team_rows=()), _figures()) == 1
    assert "won: site 10, desk 0" in capsys.readouterr().out


def test_a_program_with_no_results_and_no_desk_row_passes(tmp_path: Path) -> None:
    record = {k: 0 for k in RECORD}
    assert _run(tmp_path, _desk(team_rows=()), _figures(record=record)) == 0


def test_a_build_with_no_programs_fails(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _desk(), _figures(programmes=False)) == 1
    assert "the site's figures list no programs" in capsys.readouterr().out


def test_player_differences_are_reported_not_gated(tmp_path: Path, capsys) -> None:
    player = {**PLAYER, "goals": 8}
    keeper = copy.deepcopy(KEEPER)
    keeper["keeper"]["saves"] = 61
    assert _run(tmp_path, _desk(), _figures(players=(player, keeper))) == 0
    out = capsys.readouterr().out
    assert "Sam Field goals: site 8, desk 7" in out
    assert "Kim Keeper keeper saves: site 61, desk 60" in out


def test_a_keeper_only_line_is_compared(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _desk(player_rows=PLAYER_ROWS[:1]), _figures()) == 0
    assert "Kim Keeper: the desk has 0 lines" in capsys.readouterr().out


def test_a_roster_name_without_figures_is_skipped(tmp_path: Path, capsys) -> None:
    bare = {"name": "No Stats", "gp": None, "keeper": None}
    assert _run(tmp_path, _desk(), _figures(players=(PLAYER, KEEPER, bare))) == 0
    assert "No Stats" not in capsys.readouterr().out


@pytest.mark.parametrize("which", ["desk", "figures"])
def test_a_document_of_the_wrong_schema_is_refused(tmp_path: Path, which: str) -> None:
    desk, figures = _desk(), _figures()
    (desk if which == "desk" else figures)["schema"] = "something/1"
    with pytest.raises(SystemExit):
        _run(tmp_path, desk, figures)


def test_games_beyond_the_team_page_are_reported_not_gated(
    tmp_path: Path, capsys
) -> None:
    unlisted = {**EXTRA, "team": "someone-else"}
    assert _run(tmp_path, _desk(extra_rows=(EXTRA, unlisted)), _figures()) == 0
    out = capsys.readouterr().out
    assert "Every program's record, goals and games agree." in out
    assert "1 game(s) the desk counts that the team pages leave out" in out
    assert (
        "Rogers State (rogers-state) 2026-08-20 v newman 2-1: not on its own schedule"
        in out
    )
