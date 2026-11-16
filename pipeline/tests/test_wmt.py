"""Tests for what the pipeline knows about WMT Digital athletics sites.

Every body below is a capture from the 2026-11-15 reconnaissance
(``d1-soccer/data/scratch/authoring/wmt``), copied into tests/fixtures: the
``wmt.games`` answers exactly as served (``{"__gz": base64}`` wrapper and
all), the site API answers whole, and the Nuxt season pages trimmed to their
title and ``__NUXT_DATA__`` payload, both verbatim.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import collect_board
from src import wmt
from src.config import SchoolConfig, load_schools
from src.membership import load_membership
from src.page_state import BoxArchive, PageStateStore
from src.recipes import LIVE_COLLECTORS, WMT, live_recipe
from src.sidearm_live import (
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    STATE_UNAVAILABLE,
    LiveCollectionError,
    PublishedPage,
    ResolutionScope,
    assert_served_body,
    collect_programme,
    write_raw_pages,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fresh_generations(monkeypatch) -> None:
    """Each test meets its sites for the first time."""
    monkeypatch.setattr(wmt, "_GENERATIONS", {})


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


ORIGIN = "https://goseattleu.com"
BASE = f"{ORIGIN}/sports/mens-soccer"
STATS_ORIGIN = "https://wmt.games"
SCHEDULE_URL = f"{BASE}/schedule/season/2025"
ROSTER_URL = f"{BASE}/roster/season/2025"
STATS_URL = f"{BASE}/stats/season/2025"
EVENTS_URL = wmt.events_url(ORIGIN, 75)
TEAM_URL = wmt.team_season_url(STATS_ORIGIN, 604058)
GAME_URL = wmt.game_url(STATS_ORIGIN, 6412291)

SCHEDULE_PAGE = _fixture("wmt_seattleu_schedule_2025.html")
ROSTER_PAGE = _fixture("wmt_seattleu_roster_2025.html")
STATS_PAGE = _fixture("wmt_seattleu_stats_2025.html")
NOT_FOUND = _fixture("wmt_seattleu_schedule_1999_404.html")
EVENTS = _fixture("wmt_seattleu_events_2025.json")
TEAM = _fixture("wmt_games_team_604058.json")
GAME = _fixture("wmt_games_game_6412291.json")
THIN_GAME = _fixture("wmt_games_game_6487961_thin.json")
ODU_TEAM = _fixture("wmt_games_team_587798_odu.json")


class _Site:
    """A WMT site and its statistics host, answering each URL with its
    captured body; any other URL is an honest 404.  A ``wmt.games`` body
    carries an ETag, and a request naming it in ``If-None-Match`` is
    answered 304, as the host does."""

    def __init__(
        self, pages: dict[str, str], *, etags: dict[str, str] | None = None
    ) -> None:
        self.pages = pages
        self.etags = etags or {}
        self.requests: list[tuple[str, object]] = []
        self.paced: list[str] = []

    def presume_paced(self, url: str) -> None:
        self.paced.append(url)

    def get(self, url: str, timeout: int | None = None, headers: object = None):
        del timeout
        self.requests.append((url, headers))
        etag = self.etags.get(url)
        if url not in self.pages:
            return SimpleNamespace(
                status_code=404,
                url=url,
                text=NOT_FOUND,
                headers={},
                raise_for_status=lambda: None,
            )
        if etag and isinstance(headers, dict) and headers.get("If-None-Match") == etag:
            return SimpleNamespace(
                status_code=304,
                url=url,
                text="",
                headers={"ETag": etag},
                raise_for_status=lambda: None,
            )
        return SimpleNamespace(
            status_code=200,
            url=url,
            text=self.pages[url],
            headers={"ETag": etag} if etag else {},
            raise_for_status=lambda: None,
        )

    def urls(self) -> list[str]:
        return [url for url, _ in self.requests]


def _seattle_site(**extra: str) -> _Site:
    return _Site(
        {
            SCHEDULE_URL: SCHEDULE_PAGE,
            ROSTER_URL: ROSTER_PAGE,
            STATS_URL: STATS_PAGE,
            EVENTS_URL: EVENTS,
            TEAM_URL: TEAM,
            GAME_URL: GAME,
            **extra,
        },
        etags={TEAM_URL: 'W/"team-604058"', GAME_URL: 'W/"game-6412291"'},
    )


def _seattle() -> SchoolConfig:
    return SchoolConfig(
        name="Seattle U",
        abbreviation="SU",
        conference="WCC",
        prefix="",
        base_url=BASE,
        gender="men",
        scraper="wmt",
        live_scraper="wmt",
        enabled=True,
    )


def _layer(kind: str, site: _Site | None = None) -> str:
    return wmt.fetch_layer(site or _seattle_site(), BASE, 2025, kind).page.html


def _schedule(**kwargs) -> list[dict[str, object]]:
    return wmt.parse_schedule(
        _layer(LAYER_SCHEDULE),
        page_url=SCHEDULE_URL,
        year=2025,
        owner_slug="seattle-u",
        aliases={},
        **kwargs,
    )


# --- The recipe and the seam ---------------------------------------------------


def test_the_wmt_recipe_is_registered_under_its_platform() -> None:
    assert LIVE_COLLECTORS["wmt"] is WMT
    assert live_recipe(_seattle().live_collector()) is WMT
    assert WMT.fetch_layer is not None
    assert collect_board.COLLECTORS["wmt"] == "wmt-live"
    assert WMT.layer_url(BASE, 2025, LAYER_SCHEDULE) == SCHEDULE_URL
    # The sport path is the stanza's own, never assumed.
    assert wmt.sport_base("https://gamecocksonline.com/sports/msoc/") == (
        "https://gamecocksonline.com",
        "msoc",
        "https://gamecocksonline.com/sports/msoc",
    )
    with pytest.raises(LiveCollectionError, match="not a WMT sport landing page"):
        wmt.sport_base("https://goseattleu.com/")


def test_a_gz_wrapped_body_is_decoded_at_parse_time_and_archived_as_served() -> None:
    # Measured: 13 of 14 wmt.games answers are the wrapper, one plain.
    assert set(json.loads(GAME)) == {"__gz"}
    assert wmt.decode_json_body(GAME, GAME_URL)["header"]["gameId"] == 6412291
    assert set(json.loads(THIN_GAME)) != {"__gz"}
    assert wmt.decode_json_body(THIN_GAME, "thin")["header"]["gameId"] == 6487961
    bundle = wmt.read_bundle(_layer(LAYER_STATS))
    season = bundle.first("season")
    assert season is not None and season.body == TEAM  # verbatim, still wrapped
    with pytest.raises(LiveCollectionError, match="does not decode"):
        wmt.decode_json_body('{"__gz": "bm90IGd6aXA="}', "x")


def test_the_served_body_check_refuses_a_challenge_in_place_of_json() -> None:
    def answer(status: int, text: str) -> SimpleNamespace:
        return SimpleNamespace(status_code=status, text=text)

    assert_served_body(answer(200, GAME), year=2025, kind="box", url="u", body="json")
    with pytest.raises(LiveCollectionError, match="not a JSON document") as refused:
        assert_served_body(
            answer(200, "<html><body>Just a moment</body></html>"),
            year=2025,
            kind="box",
            url="u",
            body="json",
        )
    assert refused.value.status == 200
    with pytest.raises(LiveCollectionError, match="HTTP 202 with a JSON body"):
        assert_served_body(
            answer(202, "{}"), year=2025, kind="box", url="u", body="json"
        )
    with pytest.raises(LiveCollectionError, match="empty body"):
        assert_served_body(
            answer(200, " "), year=2025, kind="box", url="u", body="json"
        )
    # The HTML default is the check SideArm and PrestoSports always had:
    # a JSON body is still no page there.
    with pytest.raises(LiveCollectionError, match="carrying no HTML"):
        assert_served_body(answer(200, GAME), year=2025, kind="schedule", url="u")
    with pytest.raises(ValueError):
        assert_served_body(answer(200, GAME), year=2025, kind="x", url="u", body="xml")


# --- Schedule ------------------------------------------------------------------


def test_the_schedule_layer_bundles_the_proven_page_and_its_event_list() -> None:
    site = _seattle_site()
    fetched = wmt.fetch_layer(site, BASE, 2025, LAYER_SCHEDULE)
    bundle = wmt.read_bundle(fetched.page.html)
    assert [part.role for part in bundle.parts] == ["page", "events"]
    assert bundle.parts[0].body == SCHEDULE_PAGE
    assert bundle.parts[1].body == EVENTS
    assert fetched.page.final_url == SCHEDULE_URL
    # Every played match carrying its game id, no Game by Game join is needed.
    assert site.urls() == [SCHEDULE_URL, EVENTS_URL]


def test_kickoffs_are_dated_in_the_sites_own_timezone_not_utc() -> None:
    """Trap 6.1: Seattle U at Missouri State is ``2025-08-22T00:00Z``, the
    evening of the 21st in Seattle (and the 21st on the box score)."""
    fixtures = {fixture["id"]: fixture for fixture in _schedule()}
    missouri = fixtures["wmt:seattle-u:2077"]
    assert (missouri["date"], missouri["time"]) == ("2025-08-21", "17:00")
    raw = {event["id"]: event for event in json.loads(EVENTS)["data"]}
    assert raw[2077]["datetime"] == "2025-08-22T00:00:00.000000Z"
    utc_dates = sum(
        1
        for event in raw.values()
        if event["datetime"][:10] != fixtures[f"wmt:seattle-u:{event['id']}"]["date"]
    )
    assert utc_dates == 13  # FINDINGS 6.1: wrong for 13 of Seattle U's matches


def test_schedule_rows_carry_published_flags_scores_and_absence() -> None:
    fixtures = _schedule()
    assert len(fixtures) == 19
    by_id = {fixture["id"]: fixture for fixture in fixtures}
    missouri = by_id["wmt:seattle-u:2077"]
    assert missouri == {
        "id": "wmt:seattle-u:2077",
        "date": "2025-08-21",
        "home": "missouri-state",
        "away": "seattle-u",
        "status": "final",
        "source_url": SCHEDULE_URL,
        "conference_game": False,
        "time": "17:00",
        "venue": "Springfield, MO",
        "home_score": 4,
        "away_score": 1,
    }
    # The two exhibitions: flagged as published, final, and with no score,
    # because the site published ``no_result`` (never a 0-0).
    exhibitions = [
        fixture for fixture in fixtures if fixture.get("match_type") == "exhibition"
    ]
    assert [fixture["id"] for fixture in exhibitions] == [
        "wmt:seattle-u:2081",
        "wmt:seattle-u:2074",
    ]
    assert all("home_score" not in fixture for fixture in exhibitions)
    # Conference flags are the site's, carried with no derived-source stamp.
    published = {
        event["id"]: event["is_conference"] for event in json.loads(EVENTS)["data"]
    }
    assert {fixture["id"]: fixture["conference_game"] for fixture in fixtures} == {
        f"wmt:seattle-u:{event_id}": flag for event_id, flag in published.items()
    }
    assert sum(published.values()) > 0
    assert not any("conference_game_source" in fixture for fixture in fixtures)


def test_a_neutral_site_row_is_venue_type_neutral_with_the_events_own_sides() -> None:
    """Virginia 2025 holds two neutral-site matches; ``neutral_event`` is
    false on both (false on every event measured), ``venue_type`` is
    ``neutral``."""
    fixtures = _virginia_schedule()
    neutral = [fixture for fixture in fixtures if fixture.get("neutral")]
    assert [fixture["id"] for fixture in neutral] == [
        "wmt:virginia:314",
        "wmt:virginia:321",
    ]
    events = {
        event["id"]: event
        for event in json.loads(_fixture("wmt_virginia_events_2025.json"))["data"]
    }
    assert {events[314]["neutral_event"], events[321]["neutral_event"]} == {False}
    # Ranked opponents print their ranking ("(12) California"): dropped.
    assert neutral[0]["away"] == "california"
    assert all(fixture.get("neutral") is not False for fixture in fixtures)


def test_a_season_page_must_prove_men_soccer_and_the_requested_season() -> None:
    # Seattle U's 2025 page served at the 2023 address is not the 2023 season.
    site = _Site({f"{BASE}/schedule/season/2023": SCHEDULE_PAGE})
    with pytest.raises(LiveCollectionError, match="season 2025"):
        wmt.fetch_layer(site, BASE, 2023, LAYER_SCHEDULE)
    # Under another sport's path the page renders no such sport view.
    other = "https://goseattleu.com/sports/womens-soccer"
    site = _Site({f"{other}/schedule/season/2025": SCHEDULE_PAGE})
    with pytest.raises(
        LiveCollectionError, match="no sport view for /sports/womens-soccer"
    ):
        wmt.fetch_layer(site, other, 2025, LAYER_SCHEDULE)
    # A roster page is not a schedule page.
    site = _Site({SCHEDULE_URL: ROSTER_PAGE})
    with pytest.raises(LiveCollectionError, match="rendered roster season"):
        wmt.fetch_layer(site, BASE, 2025, LAYER_SCHEDULE)


def test_an_unfiled_season_is_an_honest_404_on_both_slugs() -> None:
    site = _Site({})
    with pytest.raises(
        LiveCollectionError, match="files no 1999 schedule season"
    ) as refused:
        wmt.fetch_layer(site, BASE, 1999, LAYER_SCHEDULE)
    assert refused.value.status == 404
    assert site.urls() == [
        f"{BASE}/schedule/season/1999",
        f"{BASE}/schedule/season/1999-00",
    ]


VIRGINIA = "https://virginiasports.com/sports/msoc"


def _virginia_site() -> _Site:
    return _Site(
        {
            f"{VIRGINIA}/schedule/season/2025-26": _fixture(
                "wmt_virginia_schedule_2025-26.html"
            ),
            wmt.events_url("https://virginiasports.com", 15): _fixture(
                "wmt_virginia_events_2025.json"
            ),
        }
    )


def _virginia_schedule() -> list[dict[str, object]]:
    return wmt.parse_schedule(
        wmt.fetch_layer(_virginia_site(), VIRGINIA, 2025, LAYER_SCHEDULE).page.html,
        page_url=f"{VIRGINIA}/schedule/season/2025-26",
        year=2025,
        owner_slug="virginia",
        aliases={},
    )


def test_a_site_filing_the_season_by_academic_year_is_found_after_an_honest_404(
    caplog,
) -> None:
    """Virginia answers 404 at ``/season/2025`` and files fall 2025 as
    ``2025-26``.  Its played 2025 match without a game id (event 321) needs
    the Game by Game join; the statistics host is unavailable here, so the
    schedule stands and the join is named as unavailable."""
    site = _virginia_site()
    with caplog.at_level(logging.WARNING, logger="src.wmt"):
        fetched = wmt.fetch_layer(site, VIRGINIA, 2025, LAYER_SCHEDULE)
    assert site.urls()[:2] == [
        f"{VIRGINIA}/schedule/season/2025",
        f"{VIRGINIA}/schedule/season/2025-26",
    ]
    bundle = wmt.read_bundle(fetched.page.html)
    assert fetched.page.final_url == f"{VIRGINIA}/schedule/season/2025-26"
    assert [part.role for part in bundle.parts] == ["page", "events"]
    assert any("Game by Game join unavailable" in note for note in bundle.notes)
    assert "Game by Game join is unavailable" in caplog.text
    fixtures = _virginia_schedule()
    assert len(fixtures) == 20
    links = wmt.boxscore_links(fetched.page.html, "")
    assert "321" not in links and len(links) == 18


def test_penn_states_fall_schedule_is_the_plain_year_never_a_prefix_match() -> None:
    """Trap 6.3: Penn State lists ``2025`` (its 20-event fall schedule, id
    984) and ``2025-26`` (a 5-event spring one, id 1174); both start with
    the year."""
    listed = json.loads(_fixture("wmt_pennstate_schedules.json"))["data"]
    slugs = [schedule["season"]["slug"] for schedule in listed]
    assert "2025" in slugs and "2025-26" in slugs
    assert slugs.index("2025-26") < slugs.index(
        "2025"
    )  # a prefix match finds spring first
    assert wmt.pick_season_slug(slugs, 2025) == "2025"
    assert wmt.pick_season_slug([s for s in slugs if s != "2025"], 2025) == "2025-26"
    assert wmt.season_slugs(2025) == ("2025", "2025-26")
    # The fall events prove schedule 984 and refuse to stand for 1174.
    events = json.loads(_fixture("wmt_pennstate_events_984.json"))["data"]
    proof = dict(sport="mens-soccer", year=2025, timezone="America/New_York", url="u")
    wmt.prove_events(events, schedule_id=984, **proof)
    with pytest.raises(LiveCollectionError, match="not schedule 1174"):
        wmt.prove_events(events, schedule_id=1174, **proof)
    # And when the plain year is served, the academic year is never asked.
    site = _seattle_site()
    wmt.fetch_layer(site, BASE, 2025, LAYER_SCHEDULE)
    assert f"{BASE}/schedule/season/2025-26" not in site.urls()


def test_an_event_list_must_be_the_proven_schedules_sport_and_season() -> None:
    events = json.loads(EVENTS)["data"]
    proof = dict(schedule_id=75, year=2025, timezone="America/Los_Angeles", url="u")
    wmt.prove_events(events, sport="mens-soccer", **proof)
    with pytest.raises(
        LiveCollectionError, match="does not name the womens-soccer sport"
    ):
        wmt.prove_events(events, sport="womens-soccer", **proof)
    # Trap 6.8: a season runs into the next calendar year, never two on.
    spring = copy.deepcopy(events[:1])
    spring[0]["datetime"] = "2026-04-11T20:00:00.000000Z"
    wmt.prove_events(spring, sport="mens-soccer", **proof)
    spring[0]["datetime"] = "2027-04-11T20:00:00.000000Z"
    with pytest.raises(LiveCollectionError, match="outside the 2025 season"):
        wmt.prove_events(spring, sport="mens-soccer", **proof)


def test_a_played_match_without_a_game_id_is_joined_by_its_local_date() -> None:
    """Trap 6.6 on Seattle U's own capture: event 2076 (at North Carolina,
    2025-08-24, game 6416865) with its game id withheld, as Clemson,
    Virginia, UCF and ODU withhold some.  The team is read off the first
    linked game's header (6412291, Seattle U the away side) and its Game by
    Game table supplies 6416865 by the match's local date."""
    events = json.loads(EVENTS)
    for event in events["data"]:
        if event["id"] == 2076:
            assert event["wmt_stats2_game_id"] == 6416865
            event["wmt_stats2_game_id"] = None
    site = _seattle_site(**{EVENTS_URL: json.dumps(events)})
    html = wmt.fetch_layer(site, BASE, 2025, LAYER_SCHEDULE).page.html
    bundle = wmt.read_bundle(html)
    assert [part.role for part in bundle.parts] == ["page", "events", "game", "season"]
    assert [part.url for part in bundle.parts[2:]] == [GAME_URL, TEAM_URL]
    links = wmt.boxscore_links(html, SCHEDULE_URL)
    assert links["2076"] == wmt.game_url(STATS_ORIGIN, 6416865)
    assert links["2077"] == GAME_URL
    # The two no_result exhibitions published no match to link.
    assert "2081" not in links and "2074" not in links
    assert site.paced == [GAME_URL, TEAM_URL]


def test_the_date_join_refuses_a_day_with_two_candidate_games() -> None:
    events = json.loads(EVENTS)
    for event in events["data"]:
        if event["id"] == 2076:
            event["wmt_stats2_game_id"] = None
    season = wmt.decode_json_body(TEAM, TEAM_URL)
    rows = wmt.game_by_game(season)
    assert len(rows) == 17 and ("2025-08-24", 6416865) in [row[:2] for row in rows]
    bundle = wmt.Bundle(
        LAYER_SCHEDULE,
        2025,
        wmt.GENERATION_NUXT,
        (
            wmt.Part("page", SCHEDULE_URL, SCHEDULE_URL, 200, SCHEDULE_PAGE),
            wmt.Part("events", EVENTS_URL, EVENTS_URL, 200, json.dumps(events)),
        ),
    )
    doubled = copy.deepcopy(season)
    for path, table in wmt._walk_tables(doubled["tabs"]):
        if path[0] == "Game by Game":
            row = next(
                r
                for r in table["body"]
                if wmt._text(wmt._cells(r).get("gameDate")) == "08/24/2025"
            )
            twin = copy.deepcopy(row)
            wmt._cells(twin)["gameDate"]["meta"]["gameId"] = 1
            table["body"].append(twin)
    for body, linked in ((season, True), (doubled, False)):
        parts = (
            *bundle.parts,
            wmt.Part("season", TEAM_URL, TEAM_URL, 200, json.dumps(body)),
        )
        html = wmt.Bundle(LAYER_SCHEDULE, 2025, wmt.GENERATION_NUXT, parts).text()
        assert ("2076" in wmt.boxscore_links(html, "")) is linked


def _archived_schedule(
    name: str, *, owner: str, conference: str, year: int
) -> tuple[dict[str, dict[str, object]], ResolutionScope]:
    """An archived schedule bundle, trimmed to the page's title and timezone
    and a few events (verbatim), parsed with the real Division I identity
    the collect resolves with."""
    aliases, members, scope = collect_board.collect_identity(
        load_schools(), "men", conference, year, document=load_membership()
    )
    html = _fixture(name)
    fixtures = wmt.parse_schedule(
        html,
        page_url=wmt.read_bundle(html).final_url,
        year=year,
        owner_slug=owner,
        aliases=aliases,
        members=members,
        scope=scope,
    )
    return {str(fixture["id"]): fixture for fixture in fixtures}, scope


def _opponent(fixture: dict[str, object], owner: str) -> object:
    return fixture["away"] if fixture["home"] == owner else fixture["home"]


def test_a_nickname_printed_where_the_school_belongs_reads_the_records_school() -> None:
    """fightingirish.com 2023: the opponent record of most events is swapped,
    ``name`` (and so ``opponent_name``) "Tar Heels" and ``long_name`` (and
    ``opponent_school_name``) "North Carolina"; the exhibitions and Indiana
    keep the other order ("Indiana" / "Hoosiers").  Each swapped event filed
    a stranger (tar-heels) beside the real programme's own row of the match."""
    by_id, scope = _archived_schedule(
        "wmt_notredame_schedule_bundle_2023.json",
        owner="notre-dame",
        conference="ACC",
        year=2023,
    )
    opponents = {key: _opponent(row, "notre-dame") for key, row in by_id.items()}
    assert opponents == {
        # Swapped: the printed nickname names no programme; the record's
        # other name names exactly one.
        "wmt:notre-dame:2351": "iu-indy",  # "Jaguars" / "IUPUI"
        "wmt:notre-dame:2340": "north-carolina",  # "Tar Heels"
        # The round annotation rides on the school name and is folded off.
        "wmt:notre-dame:2071": "louisville",  # "Cardinals" / "Louisville (ACC ...)"
        # The other order: a printed name that resolves is never rewritten.
        "wmt:notre-dame:2352": "indiana",  # "Indiana" / "Hoosiers"
        "wmt:notre-dame:2347": "saint-louis",  # "Saint Louis (Exhibition)"
        # Both names alike: nothing to choose.
        "wmt:notre-dame:2063": "kentucky",  # "Kentucky (NCAA 2nd Round)"
        # Neither name is a Division I programme (Oberlin): nothing says
        # which is the school, so the printed text stands, named in the log.
        "wmt:notre-dame:2338": "yeomen",
    }
    assert by_id["wmt:notre-dame:2347"]["match_type"] == "exhibition"
    notes = scope.notes()
    assert any(
        "'Tar Heels' on notre-dame's page names no programme; read as "
        "'North Carolina' (north-carolina)" in line
        for line in notes
    )
    assert any(
        "'Yeomen' on notre-dame's page (2023-10-10) kept as printed; its "
        "opponent record also names 'Oberlin', and neither names a programme" in line
        for line in notes
    )
    assert not any("'Indiana'" in line or "'Hoosiers'" in line for line in notes)


def test_a_record_whose_other_name_is_formal_or_overridden_changes_nothing() -> None:
    """odusports.com 2024, a site not affected: ``long_name`` is the formal
    name ("University of Maryland-College Park", "College of William and
    Mary") and ``opponent_school_name`` a short one ("W&M"); the printed
    names resolve, so neither is read.  "UMBC" is the event's own override
    of a record named "Maryland-Baltimore-County": the printed text is not
    the record's name, so the record is not consulted."""
    by_id, scope = _archived_schedule(
        "wmt_olddominion_schedule_bundle_2024.json",
        owner="old-dominion",
        conference="SUNBELT",
        year=2024,
    )
    opponents = {key: _opponent(row, "old-dominion") for key, row in by_id.items()}
    assert opponents == {
        "wmt:old-dominion:13573": "uncw",  # "UNCW" / "UNC Wilmington"
        "wmt:old-dominion:13574": "maryland",
        "wmt:old-dominion:13580": "umbc",
        "wmt:old-dominion:13581": "william-mary",
    }
    assert not [line for line in scope.notes() if "old-dominion's page" in line]
    # Without an identity nothing resolves, and nothing is rewritten either.
    html = _fixture("wmt_notredame_schedule_bundle_2023.json")
    bare = wmt.parse_schedule(
        html, page_url="", year=2023, owner_slug="notre-dame", aliases={}
    )
    assert "tar-heels" in {_opponent(row, "notre-dame") for row in bare}


# --- Roster ---------------------------------------------------------------------


def test_the_roster_is_read_from_the_page_payload() -> None:
    players = wmt.parse_roster(_layer(LAYER_ROSTER), page_url=ROSTER_URL)
    assert len(players) == 29
    assert players[0] == {
        "name": "Davis Mungomba",
        "number": "5",
        "position": "Defender",
        "height": "6'1\"",
        "hometown": "Bergisch, Gladbach",
        "class_year": "Redshirt Senior",
        "source_url": f"{ROSTER_URL}/player/davis-mungomba",
    }
    # Weight is published for seven players; the rest omit it, never 0 lbs.
    assert sum(1 for player in players if "weight" in player) == 7
    assert all(player.get("weight") != "0 lbs" for player in players)


# --- Season statistics ----------------------------------------------------------


def test_season_statistics_come_from_the_proven_team_season() -> None:
    players, keepers = wmt.parse_stats(_layer(LAYER_STATS), page_url=STATS_URL)
    assert (len(players), len(keepers)) == (26, 2)
    assert players[0] == {
        "name": "Yeider Zuluaga",
        "number": "17",
        "gp": 13,
        "gs": 13,
        "minutes": 909,
        "goals": 9,
        "assists": 5,
        "points": 23,
        "shots": 30,
        "shot_pct": 0.3,
        "sog": 16,
        "sog_pct": 0.533,
        "game_winners": 2,
        "yellow": 3,
        "red": 0,
    }
    assert keepers[0]["name"] == "Charlie Lanphier"
    assert (
        keepers[0]["goals_against"],
        keepers[0]["saves"],
        keepers[0]["shutouts"],
    ) == (27, 53, 4)
    names = {line["name"].lower() for line in players + keepers}
    assert not names & {"team", "totals", "opponents"}
    assert not any("player_id" in line for line in players + keepers)


def test_a_previous_seasons_statistics_team_is_refused_by_academic_year() -> None:
    """Trap 6.4: Old Dominion's 2025 roster carries 587798, which is its
    2024-25 team (``academicYear: 2025``)."""
    season = wmt.decode_json_body(ODU_TEAM, "odu")
    with pytest.raises(
        LiveCollectionError, match=r"2024-25 season \(academicYear 2025\)"
    ):
        wmt.prove_team_season(season, team_id=587798, year=2025, url="odu")
    wmt.prove_team_season(season, team_id=587798, year=2024, url="odu")
    seattle = wmt.decode_json_body(TEAM, TEAM_URL)
    wmt.prove_team_season(seattle, team_id=604058, year=2025, url=TEAM_URL)
    with pytest.raises(LiveCollectionError, match="served team 604058"):
        wmt.prove_team_season(seattle, team_id=604059, year=2025, url=TEAM_URL)


CLEMSON = "https://clemsontigers.com/sports/mens-soccer"
CLEMSON_TEAM_URL = wmt.team_season_url(STATS_ORIGIN, 603879)


def _clemson_site(*, roster_team: object, monkeypatch) -> _Site:
    """Clemson's 2025 statistics page with its season roster's team id
    replaced by ``roster_team``: ``None`` is Clemson 2026's own state (trap
    6.5), 587798 Old Dominion's wrong team (trap 6.4), whose real body the
    statistics host answers."""
    real = wmt._nuxt_state

    def state(html: str):
        decoded = real(html)
        roster = decoded.get("data", {}).get("sport-mens-soccer-roster-season-2025")
        if isinstance(roster, dict):
            roster["wmt_stats2_team_id"] = roster_team
        return decoded

    monkeypatch.setattr(wmt, "_nuxt_state", state)
    return _Site(
        {
            f"{CLEMSON}/stats/season/2025": _fixture("wmt_clemson_stats_2025.html"),
            wmt.events_url("https://clemsontigers.com", 4): _fixture(
                "wmt_clemson_events_2025.json"
            ),
            wmt.game_url(STATS_ORIGIN, 6391102): _fixture(
                "wmt_games_game_6391102.json"
            ),
            CLEMSON_TEAM_URL: _fixture("wmt_games_team_603879.json"),
            wmt.team_season_url(STATS_ORIGIN, 587798): ODU_TEAM,
        }
    )


@pytest.mark.parametrize("roster_team", [None, 587798])
def test_a_missing_or_wrong_statistics_team_is_recovered_from_a_game_header(
    roster_team: object, monkeypatch
) -> None:
    site = _clemson_site(roster_team=roster_team, monkeypatch=monkeypatch)
    fetched = wmt.fetch_layer(site, CLEMSON, 2025, LAYER_STATS)
    bundle = wmt.read_bundle(fetched.page.html)
    roles = [part.role for part in bundle.parts]
    expected = ["page", "events", "game", "season"]
    if roster_team is not None:
        expected.insert(1, "season-refused")
    assert roles == expected
    # Clemson was the away side of 6391102 (at Indiana): its teamId names it.
    assert bundle.first("season").url == CLEMSON_TEAM_URL
    assert "recovered from a game header" in bundle.notes[0]
    players, keepers = wmt.parse_stats(fetched.page.html, page_url="")
    assert players and keepers


# --- Box scores -------------------------------------------------------------------


def _missouri() -> dict[str, object]:
    return next(
        fixture for fixture in _schedule() if fixture["id"] == "wmt:seattle-u:2077"
    )


def test_a_box_score_is_proven_parsed_and_archived_verbatim(tmp_path: Path) -> None:
    site = _seattle_site()
    store = PageStateStore(tmp_path, 2025, "men")
    archive = BoxArchive(store, "seattle-u", "wmt:seattle-u:2077", "fingerprint")
    detail = wmt.collect_match(site, GAME_URL, 2025, _missouri(), archive=archive)
    assert site.paced == [GAME_URL]
    assert [team["name"] for team in detail["teams"]] == ["Seattle U", "Missouri St."]
    assert [team["score"] for team in detail["teams"]] == [1, 4]
    assert detail["home_index"] == 1
    assert detail["teams"][1]["winner"] is True
    assert detail["teams"][0]["periods"] == [1, 0]
    assert (detail["teams"][0]["shots"], detail["teams"][0]["sog"]) == (5, 4)
    assert [(goal["scorer"], goal["team"]) for goal in detail["scoring"]] == [
        ("Fumiya Shiraishi", 1),
        ("Yeider Zuluaga", 0),
        ("Fumiya Shiraishi", 1),
        ("Fumiya Shiraishi", 1),
        ("Fumiya Shiraishi", 1),
    ]
    assert detail["scoring"][3]["assist"] == "Jared Harlock, Ollie Bate"
    assert detail["cards"][0] == {
        "type": "yellow",
        "player": "Dylan Wojdyla",
        "number": "4",
        "time": "34:36",
        "team": 0,
    }
    goals = [play for play in detail["plays"] if play.get("type") == "goal"]
    assert [play["score"] for play in goals] == [[0, 1], [1, 1], [1, 2], [1, 3], [1, 4]]
    assert {play["period"] for play in detail["plays"]} == {"1", "2"}
    starters = [p for p in detail["teams"][0]["players"] if p["started"]]
    assert len(starters) == 11 and starters[1]["minutes"] == 84
    assert detail["teams"][0]["keepers"] == [
        {
            "name": "Charlie Lanphier",
            "position": "GK",
            "number": "1",
            "minutes": 90,
            "goals_against": 4,
            "saves": 1,
        }
    ]
    assert (detail["stadium"], detail["attendance"]) == (
        "Betty and Bobby Allison South Stadium",
        620,
    )
    stored = store.html_path("seattle-u", archive.kind).read_text(encoding="utf-8")
    assert stored == GAME  # the __gz wrapper as served
    # The archived page proves and parses exactly as the served one did.
    again = WMT.parse_match(
        PublishedPage(GAME_URL, GAME_URL, stored), 2025, _missouri()
    )
    assert again == detail


def test_a_box_score_date_is_read_as_printed_never_converted() -> None:
    """Trap 6.2: ``gameDate`` ``2025-08-21T19:30:00.000Z`` is 7:30 PM in
    Springfield labelled Z.  The fixture's date is the 21st; a fixture that
    took the schedule's UTC date (the 22nd) is refused."""
    page = PublishedPage(GAME_URL, GAME_URL, GAME)
    wmt.assert_served_match(page, 2025, _missouri())
    utc_dated = {**_missouri(), "date": "2025-08-22"}
    with pytest.raises(LiveCollectionError, match="is dated 2025-08-21"):
        wmt.assert_served_match(page, 2025, utc_dated)


def test_a_box_score_must_be_the_requested_game_and_name_both_sides() -> None:
    wrong_id = PublishedPage(wmt.game_url(STATS_ORIGIN, 6416865), GAME_URL, GAME)
    with pytest.raises(LiveCollectionError, match="requested game 6416865"):
        wmt.assert_served_match(wrong_id, 2025, _missouri())
    other = {**_missouri(), "home": "north-carolina"}
    with pytest.raises(LiveCollectionError, match="does not name both"):
        wmt.assert_served_match(PublishedPage(GAME_URL, GAME_URL, GAME), 2025, other)


def test_a_thin_box_score_yields_what_it_has_and_names_what_it_lacks(caplog) -> None:
    """Trap 6.7: 6487961 (Kentucky 0-0 Coastal Carolina, decided on
    penalties) publishes Team Statistics and the Individual tables only."""
    fixture = {
        "id": "wmt:kentucky:9001",
        "date": "2025-11-09",
        "home": "kentucky",
        "away": "coastal-carolina",
        "home_score": 0,
        "away_score": 0,
    }
    url = wmt.game_url(STATS_ORIGIN, 6487961)
    with caplog.at_level(logging.WARNING, logger="src.wmt"):
        detail = wmt.parse_match_page(PublishedPage(url, url, THIN_GAME), 2025, fixture)
    assert [team["score"] for team in detail["teams"]] == [0, 0]
    assert all(team.get("players") for team in detail["teams"])
    assert not {"scoring", "cards", "plays"} & set(detail)
    assert (
        "publishes no play-by-play, no scoring summary, no cautions and ejections"
        in caplog.text
    )
    assert wmt.thin_box_lacks(wmt.decode_json_body(GAME, GAME_URL)) == []


# --- Conditional fetches and the collectors ------------------------------------


def test_a_second_fetch_asks_the_statistics_host_with_its_etag_and_reuses_the_archive(
    tmp_path: Path,
) -> None:
    store = PageStateStore(tmp_path, 2025, "men")
    site = _seattle_site()
    first = wmt.fetch_layer(site, BASE, 2025, LAYER_STATS, want_validators=True)
    store.save_html("seattle-u", LAYER_STATS, first.page.html)
    store.save(
        "seattle-u",
        LAYER_STATS,
        requested_url=first.page.requested_url,
        final_url=first.page.final_url,
        etag=None,
        last_modified=None,
        signature=first.signature or "",
        fingerprint="f",
        outcome_state=STATE_COMPLETE,
        outcome_count=28,
        outcome_reason=None,
        parsed={"players": [], "keepers": []},
    )
    state = store.load("seattle-u", LAYER_STATS, "f")
    site.requests.clear()
    second = wmt.fetch_layer(
        site, BASE, 2025, LAYER_STATS, state=state, want_validators=True
    )
    assert site.requests == [
        (STATS_URL, None),
        (TEAM_URL, {"If-None-Match": 'W/"team-604058"'}),
    ]
    assert second.unchanged is True
    assert second.page.html == first.page.html


def test_the_config_load_stamp_alone_does_not_change_a_bundle() -> None:
    """Two fetches of a Nuxt season page differ by one token,
    ``configLoadedAt`` (measured on goseattleu.com, 2026-11-15)."""
    stamp = "1794790366093"
    assert STATS_PAGE.count(stamp) == 1

    def signature(page: str) -> str:
        part = wmt.Part("page", STATS_URL, STATS_URL, 200, page)
        return wmt.Bundle(LAYER_STATS, 2025, wmt.GENERATION_NUXT, (part,)).signature()

    assert signature(STATS_PAGE) == signature(
        STATS_PAGE.replace(stamp, "1794794306241")
    )
    edited = STATS_PAGE.replace("Featured: Sport Page Only", "Featured")
    assert signature(STATS_PAGE) != signature(edited)


def test_a_recompressed_json_body_is_the_same_content() -> None:
    import base64
    import gzip

    decoded = wmt.decode_json_body(TEAM, TEAM_URL)
    rewrapped = json.dumps(
        {
            "__gz": base64.b64encode(
                gzip.compress(json.dumps(decoded).encode(), mtime=1)
            ).decode()
        }
    )
    assert rewrapped != TEAM

    def signature(body: str) -> str:
        part = wmt.Part("season", TEAM_URL, TEAM_URL, 200, body)
        return wmt.Bundle(LAYER_STATS, 2025, wmt.GENERATION_NUXT, (part,)).signature()

    assert signature(rewrapped) == signature(TEAM)
    decoded["team"]["wins"] = 99
    assert signature(json.dumps(decoded)) != signature(TEAM)


def test_collect_programme_collects_three_wmt_layers_and_archives_the_bundles(
    tmp_path: Path,
) -> None:
    store = PageStateStore(tmp_path, 2025, "men")
    result = collect_programme(
        _seattle(),
        2025,
        {},
        session=_seattle_site(),
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS),
        page_cache=store,
    )
    assert result.state(LAYER_SCHEDULE) == STATE_COMPLETE
    assert result.outcomes[LAYER_SCHEDULE].count == 19
    assert result.outcomes[LAYER_SCHEDULE].source_url == SCHEDULE_URL
    assert result.outcomes[LAYER_ROSTER].count == 29
    assert result.outcomes[LAYER_STATS].count == 28
    write_raw_pages(tmp_path, result, 2025, "men")
    archived = wmt.read_bundle(
        (
            tmp_path / "data" / "raw_html" / "seattle-u" / "2025-men-stats.html"
        ).read_text("utf-8")
    )
    assert archived.first("season").body == TEAM
    # A site answering 404 for the season leaves each layer a named gap.
    empty = collect_programme(
        _seattle(), 1999, {}, session=_Site({}), layers=(LAYER_ROSTER,)
    )
    assert empty.state(LAYER_ROSTER) == STATE_UNAVAILABLE
    assert "answered HTTP 404" in str(empty.outcomes[LAYER_ROSTER].reason)


def test_the_board_collector_collects_all_four_wmt_layers(
    monkeypatch, tmp_path: Path
) -> None:
    school = _seattle()
    site = _seattle_site()
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(collect_board, "build_session", lambda session=None: site)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    fixtures, rosters, stats, matches, cells, errors, _ = collect_board.collect(
        season=2025,
        gender="men",
        conference="WCC",
        wanted=["seattle-u"],
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
        workers=1,
    )

    assert {cell["collector"] for cell in cells.values()} == {"wmt-live"}
    assert {
        layer: cells[f"2025/men/seattle-u/{layer}"]["state"]
        for layer in ("schedule", "roster", "stats")
    } == {
        "schedule": "complete",
        "roster": "complete",
        "stats": "complete",
    }
    assert len(fixtures["fixtures"]) == 19
    assert len(rosters["rosters"]["seattle-u"]["players"]) == 29
    assert len(stats["teams"]["seattle-u"]["players"]) == 26
    # Only Missouri State's game is captured: one box score of 17 linked
    # matches; the other sixteen are named gaps, never empty details.
    assert list(matches["matches"]) == ["wmt:seattle-u:2077"]
    assert len(matches["missing"]) == 18
    assert cells["2025/men/seattle-u/matches"]["count"] == 1


# --- The WordPress generation ---------------------------------------------------

SC = "https://gamecocksonline.com/sports/msoc"
SC_SCHEDULE_URL = f"{SC}/schedule/season/2025/"
SC_CUMESTATS_URL = f"{SC}/cumestats/season/2025/"
SC_TEAM_URL = wmt.team_season_url(STATS_ORIGIN, 603646)
SC_GAME_URL = wmt.game_url(STATS_ORIGIN, 6393084)
UK = "https://ukathletics.com/sports/msoc"


class _WordPressSite(_Site):
    """A WordPress site: the season pages answer at their trailing-slash
    address (the site redirects there), and any other season path answers
    the page it was handed for it, as the real sites serve their current
    season under any season path."""

    def get(self, url: str, timeout: int | None = None, headers: object = None):
        if (
            not url.endswith("/")
            and "/proxy-api/" not in url
            and f"{url}/" in self.pages
        ):
            self.requests.append((url, headers))
            answer = super().get(f"{url}/", timeout, headers)
            self.requests.pop()
            return answer
        return super().get(url, timeout, headers)


def _south_carolina_site(**extra: str) -> _WordPressSite:
    return _WordPressSite(
        {
            SC_SCHEDULE_URL: _fixture("wmt_southcarolina_schedule_2025.html"),
            f"{SC}/roster/season/2025/": _fixture("wmt_southcarolina_roster_2025.html"),
            SC_CUMESTATS_URL: _fixture("wmt_southcarolina_cumestats_2025.html"),
            SC_TEAM_URL: _fixture("wmt_games_team_603646.json"),
            SC_GAME_URL: _fixture("wmt_games_game_6393084.json"),
            **extra,
        },
        etags={SC_TEAM_URL: 'W/"team-603646"'},
    )


def _kentucky_site() -> _WordPressSite:
    return _WordPressSite(
        {
            f"{UK}/schedule/season/2025/": _fixture("wmt_kentucky_schedule_2025.html"),
            f"{UK}/roster/season/2025/": _fixture("wmt_kentucky_roster_2025.html"),
            f"{UK}/cumestats/season/2025/": _fixture(
                "wmt_kentucky_cumestats_2025.html"
            ),
            wmt.team_season_url(STATS_ORIGIN, 603965): _fixture(
                "wmt_games_team_603965.json"
            ),
        }
    )


def _wp_schedule(
    site: _Site, base: str, owner: str
) -> tuple[str, list[dict[str, object]]]:
    html = wmt.fetch_layer(site, base, 2025, LAYER_SCHEDULE).page.html
    url = f"{base}/schedule/season/2025/"
    return html, wmt.parse_schedule(
        html, page_url=url, year=2025, owner_slug=owner, aliases={}
    )


def test_a_wordpress_schedule_bundles_the_page_cumestats_and_team_season() -> None:
    site = _south_carolina_site()
    html, fixtures = _wp_schedule(site, SC, "south-carolina")
    bundle = wmt.read_bundle(html)
    assert bundle.generation == wmt.GENERATION_WORDPRESS
    assert [part.role for part in bundle.parts] == ["page", "cumestats", "season"]
    assert bundle.final_url == SC_SCHEDULE_URL
    assert site.urls() == [f"{SC}/schedule/season/2025", SC_CUMESTATS_URL, SC_TEAM_URL]
    assert SC_TEAM_URL in site.paced
    assert len(fixtures) == 20
    charleston = next(
        f for f in fixtures if f["id"] == "wmt:south-carolina:20250821-charleston"
    )
    # "W 3-2" at Charleston, kicked off 7:30 pm local (JSON-LD startDate).
    assert charleston == {
        "id": "wmt:south-carolina:20250821-charleston",
        "date": "2025-08-21",
        "home": "charleston",
        "away": "south-carolina",
        "status": "final",
        "source_url": SC_SCHEDULE_URL,
        "time": "19:30",
        "venue": "Charleston, S.C.",
        "home_score": 2,
        "away_score": 3,
    }
    # The two exhibitions are marked "(EXH)" by the site; no result typed,
    # so neither is final and neither carries a score.
    exhibitions = [f for f in fixtures if f.get("match_type") == "exhibition"]
    assert [f["id"] for f in exhibitions] == [
        "wmt:south-carolina:20250809-nc-state",
        "wmt:south-carolina:20250816-wofford",
    ]
    assert all(
        f["status"] == "scheduled" and "home_score" not in f for f in exhibitions
    )
    # No machine-readable conference flag is published: absent, not derived.
    assert not any("conference_game" in f for f in fixtures)


def test_a_wordpress_site_serving_its_current_season_for_any_path_is_refused() -> None:
    """The WordPress trap: ``/schedule/season/2031/`` answers HTTP 200 with
    the 2026 season.  route_vars and the title are the witnesses."""
    page = _fixture("wmt_southcarolina_schedule_2031.html")
    site = _WordPressSite({f"{SC}/schedule/season/2031/": page})
    with pytest.raises(LiveCollectionError, match="served the 2026 season"):
        wmt.fetch_layer(site, SC, 2031, LAYER_SCHEDULE)
    # The same page under its own season still proves, by both witnesses.
    wmt.prove_wordpress_page(
        page, year=2026, kind=LAYER_SCHEDULE, sport="msoc", url="u"
    )
    with pytest.raises(LiveCollectionError, match="titled"):
        wmt.prove_wordpress_page(
            page, year=2026, kind=LAYER_ROSTER, sport="msoc", url="u"
        )
    with pytest.raises(LiveCollectionError, match="not men's soccer at /sports/wsoc"):
        wmt.prove_wordpress_page(
            page, year=2026, kind=LAYER_SCHEDULE, sport="wsoc", url="u"
        )


def test_wordpress_box_scores_are_joined_through_game_by_game_by_date(
    tmp_path: Path,
) -> None:
    html, fixtures = _wp_schedule(_south_carolina_site(), SC, "south-carolina")
    links = wmt.boxscore_links(html, SC_SCHEDULE_URL)
    assert len(links) == 18  # every typed result; not the two exhibitions
    assert links["20250821-charleston"] == SC_GAME_URL
    # The site's own box-score page for that row embeds the same game.
    box_page = _fixture("wmt_southcarolina_boxscore_charleston.html")
    assert 'path="/gamecocksonline/stats/match/full/6393084"' in box_page
    charleston = next(
        f for f in fixtures if f["id"] == "wmt:south-carolina:20250821-charleston"
    )
    site = _south_carolina_site()
    detail = wmt.collect_match(site, SC_GAME_URL, 2025, charleston)
    teams = detail["teams"]
    assert [team["name"] for team in teams] == ["South Carolina", "Col. of Charleston"]
    assert [team["score"] for team in teams] == [3, 2]
    assert detail["home_index"] == 1
    assert len(detail["scoring"]) == 5


def test_kentuckys_skin_reads_the_same_with_a_published_shootout_and_a_thin_box(
    caplog,
) -> None:
    html, fixtures = _wp_schedule(_kentucky_site(), UK, "kentucky")
    assert len(fixtures) == 21
    by_date = {f["date"]: f for f in fixtures}
    shootout = by_date["2025-11-09"]
    assert (shootout["home"], shootout["away"]) == ("kentucky", "coastal-carolina")
    assert (shootout["home_score"], shootout["away_score"]) == (0, 0)
    assert shootout["result_published"] == "T 0-0 (UK 6-5 PKs)"
    # "L 2-1 2OT" is typed winner first; the letter orients it.
    saint_louis = by_date["2025-11-20"]
    assert saint_louis["neutral"] is True
    assert (saint_louis["home_score"], saint_louis["away_score"]) == (1, 2)
    # Kentucky's rows link only PDFs; the date join supplies all 19 games.
    links = wmt.boxscore_links(html, "")
    assert len(links) == 19
    assert links[shootout["id"].rpartition(":")[2]] == wmt.game_url(
        STATS_ORIGIN, 6487961
    )
    url = wmt.game_url(STATS_ORIGIN, 6487961)
    with caplog.at_level(logging.WARNING, logger="src.wmt"):
        detail = wmt.parse_match_page(
            PublishedPage(url, url, THIN_GAME), 2025, shootout
        )
    assert [team["score"] for team in detail["teams"]] == [0, 0]
    assert "publishes no play-by-play" in caplog.text


def test_wordpress_rosters_are_read_from_the_players_table() -> None:
    sc = wmt.parse_roster(
        wmt.fetch_layer(_south_carolina_site(), SC, 2025, LAYER_ROSTER).page.html,
        page_url="",
    )
    assert len(sc) == 28
    assert sc[0] == {
        "name": "Filip Versterre",
        "number": "1",
        "position": "Goalkeeper",
        "height": "6'3\"",
        "hometown": "Copenhagen, Denmark",
        "class_year": "Sophomore",
        "source_url": f"{SC}/roster/season/2025/player/filip-versterre/",
    }
    uk = wmt.parse_roster(
        wmt.fetch_layer(_kentucky_site(), UK, 2025, LAYER_ROSTER).page.html, page_url=""
    )
    assert uk[0]["weight"] == "185 lbs" and uk[0]["height"] == "6'4\""
    assert not any(
        player["name"] in {"Johan Cedergren", "Ryan Zinkhan"} for player in uk
    )


def test_wordpress_statistics_come_from_the_cumestats_iframes_team() -> None:
    site = _south_carolina_site()
    fetched = wmt.fetch_layer(site, SC, 2025, LAYER_STATS)
    assert site.urls() == [f"{SC}/stats/season/2025", SC_CUMESTATS_URL, SC_TEAM_URL]
    assert fetched.page.final_url == SC_CUMESTATS_URL
    players, keepers = wmt.parse_stats(fetched.page.html, page_url="")
    assert (len(players), len(keepers)) == (23, 2)
    assert players[0]["name"] == "Ethan Ballek" and players[0]["goals"] == 8
    WMT.assert_served_season(fetched.page, 2025, LAYER_STATS)
    with pytest.raises(LiveCollectionError):
        WMT.assert_served_season(fetched.page, 2024, LAYER_STATS)


def test_the_board_collector_collects_a_wordpress_programme(
    monkeypatch, tmp_path: Path
) -> None:
    school = SchoolConfig(
        name="South Carolina",
        abbreviation="SC",
        conference="SBC",
        prefix="",
        base_url=SC,
        gender="men",
        scraper="wmt",
        live_scraper="wmt",
        enabled=True,
    )
    site = _south_carolina_site()
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(collect_board, "build_session", lambda session=None: site)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    fixtures, rosters, stats, matches, cells, _errors, _ = collect_board.collect(
        season=2025,
        gender="men",
        conference="SBC",
        wanted=["south-carolina"],
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
        workers=1,
    )

    assert {cell["state"] for cell in cells.values()} == {"complete"}
    assert len(fixtures["fixtures"]) == 20
    assert len(rosters["rosters"]["south-carolina"]["players"]) == 28
    assert len(stats["teams"]["south-carolina"]["players"]) == 23
    assert list(matches["matches"]) == ["wmt:south-carolina:20250821-charleston"]
    assert len(matches["missing"]) == 17


def test_a_site_seen_to_be_wordpress_is_asked_its_own_addresses(monkeypatch) -> None:
    monkeypatch.setattr(wmt, "_GENERATIONS", {})
    site = _south_carolina_site()
    wmt.fetch_layer(site, SC, 2025, LAYER_ROSTER)
    site.requests.clear()
    wmt.fetch_layer(site, SC, 2025, LAYER_STATS)
    wmt.fetch_layer(site, SC, 2025, LAYER_SCHEDULE)
    assert site.urls() == [
        SC_CUMESTATS_URL,
        SC_TEAM_URL,
        SC_SCHEDULE_URL,
        SC_CUMESTATS_URL,
        SC_TEAM_URL,
    ]


# --- The probe ---------------------------------------------------------------------


def test_the_probe_fingerprints_both_wmt_generations() -> None:
    from src.probe import PLATFORM_WMT, classify_platform

    platform, evidence = classify_platform(SCHEDULE_PAGE)
    assert platform == PLATFORM_WMT == "wmt"
    assert evidence == [
        "Nuxt __NUXT_DATA__ payload with the WMT oas-config store",
        "WMT statistics host named",
    ]
    platform, evidence = classify_platform(
        _fixture("wmt_southcarolina_schedule_2025.html")
    )
    assert platform == PLATFORM_WMT
    assert "inline wmtGames statistics configuration" in evidence
    # Neither SideArm's nor PrestoSports's markup is mistaken for WMT.
    assert wmt.is_wmt(_fixture("prestosports_tampa_schedule_2025.html")) == []
    assert wmt.is_wmt(_fixture("sidearm_boxscore_6126.html")) == []


@pytest.mark.parametrize(
    ("base", "site", "landing", "seasons"),
    [
        (BASE, _seattle_site, "wmt_seattleu_schedule_2025.html", "2025"),
        (SC, _south_carolina_site, "wmt_southcarolina_schedule_2025.html", "2024-2025"),
    ],
)
def test_the_probe_drafts_a_wmt_stanza_with_the_sites_sport_path(
    base: str, site, landing: str, seasons: str, capsys
) -> None:
    """The landing page here is the captured season page (the sport landing
    page itself was not captured; it carries the same markers)."""
    import tomllib

    from scripts import probe as probe_cli

    session = site(**{base: _fixture(landing)})
    if base == SC:
        # As the site does: the 2025 season served under the 2024 path.
        session.pages[f"{SC}/schedule/season/2024/"] = session.pages[SC_SCHEDULE_URL]
    exit_code = probe_cli.main(
        [
            "--url",
            f"{base}/",
            "--conference",
            "X",
            "--seasons",
            seasons,
            "--name",
            "Owner",
        ],
        session=session,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Platform: wmt" in out
    for layer in ("schedule", "roster", "stats", "matches"):
        assert f"  {layer}: present" in out
    # South Carolina serves 2025 under the 2024 path too: refused, not served.
    assert "Served seasons: 2025\n" in out
    assert "Seasons not seen" not in out
    stanza = tomllib.loads(
        out.split("Draft schools.toml stanza:\n", 1)[1].split("\n\n")[0]
    )
    school = stanza["schools"][0]
    assert (school["scraper"], school["live_scraper"]) == ("wmt", "wmt")
    assert school["base_url"] == base
    assert school["years"] == [2025]
    assert school["enabled"] is False
