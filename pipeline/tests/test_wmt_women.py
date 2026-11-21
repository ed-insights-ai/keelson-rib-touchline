"""Women's soccer on WMT Digital sites: the stanza's gender, proven.

The WMT proofs read men's soccer only (``wmt.games`` sport code ``MSO``, a
sport view named "Men's Soccer"), so every women's layer of the 32 Division
I women's WMT programmes read "season not proven", although each site's
``/website-api`` lists women's schedules 2022-2026.  Women's soccer is
``WSO`` on ``wmt.games``, and five sites name it plain "Soccer", three of
them at a sport path that names no gender (``/sports/soccer``,
``/sports/soc``).  So the gender is the stanza's, and every page, team season
and game must prove it.

Every body is a capture of 2026-11-20 (``d1-soccer/docs/onboarding-
2026-11-20-women``): Nebraska's 2025 season at ``huskers.com/sports/soccer``
(the sport view "Soccer", abbreviation WSOC), its ``wmt.games`` team season
602773 and game 6397124 exactly as served, and South Carolina's women's
WordPress schedule page trimmed to its title and ``route_vars``.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest

from scripts import collect_board
from scripts import probe as probe_cli
from src import wmt
from src.config import SchoolConfig, load_schools
from src.membership import load_membership
from src.probe import LAYER_ABSENT, ProbeReport
from src.recipes import PRESTO, SIDEARM, WMT
from src.sidearm_live import (
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    LiveCollectionError,
    PublishedPage,
    collect_programme,
)
from tests.test_wmt import GAME as SEATTLE_MENS_GAME
from tests.test_wmt import SCHEDULE_PAGE as SEATTLE_MENS_SCHEDULE
from tests.test_wmt import TEAM as SEATTLE_MENS_TEAM
from tests.test_wmt import _fixture, _Site

ORIGIN = "https://huskers.com"
NEBRASKA = f"{ORIGIN}/sports/soccer"
STATS_ORIGIN = "https://wmt.games"
SCHEDULE_URL = f"{NEBRASKA}/schedule/season/2025"
STATS_URL = f"{NEBRASKA}/stats/season/2025"
EVENTS_URL = wmt.events_url(ORIGIN, 1362)
TEAM_URL = wmt.team_season_url(STATS_ORIGIN, 602773)
GAME_URL = wmt.game_url(STATS_ORIGIN, 6397124)

SCHEDULE_PAGE = _fixture("wmt_nebraska_schedule_2025.html")
STATS_PAGE = _fixture("wmt_nebraska_stats_2025.html")
EVENTS = _fixture("wmt_nebraska_events_2025.json")
TEAM = _fixture("wmt_games_team_602773.json")
GAME = _fixture("wmt_games_game_6397124.json")
SC_WOMEN_HEAD = _fixture("wmt_southcarolina_women_schedule_2025_head.html")


@pytest.fixture(autouse=True)
def _fresh_generations(monkeypatch) -> None:
    monkeypatch.setattr(wmt, "_GENERATIONS", {})


def _nebraska_site(**extra: str) -> _Site:
    return _Site(
        {
            SCHEDULE_URL: SCHEDULE_PAGE,
            STATS_URL: STATS_PAGE,
            EVENTS_URL: EVENTS,
            TEAM_URL: TEAM,
            GAME_URL: GAME,
            **extra,
        }
    )


def _nebraska(**fields: object) -> SchoolConfig:
    return SchoolConfig(
        name="Nebraska",
        abbreviation="NU",
        conference="B1G",
        prefix="",
        base_url=NEBRASKA,
        gender=str(fields.pop("gender", "women")),
        scraper="wmt",
        live_scraper="wmt",
        enabled=True,
    )


def _schedule(site: _Site | None = None) -> list[dict[str, object]]:
    fetched = wmt.fetch_layer(
        site or _nebraska_site(), NEBRASKA, 2025, LAYER_SCHEDULE, gender="women"
    )
    return wmt.parse_schedule(
        fetched.page.html,
        page_url=SCHEDULE_URL,
        year=2025,
        owner_slug="nebraska",
        aliases={},
        gender="women",
    )


# --- The sport proof -------------------------------------------------------------


def test_a_womens_page_at_a_path_naming_no_gender_proves_the_stanzas_gender() -> None:
    # Nebraska names its sport "Soccer" at /sports/soccer: only its
    # abbreviation (WSOC) and the stanza say women.
    fixtures = _schedule()
    assert len(fixtures) == 20
    assert {fixture["home"] for fixture in fixtures} | {
        fixture["away"] for fixture in fixtures
    } >= {"nebraska"}


def test_the_same_page_is_never_a_mens_page() -> None:
    with pytest.raises(LiveCollectionError, match="not men's soccer"):
        wmt.fetch_layer(_nebraska_site(), NEBRASKA, 2025, LAYER_SCHEDULE)
    # And a men's page is never a women's one.
    base = "https://goseattleu.com/sports/mens-soccer"
    site = _Site({f"{base}/schedule/season/2025": SEATTLE_MENS_SCHEDULE})
    with pytest.raises(LiveCollectionError, match="Men's Soccer.*not women's soccer"):
        wmt.fetch_layer(site, base, 2025, LAYER_SCHEDULE, gender="women")


@pytest.mark.parametrize(
    ("name", "witnesses", "gender"),
    [
        ("Women's Soccer", {"slug": "womens-soccer", "abbreviation": "WSOC"}, "women"),
        ("Women’s Soccer", {"slug": "wsoc"}, "women"),
        ("Soccer", {"slug": "soccer", "abbreviation": "WSOC"}, "women"),
        # Washington State: the view's own gender field.
        ("Soccer", {"slug": "womens-soccer", "gender": "female"}, "women"),
        ("Men's Soccer", {"slug": "mens-soccer", "abbreviation": "M. Soccer"}, "men"),
        # Miami: no witness names a gender, so a women's stanza's stands.
        ("Soccer", {"slug": "soc", "abbreviation": "soc", "gender": None}, "women"),
    ],
)
def test_a_sport_proves_the_gender_its_witnesses_name(
    name: str, witnesses: dict[str, object], gender: str
) -> None:
    wmt.prove_sport(name, witnesses=witnesses, gender=gender, year=2025, url="u")


@pytest.mark.parametrize(
    ("name", "witnesses", "gender", "message"),
    [
        # Little Rock: "Soccer" at womens-soccer, abbreviation WSOC.
        ("Soccer", {"slug": "womens-soccer", "abbreviation": "WSOC"}, "men", "slug"),
        ("Soccer", {"slug": "soccer", "abbreviation": "WSOC"}, "men", "abbreviation"),
        ("Women's Soccer", {"slug": "soccer"}, "men", "name"),
        ("Men's Soccer", {"slug": "msoc"}, "women", "slug 'msoc'"),
        ("Football", {"slug": "football"}, "women", "not women's soccer"),
        # A men's stanza is proven by "Men's Soccer" alone, as before women's
        # WMT collection: a name that leaves the gender unsaid proves no men's
        # page, even where no other witness genders it.
        (
            "Soccer",
            {"slug": "soc", "abbreviation": "soc", "gender": None},
            "men",
            "not men's soccer",
        ),
        ("Soccer", {"slug": "soccer"}, "men", "not men's soccer"),
        ("Soccer", {}, "men", "not men's soccer"),
    ],
)
def test_a_sport_any_witness_genders_otherwise_is_refused(
    name: str, witnesses: dict[str, object], gender: str, message: str
) -> None:
    with pytest.raises(LiveCollectionError, match=message):
        wmt.prove_sport(name, witnesses=witnesses, gender=gender, year=2025, url="u")


def test_a_gender_wmt_serves_no_soccer_for_is_refused() -> None:
    with pytest.raises(LiveCollectionError, match="not a soccer gender"):
        wmt.sport_code("mixed")
    assert (wmt.sport_code("men"), wmt.sport_code("women")) == ("MSO", "WSO")
    assert wmt.SPORT_CODE == "MSO"


# --- wmt.games: the sport code -------------------------------------------------


def test_womens_statistics_come_from_a_wso_team_season() -> None:
    fetched = wmt.fetch_layer(
        _nebraska_site(), NEBRASKA, 2025, LAYER_STATS, gender="women"
    )
    players, keepers = wmt.parse_stats(fetched.page.html, page_url=STATS_URL)
    assert players and keepers
    # The men's sport code on a women's stanza, and the reverse, are refused.
    with pytest.raises(LiveCollectionError, match=r"not women's soccer \(WSO\)"):
        wmt.prove_team_season(
            wmt.decode_json_body(SEATTLE_MENS_TEAM, "u"),
            team_id=604058,
            year=2025,
            url="u",
            gender="women",
        )
    with pytest.raises(LiveCollectionError, match=r"not men's soccer \(MSO\)"):
        wmt.prove_team_season(
            wmt.decode_json_body(TEAM, "u"), team_id=602773, year=2025, url="u"
        )


def _opener() -> dict[str, object]:
    return next(f for f in _schedule() if str(f["id"]) == "wmt:nebraska:23573")


def test_a_womens_box_score_proves_wso_and_is_read() -> None:
    fixture = _opener()
    assert fixture["date"] == "2025-08-14"
    detail = wmt.collect_match(
        _nebraska_site(), GAME_URL, 2025, dict(fixture), gender="women"
    )
    assert len(detail["teams"]) == 2
    with pytest.raises(LiveCollectionError, match="not men's soccer"):
        wmt.collect_match(_nebraska_site(), GAME_URL, 2025, dict(fixture))
    # A men's game under a women's stanza is refused by its sport code.
    page = PublishedPage(
        wmt.game_url(STATS_ORIGIN, 6412291),
        wmt.game_url(STATS_ORIGIN, 6412291),
        SEATTLE_MENS_GAME,
    )
    with pytest.raises(LiveCollectionError, match="not women's soccer"):
        wmt.parse_match_page(page, 2025, dict(fixture), gender="women")


# --- The collectors read the stanza's gender -----------------------------------


def test_collect_programme_collects_a_womens_wmt_programme_at_a_neutral_path() -> None:
    result = collect_programme(
        _nebraska(),
        2025,
        {},
        session=_nebraska_site(),
        layers=(LAYER_SCHEDULE, LAYER_STATS),
    )
    assert result.state(LAYER_SCHEDULE) == STATE_COMPLETE
    assert result.outcomes[LAYER_SCHEDULE].count == 20
    assert result.state(LAYER_STATS) == STATE_COMPLETE
    # The same site under a men's stanza proves nothing.
    men = collect_programme(
        _nebraska(gender="men"),
        2025,
        {},
        session=_nebraska_site(),
        layers=(LAYER_SCHEDULE,),
    )
    assert men.state(LAYER_SCHEDULE) != STATE_COMPLETE
    assert "not men's soccer" in str(men.outcomes[LAYER_SCHEDULE].reason)


def test_the_board_collector_binds_the_stanzas_gender_into_the_box_score_proof() -> (
    None
):
    recipe = collect_board._recipe_for(_nebraska())
    assert recipe is not None and recipe.platform == WMT.platform
    detail = recipe.collect_match(_nebraska_site(), GAME_URL, 2025, dict(_opener()))
    assert len(detail["teams"]) == 2
    page = PublishedPage(GAME_URL, GAME_URL, GAME)
    assert recipe.parse_match(page, 2025, dict(_opener()))["teams"]
    # A platform whose pages name their sport binds nothing.
    assert SIDEARM.for_gender("women") is SIDEARM
    assert PRESTO.for_gender("women") is PRESTO


def test_every_wmt_member_that_proves_gender_is_bound(monkeypatch) -> None:
    # Each recipe member that calls a wmt function taking ``gender`` is in
    # ``gendered``; one left out proves every stanza as men's.
    # parse_schedule is handed the stanza's gender by its caller and reads
    # nothing from it.
    taking_gender = {
        field.name
        for field in dataclasses.fields(WMT)
        if callable(member := getattr(WMT, field.name))
        and hasattr(wmt, getattr(member, "__name__", ""))
        and "gender" in inspect.signature(getattr(wmt, member.__name__)).parameters
    } - {"parse_schedule"}
    assert "assert_served_season" in taking_gender
    assert set(WMT.gendered) == taking_gender

    seen: dict[str, object] = {}
    monkeypatch.setattr(wmt, "assert_served_season", lambda *a, **k: seen.update(k))
    page = PublishedPage(GAME_URL, GAME_URL, GAME)
    WMT.for_gender("women").assert_served_season(page, 2025, LAYER_SCHEDULE)
    assert seen == {"gender": "women"}


# --- The WordPress generation ------------------------------------------------------


def test_a_wordpress_womens_page_proves_its_category_and_title() -> None:
    url = "https://gamecocksonline.com/sports/wsoc/schedule/season/2025/"
    wmt.prove_wordpress_page(
        SC_WOMEN_HEAD,
        year=2025,
        kind=LAYER_SCHEDULE,
        sport="wsoc",
        url=url,
        gender="women",
    )
    with pytest.raises(LiveCollectionError, match="not men's soccer"):
        wmt.prove_wordpress_page(
            SC_WOMEN_HEAD, year=2025, kind=LAYER_SCHEDULE, sport="wsoc", url=url
        )
    # The title names the category's own sport and the layer.
    with pytest.raises(LiveCollectionError, match="Women's Soccer Roster 2025"):
        wmt.prove_wordpress_page(
            SC_WOMEN_HEAD,
            year=2025,
            kind=LAYER_ROSTER,
            sport="wsoc",
            url=url,
            gender="women",
        )


def test_the_older_wordpress_generations_sport_path_is_named_not_misread() -> None:
    with pytest.raises(LiveCollectionError, match="older WMT WordPress generation"):
        wmt.sport_base("https://arkansasrazorbacks.com/sport/w-soccer")


# --- The probe -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "stated", "gender"),
    [
        ("https://x.com/sports/mens-soccer", None, "men"),
        ("https://x.com/sports/womens-soccer", "women", "women"),
        ("https://x.com/sports/wsoc", None, "women"),
        ("https://x.com/sport/w-soccer", None, "women"),
        ("https://x.com/sports/soccer", "women", "women"),
        ("https://x.com/sports/soc", "women", "women"),
        ("https://x.com/sports/sc", "men", "men"),
    ],
)
def test_the_probe_takes_the_gender_from_the_slug_else_from_gender(
    url: str, stated: str | None, gender: str
) -> None:
    assert probe_cli._gender_from_url(url, stated) == gender


def test_the_probe_refuses_a_slug_naming_no_gender_without_gender_and_a_contradiction() -> (
    None
):
    with pytest.raises(ValueError, match="names no gender.*--gender"):
        probe_cli._gender_from_url("https://miamihurricanes.com/sports/soc")
    with pytest.raises(ValueError, match="names women's soccer, but --gender says men"):
        probe_cli._gender_from_url("https://x.com/sports/womens-soccer", "men")


def test_the_probe_reads_a_womens_wmt_site_at_a_neutral_path(capsys) -> None:
    site = _nebraska_site(**{NEBRASKA: SCHEDULE_PAGE})
    argv = ["--url", NEBRASKA, "--conference", "B1G", "--seasons", "2025"]
    exit_code = probe_cli.main([*argv, "--gender", "women", "--json"], session=site)
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["platform"] == "wmt"
    assert report["layers"]["schedule"] == "present"
    assert report["layers"]["stats"] == "present"
    assert report["seasons"] == [2025]
    assert report["served_nothing"] is False
    assert 'gender       = "women"' in report["stanza"]
    # Without --gender the URL is refused, not guessed.
    assert probe_cli.main(argv, session=_nebraska_site()) == 1
    assert "names no gender" in capsys.readouterr().err


def test_a_200_with_nothing_in_it_is_reported_as_exactly_that() -> None:
    # Ohio's /sports/womens-soccer (its programme is at /sports/wsoc).
    report = ProbeReport(
        url="https://ohiobobcats.com/sports/womens-soccer",
        platform="sidearm",
        evidence=["sidearmsports asset or hostname"],
        layers=dict.fromkeys(("schedule", "roster", "stats", "matches"), LAYER_ABSENT),
        seasons=[],
        stanza="",
    )
    assert report.served_nothing
    assert (
        "Served nothing: https://ohiobobcats.com/sports/womens-soccer answered "
        "HTTP 200 with nothing in it"
    ) in report.render()
    # A refusal, a served season or one present layer is not "nothing".
    assert not ProbeReport(**{**report.__dict__, "not_seen": "HTTP 403"}).served_nothing
    assert not ProbeReport(**{**report.__dict__, "seasons": [2026]}).served_nothing
    present = {**report.layers, "roster": "present"}
    assert not ProbeReport(**{**report.__dict__, "layers": present}).served_nothing


# --- Rank prefixes on a WMT schedule (bead tui-l57) --------------------------


def test_a_dash_in_the_empty_poll_slot_is_not_in_the_slug() -> None:
    """ucfknights.com 2026 women: ``opponent_name`` "-/#21 LSU" (event 12189,
    UCF won 2-1 at LSU), a dash holding the first poll slot, was filed as
    home=21-lsu beside LSU's own record. The WMT parser cleans the prefix
    through the same ``_clean_team_name`` as SideArm; the grammar had no
    dash slot. Three events verbatim from the archived bundle, the third a
    two-poll prefix the grammar already read."""
    aliases, members, scope = collect_board.collect_identity(
        load_schools(), "women", "BIG12", 2026, document=load_membership()
    )
    html = _fixture("wmt_ucf_women_schedule_bundle_2026.json")
    rows = wmt.parse_schedule(
        html,
        page_url=wmt.read_bundle(html).final_url,
        year=2026,
        owner_slug="ucf",
        aliases=aliases,
        members=members,
        scope=scope,
        gender="women",
    )
    sides = {str(row["id"]): (row["home"], row["away"]) for row in rows}
    assert sides == {
        "wmt:ucf:12189": ("lsu", "ucf"),  # "-/#21 LSU"
        "wmt:ucf:11867": ("ucf", "texas-tech"),  # "-/#19 Texas Tech"
        "wmt:ucf:11873": ("west-virginia", "ucf"),  # "#12/14 West Virginia"
    }
