"""``check-player-identity`` measures a data home's ``player_ref`` coverage
per file and never dies: a home with no matches directory, or none it can
read, is an alarm that says the check did not run."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_player_identity as check
from src.paths import data_root


def _home(tmp_path: Path) -> Path:
    for kind in ("rosters", "matches", "fixtures"):
        (tmp_path / "data" / kind).mkdir(parents=True)
    host = "https://alphaathletics.example"
    (tmp_path / "data" / "rosters" / "2026-men-x.json").write_text(
        json.dumps(
            {
                "rosters": {
                    "alpha": {
                        "programme": "alpha",
                        "source_url": f"{host}/sports/mens-soccer/roster/2026",
                        "players": [
                            {
                                "name": "Marcus Reed",
                                "number": "22",
                                "source_url": f"{host}/sports/mens-soccer/roster/marcus-reed/106",
                            }
                        ],
                    }
                }
            }
        )
    )
    fixture = {
        "id": "sidearm:beta:1",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    (tmp_path / "data" / "fixtures" / "2026-men-x.json").write_text(
        json.dumps({"fixtures": [fixture]})
    )
    box = {
        "source_url": "https://betasports.example/x/boxscore/1",
        "home_index": 0,
        "teams": [
            {
                "name": "Beta",
                "players": [{"name": "Tom Keeper", "player_id": "9"}],
                "keepers": [],
            },
            {
                "name": "Alpha",
                "players": [
                    {"name": "Marcus Reed", "number": "22"},
                    {"name": "No Body"},
                ],
                "keepers": [],
            },
        ],
    }
    (tmp_path / "data" / "matches" / "2026-men-x.json").write_text(
        json.dumps(
            {"schema": "touchline.matches/1", "matches": {"sidearm:beta:1": box}}
        )
    )
    return tmp_path


def test_sweep_measures_each_file_by_route_and_names_legacy(tmp_path: Path) -> None:
    result = check.sweep(_home(tmp_path))
    counts = result["counts"]
    assert isinstance(counts, dict)
    assert counts["files"] == 1
    assert counts["owner_page"] == 1
    assert counts["opponent_roster"] == 1
    assert counts["opponent_key"] == 1
    assert counts["miss_not_on_roster"] == 1
    assert result["legacy"] == ["2026-men-x.json"]
    (line,) = result["lines"]  # type: ignore[misc]
    assert "opponent 2 lines: roster 1 · key 1" in line
    assert line.endswith("[legacy file, no refs stored]")


def test_main_prints_a_verdict_and_alarms_when_it_cannot_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    assert data_root() == tmp_path.resolve()
    assert check.main() == 0
    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert verdict["verdict"] == "alarm"
    assert verdict["headline"].startswith("CHECK DID NOT RUN")
    _home(tmp_path)
    assert check.main() == 0
    out = capsys.readouterr().out.strip().splitlines()
    verdict = json.loads(out[-1])
    assert verdict["check"] == "player-identity"
    # A legacy file is a warning, not a failure: the next collect rewrites it.
    assert verdict["verdict"] == "warn"
    assert "1 of 1 files still touchline.matches/1" in verdict["headline"]
