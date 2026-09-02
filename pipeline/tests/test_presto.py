"""Tests for what the pipeline knows about PrestoSports sites."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import collect_board
from src.config import SchoolConfig
from src.presto import (
    PLATFORM,
    boxscore_links,
    fetch_page,
    has_roster_markup,
    has_schedule_markup,
    has_stats_markup,
    is_presto,
    layer_url,
    parse_roster,
    parse_schedule,
    season_path,
    season_served,
    stats_url,
    team_segment,
)
from src.recipes import LIVE_COLLECTORS, PRESTO, NoCollector, live_recipe
from src.sidearm_live import (
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    STATE_NO_COLLECTOR,
    STATE_UNAVAILABLE,
    LiveCollectionError,
    build_session,
    collect_programme,
)

FIXTURES = Path("tests/fixtures")
BASE = "https://www.tampaspartans.com/sports/msoc"
SCHEDULE = (FIXTURES / "prestosports_tampa_schedule_2025.html").read_text()
SCHEDULE_2026 = (FIXTURES / "prestosports_tampa_schedule_2026.html").read_text()
ROSTER = (FIXTURES / "prestosports_tampa_roster_2026.html").read_text()
TEAMS = (FIXTURES / "prestosports_tampa_teams_2026.html").read_text()
SCHEDULE_URL = f"{BASE}/2025-26/schedule"
SCHEDULE_2026_URL = f"{BASE}/2026-27/schedule"
ROSTER_URL = f"{BASE}/2026-27/roster"


def test_season_path_is_the_academic_year() -> None:
    assert PLATFORM == "prestosports"
    assert season_path(2025) == "2025-26"
    assert season_path(2099) == "2099-00"


def test_layer_urls_hang_off_the_sport_landing_page() -> None:
    assert layer_url(BASE, 2025, "schedule") == f"{BASE}/2025-26/schedule"
    assert layer_url(f"{BASE}/", 2026, "roster") == f"{BASE}/2026-27/roster"
    assert stats_url(f"{BASE}/", 2025, "tampa") == f"{BASE}/2025-26/teams/tampa"
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
        "position": "GK",
        "height": "6-4",
        "weight": "200",
        "class_year": "Sr.",
        "hometown": "Derby, England",
        "source_url": f"{BASE}/2026-27/bios/hare_alex_2fev",
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
            "position": "D",
            "class_year": "Sr.",
            "source_url": f"{BASE}/2026-27/bios/x_y",
        }
    ]


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

    def __init__(self, pages: dict[str, str], *, status: int = 200) -> None:
        self.pages = pages
        self.status = status
        self.requests: list[tuple[str, object]] = []

    def get(self, url: str, timeout: int | None = None, headers: object = None):
        del timeout
        self.requests.append((url, headers))
        return SimpleNamespace(
            status_code=self.status,
            url=url,
            text=self.pages.get(url, ""),
            headers={},
            raise_for_status=lambda: None,
        )


def test_the_presto_recipe_is_registered_under_its_platform() -> None:
    assert LIVE_COLLECTORS[PLATFORM] is PRESTO
    assert live_recipe(_tampa().live_collector()) is PRESTO
    assert PRESTO.layer_url(BASE, 2025, LAYER_SCHEDULE) == f"{BASE}/2025-26/schedule"
    assert PRESTO.layer_url(BASE, 2026, LAYER_ROSTER) == f"{BASE}/2026-27/roster"
    with pytest.raises(NoCollector) as stats:
        PRESTO.layer_url(BASE, 2025, LAYER_STATS)
    assert stats.value.reason(_tampa()) == (
        "Tampa men: no stats collector for platform 'prestosports' yet (PR 3)"
    )
    with pytest.raises(NoCollector) as matches:
        PRESTO.boxscore_links(SCHEDULE, SCHEDULE_URL)
    assert matches.value.layer == LAYER_MATCHES


def test_unimplemented_layers_are_no_collector_without_a_request() -> None:
    session = MagicMock()

    result = collect_programme(_tampa(), 2025, {}, session=session, layers=("stats",))

    assert result.state(LAYER_STATS) == STATE_NO_COLLECTOR
    assert result.outcomes[LAYER_STATS].reason == (
        "Tampa men: no stats collector for platform 'prestosports' yet (PR 3)"
    )
    session.get.assert_not_called()


def test_collect_programme_reads_a_presto_season_through_the_recipe() -> None:
    site = _Site({SCHEDULE_2026_URL: SCHEDULE_2026, ROSTER_URL: ROSTER})

    result = collect_programme(
        _tampa(),
        2026,
        {},
        session=site,
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS),
        members=SSC,
    )

    assert result.state(LAYER_SCHEDULE) == STATE_COMPLETE
    assert result.outcomes[LAYER_SCHEDULE].count == 15
    assert result.outcomes[LAYER_SCHEDULE].source_url == SCHEDULE_2026_URL
    assert result.schedule_html == SCHEDULE_2026
    assert result.state(LAYER_ROSTER) == STATE_COMPLETE
    assert result.outcomes[LAYER_ROSTER].count == 37
    assert result.roster_html == ROSTER
    assert result.state(LAYER_STATS) == STATE_NO_COLLECTOR
    assert [url for url, _ in site.requests] == [SCHEDULE_2026_URL, ROSTER_URL]


def test_the_board_collector_archives_presto_pages_like_sidearm_ones(
    monkeypatch, tmp_path: Path
) -> None:
    school = _tampa()
    site = _Site({SCHEDULE_2026_URL: SCHEDULE_2026, ROSTER_URL: ROSTER})
    monkeypatch.setattr(collect_board, "load_schools", lambda _path: [school])
    monkeypatch.setattr(collect_board, "build_session", lambda session=None: site)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    fixtures, rosters, _stats, _matches, cells, _errors, _ = collect_board.collect(
        season=2026,
        gender="men",
        conference="SSC",
        wanted=["tampa"],
        layers=(LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES),
        config_path=tmp_path / "schools.toml",
        membership_extrapolated=False,
    )

    states = {
        layer: cells[f"2026/men/tampa/{layer}"]["state"]
        for layer in (LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES)
    }
    assert states == {
        "schedule": "complete",
        "roster": "complete",
        "stats": "no-collector",
        "matches": "no-collector",
    }
    assert cells["2026/men/tampa/stats"]["reason"] == (
        "Tampa men: no stats collector for platform 'prestosports' yet (PR 3)"
    )
    assert cells["2026/men/tampa/matches"]["reason"] == (
        "Tampa men: no matches collector for platform 'prestosports' yet (PR 3)"
    )
    assert len(fixtures["fixtures"]) == 15
    assert fixtures["programmes"] == [
        {"slug": "tampa", "name": "Tampa", "conference": "SSC", "abbr": "UT"}
    ]
    assert len(rosters["rosters"]["tampa"]["players"]) == 37
    archive = tmp_path / "data" / "raw_html" / "tampa"
    assert (archive / "2026-men-schedule.html").read_text("utf-8") == SCHEDULE_2026
    assert (archive / "2026-men-roster.html").read_text("utf-8") == ROSTER
    assert (archive / "2026-men-schedule.state.json").is_file()
    assert (archive / "2026-men-roster.state.json").is_file()
    assert not (archive / "2026-men-stats.html").exists()


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
