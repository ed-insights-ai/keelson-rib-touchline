"""Tests for published schedule and roster collection."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src import coverage
from src.config import SchoolConfig
from src.sidearm_live import (
    LiveCollectionError,
    _oriented_scores,
    STATE_NO_COLLECTOR,
    identity_aliases,
    opponent_slug,
    PublishedPage,
    assert_served_season,
    assert_untrapped_schedule,
    collect_programme,
    conference_members,
    parse_roster_page,
    parse_schedule_page,
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
    assert opponent_slug("University of Montevallo", mens) == "of-montevallo"


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


def test_a_completed_game_without_a_published_score_is_final() -> None:
    """Measured on rsuhillcats.com, 2026-08-21: the modern theme fills scores
    client-side, so a played game's served DOM carries a completed class and a
    Final span but empty result spans.  Played is final, not scheduled — the
    board must not show a finished game as upcoming."""
    html = _dom_page(
        _dom_game(
            game_id="7655",
            opponent="Oklahoma Wesleyan (Exhibition)",
            date="Aug 13 (Thu)",
            completed=True,
        )
    )
    [fixture] = parse_schedule_page(
        html,
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases={"oklahoma wesleyan": "oklahoma-wesleyan"},
    )
    assert fixture["status"] == "final"
    assert "home_score" not in fixture
    assert fixture["match_type"] == "exhibition"
    assert fixture["conference_game"] is False


def test_the_payload_marks_an_exhibition_and_a_scoreless_final() -> None:
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
    [fixture] = parse_schedule_page(
        _schedule_html(event),
        page_url="https://example.test/schedule/2026",
        year=2026,
        owner_slug="rogers-state",
        aliases={"oklahoma wesleyan": "oklahoma-wesleyan"},
    )
    assert fixture["status"] == "final"
    assert "home_score" not in fixture
    assert fixture["match_type"] == "exhibition"


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
    assert fixture["status"] == "final"
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
    assert fixture["status"] == "final"
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
    assert fixture["status"] == "final"
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
