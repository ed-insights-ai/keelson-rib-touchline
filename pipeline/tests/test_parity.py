"""check-parity: two data homes, record by record.

Every case starts from the checked-in sample homes (samples/), copied to a
temp dir and edited the way a later or a broken collect would differ.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import check_parity
from src import parity

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
D2 = SAMPLES / "d2-soccer"
FIX = "data/fixtures/2026-men-gac.json"
MAT = "data/matches/2026-men-gac.json"
ROS = "data/rosters/2026-men-gac.json"
STA = "data/stats/2026-men-gac.json"
COV = "data/coverage.json"
SEASON_FILES = [FIX, MAT, ROS, STA]


def load(home: Path, rel: str) -> Any:
    return json.loads((home / rel).read_text())


def save(home: Path, rel: str, doc: Any) -> None:
    (home / rel).write_text(json.dumps(doc, indent=2))


def stamp(home: Path, when: dt.datetime, files: list[str] = SEASON_FILES) -> None:
    for rel in files:
        doc = load(home, rel)
        doc["collected_at"] = when.isoformat()
        save(home, rel, doc)


@pytest.fixture
def homes(tmp_path: Path) -> tuple[Path, Path]:
    e, a = tmp_path / "expected", tmp_path / "actual"
    shutil.copytree(D2, e)
    shutil.copytree(D2, a)
    return e, a


def run(e: Path, a: Path, **kw: Any) -> parity.Result:
    return parity.compare(parity.DirTree(e), parity.DirTree(a), **kw)


def final_fixture(home: Path) -> dict[str, Any]:
    """A played fixture with a box score, the latest one in the file."""
    matches = load(home, MAT)["matches"]
    rows = [
        f
        for f in load(home, FIX)["fixtures"]
        if f["status"] == "final" and f["id"] in matches
    ]
    return max(rows, key=lambda f: f["date"])


def at(day: str, hours: int = 0) -> dt.datetime:
    return dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC) + dt.timedelta(
        hours=hours
    )


def only(result: parity.Result, layer: str) -> list[parity.Finding]:
    return [f for f in result.findings if f.layer == layer]


# -- the samples against themselves ----------------------------------------


@pytest.mark.parametrize("home", ["d1-soccer", "d2-soccer"])
def test_a_sample_against_itself_matches_every_record(home: str) -> None:
    tree = parity.DirTree(SAMPLES / home)
    result = parity.compare(tree, tree, compare_inherited=True)
    doc = result.to_json()
    assert doc["verdict"] == "pass", doc["errors"]
    assert doc["totals"]["timing"] == doc["totals"]["disagreement"] == 0
    for layer in ("fixtures", "matches", "rosters", "stats", "coverage", "reference"):
        assert doc["layers"][layer]["match"] > 0, layer
    assert doc["not_compared"] == [
        {
            "path": "data/sample.json",
            "count": 1,
            "reason": parity.NOT_COMPARED_FILES["sample.json"],
        }
    ]


def test_identical_stamps_are_unproven_not_matches(homes: tuple[Path, Path]) -> None:
    e, a = homes
    result = run(e, a)
    doc = result.to_json()
    assert doc["verdict"] == "pass"
    assert doc["complete"] is False
    assert doc["files"]["unproven"] == 8  # every season file
    assert doc["coverage_cells"]["unproven"] == len(load(e, COV)["cells"])
    assert doc["layers"].get("fixtures") is None  # nothing was compared
    gated = run(e, a, require_complete=True)
    assert gated.verdict == "fail"


# -- timing against disagreement --------------------------------------------


def test_a_game_finished_after_the_earlier_collect_is_timing(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    game = final_fixture(e)
    doc = load(e, FIX)
    row = next(f for f in doc["fixtures"] if f["id"] == game["id"])
    row["status"] = "scheduled"
    row.pop("home_score", None)
    row.pop("away_score", None)
    save(e, FIX, doc)
    m = load(e, MAT)
    del m["matches"][game["id"]]
    save(e, MAT, m)
    stamp(e, at(game["date"], 12))
    stamp(a, at(game["date"], 40))
    result = run(e, a, compare_inherited=True)
    fx = only(result, "fixtures")
    assert [(f.key, f.cls, f.kind) for f in fx] == [(game["id"], "timing", "changed")]
    assert "scheduled then final" in fx[0].reason
    mx = only(result, "matches")
    assert [(f.key, f.cls, f.kind) for f in mx] == [(game["id"], "timing", "added")]
    assert result.verdict == "pass"


def test_the_same_change_in_the_other_direction_disagrees(
    homes: tuple[Path, Path],
) -> None:
    """Final on the earlier side, scheduled on the later: a regression."""
    e, a = homes
    game = final_fixture(e)
    doc = load(a, FIX)
    row = next(f for f in doc["fixtures"] if f["id"] == game["id"])
    row["status"] = "scheduled"
    save(a, FIX, doc)
    m = load(a, MAT)
    del m["matches"][game["id"]]
    save(a, MAT, m)
    stamp(e, at(game["date"], 12))
    stamp(a, at(game["date"], 40))
    result = run(e, a)
    assert result.verdict == "fail"
    reasons = {f.layer: f.reason for f in result.disagreements}
    assert "went backwards" in reasons["fixtures"]
    assert "vanished" in reasons["matches"]


def test_an_old_game_that_differs_disagrees_whatever_the_gap(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    game = final_fixture(e)
    doc = load(a, FIX)
    row = next(f for f in doc["fixtures"] if f["id"] == game["id"])
    row["home_score"] = row["home_score"] + 1
    save(a, FIX, doc)
    stamp(e, at(game["date"], 24 * 10))
    stamp(a, at(game["date"], 24 * 11))
    result = run(e, a)
    [f] = result.disagreements
    assert f.key == game["id"]
    assert f.date == game["date"]
    assert f.fields == [
        {
            "path": "home_score",
            "expected": game["home_score"],
            "actual": game["home_score"] + 1,
        }
    ]
    assert "more than 3 days before" in f.reason
    # A wider window lets a recent revision through, as timing.
    assert run(e, a, lag_days=12).verdict == "pass"


def test_simultaneous_collections_that_differ_disagree(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    game = final_fixture(e)
    doc = load(a, FIX)
    next(f for f in doc["fixtures"] if f["id"] == game["id"])["venue"] = "Elsewhere"
    save(a, FIX, doc)
    stamp(e, at(game["date"], 2))
    stamp(a, at(game["date"], 2) + dt.timedelta(seconds=30))
    [f] = run(e, a).disagreements
    assert "same time" in f.reason


def test_a_box_score_with_no_dated_fixture_cannot_be_timing(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    m = load(a, MAT)
    m["matches"]["sidearm:nowhere:1"] = next(iter(m["matches"].values()))
    save(a, MAT, m)
    stamp(e, at("2026-11-01"))
    stamp(a, at("2026-11-02"))
    [f] = run(e, a).disagreements
    assert f.key == "sidearm:nowhere:1"
    assert "no fixture" in f.reason


def test_roster_differences_always_disagree(homes: tuple[Path, Path]) -> None:
    e, a = homes
    doc = load(a, ROS)
    slug = next(iter(doc["rosters"]))
    doc["rosters"][slug]["players"][0]["height"] = "7'0\""
    save(a, ROS, doc)
    stamp(e, at("2026-11-01"))
    stamp(a, at("2026-11-02"))
    [f] = run(e, a, lag_days=100).disagreements
    assert (f.layer, f.key) == ("rosters", slug)
    assert f.fields[0]["path"].endswith(".height")
    assert "re-collect both sides together" in f.reason


def _stats_case(homes: tuple[Path, Path], bump: int) -> parity.Result:
    e, a = homes
    game = final_fixture(e)
    slug = game["home"]
    doc = load(a, STA)
    if slug not in doc["teams"]:
        slug = game["away"]
    player = doc["teams"][slug]["players"][0]
    player["minutes"] = player["minutes"] + bump
    save(a, STA, doc)
    stamp(e, at(game["date"], -6))
    stamp(a, at(game["date"], 30))
    return run(e, a)


def test_season_totals_that_grew_with_a_game_are_timing(
    homes: tuple[Path, Path],
) -> None:
    result = _stats_case(homes, +90)
    [f] = only(result, "stats")
    assert f.cls == "timing", f.reason
    assert result.verdict == "pass"


def test_season_totals_that_went_down_disagree(homes: tuple[Path, Path]) -> None:
    result = _stats_case(homes, -90)
    [f] = only(result, "stats")
    assert f.cls == "disagreement"
    assert "minutes went down" in f.reason


def test_totals_that_moved_with_no_game_between_disagree(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    doc = load(a, STA)
    slug = next(iter(doc["teams"]))
    doc["teams"][slug]["players"][0]["goals"] += 1
    save(a, STA, doc)
    stamp(e, at("2026-12-20"))
    stamp(a, at("2026-12-21"))
    [f] = only(run(e, a), "stats")
    assert f.cls == "disagreement"
    assert "no game" in f.reason


def test_a_coverage_cell_that_lost_its_data_disagrees(homes: tuple[Path, Path]) -> None:
    e, a = homes
    doc = load(a, COV)
    key, cell = next(
        (k, c)
        for k, c in doc["cells"].items()
        if c["state"] == "complete" and c["layer"] == "matches"
    )
    cell.update(
        state="unavailable",
        reason="failed to fetch",
        confirmed_at="2099-01-01T00:00:00+00:00",
    )
    save(a, COV, doc)
    result = run(e, a)
    [f] = only(result, "coverage")
    assert (f.key, f.cls) == (key, "disagreement")
    assert "lost what the earlier one had" in f.reason


def test_a_header_gap_on_one_side_disagrees(homes: tuple[Path, Path]) -> None:
    e, a = homes
    doc = load(a, FIX)
    doc["missing"] = ["harding"]
    save(a, FIX, doc)
    stamp(e, at("2026-11-01"))
    stamp(a, at("2026-11-02"))
    [f] = run(e, a).disagreements
    assert (f.key, f.fields[0]["path"]) == ("<header>", "missing")


def test_a_box_score_that_differs_only_in_player_ref_says_so(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    game = final_fixture(e)
    m = load(a, MAT)
    m["matches"][game["id"]]["teams"][0]["players"][0]["player_ref"] = {
        "id": "x:y:1",
        "source": "key",
    }
    save(a, MAT, m)
    stamp(e, at(game["date"], 24 * 30))
    stamp(a, at(game["date"], 24 * 31))
    [f] = run(e, a).disagreements
    assert "only player_ref differs" in f.reason


def test_a_schema_version_change_is_named_and_records_still_compared(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    m = parity._strip_player_ref(load(e, MAT))
    m["schema"] = "touchline.matches/1"
    save(e, MAT, m)
    stamp(e, at("2026-11-01"))
    stamp(a, at("2026-11-02"))
    result = run(e, a)
    assert [(f.key, f.cls) for f in result.findings] == [("<schema>", "disagreement")]
    assert result.counts["matches"]["match"] > 80


# -- run records -------------------------------------------------------------


def _record(path: Path, result: str, when: dt.datetime | None = None) -> Path:
    unit: dict[str, Any] = {
        "conference": "GAC",
        "gender": "men",
        "job": "hosted",
        "result": result,
    }
    if when:
        unit["collected_at"] = when.isoformat()
    path.write_text(
        json.dumps(
            {
                "schema": "touchline.collect-record/1",
                "division": "d2",
                "season": 2026,
                "units": [unit],
            }
        )
    )
    return path


def test_a_record_vouches_for_a_unit_with_the_inherited_stamp(
    homes: tuple[Path, Path], tmp_path: Path
) -> None:
    e, a = homes
    rec = parity.load_records(
        [_record(tmp_path / "r.json", "no-change", at("2026-11-21"))]
    )
    result = run(e, a, records=rec)
    doc = result.to_json()
    assert doc["files"]["unproven"] == 4  # the women's files only
    assert doc["layers"]["fixtures"]["match"] > 0
    # Men's GAC cells are vouched for too; the women's stay unproven.
    assert all("/women/" in u["path"] for u in result.unproven if "#" in u["path"])


def test_a_skipped_unit_is_excluded_not_counted(
    homes: tuple[Path, Path], tmp_path: Path
) -> None:
    e, a = homes
    doc = load(a, FIX)
    doc["fixtures"] = []
    save(a, FIX, doc)
    rec = parity.load_records([_record(tmp_path / "r.json", "skipped")])
    result = run(e, a, records=rec)
    assert result.verdict == "pass"
    assert {x["path"] for x in result.excluded if "#" not in x["path"]} == set(
        SEASON_FILES
    )
    assert run(e, a, records=rec, require_complete=True).verdict == "fail"


def test_a_record_with_another_schema_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "r.json"
    bad.write_text(json.dumps({"schema": "nope", "units": []}))
    with pytest.raises(parity.ParityError):
        parity.load_records([bad])


# -- what it cannot compare --------------------------------------------------


def test_an_unknown_schema_is_an_error(homes: tuple[Path, Path]) -> None:
    e, a = homes
    doc = load(a, ROS)
    doc["schema"] = "touchline.rosters/9"
    save(a, ROS, doc)
    stamp(a, at("2026-11-02"))
    result = run(e, a)
    assert result.verdict == "error"
    assert "touchline.rosters/9" in result.errors[0]


def test_a_file_with_no_rule_is_an_error(homes: tuple[Path, Path]) -> None:
    e, a = homes
    (a / "data" / "mystery.json").write_text("{}")
    result = run(e, a)
    assert result.verdict == "error"
    assert result.errors == ["data/mystery.json: no parity rule for this file"]


def test_known_side_directories_are_listed_not_compared(
    homes: tuple[Path, Path],
) -> None:
    e, a = homes
    for home in (e, a):
        (home / "data" / "errors").mkdir()
        (home / "data" / "errors" / "collect-board-2026-men-gac.json").write_text("{}")
    (a / "data" / "errors" / "collect-board-2026-women-gac.json").write_text("{}")
    (a / "data" / "stats" / "stats").symlink_to("/nowhere")
    result = run(e, a)
    assert {
        "path": "data/errors/",
        "count": 2,
        "reason": parity.NOT_COMPARED_DIRS["errors"],
    } in result.not_compared
    assert any(n["path"] == "data/stats/stats" for n in result.not_compared)
    assert result.verdict == "pass"


def test_homes_at_different_levels_are_an_error(homes: tuple[Path, Path]) -> None:
    e, a = homes
    marker = a / "touchline-data.yaml"
    marker.write_text(marker.read_text().replace("level: d2", "level: d1"))
    assert run(e, a).verdict == "error"


# -- git refs and the CLI ----------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_git_refs_are_read_without_a_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "home"
    shutil.copytree(D2, repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "main")
    _git(repo, "checkout", "-qb", "shadow")
    game = final_fixture(repo)
    doc = load(repo, FIX)
    next(f for f in doc["fixtures"] if f["id"] == game["id"])["away_score"] = 99
    save(repo, FIX, doc)
    stamp(repo, at("2026-11-21"))
    _git(repo, "commit", "-qam", "shadow")
    _git(repo, "checkout", "-q", "main")

    out = tmp_path / "parity.json"
    code = check_parity.main(
        [
            f"{repo}@main",
            f"{repo}@shadow",
            "--json",
            str(out),
            "--report",
            str(tmp_path / "r.md"),
        ]
    )
    assert code == 1
    doc = json.loads(out.read_text())
    assert doc["schema"] == "touchline.parity/1"
    assert doc["verdict"] == "fail"
    [f] = [x for x in doc["findings"] if x["class"] == "disagreement"]
    assert (f["key"], f["fields"][0]["path"]) == (game["id"], "away_score")
    report = (tmp_path / "r.md").read_text()
    assert report.startswith("# Data-home parity: FAIL")
    assert game["id"] in report
    # The working tree was never touched.
    assert _git(repo, "status", "--porcelain") == ""


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        check_parity.main(
            [
                str(D2),
                str(D2),
                "--compare-inherited",
                "--report",
                str(tmp_path / "r.md"),
            ]
        )
        == 0
    )
    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert verdict["check"] == "parity" and verdict["verdict"] == "pass"
    assert (
        check_parity.main(
            [str(D2), str(D2), "--require-complete", "--json", str(tmp_path / "p.json")]
        )
        == 1
    )
    assert check_parity.main([str(D2), str(tmp_path / "nowhere")]) == 2
    assert (
        json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"]
        == "error"
    )


def test_deep_diff_tells_true_from_one() -> None:
    assert list(parity.deep_diff({"a": True}, {"a": 1})) == [("a", True, 1)]
    assert list(parity.deep_diff([1, 2], [1, 2, 3])) == [("", [1, 2], [1, 2, 3])]
    assert (
        list(parity.deep_diff(copy.deepcopy({"x": [{"y": 1}]}), {"x": [{"y": 1}]}))
        == []
    )


def test_two_records_naming_one_unit_keep_the_collect_that_landed(
    tmp_path: Path,
) -> None:
    hosted = _record(tmp_path / "hosted.json", "changed", at("2026-11-21"))
    presto = _record(tmp_path / "presto.json", "skipped")
    for order in ([hosted, presto], [presto, hosted]):
        [unit] = parity.load_records(order).values()
        assert unit.result == "changed"
    later = _record(tmp_path / "later.json", "no-change", at("2026-11-22"))
    [unit] = parity.load_records([later, hosted]).values()
    assert unit.collected_at == at("2026-11-22")
