"""Tests for published schedule and roster collection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import coverage
from src.config import SchoolConfig
from src.sidearm_live import (
    LiveCollectionError,
    _event_status,
    _oriented_scores,
    STATE_NO_COLLECTOR,
    identity_aliases,
    identity_fold_rules,
    opponent_slug,
    PublishedPage,
    assert_schedule_proven,
    assert_served_season,
    assert_untrapped_schedule,
    collect_programme,
    conference_members,
    parse_roster_page,
    parse_schedule_page,
    round_placeholder,
)


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
        layers=("schedule", "roster"),
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


def _trap_html(requested: int) -> str:
    """A past-season URL whose rendered games ARE the current season's.

    Measured 2026-08-09: two sites answer ``/schedule/2020`` with the current
    schedule. Payload and DOM carry the same games under the same event ids.
    """
    component = (
        "<script>\nvar obj = "
        + json.dumps(
            {
                "type": "events",
                "data": [
                    {
                        "id": 7655,
                        "date": "2026-08-27T18:00:00",
                        "schedule": {"title": "2026 Men's Soccer Schedule"},
                    }
                ],
            }
        )
        + ";\n</script>"
    )
    rows = _dom_game(game_id="7655", opponent="Southern Nazarene", date="Aug 27 (Thu)")
    return (
        f"<html><head><title>{requested} Men's Soccer Schedule - Example</title>"
        f"</head><body>{component}<ul>{rows}</ul></body></html>"
    )


def test_a_past_url_serving_the_current_dom_schedule_is_refused() -> None:
    """The one dangerous shape: a past URL canonicalised to the current page.

    The payload alone proves nothing (it names the current season at EVERY
    season URL, genuine archives included) — the tell is a parsed fixture
    sharing an event id with the payload's games.
    """
    html = _trap_html(2020)
    fixtures = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2020",
        year=2020,
        owner_slug="harding",
        aliases={},
    )
    with pytest.raises(LiveCollectionError, match="renders the season-2026 schedule"):
        assert_untrapped_schedule(
            html, 2020, "https://example.test/schedule/2020", fixtures, "harding"
        )


def test_a_genuine_archive_page_parses_dom_only_without_current_pollution() -> None:
    """Measured 2026-08-09 across seven sites back to 2016: ``/schedule/{year}``
    renders the genuine past season in the DOM while the embedded payload still
    names the current one. The past season is DOM-only, and not one current-
    season payload event may leak into it."""
    component = (
        "<script>\nvar obj = "
        + json.dumps(
            {
                "type": "events",
                "data": [
                    {
                        "id": 7655,
                        "date": "2026-08-27T18:00:00",
                        "schedule": {"title": "2026 Men's Soccer Schedule"},
                        "opponent": {"title": "Southern Nazarene"},
                        "location_indicator": "H",
                    }
                ],
            }
        )
        + ";\n</script>"
    )
    rows = _dom_game(
        game_id="9001",
        opponent="Southern Nazarene",
        date="Sep 12 (Thu)",
        result="W, 2-1",
    ) + _dom_game(
        game_id="9002",
        opponent="Rogers State",
        date="Oct 05 (Sat)",
        side="away",
        result="L, 0-3",
    )
    html = (
        "<html><head><title>2019 Men's Soccer Schedule - Example</title></head>"
        f"<body>{component}<ul>{rows}</ul></body></html>"
    )
    fixtures = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2019",
        year=2019,
        owner_slug="harding",
        aliases={
            "southern nazarene": "southern-nazarene",
            "rogers state": "rogers-state",
        },
    )
    assert_untrapped_schedule(
        html, 2019, "https://example.test/schedule/2019", fixtures, "harding"
    )

    assert [str(fixture["id"]) for fixture in fixtures] == [
        "sidearm:harding:9001",
        "sidearm:harding:9002",
    ]
    assert [str(fixture["date"]) for fixture in fixtures] == [
        "2019-09-12",
        "2019-10-05",
    ]
    assert all(fixture["status"] == "final" for fixture in fixtures)
    assert (fixtures[0]["home_score"], fixtures[0]["away_score"]) == (2, 1)
    # Away result re-oriented from the owner's perspective to home/away.
    assert (fixtures[1]["home_score"], fixtures[1]["away_score"]) == (3, 0)


def test_a_spring_completion_lands_in_the_following_calendar_year() -> None:
    """The COVID 2020 season was finished in spring 2021; the rendered date
    carries no year, so January–June belongs to the year after the season's."""
    rows = _dom_game(
        game_id="8801",
        opponent="Southern Nazarene",
        date="Feb 20 (Sat)",
        result="W, 1-0",
    )
    html = (
        "<html><head><title>2020 Men's Soccer Schedule - Example</title></head>"
        f"<body><ul>{rows}</ul></body></html>"
    )
    fixtures = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2020",
        year=2020,
        owner_slug="harding",
        aliases={},
    )
    assert [str(fixture["date"]) for fixture in fixtures] == ["2021-02-20"]


def test_an_honest_empty_season_is_empty_not_unavailable() -> None:
    """Measured: one site's 2020 page is honestly titled and lists no games —
    a season that was not played, not a page that could not be read."""
    schedule_response = MagicMock()
    schedule_response.url = "https://example.test/sports/mens-soccer/schedule/2020"
    schedule_response.text = _stale_payload_html(2020)
    session = MagicMock()
    session.get.side_effect = [schedule_response]

    result = collect_programme(
        _school(), 2020, {}, session=session, layers=("schedule",)
    )

    assert result.state("schedule") == "empty"
    assert "listed no fixtures" in (result.outcomes["schedule"].reason or "")


def test_a_page_with_no_schedule_shape_at_all_is_unavailable() -> None:
    schedule_response = MagicMock()
    schedule_response.url = "https://example.test/sports/mens-soccer/schedule/2019"
    schedule_response.text = (
        "<html><head><title>2019 Men's Soccer Schedule - Example</title></head>"
        "<body><p>Welcome to our athletics site.</p></body></html>"
    )
    session = MagicMock()
    session.get.side_effect = [schedule_response]

    result = collect_programme(
        _school(), 2019, {}, session=session, layers=("schedule",)
    )

    assert result.state("schedule") == "unavailable"
    assert "no rendered games" in (result.outcomes["schedule"].reason or "")


def test_a_trapped_schedule_does_not_discard_a_good_historical_roster() -> None:
    """The capability that makes past-season analysis possible: each layer
    stands or falls on its own, so a site that canonicalises past schedule
    URLs to the current season can still serve its roster archive."""
    schedule_response = MagicMock()
    schedule_response.url = "https://example.test/sports/mens-soccer/schedule/2019"
    schedule_response.text = _trap_html(2019)
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

    result = collect_programme(
        _school(), 2019, {}, session=session, layers=("schedule", "roster")
    )

    assert result.state("schedule") == "unavailable"
    assert "renders the season-2026 schedule" in (
        result.outcomes["schedule"].reason or ""
    )
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


def test_configured_aliases_fold_formal_names_onto_the_school() -> None:
    """A formal published name can share no token with the configured one.

    "AUM" and "Auburn University at Montgomery" are the same school, but the
    token-matching fallback cannot connect them: no token of "AUM" appears in
    the formal string. Without a stated alias the fixture fragments across two
    slugs, and a conference opponent stops being recognized as one.
    """
    schools = [
        SchoolConfig(
            name="AUM",
            abbreviation="AUM",
            conference="GSC",
            prefix="aum",
            base_url="https://example.test/sports/mens-soccer",
            gender="men",
            aliases=["Auburn University at Montgomery", "Auburn University Montgomery"],
        ),
        SchoolConfig(
            name="Trevecca",
            abbreviation="TNU",
            conference="GSC",
            prefix="tnu",
            base_url="https://example.test/sports/mens-soccer",
            gender="men",
            aliases=["Trevecca Nazarene"],
        ),
    ]
    aliases = identity_aliases(schools, "men")
    for published in (
        "Auburn University at Montgomery",
        "Auburn University Montgomery (Ala.)",
        "AUM",
    ):
        assert opponent_slug(published, aliases) == "aum"
    for published in ("Trevecca Nazarene University", "Trevecca"):
        assert opponent_slug(published, aliases) == "trevecca"


def test_aliases_stay_scoped_to_their_own_gender() -> None:
    """An alias is a per-stanza fact, so it must not leak across genders."""
    womens_only = [
        SchoolConfig(
            name="Montevallo",
            abbreviation="UM",
            conference="GSC",
            prefix="um",
            base_url="https://example.test/sports/womens-soccer",
            gender="women",
            aliases=["University of Montevallo"],
        )
    ]
    mens = identity_aliases(womens_only, "men")
    assert mens == {}
    # No alias reached the men's map; the fold alone carries the formal name
    # to the plain one (it used to leave "of-montevallo", tl-kvn).
    assert opponent_slug("University of Montevallo", mens) == "montevallo"


def test_an_institutional_prefix_folds_onto_the_plain_name() -> None:
    """ "University of X" is X, not "of X".

    Dropping "university" alone left the preposition standing, and the data
    home filed "of-tampa" beside "tampa", "of-findlay" beside "findlay",
    "of-texas-at-dallas" beside "ut-dallas" (tl-kvn: thirty-odd of- slugs
    across the fixture files). The prefix forms all reduce to the same key,
    and a leading "the" or a doubled "of the" goes with them.
    """
    aliases = identity_aliases(_gac(), "men")
    for published in (
        "University of Tampa",
        "The University of Tampa",
        "Tampa University",
        "Tampa",
    ):
        assert opponent_slug(published, aliases) == "tampa"
    assert opponent_slug("College of the Ozarks", aliases) == "ozarks"
    assert opponent_slug("University of the Southwest", aliases) == "southwest"
    # Only a LEADING "of" is residue; inside a name it is the name.
    assert (
        opponent_slug("Colorado School of Mines", aliases) == "colorado-school-of-mines"
    )


def test_a_locative_joiner_folds_onto_the_hyphenated_spelling() -> None:
    """ "Texas at Dallas" and "Texas-Dallas" are one spelling.

    Peers print the formal "University of Texas at Tyler" and the wire-style
    "Texas-Tyler" for one programme (CSU Pueblo 2024, Colorado Christian
    2025); the same for Alabama-Huntsville and Auburn Montgomery. The
    preposition between two words joins nothing an identity needs.
    """
    aliases = identity_aliases(_gac(), "men")
    assert (
        opponent_slug("University of Texas at Tyler", aliases)
        == opponent_slug("The University of Texas at Tyler", aliases)
        == opponent_slug("Texas-Tyler", aliases)
        == "texas-tyler"
    )
    assert (
        opponent_slug("University of Alabama in Huntsville", aliases)
        == opponent_slug("Alabama-Huntsville", aliases)
        == "alabama-huntsville"
    )
    assert (
        opponent_slug("Auburn University at Montgomery", aliases)
        == opponent_slug("Auburn University Montgomery", aliases)
        == "auburn-montgomery"
    )
    # A leading "at" is an orientation word, not a joiner; it is not eaten.
    assert opponent_slug("at Molloy", aliases) == "at-molloy"


def test_the_fold_names_the_rules_that_fired() -> None:
    assert identity_fold_rules("University of Texas at Dallas") == (
        "institution-word",
        "of-prefix",
        "locative-joiner",
    )
    assert identity_fold_rules("Fort Hays St.") == ()
    assert identity_fold_rules("Lewis University") == ("institution-word",)


def test_an_abbreviated_member_still_needs_its_stated_alias() -> None:
    """The fold reaches "texas dallas"; only an alias reaches "UT Dallas"."""
    schools = [
        SchoolConfig(
            name="UT Dallas",
            abbreviation="UTD",
            conference="LSC",
            prefix="utd",
            base_url="https://example.test/sports/mens-soccer",
            gender="men",
            aliases=["University of Texas at Dallas"],
        )
    ]
    aliases = identity_aliases(schools, "men")
    for published in (
        "University of Texas at Dallas",
        "The University of Texas at Dallas",
        "Texas-Dallas",
        "UT Dallas",
    ):
        assert opponent_slug(published, aliases) == "ut-dallas"


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


def test_a_poll_rank_is_not_part_of_an_identity() -> None:
    """A rank moves week to week, so keeping it mints one slug per week.

    Measured in the archive: no-4-csu-pueblo beside no-15-csu-pueblo,
    no-25-maryville beside no-12-maryville, and three separate slugs for
    Midwestern State. Sites publish the rank as "#4", "No. 4", "No 4" and bare
    "4", and only the first form was being stripped.
    """
    aliases = identity_aliases(_gac(), "men")
    assert (
        opponent_slug("#4 CSU Pueblo", aliases)
        == opponent_slug("No. 4 CSU Pueblo", aliases)
        == opponent_slug("No 15 CSU Pueblo", aliases)
        == opponent_slug("10 CSU Pueblo", aliases)
        == opponent_slug("CSU Pueblo", aliases)
        == "csu-pueblo"
    )
    # A ranked configured member must still fold onto its canonical slug.
    assert opponent_slug("No. 7 Fort Hays State", aliases) == "fort-hays-state"


def test_receiving_votes_is_a_rank_not_an_identity() -> None:
    """ "RV" is a rank with no digits in it, so the numeric forms never caught it.

    Measured in the archive: rv-lee beside lee, rv-rollins, rv-seattle-pacific
    and five more — eight rows across eight shards, in both the GSC and the
    LSC. A team drifting in and out of the poll minted a second slug for itself
    exactly as a moving number did.
    """
    aliases = identity_aliases(_gac(), "men")
    assert (
        opponent_slug("RV Rollins", aliases)
        == opponent_slug("rv Rollins", aliases)
        # The "#" marker fronts RV as readily as it fronts a number; this is the
        # form Union published, and it survived the first pass at this fix.
        == opponent_slug("#RV Rollins", aliases)
        == opponent_slug("Rollins", aliases)
        == "rollins"
    )
    # A ranked configured member must still fold onto its canonical slug.
    assert opponent_slug("RV Fort Hays State", aliases) == "fort-hays-state"


def test_a_rank_in_parentheses_is_still_a_rank() -> None:
    """A seed is published bracketed — "(3) Ouachita Baptist".

    _identity_key drops parentheticals anyway, so a configured member still
    matched; the damage was in the fallback slug for an opponent that is not
    configured, which never saw the parenthetical stripper at all and minted
    3-ouachita-baptist. Measured across the archive: 41 bracketed numbers and
    22 bracketed RVs on 231 schedule pages.
    """
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("(3) Ouachita Baptist", aliases) == "ouachita-baptist"
    assert opponent_slug("(4) Northeastern State", aliases) == "northeastern-state"
    assert opponent_slug("(RV) Rollins", aliases) == "rollins"


def test_a_bracketed_seed_can_be_followed_by_a_second_rank() -> None:
    """The prefix repeats because the rank strip runs before parentheses go.

    "(5) RV Seattle Pacific" and "(1) #3 Stanislaus State" both hid a second
    rank behind the bracket, so stripping one token left the other stranded.
    """
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("(5) RV Seattle Pacific", aliases) == "seattle-pacific"
    assert opponent_slug("(1) #3 Stanislaus State", aliases) == "stanislaus-state"
    assert opponent_slug("#10 (4) Rockhurst", aliases) == "rockhurst"


def test_a_seed_is_a_rank_however_it_is_spelled() -> None:
    """A seed word is a rank, and an earlier pass here asserted the opposite.

    "5th-Seed Oklahoma Christian" was pinned as untouchable on the guess that
    the digit belonged to the name. It does not — that is Oklahoma Christian,
    a configured programme, and the assertion pinned the bug rather than the
    behaviour. The archive publishes the seed three ways.
    """
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("3-seed Oklahoma Christian", aliases) == "oklahoma-christian"
    assert opponent_slug("#4-seed Oklahoma Christian", aliases) == "oklahoma-christian"
    assert opponent_slug("5th-Seed Oklahoma Christian", aliases) == "oklahoma-christian"


def test_a_seed_in_square_brackets_is_still_a_rank() -> None:
    """Tournament seeds are bracketed, and can sit behind a poll rank."""
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("[7] Cedarville", aliases) == "cedarville"
    assert opponent_slug("#17 [7] Cedarville", aliases) == "cedarville"
    assert opponent_slug("#15 [3] Lincoln", aliases) == "lincoln"


def test_an_all_caps_abbreviation_is_not_a_rank() -> None:
    """The scan for rank forms turns up far more abbreviations than ranks."""
    aliases = identity_aliases(_gac(), "men")
    for published in ("UT Tyler", "MSU Denver", "CSU Pueblo", "USC Aiken"):
        assert opponent_slug(published, aliases) == published.lower().replace(" ", "-")


def test_two_polls_publish_one_rank_joined_by_a_slash() -> None:
    """A school ranked in two polls carries both, e.g. "RV/#11 Palm Beach".

    Stripping a single token leaves the other behind, so the prefix repeats.
    """
    aliases = identity_aliases(_gac(), "men")
    for published in (
        "RV/#11 Palm Beach Atlantic University",
        "#11/RV Palm Beach Atlantic",
        "Palm Beach Atlantic",
    ):
        assert opponent_slug(published, aliases) == "palm-beach-atlantic"


def test_a_name_merely_starting_with_those_letters_is_untouched() -> None:
    """The trailing-whitespace requirement is what makes the bare "rv" safe."""
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("Rverside", aliases) == "rverside"
    assert opponent_slug("RVing Club", aliases) == "rving-club"


def test_st_is_saint_before_a_word_and_state_at_the_end() -> None:
    """One abbreviation, two different words, told apart by position.

    Expanding "St." to State unconditionally slugged St. Edward's as
    state-edward-s and Missouri-St. Louis as missouri-state-louis. Both are
    real programmes, and the Lone Star Conference brings two more Saint
    schools, so this blocks conference expansion rather than following it.
    """
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("St. Edward's", aliases) == "saint-edwards"
    assert opponent_slug("St. Mary's (Texas)", aliases) == "saint-marys"
    assert opponent_slug("Missouri-St. Louis", aliases) == "missouri-saint-louis"
    # Trailing "St." still means State, which is why the rule exists at all.
    assert opponent_slug("Northeastern St.", aliases) == "northeastern-state"
    assert opponent_slug("Delta St.", aliases) == "delta-state"


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


def test_an_unimplemented_live_collector_reports_no_collector_without_fetching() -> (
    None
):
    school = _school()
    school.live_scraper = "sidearm_legacy"
    session = MagicMock()

    result = collect_programme(
        school,
        2026,
        {},
        session=session,
        layers=("schedule", "roster", "stats"),
    )

    assert STATE_NO_COLLECTOR == coverage.STATE_NO_COLLECTOR
    assert all(
        result.state(layer) == STATE_NO_COLLECTOR
        for layer in ("schedule", "roster", "stats")
    )
    assert "sidearm_legacy" in (result.outcomes["schedule"].reason or "")
    session.get.assert_not_called()


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
    location: str = "",
    promotion: str = "",
    completed: bool = False,
    neutral: bool = False,
) -> str:
    # The measured neutral shape (goriverhawksgo.com 2022, mckbearcats.com
    # 2025): the row carries sidearm-schedule-neutral-game in place of the
    # home/away class, and the "vs"/"at" span is the only side indicator.
    side_class = (
        "sidearm-schedule-neutral-game" if neutral else f"sidearm-schedule-{side}-game"
    )
    if completed:
        side_class += " sidearm-schedule-game-completed"
    indicator = "at" if side == "away" else "vs"
    time_html = (
        f'<div class="sidearm-schedule-game-time"><span>{time}</span></div>'
        if time
        else ""
    )
    # The measured played-without-score shape: the modern theme fills scores
    # client-side, so the served result element holds only empty spans while
    # a Final span (whose class the result selector does not match) rides the
    # date line.
    if completed and not result:
        result_html = (
            '<span class="sidearm-schedule-game-result-final">Final</span>'
            '<div class="sidearm-schedule-game-result "><span></span><span></span></div>'
        )
    else:
        result_html = (
            f'<div class="sidearm-schedule-game-result">{result}</div>'
            if result
            else ""
        )
    # The measured served shape (goriverhawksgo.com 2026): a promotion such as
    # "Friendly" is a distinct child div inside the location element, beside
    # the city span.
    promotion_html = (
        f'<div class="sidearm-schedule-game-opponent-promotion">{promotion}</div>'
        if promotion
        else ""
    )
    if facility:
        facility_html = (
            f'<div class="sidearm-schedule-game-location"><span>Somewhere, OK</span>'
            f'<span><a href="/facilities/?id=1">{facility}</a></span>'
            f"{promotion_html}</div>"
        )
    elif location or promotion:
        facility_html = (
            f'<div class="sidearm-schedule-game-location"><span>{location}</span>'
            f"{promotion_html}</div>"
        )
    else:
        facility_html = ""
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


def _with_lsc() -> list[SchoolConfig]:
    return _gac() + [
        SchoolConfig(
            name="Dallas Baptist",
            abbreviation="DBU",
            conference="LSC",
            prefix="dbu",
            base_url="https://example.test/sports/mens-soccer",
            gender="men",
        )
    ]


def test_conference_members_is_scoped_by_conference_and_by_gender() -> None:
    """Identity spans every configured school; membership must not."""
    schools = _with_lsc()
    assert conference_members(schools, "men", "LSC") == {"dallas-baptist"}
    assert "dallas-baptist" not in conference_members(schools, "men", "GAC")
    # The women's programmes in the fixture are GAC too, and must not leak in.
    assert conference_members(schools, "men", "GAC") == {
        "harding",
        "fort-hays-state",
        "rogers-state",
        "newman",
        "northeastern-state",
    }


def _with_trevecca() -> list[SchoolConfig]:
    """The GAC fixture plus Trevecca, whose stanza says its CURRENT conference."""
    return _gac() + [
        SchoolConfig(
            name="Trevecca",
            abbreviation="TNU",
            conference="GSC",
            prefix="tnu",
            base_url="https://example.test/sports/mens-soccer",
            gender="men",
        )
    ]


def _mid_window_mover_document() -> dict:
    def window(conference: str, from_season: int, to_season: int) -> dict:
        return {
            "conference": conference,
            "from_season": from_season,
            "to_season": to_season,
            "source": "test fixture",
        }

    return {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": ["G-MAC", "GSC", "GAC", "independent", "non_member"],
        "memberships": {
            "trevecca": {
                "men": [window("G-MAC", 2022, 2023), window("GSC", 2024, 2026)]
            },
            "harding": {"men": [window("GAC", 2022, 2026)]},
            # Membership-only: a window but no stanza (a dead host).
            "lee": {"men": [window("GSC", 2022, 2026)]},
        },
    }


def test_conference_members_resolves_a_mid_window_mover_per_season() -> None:
    """The stanza names the current conference; the window names the season's."""
    schools = _with_trevecca()
    document = _mid_window_mover_document()

    for season in (2022, 2023):
        members = conference_members(
            schools, "men", "G-MAC", season=season, document=document
        )
        assert members == {"trevecca"}
        assert "trevecca" not in conference_members(
            schools, "men", "GSC", season=season, document=document
        )
    for season in (2024, 2026):
        assert "trevecca" in conference_members(
            schools, "men", "GSC", season=season, document=document
        )
        assert (
            conference_members(
                schools, "men", "G-MAC", season=season, document=document
            )
            == set()
        )


def test_conference_members_with_a_season_keeps_the_stanza_as_the_default() -> None:
    schools = _with_trevecca()
    document = _mid_window_mover_document()
    stanza_only = conference_members(schools, "men", "GAC")
    # Harding resolves through its window, the rest through their stanza; the
    # GAC set is the same either way and the women's programmes stay out.
    assert (
        conference_members(schools, "men", "GAC", season=2022, document=document)
        == stanza_only
    )


def _stanza(name: str, conference: str) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=name[:3].upper(),
        conference=conference,
        prefix=name[:3].lower(),
        base_url="https://example.test/sports/mens-soccer",
        gender="men",
    )


def _uncovered_season_case() -> tuple[list[SchoolConfig], dict]:
    def window(conference: str, from_season: int, to_season: int) -> dict:
        return {
            "conference": conference,
            "from_season": from_season,
            "to_season": to_season,
            "source": "test fixture",
        }

    schools = [
        _stanza("Anchor", "UPPER"),
        # Left UPPER after 2023; the stanza still says UPPER.
        _stanza("Leaver", "UPPER"),
        # Joined UPPER in 2025; the stanza says UPPER for every season.
        _stanza("Arriver", "UPPER"),
        # LOWER is authored through 2025 only.
        _stanza("Stayer", "LOWER"),
        # No window anywhere: the reference has not reached it.
        _stanza("Unwindowed", "UPPER"),
    ]
    document = {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": ["UPPER", "LOWER", "independent", "non_member"],
        "memberships": {
            "anchor": {"men": [window("UPPER", 2022, 2026)]},
            "leaver": {"men": [window("UPPER", 2022, 2023)]},
            "arriver": {"men": [window("UPPER", 2025, 2026)]},
            "stayer": {"men": [window("LOWER", 2022, 2025)]},
        },
    }
    return schools, document


def test_conference_members_never_reads_an_uncovered_season_off_the_stanza() -> None:
    """A programme with windows is in no conference for a season none covers.

    The stanza used to answer for it, with the conference the programme had
    left or had not yet joined.
    """
    schools, document = _uncovered_season_case()

    def members(season: int) -> set[str]:
        return conference_members(
            schools, "men", "UPPER", season=season, document=document
        )

    assert members(2023) == {"anchor", "leaver", "unwindowed"}
    assert members(2024) == {"anchor", "unwindowed"}
    assert members(2025) == {"anchor", "arriver", "unwindowed"}
    assert members(2026) == {"anchor", "arriver", "unwindowed"}
    # The stanza is still the default for the programme with no window at all,
    # and still the whole answer when no season is asked.
    assert conference_members(schools, "men", "UPPER") == {
        "anchor",
        "leaver",
        "arriver",
        "unwindowed",
    }


def test_conference_members_carries_a_conference_past_its_own_horizon() -> None:
    """The legitimate uncovered season: one past the CONFERENCE's last authored
    season, which the rib resolves as extrapolated (the GAC, authored through
    2025, collected for 2026)."""
    schools, document = _uncovered_season_case()
    for season in (2025, 2026, 2027):
        assert conference_members(
            schools, "men", "LOWER", season=season, document=document
        ) == {"stayer"}
    # Not a licence to carry a leaver: UPPER authors 2024, so 2024 is read.
    assert "leaver" not in conference_members(
        schools, "men", "UPPER", season=2027, document=document
    )


def test_the_shipped_mercyhurst_is_a_psac_member_only_under_its_windows() -> None:
    """Measured: PSAC windows 2022-2023, stanza conference PSAC, and the
    stanza kept it a PSAC member for 2024, 2025 and 2026."""
    from src.config import load_schools
    from src.membership import load_membership

    schools = load_schools()
    document = load_membership()
    for gender in ("men", "women"):
        for season in (2022, 2023):
            assert "mercyhurst" in conference_members(
                schools, gender, "PSAC", season=season, document=document
            )
        for season in (2024, 2025, 2026):
            assert "mercyhurst" not in conference_members(
                schools, gender, "PSAC", season=season, document=document
            )


def test_conference_members_counts_a_membership_only_slug() -> None:
    schools = _with_trevecca()
    document = _mid_window_mover_document()
    members = conference_members(schools, "men", "GSC", season=2025, document=document)
    assert members == {"trevecca", "lee"}
    assert "lee" not in conference_members(schools, "men", "GSC")


def test_conference_members_without_a_season_is_the_stanza_set() -> None:
    """Pins the default: no season, no window lookup, byte-for-byte as before."""
    schools = _with_trevecca()
    document = _mid_window_mover_document()
    assert conference_members(schools, "men", "GSC") == {"trevecca"}
    assert conference_members(schools, "men", "GSC", document=document) == {"trevecca"}
    assert conference_members(schools, "men", "G-MAC", document=document) == set()


def test_membership_derivation_is_one_conference_not_every_school() -> None:
    """A second conference must not turn a cross-conference game into one.

    The derived flag tested both sides against the whole configured school list,
    which is indistinguishable from "this conference" only while exactly one
    conference is configured. With the Lone Star Conference alongside the GAC, a
    Rogers State versus Dallas Baptist fixture is emphatically not a conference
    game, and nothing would have caught it: the collect succeeds either way.
    """
    schools = _with_lsc()
    rows = _dom_game(
        game_id="1", opponent="Harding (Ark.)", date="Oct 1 (Thu)"
    ) + _dom_game(game_id="2", opponent="Dallas Baptist", date="Sep 6 (Sun)")
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(schools, "men"),
        members=conference_members(schools, "men", "GAC"),
    )
    by_id = {str(fixture["id"]).rsplit(":", 1)[-1]: fixture for fixture in fixtures}
    assert by_id["1"]["conference_game"] is True
    assert by_id["2"]["conference_game"] is False
    # Identity is NOT scoped, so the out-of-conference opponent still canonicalizes.
    assert {by_id["2"]["home"], by_id["2"]["away"]} == {
        "rogers-state",
        "dallas-baptist",
    }


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
    rows = _dom_game(
        game_id="1",
        opponent="Harding",
        date="Oct 3 (Sat)",
        conference='<img alt="Great American Conference" src="/gac.png">',
    ) + _dom_game(game_id="2", opponent="Drury", date="Sep 2 (Wed)")
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


# ── the statistics layer ─────────────────────────────────────────────────────


def _stats_html(title: str = "2019 Men's Soccer Cumulative Statistics") -> str:
    """A cumulative-stats page in the shape every measured site serves:
    data-labelled cells, player rows anchored by a[data-player-id], and
    Total/Opponents footer rows with no anchor at all."""

    def cell(label: str, value: str) -> str:
        return f'<td data-label="{label}">{value}</td>'

    offense = (
        "<table><caption>Individual Overall Offensive Statistics</caption>"
        "<tr><th>#</th><th>Player</th><th>GP</th></tr>"
        '<tr><td data-sort="7">7</td>'
        '<td><a data-player-id="2914" href="#">Simpson, Jake</a>'
        '<a href="/sports/mens-soccer/roster/jake-simpson/2914">View Bio</a></td>'
        + cell("GP", "20")
        + cell("GS", "20")
        + cell("MIN", "1753")
        + cell("G", "14")
        + cell("A", "8")
        + cell("PTS", "36")
        + cell("SH", "72")
        + cell("SH%", ".194")
        + cell("SOG", "37")
        + cell("SOG%", ".514")
        + cell("YC-RC", "5-0")
        + cell("GW", "2")
        + cell("PG-PA", "1-1")
        + "</tr>"
        "<tr><td></td><td>Total</td>"
        + cell("GP", "20")
        + cell("MIN", "20459")
        + "</tr></table>"
    )
    keeping = (
        "<table><caption>Individual Overall Goalkeeping Statistics</caption>"
        "<tr><th>#</th><th>Player</th><th>GP</th></tr>"
        '<tr><td data-sort="1">1</td>'
        '<td><a data-player-id="2902" href="#">Dean, Dillon</a></td>'
        + cell("GP", "10")
        + cell("GS", "9")
        + cell("MIN", "905:07")
        + cell("GA", "4")
        + cell("GAA", "0.40")
        + cell("SV", "26")
        + cell("SV%", ".867")
        + cell("W", "8")
        + cell("L", "1")
        + cell("T", "0")
        + cell("SHO", "5")
        + cell("SF", "97")
        + "</tr>"
        "<tr><td></td><td>Opponents</td>" + cell("GA", "42") + "</tr></table>"
    )
    return (
        f"<html><head><title>{title} - Example</title></head>"
        f"<body>{offense}{keeping}</body></html>"
    )


def test_stats_parser_reads_both_tables_and_skips_the_totals() -> None:
    from src.sidearm_live import parse_stats_page

    players, keepers = parse_stats_page(
        _stats_html(), page_url="https://example.test/sports/mens-soccer/stats/2019"
    )
    assert [p["name"] for p in players] == ["Jake Simpson"]  # flipped, no Total row
    simpson = players[0]
    assert simpson["player_id"] == "2914"
    assert simpson["number"] == "7"
    assert simpson["bio_url"] == (
        "https://example.test/sports/mens-soccer/roster/jake-simpson/2914"
    )
    assert (simpson["gp"], simpson["minutes"], simpson["goals"]) == (20, 1753, 14)
    assert (simpson["assists"], simpson["points"], simpson["shots"]) == (8, 36, 72)
    assert (simpson["sog"], simpson["sog_pct"]) == (37, 0.514)
    assert (simpson["yellow"], simpson["red"]) == (5, 0)
    assert (simpson["penalty_goals"], simpson["penalty_attempts"]) == (1, 1)

    assert [k["name"] for k in keepers] == ["Dillon Dean"]
    dean = keepers[0]
    # Keeper minutes are printed with seconds; whole minutes land.
    assert dean["minutes"] == 905
    assert (dean["goals_against"], dean["gaa"]) == (4, 0.40)
    assert (dean["saves"], dean["save_pct"]) == (26, 0.867)
    assert (dean["wins"], dean["losses"], dean["ties"]) == (8, 1, 0)
    assert (dean["shutouts"], dean["shots_faced"]) == (5, 97)


def test_a_stats_page_serving_another_season_is_refused() -> None:
    """The wrapper check is the whole stats guard — the page is fully
    server-rendered, so a canonicalised year shows up in the title."""
    response = MagicMock()
    response.url = "https://example.test/sports/mens-soccer/stats/2026"
    response.text = _stats_html(title="2026 Men's Soccer Cumulative Statistics")
    session = MagicMock()
    session.get.return_value = response

    result = collect_programme(_school(), 2019, {}, session=session, layers=("stats",))

    assert result.state("stats") == "unavailable"
    reason = result.outcomes["stats"].reason or ""
    assert "2026" in reason and "2019" in reason


def test_an_honest_stats_page_lands_complete_with_both_lines_counted() -> None:
    response = MagicMock()
    response.url = "https://example.test/sports/mens-soccer/stats/2019"
    response.text = _stats_html()
    session = MagicMock()
    session.get.return_value = response

    result = collect_programme(_school(), 2019, {}, session=session, layers=("stats",))

    (url,), _ = session.get.call_args
    assert url.endswith("/stats/2019")
    assert result.state("stats") == "complete"
    assert result.outcomes["stats"].count == 2
    assert result.stat_players and result.stat_players[0]["name"] == "Jake Simpson"
    assert result.stat_keepers and result.stat_keepers[0]["name"] == "Dillon Dean"


def test_an_honest_stats_page_with_no_players_is_empty_not_unavailable() -> None:
    response = MagicMock()
    response.url = "https://example.test/sports/mens-soccer/stats/2019"
    response.text = (
        "<html><head><title>2019 Men's Soccer Cumulative Statistics</title></head>"
        "<body><table><caption>Individual Overall Offensive Statistics</caption>"
        "<tr><th>#</th></tr></table></body></html>"
    )
    session = MagicMock()
    session.get.return_value = response

    result = collect_programme(_school(), 2019, {}, session=session, layers=("stats",))

    assert result.state("stats") == "empty"
    assert "listed no players" in (result.outcomes["stats"].reason or "")


# ─── box scores ──────────────────────────────────────────────────────────────


def _boxscore_html(
    *,
    title: str = "Men's Soccer vs Union (TN) on 9/6/2025 - Box Score - Harding University Athletics",
) -> str:
    """A box score with the measured shapes: name/abbr span pairs, a winner
    marker, the Fouls group mislabelled id="offsides", a Totals footer in the
    goalie table, and an anonymous "#0 0" bench caution."""
    return f"""<html><head><title>{title}</title></head><body>
    <dl class="text-center inline">
      <dt>Date:</dt><dd>09/06/2025</dd>
      <dt>Time:</dt><dd>07:30</dd>
      <dt>Stadium:</dt><dd>Smith Memorial Soccer Complex</dd>
      <dt>Attendance:</dt><dd>115</dd>
      <dt>Officials</dt><dd>Referee: A Person</dd><dd>Asst. Referee: B Person</dd>
      <dt>VIEW</dt><dd><a href="/history">Match History</a></dd>
    </dl>
    <table><caption>Team Score By Period</caption>
      <thead><tr><th scope="col">Team</th><th>1</th><th>2</th><th>OT</th><th>Total</th></tr></thead>
      <tbody>
      <tr><th scope="row"><span class="hide-on-small-down">Harding</span><span class="hide-on-medium">HU</span></th>
        <td>0</td><td>1</td><td>1</td><td class="emphasize">2</td></tr>
      <tr><th scope="row"><span class="boxscore-winner"><span class="sr-only">Winner</span></span>
        <span class="hide-on-small-down">Union (TN)</span><span class="hide-on-medium">Union</span></th>
        <td>1</td><td>1</td><td>1</td><td class="emphasize">3</td></tr>
      </tbody></table>
    <table><caption>Scoring Summary</caption>
      <tr><th>Time</th><th>Team</th><th>Description</th></tr>
      <tr><td>37:00</td><td><span class="hide">HU</span><img alt="HU" src="x.png"></td>
        <td><span class='text-bold'>Nojus Grudis (4)</span><br>
        <span class='text-italic'>Assisted By: Romario Castro</span><br>
        <span class="text-capitalize">pass to middle, shot to bottom right corner</span></td></tr>
      <tr><td>88:33</td><td><span class="hide">Union</span></td>
        <td><span class='text-bold'>Solomon Pela (2)</span><br>
        <span class="text-capitalize">GOAL by Union Pela, Solomon.</span></td></tr>
    </table>
    <table><caption>Cautions and Ejections</caption>
      <tr><th>Time</th><th>Team</th><th>Type</th><th>Player</th></tr>
      <tr><td class="penalty-type yellow"></td><td>41:45</td><td>Union</td><td>#8 Wesley Mhlanga</td></tr>
      <tr><td class="penalty-type red"></td><td>81:19</td><td>HU</td><td>#7 Cian Halpin</td></tr>
      <tr><td class="penalty-type yellow"></td><td>42:54</td><td>HU</td><td>#0 0</td></tr>
    </table>
    <table><caption>Team Statistics</caption>
      <thead><tr><th class="text-hide">Statistic</th><th id="team-period-1">1</th><th id="team-period-2">2</th><th id="total">T</th></tr></thead>
      <tbody>
      <tr><th class="header-group" colspan="4" id="shots">Shots</th></tr>
      <tr><td>HU</td><td headers="team-period-1 shots">3</td><td headers="team-period-2 shots">11</td>
        <td headers="total shots"><span class="text-bold">14</span> <span class="text-italic">(8)</span></td></tr>
      <tr><td>Union</td><td headers="team-period-1 shots">6</td><td headers="team-period-2 shots">7</td>
        <td headers="total shots"><span class="text-bold">13</span> <span class="text-italic">(6)</span></td></tr>
      <tr><th class="header-group" colspan="4" id="saves">Saves</th></tr>
      <tr><td>HU</td><td>2</td><td>3</td><td class="text-bold" headers="total saves">5</td></tr>
      <tr><td>Union</td><td>4</td><td>3</td><td class="text-bold" headers="total saves">7</td></tr>
      <tr><th class="header-group" colspan="4" id="corners">Corner Kicks</th></tr>
      <tr><td>HU</td><td>3</td><td>2</td><td headers="total corners">5</td></tr>
      <tr><td>Union</td><td>1</td><td>4</td><td headers="total corners">5</td></tr>
      <tr><th class="header-group" colspan="4" id="offsides">Fouls</th></tr>
      <tr><td>HU</td><td>6</td><td>7</td><td headers="total offsides">13</td></tr>
      <tr><td>Union</td><td>5</td><td>8</td><td headers="total offsides">13</td></tr>
      </tbody></table>
    <table><caption>HU - Player Stats</caption>
      <tr><th>Pos</th><th>#</th><th>Player</th><th>SH</th><th>SOG</th><th>G</th><th>A</th><th>MIN</th></tr>
      <tr><th class="header-group" colspan="8">Starters</th></tr>
      <tr><td class="hide-on-small-down">FWD</td><td class="hide-on-small-down text-center">11</td>
        <td><span class="hide-on-medium mobile-jersey-number">11</span>
          <a class="boxscore_player_link" href="/sports/mens-soccer/roster/nojus-grudis/18800">Grudis, Nojus</a></td>
        <td data-label="SH">4</td><td data-label="SOG">2</td><td data-label="G">1</td><td data-label="A">0</td><td data-label="MIN">90</td></tr>
      <tr><th class="header-group" colspan="8">Substitutes</th></tr>
      <tr><td class="hide-on-small-down">MID</td><td class="hide-on-small-down text-center">14</td>
        <td><span class="hide-on-medium mobile-jersey-number">14</span>
          <a class="boxscore_player_link" href="/sports/mens-soccer/roster/jimmy-tuyishime/18811">Tuyishime, Jimmy</a></td>
        <td data-label="SH">2</td><td data-label="SOG">1</td><td data-label="G">1</td><td data-label="A">0</td><td data-label="MIN">45</td></tr>
    </table>
    <table><caption>Harding - Goalie Statistics</caption>
      <tr><th>Position</th><th>#</th><th>Goalie</th><th>Minutes</th><th>GA</th><th>Saves</th></tr>
      <tr><th class="header-group" colspan="6">Goalkeeping</th></tr>
      <tr><td class="hide-on-small-down">GK</td><td class="hide-on-small-down text-center">1</td>
        <td><span class="hide-on-medium mobile-jersey-number">1</span>
          <a class="boxscore_player_link" href="/sports/mens-soccer/roster/rinner-stewart/19271">Stewart, Rinner</a></td>
        <td data-label="Mins.">90:00</td><td data-label="GA">3</td><td data-label="S">5</td></tr>
      <tr><td class="hide-on-small-down"></td><td class="hide-on-small-down"></td><td>Totals</td>
        <td data-label="Mins.">90:00</td><td data-label="GA">3</td><td data-label="S">5</td></tr>
    </table>
    <table><caption>Union - Player Stats</caption>
      <tr><th>Pos</th><th>#</th><th>Player</th><th>SH</th><th>SOG</th><th>G</th><th>A</th><th>MIN</th></tr>
      <tr><th class="header-group" colspan="8">Starters</th></tr>
      <tr><td class="hide-on-small-down">FWD</td><td class="hide-on-small-down text-center">9</td>
        <td><span class="hide-on-medium mobile-jersey-number">9</span>Pela, Solomon</td>
        <td data-label="SH">5</td><td data-label="SOG">3</td><td data-label="G">1</td><td data-label="A">0</td><td data-label="MIN">90</td></tr>
    </table>
    </body></html>"""


_OT_FIXTURE = {
    "id": "sidearm:harding:14824",
    "date": "2025-09-06",
    "home": "union",
    "away": "harding",
    "home_score": 3,
    "away_score": 2,
    "status": "final",
}


def test_boxscore_parser_reads_the_whole_match() -> None:
    from src.sidearm_live import orient_match, parse_boxscore_page

    detail = parse_boxscore_page(
        _boxscore_html(), page_url="https://example.test/boxscore/14824"
    )
    orient_match(detail, dict(_OT_FIXTURE))

    harding, union = detail["teams"]
    assert harding["name"] == "Harding" and harding["abbr"] == "HU"
    assert harding["periods"] == [0, 1, 1] and harding["score"] == 2
    assert union["winner"] is True and "winner" not in harding
    # The Fouls group is mislabelled id="offsides" in the template; the visible
    # header text must win.
    assert harding["shots"] == 14 and harding["sog"] == 8
    assert union["saves"] == 7 and union["corners"] == 5 and union["fouls"] == 13
    assert "offsides" not in harding

    first, second = detail["scoring"]
    assert first == {
        "time": "37:00",
        "team": 0,
        "scorer": "Nojus Grudis",
        "season_total": 4,
        "assist": "Romario Castro",
        "description": "pass to middle, shot to bottom right corner",
    }
    assert second["team"] == 1 and second["scorer"] == "Solomon Pela"

    yellow, red, bench = detail["cards"]
    assert yellow == {
        "type": "yellow",
        "player": "Wesley Mhlanga",
        "number": "8",
        "time": "41:45",
        "team": 1,
    }
    assert red["type"] == "red" and red["player"] == "Cian Halpin" and red["team"] == 0
    assert bench["player"] == "0"  # the site's own anonymous bench caution

    starters = detail["teams"][0]["players"]
    assert starters[0] == {
        "name": "Nojus Grudis",
        "player_id": "18800",
        "position": "FWD",
        "number": "11",
        "started": True,
        "shots": 4,
        "sog": 2,
        "goals": 1,
        "assists": 0,
        "minutes": 90,
    }
    assert starters[1]["started"] is False and starters[1]["name"] == "Jimmy Tuyishime"
    keepers = detail["teams"][0]["keepers"]
    assert len(keepers) == 1  # the Totals footer row is not a person
    assert keepers[0]["name"] == "Rinner Stewart" and keepers[0]["minutes"] == 90
    assert detail["teams"][1]["players"][0]["name"] == "Solomon Pela"

    assert detail["stadium"] == "Smith Memorial Soccer Complex"
    assert detail["attendance"] == 115 and detail["kickoff"] == "07:30"
    assert detail["officials"] == ["Referee: A Person", "Asst. Referee: B Person"]
    # Decided match orients by score: Union 3 = home.
    assert detail["home_index"] == 1


def test_a_boxscore_for_another_date_is_refused_by_name() -> None:
    from src.sidearm_live import assert_served_match

    page = PublishedPage(
        "https://example.test/stats/2025/union/boxscore/14824",
        "https://example.test/stats/2025/union/boxscore/14824",
        _boxscore_html(
            title="Men's Soccer vs Union (TN) on 9/7/2025 - Box Score - Example"
        ),
    )
    with pytest.raises(LiveCollectionError) as refused:
        assert_served_match(page, 2025, dict(_OT_FIXTURE))
    assert "2025-09-06" in str(refused.value) and "2025-09-07" in str(refused.value)


def test_a_covid_season_boxscore_dated_the_following_spring_is_accepted() -> None:
    from src.sidearm_live import assert_served_match

    page = PublishedPage(
        "https://example.test/stats/2020/rogers-state/boxscore/900",
        "https://example.test/stats/2020/rogers-state/boxscore/900",
        "<html><head><title>Men's Soccer vs Rogers State on 4/3/2021 - Box Score - Example</title></head></html>",
    )
    assert_served_match(page, 2020, {"id": "sidearm:x:900", "date": "2021-04-03"})


def test_a_boxscore_redirected_to_the_schedule_is_refused() -> None:
    from src.sidearm_live import assert_served_match

    page = PublishedPage(
        "https://example.test/stats/2026/x/boxscore/1",
        "https://example.test/sports/mens-soccer/schedule",
        "<html><head><title>2026 Men's Soccer Schedule</title></head></html>",
    )
    with pytest.raises(LiveCollectionError, match="not a box-score page"):
        assert_served_match(page, 2026, {"id": "sidearm:x:1", "date": "2026-09-01"})


def test_a_boxscore_redirected_to_another_game_id_is_refused() -> None:
    from src.sidearm_live import assert_served_match

    page = PublishedPage(
        "https://example.test/stats/2025/union/boxscore/14824",
        "https://example.test/stats/2025/harding/boxscore/14999",
        _boxscore_html(),
    )
    with pytest.raises(LiveCollectionError, match="served box score 14999"):
        assert_served_match(page, 2025, dict(_OT_FIXTURE))


def test_a_draw_orients_by_name_affinity_not_score() -> None:
    from src.sidearm_live import orient_match

    detail = {
        "teams": [
            {"name": "Northeastern St.", "score": 1},
            {"name": "Harding", "score": 1},
        ]
    }
    orient_match(
        detail,
        {
            "home": "harding",
            "away": "northeastern-state",
            "home_score": 1,
            "away_score": 1,
        },
    )
    assert detail["home_index"] == 1


def test_an_unresolvable_draw_stays_unoriented() -> None:
    from src.sidearm_live import orient_match

    detail = {"teams": [{"name": "Alpha", "score": 0}, {"name": "Beta", "score": 0}]}
    orient_match(
        detail, {"home": "gamma", "away": "delta", "home_score": 0, "away_score": 0}
    )
    assert "home_index" not in detail


def test_play_by_play_reads_every_period_with_team_attribution() -> None:
    from pathlib import Path

    from src.sidearm_live import parse_boxscore_page

    detail = parse_boxscore_page(
        Path("tests/fixtures/sidearm_boxscore_6126.html").read_text(), page_url="x"
    )
    # Sides resolve through the column-header abbreviations, so an event's
    # team index agrees with the Score By Period order, not column position.
    assert [team["abbr"] for team in detail["teams"]] == ["OBU", "HU"]
    plays = detail["plays"]
    assert len(plays) == 101
    assert plays[0] == {
        "period": "1",
        "text": "Stewart, Rinner at goalie for Harding",
        "clock": "00:00",
        "team": 1,
        "type": "goalie",
    }
    goals = [play for play in plays if play.get("type") == "goal"]
    # Running score cells are aligned to the teams order: OBU 2, then HU pull one back.
    assert [goal["score"] for goal in goals] == [[1, 0], [2, 0], [2, 1]]
    assert {play["period"] for play in plays} == {"1", "2"}
    assert all("team" in play for play in plays)


def _play_panel_html(rows: str, *, left: str, right: str) -> str:
    return f"""<html><body>
    <table><caption>Team Score By Period</caption>
      <tr><th scope="row"><span class="hide-on-small-down">Alpha</span>
        <span class="hide-on-medium">AU</span></th><td>0</td><td>1</td><td>1</td></tr>
      <tr><th scope="row"><span class="hide-on-small-down">Beta</span>
        <span class="hide-on-medium">BU</span></th><td>1</td><td>0</td><td>1</td></tr>
    </table>
    <section id="play-by-play" class="panel"><section id="period-SO" class="period-SO">
      <table class="sidearm-table play-by-play">
        <thead><tr><th class="text-hide">Clock</th>
          <th class="text-center hide-on-medium-down">{left}<span class="hide"> - Play Description</span></th>
          <th class="text-hide hide-on-medium-down">Visiting Team Score</th>
          <th class="text-hide hide-on-medium-down">Team Logo</th>
          <th class="text-hide hide-on-medium-down">Home Team Score</th>
          <th class="text-center hide-on-medium-down">{right}<span class="hide"> - Play Description</span></th>
          <th aria-hidden="true" class="text-hide">Score</th>
          <th aria-hidden="true" class="hide">Team Indicator</th>
          <th aria-hidden="true" class="text-hide">Play</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section></section></body></html>"""


def _play_row(
    clock: str, left: str, right: str, visiting: str = "", home: str = ""
) -> str:
    return f"""<tr><td>{clock}</td>
      <td class="text-right hide-on-medium-down">{left}</td>
      <td class="text-center text-bold hide-on-medium-down">{visiting}</td>
      <td class="text-center hide-on-medium-down"></td>
      <td class="text-center text-bold hide-on-medium-down">{home}</td>
      <td class="hide-on-medium-down">{right}</td>
      <td aria-hidden="true" class="hide-on-large text-center text-bold"></td>
      <td aria-hidden="true" class="hide-on-large play"></td>
      <td aria-hidden="true" class="hide-on-large">{left or right}</td></tr>"""


def test_play_by_play_scores_align_by_abbreviation_not_column_order() -> None:
    from src.sidearm_live import parse_boxscore_page

    # Beta is the visiting (left) column but sits second in the teams order,
    # and shootout rows carry no game clock.
    html = _play_panel_html(
        _play_row(
            "--", "Shootout attempt by BU Doe, Jan MADE [Keeper, Al].", "", "1", "0"
        )
        + _play_row("00:00", "", "*")
        + _play_row("00:00", "", "GOAL by AU Roe, Sam."),
        left="BU",
        right="AU",
    )
    detail = parse_boxscore_page(html, page_url="x")
    shootout, goal = detail["plays"]
    assert shootout == {
        "period": "SO",
        "text": "Shootout attempt by BU Doe, Jan MADE [Keeper, Al].",
        "team": 1,
        "type": "shootout",
        "score": [0, 1],
    }
    # The letterless "*" footnote row narrates nothing and is dropped.
    assert goal["team"] == 0 and goal["type"] == "goal" and "score" not in goal


def test_boxscore_links_join_on_the_game_id() -> None:
    from src.sidearm_live import boxscore_links

    html = (
        '<a href="/sports/mens-soccer/stats/2025/union-tn-/boxscore/14824">Box Score</a>'
        '<a href="/sports/mens-soccer/stats/2025/drury/boxscore/14820">Box Score</a>'
    )
    links = boxscore_links(
        html, "https://example.test/sports/mens-soccer/schedule/2025"
    )
    assert links == {
        "14824": "https://example.test/sports/mens-soccer/stats/2025/union-tn-/boxscore/14824",
        "14820": "https://example.test/sports/mens-soccer/stats/2025/drury/boxscore/14820",
    }


def test_collect_match_proves_and_parses_one_fixture() -> None:
    from src.sidearm_live import collect_match

    response = MagicMock()
    response.url = (
        "https://example.test/sports/mens-soccer/stats/2025/union-tn-/boxscore/14824"
    )
    response.text = _boxscore_html()
    session = MagicMock()
    session.get.return_value = response

    detail = collect_match(session, response.url, 2025, dict(_OT_FIXTURE))

    assert detail["home_index"] == 1
    assert detail["teams"][0]["name"] == "Harding"
    assert detail["source_url"].endswith("/boxscore/14824")


def test_collect_match_archives_the_proven_page_and_its_parse(tmp_path: Path) -> None:
    """With an archive, the served box page and a sidecar carrying the parse
    fingerprint and the match record land in the fetch cache under the
    linking programme, named by the folded fixture id (bead tl-ir6)."""
    from src.page_state import BoxArchive, PageStateStore, content_signature
    from src.sidearm_live import collect_match, parse_fingerprint

    response = MagicMock()
    response.url = (
        "https://example.test/sports/mens-soccer/stats/2025/union-tn-/boxscore/14824"
    )
    response.text = _boxscore_html()
    session = MagicMock()
    session.get.return_value = response
    fingerprint = parse_fingerprint(2025)
    archive = BoxArchive(
        PageStateStore(tmp_path, 2025, "men"),
        "harding",
        "sidearm:harding:14824",
        fingerprint,
    )

    detail = collect_match(
        session, response.url, 2025, dict(_OT_FIXTURE), archive=archive
    )

    html_path = (
        tmp_path
        / "data"
        / "raw_html"
        / "harding"
        / "2025-men-box-sidearm-harding-14824.html"
    )
    assert html_path.read_text(encoding="utf-8") == _boxscore_html()
    sidecar = json.loads(
        html_path.with_suffix(".state.json").read_text(encoding="utf-8")
    )
    assert sidecar["fingerprint"] == fingerprint
    assert sidecar["parsed"] == detail
    assert sidecar["final_url"] == response.url
    assert sidecar["signature"] == content_signature(response.text)
    assert archive.load().parsed == detail  # type: ignore[union-attr]


def test_collect_match_archives_nothing_it_could_not_prove(tmp_path: Path) -> None:
    from src.page_state import BoxArchive, PageStateStore
    from src.sidearm_live import collect_match

    response = MagicMock()
    response.url = (
        "https://example.test/sports/mens-soccer/stats/2025/union-tn-/boxscore/14824"
    )
    response.text = _boxscore_html()
    session = MagicMock()
    session.get.return_value = response
    archive = BoxArchive(
        PageStateStore(tmp_path, 2025, "men"), "harding", "sidearm:harding:14824", "fp"
    )
    other_day = dict(_OT_FIXTURE, date="2025-09-07")

    with pytest.raises(LiveCollectionError, match="served the match of 2025-09-06"):
        collect_match(session, response.url, 2025, other_day, archive=archive)

    assert not (tmp_path / "data").exists()


def test_a_challenge_answer_to_a_box_score_is_refused_with_its_status() -> None:
    """The body check at the season-page seam guards the box-score fetch
    too: an empty HTTP 202 names its status, never a box score with no
    teams (bead tl-v1q.12)."""
    from src.sidearm_live import collect_match

    url = "https://example.test/sports/mens-soccer/stats/2025/union-tn-/boxscore/14824"
    response = MagicMock()
    response.status_code = 202
    response.url = url
    response.text = ""
    session = MagicMock()
    session.get.return_value = response

    with pytest.raises(LiveCollectionError) as refused:
        collect_match(session, url, 2025, dict(_OT_FIXTURE))

    assert refused.value.status == 202
    assert str(refused.value) == (
        f"[2025] box-score page {url} answered HTTP 202 with an empty body "
        "(served a challenge, not the page)"
    )


def test_a_boxscore_with_one_team_is_refused_not_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src import sidearm_live

    response = MagicMock()
    response.url = (
        "https://example.test/sports/mens-soccer/stats/2025/union-tn-/boxscore/14824"
    )
    response.text = _boxscore_html()
    session = MagicMock()
    session.get.return_value = response
    monkeypatch.setattr(
        sidearm_live,
        "parse_boxscore_page",
        lambda html, *, page_url: {
            "source_url": page_url,
            "teams": [{"name": "Harding"}],
        },
    )
    with pytest.raises(LiveCollectionError, match="rendered 1 team"):
        sidearm_live.collect_match(session, response.url, 2025, dict(_OT_FIXTURE))


def test_a_completed_game_without_a_published_score_is_scheduled_and_named(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The modern theme fills scores client-side, so a served row can carry a
    completed class and a Final span with empty result spans (measured on
    rsuhillcats.com, 2026-08-21). That row used to be stored final with no
    score. Final requires scores (beads tl-d69, tl-md2): the opponent's own
    page reads scheduled for such a row and the site's fold refuses the
    contradiction, so it is stored scheduled and named in the log."""
    html = _dom_page(
        _dom_game(
            game_id="7655",
            opponent="Oklahoma Wesleyan (Exhibition)",
            date="Aug 13 (Thu)",
            completed=True,
        )
    )
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        [fixture] = parse_schedule_page(
            html,
            page_url="https://example.test/schedule/2026",
            year=2026,
            owner_slug="rogers-state",
            aliases={"oklahoma wesleyan": "oklahoma-wesleyan"},
        )
    assert fixture["status"] == "scheduled"
    assert "home_score" not in fixture and "away_score" not in fixture
    assert fixture["match_type"] == "exhibition"
    assert fixture["conference_game"] is False
    assert (
        "sidearm:rogers-state:7655: page reads final with no score ('Final'); "
        "stored scheduled, no score"
    ) in caplog.text


def test_the_payload_marks_an_exhibition_and_stores_a_scoreless_final_as_scheduled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = {
        "id": 77,
        "date": "2026-08-13T19:00:00",
        "location_indicator": "H",
        "is_conference": False,
        "type": "completed",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Oklahoma Wesleyan (Exhibition)"},
        "result": {"team_score": None, "opponent_score": None, "status": "Final"},
    }
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        [fixture] = parse_schedule_page(
            _schedule_html(event),
            page_url="https://example.test/schedule/2026",
            year=2026,
            owner_slug="rogers-state",
            aliases={"oklahoma wesleyan": "oklahoma-wesleyan"},
        )
    assert fixture["status"] == "scheduled"
    assert "home_score" not in fixture and "away_score" not in fixture
    assert fixture["match_type"] == "exhibition"
    assert (
        "sidearm:rogers-state:77: page reads final with no score ('Final'); "
        "stored scheduled, no score"
    ) in caplog.text


def test_the_payload_stores_a_final_with_scores_as_final(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = {
        "id": 78,
        "date": "2026-09-13T19:00:00",
        "location_indicator": "H",
        "is_conference": True,
        "type": "completed",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Harding"},
        "result": {"team_score": 2, "opponent_score": 1, "status": "W"},
    }
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        [fixture] = parse_schedule_page(
            _schedule_html(event),
            page_url="https://example.test/schedule/2026",
            year=2026,
            owner_slug="rogers-state",
            aliases={"harding": "harding"},
        )
    assert fixture["status"] == "final"
    assert (fixture["home_score"], fixture["away_score"]) == (2, 1)
    assert "reads final with no score" not in caplog.text


def test_a_league_game_carries_no_match_type() -> None:
    html = _dom_page(_dom_game(game_id="8", opponent="Harding", date="Sep 17 (Thu)"))
    [fixture] = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases={"harding": "harding"},
    )
    assert fixture["status"] == "scheduled"
    assert "match_type" not in fixture


def test_a_friendly_said_only_in_the_location_is_an_exhibition() -> None:
    """The measured Northeastern State 2026 shape: the opponent's title says
    nothing, and "Friendly" rides a distinct promotion div inside the
    location element.  The flag must be read from it — and the venue must
    not, or it flattens into "Tulsa, Okla. Friendly"."""
    html = _dom_page(
        _dom_game(
            game_id="14421",
            opponent="Oral Roberts",
            date="Aug 14 (Fri)",
            side="away",
            location="Tulsa, Okla.",
            promotion="Friendly",
            completed=True,
        )
    )
    [fixture] = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="northeastern-state",
        aliases={"oral roberts": "oral-roberts"},
    )
    assert fixture["home"] == "oral-roberts"
    assert fixture["away"] == "northeastern-state"
    # Scoreless, so scheduled: final requires scores (tl-d69).
    assert fixture["status"] == "scheduled"
    assert fixture["match_type"] == "exhibition"
    assert fixture["venue"] == "Tulsa, Okla."


def test_the_payload_marks_a_friendly_said_only_in_the_location() -> None:
    event = {
        "id": 14421,
        "date": "2026-08-14T19:00:00",
        "location_indicator": "A",
        "location": "Tulsa, Okla. Friendly",
        "is_conference": False,
        "type": "completed",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Oral Roberts"},
        "result": {"team_score": None, "opponent_score": None, "status": "Final"},
    }
    [fixture] = parse_schedule_page(
        _schedule_html(event),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="northeastern-state",
        aliases={"oral roberts": "oral-roberts"},
    )
    # Scoreless, so scheduled: final requires scores (tl-d69).
    assert fixture["status"] == "scheduled"
    assert fixture["match_type"] == "exhibition"


def test_friends_university_is_an_opponent_not_a_friendly() -> None:
    """The marker is word-bounded: a school named Friends is not a friendly."""
    html = _dom_page(
        _dom_game(
            game_id="9101",
            opponent="Friends University",
            date="Sep 9 (Wed)",
            location="Wichita, Kan.",
        )
    )
    [fixture] = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases={"friends": "friends"},
    )
    assert "match_type" not in fixture
    assert fixture["venue"] == "Wichita, Kan."


def test_the_payload_does_not_mark_friends_university_as_a_friendly() -> None:
    event = {
        "id": 9102,
        "date": "2026-09-09T19:00:00",
        "location_indicator": "A",
        "location": "Wichita, Kan.",
        "is_conference": False,
        "type": "upcoming",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Friends University"},
        "result": {"team_score": None, "opponent_score": None, "status": None},
    }
    [fixture] = parse_schedule_page(
        _schedule_html(event),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases={"friends": "friends"},
    )
    assert "match_type" not in fixture
    assert fixture["venue"] == "Wichita, Kan."


# ── tl-b39: the W/L/T letter orients a result, never the printed order ──────
# oceagles.com prints the winner's score first ("L, 3-2" for a match Oklahoma
# Christian lost 2-3), verified on the live 2025 schedule 2026-09-02. These
# are that page's own strings.

_OC_2025 = [
    # (result as printed, owner is home, expected owner score, other score)
    ("W, 1-0", True, 1, 0),  # Sep 4 vs Southern Nazarene
    ("L, 3-2", False, 2, 3),  # Sep 6 at Newman — Newman 3, OC 2
    ("T, 1-1", True, 1, 1),  # Sep 10 vs Drury
    ("L, 1-0", True, 0, 1),  # Sep 13 vs Rogers State — RSU 1, OC 0
    ("W, 4-0", False, 4, 0),  # Sep 20 at Mid-America Christian
    ("L, 2-1", False, 1, 2),  # Oct 1 at UT Dallas
    ("L, 3-1", False, 1, 3),  # Nov 5 at Drury
]


@pytest.mark.parametrize(("printed", "owner_home", "owner", "other"), _OC_2025)
def test_dom_result_honours_the_letter_over_the_printed_order(
    printed: str, owner_home: bool, owner: int, other: int
) -> None:
    rows = _dom_game(
        game_id="12572",
        opponent="Newman",
        date="Sep 6 (Sat)",
        side="home" if owner_home else "away",
        result=printed,
    )
    fixture = parse_schedule_page(
        _dom_page(rows),
        page_url="https://oceagles.com/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="oklahoma-christian",
        aliases=identity_aliases(_gac(), "men"),
    )[0]
    owner_score = fixture["home_score"] if owner_home else fixture["away_score"]
    other_score = fixture["away_score"] if owner_home else fixture["home_score"]
    assert (owner_score, other_score) == (owner, other)
    letter = printed[0]
    # The invariant the bug violated: L can never store the owner higher and
    # W never lower, whatever order the page printed.
    if letter == "L":
        assert owner_score < other_score
    elif letter == "W":
        assert owner_score > other_score
    else:
        assert owner_score == other_score


def test_dom_result_refuses_a_tie_with_unequal_numbers() -> None:
    rows = _dom_game(
        game_id="9",
        opponent="Harding",
        date="Oct 1 (Wed)",
        side="home",
        result="T, 2-1",
    )
    fixture = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )[0]
    # A refused pair stores no score, and final requires scores (tl-d69).
    assert fixture["status"] == "scheduled"
    assert "home_score" not in fixture
    assert "away_score" not in fixture


def test_component_json_honours_the_letter_too() -> None:
    event = {
        "id": 12572,
        "date": "2025-09-06T19:00:00",
        "location_indicator": "A",
        "is_conference": False,
        "type": "completed",
        "schedule": {"title": "2025 Men's Soccer Schedule"},
        "opponent": {"title": "Newman"},
        "result": {"team_score": "3", "opponent_score": "2", "status": "L"},
    }
    fixture = parse_schedule_page(
        _schedule_html(event),
        page_url="https://oceagles.com/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="oklahoma-christian",
        aliases={"newman": "newman"},
    )[0]
    assert fixture["home"] == "newman"
    assert fixture["home_score"] == 3
    assert fixture["away_score"] == 2


def test_a_swap_is_logged_by_fixture_id(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        _oriented_scores("L", 3, 2, fixture_id="sidearm:oklahoma-christian:12572")
    assert "sidearm:oklahoma-christian:12572" in caplog.text
    assert "stored owner 2-3" in caplog.text


def test_a_seed_spelled_as_a_separate_word_is_a_rank() -> None:
    """The tournament theme prints the seed as its own span before the link.

    Measured: "#5 Seed Maryville University" on mckbearcats.com 2025 (game
    19843), "#8 Seed Drury University" and "#4 Seed McKendree University" on
    uisprairiestars.com 2023, "#4 seed DBU" on uttylerpatriots.com 2025. The
    hyphenated form stripped "#5" and kept "Seed", so the archive filed those
    matches under seed-maryville, seed-drury, seed-mckendree and seed-dbu,
    slugs nobody else uses (tl-4sg.22).
    """
    aliases = identity_aliases(_gac(), "men")
    assert opponent_slug("#5 Seed Maryville University", aliases) == "maryville"
    assert opponent_slug("#8 Seed Drury University", aliases) == "drury"
    assert opponent_slug("#4 Seed McKendree University", aliases) == "mckendree"
    assert opponent_slug("#4 seed DBU", aliases) == "dbu"
    # The "No. N" forms the same pages print already fold; they stay pinned so
    # a stricter seed token can never widen into them.
    assert opponent_slug("No. 25 Maryville", aliases) == "maryville"
    assert opponent_slug("No. 12 Maryville", aliases) == "maryville"
    assert opponent_slug("No. 24 McKendree", aliases) == "mckendree"


def test_a_neutral_site_row_carries_the_flag_and_keeps_the_published_sides() -> None:
    """The measured goriverhawksgo.com 2022 shape (game 12745): the row's only
    site class is sidearm-schedule-neutral-game, the indicator span says "vs",
    and the venue is "Springfield, Mo.". Both twins of a neutral game name a
    different home side, so the site's fold had only their disagreement to go
    on; the flag is its first-hand source, and home/away stay as published."""
    html = _dom_page(
        _dom_game(
            game_id="12745",
            opponent="No. 25 Maryville",
            date="Sep 4 (Sun)",
            neutral=True,
            location="Springfield, Mo.",
            result="W, 2-0",
            completed=True,
        )
        + _dom_game(
            game_id="12746",
            opponent="Harding",
            date="Sep 8 (Thu)",
            side="home",
            completed=True,
        )
    )
    neutral, hosted = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2022",
        year=2022,
        owner_slug="northeastern-state",
        aliases={"maryville": "maryville", "harding": "harding"},
    )
    assert neutral["id"] == "sidearm:northeastern-state:12745"
    assert neutral["neutral"] is True
    assert (neutral["home"], neutral["away"]) == ("northeastern-state", "maryville")
    assert neutral["venue"] == "Springfield, Mo."
    assert (neutral["home_score"], neutral["away_score"]) == (2, 0)
    # A hosted row says nothing: absence means the page published no marker.
    assert "neutral" not in hosted


def test_the_payload_marks_a_neutral_site_by_its_indicator() -> None:
    """Measured in the snuathletics.com events component: Maryville University
    with "location_indicator":"N" and "neutral_hometeam":true at
    "Claremore, OK". The indicator is the payload's whole word on the site;
    the flag rides it the same way the DOM path rides the row class."""
    event = {
        "id": 7718,
        "date": "2026-08-27T17:00:00",
        "location_indicator": "N",
        "neutral_hometeam": True,
        "location": "Claremore, OK",
        "is_conference": False,
        "type": "completed",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Maryville University"},
        "result": {"team_score": 1, "opponent_score": 0, "status": "W"},
    }
    [fixture] = parse_schedule_page(
        _schedule_html(event),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="southern-nazarene",
        aliases={"maryville": "maryville"},
    )
    assert fixture["neutral"] is True
    assert (fixture["home"], fixture["away"]) == ("southern-nazarene", "maryville")
    assert fixture["venue"] == "Claremore, OK"


def test_the_sidearm_recipe_routes_collect_programme_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live-collector table maps a platform onto a recipe now.  SideArm's
    entry is this module's own functions, looked up by name at call time so
    the module names stay the seams tests replace, and a SideArm school
    still requests ``{base}/{layer}/{year}`` and parses with them."""
    from src import sidearm_live
    from src.recipes import LIVE_COLLECTORS, SIDEARM

    assert LIVE_COLLECTORS["sidearm"] is SIDEARM
    assert _school().live_collector() == "sidearm"
    assert SIDEARM.layer_url(
        "https://example.test/sports/mens-soccer/", 2026, "schedule"
    ) == ("https://example.test/sports/mens-soccer/schedule/2026")
    assert {
        member: getattr(SIDEARM, member).__name__
        for member in (
            "assert_served_season",
            "parse_schedule",
            "assert_schedule_proven",
            "parse_roster",
            "parse_stats",
            "boxscore_links",
            "collect_match",
        )
    } == {
        "assert_served_season": "assert_served_season",
        "parse_schedule": "parse_schedule_page",
        "assert_schedule_proven": "assert_schedule_proven",
        "parse_roster": "parse_roster_page",
        "parse_stats": "parse_stats_page",
        "boxscore_links": "boxscore_links",
        "collect_match": "collect_match",
    }

    parsed: list[str] = []

    def counting_parse(html: str, *, page_url: str) -> list[dict[str, str]]:
        parsed.append(page_url)
        return parse_roster_page(html, page_url=page_url)

    monkeypatch.setattr(sidearm_live, "parse_roster_page", counting_parse)
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

    assert session.get.call_args.args[0] == (
        "https://example.test/sports/mens-soccer/roster/2019"
    )
    assert result.state("roster") == "complete"
    assert [player["name"] for player in result.players] == ["Andre Cunha"]
    assert parsed == ["https://example.test/sports/mens-soccer/roster/2019"]


def test_an_empty_2xx_is_refused_as_what_http_said() -> None:
    """Measured 2026-09-02 on tampaspartans.com: a WAF challenge answers HTTP
    202 with an empty body.  ``raise_for_status`` passes it; the seam must
    not, and must name the status rather than fail the season proof with
    "cannot prove which season", which reads as a parser problem."""
    from src.sidearm_live import fetch_published_page_conditional

    url = "https://example.test/sports/mens-soccer/schedule/2025"
    response = MagicMock()
    response.status_code = 202
    response.url = url
    response.text = ""
    session = MagicMock()
    session.get.return_value = response

    with pytest.raises(LiveCollectionError) as refused:
        fetch_published_page_conditional(session, url, 2025, "schedule")

    assert refused.value.status == 202
    assert str(refused.value) == (
        f"[2025] schedule page {url} answered HTTP 202 with an empty body "
        "(served a challenge, not the page)"
    )


def test_a_challenge_answer_is_an_unavailable_layer_not_a_retry() -> None:
    url = "https://example.test/sports/mens-soccer/schedule/2025"
    response = MagicMock()
    response.status_code = 202
    response.url = url
    response.text = ""
    session = MagicMock()
    session.get.return_value = response

    result = collect_programme(
        _school(), 2025, {}, session=session, layers=("schedule",)
    )

    assert result.state("schedule") == "unavailable"
    assert result.outcomes["schedule"].reason == (
        f"[2025] schedule page {url} answered HTTP 202 with an empty body "
        "(served a challenge, not the page)"
    )
    assert session.get.call_count == 1


FIXTURES = Path(__file__).parent / "fixtures"


def _staten_island_2026() -> dict[str, dict[str, object]]:
    """The trimmed csidolphins.com 2026 schedule, keyed by game id."""
    fixtures = parse_schedule_page(
        (FIXTURES / "sidearm_staten_island_schedule_2026.html").read_text(),
        page_url="https://csidolphins.com/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug="staten-island",
        aliases={},
    )
    return {str(fixture["id"]).rsplit(":", 1)[-1]: fixture for fixture in fixtures}


def test_a_make_up_date_result_cell_is_postponed_not_final() -> None:
    """The measured miss: Staten Island's Aug 27 row v Assumption.

    The row sits on a past date with the completed class and a result cell
    reading "Make Up Date TBD". The class alone stored it final with no
    score, and the fold refused it against Assumption's cancelled record.
    The status word wins over the class.
    """
    row = _staten_island_2026()["12026"]
    assert row["status"] == "postponed"
    assert row["date"] == "2026-08-27"
    assert row["home"] == "staten-island"
    assert row["away"] == "assumption"
    assert "home_score" not in row and "away_score" not in row


def test_the_other_staten_island_rows_keep_their_statuses() -> None:
    rows = _staten_island_2026()
    played = rows["12027"]
    assert played["status"] == "final"
    assert (played["home"], played["away"]) == ("staten-island", "saint-anselm")
    assert (played["home_score"], played["away_score"]) == (2, 3)
    upcoming = rows["12028"]
    assert upcoming["status"] == "scheduled"
    assert (upcoming["home"], upcoming["away"]) == ("georgian-court", "staten-island")
    assert "home_score" not in upcoming


@pytest.mark.parametrize(
    ("game_id", "time", "status"),
    [
        # Result cell "Make Up Date TBD"; the opponent link's aria-label reads
        # "Assumption University on August 27 1:00 PM", Assumption's own
        # record of the match says 13:00.
        ("12026", "13:00", "postponed"),
        # Final, L 2-3; the box-score link's aria-label reads "... on
        # August 29, 2026 at 2:00 PM".
        ("12027", "14:00", "final"),
    ],
)
def test_a_completed_list_row_keeps_the_kickoff_its_aria_labels_publish(
    game_id: str, time: str, status: str
) -> None:
    """Bead tl-4sg.31, measured csidolphins.com 2026.

    The game-list skin drops span.sidearm-schedule-game-time once a row is
    completed, so its played and postponed rows stored no kickoff at all.
    The page still publishes the time in the row's link aria-labels, local
    and as rendered: that is the stored kickoff.  (The filed reading, an hour
    gained, did not reproduce: every upcoming row's element and label agree.)
    """
    (row,) = parse_schedule_page(
        (FIXTURES / f"sidearm_staten_island_schedule_2026_{game_id}.html").read_text(),
        page_url="https://csidolphins.com/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug="staten-island",
        aliases={},
    )
    assert row["id"] == f"sidearm:staten-island:{game_id}"
    assert row["status"] == status
    assert row["time"] == time


def test_the_time_element_outranks_the_aria_label() -> None:
    """An upcoming row prints its kickoff in the element; the label is read
    only when no element exists, so a label that disagrees never wins."""
    html = _dom_game(
        game_id="12099", opponent="Alpha", date="Aug 30 (Sun)", time="2:30 PM"
    ).replace("<a>Alpha</a>", '<a aria-label="Alpha on August 30 3:30 PM">Alpha</a>')
    (row,) = parse_schedule_page(
        _dom_page(html),
        page_url="https://example.com/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug="owner",
        aliases={},
    )
    assert row["time"] == "14:30"


def test_a_label_without_a_clock_stores_no_kickoff() -> None:
    """A row whose links say only "History vs X" publishes no time."""
    html = _dom_game(game_id="12099", opponent="Alpha", date="Aug 30 (Sun)").replace(
        "<a>Alpha</a>", '<a aria-label="History vs Alpha">Alpha</a>'
    )
    (row,) = parse_schedule_page(
        _dom_page(html),
        page_url="https://example.com/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug="owner",
        aliases={},
    )
    assert "time" not in row


@pytest.mark.parametrize(
    "result",
    ["Make Up Date TBD", "MAKEUP TBA", "Make-up date TBD", "PPD", "Postponed"],
)
def test_every_spelling_of_a_make_up_beats_the_completed_class(result: str) -> None:
    rows = _dom_game(
        game_id="40",
        opponent="Harding",
        date="Aug 27 (Thu)",
        result=result,
        completed=True,
    )
    fixture = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
    )[0]
    assert fixture["status"] == "postponed"
    assert "home_score" not in fixture


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Make Up Date TBD", "postponed"),
        ("Makeup TBA", "postponed"),
        ("PPD", "postponed"),
        ("Cancelled", "cancelled"),
        ("Final", "final"),
    ],
)
def test_event_status_reads_the_same_words_on_the_json_path(
    status: str, expected: str
) -> None:
    event = {
        "result": {"status": status, "team_score": 1, "opponent_score": 0},
    }
    assert _event_status(event) == expected


@pytest.mark.parametrize(
    ("letter", "result", "expected"),
    [
        # catawba 2026, game 7931: status "C", type "recent", an empty
        # result, and Canceled in the rendered result cell (bead tl-0y9u).
        (
            "C",
            {"status": None, "team_score": None, "opponent_score": None},
            "cancelled",
        ),
        (
            "P",
            {"status": None, "team_score": None, "opponent_score": None},
            "postponed",
        ),
        (
            "A",
            {"status": None, "team_score": None, "opponent_score": None},
            "scheduled",
        ),
        ("O", {"status": "W", "team_score": 2, "opponent_score": 0}, "final"),
    ],
)
def test_event_status_reads_the_payload_status_letter(
    letter: str, result: dict[str, object], expected: str
) -> None:
    assert _event_status({"status": letter, "result": result}) == expected


# Bead tl-4sg.34: three PSAC hosts read as "no schedule payload and no rendered
# games" in every season, and one of them listed no players either.  The
# pipeline's own session receives exactly what a browser does (HTTP 200, same
# bytes); the pages are two skins the parser had never seen, both of which
# publish the season as a payload and render nothing server-side.


def _fixture_rows(
    name: str, *, owner_slug: str, base: str
) -> tuple[str, dict[str, dict[str, object]]]:
    html = (FIXTURES / name).read_text()
    fixtures = parse_schedule_page(
        html,
        page_url=f"{base}/schedule/2025",
        year=2025,
        owner_slug=owner_slug,
        aliases={},
    )
    return html, {str(row["id"]).rsplit(":", 1)[-1]: row for row in fixtures}


def test_the_legacy_list_skin_reads_the_season_off_its_vue_data() -> None:
    """lockhavenathletics.com and shipraiders.com: no events component, no
    li.sidearm-schedule-game rows, the whole season in one inline object."""
    from src.sidearm_live import boxscore_links, payload_seasons

    base = "https://www.lockhavenathletics.com/sports/mens-soccer"
    html, rows = _fixture_rows(
        "sidearm_lock_haven_schedule_2025.html", owner_slug="lock-haven", base=base
    )
    assert set(rows) == {"12970", "12983", "12999"}
    away_win = rows["12970"]
    assert (away_win["home"], away_win["away"]) == ("chestnut-hill", "lock-haven")
    assert (away_win["home_score"], away_win["away_score"]) == (0, 2)
    assert away_win["status"] == "final"
    assert away_win["conference_game"] is False
    assert away_win["time"] == "19:00"
    assert away_win["venue"] == "Plymouth Meeting, Pa./Plymouth-Whitemarsh High School"
    # The object spells the flag ``conference``, not ``is_conference``.
    conference_loss = rows["12983"]
    assert conference_loss["conference_game"] is True
    assert (conference_loss["home_score"], conference_loss["away_score"]) == (1, 0)
    # A division seed ("No. 2E") is a rank prefix, not part of the name.
    assert rows["12999"]["home"] == "west-chester"
    # The season the payload names is the served one, and the page counts as
    # a schedule even though it renders no rows.
    assert payload_seasons(html) == {2025}
    assert_schedule_proven(
        html,
        year=2025,
        page_url=f"{base}/schedule/2025",
        fixtures=list(rows.values()),
        owner_slug="lock-haven",
    )
    # Box-score links ride in the payload, since the skin prints no href.
    links = boxscore_links(html, f"{base}/schedule/2025")
    assert links["12983"] == f"{base}/stats/2025/slippery-rock/boxscore/12983"
    assert set(links) == set(rows)


def test_the_nuxt_skin_reads_the_season_off_its_pinia_store() -> None:
    """millersvilleathletics.com: server-rendered cards, but the data is the
    devalue-encoded state in #__NUXT_DATA__ and that is what is read."""
    from src.sidearm_live import boxscore_links

    base = "https://millersvilleathletics.com/sports/mens-soccer"
    html, rows = _fixture_rows(
        "sidearm_millersville_schedule_2025.html", owner_slug="millersville", base=base
    )
    assert set(rows) == {"10090", "10095", "10107"}
    home_win = rows["10090"]
    assert (home_win["home"], home_win["away"]) == ("millersville", "salem")
    assert (home_win["home_score"], home_win["away_score"]) == (1, 0)
    assert home_win["venue"] == "Pucillo Field"  # the object's ``facility``
    assert home_win["conference_game"] is False
    assert rows["10095"]["conference_game"] is True
    neutral = rows["10107"]
    assert neutral["neutral"] is True
    assert (neutral["home"], neutral["away"]) == ("millersville", "gannon")
    assert (neutral["home_score"], neutral["away_score"]) == (1, 2)
    assert_schedule_proven(
        html,
        year=2025,
        page_url=f"{base}/schedule/2025",
        fixtures=list(rows.values()),
        owner_slug="millersville",
    )
    assert set(boxscore_links(html, f"{base}/schedule/2025")) == set(rows)


@pytest.mark.parametrize(
    "name",
    [
        "sidearm_lock_haven_schedule_2025.html",
        "sidearm_millersville_schedule_2025.html",
    ],
)
def test_a_schedule_object_naming_another_season_is_the_trap(name: str) -> None:
    """These payloads name the season they are, so one naming 2025 under a
    2024 URL cannot be 2024 — and there is no DOM to carry 2024 instead."""
    html = (FIXTURES / name).read_text()
    with pytest.raises(LiveCollectionError, match="renders the season-2025"):
        assert_untrapped_schedule(
            html, 2024, "https://example.test/schedule/2024", [], "owner"
        )


def test_the_nuxt_roster_store_lists_its_players() -> None:
    players = parse_roster_page(
        (FIXTURES / "sidearm_millersville_roster_2025.html").read_text(),
        page_url="https://millersvilleathletics.com/sports/mens-soccer/roster/2025",
    )
    assert [p["name"] for p in players] == [
        "Kieran Finegan",
        "Quinn McCarty",
        "Mason Quinton",
    ]
    assert players[0] == {
        "name": "Kieran Finegan",
        "number": "0",
        "position": "GK",
        "height": "6'2\"",
        "weight": "175 lbs",
        "hometown": "Camp Hill, Pa.",
        "class_year": "Freshman",
        "source_url": (
            "https://millersvilleathletics.com/sports/mens-soccer/roster/kieran-finegan/12536"
        ),
    }


def test_the_nuxt_stats_store_reads_both_tables_and_skips_the_totals() -> None:
    from src.sidearm_live import parse_stats_page

    players, keepers = parse_stats_page(
        (FIXTURES / "sidearm_millersville_stats_2025.html").read_text(),
        page_url="https://millersvilleathletics.com/sports/mens-soccer/stats/2025",
    )
    assert [p["name"] for p in players] == ["Zander Leik", "Zach Richwine"]
    leik = players[0]
    assert (leik["player_id"], leik["number"]) == ("11990", "22")
    assert leik["bio_url"] == (
        "https://millersvilleathletics.com/sports/mens-soccer/roster/zander-leik/11990"
    )
    assert (leik["gp"], leik["gs"], leik["minutes"]) == (18, 11, 801)
    assert (leik["goals"], leik["assists"], leik["points"]) == (11, 4, 26)
    assert (leik["shots"], leik["shot_pct"], leik["sog"], leik["sog_pct"]) == (
        39,
        0.282,
        20,
        0.513,
    )
    assert (leik["game_winners"], leik["yellow"], leik["red"]) == (3, 2, 0)
    assert (leik["penalty_goals"], leik["penalty_attempts"]) == (0, 0)
    assert [k["name"] for k in keepers] == ["Kieran Finegan", "Gavin Massimi"]
    massimi = keepers[1]
    assert massimi["minutes"] == 1276  # "1276:25" as printed
    assert (massimi["goals_against"], massimi["gaa"]) == (12, 0.85)
    assert (massimi["saves"], massimi["save_pct"]) == (48, 0.8)
    assert (massimi["wins"], massimi["losses"], massimi["ties"]) == (10, 2, 2)
    assert (massimi["shutouts"], massimi["shots_faced"]) == (5, 133)


_MILLERSVILLE_BOX_URL = (
    "https://millersvilleathletics.com/sports/mens-soccer/stats/2026/"
    "lackawanna/boxscore/10767"
)
_MILLERSVILLE_BOX_FIXTURE = {
    "id": "sidearm:millersville:10767",
    "date": "2026-10-24",
    "home": "millersville",
    "away": "lackawanna",
    "home_score": 3,
    "away_score": 0,
    "status": "final",
}


def test_the_nuxt_box_score_reads_the_whole_match_off_its_store() -> None:
    """The nextgen box score (millersvilleathletics.com, 2026-11-08) captions
    no table; the match rides in its Pinia boxscore store, read into the
    classic parser's shape and proved and oriented exactly as before."""
    from src.sidearm_live import parse_match_page

    page = PublishedPage(
        _MILLERSVILLE_BOX_URL,
        _MILLERSVILLE_BOX_URL,
        (FIXTURES / "sidearm_millersville_box_2026_10767.html").read_text(),
    )
    detail = parse_match_page(page, 2026, dict(_MILLERSVILLE_BOX_FIXTURE))

    lackawanna, millersville = detail["teams"]
    assert {
        key: value
        for key, value in lackawanna.items()
        if key not in {"players", "keepers"}
    } == {
        "name": "Lackawanna",
        "abbr": "LACK",
        "score": 0,
        "periods": [0, 0],
        "shots": 3,
        "saves": 6,
        "corners": 2,
        "fouls": 12,
        "offsides": 2,
        "sog": 1,
    }
    assert millersville["name"] == "Millersville" and millersville["abbr"] == "VILLE"
    assert millersville["score"] == 3 and millersville["periods"] == [2, 1]
    assert millersville["winner"] is True and "winner" not in lackawanna
    # The store's totals.miscStats prints zero corners and offsides; the
    # Team Statistics table the page renders sums the per-period rows.
    assert (millersville["shots"], millersville["sog"]) == (26, 9)
    assert (millersville["corners"], millersville["offsides"]) == (7, 3)
    assert detail["home_index"] == 1

    # Only who played, starters first; the roster-linked side carries ids.
    assert millersville["players"][0] == {
        "name": "Kieran Finegan",
        "player_id": "12536",
        "position": "GK",
        "number": "0",
        "started": True,
        "shots": 0,
        "sog": 0,
        "goals": 0,
        "assists": 0,
        "minutes": 72,
    }
    names = [line["name"] for line in millersville["players"]]
    assert "Gavin Massimi" not in names and "Aidan Thomas" not in names
    assert len(names) == 23 and len(lackawanna["players"]) == 21
    assert "Abass Ndiaye" in names  # the store's "Ndiaye, Abass " flipped
    started = [line["started"] for line in millersville["players"]]
    assert started == sorted(started, reverse=True)
    assert lackawanna["players"][0] == {
        "name": "Kevin Nievas",
        "position": "GK",
        "number": "1",
        "started": True,
        "shots": 0,
        "sog": 0,
        "goals": 0,
        "assists": 0,
        "minutes": 90,
    }
    assert lackawanna["keepers"] == [
        {
            "name": "Kevin Nievas",
            "position": "GK",
            "number": "1",
            "minutes": 90,
            "goals_against": 3,
            "saves": 6,
        }
    ]
    assert [k["name"] for k in millersville["keepers"]] == [
        "Kieran Finegan",
        "Logan Kratz",
    ]

    assert detail["scoring"] == [
        {
            "time": "00:50",
            "team": 1,
            "scorer": "Zander Leik",
            "season_total": 6,
            "assist": "Matias Schmidt , Brian ONeill",
            "description": (
                "GOAL by VILLE Leik, Zander Assist by Schmidt, Matias and ONeill, Brian."
            ),
        },
        {
            "time": "21:15",
            "team": 1,
            "scorer": "Roy Parkyn",
            "season_total": 8,
            "description": "GOAL by VILLE Parkyn, Roy.",
        },
        {
            "time": "65:58",
            "team": 1,
            "scorer": "Omar Warthen Jr",
            "season_total": 3,
            "assist": "John Fiorillo",
            "description": "GOAL by VILLE Warthen Jr, Omar Assist by Fiorillo, John.",
        },
    ]
    assert detail["cards"] == [
        {
            "type": "yellow",
            "player": "Will Claugh",
            "number": "8",
            "time": "78:37",
            "team": 0,
        }
    ]

    plays = detail["plays"]
    assert len(plays) == 113
    assert plays[0] == {
        "period": "1",
        "text": "Finegan, Kieran at goalie for Millersville",
        "clock": "00:00",
        "team": 1,
        "type": "goalie",
    }
    assert plays[7] == {
        "period": "1",
        "text": "Shot by VILLE Jones, Andrew, top right, saved by Nievas, Kevin.",
        "clock": "11:32",
        "team": 1,
        "type": "shot",
    }
    assert plays[97]["text"] == "Yellow card on LACK Claugh, Will."
    assert (plays[97]["team"], plays[97]["type"]) == (0, "yellow")
    # The period markers name team "0": no side, so no attribution.
    assert plays[47] == {
        "period": "1",
        "text": "End of period [45:00].",
        "clock": "45:00",
        "type": "period",
    }
    assert sum("team" not in play for play in plays) == 3
    goals = [play for play in plays if play.get("type") == "goal"]
    assert [goal["score"] for goal in goals] == [[0, 1], [0, 2], [0, 3]]

    assert detail["stadium"] == "Pucillo Field"
    assert detail["attendance"] == 127 and detail["kickoff"] == "01:00"
    assert detail["officials"] == [
        "Referee: Brian Holden",
        "Asst. Referee: Ryan Difiore",
        "Asst. Referee: Bukhosi Ndlovu",
    ]


def _nuxt_box_page(
    box: dict[str, object],
    *,
    title: str = "Men's Soccer vs Beta on 9/9/2026 - Box Score - Example",
    body: str = "",
) -> str:
    """A minimal Nuxt page whose devalue payload holds one boxscore store,
    with ``body`` as the server-rendered markup beside it."""
    values: list[object] = []

    def encode(value: object) -> int:
        if value is None:
            return -1
        index = len(values)
        values.append(None)
        if isinstance(value, dict):
            values[index] = {key: encode(item) for key, item in value.items()}
        elif isinstance(value, list):
            values[index] = [encode(item) for item in value]
        else:
            values[index] = value
        return index

    encode({"pinia": {"boxscore": {"boxscore": {"1": box}, "isLoading": False}}})
    return (
        f"<html><head><title>{title}</title></head><body>{body}"
        '<script type="application/json" id="__NUXT_DATA__">'
        f"{json.dumps(values)}</script></body></html>"
    )


def _nuxt_side(team_id: str, name: str, score: str) -> dict[str, object]:
    first = {"shots": "2", "saves": "3", "fouls": "4", "corners": "1", "offsides": "0"}
    second = {"shots": "7", "saves": "1", "fouls": "4", "corners": "2"}
    return {
        "id": team_id,
        "name": name,
        "scoreSummary": {"score": score, "periodSummaries": [first, second]},
        "players": [],
    }


def _nuxt_play(team: str, home: bool, action: str, text: str) -> dict[str, object]:
    return {
        "period": "1",
        "action": action,
        "isAHomeTeam": home,
        "team": team,
        "clock": "10:00",
        "text": text,
    }


def test_a_nuxt_box_score_leaves_unresolvable_references_unattributed() -> None:
    from src.sidearm_live import parse_boxscore_page

    box = {
        "visitingTeam": _nuxt_side("BU", "Beta", "1"),
        "homeTeam": _nuxt_side("AU", "Alpha", "0"),
        "winningTeamId": "BU",
        "losingTeamId": "AU",
        "periodScoresAway": ["1", "0"],
        "periodScoresHome": ["0", "0"],
        "scores": [
            {
                "isAHomeTeam": False,
                "teamId": "BU",
                "time": "10:00",
                "nameOfPlayer": "Sam Roe",
                "seasonGoalNumber": "2",
                "description": "GOAL by BU Roe, Sam.",
                "scoringAssistsOutput": "",
            }
        ],
        "penalties": [
            # The site's own anonymous bench caution, printed "#0 0".
            {
                "teamId": "BU",
                "time": "82:43",
                "type": "YELLOW",
                "nameOfPlayer": "0",
                "uniformNumber": "0",
            },
            {
                "teamId": "ZZ",
                "time": "88:00",
                "type": "YELLOW-RED",
                "nameOfPlayer": "Al Roe",
                "uniformNumber": "5",
            },
        ],
        "plays": [
            _nuxt_play("XYZ", True, "SHOT", "Shot by XYZ Doe, Jan."),
            # The side flag contradicts the id: neither is trusted.
            _nuxt_play("BU", True, "GOAL", "GOAL by BU Roe, Sam."),
            _nuxt_play("AU", True, "FOUL", "Foul on Poe, Kim."),
        ],
    }
    detail = parse_boxscore_page(_nuxt_box_page(box), page_url="x")

    beta, alpha = detail["teams"]
    assert (beta["name"], beta["score"], beta["winner"]) == ("Beta", 1, True)
    assert beta["periods"] == [1, 0] and "winner" not in alpha
    assert (beta["shots"], beta["corners"], beta["fouls"]) == (9, 3, 8)
    # A per-period field one period leaves out is not totalled.
    assert "offsides" not in beta and "sog" not in beta and "players" not in beta
    bench, unknown = detail["cards"]
    assert bench == {
        "type": "yellow",
        "player": "0",
        "number": "0",
        "time": "82:43",
        "team": 0,
    }
    assert unknown == {
        "type": "unknown",
        "player": "Al Roe",
        "number": "5",
        "time": "88:00",
    }
    # The scoring entry's own flag agrees with its id; the play's does not.
    assert detail["scoring"] == [
        {
            "time": "10:00",
            "team": 0,
            "scorer": "Sam Roe",
            "season_total": 2,
            "description": "GOAL by BU Roe, Sam.",
        }
    ]
    stray, goal, foul = detail["plays"]
    assert "team" not in stray and "team" not in goal and foul["team"] == 1
    # An unattributed goal leaves the running score unproven: none is kept.
    assert goal["type"] == "goal" and "score" not in goal
    assert not {"stadium", "attendance", "kickoff", "officials"} & set(detail)


def test_a_nuxt_penalty_logged_apart_from_goals_still_carries_its_score() -> None:
    """Measured 2026-11-08 (millersvilleathletics.com/…/boxscore/10757): a
    penalty goal arrives as action PENSHOT with its own wording; the page
    prints the running score beside it because it is a ``scores`` entry."""
    from src.sidearm_live import parse_boxscore_page

    penalty = "MIL Roy Parkyn PENALTY KICK GOAL."
    box = {
        "visitingTeam": _nuxt_side("HFU", "Holy Family", "0"),
        "homeTeam": _nuxt_side("MIL", "Millersville", "2"),
        "scores": [
            {
                "teamId": "MIL",
                "time": "10:00",
                "nameOfPlayer": "Ann Lee",
                "description": "GOAL by MIL Lee, Ann.",
            },
            {
                "teamId": "MIL",
                "time": "10:00",
                "nameOfPlayer": "Roy Parkyn",
                "seasonGoalNumber": "0",
                "description": penalty,
            },
        ],
        "plays": [
            _nuxt_play("MIL", True, "GOAL", "GOAL by MIL Lee, Ann."),
            _nuxt_play("MIL", True, "SHOT", "Shot by MIL Lee, Ann."),
            _nuxt_play("MIL", True, "PENSHOT", penalty),
        ],
    }
    goal, shot, kick = parse_boxscore_page(_nuxt_box_page(box), page_url="x")["plays"]
    assert goal["score"] == [0, 1] and "score" not in shot
    assert kick == {
        "period": "1",
        "text": penalty,
        "clock": "10:00",
        "team": 1,
        # typed a penalty, as the classic data types it; the score says goal
        "type": "penalty",
        "score": [0, 2],
    }


def test_a_nuxt_player_line_takes_the_printed_name_not_the_roster_name() -> None:
    """The store's ``name`` is the roster's ("Woodfill, Nick"); the page's
    player table prints the stat crew's ``checkName``, recased ("Woodfill,
    Nicholas"). Text as published: the line takes the printed cell, and with
    no unique cell the ``checkName`` as the store gives it — never the roster
    name the box score does not print."""
    from src.sidearm_live import parse_boxscore_page

    def player(name: str, check: str, number: str) -> dict[str, object]:
        return {
            "name": name,
            "checkName": check,
            "uniform": number,
            "position": "def",
            "gamePlayed": "1",
            "gameStarted": "1",
        }

    home = _nuxt_side("AU", "Alpha", "0")
    home["players"] = [
        player("Woodfill, Nick", "WOODFILL,NICHOLAS", "2"),
        player("Jones, Drew", "JONES,ANDREW", "8"),
    ]
    box = {
        "visitingTeam": _nuxt_side("BU", "Beta", "1"),
        "homeTeam": home,
        "periodScoresAway": ["1", "0"],
        "periodScoresHome": ["0", "0"],
    }
    # only Woodfill's row is rendered: Jones falls back to the checkName
    body = (
        '<table><tr><td class="s-table-whole-td-clickable">'
        '<a href="/roster/nick-woodfill/1"> Woodfill, Nicholas</a></td></tr></table>'
    )
    detail = parse_boxscore_page(_nuxt_box_page(box, body=body), page_url="x")
    names = [line["name"] for line in detail["teams"][1]["players"]]
    assert names == ["Nicholas Woodfill", "ANDREW JONES"]


def test_a_box_score_page_with_neither_layout_is_still_refused() -> None:
    from src.sidearm_live import parse_match_page

    url = "https://example.test/sports/mens-soccer/stats/2026/beta/boxscore/1"
    fixture = {"id": "sidearm:example:1", "date": "2026-09-09"}
    title = "Men's Soccer vs Beta on 9/9/2026 - Box Score - Example"
    bare = f"<html><head><title>{title}</title></head><body><p>Final</p></body></html>"
    # A Nuxt page whose store carries no match is no box score either.
    storeless = _nuxt_box_page({"isLoading": False}, title=title)
    for html in (bare, storeless):
        with pytest.raises(LiveCollectionError, match="rendered 0 team"):
            parse_match_page(PublishedPage(url, url, html), 2026, fixture)


def test_the_two_team_list_skin_reads_scores_and_dates_off_each_row() -> None:
    """Bead tl-4sg.29 (daemenwildcats.com): rendered rows, but the date sits
    in div.sidearm-schedule-game-date and the result is one bare number per
    team block with the letter as a row class.  Same root: a list variant
    the DOM reader had never measured."""
    base = "https://daemenwildcats.com/sports/mens-soccer"
    _, rows = _fixture_rows(
        "sidearm_daemen_schedule_2025.html", owner_slug="daemen", base=base
    )
    assert set(rows) == {"7851", "7852", "7867"}
    away_loss = rows["7851"]
    assert away_loss["date"] == "2025-09-04"
    assert (away_loss["home"], away_loss["away"]) == ("walsh", "daemen")
    assert (away_loss["home_score"], away_loss["away_score"]) == (5, 1)
    assert away_loss["status"] == "final"
    assert (away_loss["time"], away_loss["venue"]) == ("19:30", "Larry Staudt Field")
    away_win = rows["7852"]
    assert (away_win["home_score"], away_win["away_score"]) == (1, 3)
    home_loss = rows["7867"]
    assert (home_loss["home"], home_loss["away"]) == ("daemen", "staten-island")
    assert (home_loss["home_score"], home_loss["away_score"]) == (1, 5)
    # The theme marks conference games with a bare logo.
    assert home_loss["conference_game"] is True
    assert away_loss["conference_game"] is False


def test_the_all_sports_upcoming_events_block_mints_no_other_sport_rows() -> None:
    """Bead tl-4sg.41 (smcathletics.com 2026-09-07): the men's soccer page
    embeds an all-sports upcoming-events block under the same ``events``
    component type as the sport's own stub — women's soccer, volleyball,
    field hockey, tennis and a cross-country invitational, every one naming
    its sport.  None of them is a men's soccer fixture; the sport's own
    events and the rendered rows still are."""
    base = "https://smcathletics.com/sports/mens-soccer"
    html = (FIXTURES / "sidearm_saint_michaels_schedule_2026.html").read_text()
    rows = {
        str(row["id"]).rsplit(":", 1)[-1]: row
        for row in parse_schedule_page(
            html,
            page_url=f"{base}/schedule/2026",
            year=2026,
            owner_slug="saint-michael-s",
            aliases={},
            gender="men",
        )
    }
    # 9947 is a rendered row only (a played match the stub no longer lists),
    # 10129 rides the payload only, 9952 rides both.
    assert set(rows) == {"9947", "10129", "9952"}
    assert (rows["9947"]["home"], rows["9947"]["away"]) == (
        "saint-michael-s",
        "caldwell",
    )
    assert rows["10129"]["away"] == "saint-michael-s"
    assert rows["9952"]["home"] == "saint-michael-s"
    # The other gender's soccer is that programme's schedule, not this one's.
    women = {
        str(row["id"]).rsplit(":", 1)[-1]
        for row in parse_schedule_page(
            html,
            page_url=f"{base}/schedule/2026",
            year=2026,
            owner_slug="saint-michael-s",
            aliases={},
            gender="women",
        )
    }
    assert {"9816", "9817"} <= women
    assert "10129" not in women
    # A sport that is not soccer is never a row for either gender.
    for other in ("9796", "10122", "9739", "10124", "9873", "9881"):
        assert other not in rows and other not in women, other


def test_the_two_team_list_skin_strips_the_orientation_word_on_upcoming_rows() -> None:
    """Bead tl-4sg.38 (daemenwildcats.com 2026): upcoming rows print the
    orientation word as a bare span inside the opponent-name span, so the
    flattened text reads "at Molloy" / "vs D'Youville".  The word is
    orientation, never part of the opponent's identity."""
    base = "https://daemenwildcats.com/sports/mens-soccer"
    html = (FIXTURES / "sidearm_daemen_schedule_2026.html").read_text()
    rows = {
        str(row["id"]).rsplit(":", 1)[-1]: row
        for row in parse_schedule_page(
            html,
            page_url=f"{base}/schedule/2026",
            year=2026,
            owner_slug="daemen",
            aliases={"molloy": "molloy", "dyouville": "d-youville"},
        )
    }
    assert set(rows) == {"8312", "8316"}
    away = rows["8312"]
    assert (away["home"], away["away"]) == ("molloy", "daemen")
    assert (away["date"], away["status"]) == ("2026-09-19", "scheduled")
    assert away["conference_game"] is True
    home = rows["8316"]
    assert (home["home"], home["away"]) == ("daemen", "d-youville")
    assert home["conference_game"] is False
    # The payload skins name the opponent in a JSON title and carry the side
    # in location_indicator, so no orientation word can reach their slugs.
    for name, owner in (
        ("sidearm_lock_haven_schedule_2025.html", "lock-haven"),
        ("sidearm_millersville_schedule_2025.html", "millersville"),
    ):
        _, payload_rows = _fixture_rows(name, owner_slug=owner, base=base)
        assert payload_rows
        for row in payload_rows.values():
            for side in (row["home"], row["away"]):
                assert not str(side).startswith(("vs-", "v-", "at-")), (name, row["id"])


def test_a_division_seed_is_a_rank_prefix() -> None:
    from src.sidearm_live import _clean_team_name

    assert (
        _clean_team_name("No. 2E West Chester (PSAC Quarterfinal)")
        == "West Chester (PSAC Quarterfinal)"
    )
    assert _clean_team_name("2Excellent College") == "2Excellent College"


# --- Rank forms the first grammar let through (bead tl-cgb) --------------------
# The ECC files held sidearm:queens:6816 (2023-09-23) under away=5-mercy and
# sidearm:queens:7618 (2025-09-27) under away=8-mercy beside Mercy's own rows
# under mercy: the theme prints two poll slots with the first empty ("/#5"),
# and a prefix that had to start with a token never matched it. A scan of the
# 755 archived schedule pages found the rest of the family below.


@pytest.mark.parametrize(
    ("published", "name"),
    [
        # queensknights.com 2023 game 6816, 2025 game 7618, plus 9-adelphi.
        ("/#5 Mercy College", "Mercy College"),
        ("/#8 Mercy University", "Mercy University"),
        ("/#9 Adelphi University", "Adelphi University"),
        ("/No. 10 East Stroudsburg University", "East Stroudsburg University"),
        # Two polls joined by a pipe, and a tied rank.
        ("#17 | #3 Seed Fort Lewis", "Fort Lewis"),
        ("#T-15 | #3 seed CSU Pueblo", "CSU Pueblo"),
        # A bracketed seed with its own marker, its "Seed" word, or a
        # division letter, before or after a poll rank.
        ("#7 (#1 Seed) Florida Tech", "Florida Tech"),
        ("#1 seed (#8) Midwestern State", "Midwestern State"),
        ("(#3A) Christian Brothers University", "Christian Brothers University"),
        ("(#7) Cedarville University", "Cedarville University"),
        # A lone dash between the prefix and the name.
        ("No. 1/ No. 1 seed - Lynn University", "Lynn University"),
        # The seed-word and no-NN forms the runbook names (tl-4sg.22).
        ("#5 Seed Maryville University", "Maryville University"),
        ("No. 12 Maryville", "Maryville"),
        ("3-seed Drury", "Drury"),
        # A hash-marked rank glued to the name by a hyphen (wsuathletics.com
        # 2026 women, games 12026 and 12036), and the seed form it must not
        # swallow.
        ("#21-McKendree", "McKendree"),
        ("#15-Ashland", "Ashland"),
        ("#4-seed Harding", "Harding"),
        # Real names that lead with a numeral, a letter-dash, or a dash keep
        # every character: a token must end in whitespace and a dash only
        # follows a rank.
        ("2Excellent College", "2Excellent College"),
        ("T-Bird College", "T-Bird College"),
        ("21-McKendree", "21-McKendree"),
        ("Lynn - University", "Lynn - University"),
        ("UT Tyler", "UT Tyler"),
        (
            "2023 DII Men's Soccer Selection Show",
            "2023 DII Men's Soccer Selection Show",
        ),
    ],
)
def test_every_leading_rank_form_in_the_archive_is_stripped(
    published: str, name: str
) -> None:
    from src.sidearm_live import _clean_team_name

    assert _clean_team_name(published) == name


def test_a_rank_with_an_empty_first_poll_slot_is_not_in_the_slug() -> None:
    """queens 2023, game 6816: "<span>/#5</span> Mercy College", a home win for
    Mercy, 1-3.  Stored as away=5-mercy; the slug is mercy."""
    row = _archived_row(
        "sidearm_queens_schedule_2023_6816.html", year=2023, owner_slug="queens"
    )
    assert row["id"] == "sidearm:queens:6816"
    assert row["date"] == "2023-09-23"
    assert (row["home"], row["away"]) == ("queens", "mercy")
    assert (row["home_score"], row["away_score"]) == (1, 3)
    assert row["status"] == "final"
    # The payload path reads the same title through the same helper.
    assert opponent_slug("/#5 Mercy College", {}) == "mercy"
    assert opponent_slug("/#8 Mercy University", {}) == "mercy"


# --- Hosted other-match rows (beads tl-clk.10, tl-5ru) ------------------------
# A tournament host lists the other pair's match on its own schedule page.
# Measured on the host's SideArm site: the 2023 rendered list carries
# "0 Colorado Mesa vs 1 Midwestern" as the opponent cell of a neutral row at
# the host's own ground, and the 2026 events payload carries the opponent
# title "Western Oregon University vs Metropolitan State University of
# Denver" with location_indicator "N".  Neither names the owner, so neither
# is the owner's fixture: read, named as a skip, never minted.  The owner is
# recognised by the alias-aware fold, so its own published spellings count.

_HOST = "hostville"
_HOST_ALIASES = {
    "hostville": "hostville",
    "hostville griffins": "hostville",
    "alpha": "alpha",
    "bravo": "bravo",
}


def _clone_row(
    html: str,
    *,
    row_selector: str,
    name_selector: str,
    id_attr: str,
    game_id: str,
    opponent: str,
) -> str:
    """The page with its first row duplicated, renamed and re-identified."""
    import copy

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    row = soup.select_one(row_selector)
    assert row is not None
    clone = copy.copy(row)
    clone[id_attr] = game_id
    name = clone.select_one(name_selector)
    assert name is not None
    name.clear()
    name.append(opponent)
    row.insert_before(clone)
    return str(soup)


def _ids(fixtures: list[dict[str, object]]) -> set[str]:
    return {str(row["id"]).rsplit(":", 1)[-1] for row in fixtures}


def test_the_events_payload_skips_a_hosted_other_match_and_names_it() -> None:
    """The 2026 shape: two events on one day, the hosted one under an "N"
    indicator with both teams in the opponent title."""
    real = {
        "id": 13071,
        "date": "2026-08-27T19:00:00",
        "location_indicator": "H",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Alpha"},
        "result": {"status": "N"},
    }
    hosted = {
        **real,
        "id": 13070,
        "date": "2026-08-27T16:00:00",
        "location_indicator": "N",
        "opponent": {"title": "Alpha vs Bravo"},
    }
    component = {"type": "events", "data": [hosted, real]}
    html = (
        "<html><head><title>2026 Men's Soccer Schedule - Host</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url="https://host.test/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug=_HOST,
        aliases=_HOST_ALIASES,
        skips=skips,
    )
    assert [row["id"] for row in fixtures] == ["sidearm:hostville:13071"]
    assert (fixtures[0]["home"], fixtures[0]["away"]) == ("hostville", "alpha")
    assert skips == ["hosted other-match skipped: 2026-08-27, Alpha v Bravo"]


def test_the_events_payload_skips_a_round_placeholder_and_names_it() -> None:
    """Rib issue #41: the payload path minted "Gulf South Conference" and
    "NCAA First Round" as programmes; the rendered-list rule never reached
    it. A round named inside a parenthetical is still a fixture."""
    base = {
        "date": "2026-10-31T19:00:00",
        "location_indicator": "N",
        "is_conference": True,
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "result": {"team_score": None, "opponent_score": None, "status": None},
    }
    events = [
        {**base, "id": 1, "opponent": {"title": "Gulf South Conference"}},
        {
            **base,
            "id": 2,
            "date": "2026-11-13T00:00:00",
            "opponent": {"title": "NCAA First Round"},
        },
        {
            **base,
            "id": 3,
            "date": "2026-12-03T00:00:00",
            "opponent": {"title": "NCAA Semifinals (MIAA)"},
        },
        {**base, "id": 4, "date": "2026-11-05T00:00:00", "opponent": {"title": "TBA"}},
        {
            **base,
            "id": 5,
            "date": "2026-11-01T13:00:00",
            "opponent": {"title": "No. 2E Alpha (PSAC Quarterfinal)"},
        },
    ]
    component = {"type": "events", "data": events}
    html = (
        "<html><head><title>2026 Men's Soccer Schedule - Host</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url="https://host.test/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug=_HOST,
        aliases=_HOST_ALIASES,
        skips=skips,
    )
    assert [row["id"] for row in fixtures] == ["sidearm:hostville:5"]
    assert {fixtures[0]["home"], fixtures[0]["away"]} == {"hostville", "alpha"}
    assert skips == [
        "round placeholder skipped: 2026-10-31, Gulf South Conference",
        "round placeholder skipped: 2026-11-13, NCAA First Round",
        "round placeholder skipped: 2026-12-03, NCAA Semifinals (MIAA)",
        "round placeholder skipped: 2026-11-05, TBA",
    ]


def test_round_placeholder_reads_every_measured_slot_and_no_opponent() -> None:
    """The 27 shapes measured over the archived payloads on 2026-09-12, and
    the opponent strings nearest to them that must stay opponents."""
    slots = [
        "Gulf South Conference",
        "CCAA Tournament",
        "TBD",
        "TBA",
        "GLVC Quarterfinals",
        "PBC Semifinals",
        "PBC Championship",
        "PBC Quartefinals",
        "NCAA Selection Show",
        "NCAA First Round",
        "NCAA Second Round",
        "NCAA Third Round",
        "NCAA Quarterfinals",
        "NCAA Semifinals (MIAA)",
        "NCAA Finals (MIAA)",
        "Quarterfinal",
        "Semifinal",
        "CCAA Tournament First Round (At Campus Sites)",
        "CCAA Tournament Semifinals (at Cal Poly Pomona)",
        "CCAA Tournament Championship Game (At Cal Poly Pomona)",
        "SAC Tournament",
        "PSAC Finals (top East seed)",
        "NCAA Tournament First and Second Rounds",
        "NCAA 1st Round",
        "Lone Star Conference",
        "Conference Carolinas",
        "Pennsylvania State Athletic Conference (PSAC)",
        "NCAA D2 National 3rd Round and Quarterfinals",
        "NCAA First and Second Rounds",
        "NCAA 1st and 2nd Rounds",
        "NCAA 1st/2nd Rounds",
        "NCAA D2 National 1st and 2nd Rounds",
        "NCAA Opening Round",
        "NCAA Midwest Regional",
        "NCAA South Regional",
        "USCA/Lander Winner",
        "#6 Seed Dallas Baptist OR #3 Seed St. Mary's",
    ]
    opponents = [
        "No. 2E West Chester (PSAC Quarterfinal)",
        "No. 1 Seed Post (CACC Championship)",
        "Friends University",
        "Finlandia",
        "Oklahoma Wesleyan (Exhibition)",
        "Rogers State University (Okla.)",
        "Southern Nazarene",
        "Lee (Conference Opener)",
        "Oregon Tech",
        "Lake Erie (Senior Night)",
    ]
    assert [name for name in slots if not round_placeholder(name)] == []
    assert [name for name in opponents if round_placeholder(name)] == []


def test_the_rendered_list_skin_skips_a_hosted_other_match() -> None:
    """The 2023 shape on a server-rendered list: the opponent cell reads
    "0 Colorado Mesa vs 1 Midwestern" (scores interleaved, no side span).
    Here the csidolphins.com page gains such a row beside its real ones."""
    base = "https://csidolphins.com/sports/mens-soccer"
    html = _clone_row(
        (FIXTURES / "sidearm_staten_island_schedule_2026.html").read_text(),
        row_selector="li.sidearm-schedule-game",
        name_selector=".sidearm-schedule-game-opponent-name",
        id_attr="data-game-id",
        game_id="12099",
        opponent="0 Alpha vs 1 Bravo",
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url=f"{base}/schedule/2026",
        year=2026,
        owner_slug="staten-island",
        aliases={**_HOST_ALIASES, "staten island": "staten-island"},
        skips=skips,
    )
    assert _ids(fixtures) == {"12026", "12027", "12028"}
    assert all("staten-island" in (row["home"], row["away"]) for row in fixtures)
    assert skips == ["hosted other-match skipped: 2026-08-27, Alpha v Bravo"]


def test_the_legacy_list_skin_skips_a_hosted_other_match() -> None:
    """The Vue schedule object (lockhavenathletics.com) gains a game whose
    opponent title names two other teams."""
    import re

    base = "https://www.lockhavenathletics.com/sports/mens-soccer"
    lines = (FIXTURES / "sidearm_lock_haven_schedule_2025.html").read_text().split("\n")
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*schedule\s*:\s*)(\{.*\})(\s*,?\s*)$", line)
        if match is None:
            continue
        schedule = json.loads(match.group(2))
        hosted = json.loads(json.dumps(schedule["games"][0]))
        hosted["id"] = 12998
        hosted["location_indicator"] = "N"
        hosted["opponent"]["title"] = "Alpha vs. Bravo"
        schedule["games"].insert(0, hosted)
        lines[index] = match.group(1) + json.dumps(schedule) + match.group(3)
        break
    else:  # pragma: no cover - the fixture carries the line
        raise AssertionError("no schedule object line")
    skips: list[str] = []
    fixtures = parse_schedule_page(
        "\n".join(lines),
        page_url=f"{base}/schedule/2025",
        year=2025,
        owner_slug="lock-haven",
        aliases={**_HOST_ALIASES, "lock haven": "lock-haven"},
        skips=skips,
    )
    assert _ids(fixtures) == {"12970", "12983", "12999"}
    assert all("lock-haven" in (row["home"], row["away"]) for row in fixtures)
    assert skips == ["hosted other-match skipped: 2025-09-04, Alpha v Bravo"]


def test_the_nuxt_skin_skips_a_hosted_other_match() -> None:
    """The devalue-encoded Pinia state (millersvilleathletics.com) gains a
    game: new values are appended to the flat array and the game's index
    pushed onto the schedule's games list."""
    from bs4 import BeautifulSoup

    base = "https://millersvilleathletics.com/sports/mens-soccer"
    html = (FIXTURES / "sidearm_millersville_schedule_2025.html").read_text()
    element = BeautifulSoup(html, "lxml").find("script", id="__NUXT_DATA__")
    assert element is not None
    encoded = element.get_text()
    values = json.loads(encoded)
    [games_index] = [
        value["games"]
        for value in values
        if isinstance(value, dict) and "games" in value and "title" in value
    ]
    games: list[int] = values[games_index]
    first: dict[str, int] = dict(values[games[0]])
    opponent: dict[str, int] = dict(values[first["opponent"]])
    values.append("Alpha vs Bravo")
    opponent["title"] = len(values) - 1
    values.append(opponent)
    first["opponent"] = len(values) - 1
    values.append(10999)
    first["id"] = len(values) - 1
    values.append(first)
    games.insert(0, len(values) - 1)
    html = html.replace(encoded, json.dumps(values))

    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url=f"{base}/schedule/2025",
        year=2025,
        owner_slug="millersville",
        aliases={**_HOST_ALIASES, "millersville": "millersville"},
        skips=skips,
    )
    assert _ids(fixtures) == {"10090", "10095", "10107"}
    assert all("millersville" in (row["home"], row["away"]) for row in fixtures)
    assert skips == ["hosted other-match skipped: 2025-09-04, Alpha v Bravo"]


def test_the_two_team_list_skin_skips_a_hosted_other_match() -> None:
    """daemenwildcats.com's row blocks name the opponent in their own span;
    a row whose span names two other teams is not Daemen's."""
    base = "https://daemenwildcats.com/sports/mens-soccer"
    html = _clone_row(
        (FIXTURES / "sidearm_daemen_schedule_2025.html").read_text(),
        row_selector="li.sidearm-schedule-game",
        name_selector=".sidearm-schedule-game-opponent-name",
        id_attr="data-game-id",
        game_id="7899",
        opponent="Alpha vs Bravo",
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url=f"{base}/schedule/2025",
        year=2025,
        owner_slug="daemen",
        aliases={**_HOST_ALIASES, "daemen": "daemen"},
        skips=skips,
    )
    assert _ids(fixtures) == {"7851", "7852", "7867"}
    assert all("daemen" in (row["home"], row["away"]) for row in fixtures)
    # The cloned row is the page's first, the Nov 1 one.
    assert skips == ["hosted other-match skipped: 2025-11-01, Alpha v Bravo"]


def test_a_two_team_row_naming_the_owner_by_alias_is_the_owners_fixture() -> None:
    """The owner is matched by the alias-aware fold, not the string: a row
    reading "Hostville Griffins vs Alpha" is Hostville v Alpha, and the
    same row with the owner second is read the same way."""
    rows = _dom_game(
        game_id="31", opponent="Hostville Griffins vs Alpha", date="Aug 27 (Thu)"
    ) + _dom_game(
        game_id="32", opponent="Bravo v Hostville Griffins", date="Aug 29 (Sat)"
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://host.test/schedule/2026",
        year=2026,
        owner_slug=_HOST,
        aliases=_HOST_ALIASES,
        skips=skips,
    )
    assert [(row["home"], row["away"]) for row in fixtures] == [
        ("hostville", "alpha"),
        ("hostville", "bravo"),
    ]
    assert skips == []


def test_a_hosted_other_match_is_not_minted_under_the_owners_id() -> None:
    """The row the old parser minted as a fixture between the two named
    teams under the host's id (the duplicate of the real match, which one
    of the two publishes itself) is now the named skip."""
    rows = _dom_game(
        game_id="9", opponent="Southern Nazarene vs. Maryville", date="Aug 27 (Thu)"
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        _dom_page(rows),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases=identity_aliases(_gac(), "men"),
        skips=skips,
    )
    assert fixtures == []
    assert skips == [
        "hosted other-match skipped: 2026-08-27, Southern Nazarene v Maryville"
    ]
    # Without a skips list the row is still not minted, just not narrated.
    assert (
        parse_schedule_page(
            _dom_page(rows),
            page_url="https://example.test/schedule/2026",
            year=2026,
            owner_slug="rogers-state",
            aliases=identity_aliases(_gac(), "men"),
        )
        == []
    )


def test_collect_programme_carries_the_skips_on_the_schedule_outcome() -> None:
    from src.sidearm_live import LAYER_SCHEDULE

    component = {
        "type": "events",
        "data": [
            {
                "id": 1,
                "date": "2026-09-05T19:00:00",
                "location_indicator": "H",
                "schedule": {"title": "2026 Men's Soccer Schedule"},
                "opponent": {"title": "Alpha vs Bravo"},
            },
            {
                "id": 2,
                "date": "2026-09-05T16:00:00",
                "location_indicator": "H",
                "schedule": {"title": "2026 Men's Soccer Schedule"},
                "opponent": {"title": "Bravo"},
            },
        ],
    }
    response = MagicMock()
    response.url = "https://example.test/sports/mens-soccer/schedule/2026"
    response.text = (
        "<html><head><title>2026 Men's Soccer Schedule - Example</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )
    session = MagicMock()
    session.get.side_effect = [response]

    result = collect_programme(
        _school(), 2026, _HOST_ALIASES, session=session, layers=("schedule",)
    )

    outcome = result.outcomes[LAYER_SCHEDULE]
    assert outcome.state == "complete"
    assert outcome.count == 1
    assert outcome.reason is None
    assert outcome.skips == ("hosted other-match skipped: 2026-09-05, Alpha v Bravo",)
    assert [row["id"] for row in result.fixtures] == ["sidearm:harding:2"]


def test_a_hosted_row_in_both_the_payload_and_the_dom_is_one_skip() -> None:
    """The measured 2026 host page carries each hosted row twice, in the
    events payload and in the rendered list; the summary names it once."""
    component = {
        "type": "events",
        "data": [
            {
                "id": 13070,
                "date": "2026-08-27T16:00:00",
                "location_indicator": "N",
                "schedule": {"title": "2026 Men's Soccer Schedule"},
                "opponent": {"title": "Alpha vs Bravo"},
            }
        ],
    }
    rows = _dom_game(game_id="13070", opponent="Alpha vs Bravo", date="Aug 27 (Thu)")
    html = _dom_page(
        rows, component=f"<script>\nvar obj = {json.dumps(component)};\n</script>"
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url="https://host.test/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug=_HOST,
        aliases=_HOST_ALIASES,
        skips=skips,
    )
    assert fixtures == []
    assert skips == ["hosted other-match skipped: 2026-08-27, Alpha v Bravo"]


# Bead tl-ttr: a calendar event SideArm files under an opponent record (a
# media day, with an opponent id, a logo and a JSON-LD SportsEvent) reached the
# fixture contract as a countable fixture. The tell a match can never carry is
# the start-to-end time range printed where a match prints its kickoff.


def test_a_calendar_event_on_the_rendered_list_is_a_named_skip() -> None:
    """gohilltoppers.com 2026: row 8813, "Men's Soccer Media Day", prints
    "11:25 AM-12:40 PM" in the date cell and in the opponent link's
    aria-label; row 8616, the real match vs Southwestern, prints "7:00 PM".
    The event is named, never minted; the match still parses; the page's
    fixture count drops by exactly one."""
    from bs4 import BeautifulSoup

    html = (FIXTURES / "sidearm_saint_edwards_schedule_2026.html").read_text()
    rendered = BeautifulSoup(html, "lxml").select("li.sidearm-schedule-game")
    assert len(rendered) == 2
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url="https://gohilltoppers.com/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug="saint-edwards",
        aliases={"southwestern university": "southwestern"},
        skips=skips,
    )
    assert len(fixtures) == len(rendered) - 1
    [match] = fixtures
    assert match["id"] == "sidearm:saint-edwards:8616"
    assert (match["home"], match["away"]) == ("saint-edwards", "southwestern")
    assert (match["date"], match["time"], match["status"]) == (
        "2026-08-22",
        "19:00",
        "scheduled",
    )
    assert match["venue"] == "Lewis-Chen Family Field"
    assert skips == ["calendar event skipped: 2026-08-09, Men's Soccer Media Day"]
    # Without a skips list the row is still not minted, just not narrated.
    assert _ids(
        parse_schedule_page(
            html,
            page_url="https://gohilltoppers.com/sports/mens-soccer/schedule/2026",
            year=2026,
            owner_slug="saint-edwards",
            aliases={"southwestern university": "southwestern"},
        )
    ) == {"8616"}


def test_a_calendar_event_in_the_payload_is_a_named_skip() -> None:
    """The events component's copy of the same tell: the rendered ``time``
    string printing a range, or an ``end_date`` after ``date``. No archived
    payload carries the media-day row (the St. Edward's events stub is
    windowed to upcoming games), so the shape here is the one the rendered
    range must come from. A stub whose end_date is EARLIER than its start
    (measured: cal-state-east-bay 7008, a real match) stays a fixture."""
    real = {
        "id": 13071,
        "date": "2026-08-22T19:00:00",
        "end_date": None,
        "time": "7:00 PM",
        "tbd": False,
        "location_indicator": "H",
        "is_conference": False,
        "type": "upcoming",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "opponent": {"title": "Alpha"},
        "result": {"status": "N"},
    }
    by_time = {
        **real,
        "id": 13070,
        "date": "2026-08-09T11:25:00",
        "time": "11:25 AM-12:40 PM",
        "opponent": {"title": "Men's Soccer Media Day"},
    }
    by_end_date = {
        **real,
        "id": 13069,
        "date": "2026-08-10T09:00:00",
        "end_date": "2026-08-10T10:00:00",
        "time": "9:00 AM",
        "opponent": {"title": "Community Clinic"},
    }
    end_before_start = {
        **real,
        "id": 13072,
        "date": "2026-09-27T15:00:00",
        "end_date": "2026-09-27T11:30:00",
        "time": "3:00 PM",
        "opponent": {"title": "Bravo"},
    }
    component = {
        "type": "events",
        "data": [by_time, by_end_date, real, end_before_start],
    }
    html = (
        "<html><head><title>2026 Men's Soccer Schedule - Host</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url="https://host.test/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug=_HOST,
        aliases=_HOST_ALIASES,
        skips=skips,
    )
    assert [row["id"] for row in fixtures] == [
        "sidearm:hostville:13071",
        "sidearm:hostville:13072",
    ]
    assert [(row["away"], row["time"]) for row in fixtures] == [
        ("alpha", "19:00"),
        ("bravo", "15:00"),
    ]
    assert skips == [
        "calendar event skipped: 2026-08-09, Men's Soccer Media Day",
        "calendar event skipped: 2026-08-10, Community Clinic",
    ]


def test_the_time_range_marker_reads_ranges_and_nothing_else() -> None:
    """The cell forms a range can take, and the texts a match row prints
    that must never read as one (a kickoff, a score, a repeated date)."""
    from src.sidearm_live import _calendar_event_marked

    assert _calendar_event_marked("Aug 9 (Sun) 11:25 AM-12:40 PM")
    assert _calendar_event_marked("11 a.m. - 1 p.m.")
    assert _calendar_event_marked("11:25-12:40 PM")
    assert _calendar_event_marked("9:00 AM \u2013 10:00 AM")
    for text in (
        "Aug 22 (Sat) 7:00 PM",
        "Aug 20 (Sat) Aug 20 (Sat)",
        "W, 2-1",
        "T, 1-1 (SO, 4-3)",
        "7:00 PM - TBA",
        "Noon",
        "",
    ):
        assert not _calendar_event_marked(text), text


# Beads tl-d69 and tl-md2: a fixture is final only when it carries a score.
# The twin-check after the 2026-09-02 GAC re-collect named rows the owner's
# page marks completed or "Final" with no score while the opponent's own page
# reads scheduled; the site's fold throws on that split. Each fixture below is
# one archived row, trimmed, its source and fetch date in the file's header.


def _archived_row(name: str, *, year: int, owner_slug: str) -> dict[str, object]:
    [fixture] = parse_schedule_page(
        (FIXTURES / name).read_text(),
        page_url=f"https://example.test/schedule/{year}",
        year=year,
        owner_slug=owner_slug,
        aliases={},
    )
    return fixture


def test_a_final_span_with_no_score_is_scheduled_and_named(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Shape 1: newman 2023, game 6929. "Aug 26 (Sat) / Final Edmond, OK
    EXHIBITION at Oklahoma Christian", completed class and Final span, empty
    result spans; Oklahoma Christian's own page reads scheduled."""
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        row = _archived_row(
            "sidearm_newman_schedule_2023_6929.html", year=2023, owner_slug="newman"
        )
    assert row["id"] == "sidearm:newman:6929"
    assert row["date"] == "2023-08-26"
    assert row["away"] == "newman"
    assert row["status"] == "scheduled"
    assert "home_score" not in row and "away_score" not in row
    assert row["match_type"] == "exhibition"
    assert (
        "sidearm:newman:6929: page reads final with no score ('Final'); "
        "stored scheduled, no score"
    ) in caplog.text


@pytest.mark.parametrize(
    ("name", "year", "owner_slug", "game_id", "date"),
    [
        # Result cell "Rescheduled for 10/21" (class text-italic), completed class.
        (
            "sidearm_eckerd_schedule_2024_8371.html",
            2024,
            "eckerd",
            "8371",
            "2024-09-28",
        ),
        # Final span beside a result cell reading "Post." (abbreviated).
        (
            "sidearm_barry_schedule_2025_14613.html",
            2025,
            "barry",
            "14613",
            "2025-09-13",
        ),
        # Final span beside "Suspended Due To Lightning".
        (
            "sidearm_georgian_court_schedule_2025_6377.html",
            2025,
            "georgian-court",
            "6377",
            "2025-09-06",
        ),
        # Two-team list skin: "PPD to 10/25" in a game-cancelled div, no
        # result element at all, so the word is read from the whole row.
        (
            "sidearm_daemen_schedule_2023_7070.html",
            2023,
            "daemen",
            "7070",
            "2023-09-27",
        ),
        # Result cell "SUSPENDED-TO BE FINISHED 10/30" beside a Recap link.
        (
            "sidearm_pitt_johnstown_schedule_2023_5521.html",
            2023,
            "pitt-johnstown",
            "5521",
            "2023-09-09",
        ),
    ],
)
def test_a_status_word_anywhere_on_a_completed_row_is_postponed(
    name: str, year: int, owner_slug: str, game_id: str, date: str
) -> None:
    """Shape 2: the completed class (and on some, a Final span) beside a row
    that says the match was not played. Each used to store final, no score."""
    row = _archived_row(name, year=year, owner_slug=owner_slug)
    assert row["id"] == f"sidearm:{owner_slug}:{game_id}"
    assert row["date"] == date
    assert row["status"] == "postponed"
    assert "home_score" not in row and "away_score" not in row


def test_a_completed_class_alone_is_scheduled_and_named(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Shape 3: the completed class with no result element and no Final span,
    the shape a page fetched the evening of the match serves (measured
    nova-southeastern 2026, game 10758, "Game Notes" only, on the 2026-09-02
    fetch; the 2026-09-03 archive of that page has since moved to "Suspended
    (NSU 1-0)", which the postponed family reads)."""
    html = _dom_page(
        '<li class="sidearm-schedule-game sidearm-schedule-home-game upcoming-game '
        'sidearm-schedule-game-completed" data-game-id="10758">'
        '<span class="sidearm-schedule-game-opponent-date"><span>Sep 2 (Wed)</span></span>'
        '<div class="sidearm-schedule-game-opponent-text">'
        '<span class="sidearm-schedule-game-home">vs</span>'
        '<span class="sidearm-schedule-game-opponent-name"><a>Florida Memorial</a></span>'
        "</div></li>"
    )
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        [row] = parse_schedule_page(
            html,
            page_url="https://example.test/schedule/2026",
            year=2026,
            owner_slug="nova-southeastern",
            aliases={},
        )
    assert row["status"] == "scheduled"
    assert "home_score" not in row
    assert (
        "sidearm:nova-southeastern:10758: page reads final with no score "
        "('sidearm-schedule-game-completed'); stored scheduled, no score"
    ) in caplog.text


@pytest.mark.parametrize(
    ("name", "year", "owner_slug", "game_id", "printed"),
    [
        # "W, 1-1 (SO, 4-3)": a shootout win, the owner at home.
        (
            "sidearm_lincoln_schedule_2025_4402.html",
            2025,
            "lincoln",
            "4402",
            "W, 1-1 (SO, 4-3)",
        ),
        # "W, 1-1 (PK-5-4)": a shootout win on a neutral tournament row.
        (
            "sidearm_delta_state_schedule_2020_12951.html",
            2020,
            "delta-state",
            "12951",
            "W, 1-1 (PK-5-4)",
        ),
    ],
)
def test_a_shootout_win_beside_a_level_score_is_stored_as_the_draw(
    name: str,
    year: int,
    owner_slug: str,
    game_id: str,
    printed: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The letter records advancement, the numbers are the goals: with a
    shootout marker in the result text the level pair is the drawn score,
    stored final, and the row is logged at info by fixture id."""
    with caplog.at_level("INFO", logger="src.sidearm_live"):
        row = _archived_row(name, year=year, owner_slug=owner_slug)
    assert row["id"] == f"sidearm:{owner_slug}:{game_id}"
    assert row["status"] == "final"
    assert (row["home_score"], row["away_score"]) == (1, 1)
    assert (
        f"sidearm:{owner_slug}:{game_id}: W beside a level score 1-1 with a "
        f"shootout marker ({printed!r}); stored as the draw"
    ) in caplog.text
    assert "reads final with no score" not in caplog.text


def test_a_forfeit_printed_as_a_level_score_is_final_with_the_awarded_side(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """upper-iowa 2024, game 9017: "W, 2-2" beside a promotion reading "Win by
    forfeit", the owner at home. The forfeit rule (bead tl-wyv, closing
    tl-49e) stores the printed pair as printed, keeps the row final, and
    names the awarded side: W on the owner's page is the owner's slot. The
    word stays out of every other field."""
    with caplog.at_level("INFO", logger="src.sidearm_live"):
        row = _archived_row(
            "sidearm_upper_iowa_schedule_2024_9017.html",
            year=2024,
            owner_slug="upper-iowa",
        )
    assert row["id"] == "sidearm:upper-iowa:9017"
    assert row["status"] == "final"
    assert (row["home"], row["away"]) == ("upper-iowa", "roosevelt")
    assert (row["home_score"], row["away_score"]) == (2, 2)
    assert row["forfeit"] == "home"
    assert row["venue"] == "Harms-Eischeid Stadium"
    assert not any(
        "forfeit" in str(value).lower()
        for key, value in row.items()
        if key != "forfeit"
    )
    assert (
        "sidearm:upper-iowa:9017: W beside a level score 2-2 on a forfeit row "
        "('W, 2-2'); stored as printed"
    ) in caplog.text
    assert "contradicts" not in caplog.text
    assert "reads final with no score" not in caplog.text


def test_a_level_score_without_a_shootout_or_forfeit_word_is_still_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The rib #85 rule stands where no word explains the letter: "W, 2-2"
    with the completed class and nothing saying forfeit or shootout is
    refused, scheduled, named twice, and carries no forfeit."""
    html = _dom_page(
        _dom_game(
            game_id="9018",
            opponent="Roosevelt University",
            date="Sep 5 (Thu)",
            result="W, 2-2",
            completed=True,
        )
    )
    with caplog.at_level("INFO", logger="src.sidearm_live"):
        [row] = parse_schedule_page(
            html,
            page_url="https://example.test/schedule/2024",
            year=2024,
            owner_slug="upper-iowa",
            aliases={},
        )
    assert row["status"] == "scheduled"
    assert "home_score" not in row
    assert "forfeit" not in row
    assert "sidearm:upper-iowa:9018: result letter 'W' contradicts 2-2" in caplog.text
    assert (
        "sidearm:upper-iowa:9018: page reads final with no score ('W, 2-2'); "
        "stored scheduled, no score"
    ) in caplog.text


@pytest.mark.parametrize(
    ("side", "result", "promotion", "row_class", "expected"),
    [
        # "Loss by forfeit" as a promotion with the letter as a row class and
        # empty result spans: the opponent's slot is awarded, 0-1 at home.
        ("home", "", "Loss by forfeit", "L", ("away", 0, 1)),
        # The same, the owner away: the opponent is the home slot.
        ("away", "", "Loss by forfeit", "L", ("home", 1, 0)),
        # A bare letter in the result cell with the word in parentheses.
        ("home", "W (forfeit)", "", "", ("home", 1, 0)),
        # "Forfeited" in the cell, the letter on the row.
        ("away", "Forfeited", "", "W", ("away", 0, 1)),
        # The Upper Iowa shape with a decisive printed score keeps it.
        ("home", "W, 3-0", "Win by forfeit", "W", ("home", 3, 0)),
    ],
)
def test_a_forfeit_with_no_printed_score_takes_the_one_nil_convention(
    side: str,
    result: str,
    promotion: str,
    row_class: str,
    expected: tuple[str, int, int],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A forfeit the page did not score is final, 1-0 to the awarded side, the
    side read from the letter (W the owner's slot, L the opponent's); a
    printed score is kept as printed. The forms are the spellings the rule
    admits beside the one measured ("Win by forfeit", upper-iowa 2024)."""
    html = _dom_page(
        _dom_game(
            game_id="77",
            opponent="Roosevelt University",
            date="Sep 5 (Thu)",
            side=side,
            result=result,
            promotion=promotion,
            completed=True,
        )
    )
    if row_class:
        html = html.replace("upcoming-game", f"upcoming-game {row_class}", 1)
    with caplog.at_level("INFO", logger="src.sidearm_live"):
        [row] = parse_schedule_page(
            html,
            page_url="https://example.test/schedule/2024",
            year=2024,
            owner_slug="upper-iowa",
            aliases={},
        )
    awarded, home_score, away_score = expected
    assert row["status"] == "final"
    assert row["forfeit"] == awarded
    assert (row["home_score"], row["away_score"]) == (home_score, away_score)
    assert row["away" if side == "home" else "home"] == "roosevelt"
    assert "reads final with no score" not in caplog.text
    if "-" not in result:
        assert (
            f"sidearm:upper-iowa:77: forfeit awarded to the {awarded} side with no "
            "printed score; stored 1-0"
        ) in caplog.text


def test_a_forfeit_word_with_no_letter_names_no_side_and_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The word without a letter awards nobody: no forfeit is set, and the
    row falls to the ordinary final-requires-scores refusal."""
    html = _dom_page(
        _dom_game(
            game_id="78",
            opponent="Roosevelt University",
            date="Sep 5 (Thu)",
            promotion="Forfeit",
            completed=True,
        )
    )
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        [row] = parse_schedule_page(
            html,
            page_url="https://example.test/schedule/2024",
            year=2024,
            owner_slug="upper-iowa",
            aliases={},
        )
    assert row["status"] == "scheduled"
    assert "forfeit" not in row
    assert "home_score" not in row
    assert "sidearm:upper-iowa:78: page reads final with no score" in caplog.text


@pytest.mark.parametrize(
    ("result", "promotion", "expected"),
    [
        # The Upper Iowa shape in the payload: the level pair stays printed.
        (
            {"team_score": 2, "opponent_score": 2, "status": "W"},
            "Win by forfeit",
            ("home", 2, 2),
        ),
        # The word in the result's own info string, no score printed.
        (
            {
                "team_score": None,
                "opponent_score": None,
                "status": "L",
                "postscore_info": "(forfeit)",
            },
            None,
            ("away", 0, 1),
        ),
    ],
)
def test_the_payload_reads_the_forfeit_word_from_its_own_strings(
    result: dict[str, object],
    promotion: str | None,
    expected: tuple[str, int, int],
) -> None:
    """The events payload has no forfeit field; the word is read from the
    result's status and info strings and the event's promotion, the letter
    (result.status) awards the side, and a null score pair takes 1-0."""
    event = {
        "id": 9017,
        "date": "2024-09-05T19:00:00",
        "location_indicator": "H",
        "is_conference": False,
        "type": "completed",
        "promotion": promotion,
        "schedule": {"title": "2024 Men's Soccer Schedule"},
        "opponent": {"title": "Roosevelt University"},
        "result": result,
    }
    [fixture] = parse_schedule_page(
        _schedule_html(event, title="2024 Men's Soccer Schedule"),
        page_url="https://example.test/schedule/2024",
        year=2024,
        owner_slug="upper-iowa",
        aliases={},
    )
    awarded, home_score, away_score = expected
    assert fixture["status"] == "final"
    assert fixture["forfeit"] == awarded
    assert (fixture["home_score"], fixture["away_score"]) == (home_score, away_score)
    assert fixture["away"] == "roosevelt"


@pytest.mark.parametrize(
    ("postscore_info", "expected_status"),
    [("(SO, 4-3)", "final"), (None, "scheduled")],
)
def test_the_payload_reads_the_shootout_marker_from_its_score_info(
    postscore_info: str | None, expected_status: str
) -> None:
    """The events payload carries no shootout field, so the marker is read
    from the strings result does carry (status, postscore_info,
    prescore_info); the same rule as the DOM cell, refused without it."""
    event = {
        "id": 4402,
        "date": "2025-11-23T15:00:00",
        "location_indicator": "H",
        "is_conference": False,
        "type": "completed",
        "schedule": {"title": "2025 Men's Soccer Schedule"},
        "opponent": {"title": "Tiffin"},
        "result": {
            "team_score": 1,
            "opponent_score": 1,
            "status": "W",
            "postscore_info": postscore_info,
        },
    }
    [fixture] = parse_schedule_page(
        _schedule_html(event, title="2025 Men's Soccer Schedule"),
        page_url="https://example.test/schedule/2025",
        year=2025,
        owner_slug="lincoln",
        aliases={},
    )
    assert fixture["status"] == expected_status
    if expected_status == "final":
        assert (fixture["home_score"], fixture["away_score"]) == (1, 1)
    else:
        assert "home_score" not in fixture


def test_a_played_row_with_a_score_stays_final(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The control pinned beside the demotions: the completed class with a
    parsed "W, 2-0" is final, scored, and not named."""
    html = _dom_page(
        _dom_game(
            game_id="41",
            opponent="Harding",
            date="Sep 20 (Sat)",
            result="W, 2-0",
            completed=True,
        )
    )
    with caplog.at_level("WARNING", logger="src.sidearm_live"):
        [row] = parse_schedule_page(
            html,
            page_url="https://example.test/schedule/2026",
            year=2026,
            owner_slug="rogers-state",
            aliases={"harding": "harding"},
        )
    assert row["status"] == "final"
    assert (row["home_score"], row["away_score"]) == (2, 0)
    assert "reads final with no score" not in caplog.text


def test_a_parsed_score_beats_a_status_word_outside_the_result_cell() -> None:
    """Measured on the archive reparse (2026-09-03): 31 played make-up dates
    still name the date they were moved from beside their score (caldwell
    2023, game 6141, "rescheduled from 9/23" beside "L, 2-3"). The word
    outside the cell is a note, not a status, when the cell holds a score."""
    html = _dom_page(
        _dom_game(
            game_id="6141",
            opponent="Chestnut Hill College",
            date="Oct 25 (Wed)",
            result="L, 2-3",
            promotion="rescheduled from 9/23",
            completed=True,
        )
    )
    [row] = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2023",
        year=2023,
        owner_slug="caldwell",
        aliases={},
    )
    assert row["status"] == "final"
    assert (row["home_score"], row["away_score"]) == (2, 3)


def test_a_scrimmage_is_an_exhibition() -> None:
    """bloomsburg 2022, game 14253: promotion "Scrimmage" beside "vs Chestnut
    Hill College", no exhibition mark stored, while Chestnut Hill's own row
    is marked exhibition. "Scrimmage" is the third spelling of the marker."""
    row = _archived_row(
        "sidearm_bloomsburg_schedule_2022_14253.html",
        year=2022,
        owner_slug="bloomsburg",
    )
    assert row["id"] == "sidearm:bloomsburg:14253"
    assert row["date"] == "2022-08-23"
    assert row["home"] == "bloomsburg"
    assert row["status"] == "scheduled"
    assert row["match_type"] == "exhibition"


def test_the_scrimmage_marker_keeps_its_word_boundary() -> None:
    from src.sidearm_live import _exhibition_marked

    assert _exhibition_marked("Blue-Grey Scrimmage")
    assert _exhibition_marked("Drexel University (scrimmage)")
    assert not _exhibition_marked("Scrimmagers FC")


# Bead tl-11p7: a schedule row whose opponent is not a team (an alumni game,
# an intrasquad, a scrimmage against a club, a club side with no programme,
# the school listed against itself) was minted as a countable fixture. The
# ruling keeps the row and marks it exhibition; the opponent slug stays
# whatever the text mints. Three tells: the opponent text ("Alumni Game",
# "Intrasquad Game"), the minted slug being the owner's own, and the opponent
# link pointing at the site's own root, which is the only tell a colour game
# or a club side carries.


def _tl_11p7_page(name: str, *, page_url: str, year: int, owner_slug: str):
    from bs4 import BeautifulSoup

    html = (FIXTURES / name).read_text()
    rendered = BeautifulSoup(html, "lxml").select("li.sidearm-schedule-game")
    skips: list[str] = []
    fixtures = parse_schedule_page(
        html,
        page_url=page_url,
        year=year,
        owner_slug=owner_slug,
        aliases={},
        skips=skips,
    )
    # Every rendered row is still a fixture: marked, never skipped.
    assert len(fixtures) == len(rendered)
    assert skips == []
    return {str(row["id"]).rsplit(":", 1)[-1]: row for row in fixtures}


def test_an_alumni_game_is_an_exhibition_and_the_match_beside_it_is_not() -> None:
    """sonomaseawolves.com 2024: row 12375, "Alumni Game", links the
    opponent to the site's own root; row 12376, Santa Rosa JC the same
    afternoon, links to srjcathletics.com. The alumni row keeps its minted
    slug and its place in the list under the exhibition mark."""
    rows = _tl_11p7_page(
        "sidearm_sonoma_state_schedule_2024.html",
        page_url="https://sonomaseawolves.com/sports/mens-soccer/schedule/2024",
        year=2024,
        owner_slug="sonoma-state",
    )
    alumni, match = rows["12375"], rows["12376"]
    assert (alumni["home"], alumni["away"]) == ("sonoma-state", "alumni-game")
    assert (alumni["date"], alumni["time"]) == ("2024-08-24", "11:30")
    assert alumni["match_type"] == "exhibition"
    assert alumni["conference_game"] is False
    assert (match["home"], match["away"]) == ("sonoma-state", "santa-rosa-jc")
    assert "match_type" not in match


def test_an_intrasquad_with_only_the_own_root_link_is_an_exhibition() -> None:
    """hpusharks.com 2026: row 11357, "HPU Grey and Black Game", carries no
    marker word; its only tell is the opponent link to the site's own root.
    Row 11356, "Paradise SC", a club opponent with no website, prints no link
    at all and stays a match; row 11358, the played conference match at UH
    Hilo, links to hiloathletics.com and keeps its score."""
    rows = _tl_11p7_page(
        "sidearm_hawaii_pacific_schedule_2026.html",
        page_url="https://hpusharks.com/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug="hawaii-pacific",
    )
    colours, club, match = rows["11357"], rows["11356"], rows["11358"]
    assert (colours["home"], colours["away"]) == (
        "hawaii-pacific",
        "hpu-grey-and-black-game",
    )
    assert colours["match_type"] == "exhibition"
    assert (club["home"], club["away"]) == ("hawaii-pacific", "paradise-sc")
    assert "match_type" not in club
    assert (match["home"], match["away"]) == ("uh-hilo", "hawaii-pacific")
    assert (match["status"], match["home_score"], match["away_score"]) == (
        "final",
        2,
        1,
    )
    assert "match_type" not in match


def test_a_scrimmage_against_a_club_is_an_exhibition_and_alumni_night_is_not() -> None:
    """eckerdtritons.com 2024: row 8363, "St. Pete Aztecs (Scrimmage)", says
    the word and links to the site's own root; row 8369, "Barry University
    (Alumni Night)", is a played conference match whose opponent cell
    carries a promotion. "Alumni" alone is not the marker."""
    rows = _tl_11p7_page(
        "sidearm_eckerd_schedule_2024.html",
        page_url="https://www.eckerdtritons.com/sports/mens-soccer/schedule/2024",
        year=2024,
        owner_slug="eckerd",
    )
    scrimmage, match = rows["8363"], rows["8369"]
    assert (scrimmage["home"], scrimmage["away"]) == ("eckerd", "saint-pete-aztecs")
    assert scrimmage["match_type"] == "exhibition"
    assert (match["home"], match["away"]) == ("eckerd", "barry")
    assert (match["status"], match["home_score"], match["away_score"]) == (
        "final",
        0,
        3,
    )
    assert "match_type" not in match


def test_a_school_listed_against_itself_is_an_exhibition() -> None:
    """cbubucs.com 2025: row 9364 names "Christian Brothers University" as
    the opponent (an alumni game the venue text names), so both sides mint
    the owner; row 9025, the played match vs Mississippi College, is a
    match."""
    rows = _tl_11p7_page(
        "sidearm_christian_brothers_schedule_2025.html",
        page_url="https://cbubucs.com/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="christian-brothers",
    )
    own, match = rows["9364"], rows["9025"]
    assert (own["home"], own["away"]) == ("christian-brothers", "christian-brothers")
    assert own["date"] == "2026-04-25"
    assert own["match_type"] == "exhibition"
    assert (match["home"], match["away"]) == ("christian-brothers", "mississippi")
    assert (match["home_score"], match["away_score"]) == (4, 4)
    assert "match_type" not in match


def test_a_club_side_with_no_programme_is_an_exhibition() -> None:
    """rooseveltlakers.com 2025: row 5305, "FC United", carries no marker
    word and links the opponent to the site's own root; row 5306, the played
    match at Thomas More, links to thomasmoresaints.com."""
    rows = _tl_11p7_page(
        "sidearm_roosevelt_schedule_2025.html",
        page_url="https://rooseveltlakers.com/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="roosevelt",
    )
    club, match = rows["5305"], rows["5306"]
    assert (club["home"], club["away"]) == ("roosevelt", "fc-united")
    assert club["match_type"] == "exhibition"
    assert (match["home"], match["away"]) == ("thomas-more", "roosevelt")
    assert (match["home_score"], match["away_score"]) == (0, 1)
    assert "match_type" not in match


def test_a_venue_named_alumni_field_is_not_an_exhibition() -> None:
    """umotrojans.com 2026, row 7659: Belmont Abbey at "Belmont, NC Alumni
    Field". The word sits in the venue, where the existing marker reads
    "Friendly"; the alumni-game marker never reads the venue."""
    row = _archived_row(
        "sidearm_mount_olive_schedule_2026_7659.html",
        year=2026,
        owner_slug="mount-olive",
    )
    assert (row["home"], row["away"]) == ("belmont-abbey", "mount-olive")
    assert row["venue"] == "Belmont, NC Alumni Field"
    assert "match_type" not in row


def test_the_payload_marks_alumni_intrasquad_self_and_own_site_rows() -> None:
    """The events component cannot see the rendered link; it carries the
    opponent's title and, on some events, ``opponent.website``. The word
    marks an alumni game or intrasquad by title, the slug marks the owner
    listed against itself, and a website at the page's own root marks a
    club side (gochoctaws.com's "Alumni Game" events point theirs there). A
    real opponent with its own site, and a promotion naming alumni, stay
    matches."""
    base = {
        "date": "2026-08-22T19:00:00",
        "location_indicator": "H",
        "schedule": {"title": "2026 Men's Soccer Schedule"},
        "result": {"status": "N"},
    }
    events = [
        {**base, "id": 1, "opponent": {"title": "Alumni Game"}},
        {**base, "id": 2, "opponent": {"title": "Intrasquad Game"}},
        {**base, "id": 3, "opponent": {"title": "Hostville Griffins"}},
        {
            **base,
            "id": 4,
            "opponent": {"title": "FC United", "website": "http://www.host.test/"},
        },
        {
            **base,
            "id": 5,
            "opponent": {"title": "Alpha", "website": "http://www.alpha.test/"},
        },
        {**base, "id": 6, "opponent": {"title": "Bravo (Alumni Night)"}},
    ]
    component = {"type": "events", "data": events}
    html = (
        "<html><head><title>2026 Men's Soccer Schedule - Host</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )
    fixtures = parse_schedule_page(
        html,
        page_url="https://host.test/sports/mens-soccer/schedule/2026",
        year=2026,
        owner_slug=_HOST,
        aliases=_HOST_ALIASES,
    )
    by_id = {str(row["id"]).rsplit(":", 1)[-1]: row for row in fixtures}
    assert set(by_id) == {"1", "2", "3", "4", "5", "6"}
    assert [by_id[key]["away"] for key in ("1", "2", "3", "4")] == [
        "alumni-game",
        "intrasquad-game",
        "hostville",
        "fc-united",
    ]
    assert all(by_id[key]["match_type"] == "exhibition" for key in ("1", "2", "3", "4"))
    assert (by_id["5"]["away"], by_id["6"]["away"]) == ("alpha", "bravo")
    assert "match_type" not in by_id["5"]
    assert "match_type" not in by_id["6"]


def test_the_non_match_markers_keep_their_word_boundaries() -> None:
    from src.sidearm_live import _non_match_opponent, _own_root_link

    assert _non_match_opponent("Alumni Game")
    assert _non_match_opponent("ALUMNI GAME")
    assert _non_match_opponent("Alumni Match")
    assert _non_match_opponent("Alumni Game (Exhibition)")
    assert _non_match_opponent("Intrasquad Game")
    for text in (
        "Barry University (Alumni Night)",
        "Millersville (Alumni Day)",
        "Embry-Riddle University (Teal Out and Alumni Night)",
        "Alumni Appreciation Game",
        "Belmont, NC Alumni Field",
        "Alumnigame FC",
        "Intrasquads United",
    ):
        assert not _non_match_opponent(text), text
    page = "https://sonomaseawolves.com/sports/mens-soccer/schedule/2024"
    assert _own_root_link("http://sonomaseawolves.com/", page)
    assert _own_root_link("https://www.sonomaseawolves.com", page)
    assert not _own_root_link("http://srjcathletics.com", page)
    assert not _own_root_link(
        "https://sonomaseawolves.com/sports/mens-soccer/opponents/1", page
    )
    assert not _own_root_link("", page)
    assert not _own_root_link("#", page)
    assert not _own_root_link("/sports/mens-soccer/schedule", page)
