"""Tests for what the pipeline knows about PrestoSports sites."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import collect_board
from src.config import SchoolConfig
from src.presto import (
    PLATFORM,
    STATS_TEMPLATE,
    _period_name,
    assert_served_match,
    assert_served_season,
    boxscore_links,
    boxscore_links_by_event,
    collect_match,
    fetch_page,
    has_player_stats_markup,
    has_roster_markup,
    has_schedule_markup,
    has_stats_markup,
    is_presto,
    layer_url,
    locate_stats,
    parse_boxscore,
    parse_roster,
    parse_schedule,
    parse_stats,
    player_stats_url,
    season_path,
    season_served,
    stats_url,
    team_segment,
)
from src.recipes import LIVE_COLLECTORS, PRESTO, live_recipe
from src.sidearm_live import (
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    STATE_UNAVAILABLE,
    LiveCollectionError,
    PublishedPage,
    build_session,
    collect_programme,
    orient_match,
)

FIXTURES = Path("tests/fixtures")
BASE = "https://www.tampaspartans.com/sports/msoc"
SCHEDULE = (FIXTURES / "prestosports_tampa_schedule_2025.html").read_text()
SCHEDULE_2026 = (FIXTURES / "prestosports_tampa_schedule_2026.html").read_text()
ROSTER = (FIXTURES / "prestosports_tampa_roster_2026.html").read_text()
ROSTER_2025 = (FIXTURES / "prestosports_tampa_roster_2025.html").read_text()
TEAMS = (FIXTURES / "prestosports_tampa_teams_2026.html").read_text()
STATS = (FIXTURES / "prestosports_tampa_stats_2025.html").read_text()
BOX_4ZCL = (FIXTURES / "prestosports_tampa_box_20250906_4zcl.html").read_text()
BOX_FJLO = (FIXTURES / "prestosports_tampa_box_20250911_fjlo.html").read_text()
SCHEDULE_URL = f"{BASE}/2025-26/schedule"
SCHEDULE_2026_URL = f"{BASE}/2026-27/schedule"
ROSTER_URL = f"{BASE}/2026-27/roster"
ROSTER_2025_URL = f"{BASE}/2025-26/roster"
TEAMS_URL = f"{BASE}/2025-26/teams"
TEAM_URL = f"{BASE}/2025-26/teams/tampa"
STATS_URL = f"{TEAM_URL}?tmpl={STATS_TEMPLATE}"
BOX_4ZCL_URL = f"{BASE}/2025-26/boxscores/20250906_4zcl.xml"
BOX_FJLO_URL = f"{BASE}/2025-26/boxscores/20250911_fjlo.xml"
# The 2026 skin's two play-by-play flavours: rvya abbreviates the sides
# (UT, AUM) that its keeper lines spell out, jdlp spells them out everywhere.
BOX_RVYA = (FIXTURES / "prestosports_tampa_box_rvyaoly2aiqu23s2.html").read_text()
BOX_JDLP = (FIXTURES / "prestosports_tampa_box_jdlp1av2o4p3e3ql.html").read_text()
BOX_RVYA_URL = f"{BASE}/2026-27/boxscores/20260829_rvya.xml"
BOX_JDLP_URL = f"{BASE}/2026-27/boxscores/20260903_jdlp.xml"


def test_season_path_is_the_academic_year() -> None:
    assert PLATFORM == "prestosports"
    assert season_path(2025) == "2025-26"
    assert season_path(2099) == "2099-00"


def test_layer_urls_hang_off_the_sport_landing_page() -> None:
    assert layer_url(BASE, 2025, "schedule") == f"{BASE}/2025-26/schedule"
    assert layer_url(f"{BASE}/", 2026, "roster") == f"{BASE}/2026-27/roster"
    assert stats_url(f"{BASE}/", 2025, "tampa") == f"{BASE}/2025-26/teams/tampa"
    assert player_stats_url(f"{BASE}/", 2025, "tampa") == STATS_URL
    with pytest.raises(ValueError, match="stats live at stats_url"):
        layer_url(BASE, 2025, "stats")


def test_team_segment_is_read_from_the_published_link() -> None:
    # The link names whichever season the site calls current (2026-27 on
    # the played 2025 schedule); only the segment is read.
    assert team_segment(SCHEDULE) == "tampa"
    assert team_segment(ROSTER) == "tampa"
    assert team_segment("<html><a href='/sports/msoc/recordbook'>x</a></html>") is None


def test_is_presto_lists_positive_evidence_and_nothing_for_sidearm() -> None:
    sidearm = (FIXTURES / "sidearm_boxscore_6126.html").read_text()

    assert is_presto(SCHEDULE) == [
        "prestosports theme asset host",
        "presto-sport-static asset host",
        "PrestoSports mirror host tampaspartans.prestosports.com",
        "server-rendered PrestoSports schedule markup",
    ]
    assert "server-rendered PrestoSports roster table" in is_presto(ROSTER)
    assert "PrestoSports team statistics tables" in is_presto(TEAMS)
    assert is_presto(sidearm) == []
    assert is_presto("<html><p>Plain site</p></html>") == []


def test_markup_detectors_tell_the_layers_apart() -> None:
    assert has_schedule_markup(SCHEDULE)
    assert not has_schedule_markup(ROSTER)
    assert not has_schedule_markup(TEAMS)
    assert has_roster_markup(ROSTER)
    assert not has_roster_markup(SCHEDULE)
    assert has_stats_markup(TEAMS)
    assert not has_stats_markup(SCHEDULE)
    assert not has_stats_markup(ROSTER)


def test_boxscore_links_are_absolute_unique_and_in_page_order() -> None:
    links = boxscore_links(SCHEDULE, f"{BASE}/2025-26/schedule")

    assert len(links) == 15
    assert links[0] == f"{BASE}/2025-26/boxscores/20250904_rgbk.xml"
    assert links[-1] == f"{BASE}/2025-26/boxscores/20251101_6oot.xml"
    assert len(set(links)) == len(links)
    assert all(link.startswith(f"{BASE}/2025-26/boxscores/") for link in links)
    # The statistics page links its recent box scores relatively.
    assert boxscore_links(TEAMS, f"{BASE}/2026-27/teams/tampa") == [
        f"{BASE}/2026-27/boxscores/20260827_k1ap.xml",
        f"{BASE}/2026-27/boxscores/20260829_rvya.xml",
    ]
    assert boxscore_links(ROSTER, f"{BASE}/2026-27/roster") == []


def test_season_served_requires_the_path_and_the_title_to_agree() -> None:
    season_served(f"{BASE}/2025-26/schedule", SCHEDULE, 2025, "schedule")
    season_served(f"{BASE}/2026-27/teams/tampa", TEAMS, 2026, "stats")

    with pytest.raises(LiveCollectionError) as wrong_year:
        season_served(f"{BASE}/2025-26/schedule", SCHEDULE, 2026, "schedule")
    assert str(wrong_year.value) == (
        f"[2026] requested schedule season 2026 but {BASE}/2025-26/schedule served 2025"
    )
    with pytest.raises(LiveCollectionError) as redirected:
        season_served(f"{BASE}/2026-27/roster", ROSTER, 2025, "roster")
    assert "served 2026" in str(redirected.value)
    with pytest.raises(LiveCollectionError) as unproven:
        season_served(
            f"{BASE}/schedule", "<title>Men's Soccer</title>", 2025, "schedule"
        )
    assert str(unproven.value) == (
        f"[2025] cannot prove which schedule season was served at {BASE}/schedule"
    )


# ---------------------------------------------------------------------------
# The schedule parser, over the played 2025 page and the 2026 page to come.
# ---------------------------------------------------------------------------

SSC = {
    "barry",
    "eckerd",
    "embry-riddle",
    "florida-southern",
    "florida-tech",
    "lynn",
    "nova-southeastern",
    "palm-beach-atlantic",
    "rollins",
    "saint-leo",
    "tampa",
}


def _rows(
    html: str = SCHEDULE,
    *,
    year: int = 2025,
    page_url: str = SCHEDULE_URL,
    aliases: dict[str, str] | None = None,
    members: set[str] | None = None,
) -> list[dict[str, object]]:
    return parse_schedule(
        html,
        page_url=page_url,
        year=year,
        owner_slug="tampa",
        aliases=aliases or {},
        members=members,
    )


def test_schedule_parse_reads_every_played_row_on_the_2025_page() -> None:
    rows = _rows()

    # The page's fifteen event cards, one box score each.
    assert len(rows) == 15
    assert len({str(row["id"]) for row in rows}) == 15
    assert all(str(row["id"]).startswith("presto:tampa:") for row in rows)
    assert all(row["status"] == "final" for row in rows)
    assert [row["date"] for row in rows] == sorted(str(row["date"]) for row in rows)
    assert (rows[0]["date"], rows[-1]["date"]) == ("2025-09-04", "2025-11-01")
    assert all("home_score" in row and "away_score" in row for row in rows)
    assert all("time" in row for row in rows)


def test_a_played_home_row_field_by_field() -> None:
    [row] = [row for row in _rows() if row["away"] == "west-florida"]

    assert row == {
        "id": "presto:tampa:rgbkkmfvl7strvbr",
        "date": "2025-09-04",
        "time": "19:00",
        "home": "tampa",
        "away": "west-florida",
        "venue": "Tampa, Fla.",
        "status": "final",
        "conference_game": False,
        "source_url": SCHEDULE_URL,
        "home_score": 3,
        "away_score": 1,
    }


def test_a_played_away_row_is_oriented_from_the_owner() -> None:
    """ "L , 2-1" at Rollins: the site prints the winner's score first, and
    the letter puts Tampa's 1 on the away side, which is what the members'
    page publishes (rollins 2, tampa 1)."""
    [row] = [row for row in _rows() if row["home"] == "rollins"]

    assert row == {
        "id": "presto:tampa:wsg9n77y0zc01qxj",
        "date": "2025-10-01",
        "time": "18:00",
        "home": "rollins",
        "away": "tampa",
        "venue": "Winter Park, Fla.",
        "status": "final",
        "conference_game": True,
        "source_url": SCHEDULE_URL,
        "home_score": 2,
        "away_score": 1,
    }


def test_a_ranked_opponent_is_resolved_without_its_rank() -> None:
    rows = _rows(aliases={"lynn": "lynn", "auburn montgomery": "aum"})
    opponents = {str(row["home"]) for row in rows} | {str(row["away"]) for row in rows}

    # "#13 West Florida", "#21 Auburn-Montgomery", "#13 North Georgia",
    # "#1 Lynn", "#14 Florida Tech", "#21 Palm Beach Atlantic" on the page.
    assert {
        "west-florida",
        "aum",
        "north-georgia",
        "lynn",
        "florida-tech",
        "palm-beach-atlantic",
    } <= opponents
    assert not any("#" in name or name[0].isdigit() for name in opponents)


def test_a_neutral_site_row_carries_the_flag_and_the_site() -> None:
    rows = _rows()
    [neutral] = [row for row in rows if row["away"] == "north-georgia"]
    [hosted] = [row for row in rows if row["away"] == "west-florida"]

    assert neutral["neutral"] is True
    assert (neutral["home"], neutral["away"]) == ("tampa", "north-georgia")
    assert neutral["venue"] == "Morrow, Ga."
    assert (neutral["home_score"], neutral["away_score"]) == (1, 1)
    assert "neutral" not in hosted


def test_the_conference_marker_is_read_as_published() -> None:
    rows = _rows()
    marked = [row for row in rows if row["conference_game"]]

    assert len(marked) == 10
    assert not any("conference_game_source" in row for row in rows)
    assert {str(row["home"]) for row in marked} | {
        str(row["away"]) for row in marked
    } == SSC


def test_without_a_marker_the_flag_is_derived_from_membership() -> None:
    unmarked = SCHEDULE.replace('title="Conference"', 'title="Marked"').replace(
        " conf ", " "
    )
    rows = _rows(unmarked, members=SSC)

    assert all(row["conference_game_source"] == "derived:membership" for row in rows)
    assert sum(1 for row in rows if row["conference_game"]) == 10


def test_the_2026_page_yields_scheduled_rows_and_skips_the_rounds() -> None:
    rows = _rows(SCHEDULE_2026, year=2026, page_url=SCHEDULE_2026_URL)

    # 24 identified cards: two results, thirteen fixtures to come, and nine
    # postseason placeholders naming a round.  The "next event" banner the
    # page repeats above the list carries no id and is not a second row.
    # The page carries no cancelled or postponed row to pin.
    assert len(rows) == 15
    assert [row["status"] for row in rows].count("final") == 2
    assert [row["status"] for row in rows].count("scheduled") == 13
    assert {str(row["away"]) for row in rows} | {str(row["home"]) for row in rows} == {
        "tampa",
        "west-alabama",
        "auburn-montgomery",
        "clayton-state",
        "harding",
        "rollins",
        "saint-leo",
        "eckerd",
        "barry",
        "chowan",
        "embry-riddle",
        "palm-beach-atlantic",
        "florida-tech",
        "lynn",
        "florida-southern",
        "nova-southeastern",
    }
    assert rows[0]["date"] == "2026-08-27"
    [harding] = [row for row in rows if row["away"] == "harding"]
    assert harding == {
        "id": "presto:tampa:7ayo846y0k1n2epk",
        "date": "2026-09-07",
        "time": "11:00",
        "home": "tampa",
        "away": "harding",
        "venue": "Pepin Stadium",
        "status": "scheduled",
        "conference_game": False,
        "source_url": SCHEDULE_2026_URL,
    }


def test_a_january_row_belongs_to_the_calendar_year_after_the_season() -> None:
    """The rendered date carries no year; the SideArm rule supplies it."""
    html = (
        "<html><head><title>2020 Tampa Spartans Men's Soccer Schedule</title></head>"
        '<body><div class="section-event-month january">'
        '<span class="month-title">January</span>'
        '<div class="card event-row home" data-event-id="abc">'
        '<div class="event-opponent"><span class="event-location-badge">vs</span>'
        '<span class="event-opponent-name">Barry</span></div>'
        '<div class="event-dateinfo"><div class="date"><span>Sat. 9</span></div>'
        '<div class="status"><span>1:00 PM</span></div></div>'
        "</div></div></body></html>"
    )
    [row] = _rows(html, year=2020, page_url=f"{BASE}/2020-21/schedule")

    assert (row["date"], row["time"], row["status"]) == (
        "2021-01-09",
        "13:00",
        "scheduled",
    )


# ---------------------------------------------------------------------------
# The roster parser.
# ---------------------------------------------------------------------------


def test_roster_parse_reads_every_player_by_header_text() -> None:
    players = parse_roster(ROSTER, page_url=ROSTER_URL)

    assert len(players) == 37
    assert players[0] == {
        "number": "1",
        "name": "Alex Hare",
        "position": "Goalkeeper",
        "height": "6'4\"",
        "weight": "200 lbs",
        "class_year": "Senior",
        "hometown": "Derby, England",
        "source_url": f"{BASE}/2026-27/bios/hare_alex_2fev",
    }
    # The whole page speaks the SideArm vocabulary after normalisation.
    assert {player["position"] for player in players} == {
        "Goalkeeper",
        "Defender",
        "Midfielder",
        "Forward",
    }
    assert {player["class_year"] for player in players} == {
        "Freshman",
        "Sophomore",
        "Junior",
        "Senior",
        "Graduate Student",
    }
    assert len({player["source_url"] for player in players}) == 37
    allowed = {
        "number",
        "name",
        "position",
        "height",
        "weight",
        "class_year",
        "hometown",
        "source_url",
    }
    assert all(set(player) <= allowed for player in players)


def test_roster_columns_follow_the_header_not_the_position() -> None:
    row = (
        '<tr><th data-label="Name"><span class="label">Name:</span>'
        '<a href="/sports/msoc/2026-27/bios/x_y"> Xavier\n Young </a></th>'
        '<td class="jersey-number">7</td><td>Sr.</td><td>D</td>'
        "<td>Somewhere High</td></tr>"
    )
    html = (
        "<table><thead><tr><th>Name</th><th>No.</th><th>Cl.</th><th>Pos.</th>"
        f"<th>High School</th></tr></thead><tbody>{row}{row}</tbody></table>"
    )

    assert parse_roster(html, page_url=ROSTER_URL) == [
        {
            "number": "7",
            "name": "Xavier Young",
            "position": "Defender",
            "class_year": "Senior",
            "source_url": f"{BASE}/2026-27/bios/x_y",
        }
    ]


def _roster_row(**cells: str) -> str:
    """One roster table with the given header/value pairs, in PrestoSports
    markup (a jersey-number cell, a bio link, a label span per cell)."""
    heads = "".join(f"<th>{label}</th>" for label in cells)
    body = "".join(
        f'<td class="{"jersey-number" if label == "No." else ""}">'
        f'<span class="label">{label}:</span>{value}</td>'
        for label, value in cells.items()
    )
    return (
        f"<table><thead><tr>{heads}</tr></thead><tbody><tr>{body}</tr></tbody></table>"
    ).replace(
        f'<span class="label">Name:</span>{cells["Name"]}',
        f'<span class="label">Name:</span><a href="/sports/msoc/2025-26/bios/p">'
        f"{cells['Name']}</a>",
    )


@pytest.mark.parametrize(
    ("field", "label", "published", "normalised"),
    [
        # Positions: the site's abbreviations become the SideArm words the
        # consumers' vocabularies parse; a two-position row keeps its slash.
        ("position", "Pos.", "GK", "Goalkeeper"),
        ("position", "Pos.", "Def.", "Defender"),
        ("position", "Pos.", "Mid.", "Midfielder"),
        ("position", "Pos.", "For.", "Forward"),
        ("position", "Pos.", "Mid./For.", "Midfielder/Forward"),
        ("position", "Pos.", "Winger", "Winger"),
        # Class years, redshirt forms included; the graduate word is the one
        # the archive carries ("Graduate Student", 728 rows on 2026-09-02).
        ("class_year", "Cl.", "Fr.", "Freshman"),
        ("class_year", "Cl.", "So.", "Sophomore"),
        ("class_year", "Cl.", "Jr.", "Junior"),
        ("class_year", "Cl.", "Sr.", "Senior"),
        ("class_year", "Cl.", "Grad.", "Graduate Student"),
        ("class_year", "Cl.", "R-Fr.", "Redshirt Freshman"),
        ("class_year", "Cl.", "RS-So.", "Redshirt Sophomore"),
        ("class_year", "Cl.", "Fifth Year", "Fifth Year"),
        # Height as feet'inches", weight as "N lbs"; anything else as printed.
        ("height", "Ht.", "6-4", "6'4\""),
        ("height", "Ht.", "5-11", "5'11\""),
        ("height", "Ht.", "1.88 m", "1.88 m"),
        ("weight", "Wt.", "200", "200 lbs"),
        ("weight", "Wt.", "200 lbs", "200 lbs"),
    ],
)
def test_roster_values_are_normalised_to_the_sidearm_vocabulary(
    field: str, label: str, published: str, normalised: str
) -> None:
    html = _roster_row(**{"No.": "9", "Name": "Pat Example", label: published})

    [player] = parse_roster(html, page_url=ROSTER_2025_URL)

    assert player[field] == normalised
    assert player["name"] == "Pat Example"


# ---------------------------------------------------------------------------
# The recipe: collect_programme and the board collector over a Presto site.
# ---------------------------------------------------------------------------


def _tampa() -> SchoolConfig:
    return SchoolConfig(
        name="Tampa",
        abbreviation="UT",
        conference="SSC",
        prefix="",
        base_url=BASE,
        gender="men",
        scraper="prestosports",
        live_scraper="prestosports",
        enabled=True,
    )


class _Site:
    """A PrestoSports site answering each URL with its saved page (the way
    test_parallel_collect's canned session does), remembering the headers
    each request rode."""

    def __init__(
        self,
        pages: dict[str, str],
        *,
        status: int = 200,
        redirects: dict[str, str] | None = None,
    ) -> None:
        self.pages = pages
        self.status = status
        # The site's own HTTP 302s (``/teams`` to ``/teams/tampa``): followed
        # unless the request said not to, in which case the answer is the
        # bare redirect with its Location, as requests hands it back.
        self.redirects = redirects or {}
        self.requests: list[tuple[str, object]] = []

    def get(
        self,
        url: str,
        timeout: int | None = None,
        headers: object = None,
        allow_redirects: bool = True,
    ):
        del timeout
        self.requests.append((url, headers))
        target = self.redirects.get(url)
        if target is not None and not allow_redirects:
            return SimpleNamespace(
                status_code=302,
                url=url,
                text="",
                headers={"Location": target},
                raise_for_status=lambda: None,
            )
        final = target or url
        return SimpleNamespace(
            status_code=self.status,
            url=final,
            text=self.pages.get(final, ""),
            headers={},
            raise_for_status=lambda: None,
        )


def _season_site(**extra: str) -> _Site:
    """Tampa's 2025 season as the site serves it: the three season pages,
    the statistics redirect, and two of the fifteen box scores."""
    return _Site(
        {
            SCHEDULE_URL: SCHEDULE,
            ROSTER_2025_URL: ROSTER_2025,
            STATS_URL: STATS,
            BOX_4ZCL_URL: BOX_4ZCL,
            BOX_FJLO_URL: BOX_FJLO,
            **extra,
        },
        redirects={TEAMS_URL: TEAM_URL},
    )


def test_the_presto_recipe_is_registered_under_its_platform() -> None:
    assert LIVE_COLLECTORS[PLATFORM] is PRESTO
    assert live_recipe(_tampa().live_collector()) is PRESTO
    assert PRESTO.layer_url(BASE, 2025, LAYER_SCHEDULE) == f"{BASE}/2025-26/schedule"
    assert PRESTO.layer_url(BASE, 2026, LAYER_ROSTER) == f"{BASE}/2026-27/roster"
    # The statistics address is the site's to reveal, so the recipe locates
    # it rather than building it from the base.
    with pytest.raises(ValueError, match="stats live at stats_url"):
        PRESTO.layer_url(BASE, 2025, LAYER_STATS)
    assert PRESTO.locate_stats is not None
    assert {
        member: getattr(PRESTO, member).__name__
        for member in (
            "assert_served_season",
            "parse_schedule",
            "assert_schedule_proven",
            "parse_roster",
            "parse_stats",
            "boxscore_links",
            "collect_match",
            "locate_stats",
        )
    } == {
        "assert_served_season": "assert_served_season",
        "parse_schedule": "parse_schedule",
        "assert_schedule_proven": "assert_schedule_proven",
        "parse_roster": "parse_roster",
        "parse_stats": "parse_stats",
        "boxscore_links": "boxscore_links_by_event",
        "collect_match": "collect_match",
        "locate_stats": "locate_stats",
    }
    assert PRESTO.boxscore_links(SCHEDULE, SCHEDULE_URL) == boxscore_links_by_event(
        SCHEDULE, SCHEDULE_URL
    )


def test_a_stats_only_collect_locates_the_print_template_through_the_redirect() -> None:
    site = _season_site()

    result = collect_programme(_tampa(), 2025, {}, session=site, layers=("stats",))

    assert result.state(LAYER_STATS) == STATE_COMPLETE
    assert result.outcomes[LAYER_STATS].count == 30
    assert result.outcomes[LAYER_STATS].source_url == STATS_URL
    assert result.stats_url == STATS_URL
    assert result.stats_html == STATS
    assert [player["name"] for player in result.stat_players][:2] == [
        "Rodrigo Lopes",
        "Viggo Svedin",
    ]
    assert [keeper["name"] for keeper in result.stat_keepers] == ["Alex Hare"]
    # One unfollowed request names the segment; the print template follows.
    assert [url for url, _ in site.requests] == [TEAMS_URL, STATS_URL]


def test_collect_programme_reads_a_presto_season_through_the_recipe() -> None:
    site = _season_site()

    result = collect_programme(
        _tampa(),
        2025,
        {},
        session=site,
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS),
        members=SSC,
    )

    assert result.state(LAYER_SCHEDULE) == STATE_COMPLETE
    assert result.outcomes[LAYER_SCHEDULE].count == 15
    assert result.outcomes[LAYER_SCHEDULE].source_url == SCHEDULE_URL
    assert result.schedule_html == SCHEDULE
    assert result.state(LAYER_ROSTER) == STATE_COMPLETE
    assert result.outcomes[LAYER_ROSTER].count == 42
    assert result.roster_html == ROSTER_2025
    assert result.state(LAYER_STATS) == STATE_COMPLETE
    assert result.outcomes[LAYER_STATS].count == 30
    assert [url for url, _ in site.requests] == [
        SCHEDULE_URL,
        ROSTER_2025_URL,
        TEAMS_URL,
        STATS_URL,
    ]


def test_the_board_collector_collects_all_four_presto_layers_like_sidearm_ones(
    monkeypatch, tmp_path: Path
) -> None:
    school = _tampa()
    site = _season_site()
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(collect_board, "build_session", lambda session=None: site)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    fixtures, rosters, stats, matches, cells, errors, _ = collect_board.collect(
        season=2025,
        gender="men",
        conference="SSC",
        wanted=["tampa"],
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
        workers=1,
    )

    states = {
        layer: cells[f"2025/men/tampa/{layer}"]["state"]
        for layer in (LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES)
    }
    assert states == {
        "schedule": "complete",
        "roster": "complete",
        "stats": "complete",
        "matches": "complete",
    }
    # Every cell of a PrestoSports programme names the PrestoSports collector.
    assert {cell["collector"] for cell in cells.values()} == {"presto-live"}
    assert cells["2025/men/tampa/stats"]["source_url"] == STATS_URL
    assert cells["2025/men/tampa/matches"]["count"] == 2
    assert cells["2025/men/tampa/matches"]["reason"].startswith(
        "[2025] box scores missing for 13 of 15 played fixtures: "
    )
    assert len(fixtures["fixtures"]) == 15
    assert len(rosters["rosters"]["tampa"]["players"]) == 42
    assert len(stats["teams"]["tampa"]["players"]) == 29
    assert len(stats["teams"]["tampa"]["keepers"]) == 1
    assert stats["teams"]["tampa"]["source_url"] == STATS_URL
    detailed = matches["matches"]
    assert {key.rsplit(":", 1)[1][:4] for key in detailed} == {"4zcl", "fjlo"}
    assert all(detail["home_index"] in (0, 1) for detail in detailed.values())
    assert len(matches["missing"]) == 13
    assert all(
        "answered HTTP 200 with an empty body" in reason
        for reason in matches["missing"].values()
    )
    assert len(errors) == 13
    archive = tmp_path / "data" / "raw_html" / "tampa"
    assert (archive / "2025-men-schedule.html").read_text("utf-8") == SCHEDULE
    assert (archive / "2025-men-roster.html").read_text("utf-8") == ROSTER_2025
    assert (archive / "2025-men-stats.html").read_text("utf-8") == STATS
    for layer in ("schedule", "roster", "stats"):
        assert (archive / f"2025-men-{layer}.state.json").is_file()


def test_the_presto_recipe_rides_the_shared_session_identity(monkeypatch) -> None:
    """Measured 2026-09-02 across six PrestoSports hosts: the pipeline's own
    session is answered 200 everywhere and a bare python-requests agent is
    refused 403.  The recipe adds no identity of its own: it fetches through
    the session ``collect_programme`` was handed, or the shared one it
    builds, with no per-request headers of its own."""
    assert build_session().headers["User-Agent"] == (
        "Mozilla/5.0 (Touchline educational/research collector)"
    )
    site = _Site({ROSTER_URL: ROSTER})
    monkeypatch.setattr("src.sidearm_live.build_session", lambda session=None: site)

    result = collect_programme(_tampa(), 2026, {}, layers=(LAYER_ROSTER,))

    assert result.state(LAYER_ROSTER) == STATE_COMPLETE
    assert site.requests == [(ROSTER_URL, None)]


def test_an_empty_202_is_refused_as_a_challenge_not_a_parse_failure() -> None:
    """Measured 2026-09-02 on tampaspartans.com: a WAF challenge answers HTTP
    202 with an empty body.  Both fetch seams say so with the status, and
    the layer's outcome is unavailable with that reason, never a retry."""
    site = _Site({}, status=202)
    refusal = (
        f"[2025] schedule page {SCHEDULE_URL} answered HTTP 202 with an empty "
        f"body (served a challenge, not the page)"
    )

    with pytest.raises(LiveCollectionError) as refused:
        fetch_page(site, SCHEDULE_URL, 2025, LAYER_SCHEDULE)
    assert refused.value.status == 202
    assert str(refused.value) == refusal

    result = collect_programme(_tampa(), 2025, {}, session=site, layers=("schedule",))

    assert result.state(LAYER_SCHEDULE) == STATE_UNAVAILABLE
    assert result.outcomes[LAYER_SCHEDULE].reason == refusal
    assert [url for url, _ in site.requests] == [SCHEDULE_URL, SCHEDULE_URL]


# ---------------------------------------------------------------------------
# The statistics layer: the print template and the redirect that names it.
# ---------------------------------------------------------------------------


def test_only_the_print_template_carries_player_lines() -> None:
    assert has_player_stats_markup(STATS)
    assert not has_player_stats_markup(TEAMS)
    # The season proof for the stats layer refuses the team page: it proves
    # the same season and renders no individual table.
    assert_served_season(PublishedPage(STATS_URL, STATS_URL, STATS), 2025, LAYER_STATS)
    with pytest.raises(LiveCollectionError, match="no individual table"):
        assert_served_season(
            PublishedPage(
                f"{BASE}/2026-27/teams?tmpl={STATS_TEMPLATE}",
                f"{BASE}/2026-27/teams/tampa",
                TEAMS,
            ),
            2026,
            LAYER_STATS,
        )


def test_stats_parse_counts_every_player_with_an_appearance() -> None:
    players, keepers = parse_stats(STATS, page_url=STATS_URL)

    # The template lists the whole roster in both tables and prints "-" for
    # a player without an appearance; 29 field lines and one keeper played.
    assert len(players) == 29
    assert len(keepers) == 1
    assert len({player["name"] for player in players}) == 29
    assert not any(
        player["name"].lower() in {"total", "opponents"} for player in players
    )
    assert not any("." in str(player["name"])[-1:] for player in players)
    assert all("gp" in player for player in players)
    assert "Connor Allen" not in {keeper["name"] for keeper in keepers}


def test_a_field_player_and_a_keeper_field_by_field() -> None:
    players, keepers = parse_stats(STATS, page_url=STATS_URL)

    [lopes] = [player for player in players if player["name"] == "Rodrigo Lopes"]
    assert lopes == {
        "name": "Rodrigo Lopes",
        "number": "18",
        "gp": 15,
        "gs": 15,
        "goals": 8,
        "assists": 3,
        "points": 19,
        "shots": 33,
        "shot_pct": 0.242,
        "sog": 17,
        "sog_pct": 0.515,
        "game_winners": 5,
        "penalty_goals": 1,
        "penalty_attempts": 1,
    }
    [hare] = keepers
    assert hare == {
        "name": "Alex Hare",
        "number": "1",
        "gp": 15,
        "gs": 15,
        "minutes": 1345,
        "goals_against": 15,
        "gaa": 1.0,
        "saves": 42,
        "save_pct": 0.737,
        "wins": 6,
        "losses": 5,
        "ties": 4,
        "shutouts": 4,
    }


def test_locate_stats_reads_the_segment_off_the_redirect() -> None:
    site = _Site({}, redirects={TEAMS_URL: TEAM_URL})

    assert locate_stats(site, BASE, 2025) == STATS_URL
    assert site.requests == [(TEAMS_URL, None)]


def test_locate_stats_reads_a_served_page_for_the_team_link() -> None:
    # A site that answers with a page instead of a redirect still publishes
    # the "Current Season" team link on it.
    site = _Site({TEAMS_URL: SCHEDULE})

    assert locate_stats(site, BASE, 2025) == STATS_URL


def test_locate_stats_says_what_http_said() -> None:
    site = _Site({}, status=202)

    with pytest.raises(LiveCollectionError) as refused:
        locate_stats(site, BASE, 2025)
    assert refused.value.status == 202
    assert "answered HTTP 202 with an empty body" in str(refused.value)

    result = collect_programme(_tampa(), 2025, {}, session=site, layers=("stats",))

    assert result.state(LAYER_STATS) == STATE_UNAVAILABLE
    assert result.outcomes[LAYER_STATS].reason == str(refused.value)


# ---------------------------------------------------------------------------
# Box scores.
# ---------------------------------------------------------------------------


def _fixture_for(box_id: str) -> dict[str, object]:
    """The schedule fixture's own row for one box score."""
    rows = parse_schedule(
        SCHEDULE, page_url=SCHEDULE_URL, year=2025, owner_slug="tampa", aliases={}
    )
    [row] = [row for row in rows if str(row["id"]).rsplit(":", 1)[1].startswith(box_id)]
    return row


def test_boxscore_links_by_event_join_on_the_schedule_card() -> None:
    links = boxscore_links_by_event(SCHEDULE, SCHEDULE_URL)
    rows = parse_schedule(
        SCHEDULE, page_url=SCHEDULE_URL, year=2025, owner_slug="tampa", aliases={}
    )

    assert len(links) == 15
    assert set(links) == {str(row["id"]).rsplit(":", 1)[1] for row in rows}
    assert links["4zclc4rvdo9ctcv4"] == BOX_4ZCL_URL
    assert all(url.startswith(f"{BASE}/2025-26/boxscores/") for url in links.values())
    assert boxscore_links_by_event(ROSTER, ROSTER_URL) == {}


def test_boxscore_parser_reads_the_whole_match() -> None:
    fixture = _fixture_for("4zcl")
    assert (fixture["date"], fixture["home"], fixture["away"]) == (
        "2025-09-06",
        "tampa",
        "auburn-montgomery",
    )

    detail = parse_boxscore(BOX_4ZCL, page_url=BOX_4ZCL_URL)
    orient_match(detail, dict(fixture))

    assert detail["source_url"] == BOX_4ZCL_URL
    aum, tampa = detail["teams"]
    # Visitor first, as the page lists them; the abbreviation is the Open
    # Graph title's ("AUM vs. Tampa").
    assert aum["name"] == "#21 Auburn-Montgomery" and aum["abbr"] == "AUM"
    assert (aum["periods"], aum["score"]) == ([0, 1], 1)
    assert tampa["name"] == "Tampa" and tampa["abbr"] == "Tampa"
    assert (tampa["periods"], tampa["score"]) == ([1, 1], 2)
    assert sum(tampa["periods"]) == tampa["score"]
    assert sum(aum["periods"]) == aum["score"]
    assert tampa["winner"] is True and "winner" not in aum
    # Team statistics by the box's own heading; shots on goal from the
    # lineup totals row.
    assert (aum["shots"], aum["sog"], aum["saves"], aum["corners"], aum["fouls"]) == (
        9,
        3,
        3,
        4,
        7,
    )
    assert (tampa["shots"], tampa["sog"], tampa["saves"], tampa["corners"]) == (
        10,
        5,
        2,
        6,
    )
    assert tampa["fouls"] == 11

    first, second, third = detail["scoring"]
    assert first == {
        "time": "28:58",
        "team": 1,
        "scorer": "Viggo Svedin",
        "season_total": 1,
        "assist": "Loc Kanku",
    }
    assert second["scorer"] == "Viggo Svedin" and second["season_total"] == 2
    # The opponent's "Last, First" is read the way the lineup names are.
    assert third == {
        "time": "84:12",
        "team": 0,
        "scorer": "Benjamin Hoffman",
        "season_total": 2,
        "assist": "Noah Fernandes",
    }

    cards = detail["cards"]
    assert len(cards) == 5
    assert cards[0] == {
        "type": "yellow",
        "player": "Joseph Arnette",
        "time": "15:23",
        "team": 0,
    }
    assert {card["type"] for card in cards} == {"yellow"}

    # A lineup entry: the owner's keeper, position and number as printed,
    # the stat cells by header text; the page marks no starters.
    assert tampa["players"][0] == {
        "name": "Alex Hare",
        "position": "GK",
        "number": "1",
        "shots": 0,
        "sog": 0,
        "goals": 0,
        "assists": 0,
        "minutes": 90,
    }
    assert len(tampa["players"]) == 22 and len(aum["players"]) == 20
    assert not any("started" in line for line in tampa["players"])
    assert not any(line["name"].upper() == "TEAM" for line in aum["players"])
    assert tampa["keepers"] == [
        {
            "name": "Alex Hare",
            "number": "1",
            "minutes": 90,
            "goals_against": 1,
            "saves": 2,
        }
    ]
    assert aum["keepers"][0]["name"] == "Viktor Rosenkrantz"

    assert detail["stadium"] == "Pepin Stadium"
    assert detail["attendance"] == 173
    assert detail["kickoff"] == "11:00 AM"
    assert detail["officials"] == [
        "Referee: Albert Escovar",
        "Asst. Referee: Jason Kopakin",
    ]
    # Decided match orients by score: Tampa 2 = the fixture's home.
    assert detail["home_index"] == 1


def test_play_by_play_reads_every_row_with_team_attribution() -> None:
    detail = parse_boxscore(BOX_4ZCL, page_url=BOX_4ZCL_URL)
    plays = detail["plays"]

    assert len(plays) == 114
    assert plays[0] == {
        "period": "1",
        "text": "Rosenkrantz, Viktor at goalie for AUM.",
        "clock": "0:00",
        "team": 0,
        "type": "goalie",
    }
    # Every line names its side after its verb or leads with it; the sides
    # resolve through the abbreviations the keepers' opening lines teach.
    assert all("team" in play for play in plays)
    assert {play["period"] for play in plays} == {"1", "2"}
    assert {play["type"] for play in plays if "type" in play} == {
        "corner",
        "foul",
        "goal",
        "goalie",
        "offside",
        "shot",
        "sub",
        "yellow",
    }
    goals = [play for play in plays if play["type"] == "goal"]
    # Running scores are aligned to the teams order (AUM, Tampa).
    assert [(goal["clock"], goal["team"], goal["score"]) for goal in goals] == [
        ("28:58", 1, [0, 1]),
        ("66:18", 1, [0, 2]),
        ("84:12", 0, [1, 2]),
    ]
    assert goals[0]["text"].startswith("GOAL by Tampa Viggo Svedin (FIRST GOAL)")
    [substitution] = [play for play in plays if play["type"] == "sub"][:1]
    assert substitution["text"].startswith("Tampa substitution: ")
    assert substitution["team"] == 1


def test_a_draw_with_the_owner_as_visitor_orients_by_name() -> None:
    fixture = _fixture_for("fjlo")
    assert fixture["neutral"] is True
    assert (fixture["home"], fixture["away"]) == ("tampa", "north-georgia")

    detail = parse_boxscore(BOX_FJLO, page_url=BOX_FJLO_URL)
    orient_match(detail, dict(fixture))

    tampa, ung = detail["teams"]
    assert (tampa["name"], tampa["abbr"], tampa["score"]) == ("#7 Tampa", "Tampa", 1)
    assert (ung["name"], ung["abbr"], ung["score"]) == (
        "#13 North Georgia",
        "North Georgia",
        1,
    )
    assert "winner" not in tampa and "winner" not in ung
    assert tampa["periods"] == [1, 0] and ung["periods"] == [0, 1]
    assert len(detail["cards"]) == 7
    assert [
        play["score"] for play in detail["plays"] if play.get("type") == "goal"
    ] == [
        [1, 0],
        [1, 1],
    ]
    assert all("team" in play for play in detail["plays"])
    # A two-name assist is kept as printed rather than flipped.
    assert detail["scoring"][1]["assist"] == "Bargagna, Valen & Lara, Aram"
    assert detail["attendance"] == 617
    # The owner's own name resolves the draw: served first, so home_index 0.
    assert detail["home_index"] == 0


def _names_on_the_record(detail: dict[str, object]) -> list[str]:
    names: list[str] = []
    for team in detail["teams"]:
        names += [line["name"] for line in team.get("players", [])]
        names += [line["name"] for line in team.get("keepers", [])]
    names += [entry["scorer"] for entry in detail["scoring"]]
    names += [entry["assist"] for entry in detail["scoring"] if "assist" in entry]
    names += [card["player"] for card in detail["cards"]]
    return names


def test_abbreviated_play_tokens_are_learned_from_every_line() -> None:
    """tl-agt: the keeper lines say "Tampa" and "AUM", every other line says
    "UT" and "AUM", so the token has to be read off the lines that pair it
    with a lineup name, not off the keeper line alone."""
    detail = parse_boxscore(BOX_RVYA, page_url=BOX_RVYA_URL)
    tampa, aum = detail["teams"]
    assert (tampa["name"], tampa["abbr"]) == ("Tampa", "Tampa")
    assert (aum["name"], aum["abbr"]) == ("Auburn-Montgomery", "AUM")

    plays = detail["plays"]
    assert len(plays) == 113
    assert sum("team" in play for play in plays) == 100
    # What is left names nobody: "Corner kick [01:59]." and the period markers.
    assert {play.get("type") for play in plays if "team" not in play} == {
        "corner",
        "period",
    }
    assert all(
        play["team"] == 0
        for play in plays
        if play["text"].startswith("UT substitution:")
        or " by UT " in play["text"]
        or " on UT " in play["text"]
    )
    assert all(play["team"] == 1 for play in plays if " by AUM " in play["text"])
    # A foul names only its player; the lineup says whose he is.
    [foul] = [play for play in plays if play["text"] == "Foul on Hoffman, Benjamin."][
        :1
    ]
    assert foul["team"] == 1
    # Tampa's 39:13 goal is on the strip, in Tampa's lane, with its score.
    goals = [play for play in plays if play.get("type") == "goal"]
    assert [(goal["clock"], goal["team"], goal["score"]) for goal in goals] == [
        ("39:13", 0, [1, 0]),
        ("65:53", 1, [1, 1]),
        ("81:28", 1, [1, 2]),
    ]
    assert goals[0]["text"].startswith("GOAL by UT Carmona, Manuel")
    # No name on the record carries a side token.
    assert not [
        name
        for name in _names_on_the_record(detail)
        if {"UT", "AUM"} & set(name.split())
    ]


def test_spelled_out_play_tokens_still_resolve() -> None:
    detail = parse_boxscore(BOX_JDLP, page_url=BOX_JDLP_URL)
    plays = detail["plays"]
    assert len(plays) == 130
    assert sum("team" in play for play in plays) == 128
    assert {play["text"] for play in plays if "team" not in play} == {
        "Free kick awarded to Clayton St..",
        "Free kick awarded to Tampa.",
    }
    assert not [
        name
        for name in _names_on_the_record(detail)
        if {"UT", "AUM"} & set(name.split())
    ]


def test_card_sides_resolve_per_row() -> None:
    """tl-agt: the Penalty Summary's offscreen label repeats one side's name
    on every row; the row's badge and the play-by-play say whose card it is."""
    detail = parse_boxscore(BOX_RVYA, page_url=BOX_RVYA_URL)
    assert [
        (card["player"], card["time"], card["team"]) for card in detail["cards"]
    ] == [
        ("Tommaso Polidori", "33:58", 0),
        ("Enrico Zanelli", "57:11", 1),
        ("Kosi Mafela", "64:14", 0),
        ("Manuel Carmona", "76:27", 0),
    ]
    detail = parse_boxscore(BOX_JDLP, page_url=BOX_JDLP_URL)
    assert [
        (card["player"], card["time"], card["team"]) for card in detail["cards"]
    ] == [
        ("Manuel Carmona", "36:27", 1),
        ("William Waters", "90:00", 1),
        ("Adrian Lopez", "90:00", 0),
    ]
    # A trimmed page without badges resolves through the play-by-play card
    # lines: "Yellow card on Tampa Loc Kanku." beside four AUM cards.
    detail = parse_boxscore(BOX_4ZCL, page_url=BOX_4ZCL_URL)
    assert [(card["player"], card["team"]) for card in detail["cards"]] == [
        ("Joseph Arnette", 0),
        ("Sean O'Donnell", 0),
        ("Loc Kanku", 1),
        ("Benjamin Hoffman", 0),
        ("Cole McNulty", 0),
    ]
    detail = parse_boxscore(BOX_FJLO, page_url=BOX_FJLO_URL)
    assert [card["team"] for card in detail["cards"]] == [1, 0, 0, 0, 0, 0, 0]


def test_an_unnamed_scorer_is_kept_as_the_teams_goal() -> None:
    """tl-agt: "  (0) (unassisted)" beside "GOAL by AUM TEAM." is a goal on
    the record, not a dropped row; a 2-1 shows three goals."""
    detail = parse_boxscore(BOX_RVYA, page_url=BOX_RVYA_URL)
    assert detail["scoring"] == [
        {
            "time": "39:13",
            "team": 0,
            "scorer": "Manuel Carmona",
            "season_total": 1,
            "assist": "Dagur Hafthorsson",
        },
        {
            "time": "65:53",
            "team": 1,
            "scorer": "Benjamin Hoffman",
            "season_total": 1,
            "assist": "Fabio Guerreiro",
        },
        {"time": "81:28", "team": 1, "scorer": "TEAM", "season_total": 0},
    ]
    assert len(detail["scoring"]) == sum(team["score"] for team in detail["teams"])


@pytest.mark.parametrize(
    ("caption", "period"),
    [("1st", "1"), ("2nd", "2"), ("OT", "3"), ("2OT", "4"), ("Shootout", "SO")],
)
def test_play_by_play_captions_map_onto_the_sidearm_periods(
    caption: str, period: str
) -> None:
    assert _period_name(caption) == period


def test_a_served_box_score_must_be_the_fixtures_match() -> None:
    fixture = _fixture_for("4zcl")
    page = PublishedPage(BOX_4ZCL_URL, BOX_4ZCL_URL, BOX_4ZCL)

    assert_served_match(page, 2025, dict(fixture))

    with pytest.raises(LiveCollectionError) as other_date:
        assert_served_match(page, 2025, {**fixture, "date": "2025-09-07"})
    assert "2025-09-06" in str(other_date.value)
    assert "2025-09-07" in str(other_date.value)

    with pytest.raises(
        LiveCollectionError, match="does not name both tampa and rollins"
    ):
        assert_served_match(page, 2025, {**fixture, "away": "rollins"})

    with pytest.raises(LiveCollectionError, match="served box score fjlo"):
        assert_served_match(
            PublishedPage(BOX_4ZCL_URL, BOX_FJLO_URL, BOX_FJLO), 2025, dict(fixture)
        )

    with pytest.raises(LiveCollectionError, match="not a box-score page"):
        assert_served_match(
            PublishedPage(BOX_4ZCL_URL, SCHEDULE_URL, SCHEDULE), 2025, dict(fixture)
        )

    with pytest.raises(LiveCollectionError, match="names no match date"):
        assert_served_match(
            PublishedPage(
                BOX_4ZCL_URL,
                BOX_4ZCL_URL,
                "<html><head><meta property='og:title' content='Box Score'></head></html>",
            ),
            2025,
            dict(fixture),
        )


def test_collect_match_proves_and_parses_one_fixture() -> None:
    fixture = _fixture_for("4zcl")
    site = _season_site()

    detail = collect_match(site, BOX_4ZCL_URL, 2025, dict(fixture))

    assert detail["home_index"] == 1
    assert detail["teams"][1]["name"] == "Tampa"
    assert detail["source_url"] == BOX_4ZCL_URL
    assert site.requests == [(BOX_4ZCL_URL, None)]


def test_a_challenge_answer_to_a_box_score_is_refused_with_its_status() -> None:
    """Measured 2026-09-02: the site's WAF answers HTTP 202 with an empty
    body after a burst.  The box-score fetch goes through the same body
    check as the season pages, so the layer names the status (bead
    tl-v1q.12)."""
    site = _Site({}, status=202)

    with pytest.raises(LiveCollectionError) as refused:
        collect_match(site, BOX_4ZCL_URL, 2025, dict(_fixture_for("4zcl")))

    assert refused.value.status == 202
    assert str(refused.value) == (
        f"[2025] box-score page {BOX_4ZCL_URL} answered HTTP 202 with an empty "
        "body (served a challenge, not the page)"
    )


# --- The other schedule and roster skins -------------------------------------
#
# PrestoSports renders a schedule through one of several skins (module
# docstring of src/presto.py).  Each fixture below was fetched live on
# 2026-09-02 through the pipeline's own session and cross-checked against a
# second season of the same site (the 2022-23 pages, and ubknights.com's
# 2026-27 page), which render the same skin: the facts asserted here hold on
# both.  Owners and opponents are the fixtures' own, never configuration.

WILMINGTON_BASE = "https://wildcats.athletics.wilmu.edu/sports/msoc"
STAC_BASE = "https://www.stacathletics.com/sports/msoc"
BRIDGEPORT_BASE = "https://ubknights.com/sports/msoc"
WILMINGTON_SCHEDULE = (
    FIXTURES / "prestosports_wilmington_schedule_2025.html"
).read_text()
WILMINGTON_ROSTER = (FIXTURES / "prestosports_wilmington_roster_2025.html").read_text()
STAC_SCHEDULE = (FIXTURES / "prestosports_stac_schedule_2025.html").read_text()
BRIDGEPORT_SCHEDULE = (
    FIXTURES / "prestosports_bridgeport_schedule_2025.html"
).read_text()
WILMINGTON_SCHEDULE_URL = f"{WILMINGTON_BASE}/2025-26/schedule"
STAC_SCHEDULE_URL = f"{STAC_BASE}/2025-26/schedule"
BRIDGEPORT_SCHEDULE_URL = f"{BRIDGEPORT_BASE}/2025-26/schedule"


def _skin_rows(html: str, page_url: str, owner: str) -> list[dict[str, object]]:
    return parse_schedule(
        html, page_url=page_url, year=2025, owner_slug=owner, aliases={}
    )


def test_every_skin_is_detected_as_a_schedule_and_proves_its_season() -> None:
    for html, url in (
        (WILMINGTON_SCHEDULE, WILMINGTON_SCHEDULE_URL),
        (STAC_SCHEDULE, STAC_SCHEDULE_URL),
        (BRIDGEPORT_SCHEDULE, BRIDGEPORT_SCHEDULE_URL),
    ):
        assert has_schedule_markup(html), url
        assert not has_roster_markup(html), url
        assert not has_stats_markup(html), url
        assert "server-rendered PrestoSports schedule markup" in is_presto(html), url
        season_served(url, html, 2025, LAYER_SCHEDULE)
    assert has_roster_markup(WILMINGTON_ROSTER)
    assert not has_schedule_markup(WILMINGTON_ROSTER)


def test_the_legacy_table_skin_reads_every_row_and_mints_ids() -> None:
    rows = _skin_rows(WILMINGTON_SCHEDULE, WILMINGTON_SCHEDULE_URL, "wilmington")

    # 21 played rows, 21 box-score links, one for one.
    assert len(rows) == 21
    assert all(row["status"] == "final" for row in rows)
    assert all("home_score" in row and "time" in row for row in rows)
    assert (rows[0]["date"], rows[-1]["date"]) == ("2025-09-04", "2025-11-23")
    assert sum(1 for row in rows if row["conference_game"]) == 10
    assert not any("conference_game_source" in row for row in rows)
    links = boxscore_links_by_event(WILMINGTON_SCHEDULE, WILMINGTON_SCHEDULE_URL)
    assert set(links) == {str(row["id"]).rsplit(":", 1)[1] for row in rows}
    assert (
        links["20250904-adelphi"]
        == f"{WILMINGTON_BASE}/2025-26/boxscores/20250904_j6bo.xml"
    )

    # A neutral-site row: "vs." with a "@ Waterbury, Conn." span, dated
    # from the event link label ("September 4 06:30 PM").
    assert rows[0] == {
        "id": "presto:wilmington:20250904-adelphi",
        "date": "2025-09-04",
        "time": "18:30",
        "home": "wilmington",
        "away": "adelphi",
        "neutral": True,
        "venue": "Waterbury, Conn.",
        "status": "final",
        "conference_game": False,
        "source_url": WILMINGTON_SCHEDULE_URL,
        "home_score": 1,
        "away_score": 1,
    }
    # An "at" row puts the owner away; the notes cell ("Homecoming", a
    # round name) is never read as a venue on this skin.
    [away] = [row for row in rows if row["home"] == "west-chester"]
    assert (away["away"], away["home_score"], away["away_score"]) == (
        "wilmington",
        0,
        2,
    )
    assert "venue" not in away
    assert not any("Round" in str(row.get("venue", "")) for row in rows)


def test_the_mobile_list_skin_reads_every_row_without_kickoffs() -> None:
    rows = _skin_rows(STAC_SCHEDULE, STAC_SCHEDULE_URL, "st-thomas-aquinas")

    assert len(rows) == 17
    assert all(row["status"] == "final" and "home_score" in row for row in rows)
    # The list prints "Final" where a kickoff would be and labels no links.
    assert not any("time" in row for row in rows)
    assert sum(1 for row in rows if row["conference_game"]) == 8
    links = boxscore_links_by_event(STAC_SCHEDULE, STAC_SCHEDULE_URL)
    assert set(links) == {str(row["id"]).rsplit(":", 1)[1] for row in rows}

    # "at Southern N.H." with "L, 4-2": the letter orients the owner's 2.
    assert rows[0] == {
        "id": "presto:st-thomas-aquinas:20250904-southern-n-h",
        "date": "2025-09-04",
        "home": "southern-n-h",
        "away": "st-thomas-aquinas",
        "status": "final",
        "conference_game": False,
        "source_url": STAC_SCHEDULE_URL,
        "home_score": 4,
        "away_score": 2,
    }
    # A postseason row keeps its opponent; the round name in its ``.more``
    # block is not a venue.
    [semifinal] = [row for row in rows if row["date"] == "2025-11-08"]
    assert (semifinal["home"], semifinal["away"]) == (
        "roberts-wesleyan",
        "st-thomas-aquinas",
    )
    assert "venue" not in semifinal


def test_the_table_skin_reads_ids_venues_and_seeded_postseason_opponents() -> None:
    rows = _skin_rows(BRIDGEPORT_SCHEDULE, BRIDGEPORT_SCHEDULE_URL, "bridgeport")

    # 22 rows carrying data-event-id, 22 box scores joined on it.
    assert len(rows) == 22
    assert all(row["status"] == "final" and "home_score" in row for row in rows)
    links = boxscore_links_by_event(BRIDGEPORT_SCHEDULE, BRIDGEPORT_SCHEDULE_URL)
    assert set(links) == {str(row["id"]).rsplit(":", 1)[1] for row in rows}
    assert sum(1 for row in rows if row["conference_game"]) == 10

    assert rows[0] == {
        "id": "presto:bridgeport:6hwmyufa4m5s7pt2",
        "date": "2025-09-04",
        "time": "18:00",
        "home": "bridgeport",
        "away": "franklin-pierce",
        "venue": "Knights Field",
        "status": "final",
        "conference_game": False,
        "source_url": BRIDGEPORT_SCHEDULE_URL,
        "home_score": 0,
        "away_score": 1,
    }
    # "Jess Dow Field | New Haven, Conn." keeps the facility; the inline
    # "~ Region" notation beside "Final" is not part of the status.
    [away] = [row for row in rows if row["id"] == "presto:bridgeport:c6myqowz4hqnk2jw"]
    assert (away["venue"], away["status"], away["home"]) == (
        "Jess Dow Field",
        "final",
        "southern-conn-state",
    )
    # "No. 1 Seed Post (CACC Championship)" is a fixture against Post, and
    # "No. 8 Seed Post (NCAA Regional First Round)" sits on a ``neutral`` row.
    [final] = [row for row in rows if row["id"] == "presto:bridgeport:e6f4c3t69mppjdgj"]
    assert (final["home"], final["away"]) == ("post", "bridgeport")
    assert (final["home_score"], final["away_score"]) == (3, 4)
    [regional] = [
        row for row in rows if row["id"] == "presto:bridgeport:5jp3o9e9qeqp8t7n"
    ]
    assert regional["neutral"] is True
    assert (regional["home"], regional["away"]) == ("bridgeport", "post")
    assert regional["venue"] == "Mark A. Ouellette Stadium"


def test_a_match_settled_on_penalties_stores_the_drawn_score() -> None:
    """ubknights.com's 2022-23 page prints "L by PK, 1-1" beside "Final - PK
    Alliance University" (fetched live 2026-09-02): the match is the draw."""
    html = (
        '<div class="section-event-month"><div class="month-title">November</div>'
        '<table><tbody><tr class="event-row home" data-event-id="fb8fwjet3bpslq33">'
        '<td class="date">Tue. 1</td>'
        '<td class="opponent"><span class="event-location-badge">vs</span>'
        '<span class="team-name">Alliance</span></td>'
        '<td class="status">Final - PK Alliance University'
        '<span class="notation" title="Region">~</span></td>'
        '<td class="result"><span class="text-danger">L</span> by PK, 1-1</td>'
        "</tr></tbody></table></div>"
    )
    [row] = _skin_rows(html, BRIDGEPORT_SCHEDULE_URL, "bridgeport")

    assert (row["status"], row["home_score"], row["away_score"]) == ("final", 1, 1)
    assert row["date"] == "2025-11-01"


def test_a_page_with_event_ids_skips_its_next_event_banner() -> None:
    """ubknights.com's 2026-27 page (fetched live 2026-09-02) repeats one row
    above the table as a card without an id; only the identified row counts."""
    banner = (
        '<div class="card event-row home"><span class="event-opponent-name">'
        '<span class="team-name">Mercy</span></span></div>'
    )
    rows = _skin_rows(
        banner + BRIDGEPORT_SCHEDULE, BRIDGEPORT_SCHEDULE_URL, "bridgeport"
    )

    assert len(rows) == 22
    assert len({str(row["id"]) for row in rows}) == 22


def test_the_legacy_roster_skin_reads_every_player_by_header_text() -> None:
    players = parse_roster(
        WILMINGTON_ROSTER, page_url=f"{WILMINGTON_BASE}/2025-26/roster"
    )

    assert len(players) == 30
    assert players[0] == {
        "name": "Will Kiers",
        "number": "0",
        "position": "Goalkeeper",
        "height": "6'2\"",
        "weight": "180 lbs",
        "hometown": "Ware, England",
        "class_year": "Freshman",
        "source_url": f"{WILMINGTON_BASE}/2025-26/bios/kiers_will_r7fl",
    }
    assert {player["position"] for player in players} == {
        "Goalkeeper",
        "Defender",
        "Midfielder",
        "Forward",
    }
    assert all("hometown" in player and "class_year" in player for player in players)


# --- Hosted other-match rows (bead tl-v1q.14) ---------------------------------
# A PrestoSports host publishing the other pair's match of a tournament it
# staged shows the SideArm shape ("A vs. B" in the opponent cell) on the same
# skins.  None of the measured pages carries one, so each skin's fixture gains
# a copy of its first row renamed to two other teams, beside the real rows.


def _with_hosted_row(html: str, *, event_id: str | None) -> str:
    import copy

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    row = soup.select_one(".event-row[data-event-id]") or soup.select_one(".event-row")
    assert row is not None
    clone = copy.copy(row)
    if event_id is not None:
        clone["data-event-id"] = event_id
        clone["id"] = f"event-{event_id}"
    name = clone.select_one(".team-name")
    assert name is not None
    name.clear()
    name.append("Alpha vs. Bravo")
    row.insert_before(clone)
    return str(soup)


@pytest.mark.parametrize(
    ("skin", "html", "url", "owner", "event_id", "count"),
    [
        ("card", SCHEDULE, SCHEDULE_URL, "tampa", "hostedrowid00001", 15),
        (
            "legacy table",
            WILMINGTON_SCHEDULE,
            WILMINGTON_SCHEDULE_URL,
            "wilmington",
            None,
            21,
        ),
        (
            "mobile list",
            STAC_SCHEDULE,
            STAC_SCHEDULE_URL,
            "st-thomas-aquinas",
            None,
            17,
        ),
        (
            "table",
            BRIDGEPORT_SCHEDULE,
            BRIDGEPORT_SCHEDULE_URL,
            "bridgeport",
            "hostedrowid00002",
            22,
        ),
    ],
)
def test_every_presto_skin_skips_a_hosted_other_match_and_names_it(
    skin: str, html: str, url: str, owner: str, event_id: str | None, count: int
) -> None:
    skips: list[str] = []
    rows = parse_schedule(
        _with_hosted_row(html, event_id=event_id),
        page_url=url,
        year=2025,
        owner_slug=owner,
        aliases={"alpha": "alpha", "bravo": "bravo"},
        skips=skips,
    )
    assert len(rows) == count, skin
    assert all(owner in (row["home"], row["away"]) for row in rows), skin
    assert not any("alpha" in (row["home"], row["away"]) for row in rows), skin
    assert skips == ["hosted other-match skipped: 2025-09-04, Alpha v Bravo"], skin


def test_a_presto_row_naming_the_owner_beside_its_opponent_is_the_owners() -> None:
    """The owner matched by its alias on one side of "A vs. B" keeps the
    row, with the other side as the opponent."""
    html = (
        '<div class="section-event-month"><div class="month-title">September</div>'
        '<table><tbody><tr class="event-row home" data-event-id="ownerside0000001">'
        '<td class="date">Thu. 4</td>'
        '<td class="opponent"><span class="event-location-badge">vs</span>'
        '<span class="team-name">Spartans of Tampa vs. Alpha</span></td>'
        '<td class="status">7:00 PM</td><td class="result"></td>'
        "</tr></tbody></table></div>"
    )
    skips: list[str] = []
    [row] = parse_schedule(
        html,
        page_url=SCHEDULE_URL,
        year=2025,
        owner_slug="tampa",
        aliases={"spartans of tampa": "tampa", "alpha": "alpha"},
        skips=skips,
    )
    assert (row["home"], row["away"]) == ("tampa", "alpha")
    assert row["id"] == "presto:tampa:ownerside0000001"
    assert skips == []


# --- Doubled-number and datatables roster skins (beads tl-4sg.32, tl-4sg.30) --
# Two fixtures trimmed from archived 2025-26 pages (title, header row, first
# three body rows).  udcfirebirds.com prints the number column twice on each
# row under one header, which slid every value one column left; the
# chargerathletics.com table carries no ``jersey-number`` class, so it was not
# a roster at all.  gonorthwood.com renders the UDC skin.

UDC_BASE = "https://www.udcfirebirds.com/sports/msoc"
DOMINICAN_BASE = "https://www.chargerathletics.com/sports/msoc"
UDC_ROSTER = (FIXTURES / "prestosports_udc_roster_2025.html").read_text()
DOMINICAN_ROSTER = (FIXTURES / "prestosports_dominican_roster_2025.html").read_text()
UDC_ROSTER_URL = f"{UDC_BASE}/2025-26/roster"
DOMINICAN_ROSTER_URL = f"{DOMINICAN_BASE}/2025-26/roster"


def test_the_doubled_number_skin_folds_both_number_cells_under_one_header() -> None:
    assert has_roster_markup(UDC_ROSTER)
    assert not has_schedule_markup(UDC_ROSTER)
    season_served(UDC_ROSTER_URL, UDC_ROSTER, 2025, LAYER_ROSTER)

    players = parse_roster(UDC_ROSTER, page_url=UDC_ROSTER_URL)

    assert [player["name"] for player in players] == [
        "Benicio Lopez",
        "Sergio Becerra",
        "Niaza Tamini",
    ]
    assert players[0] == {
        "name": "Benicio Lopez",
        "number": "0",
        "position": "Goalkeeper",
        "height": "5'10",
        "weight": "165 lbs",
        "class_year": "Freshman",
        "source_url": f"{UDC_BASE}/2025-26/bios/lopez_benicio_6vnb",
    }
    # The site spells its positions and classes out; the wide-screen number
    # cell, not the narrow-screen badge, is the one read.
    assert [(p["number"], p["position"], p["class_year"]) for p in players] == [
        ("0", "Goalkeeper", "Freshman"),
        ("1", "Goalkeeper", "Senior"),
        ("2", "Defense", "Junior"),
    ]
    assert all("hometown" not in player for player in players)


def test_the_datatables_skin_is_a_roster_by_its_data_field_cells() -> None:
    assert has_roster_markup(DOMINICAN_ROSTER)
    assert not has_schedule_markup(DOMINICAN_ROSTER)
    assert "server-rendered PrestoSports roster table" in is_presto(DOMINICAN_ROSTER)
    season_served(DOMINICAN_ROSTER_URL, DOMINICAN_ROSTER, 2025, LAYER_ROSTER)

    players = parse_roster(DOMINICAN_ROSTER, page_url=DOMINICAN_ROSTER_URL)

    assert [player["name"] for player in players] == [
        "Miguel Hernandez",
        "Johnny Corby",
        "David Arteaga",
    ]
    # The screen and print copies of the bio link are one player.
    assert players[0] == {
        "name": "Miguel Hernandez",
        "number": "00",
        "position": "Goalkeeper",
        "height": "5'10\"",
        "weight": "163 lbs",
        "class_year": "Junior",
        "source_url": f"{DOMINICAN_BASE}/2025-26/bios/hernandez_miguel_31o4",
    }
    assert [(p["number"], p["position"], p["class_year"]) for p in players] == [
        ("00", "Goalkeeper", "Junior"),
        ("0", "Goalkeeper", "Freshman"),
        ("1", "Goalkeeper", "Junior"),
    ]


def test_a_single_number_cell_row_is_read_as_before() -> None:
    # The fold only joins two adjacent ``jersey-number`` cells; the card and
    # table skins' single cell keeps its header index.
    players = parse_roster(ROSTER, page_url=ROSTER_URL)
    assert players[0]["name"] == "Alex Hare"
    assert players[0]["number"] == "1"
