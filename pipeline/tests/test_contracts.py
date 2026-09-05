"""The contract fixtures under contracts/ bound what the writers may emit.

Three layers of proof, from the fixture inward:

* the fixtures themselves are well-formed and exercise every enumerated
  value the writer's own constants can produce;
* a full collect, driven through ``collect_board.collect`` with the real
  box-score parser, stays within every fixture;
* optionally, a real data home (``TOUCHLINE_CONTRACT_DATA_DIR``) stays
  within them too, so a fixture can be checked against a year of collects
  before it ships.

The 2026-09-01 failure this guards against: the conditional fetch added
``verified: "unchanged"`` to coverage cells, nothing here noticed, and the
site's strict schema refused the manifest at the next build.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import collect_board
from src import contracts, coverage, membership, paths
from src.config import SchoolConfig
from src.sidearm_live import (
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    STATE_EMPTY,
    STATE_UNAVAILABLE,
    LayerOutcome,
    ProgrammeCollection,
    parse_boxscore_page,
    programme_slug,
)

BOXSCORE_HTML = Path(__file__).parent / "fixtures" / "sidearm_boxscore_6126.html"


def _assert_within(document: object, contract: contracts.Contract) -> None:
    found = contracts.drift(document, contract)
    assert not found, (
        f"{contract.name} writer output carries shapes its contract fixture "
        f"({contract.filename}) never promised; extend the fixture (and the "
        f"site's schema) before the writer:\n{contracts.describe(found)}"
    )


# ── the fixtures themselves ──────────────────────────────────────────────────


@pytest.mark.parametrize("contract", contracts.CONTRACTS, ids=lambda c: c.name)
def test_every_fixture_exists_and_names_its_schema(
    contract: contracts.Contract,
) -> None:
    document = contract.fixture()
    assert isinstance(document, dict)
    assert document.get("schema") == contract.schema


def test_coverage_fixture_exercises_every_state_layer_and_marker() -> None:
    document = contracts.COVERAGE.fixture()
    cells = ("cells", contracts.KEY)
    assert contracts.values(document, contracts.COVERAGE, (*cells, "state")) == {
        coverage.STATE_COMPLETE,
        coverage.STATE_EMPTY,
        coverage.STATE_UNAVAILABLE,
        coverage.STATE_NO_COLLECTOR,
    }
    assert contracts.values(document, contracts.COVERAGE, (*cells, "layer")) == {
        LAYER_SCHEDULE,
        LAYER_ROSTER,
        LAYER_STATS,
        LAYER_MATCHES,
    }
    # The marker that broke the site: a reused page's cell says so, and the
    # fixture promises exactly that one value.
    assert contracts.values(document, contracts.COVERAGE, (*cells, "verified")) == {
        "unchanged"
    }
    # One collector name per platform recipe; the fixture must promise each.
    assert contracts.values(document, contracts.COVERAGE, (*cells, "collector")) == set(
        collect_board.COLLECTORS.values()
    )


def test_fixtures_fixture_exercises_every_status_and_marking() -> None:
    document = contracts.FIXTURES.fixture()
    row = ("fixtures", contracts.ITEM)
    assert contracts.values(document, contracts.FIXTURES, (*row, "status")) == {
        "scheduled",
        "live",
        "final",
        "postponed",
        "cancelled",
    }
    assert contracts.values(document, contracts.FIXTURES, (*row, "match_type")) == {
        "exhibition"
    }
    # A forfeit names the awarded side; the writer may emit either, so the
    # fixture must carry both (bead tl-wyv).
    assert contracts.values(document, contracts.FIXTURES, (*row, "forfeit")) == {
        "home",
        "away",
    }
    assert all(
        fixture["status"] == "final" and "home_score" in fixture
        for fixture in document["fixtures"]
        if "forfeit" in fixture
    )
    assert contracts.values(
        document, contracts.FIXTURES, (*row, "conference_game_source")
    ) == {"derived:membership"}
    assert contracts.values(
        document, contracts.FIXTURES, ("conference_game_source",)
    ) == {"published:schedule-page"}
    assert document["membership_extrapolated"] is True
    assert document["missing"]
    # The neutral-site marker is a boolean the writer sets only when the page
    # itself says so; the fixture must carry one so the writer may.
    assert any(fixture.get("neutral") is True for fixture in document["fixtures"])


def test_matches_fixture_exercises_every_card_type_and_period() -> None:
    document = contracts.MATCHES.fixture()
    match = ("matches", contracts.KEY)
    assert contracts.values(
        document, contracts.MATCHES, (*match, "cards", contracts.ITEM, "type")
    ) == {"yellow", "red", "unknown"}
    periods = contracts.values(
        document, contracts.MATCHES, (*match, "plays", contracts.ITEM, "period")
    )
    assert {"1", "2", "SO"} <= periods
    assert document["missing"]
    # A match the page gave no way to orient is promised without home_index.
    assert any("home_index" not in m for m in document["matches"].values())


def test_programmes_fixture_covers_the_packaged_source_of_record() -> None:
    packaged = json.loads(paths.packaged_programmes_path().read_text(encoding="utf-8"))
    _assert_within(packaged, contracts.PROGRAMMES)
    fixture = contracts.PROGRAMMES.fixture()
    assert fixture["schema"] == packaged["schema"] == "touchline.programmes/2"
    # The fixture exhibits both the plain match and the pinned one with its note.
    notes = [
        r["provenance"]["point"].get("note") for r in fixture["programmes"].values()
    ]
    assert any(notes) and not all(notes)


def test_membership_fixture_matches_the_packaged_source_of_record() -> None:
    packaged = membership.load_membership(paths.packaged_membership_path())
    _assert_within(packaged, contracts.MEMBERSHIP)
    fixture = contracts.MEMBERSHIP.fixture()
    assert fixture["conferences"] == packaged["conferences"]


# ── the writers ──────────────────────────────────────────────────────────────


def _school(name: str, conference: str) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=name[:3].upper(),
        conference=conference,
        prefix="",
        base_url=f"https://{programme_slug(name)}.example/sports/mens-soccer",
        enabled=True,
    )


def _rows(slug: str, opponent: str) -> list[dict[str, object]]:
    url = f"https://{slug}.example/schedule/2026"
    return [
        {
            "id": f"sidearm:{slug}:1",
            "date": "2026-08-20",
            "home": slug,
            "away": opponent,
            "status": "final",
            "home_score": 2,
            "away_score": 1,
            "conference_game": True,
            "time": "19:00",
            "venue": f"{slug} Field",
            "source_url": url,
        },
        {
            "id": f"sidearm:{slug}:2",
            "date": "2026-08-23",
            "home": opponent,
            "away": slug,
            "status": "scheduled",
            "neutral": True,
            "conference_game": False,
            "conference_game_source": "derived:membership",
            "source_url": url,
        },
        {
            "id": f"sidearm:{slug}:3",
            "date": "2026-08-15",
            "home": slug,
            "away": "somebody-else",
            "status": "final",
            "match_type": "exhibition",
            "conference_game": False,
            "source_url": url,
        },
        {
            "id": f"sidearm:{slug}:4",
            "date": "2026-09-10",
            "home": slug,
            "away": opponent,
            "status": "postponed",
            "conference_game": True,
            "source_url": url,
        },
    ]


def _fake_programme(
    school,
    season,
    aliases,
    *,
    session=None,
    layers,
    members,
    page_cache=None,
    scope=None,
):
    del season, aliases, session, members, page_cache, scope
    slug = programme_slug(school.name)
    if slug == "charlie":
        # A programme whose pages could not be read: every layer is a named gap.
        return ProgrammeCollection(
            slug=slug,
            name=school.name,
            fixtures=[],
            players=[],
            outcomes={
                layer: LayerOutcome(
                    layer,
                    STATE_UNAVAILABLE,
                    reason=f"[2026] failed to fetch {layer} page: 403",
                    source_url=f"https://{slug}.example/{layer}/2026",
                )
                for layer in layers
            },
        )
    opponent = "bravo" if slug == "alpha" else "alpha"
    rows = _rows(slug, opponent)
    # The exhibition is played but its page links no box score, so the
    # matches file names it under `missing`.
    links = "".join(
        f'<a href="https://{slug}.example/boxscore/{str(row["id"]).rpartition(":")[2]}">B</a>'
        for row in rows
        if row.get("match_type") != "exhibition"
    )
    # bravo is the re-collect: every page verified unchanged, and its roster
    # page proven empty.
    unchanged = slug == "bravo"
    return ProgrammeCollection(
        slug=slug,
        name=school.name,
        fixtures=rows,
        players=[]
        if unchanged
        else [
            {
                "name": "Full Line",
                "number": "00",
                "position": "GK",
                "class_year": "Sr.",
                "height": "6-2",
                "weight": "185 lbs",
                "hometown": "Searcy, Ark.",
                "source_url": f"https://{slug}.example/roster/2026/full-line",
            },
            {"name": "Bare Line"},
        ],
        outcomes={
            LAYER_SCHEDULE: LayerOutcome(
                LAYER_SCHEDULE,
                STATE_COMPLETE,
                count=len(rows),
                source_url=f"https://{slug}.example/schedule/2026",
                unchanged=unchanged,
                # alpha hosted a match it did not play: a named skip, not a
                # gap, on a cell that is still complete.
                skips=()
                if unchanged
                else ("hosted other-match skipped: 2026-09-05, Delta v Echo",),
            ),
            LAYER_ROSTER: LayerOutcome(
                LAYER_ROSTER,
                STATE_EMPTY if unchanged else STATE_COMPLETE,
                count=0 if unchanged else 2,
                reason="[2026] the roster page proved its season but listed nobody"
                if unchanged
                else None,
                source_url=f"https://{slug}.example/roster/2026",
                unchanged=unchanged,
            ),
            LAYER_STATS: LayerOutcome(
                LAYER_STATS,
                STATE_COMPLETE,
                count=2,
                source_url=f"https://{slug}.example/stats/2026",
                unchanged=unchanged,
            ),
        },
        schedule_url=f"https://{slug}.example/schedule/2026",
        roster_url=f"https://{slug}.example/roster/2026",
        stats_url=f"https://{slug}.example/stats/2026",
        schedule_html=f"<html><body>{links}</body></html>",
        stat_players=[
            {
                "name": "Full Line",
                "player_id": "1234",
                "number": "00",
                "bio_url": f"https://{slug}.example/roster/2026/full-line",
                "gp": 3,
                "gs": 3,
                "minutes": 270,
                "goals": 2,
                "assists": 1,
                "points": 5,
                "shots": 9,
                "shot_pct": 0.222,
                "sog": 5,
                "sog_pct": 0.556,
                "game_winners": 1,
                "yellow": 1,
                "red": 0,
                "penalty_goals": 1,
                "penalty_attempts": 1,
            },
            {"name": "Bare Line"},
        ],
        stat_keepers=[
            {
                "name": "Full Line",
                "player_id": "1234",
                "number": "00",
                "bio_url": f"https://{slug}.example/roster/2026/full-line",
                "gp": 3,
                "gs": 3,
                "minutes": 270,
                "goals_against": 2,
                "gaa": 0.67,
                "saves": 11,
                "save_pct": 0.846,
                "wins": 2,
                "losses": 0,
                "ties": 1,
                "shutouts": 1,
                "shots_faced": 13,
            },
            {"name": "Bare Keeper"},
        ],
    )


def _fake_collect_match(session, url, season, fixture):
    """The real box-score parser over an archived page: writer output, not a
    hand-written stand-in."""
    del session, season, fixture
    return parse_boxscore_page(BOXSCORE_HTML.read_text(encoding="utf-8"), page_url=url)


@pytest.fixture
def collected(monkeypatch, tmp_path: Path):
    schools = [
        _school("Alpha", "GAC"),
        _school("Bravo", "GAC"),
        _school("Charlie", "LSC"),
    ]
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: schools)
    monkeypatch.setattr(collect_board, "collect_programme", _fake_programme)
    monkeypatch.setattr(collect_board, "collect_match", _fake_collect_match)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *_args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)
    fixtures, rosters, stats, matches, cells, *_ = collect_board.collect(
        season=2026,
        gender="men",
        conference="GAC",
        # "echo" has no recipe: its cells are the no-collector state.
        wanted=["alpha", "bravo", "charlie", "echo"],
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=True,
        stored_matches={},
        workers=1,
    )
    manifest = coverage.merge_cells(
        tmp_path, cells, updated_at="2026-09-02T06:30:00+00:00"
    )
    coverage.write_coverage(tmp_path, manifest)
    return {
        "fixtures": fixtures,
        "rosters": rosters,
        "stats": stats,
        "matches": matches,
        "coverage": coverage.read_coverage(tmp_path),
    }


def test_the_run_exercised_what_it_claims_to(collected) -> None:
    cells = collected["coverage"]["cells"]
    states = {cell["state"] for cell in cells.values()}
    assert states == {
        coverage.STATE_COMPLETE,
        coverage.STATE_EMPTY,
        coverage.STATE_UNAVAILABLE,
        coverage.STATE_NO_COLLECTOR,
    }
    assert cells["2026/men/bravo/schedule"]["verified"] == "unchanged"
    # The named skip rides the cell as a list; a cell without one carries no
    # key rather than an empty list.
    assert cells["2026/men/alpha/schedule"]["skips"] == [
        "hosted other-match skipped: 2026-09-05, Delta v Echo"
    ]
    assert "skips" not in cells["2026/men/bravo/schedule"]
    # Every programme here is a SideArm one (or has no recipe at all), so
    # every cell still names the SideArm collector.
    assert {cell["collector"] for cell in cells.values()} == {"sidearm-live"}
    assert collected["matches"]["matches"]
    assert collected["matches"]["missing"]


def test_coverage_writer_stays_within_its_contract(collected) -> None:
    _assert_within(collected["coverage"], contracts.COVERAGE)


def test_fixtures_writer_stays_within_its_contract(collected) -> None:
    _assert_within(collected["fixtures"], contracts.FIXTURES)


def test_rosters_writer_stays_within_its_contract(collected) -> None:
    _assert_within(collected["rosters"], contracts.ROSTERS)


def test_stats_writer_stays_within_its_contract(collected) -> None:
    _assert_within(collected["stats"], contracts.STATS)


def test_matches_writer_stays_within_its_contract(collected) -> None:
    _assert_within(collected["matches"], contracts.MATCHES)


def test_a_new_marker_is_caught_here_not_on_the_published_build(collected) -> None:
    """The regression, replayed: a writer that starts stamping a value the
    fixture never promised must fail this suite."""
    manifest = json.loads(json.dumps(collected["coverage"]))
    cell = next(iter(manifest["cells"].values()))
    cell["verified"] = "fresh"
    found = contracts.drift(manifest, contracts.COVERAGE)
    assert found == {(("cells", contracts.KEY, "verified"), "value:fresh")}

    cell.pop("verified")
    cell["etag"] = "abc"
    found = contracts.drift(manifest, contracts.COVERAGE)
    assert found == {(("cells", contracts.KEY, "etag"), "string")}


# Every fixture field the writer may leave out, per contracts/fixtures-2.json:
# present on some of its rows and not on others.  A field absent from a row is
# a fact about what the page published; null is never a value in
# touchline.fixtures/2, and a writer that starts stamping one has drifted.
OPTIONAL_FIXTURE_FIELDS = (
    "time",
    "venue",
    "match_type",
    "neutral",
    "forfeit",
    "conference_game_source",
    "home_score",
    "away_score",
)


def test_the_contract_fixture_leaves_each_optional_field_out_somewhere() -> None:
    rows = contracts.FIXTURES.fixture()["fixtures"]
    for field in OPTIONAL_FIXTURE_FIELDS:
        assert any(field not in row for row in rows), field
        assert any(field in row for row in rows), field
    assert not any(value is None for row in rows for value in row.values())


def test_fixtures_writer_omits_an_optional_field_rather_than_writing_null(
    collected,
) -> None:
    """The absent case, which drift() cannot see by construction: an omitted
    key exhibits no fact.  So assert it directly — a non-neutral row carries
    no neutral key at all (tl-0p1), and the same for every optional field."""
    rows = collected["fixtures"]["fixtures"]
    assert rows
    for field in OPTIONAL_FIXTURE_FIELDS:
        assert any(field not in row for row in rows), f"{field} is never omitted"
    assert any(row.get("neutral") is True for row in rows)
    assert all(row["neutral"] is True for row in rows if "neutral" in row)
    for row in rows:
        assert None not in row.values(), f"{row['id']} writes null: {row}"


def test_a_null_optional_field_is_drift(collected) -> None:
    """A writer that stamps neutral: null on the ordinary row must fail here,
    because null is not a value the fixture promises for any field."""
    document = json.loads(json.dumps(collected["fixtures"]))
    row = next(r for r in document["fixtures"] if "neutral" not in r)
    row["neutral"] = None
    found = contracts.drift(document, contracts.FIXTURES)
    assert found == {(("fixtures", contracts.ITEM, "neutral"), "null")}


# ── a real data home, when one is offered ────────────────────────────────────

DATA_DIR = os.environ.get("TOUCHLINE_CONTRACT_DATA_DIR")


@pytest.mark.skipif(
    not DATA_DIR, reason="set TOUCHLINE_CONTRACT_DATA_DIR to check a real data home"
)
@pytest.mark.parametrize(
    "contract",
    [c for c in contracts.CONTRACTS if c is not contracts.MEMBERSHIP],
    ids=lambda c: c.name,
)
def test_a_real_data_home_stays_within_the_contracts(
    contract: contracts.Contract,
) -> None:
    root = Path(str(DATA_DIR)).expanduser()
    if contract is contracts.COVERAGE:
        files = [coverage.coverage_path(root)]
    else:
        files = sorted((root / "data" / contract.name).glob("*.json"))
    assert files, f"no {contract.name} files under {root}"
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        found = contracts.drift(document, contract)
        assert not found, f"{path}:\n{contracts.describe(found)}"
