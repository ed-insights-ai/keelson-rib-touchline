"""Tests for what the pipeline knows about PrestoSports sites."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.presto import (
    PLATFORM,
    boxscore_links,
    has_roster_markup,
    has_schedule_markup,
    has_stats_markup,
    is_presto,
    layer_url,
    season_path,
    season_served,
    stats_url,
    team_segment,
)
from src.sidearm_live import LiveCollectionError

FIXTURES = Path("tests/fixtures")
BASE = "https://www.tampaspartans.com/sports/msoc"
SCHEDULE = (FIXTURES / "prestosports_tampa_schedule_2025.html").read_text()
ROSTER = (FIXTURES / "prestosports_tampa_roster_2026.html").read_text()
TEAMS = (FIXTURES / "prestosports_tampa_teams_2026.html").read_text()


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
