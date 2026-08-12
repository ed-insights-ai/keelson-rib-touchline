"""Read-only discovery helpers for onboarding athletics sites."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from collections.abc import Iterable

import requests
from bs4 import BeautifulSoup

from src.sidearm_live import (
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    LiveCollectionError,
    _component_objects,
    _has_schedule_markup,
    assert_served_season,
    boxscore_links,
    fetch_published_page,
    parse_roster_page,
    parse_schedule_page,
    parse_stats_page,
)

PLATFORM_SIDEARM = "sidearm"
PLATFORM_SIDEARM_LEGACY = "sidearm_legacy"
PLATFORM_STATCREW = "statcrew"
PLATFORM_UNKNOWN = "unknown"

LAYER_PRESENT = "present"
LAYER_ABSENT = "absent"
LAYER_ERROR = "error"


def classify_platform(html: str) -> tuple[str, list[str]]:
    """Classify an athletics page and return the positive evidence used."""
    lower = html.lower()
    sidearm_evidence: list[str] = []
    if _has_schedule_markup(html):
        sidearm_evidence.append("server-rendered SideArm schedule markup")
    if "sidearmsports" in lower:
        sidearm_evidence.append("sidearmsports asset or hostname")
    if "sidearmcomponents" in lower:
        sidearm_evidence.append("SideArm component runtime")
    if re.search(r"<li\b[^>]*class=[\"'][^\"']*\bsidearm-", lower):
        sidearm_evidence.append("server-rendered li.sidearm-* markup")
    if any(component.get("type") == "events" for component in _component_objects(html)):
        sidearm_evidence.append("SideArm events component")
    if sidearm_evidence:
        return PLATFORM_SIDEARM, list(dict.fromkeys(sidearm_evidence))

    if re.search(r"\bsidearm(?:\s+sports)?\b", lower):
        return PLATFORM_SIDEARM_LEGACY, [
            "SideArm branding without server-rendered schedule or box-score markup"
        ]

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    statcrew_evidence: list[str] = []
    if soup.find("table") is not None and re.search(
        r"\bgoals?\s+by\s+period\b", text, re.I
    ):
        statcrew_evidence.append("captioned goals-by-period table")
    title = soup.title.get_text(" ", strip=True) if soup.title is not None else ""
    if re.search(
        r"\bvs?\.?\s+.+\([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\)", title
    ):
        statcrew_evidence.append("StatCrew custompages title shape")
    if statcrew_evidence:
        return PLATFORM_STATCREW, statcrew_evidence

    return PLATFORM_UNKNOWN, []


def probe_layers(
    session: requests.Session, base_url: str, year: int
) -> dict[str, str]:
    """Report whether each live collection layer is present for one season."""
    layers: dict[str, str] = {}
    try:
        schedule = fetch_published_page(session, base_url, year, LAYER_SCHEDULE)
        fixtures = parse_schedule_page(
            schedule.html,
            page_url=schedule.final_url,
            year=year,
            owner_slug="probe",
            aliases={},
        )
        layers[LAYER_SCHEDULE] = (
            LAYER_PRESENT
            if fixtures or _has_schedule_markup(schedule.html)
            else LAYER_ABSENT
        )
        layers[LAYER_MATCHES] = (
            LAYER_PRESENT
            if boxscore_links(schedule.html, schedule.final_url)
            else LAYER_ABSENT
        )
    except LiveCollectionError:
        layers[LAYER_SCHEDULE] = LAYER_ERROR
        layers[LAYER_MATCHES] = LAYER_ERROR

    try:
        roster = fetch_published_page(session, base_url, year, LAYER_ROSTER)
        players = parse_roster_page(roster.html, page_url=roster.final_url)
        layers[LAYER_ROSTER] = LAYER_PRESENT if players else LAYER_ABSENT
    except LiveCollectionError:
        layers[LAYER_ROSTER] = LAYER_ERROR

    try:
        stats = fetch_published_page(session, base_url, year, LAYER_STATS)
        stat_players, stat_keepers = parse_stats_page(
            stats.html, page_url=stats.final_url
        )
        layers[LAYER_STATS] = (
            LAYER_PRESENT if stat_players or stat_keepers else LAYER_ABSENT
        )
    except LiveCollectionError:
        layers[LAYER_STATS] = LAYER_ERROR

    return {
        layer: layers[layer]
        for layer in (LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES)
    }


def served_seasons(
    session: requests.Session, base_url: str, years: Iterable[int]
) -> list[int]:
    """Return candidate seasons whose schedule page proves the requested year."""
    served: list[int] = []
    for year in years:
        try:
            page = fetch_published_page(session, base_url, year, LAYER_SCHEDULE)
            assert_served_season(page, year, LAYER_SCHEDULE)
        except LiveCollectionError:
            continue
        if _has_schedule_markup(page.html):
            served.append(year)
    return served


def draft_stanza(
    *,
    name: str,
    abbreviation: str,
    conference: str,
    base_url: str,
    gender: str,
    platform: str,
    seasons: Iterable[int],
) -> str:
    """Render a disabled, unverified ``schools.toml`` entry for human review."""
    scraper = platform
    live_scraper = platform
    lines = [
        "[[schools]]",
        f"name = {json.dumps(name)}",
        f"abbreviation = {json.dumps(abbreviation)}",
        f"conference = {json.dumps(conference)}",
        f"gender = {json.dumps(gender)}",
        f"base_url = {json.dumps(base_url.rstrip('/'))}",
        f"years = [{', '.join(str(year) for year in seasons)}]",
        f"scraper = {json.dumps(scraper)}",
    ]
    if live_scraper != scraper:
        lines.append(f"live_scraper = {json.dumps(live_scraper)}")
    lines.extend(
        [
            'data_status = "unverified"',
            "enabled = false",
        ]
    )
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ProbeReport:
    """Human-readable results for one athletics sport URL."""

    url: str
    platform: str
    evidence: list[str]
    layers: dict[str, str]
    seasons: list[int]
    stanza: str

    def render(self) -> str:
        evidence = "; ".join(self.evidence) if self.evidence else "none"
        seasons = ", ".join(str(year) for year in self.seasons) or "none"
        lines = [
            f"URL: {self.url}",
            f"Platform: {self.platform}",
            f"Evidence: {evidence}",
            "Layers:",
        ]
        lines.extend(
            f"  {layer}: {self.layers.get(layer, LAYER_ERROR)}"
            for layer in (LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES)
        )
        lines.extend(
            [
                f"Served seasons: {seasons}",
                "",
                "Draft schools.toml stanza:",
                self.stanza.rstrip(),
            ]
        )
        return "\n".join(lines) + "\n"
