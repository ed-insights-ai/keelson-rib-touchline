"""Parallel fetch: across hosts, never against one — and order-blind outputs.

Three contracts under test.  Politeness: a worker pool fans programme and
box-score fetches out across hosts while a per-host gate guarantees no host
ever sees two concurrent requests, politely spaced.  Determinism: every
payload, coverage cell, and page-state sidecar comes out byte-identical
whatever order the fetches complete in, because all order-dependent assembly
is serialized in the main thread over the gathered results in request order.
Isolation: one hung site becomes its own named gap while the rest of the run
completes — and checkpoints what it confirmed to disk, so a run killed at
the node budget keeps its progress instead of writing nothing.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import requests

from scripts import collect_board
from src import page_state
from src.config import SchoolConfig
from src.fetch_pool import GatedSession, HostGate, host_of
from src.sidearm_live import (
    DEFAULT_LAYERS,
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    STATE_UNAVAILABLE,
    LayerOutcome,
    LiveCollectionError,
    ProgrammeCollection,
    programme_slug,
)

_FROZEN = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


class _FrozenDatetime:
    """Freeze collect()'s single ``now`` capture so two runs can be diffed."""

    @staticmethod
    def now(tz: object = None) -> datetime:
        del tz
        return _FROZEN


# ---------------------------------------------------------------------------
# The politeness contract: at most one in-flight request per host, politely
# spaced — while different hosts genuinely overlap.
# ---------------------------------------------------------------------------


def test_host_gate_caps_each_host_at_one_while_hosts_overlap() -> None:
    gate = HostGate(spacing=0)
    bookkeeping = threading.Lock()
    active: dict[str, int] = {}
    peak: dict[str, int] = {}
    tally = {"active": 0, "peak": 0}

    def request(host: str) -> None:
        with gate.slot(host):
            with bookkeeping:
                active[host] = active.get(host, 0) + 1
                tally["active"] += 1
                peak[host] = max(peak.get(host, 0), active[host])
                tally["peak"] = max(tally["peak"], tally["active"])
            time.sleep(0.02)
            with bookkeeping:
                active[host] -= 1
                tally["active"] -= 1

    threads = [
        threading.Thread(target=request, args=(host,))
        for host in ("a.example", "b.example") * 4
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == {"a.example": 1, "b.example": 1}
    # The parallelism is real — it just never lands on one host.
    assert tally["peak"] >= 2


def test_host_gate_spaces_consecutive_requests_to_one_host() -> None:
    clock = SimpleNamespace(value=0.0)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(round(seconds, 6))
        clock.value += seconds

    gate = HostGate(spacing=0.2, clock=lambda: clock.value, sleep=sleep)
    with gate.slot("a.example"):
        pass  # released at t=0
    clock.value = 0.05
    with gate.slot("a.example"):
        pass  # 50ms later: politeness still owes 150ms
    with gate.slot("b.example"):
        pass  # a different host owes nothing

    assert sleeps == [0.15]


def test_gated_session_holds_the_slot_for_the_whole_request(monkeypatch) -> None:
    gate = HostGate(spacing=0)
    observed: list[tuple[str, bool]] = []

    def fake_request(self, method, url, *args, **kwargs):
        del self, method, args, kwargs
        lock = gate._lock_for(host_of(url))
        acquired = lock.acquire(blocking=False)
        if acquired:  # pragma: no cover — would mean the gate was not held
            lock.release()
        observed.append((str(url), not acquired))
        return SimpleNamespace(status_code=200, url=url, text="", headers={})

    monkeypatch.setattr(requests.Session, "request", fake_request)
    session = GatedSession(gate)
    session.get("https://a.example/sports/mens-soccer/schedule/2026")

    assert observed == [("https://a.example/sports/mens-soccer/schedule/2026", True)]


# ---------------------------------------------------------------------------
# Determinism: serial and parallel runs — under adversarial completion
# orders — produce byte-identical payloads, cells, errors, and coverage.
# ---------------------------------------------------------------------------

_NAMES = ["Alpha", "Bravo", "Charlie", "Delta"]


def _schools(count: int = 4) -> list[SchoolConfig]:
    return [
        SchoolConfig(
            name=name,
            abbreviation=name[:2].upper(),
            conference="GAC",
            prefix="",
            base_url=f"https://{name.lower()}.example/sports/mens-soccer",
            enabled=True,
        )
        for name in _NAMES[:count]
    ]


def _published_rows(slug: str, slugs: list[str]) -> list[dict[str, object]]:
    """Each programme publishes its own home game AND its own row for the
    away game — the same physical matches land on two schedule pages, so the
    dedupe's winner selection is exercised under both completion orders."""
    index = slugs.index(slug)
    opponent = slugs[(index + 1) % len(slugs)]
    previous = slugs[(index - 1) % len(slugs)]
    home_game: dict[str, object] = {
        "id": f"sidearm:{slug}:{index + 1}",
        "date": f"2026-09-0{index + 1}",
        "home": slug,
        "away": opponent,
        "status": "final",
        "home_score": 2,
        "away_score": 1,
        "conference_game": True,
        "source_url": f"https://{slug}.example/schedule/2026",
    }
    away_game: dict[str, object] = {
        "id": f"sidearm:{slug}:9{index}",
        "date": f"2026-09-0{(index - 1) % len(slugs) + 1}",
        "home": previous,
        "away": slug,
        "status": "final",
        "home_score": 2,
        "away_score": 1,
        "conference_game": True,
        "venue": f"{previous} Field",
        "source_url": f"https://{slug}.example/schedule/2026",
    }
    return [home_game, away_game]


def _fake_programme_factory(delays: dict[str, float], slugs: list[str]):
    def fake_programme(
        school, season, aliases, *, session=None, layers, members, page_cache=None
    ):
        del season, aliases, session, members, page_cache
        slug = programme_slug(school.name)
        time.sleep(delays.get(slug, 0))
        rows = _published_rows(slug, slugs)
        links = "".join(
            f'<a href="https://{slug}.example/boxscore/'
            f'{str(row["id"]).rpartition(":")[2]}">B</a>'
            for row in rows
        )
        return ProgrammeCollection(
            slug=slug,
            name=school.name,
            fixtures=rows,
            players=[{"name": f"Player {slug}"}],
            outcomes={
                LAYER_SCHEDULE: LayerOutcome(LAYER_SCHEDULE, STATE_COMPLETE, count=2),
                LAYER_ROSTER: LayerOutcome(LAYER_ROSTER, STATE_COMPLETE, count=1),
                LAYER_STATS: LayerOutcome(LAYER_STATS, STATE_COMPLETE, count=1),
            },
            schedule_url=f"https://{slug}.example/schedule/2026",
            roster_url=f"https://{slug}.example/roster/2026",
            stats_url=f"https://{slug}.example/stats/2026",
            schedule_html=f"<html><body>{links}</body></html>",
            stat_players=[{"name": f"Player {slug}", "goals": 1}],
            stat_keepers=[],
        )

    return fake_programme


def _fake_match_factory(delays: dict[str, float]):
    def fake_collect_match(session, url, season, fixture):
        del session, season
        time.sleep(delays.get(str(fixture["id"]), 0))
        return {
            "source_url": url,
            "teams": [
                {"name": str(fixture["home"]), "score": fixture["home_score"]},
                {"name": str(fixture["away"]), "score": fixture["away_score"]},
            ],
            "home_index": 0,
        }

    return fake_collect_match


def _run_collect(
    monkeypatch,
    root: Path,
    *,
    workers: int,
    prog_delays: dict[str, float],
    match_delays: dict[str, float],
):
    schools = _schools()
    slugs = [programme_slug(school.name) for school in schools]
    monkeypatch.setattr(collect_board, "datetime", _FrozenDatetime)
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: schools)
    monkeypatch.setattr(
        collect_board,
        "collect_programme",
        _fake_programme_factory(prog_delays, slugs),
    )
    monkeypatch.setattr(
        collect_board, "collect_match", _fake_match_factory(match_delays)
    )
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: root)
    return collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        # "echo" has no configured programme: its named gap must land at the
        # same place in the errors list under every completion order.
        wanted=[*slugs, "echo"],
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES),
        config_path=root / "schools.toml",
        membership_extrapolated=False,
        stored_matches={},
        workers=workers,
    )


def test_parallel_output_is_byte_identical_to_serial(monkeypatch, tmp_path) -> None:
    slugs = [programme_slug(name) for name in _NAMES]
    serial_root = tmp_path / "serial"
    parallel_root = tmp_path / "parallel"

    serial = _run_collect(
        monkeypatch, serial_root, workers=1, prog_delays={}, match_delays={}
    )
    # Adversarial completion order: the first-submitted programme and the
    # first-planned box scores finish LAST.
    prog_delays = {slug: 0.12 - 0.04 * index for index, slug in enumerate(slugs)}
    match_delays = {f"sidearm:{slug}:{index + 1}": 0.12 - 0.03 * index
                    for index, slug in enumerate(slugs)}
    parallel = _run_collect(
        monkeypatch,
        parallel_root,
        workers=4,
        prog_delays=prog_delays,
        match_delays=match_delays,
    )

    labels = ("fixtures", "rosters", "stats", "matches")
    for label, first, second in zip(labels, serial[:4], parallel[:4]):
        assert json.dumps(first, indent=2) == json.dumps(second, indent=2), label
    # Coverage cells: same content AND same insertion order.
    assert list(serial[4]) == list(parallel[4])
    assert serial[4] == parallel[4]
    assert serial[5] == parallel[5]  # errors, in the same order
    assert serial[6] == parallel[6]  # duplicate count
    # The checkpointed manifests are byte-identical too.
    serial_manifest = (serial_root / "data" / "coverage.json").read_bytes()
    parallel_manifest = (parallel_root / "data" / "coverage.json").read_bytes()
    assert serial_manifest == parallel_manifest


def _sidearm_schedule_html(name: str, opponent: str) -> str:
    component = {
        "type": "events",
        "data": [
            {
                "id": 42,
                "date": "2026-09-17T19:00:00",
                "location_indicator": "H",
                "is_conference": True,
                "type": "upcoming",
                "schedule": {"title": "2026 Men's Soccer Schedule"},
                "opponent": {"title": opponent},
                "result": {"team_score": None, "opponent_score": None},
            }
        ],
    }
    return (
        f"<html><head><title>2026 Men's Soccer Schedule - {name}</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )


class _CannedSession:
    """Serves each host's schedule page after that host's delay."""

    def __init__(self, schools: list[SchoolConfig], delays: dict[str, float]) -> None:
        self._by_host = {
            host_of(school.base_url): school for school in schools
        }
        self._delays = delays

    def get(self, url: str, timeout: int | None = None, headers=None):
        del timeout, headers
        host = host_of(url)
        time.sleep(self._delays.get(host, 0))
        school = self._by_host[host]
        index = _NAMES.index(school.name)
        opponent = _NAMES[(index + 1) % len(self._by_host)]
        return SimpleNamespace(
            status_code=200,
            url=url,
            text=_sidearm_schedule_html(school.name, opponent),
            headers={"ETag": f'"{school.name}"'},
            raise_for_status=lambda: None,
        )


def test_sidecars_and_archives_are_byte_stable_across_completion_orders(
    monkeypatch, tmp_path
) -> None:
    """The real ``collect_programme`` under fake transport: the raw_html
    archive and every page-state sidecar must come out byte-identical
    whether the fleet completes in submission order or reversed."""
    monkeypatch.setattr(page_state, "_now", lambda: "2026-08-31T12:00:00+00:00")
    monkeypatch.setattr(collect_board, "datetime", _FrozenDatetime)
    schools = _schools(3)
    slugs = [programme_slug(school.name) for school in schools]
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: schools)

    def run(root: Path, *, workers: int, delays: dict[str, float]):
        monkeypatch.setattr(
            collect_board,
            "build_session",
            lambda session=None: _CannedSession(schools, delays),
        )
        monkeypatch.setattr(collect_board.paths, "data_root", lambda: root)
        return collect_board.collect(
            season=2026,
            gender="men",
            conference="GAC",
            wanted=list(slugs),
            layers=(LAYER_SCHEDULE,),
            config_path=root / "schools.toml",
            membership_extrapolated=False,
        )

    serial_root = tmp_path / "serial"
    parallel_root = tmp_path / "parallel"
    serial = run(serial_root, workers=1, delays={})
    reversed_delays = {
        host_of(school.base_url): 0.1 - 0.05 * index
        for index, school in enumerate(schools)
    }
    parallel = run(parallel_root, workers=3, delays=reversed_delays)

    def tree(root: Path) -> dict[str, bytes]:
        base = root / "data" / "raw_html"
        return {
            str(path.relative_to(base)): path.read_bytes()
            for path in sorted(base.rglob("*"))
            if path.is_file()
        }

    serial_tree = tree(serial_root)
    assert serial_tree == tree(parallel_root)
    # Every programme landed both its archive and its sidecar.
    for slug in slugs:
        assert f"{slug}/2026-men-schedule.html" in serial_tree
        assert f"{slug}/2026-men-schedule.state.json" in serial_tree
    assert json.dumps(serial[0], indent=2) == json.dumps(parallel[0], indent=2)
    assert (serial_root / "data" / "coverage.json").read_bytes() == (
        parallel_root / "data" / "coverage.json"
    ).read_bytes()


# ---------------------------------------------------------------------------
# Isolation: a hung fetch is ITS programme's named gap; the rest complete,
# and what completed is already durable on disk.
# ---------------------------------------------------------------------------


def _ok_result(slug: str, layers) -> ProgrammeCollection:
    return ProgrammeCollection(
        slug=slug,
        name=slug.title(),
        fixtures=[],
        players=[],
        outcomes={
            layer: LayerOutcome(layer, STATE_COMPLETE, count=1) for layer in layers
        },
    )


def test_a_hung_programme_is_a_named_gap_and_the_rest_complete(
    monkeypatch, tmp_path
) -> None:
    release = threading.Event()
    schools = _schools(3)

    def fake_programme(
        school, season, aliases, *, session=None, layers, members, page_cache=None
    ):
        del season, aliases, session, members, page_cache
        slug = programme_slug(school.name)
        if slug == "bravo":
            release.wait(10)  # a hung site, far beyond the budget
        return _ok_result(slug, layers)

    monkeypatch.setattr(collect_board, "load_schools", lambda _path: schools)
    monkeypatch.setattr(collect_board, "collect_programme", fake_programme)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    started = time.monotonic()
    try:
        cells, errors = collect_board.collect(
            season=2026,
            gender="men",
            conference="GAC",
            wanted=["alpha", "bravo", "charlie"],
            layers=(LAYER_SCHEDULE,),
            config_path=tmp_path / "schools.toml",
            membership_extrapolated=False,
            workers=3,
            task_budget=0.3,
        )[4:6]
    finally:
        release.set()

    assert time.monotonic() - started < 5  # the run did not wait out the hang
    assert cells["2026/men/alpha/schedule"]["state"] == STATE_COMPLETE
    assert cells["2026/men/charlie/schedule"]["state"] == STATE_COMPLETE
    gap = cells["2026/men/bravo/schedule"]
    assert gap["state"] == STATE_UNAVAILABLE
    assert "budget" in str(gap["reason"])
    assert any("bravo" in error and "budget" in error for error in errors)
    # The completed programmes were checkpointed to disk during the run —
    # main() never ran, yet the manifest already records them.
    manifest = json.loads((tmp_path / "data" / "coverage.json").read_text())
    assert manifest["cells"]["2026/men/alpha/schedule"]["state"] == STATE_COMPLETE
    assert manifest["cells"]["2026/men/bravo/schedule"]["state"] == STATE_UNAVAILABLE


def _two_final_fixtures() -> list[dict[str, object]]:
    return [
        {
            "id": "sidearm:alpha:1",
            "date": "2026-09-01",
            "home": "alpha",
            "away": "bravo",
            "status": "final",
            "home_score": 2,
            "away_score": 1,
            "conference_game": True,
            "source_url": "https://alpha.example/schedule/2026",
        },
        {
            "id": "sidearm:alpha:2",
            "date": "2026-09-05",
            "home": "alpha",
            "away": "charlie",
            "status": "final",
            "home_score": 3,
            "away_score": 0,
            "conference_game": True,
            "source_url": "https://alpha.example/schedule/2026",
        },
    ]


def _one_programme_with_finals(monkeypatch, tmp_path) -> None:
    school = _schools(1)[0]
    rows = _two_final_fixtures()
    links = "".join(
        f'<a href="https://alpha.example/boxscore/'
        f'{str(row["id"]).rpartition(":")[2]}">B</a>'
        for row in rows
    )
    result = ProgrammeCollection(
        slug="alpha",
        name=school.name,
        fixtures=rows,
        players=[],
        outcomes={
            LAYER_SCHEDULE: LayerOutcome(LAYER_SCHEDULE, STATE_COMPLETE, count=2)
        },
        schedule_url="https://alpha.example/schedule/2026",
        schedule_html=f"<html><body>{links}</body></html>",
    )
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(
        collect_board, "collect_programme", lambda *_args, **_kwargs: result
    )
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)


def test_a_hung_box_score_fetch_is_isolated_to_its_fixture(
    monkeypatch, tmp_path
) -> None:
    release = threading.Event()
    _one_programme_with_finals(monkeypatch, tmp_path)

    def fake_collect_match(session, url, season, fixture):
        del session, season
        if str(fixture["id"]).endswith(":1"):
            release.wait(10)
        return {
            "source_url": url,
            "teams": [
                {"name": "Alpha", "score": fixture["home_score"]},
                {"name": "Other", "score": fixture["away_score"]},
            ],
            "home_index": 0,
        }

    monkeypatch.setattr(collect_board, "collect_match", fake_collect_match)

    try:
        payload, cells, errors = collect_board.collect(
            season=2026,
            gender="men",
            conference="GAC",
            wanted=["alpha"],
            layers=(LAYER_SCHEDULE, LAYER_MATCHES),
            config_path=tmp_path / "schools.toml",
            membership_extrapolated=False,
            workers=2,
            task_budget=0.3,
        )[3:6]
    finally:
        release.set()

    assert "sidearm:alpha:2" in payload["matches"]
    assert "did not finish within" in payload["missing"]["sidearm:alpha:1"]
    cell = cells["2026/men/alpha/matches"]
    assert cell["state"] == STATE_COMPLETE  # one of two still landed
    assert "1 of 2" in str(cell["reason"])
    assert any("sidearm:alpha:1" in error for error in errors)


def test_box_scores_checkpoint_to_disk_as_they_confirm(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(collect_board, "MATCH_CHECKPOINT_EVERY", 1)
    _one_programme_with_finals(monkeypatch, tmp_path)
    monkeypatch.setattr(
        collect_board,
        "collect_match",
        _fake_match_factory({}),
    )
    checkpoints: list[dict[str, object]] = []

    payload = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        wanted=["alpha"],
        layers=(LAYER_SCHEDULE, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
        workers=1,
        matches_checkpoint=checkpoints.append,
    )[3]

    assert len(checkpoints) == 2
    for checkpoint in checkpoints:
        # Every checkpoint is a valid wholesale payload, never a fragment.
        assert checkpoint["schema"] == "touchline.matches/1"
        assert checkpoint["season"] == 2026
    assert set(checkpoints[-1]["matches"]) == set(payload["matches"])


def test_a_crashing_collector_is_a_named_gap_not_a_dead_run(
    monkeypatch, tmp_path
) -> None:
    schools = _schools(2)

    def fake_programme(
        school, season, aliases, *, session=None, layers, members, page_cache=None
    ):
        del season, aliases, session, members, page_cache
        slug = programme_slug(school.name)
        if slug == "alpha":
            raise RuntimeError("collector bug")
        return _ok_result(slug, layers)

    monkeypatch.setattr(collect_board, "load_schools", lambda _path: schools)
    monkeypatch.setattr(collect_board, "collect_programme", fake_programme)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    cells, errors = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        wanted=["alpha", "bravo"],
        layers=(LAYER_SCHEDULE,),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
        workers=2,
    )[4:6]

    assert cells["2026/men/bravo/schedule"]["state"] == STATE_COMPLETE
    gap = cells["2026/men/alpha/schedule"]
    assert gap["state"] == STATE_UNAVAILABLE
    assert "collector bug" in str(gap["reason"])
    assert any("collector bug" in error for error in errors)


def test_a_late_result_after_the_budget_is_discarded_not_mixed_in(
    monkeypatch, tmp_path
) -> None:
    """A timed-out programme whose thread later finishes must stay a gap for
    THIS run — its late result never rewrites cells already settled."""
    release = threading.Event()
    finished = threading.Event()
    schools = _schools(2)

    def fake_programme(
        school, season, aliases, *, session=None, layers, members, page_cache=None
    ):
        del season, aliases, session, members, page_cache
        slug = programme_slug(school.name)
        if slug == "alpha":
            release.wait(10)
            finished.set()
        return _ok_result(slug, layers)

    monkeypatch.setattr(collect_board, "load_schools", lambda _path: schools)
    monkeypatch.setattr(collect_board, "collect_programme", fake_programme)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    try:
        cells = collect_board.collect(
            season=2026,
            gender="men",
            conference="GAC",
            wanted=["alpha", "bravo"],
            layers=(LAYER_SCHEDULE,),
            config_path=tmp_path / "schools.toml",
            membership_extrapolated=False,
            workers=2,
            task_budget=0.2,
        )[4]
    finally:
        release.set()
    finished.wait(5)

    assert cells["2026/men/alpha/schedule"]["state"] == STATE_UNAVAILABLE
    assert cells["2026/men/bravo/schedule"]["state"] == STATE_COMPLETE


# ---------------------------------------------------------------------------
# CLI wiring: --serial, --workers, --programme-timeout, and the matches
# checkpoint path all reach collect().
# ---------------------------------------------------------------------------


def _fake_payloads(season: int, gender: str, conference: str, wanted: list[str]):
    stamp = "2026-08-31T12:00:00+00:00"
    return (
        {
            "schema": "touchline.fixtures/2",
            "season": season,
            "gender": gender,
            "conference": conference,
            "collected_at": stamp,
            "programmes": [
                {"slug": slug, "name": slug, "conference": conference}
                for slug in wanted
            ],
            "fixtures": [],
        },
        {
            "schema": "touchline.rosters/1",
            "season": season,
            "gender": gender,
            "collected_at": stamp,
            "rosters": {},
        },
        {
            "schema": "touchline.stats/1",
            "season": season,
            "gender": gender,
            "collected_at": stamp,
            "teams": {},
        },
        {
            "schema": "touchline.matches/1",
            "season": season,
            "gender": gender,
            "collected_at": stamp,
            "matches": {},
        },
    )


def _run_main(monkeypatch, tmp_path, captured: dict, *extra_argv: str) -> int:
    def fake_collect(**kwargs):
        captured.update(kwargs)
        checkpoint = kwargs.get("matches_checkpoint")
        if checkpoint is not None:
            checkpoint(
                _fake_payloads(
                    kwargs["season"],
                    kwargs["gender"],
                    kwargs["conference"],
                    kwargs["wanted"],
                )[3]
            )
        return (
            *_fake_payloads(
                kwargs["season"],
                kwargs["gender"],
                kwargs["conference"],
                kwargs["wanted"],
            ),
            {},
            [],
            0,
        )

    monkeypatch.setattr(collect_board, "collect", fake_collect)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect-board",
            "--season",
            "2026",
            "--gender",
            "men",
            "--conference",
            "GAC",
            "--programmes",
            "alpha",
            "--layers",
            ",".join(DEFAULT_LAYERS),
            *extra_argv,
        ],
    )
    return collect_board.main()


def test_main_wires_serial_and_the_matches_checkpoint(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    assert _run_main(monkeypatch, tmp_path, captured, "--serial") == 0
    assert captured["workers"] == 1
    assert captured["task_budget"] == collect_board.DEFAULT_TASK_BUDGET
    # The checkpoint callable writes a valid matches file at the season path.
    checkpointed = json.loads(
        (tmp_path / "data" / "matches" / "2026-men-gac.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpointed["schema"] == "touchline.matches/1"


def test_main_wires_workers_and_programme_timeout(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    code = _run_main(
        monkeypatch, tmp_path, captured, "--workers", "4", "--programme-timeout", "12"
    )
    assert code == 0
    assert captured["workers"] == 4
    assert captured["task_budget"] == 12.0


def test_main_refuses_zero_workers(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    assert _run_main(monkeypatch, tmp_path, captured, "--workers", "0") == 2
    assert "workers" not in captured


def test_match_task_failures_keep_the_ruled_message_shape(
    monkeypatch, tmp_path
) -> None:
    """A fixture whose every candidate URL refuses still records the joined
    failure reasons, exactly as the sequential loop did."""
    _one_programme_with_finals(monkeypatch, tmp_path)

    def failing_collect_match(session, url, season, fixture):
        del session, season, fixture
        raise LiveCollectionError(f"refused {url}")

    monkeypatch.setattr(collect_board, "collect_match", failing_collect_match)

    payload, _cells, errors = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        wanted=["alpha"],
        layers=(LAYER_SCHEDULE, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
        workers=2,
    )[3:6]

    assert payload["matches"] == {}
    assert "refused" in payload["missing"]["sidearm:alpha:1"]
    assert any(error.startswith("match sidearm:alpha:1:") for error in errors)
