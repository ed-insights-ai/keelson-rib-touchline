"""The direct collect driver: work homes, the cadence's change rules, landing."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import collect_direct as cd

SEASON = 2026


def git(home: Path, *args: str) -> str:
    return cd._git(home, *args)


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def board(
    stamp: str, slugs: list[str], missing: list[str] | None = None, extra: str = ""
) -> dict:
    return {
        "collected_at": stamp,
        "programmes": [{"slug": s, "note": extra} for s in slugs],
        "rosters": {s: {"players": []} for s in slugs},
        "teams": {s: {"players": [], "keepers": []} for s in slugs},
        "missing": missing or [],
    }


def make_home(root: Path, level: str = "d2") -> Path:
    home = root / "home"
    (home / "data" / "raw_html" / "a").mkdir(parents=True)
    (home / "touchline-data.yaml").write_text(
        f"kind: touchline-data\nversion: 1\nlevel: {level}\n", encoding="utf-8"
    )
    (home / ".gitignore").write_text("data/raw_html/\n", encoding="utf-8")
    (home / "data" / "raw_html" / "a" / f"{SEASON}-men-schedule.html").write_text(
        "<html/>"
    )
    write(home / "data" / "reference" / "membership.json", {"memberships": {}})
    write(
        home / "data" / "coverage.json",
        {
            "schema": "touchline.coverage/1",
            "updated_at": "t0",
            "cells": {
                f"{SEASON}/men/a/schedule": {"state": "complete"},
                f"{SEASON}/men/x/schedule": {"state": "complete"},
                "2019/men/a/schedule": {"state": "complete"},
            },
        },
    )
    for layer in cd.BOARD_DIRS:
        write(home / "data" / layer / f"{SEASON}-men-gac.json", board("t0", ["a", "b"]))
        write(home / "data" / layer / f"{SEASON}-men-sac.json", board("t0", ["x"]))
        write(home / "data" / layer / "2019-men-gac.json", board("t0", ["a"]))
    write(
        home / "data" / "errors" / f"collect-board-{SEASON}-men-gac.json",
        {"errors": []},
    )
    git_init(home)
    return home


def git_init(home: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(home)], check=True)
    git(home, "add", "-A")
    git(home, "commit", "-q", "-m", "seed")


def unit(
    conf: str = "GAC", slugs: tuple[str, ...] = ("a", "b"), job: str = "hosted"
) -> cd.Unit:
    return cd.Unit(conf, "men", list(slugs), False, job)


def fake_runner(writes: dict[str, dict], code: int = 0, coverage: dict | None = None):
    """A stand-in for collect-board: writes the given board files (by layer)
    and coverage cells, then exits ``code``."""

    def run(home, u, season, timeout, extra):
        for layer, payload in writes.items():
            write(home / "data" / layer / f"{season}-{u.gender}-{u.key}.json", payload)
        if coverage:
            manifest = json.loads((home / cd.COVERAGE).read_text())
            manifest["cells"].update(coverage)
            manifest["updated_at"] = "t1"
            (home / cd.COVERAGE).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            )
        return code, "collector output"

    return run


@pytest.fixture
def work(tmp_path: Path) -> Path:
    home = make_home(tmp_path)
    dest = tmp_path / "work"
    cd.make_work_home(home, dest, SEASON)
    return dest


def test_default_season_follows_the_fall_semester() -> None:
    assert cd.default_season(datetime(2026, 11, 23, tzinfo=timezone.utc)) == 2026
    assert cd.default_season(datetime(2027, 3, 1, tzinfo=timezone.utc)) == 2026
    assert cd.default_season(datetime(2027, 6, 1, tzinfo=timezone.utc)) == 2027


def test_work_home_carries_the_season_and_nothing_else(work: Path) -> None:
    files = git(work, "ls-files").split()
    assert f"data/fixtures/{SEASON}-men-gac.json" in files
    assert (
        f"data/fixtures/{SEASON}-men-sac.json" in files
    )  # siblings: identities read them
    assert f"data/errors/collect-board-{SEASON}-men-gac.json" in files
    assert "data/reference/membership.json" in files
    assert "data/coverage.json" in files
    assert not any(f.startswith("data/fixtures/2019") for f in files)
    assert not any("raw_html" in f for f in files)
    assert git(work, "status", "--porcelain") == ""
    # The fetch cache never becomes tracked in the work home.
    (work / "data" / "raw_html" / "a").mkdir(parents=True)
    (work / "data" / "raw_html" / "a" / "p.html").write_text("x")
    assert git(work, "status", "--porcelain") == ""


def test_work_home_refuses_a_directory_that_is_not_a_data_home(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    with pytest.raises(cd.DirectError, match="not a Touchline data home"):
        cd.make_work_home(tmp_path / "src", tmp_path / "dest", SEASON)


def test_stamp_only_churn_is_rolled_back_and_recorded_with_its_stamp(
    work: Path,
) -> None:
    writes = {layer: board("t1", ["a", "b"]) for layer in cd.BOARD_DIRS}
    r = cd.collect_unit(
        work,
        unit(),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner(
            writes,
            coverage={f"{SEASON}/men/a/schedule": {"state": "complete", "at": "t1"}},
        ),
    )
    assert r.result == cd.RESULT_NO_CHANGE
    assert r.collected_at == "t1"
    assert git(work, "status", "--porcelain") == ""
    assert len(cd.work_commits(work)) == 0


def test_a_real_change_is_one_commit(work: Path) -> None:
    writes = {"fixtures": board("t1", ["a", "b"], extra="new score")}
    r = cd.collect_unit(
        work, unit(), SEASON, accept_loss=False, timeout=60, runner=fake_runner(writes)
    )
    assert r.result == cd.RESULT_CHANGED
    assert r.collected_at == "t1"
    commits = cd.work_commits(work)
    assert len(commits) == 1
    assert (
        git(work, "log", "-1", "--format=%s").strip()
        == f"collect(shadow): GAC men {SEASON}"
    )


def test_a_new_board_file_is_a_change(work: Path) -> None:
    writes = {"fixtures": board("t1", ["q"])}
    r = cd.collect_unit(
        work,
        unit("NEWCONF", ("q",)),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner(writes),
    )
    assert r.result == cd.RESULT_CHANGED


def test_a_failed_collect_is_rolled_back(work: Path) -> None:
    writes = {"fixtures": board("t1", ["a"], extra="half written")}
    r = cd.collect_unit(
        work,
        unit(),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner(
            writes, code=1, coverage={"2026/men/a/roster": {"state": "x"}}
        ),
    )
    assert r.result == cd.RESULT_FAILED
    assert "exited 1" in (r.reason or "")
    assert r.collected_at is None
    assert git(work, "status", "--porcelain") == ""


def test_a_programme_that_went_missing_is_a_loss_and_rolled_back(work: Path) -> None:
    writes = {
        "fixtures": board("t1", ["a"], missing=["b"]),
        "rosters": board("t1", ["a"], missing=["b"]),
    }
    r = cd.collect_unit(
        work, unit(), SEASON, accept_loss=False, timeout=60, runner=fake_runner(writes)
    )
    assert r.result == cd.RESULT_LOST
    assert r.lost == ["fixtures:b", "rosters:b"]
    assert git(work, "status", "--porcelain") == ""


def test_a_gap_head_already_carried_is_not_a_loss(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write(
        home / "data" / "fixtures" / f"{SEASON}-men-gac.json",
        board("t0", ["a"], missing=["b"]),
    )
    git(home, "commit", "-qam", "b already missing")
    dest = tmp_path / "w"
    cd.make_work_home(home, dest, SEASON)
    writes = {"fixtures": board("t1", ["a"], missing=["b"], extra="moved")}
    r = cd.collect_unit(
        dest, unit(), SEASON, accept_loss=False, timeout=60, runner=fake_runner(writes)
    )
    assert r.result == cd.RESULT_CHANGED


def test_an_accepted_loss_lands(work: Path) -> None:
    writes = {"fixtures": board("t1", ["a"], missing=["b"])}
    r = cd.collect_unit(
        work, unit(), SEASON, accept_loss=True, timeout=60, runner=fake_runner(writes)
    )
    assert r.result == cd.RESULT_CHANGED
    assert r.lost == ["fixtures:b"]


def test_route_sends_any_prestosports_member_to_the_presto_runner() -> None:
    table = {("a", "men"): "sidearm", ("p", "men"): "prestosports", ("w", "men"): "wmt"}
    assert cd.route(["a", "w"], "men", table) == cd.JOB_HOSTED
    assert cd.route(["a", "p"], "men", table) == cd.JOB_PRESTO
    assert cd.route(["p"], "women", table) == cd.JOB_HOSTED  # another gender's stanza


def test_two_jobs_land_different_units_without_losing_either(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    w1, w2 = tmp_path / "w1", tmp_path / "w2"
    cd.make_work_home(home, w1, SEASON)
    cd.make_work_home(home, w2, SEASON)
    cd.collect_unit(
        w1,
        unit("GAC"),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner(
            {"fixtures": board("t1", ["a", "b"], extra="gac moved")},
            coverage={f"{SEASON}/men/a/schedule": {"state": "complete", "at": "t1"}},
        ),
    )
    cd.collect_unit(
        w2,
        unit("SAC", ("x",), job="presto"),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner(
            {"fixtures": board("t2", ["x"], extra="sac moved")},
            coverage={f"{SEASON}/men/x/schedule": {"state": "empty", "at": "t2"}},
        ),
    )
    assert cd.replay(w1, home) == [f"collect(shadow): GAC men {SEASON}"]
    assert cd.replay(w2, home) == [f"collect(shadow): SAC men {SEASON}"]
    cells = json.loads((home / cd.COVERAGE).read_text())["cells"]
    assert cells[f"{SEASON}/men/a/schedule"]["at"] == "t1"
    assert cells[f"{SEASON}/men/x/schedule"]["at"] == "t2"
    assert "2019/men/a/schedule" in cells  # cells outside the work home survive
    gac = json.loads((home / "data/fixtures" / f"{SEASON}-men-gac.json").read_text())
    assert gac["programmes"][0]["note"] == "gac moved"
    # Older seasons, never in the work home, are untouched.
    assert (home / "data/fixtures/2019-men-gac.json").is_file()
    # Replaying again is a no-op: landing is idempotent.
    assert cd.replay(w1, home) == []


def test_land_pushes_and_replays_when_the_branch_moved(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(home), str(remote)], check=True)
    git(remote, "branch", "shadow", "main")
    clone_a, clone_b = tmp_path / "a", tmp_path / "b"
    for clone in (clone_a, clone_b):
        subprocess.run(
            ["git", "clone", "-q", "-b", "shadow", str(remote), str(clone)], check=True
        )
    w1, w2 = tmp_path / "w1", tmp_path / "w2"
    cd.make_work_home(clone_a, w1, SEASON)
    cd.make_work_home(clone_b, w2, SEASON)
    cd.collect_unit(
        w1,
        unit("GAC"),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner({"stats": board("t1", ["a", "b"], extra="g")}),
    )
    cd.collect_unit(
        w2,
        unit("SAC", ("x",)),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner({"stats": board("t1", ["x"], extra="s")}),
    )
    made_b, _ = cd.land(
        w2, clone_b, push=True, remote="origin", branch="shadow", retries=2
    )
    assert made_b == [f"collect(shadow): SAC men {SEASON}"]
    # clone_a is now behind: its push is refused, it refetches and replays.
    made_a, head = cd.land(
        w1, clone_a, push=True, remote="origin", branch="shadow", retries=2
    )
    assert made_a == [f"collect(shadow): GAC men {SEASON}"]
    log = git(remote, "log", "--format=%s", "shadow").splitlines()
    assert log[:2] == [
        f"collect(shadow): GAC men {SEASON}",
        f"collect(shadow): SAC men {SEASON}",
    ]
    assert git(remote, "rev-parse", "shadow").strip() == head
    assert (
        git(remote, "rev-parse", "main").strip()
        == git(home, "rev-parse", "HEAD").strip()
    )


def test_skipped_units_carry_the_reason() -> None:
    [r] = cd.skipped_results([unit("SAC", ("p",), job="presto")], "no presto runner")
    assert (r.result, r.reason, r.job) == (
        cd.RESULT_SKIPPED,
        "no presto runner",
        "presto",
    )


def test_a_resolver_fault_is_not_an_empty_division(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(rib, *args):
        return subprocess.CompletedProcess(args, 1, "", fake.stderr)

    monkeypatch.setattr(cd, "_resolve", fake)
    fake.stderr = "no d3 conference has a men member in 2026 (known conferences: A10)"
    assert cd.resolve_conferences(Path("."), "men", "d3", SEASON) == ([], fake.stderr)
    fake.stderr = "membership.json: Unexpected token } in JSON at position 12"
    with pytest.raises(
        cd.DirectError, match="cannot resolve the d2 men 2026 conferences"
    ):
        cd.resolve_conferences(Path("."), "men", "d2", SEASON)


def test_replaying_cells_already_landed_leaves_the_manifest_alone(
    tmp_path: Path,
) -> None:
    home = make_home(tmp_path)
    work = tmp_path / "w"
    cd.make_work_home(home, work, SEASON)
    cd.collect_unit(
        work,
        unit("GAC"),
        SEASON,
        accept_loss=False,
        timeout=60,
        runner=fake_runner(
            {"fixtures": board("t1", ["a", "b"], extra="moved")},
            coverage={f"{SEASON}/men/a/schedule": {"state": "complete", "at": "t1"}},
        ),
    )
    assert cd.replay(work, home)
    # Another job lands later and moves updated_at on.
    manifest = json.loads((home / cd.COVERAGE).read_text())
    manifest["updated_at"] = "t9"
    manifest["cells"][f"{SEASON}/men/x/schedule"] = {"state": "empty", "at": "t9"}
    write(home / cd.COVERAGE, manifest)
    git(home, "commit", "-qam", "other job")
    before = (home / cd.COVERAGE).read_text()
    assert cd.replay(work, home) == []
    assert (home / cd.COVERAGE).read_text() == before
