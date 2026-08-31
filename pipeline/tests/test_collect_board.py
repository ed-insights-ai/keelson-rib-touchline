"""Conference shards: a collect run's scope only ever widens within its shard.

The season files are rewritten wholesale by each run, so the guard under test
is what stops "refresh Harding" from silently discarding the other six
programmes of an already-collected conference without absorbing another
conference's programmes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import collect_board
from scripts.collect_board import (
    _dedupe_fixtures,
    _stored_match_current,
    widen_to_existing_scope,
)
from src.config import SchoolConfig
from src.sidearm_live import (
    DEFAULT_LAYERS,
    LAYER_MATCHES,
    LAYER_SCHEDULE,
    STATE_COMPLETE,
    STATE_EMPTY,
    STATE_NO_COLLECTOR,
    LayerOutcome,
    ProgrammeCollection,
    programme_slug,
)


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


def test_no_collector_schedule_propagates_to_matches(
    tmp_path: Path, monkeypatch
) -> None:
    school = SchoolConfig(
        name="Northeastern State",
        abbreviation="NSU",
        conference="GAC",
        prefix="nsu",
        base_url="https://example.test/sports/mens-soccer",
        enabled=True,
    )
    reason = "no live collector for platform 'sidearm_legacy'"
    result = ProgrammeCollection(
        slug="northeastern-state",
        name=school.name,
        fixtures=[],
        players=[],
        outcomes={
            LAYER_SCHEDULE: LayerOutcome(
                LAYER_SCHEDULE, STATE_NO_COLLECTOR, reason=reason
            )
        },
    )
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(collect_board, "collect_programme", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    cells = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        wanted=["northeastern-state"],
        layers=(LAYER_SCHEDULE, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
    )[4]

    match_cell = cells["2026/men/northeastern-state/matches"]
    assert match_cell["state"] == STATE_NO_COLLECTOR
    assert match_cell["reason"] == reason


def test_a_malformed_file_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    bad = tmp_path / "fx.json"
    bad.write_text("{ not json", encoding="utf-8")
    wanted, added = widen_to_existing_scope(["harding"], bad, tmp_path / "ro.json")
    assert wanted == ["harding"]
    assert added == []


def test_collect_emits_schema_v2_and_each_programmes_actual_conference(
    monkeypatch,
    tmp_path: Path,
) -> None:
    schools = [
        SchoolConfig(
            name="Harding",
            abbreviation="HU",
            conference="GAC",
            prefix="",
            base_url="https://harding.example",
            enabled=True,
        ),
        SchoolConfig(
            name="Lubbock Christian",
            abbreviation="LCU",
            conference="LSC",
            prefix="",
            base_url="https://lubbock.example",
            enabled=True,
        ),
    ]

    def fake_programme(school, season, aliases, *, layers, members, page_cache=None):
        del season, aliases, members, page_cache
        return ProgrammeCollection(
            slug=programme_slug(school.name),
            name=school.name,
            fixtures=[],
            players=[],
            outcomes={
                layer: LayerOutcome(layer=layer, state=STATE_EMPTY) for layer in layers
            },
        )

    monkeypatch.setattr(collect_board, "load_schools", lambda path: schools)
    monkeypatch.setattr(collect_board, "identity_aliases", lambda schools, gender: {})
    monkeypatch.setattr(
        collect_board, "conference_members", lambda schools, gender, conference: set()
    )
    monkeypatch.setattr(collect_board, "collect_programme", fake_programme)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    fixtures, *_ = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        wanted=["harding", "lubbock-christian"],
        layers=(LAYER_SCHEDULE,),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
    )

    assert fixtures["schema"] == "touchline.fixtures/2"
    assert fixtures["conference"] == "GAC"
    assert fixtures["programmes"] == [
        {"slug": "harding", "name": "Harding", "conference": "GAC", "abbr": "HU"},
        {
            "slug": "lubbock-christian",
            "name": "Lubbock Christian",
            "conference": "LSC",
            "abbr": "LCU",
        },
    ]


def test_main_keeps_conference_shards_independent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_collect(**kwargs):
        calls.append(kwargs)
        season = kwargs["season"]
        gender = kwargs["gender"]
        conference = kwargs["conference"]
        wanted = kwargs["wanted"]
        fixture_payload = {
            "schema": "touchline.fixtures/2",
            "season": season,
            "gender": gender,
            "conference": conference,
            "collected_at": "2026-08-12T12:00:00+00:00",
            "programmes": [
                {"slug": slug, "name": slug, "conference": conference}
                for slug in wanted
            ],
            "fixtures": [],
        }
        roster_payload = {
            "schema": "touchline.rosters/1",
            "season": season,
            "gender": gender,
            "collected_at": "2026-08-12T12:00:00+00:00",
            "rosters": {},
        }
        stats_payload = {
            "schema": "touchline.stats/1",
            "season": season,
            "gender": gender,
            "collected_at": "2026-08-12T12:00:00+00:00",
            "teams": {},
        }
        matches_payload = {
            "schema": "touchline.matches/1",
            "season": season,
            "gender": gender,
            "collected_at": "2026-08-12T12:00:00+00:00",
            "matches": {},
        }
        cells = {
            f"{season}/{gender}/{wanted[0]}/schedule": {"state": "complete"}
        }
        return (
            fixture_payload,
            roster_payload,
            stats_payload,
            matches_payload,
            cells,
            ["named gap"],
            0,
        )

    monkeypatch.setattr(collect_board, "collect", fake_collect)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    def run(conference: str, programme: str) -> None:
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
                conference,
                "--programmes",
                programme,
                "--layers",
                ",".join(DEFAULT_LAYERS),
            ],
        )
        assert collect_board.main() == 0

    run("GAC", "harding")
    gac_bytes = (
        tmp_path / "data" / "fixtures" / "2026-men-gac.json"
    ).read_bytes()
    run("LSC", "lubbock-christian")

    assert calls[0]["wanted"] == ["harding"]
    assert calls[1]["wanted"] == ["lubbock-christian"]
    assert (
        tmp_path / "data" / "fixtures" / "2026-men-gac.json"
    ).read_bytes() == gac_bytes
    for layer in ("fixtures", "rosters", "stats", "matches"):
        assert (tmp_path / "data" / layer / "2026-men-gac.json").is_file()
        assert (tmp_path / "data" / layer / "2026-men-lsc.json").is_file()
    assert (
        tmp_path / "data" / "errors" / "collect-board-2026-men-gac.json"
    ).is_file()
    assert (
        tmp_path / "data" / "errors" / "collect-board-2026-men-lsc.json"
    ).is_file()

    manifest = json.loads((tmp_path / "data" / "coverage.json").read_text())
    assert set(manifest["cells"]) == {
        "2026/men/harding/schedule",
        "2026/men/lubbock-christian/schedule",
    }


def _fx(**over: object) -> dict[str, object]:
    fixture: dict[str, object] = {
        "id": "sidearm:harding:1",
        "date": "2026-10-08",
        "home": "harding",
        "away": "rogers-state",
        "status": "scheduled",
        "conference_game": False,
        "source_url": "https://example.test",
    }
    fixture.update(over)
    return fixture


def test_dedupe_a_published_claim_beats_a_derived_one() -> None:
    published_false = _fx(id="sidearm:harding:1", conference_game=False)
    derived_true = _fx(
        id="sidearm:rogers-state:9",
        conference_game=True,
        conference_game_source="derived:membership",
    )
    merged, duplicates = _dedupe_fixtures([derived_true, published_false])
    assert duplicates == 1
    assert len(merged) == 1
    assert merged[0]["conference_game"] is False
    assert "conference_game_source" not in merged[0]


def test_dedupe_two_published_claims_or_together() -> None:
    unmarked = _fx(id="sidearm:harding:1", conference_game=False)
    marked = _fx(id="sidearm:rogers-state:9", conference_game=True)
    merged, _ = _dedupe_fixtures([unmarked, marked])
    assert merged[0]["conference_game"] is True


def test_dedupe_keeps_detail_the_other_side_published() -> None:
    bare = _fx(id="sidearm:harding:1", status="final", home_score=2, away_score=1)
    detailed = _fx(
        id="sidearm:rogers-state:9", time="19:00", venue="Soldier Field"
    )
    merged, _ = _dedupe_fixtures([bare, detailed])
    assert len(merged) == 1
    # The final wins the row; the loser's kickoff and venue survive the merge.
    assert merged[0]["status"] == "final"
    assert merged[0]["time"] == "19:00"
    assert merged[0]["venue"] == "Soldier Field"


def test_dedupe_two_derived_claims_or_together() -> None:
    one = _fx(
        id="sidearm:rogers-state:9",
        conference_game=True,
        conference_game_source="derived:membership",
    )
    other = _fx(
        id="sidearm:ouachita-baptist:4",
        home="rogers-state",
        away="harding",
        conference_game=False,
        conference_game_source="derived:membership",
    )
    merged, _ = _dedupe_fixtures([other, one])
    assert merged[0]["conference_game"] is True
    assert merged[0]["conference_game_source"] == "derived:membership"


def test_dedupe_an_exhibition_marking_survives_the_merge() -> None:
    # Only one side's page may say "(Exhibition)"; the marking must not be
    # lost when the other side's fuller record wins the merge.
    marked = _fx(id="sidearm:rogers-state:1", match_type="exhibition")
    fuller = _fx(
        id="sidearm:midwestern-state:9",
        status="final",
        time="19:00",
        venue="Soldier Field",
    )
    merged, _ = _dedupe_fixtures([marked, fuller])
    assert merged[0]["status"] == "final"
    assert merged[0]["match_type"] == "exhibition"


def test_dedupe_never_discards_a_published_score_pair() -> None:
    # Both rows are finals — same lifecycle rank — but only one side's site
    # published the score; the other published completion plus enough extras
    # to win the detail comparison. The pair must survive whichever wins.
    scoreless = _fx(
        id="sidearm:rogers-state:1",
        status="final",
        match_type="exhibition",
        time="19:00",
        venue="Soldier Field",
    )
    scored = _fx(id="sidearm:okwu:9", status="final", home_score=2, away_score=1)
    merged, _ = _dedupe_fixtures([scored, scoreless])
    assert merged[0]["home_score"] == 2
    assert merged[0]["away_score"] == 1
    assert merged[0]["match_type"] == "exhibition"


def test_dedupe_orients_a_backfilled_score_by_team_id() -> None:
    # Each site publishes itself as home, so the grouped rows arrive with
    # reversed orientations; a verbatim copy would hand each team the
    # other's goals.
    scoreless = _fx(
        id="sidearm:harding:1",
        status="final",
        match_type="exhibition",
        time="19:00",
        venue="Soldier Field",
    )
    reversed_scored = _fx(
        id="sidearm:rogers-state:9",
        home="rogers-state",
        away="harding",
        status="final",
        home_score=2,
        away_score=1,
    )
    merged, _ = _dedupe_fixtures([reversed_scored, scoreless])
    [fixture] = merged
    # rogers-state scored 2 on its own page; whichever orientation won,
    # rogers-state's side must still carry the 2.
    rs_score = (
        fixture["home_score"] if fixture["home"] == "rogers-state" else fixture["away_score"]
    )
    assert rs_score == 2
    assert fixture["match_type"] == "exhibition"


def test_dedupe_never_promotes_a_live_score_into_a_final() -> None:
    # One site still shows the game live with a partial score while the
    # other has already declared it final without one; an in-progress
    # score is not a result.
    live = _fx(id="sidearm:harding:1", status="live", home_score=1, away_score=0)
    finished = _fx(id="sidearm:rogers-state:9", status="final")
    merged, _ = _dedupe_fixtures([live, finished])
    [fixture] = merged
    assert fixture["status"] == "final"
    assert "home_score" not in fixture


# ---------------------------------------------------------------------------
# Incremental match harvest: a box score already stored for a played fixture
# whose result has not moved is never re-fetched; a silent final is always
# retried; a moved result (a correction) is re-fetched.  --refetch restores
# wholesale collection.
# ---------------------------------------------------------------------------


def _final_fixture(**over: object) -> dict[str, object]:
    fixture = _fx(status="final", home_score=2, away_score=1, conference_game=True)
    fixture.update(over)
    return fixture


def _stored_detail(first: int = 2, second: int = 1) -> dict[str, object]:
    return {
        "source_url": "https://example.test/boxscore/1",
        "teams": [
            {"name": "Harding", "score": first},
            {"name": "Rogers State", "score": second},
        ],
        "home_index": 0,
    }


def _harvest_setup(
    monkeypatch, tmp_path: Path, fixtures: list[dict[str, object]]
) -> list[str]:
    """Wire a one-programme collect whose schedule links every fixture's box
    score, and return the list of box-score URLs actually fetched."""
    school = SchoolConfig(
        name="Harding",
        abbreviation="HU",
        conference="GAC",
        prefix="hu",
        base_url="https://example.test/sports/mens-soccer",
        enabled=True,
    )
    links = "".join(
        f'<a href="/sports/mens-soccer/boxscore/{str(fixture["id"]).rpartition(":")[2]}">B</a>'
        for fixture in fixtures
    )
    result = ProgrammeCollection(
        slug="harding",
        name=school.name,
        fixtures=fixtures,
        players=[],
        outcomes={
            LAYER_SCHEDULE: LayerOutcome(
                LAYER_SCHEDULE, STATE_COMPLETE, count=len(fixtures)
            )
        },
        schedule_url="https://example.test/sports/mens-soccer/schedule/2026",
        schedule_html=f"<html><body>{links}</body></html>",
    )
    fetched: list[str] = []

    def fake_collect_match(session, url, season, fixture):
        del session, season
        fetched.append(url)
        return _stored_detail(
            int(fixture.get("home_score", 0) or 0),
            int(fixture.get("away_score", 0) or 0),
        )

    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(
        collect_board, "collect_programme", lambda *_args, **_kwargs: result
    )
    monkeypatch.setattr(collect_board, "collect_match", fake_collect_match)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)
    return fetched


def _harvest(
    fixtures: list[dict[str, object]],
    stored: dict[str, dict[str, object]],
    monkeypatch,
    tmp_path: Path,
    *,
    refetch: bool = False,
) -> tuple[dict[str, object], dict[str, dict[str, object]], list[str]]:
    fetched = _harvest_setup(monkeypatch, tmp_path, fixtures)
    values = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        wanted=["harding"],
        layers=(LAYER_SCHEDULE, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
        stored_matches=stored,
        refetch=refetch,
    )
    return values[3], values[4], fetched


def test_a_stored_box_score_with_an_unchanged_result_is_not_refetched(
    monkeypatch, tmp_path: Path
) -> None:
    fixtures = [
        _final_fixture(),
        _final_fixture(
            id="sidearm:harding:2", date="2026-10-11", away="southern-nazarene"
        ),
    ]
    stored = {
        "sidearm:harding:1": _stored_detail(),
        "sidearm:harding:2": _stored_detail(),
    }
    payload, cells, fetched = _harvest(fixtures, stored, monkeypatch, tmp_path)

    # Zero box-score requests; both records preserved verbatim.
    assert fetched == []
    assert payload["matches"] == stored
    cell = cells["2026/men/harding/matches"]
    assert cell["state"] == STATE_COMPLETE
    assert cell["count"] == 2


def test_a_silent_final_is_still_retried(monkeypatch, tmp_path: Path) -> None:
    # Final with no published score: the vocabulary rule is that tomorrow's
    # collect retries silence, so stored detail alone never earns a skip.
    silent = _final_fixture()
    silent.pop("home_score")
    silent.pop("away_score")
    stored = {"sidearm:harding:1": _stored_detail()}
    _payload, _cells, fetched = _harvest([silent], stored, monkeypatch, tmp_path)

    assert len(fetched) == 1


def test_a_changed_result_is_refetched(monkeypatch, tmp_path: Path) -> None:
    # The schedule now publishes 3-1 where the stored detail says 2-1: a
    # correction, and the stale box score must not survive it.
    corrected = _final_fixture(home_score=3, away_score=1)
    stored = {"sidearm:harding:1": _stored_detail(2, 1)}
    payload, _cells, fetched = _harvest([corrected], stored, monkeypatch, tmp_path)

    assert len(fetched) == 1
    assert payload["matches"]["sidearm:harding:1"]["teams"][0]["score"] == 3


def test_refetch_restores_wholesale_collection(monkeypatch, tmp_path: Path) -> None:
    stored = {"sidearm:harding:1": _stored_detail()}
    _payload, _cells, fetched = _harvest(
        [_final_fixture()], stored, monkeypatch, tmp_path, refetch=True
    )

    assert len(fetched) == 1


def test_a_final_with_no_stored_detail_is_fetched(
    monkeypatch, tmp_path: Path
) -> None:
    payload, _cells, fetched = _harvest([_final_fixture()], {}, monkeypatch, tmp_path)

    assert len(fetched) == 1
    assert "sidearm:harding:1" in payload["matches"]


def test_stored_match_current_respects_orientation() -> None:
    # A reversed pair is a different result, not an unchanged one: 2-1 at
    # home is not 1-2 at home.
    fixture = _final_fixture(home_score=1, away_score=2)
    assert _stored_match_current(_stored_detail(1, 2), fixture) is True
    assert _stored_match_current(_stored_detail(2, 1), fixture) is False
    # An unoriented draw compares the pair regardless of order.
    draw = _final_fixture(home_score=1, away_score=1)
    unoriented = _stored_detail(1, 1)
    unoriented.pop("home_index")
    assert _stored_match_current(unoriented, draw) is True


def test_collect_records_verified_unchanged_cells(
    monkeypatch, tmp_path: Path
) -> None:
    # A page verified unchanged must be legible in the manifest as
    # verified-unchanged, not mistakable for a gap — and a freshly parsed
    # page must not carry the marker.
    school = SchoolConfig(
        name="Harding",
        abbreviation="HU",
        conference="GAC",
        prefix="hu",
        base_url="https://example.test/sports/mens-soccer",
        enabled=True,
    )
    result = ProgrammeCollection(
        slug="harding",
        name=school.name,
        fixtures=[],
        players=[],
        outcomes={
            LAYER_SCHEDULE: LayerOutcome(
                LAYER_SCHEDULE, STATE_COMPLETE, count=9, unchanged=True
            ),
            "roster": LayerOutcome("roster", STATE_COMPLETE, count=20),
        },
    )
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(
        collect_board, "collect_programme", lambda *_args, **_kwargs: result
    )
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    cells = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        wanted=["harding"],
        layers=(LAYER_SCHEDULE, "roster"),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
    )[4]

    assert cells["2026/men/harding/schedule"]["verified"] == "unchanged"
    assert cells["2026/men/harding/schedule"]["state"] == STATE_COMPLETE
    assert "verified" not in cells["2026/men/harding/roster"]
