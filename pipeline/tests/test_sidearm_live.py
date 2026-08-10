"""Tests for published schedule and roster collection."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.sidearm_live import (
    LiveCollectionError,
    identity_aliases,
    opponent_slug,
    PublishedPage,
    assert_payload_season,
    assert_served_season,
    collect_programme,
    parse_roster_page,
    parse_schedule_page,
)
from src.config import SchoolConfig


def _schedule_html(
    event: dict[str, object], *, title: str = "2026 Men's Soccer Schedule"
) -> str:
    component = {"type": "events", "data": [event]}
    return (
        f"<html><head><title>{title} - Example</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )


def _stale_payload_html(requested: int) -> str:
    """A page titled for `requested` whose payload is the CURRENT season."""
    return _schedule_html(
        {
            "id": 1,
            "date": "2026-08-27T18:00:00",
            "schedule": {"title": "2026 Men's Soccer Schedule"},
        },
        title=f"{requested} Men's Soccer Schedule",
    )


def test_served_season_rejects_silent_wrong_title() -> None:
    page = PublishedPage(
        "https://example.test/sports/mens-soccer/schedule/2026",
        "https://example.test/sports/mens-soccer/schedule/2026",
        "<title>2025 Men's Soccer Schedule - Example</title>",
    )
    with pytest.raises(LiveCollectionError, match="served schedule season 2025"):
        assert_served_season(page, 2026, "schedule")


def test_current_season_canonical_url_is_accepted_from_title() -> None:
    page = PublishedPage(
        "https://example.test/sports/mens-soccer/schedule/2026",
        "https://example.test/sports/mens-soccer/schedule",
        "<title>2026 Men's Soccer Schedule - Example</title>",
    )
    assert_served_season(page, 2026, "schedule")


def test_schedule_parser_preserves_future_fixture_as_scheduled() -> None:
    event = {
        "id": 42,
        "date": "2026-09-17T19:00:00",
        "tbd": False,
        "location_indicator": "A",
        "location": "Bethany, OK",
        "is_conference": True,
        "type": "upcoming",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Southern Nazarene"},
        "result": {"team_score": None, "opponent_score": None, "status": None},
    }
    fixtures = parse_schedule_page(
        _schedule_html(event),
        page_url="https://example.test/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug="harding",
        aliases={"southern nazarene": "southern-nazarene"},
    )
    assert fixtures == [
        {
            "id": "sidearm:harding:42",
            "date": "2026-09-17",
            "time": "19:00",
            "home": "southern-nazarene",
            "away": "harding",
            "venue": "Bethany, OK",
            "status": "scheduled",
            "conference_game": True,
            "source_url": "https://example.test/sports/mens-soccer/schedule/2026",
        }
    ]


def test_schedule_parser_orients_a_published_result() -> None:
    event = {
        "id": 43,
        "date": "2026-09-24T19:00:00",
        "location_indicator": "H",
        "is_conference": True,
        "type": "completed",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Fort Hays St."},
        "result": {"team_score": "2", "opponent_score": "1", "status": "W"},
    }
    fixture = parse_schedule_page(
        _schedule_html(event),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="harding",
        aliases={"fort hays state": "fort-hays-state"},
    )[0]
    assert fixture["status"] == "final"
    assert fixture["home"] == "harding"
    assert fixture["away"] == "fort-hays-state"
    assert fixture["home_score"] == 2
    assert fixture["away_score"] == 1


def test_roster_parser_reads_player_contract_and_deduplicates() -> None:
    row = """
    <li class="sidearm-roster-player" data-player-id="9"
        data-player-url="/sports/mens-soccer/roster/alex-example/9">
      <div class="sidearm-roster-player-position">
        <span class="sidearm-roster-player-position-long-short hide-on-small-down">Defender</span>
        <span class="sidearm-roster-player-height">6'1&quot;</span>
      </div>
      <div class="sidearm-roster-player-name">
        <span class="sidearm-roster-player-jersey-number">5</span>
        <a href="/sports/mens-soccer/roster/alex-example/9">Alex Example</a>
      </div>
      <span class="sidearm-roster-player-academic-year hide-on-large">Jr.</span>
      <span class="sidearm-roster-player-academic-year">Junior</span>
      <span class="sidearm-roster-player-hometown">Searcy, Ark.</span>
    </li>
    """
    players = parse_roster_page(
        f"<ul>{row}{row}</ul>", page_url="https://example.test/roster/2026"
    )
    assert players == [
        {
            "number": "5",
            "name": "Alex Example",
            "position": "Defender",
            "class_year": "Junior",
            "height": "6'1\"",
            "hometown": "Searcy, Ark.",
            "source_url": "https://example.test/sports/mens-soccer/roster/alex-example/9",
        }
    ]


def test_wrong_season_roster_does_not_discard_valid_schedule() -> None:
    event = {
        "id": 42,
        "date": "2026-09-17T19:00:00",
        "location_indicator": "H",
        "is_conference": True,
        "type": "upcoming",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Southern Nazarene"},
        "result": {"team_score": None, "opponent_score": None},
    }
    schedule_response = MagicMock()
    schedule_response.url = "https://example.test/sports/mens-soccer/schedule/2026"
    schedule_response.text = _schedule_html(event)
    roster_response = MagicMock()
    roster_response.url = "https://example.test/sports/mens-soccer/roster"
    roster_response.text = "<title>2025 Men's Soccer Roster - Example</title>"
    session = MagicMock()
    session.get.side_effect = [schedule_response, roster_response]
    school = SchoolConfig(
        name="Harding",
        abbreviation="HU",
        conference="GAC",
        prefix="hu",
        base_url="https://static.example.test/{year}/{prefix}-{num:02d}.htm",
        gender="men",
        live_base_url="https://example.test/sports/mens-soccer",
    )

    result = collect_programme(
        school,
        2026,
        {"southern nazarene": "southern-nazarene"},
        session=session,
    )

    assert len(result.fixtures) == 1
    assert result.state("schedule") == "complete"
    assert result.players == []
    roster = result.outcomes["roster"]
    assert roster.state == "unavailable"
    assert "served roster season 2025" in (roster.reason or "")


def _school() -> SchoolConfig:
    return SchoolConfig(
        name="Harding",
        abbreviation="HU",
        conference="GAC",
        prefix="hu",
        base_url="https://static.example.test/{year}/{prefix}-{num:02d}.htm",
        gender="men",
        live_base_url="https://example.test/sports/mens-soccer",
    )


def test_payload_season_rejects_a_page_that_serves_the_current_schedule() -> None:
    """Measured against live sites 2026-08-09.

    ``/schedule/2019`` answers 200, keeps ``/2019`` through every redirect, and
    titles itself for 2019 — while its embedded events carry the 2026 season.
    The wrapper assertion cannot see that; only the payload can.
    """
    with pytest.raises(LiveCollectionError, match="published for season 2026"):
        assert_payload_season(
            _stale_payload_html(2019), 2019, "https://example.test/schedule/2019"
        )


def test_payload_season_names_an_unpublished_schedule_separately() -> None:
    with pytest.raises(LiveCollectionError, match="published no schedule payload"):
        assert_payload_season(
            "<html></html>", 2026, "https://example.test/schedule/2026"
        )


def test_a_failed_schedule_does_not_discard_a_good_historical_roster() -> None:
    """The capability that makes past-season roster analysis possible.

    For any past season the site serves the roster and refuses the schedule, so
    a programme treated as one indivisible unit yields nothing at all.
    """
    schedule_response = MagicMock()
    schedule_response.url = "https://example.test/sports/mens-soccer/schedule/2019"
    schedule_response.text = _stale_payload_html(2019)
    roster_response = MagicMock()
    roster_response.url = "https://example.test/sports/mens-soccer/roster/2019"
    roster_response.text = (
        "<html><head><title>2019 Men's Soccer Roster</title></head><body><ul>"
        '<li class="sidearm-roster-player" data-player-id="9">'
        '<div class="sidearm-roster-player-name"><a href="/x">Adrian Renteria</a></div>'
        "</li></ul></body></html>"
    )
    session = MagicMock()
    session.get.side_effect = [schedule_response, roster_response]

    result = collect_programme(_school(), 2019, {}, session=session)

    assert result.state("schedule") == "unavailable"
    assert "published for season 2026" in (result.outcomes["schedule"].reason or "")
    assert result.state("roster") == "complete"
    assert [player["name"] for player in result.players] == ["Adrian Renteria"]


def test_roster_only_collection_never_requests_the_schedule() -> None:
    roster_response = MagicMock()
    roster_response.url = "https://example.test/sports/mens-soccer/roster/2019"
    roster_response.text = (
        "<html><head><title>2019 Men's Soccer Roster</title></head><body><ul>"
        '<li class="sidearm-roster-player" data-player-id="9">'
        '<div class="sidearm-roster-player-name"><a href="/x">Andre Cunha</a></div>'
        "</li></ul></body></html>"
    )
    session = MagicMock()
    session.get.side_effect = [roster_response]

    result = collect_programme(_school(), 2019, {}, session=session, layers=("roster",))

    assert session.get.call_count == 1
    assert "schedule" not in result.outcomes
    assert result.state("roster") == "complete"


def _gac() -> list[SchoolConfig]:
    def mk(name: str, abbr: str, gender: str) -> SchoolConfig:
        return SchoolConfig(
            name=name,
            abbreviation=abbr,
            conference="GAC",
            prefix=abbr.lower(),
            base_url=f"https://example.test/sports/{gender}s-soccer",
            gender=gender,
        )

    return [
        mk("Harding", "HU", "men"),
        mk("Fort Hays State", "FHSU", "men"),
        mk("Rogers State", "RSU", "men"),
        mk("Newman", "NU", "men"),
        mk("Northeastern State", "NSU", "men"),
        mk("Southwestern Oklahoma State", "SWOSU", "women"),
        mk("East Central", "ECU", "women"),
    ]


def test_a_mens_fixture_never_resolves_to_a_womens_only_programme() -> None:
    """The measured defect, pinned.

    Southwestern Oklahoma State fields women's soccer only. "Southwestern" on a
    men's schedule is a different institution, but a substring test sees the
    published string sitting inside the configured name and resolves it.
    """
    mens = identity_aliases(_gac(), "men")
    assert not any("southwestern" in alias for alias in mens)
    assert opponent_slug("Southwestern", mens) == "southwestern"

    # Unscoped, the alias is present — which is exactly how it used to resolve.
    unscoped = identity_aliases(_gac())
    assert any("southwestern" in alias for alias in unscoped)
    # Even unscoped, a prefix must no longer count as an identity.
    assert opponent_slug("Southwestern", unscoped) == "southwestern"


def test_configured_members_still_fold_across_published_spellings() -> None:
    aliases = identity_aliases(_gac(), "men")
    for published in ("Fort Hays St.", "Fort Hays State University", "Fort Hays State"):
        assert opponent_slug(published, aliases) == "fort-hays-state"
    for published in ("Rogers St.", "Rogers State University (Okla.)"):
        assert opponent_slug(published, aliases) == "rogers-state"
    assert opponent_slug("Harding University", aliases) == "harding"
    assert opponent_slug("Northeastern St.", aliases) == "northeastern-state"


def test_unconfigured_opponents_fold_on_the_normalized_key() -> None:
    aliases = identity_aliases(_gac(), "men")
    assert (
        opponent_slug("Delta St.", aliases)
        == opponent_slug("Delta State", aliases)
        == "delta-state"
    )
    assert (
        opponent_slug("Oklahoma Christian", aliases)
        == opponent_slug("Oklahoma Christian University", aliases)
        == "oklahoma-christian"
    )
    assert (
        opponent_slug("West Texas A&M", aliases)
        == opponent_slug("West Texas A&M University", aliases)
        == "west-texas-a-and-m"
    )
    # A match-type annotation is not part of an institution's identity.
    assert (
        opponent_slug("Oklahoma Wesleyan (Exhibition)", aliases) == "oklahoma-wesleyan"
    )


def test_an_opaque_abbreviation_is_recorded_rather_than_guessed() -> None:
    """DBU really is Dallas Baptist, and the collector must NOT infer that.

    Guessing across an abbreviation is the move that produced the Southwestern
    defect. These stay separate until a human records the alias.
    """
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("DBU", aliases) == "dbu"
    assert opponent_slug("Dallas Baptist", aliases) == "dallas-baptist"


def test_a_programme_with_no_live_recipe_reports_every_layer_unavailable() -> None:
    school = SchoolConfig(
        name="Northeastern State",
        abbreviation="NSU",
        conference="GAC",
        prefix="nsu",
        base_url="https://static.example.test/{year}/{prefix}-{num:02d}.htm",
        gender="men",
    )
    result = collect_programme(school, 2026, {}, session=MagicMock())
    assert result.state("schedule") == "unavailable"
    assert result.state("roster") == "unavailable"
    assert "no live schedule/roster recipe" in (result.outcomes["roster"].reason or "")


def _dom_game(
    *,
    game_id: str,
    opponent: str,
    date: str,
    side: str = "home",
    time: str = "",
    conference: str = "",
    result: str = "",
    facility: str = "",
) -> str:
    side_class = f"sidearm-schedule-{side}-game"
    indicator = "at" if side == "away" else "vs"
    time_html = (
        f'<div class="sidearm-schedule-game-time"><span>{time}</span></div>'
        if time
        else ""
    )
    result_html = (
        f'<div class="sidearm-schedule-game-result">{result}</div>' if result else ""
    )
    facility_html = (
        f'<div class="sidearm-schedule-game-location"><span>Somewhere, OK</span>'
        f'<span><a href="/facilities/?id=1">{facility}</a></span></div>'
        if facility
        else ""
    )
    return f"""
    <li class="sidearm-schedule-game {side_class} upcoming-game" data-game-id="{game_id}">
      <span class="sidearm-schedule-game-opponent-date"><span>{date}</span></span>
      {time_html}
      <div class="sidearm-schedule-game-opponent-text">
        <span class="sidearm-schedule-game-{"away" if side == "away" else "home"}">{indicator}</span>
        <span class="sidearm-schedule-game-opponent-name"><a>{opponent}</a></span>
      </div>
      <div class="sidearm-schedule-game-conference">{conference}</div>
      {facility_html}
      {result_html}
    </li>
    """


def _dom_page(rows: str, *, component: str = "") -> str:
    return (
        "<html><head><title>2026 Men's Soccer Schedule - Example</title></head>"
        f"<body>{component}<ul>{rows}</ul></body></html>"
    )


def test_dom_games_fill_in_what_the_json_stub_omits() -> None:
    """The measured defect: one theme embedded 1 of 27 games as JSON.

    The stub game must keep its richer JSON detail; the DOM game arrives under
    the same id space so a later full payload cannot double it.
    """
    event = {
        "id": 7655,
        "date": "2026-08-13T19:00:00",
        "tbd": False,
        "location_indicator": "H",
        "is_conference": False,
        "type": "upcoming",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Oklahoma Wesleyan (Exhibition)"},
        "result": {"team_score": None, "opponent_score": None, "status": None},
    }
    component = (
        "<script>\nvar obj = "
        + json.dumps({"type": "events", "data": [event]})
        + ";\n</script>"
    )
    rows = _dom_game(
        game_id="7655", opponent="Oklahoma Wesleyan (Exhibition)", date="Aug 13 (Thu)"
    ) + _dom_game(
        game_id="7660",
        opponent="Harding (Ark.)",
        date="Oct 1 (Thu)",
        time="7:00 p.m.",
        facility="Soldier Field",
    )
    fixtures = parse_schedule_page(
        _dom_page(rows, component=component),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )
    assert [fixture["id"] for fixture in fixtures] == [
        "sidearm:rogers-state:7655",
        "sidearm:rogers-state:7660",
    ]
    stub, dom = fixtures
    assert stub["time"] == "19:00"  # JSON detail retained, not overwritten
    assert dom["home"] == "rogers-state"
    assert dom["away"] == "harding"
    assert dom["time"] == "19:00"
    assert dom["venue"] == "Soldier Field"
    assert dom["status"] == "scheduled"


def test_marker_less_theme_derives_conference_and_says_so() -> None:
    """A theme with no conference column anywhere cannot publish the flag.

    Membership derivation fills it — and stamps the source, so a derived value
    can never masquerade as the publisher's claim.  An exhibition against a
    member is still not a conference game.
    """
    rows = (
        _dom_game(game_id="1", opponent="Harding (Ark.)", date="Oct 1 (Thu)")
        + _dom_game(game_id="2", opponent="Maryville (Mo.)", date="Sep 6 (Sun)")
        + _dom_game(game_id="3", opponent="Newman (Exhibition)", date="Aug 15 (Sat)")
    )
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )
    by_id = {str(fixture["id"]).rsplit(":", 1)[-1]: fixture for fixture in fixtures}
    assert by_id["1"]["conference_game"] is True
    assert by_id["2"]["conference_game"] is False
    assert by_id["3"]["conference_game"] is False
    assert all(
        fixture["conference_game_source"] == "derived:membership"
        for fixture in fixtures
    )


def test_marked_theme_publishes_the_conference_flag() -> None:
    rows = _dom_game(
        game_id="1", opponent="Harding", date="Oct 1 (Thu)", conference="GAC"
    ) + _dom_game(game_id="2", opponent="Maryville (Mo.)", date="Sep 6 (Sun)")
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )
    assert [fixture["conference_game"] for fixture in fixtures] == [False, True]
    assert all("conference_game_source" not in fixture for fixture in fixtures)


def test_a_hosted_tournament_row_belongs_to_the_named_teams() -> None:
    """A host lists other teams' games on its own page; the host is not in them."""
    rows = _dom_game(
        game_id="9",
        opponent="Southern Nazarene vs. Maryville",
        date="Aug 27 (Thu)",
    )
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )
    assert len(fixtures) == 1
    assert fixtures[0]["home"] == "southern-nazarene"
    assert fixtures[0]["away"] == "maryville"
    assert fixtures[0]["conference_game"] is False


def test_postseason_placeholder_rows_are_not_fixtures() -> None:
    rows = (
        _dom_game(game_id="20", opponent="TBA", date="Nov 6 (Fri)")
        + _dom_game(
            game_id="21",
            opponent="NCAA Tournament First and Second Rounds",
            date="Nov 13 (Fri)",
        )
        + _dom_game(
            game_id="22",
            opponent="GAC/MIAA Championship Tournament",
            date="Nov 8 (Sun)",
        )
    )
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )
    assert fixtures == []


def test_dom_result_is_oriented_from_the_owner_perspective() -> None:
    rows = _dom_game(
        game_id="30",
        opponent="Harding",
        date="Oct 29 (Thu)",
        side="away",
        result="L, 0-1",
    )
    fixture = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )[0]
    assert fixture["status"] == "final"
    assert fixture["home"] == "harding"
    assert fixture["home_score"] == 1
    assert fixture["away"] == "rogers-state"
    assert fixture["away_score"] == 0


def test_roster_position_blob_is_peeled_into_fields() -> None:
    """Themes without the long-short span pack pos/height/weight into one text."""
    row = """
    <li class="sidearm-roster-player" data-player-id="7">
      <div class="sidearm-roster-player-position">D 5'11" 165 lbs</div>
      <div class="sidearm-roster-player-name"><a>Casey Blob</a></div>
    </li>
    """
    players = parse_roster_page(
        f"<ul>{row}</ul>", page_url="https://example.test/roster/2026"
    )
    assert players == [
        {
            "name": "Casey Blob",
            "position": "D",
            "height": "5'11\"",
            "weight": "165 lbs",
        }
    ]


def test_a_logo_only_conference_marker_still_counts_as_published() -> None:
    """One theme marks conference games with a bare logo image and no text."""
    rows = (
        _dom_game(
            game_id="1",
            opponent="Harding",
            date="Oct 3 (Sat)",
            conference='<img alt="Great American Conference" src="/gac.png">',
        )
        + _dom_game(game_id="2", opponent="Drury", date="Sep 2 (Wed)")
    )
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="northeastern-state",
        aliases=identity_aliases(_gac(), "men"),
    )
    flags = {str(f["id"]).rsplit(":", 1)[-1]: f for f in fixtures}
    assert flags["1"]["conference_game"] is True
    assert flags["2"]["conference_game"] is False
    # The logo is the publisher speaking — nothing here is derived.
    assert all("conference_game_source" not in f for f in fixtures)
