"""What the pipeline knows about PrestoSports athletics sites.

PrestoSports is the second platform the pipeline recognises (Tampa in the
SSC; Westmont, Wilmington and St. Thomas Aquinas are next), and this module
holds everything the pipeline knows about it: the URL shapes, the markup the
probe fingerprints, and the season proof.  The schedule and roster parsers,
then the stats and box-score parsers, land here in the changes that follow
(bead tl-v1q.5); nothing about the platform lives anywhere else.

Season paths are academic years.  The fall ``{year}`` season lives under
``{base}/{year}-{yy}/…`` where ``yy`` is the last two digits of ``year + 1``:
``/sports/msoc/2025-26/schedule`` is the 2025 season, and its title reads
"2025 Tampa Spartans Men's Soccer Schedule".  The layers are ``schedule``,
``roster``, and team statistics at ``teams/{segment}``; the segment is read
from a link the site publishes (every page carries a "Current Season" link
to ``{y}-{yy}/teams/{segment}``), never derived from the school's name.  Box
scores are ``boxscores/{yyyymmdd}_{id}.xml`` pages linked from played
schedule rows.

Fingerprints, verified 2026-09-02 against
https://www.tampaspartans.com/sports/msoc: stylesheets and scripts on the
``theme-assets.prestosports.com/theme-assets/…`` host, the
``presto-sport-static`` font host, a mirror host ``{site}.prestosports.com``,
server-rendered schedule rows (``event-row`` cards with ``event-opponent``,
``event-result``, ``event-links`` and ``event-details-link``), a sortable
roster table whose rows carry a ``jersey-number`` cell, and a statistics page
built from ``stats-container`` tables beside a ``team-stats`` block.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.sidearm_live import (
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LiveCollectionError,
    PublishedPage,
    http_status,
)

PLATFORM = "prestosports"

_SEASON_IN_PATH = re.compile(r"/(\d{4})-\d{2}(?:/|$)")
_LEADING_YEAR = re.compile(r"^\s*(\d{4})(?:-\d{2})?\b")
_TEAM_LINK = re.compile(r"/\d{4}-\d{2}/teams/([A-Za-z0-9_.-]+)/?$")
_BOXSCORE_HREF = re.compile(r'href="\s*([^"]*?/boxscores/\d{8}_[A-Za-z0-9]+\.xml)\s*"')
_MIRROR_HOST = re.compile(r"\b([a-z0-9-]+)\.prestosports\.com\b")
_SHARED_HOSTS = frozenset({"theme-assets", "cdn", "www"})


def season_path(year: int) -> str:
    """The academic-year path segment for the fall ``year`` season: 2025 → "2025-26"."""
    return f"{year}-{(year + 1) % 100:02d}"


def layer_url(base_url: str, year: int, kind: str) -> str:
    """The schedule or roster URL for one season under the sport landing page."""
    if kind not in (LAYER_SCHEDULE, LAYER_ROSTER):
        raise ValueError(
            f"{kind!r} is not a PrestoSports season layer; stats live at stats_url"
        )
    return f"{base_url.rstrip('/')}/{season_path(year)}/{kind}"


def stats_url(base_url: str, year: int, team_segment: str) -> str:
    """The team statistics URL: ``{base}/{y}-{yy}/teams/{segment}``."""
    return f"{base_url.rstrip('/')}/{season_path(year)}/teams/{team_segment}"


def team_segment(html: str) -> str | None:
    """The ``{y}-{yy}/teams/<segment>`` link a schedule or landing page carries.

    The segment names the school in the site's own statistics URL space
    ("tampa"); the season in the link is whichever the site calls current and
    is ignored, since ``stats_url`` supplies the requested one.
    """
    for anchor in BeautifulSoup(html, "lxml").select("a[href]"):
        match = _TEAM_LINK.search(urlparse(str(anchor["href"]).strip()).path)
        if match:
            return match.group(1)
    return None


def has_schedule_markup(html: str) -> bool:
    """Whether the page carries server-rendered PrestoSports schedule rows."""
    return (
        BeautifulSoup(html, "lxml").select_one(".event-row .event-opponent") is not None
    )


def has_roster_markup(html: str) -> bool:
    """Whether the page carries a PrestoSports roster table."""
    return BeautifulSoup(html, "lxml").select_one("table tr .jersey-number") is not None


def has_stats_markup(html: str) -> bool:
    """Whether the page is a PrestoSports team statistics page."""
    soup = BeautifulSoup(html, "lxml")
    return (
        soup.select_one(".stats-container table") is not None
        and soup.select_one(".team-stats") is not None
    )


def boxscore_links(html: str, page_url: str) -> list[str]:
    """Absolute URLs of the ``boxscores/*.xml`` pages a schedule page links, in order.

    Played rows link their box score from the row's ``event-links`` block;
    the same href also rides a ``data-boxscore`` attribute, so links are
    deduplicated by URL.
    """
    links: list[str] = []
    for match in _BOXSCORE_HREF.finditer(html):
        url = urljoin(page_url, match.group(1))
        if url not in links:
            links.append(url)
    return links


def is_presto(html: str) -> list[str]:
    """The positive evidence that a page is served by PrestoSports, or nothing."""
    lower = html.lower()
    evidence: list[str] = []
    if "prestosports.com/theme-assets" in lower:
        evidence.append("prestosports theme asset host")
    if "presto-sport-static" in lower:
        evidence.append("presto-sport-static asset host")
    for host in _MIRROR_HOST.findall(lower):
        if host not in _SHARED_HOSTS:
            evidence.append(f"PrestoSports mirror host {host}.prestosports.com")
            break
    if has_schedule_markup(html):
        evidence.append("server-rendered PrestoSports schedule markup")
    if has_roster_markup(html):
        evidence.append("server-rendered PrestoSports roster table")
    if has_stats_markup(html):
        evidence.append("PrestoSports team statistics tables")
    return list(dict.fromkeys(evidence))


def _season_in_path(url: str) -> int | None:
    match = _SEASON_IN_PATH.search(urlparse(url).path)
    return int(match.group(1)) if match else None


def _season_in_title(html: str) -> int | None:
    title = BeautifulSoup(html, "lxml").title
    if title is None:
        return None
    match = _LEADING_YEAR.match(title.get_text(" "))
    return int(match.group(1)) if match else None


def season_served(page_url: str, html: str, year: int, kind: str = PLATFORM) -> None:
    """Reject a silent redirect or fallback to another season.

    PrestoSports names the season twice: the ``{y}-{yy}`` segment of the
    served URL and the year that leads the title ("2025 Tampa Spartans Men's
    Soccer Schedule", "2026-27 Soccer Statistics").  Whichever are present
    must name ``year``; a page carrying neither cannot prove which season it
    is.
    """
    path_year = _season_in_path(page_url)
    title_year = _season_in_title(html)
    observed = [value for value in (path_year, title_year) if value is not None]
    if not observed:
        raise LiveCollectionError(
            f"[{year}] cannot prove which {kind} season was served at {page_url}"
        )
    wrong = sorted({value for value in observed if value != year})
    if wrong:
        raise LiveCollectionError(
            f"[{year}] requested {kind} season {year} but {page_url} served "
            f"{', '.join(str(value) for value in wrong)}"
        )


def fetch_page(
    session: requests.Session, url: str, year: int, kind: str
) -> PublishedPage:
    """Fetch one season page and prove it is the requested season.

    A non-2xx answer raises ``LiveCollectionError`` carrying the HTTP status,
    so a 403 is reported as a 403 and never read as nothing (bead tl-v1q.6).
    """
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LiveCollectionError(
            f"[{year}] failed to fetch {kind} page {url}: {exc}",
            status=http_status(exc),
        ) from exc
    page = PublishedPage(url, response.url, response.text)
    season_served(page.final_url, page.html, year, kind)
    return page
