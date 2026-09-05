"""What the pipeline knows about PrestoSports athletics sites.

PrestoSports is the second platform the pipeline recognises (Tampa in the
SSC; Westmont, Wilmington and St. Thomas Aquinas are next), and this module
holds everything the pipeline knows about it: the URL shapes, the markup the
probe fingerprints, the season proof, and the parsers for all four layers
(schedule, roster, season statistics, box scores); nothing about the
platform lives anywhere else.  The recipe that hands these to
``collect_programme`` and the board collector is ``PRESTO`` in
src/recipes.py.

The parsers emit the same fixture, player, statistics and match-detail
shapes the SideArm parsers do, and they read rendered text by the SideArm
path's own rules (its date, kickoff, result, orientation, exhibition,
statistic and play-type helpers are imported below), so a date, a kickoff, a
"L, 2-1", a "905:07" of keeper minutes or a "GOAL by" line resolves the same
way on both platforms.

Season paths are academic years.  The fall ``{year}`` season lives under
``{base}/{year}-{yy}/…`` where ``yy`` is the last two digits of ``year + 1``:
``/sports/msoc/2025-26/schedule`` is the 2025 season, and its title reads
"2025 Tampa Spartans Men's Soccer Schedule".  The layers are ``schedule``,
``roster``, and team statistics at ``teams/{segment}``; the segment is read
from a link the site publishes (every page carries a "Current Season" link
to ``{y}-{yy}/teams/{segment}``) or from the site's own redirect of
``{y}-{yy}/teams`` (``locate_stats``), never derived from the school's name.
The team page fills its individual tables by script, so the season lines
are read from its print template (``player_stats_url``).  Box scores are
``boxscores/{yyyymmdd}_{id}.xml`` pages linked from played schedule rows;
the extension is a name, the body is HTML.

Fingerprints, verified 2026-09-02 against
https://www.tampaspartans.com/sports/msoc: stylesheets and scripts on the
``theme-assets.prestosports.com/theme-assets/…`` host, the
``presto-sport-static`` font host, a mirror host ``{site}.prestosports.com``,
server-rendered schedule rows (``event-row`` cards with ``event-opponent``,
``event-result``, ``event-links`` and ``event-details-link``), a sortable
roster table whose rows carry a ``jersey-number`` cell, and a statistics page
built from ``stats-container`` tables beside a ``team-stats`` block.

PrestoSports renders a schedule through one of several skins, and a site
may change skin between seasons.  Every skin marks a row ``event-row``,
names the opponent in a ``team-name`` span and links the box score from the
row, so the detector and the parser read those; the rest is skin by skin
(each measured 2026-09-02 live and kept as a fixture under tests/fixtures):

- card (``prestosports_tampa_schedule_2025.html``): ``div.event-row`` with
  ``data-event-id``, ``event-opponent-name``, ``event-location-badge``
  ("vs"/"at"), ``event-dateinfo`` (a day cell under a ``section-event-month``
  block), ``event-result`` and ``event-links`` labelled by aria-label.
- table (``prestosports_bridgeport_schedule_2025.html``; the same site's
  2022-23 and 2026-27 pages match): ``tr.event-row`` with ``data-event-id``
  under the same month blocks, ``td.date``, ``td.opponent`` carrying the
  badge and the name, ``td.e_venue``, ``td.status`` (with the conference,
  postseason and region notations rendered inline), ``td.result`` and
  ``td.links``.  A "next event" card above the table repeats one row of it
  without an id and is skipped.
- legacy table (``prestosports_wilmington_schedule_2025.html``; the same
  site's 2022-23 page and stacathletics.com's 2022-23 page match): ``tr
  .event-row`` without any event id, ``td.e_date`` ("Thu. 4"), ``td.e_team``
  with a ``va`` span ("vs."/"at"), the name, a ``notation`` marker and a
  ``neutralsite`` span, ``td.e_notes``, ``td.e_result``, ``td.e_status`` and
  ``td.e_links`` labelled by aria-label; no month blocks, so the date comes
  from the labels.
- mobile list (``prestosports_stac_schedule_2025.html``): ``div.event-row``
  without any event id, ``.date`` ("Sep 4"), ``.opponent`` with the ``va``
  span and the name, ``.result``, ``.time`` (the status), and a ``.more``
  block carrying the round name and the links; ``home``/``away``/``conf``/
  ``postseason`` ride the row as classes.

A skin without event ids identifies a fixture by its date and opponent
(``{yyyymmdd}-{opponent slug}``), which the box-score join mints the same
way from the link's filename date and the row's name, so a fixture keeps its
id from the day it is scheduled to the day its box score is stored.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from src.sidearm_live import (
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    LiveCollectionError,
    PublishedPage,
    ResolutionScope,
    _clean_team_name,
    _DOM_MONTHS,
    _dom_date,
    _dom_result,
    _dom_time,
    _exhibition_marked,
    hosted_other_match,
    hosted_skip,
    own_side_opponent,
    _name_slug_affinity,
    _oriented_scores,
    _play_type,
    _stat_float,
    _stat_int,
    _stat_minutes,
    _stat_pair,
    _stats_player_name,
    assert_served_body,
    http_status,
    opponent_slug,
    orient_match,
    programme_slug,
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


# The team page's "Coach's View" link: a print version of the same page.
STATS_TEMPLATE = "teaminfo-network-monospace-template"


def player_stats_url(base_url: str, year: int, team_segment: str) -> str:
    """The one served page carrying every player's season line.

    Measured 2026-09-02 on
    https://www.tampaspartans.com/sports/msoc/2025-26/teams/tampa: the team
    page itself server-renders the roster tab, the team-level figures and
    empty game-log shells, and fills each individual table (Scoring,
    Shooting, Misc., Goalkeepers) by script from
    ``players?teamId=…&view=lineup&pos=…&ajax=true``, one request per tab.
    Its "Coach's View" link is ``?tmpl=teaminfo-network-monospace-template``,
    a print version that renders the cumulative individual and goalkeeping
    tables in one page under an honest title ("2025-26 Men's Soccer
    Statistics - Tampa - University of Tampa Athletics - Print Version").
    """
    return f"{stats_url(base_url, year, team_segment)}?tmpl={STATS_TEMPLATE}"


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


# A schedule row on every skin: an ``event-row`` naming its opponent.
_SCHEDULE_ROW = ".event-row .team-name, .event-row .event-opponent-name"
# A roster row on any skin: a ``jersey-number`` cell (card, table and
# doubled-number skins), the legacy skin's ``number`` cell beside its ``name``
# header cell, or the datatables skin's ``data-field="number"`` cell beside
# the name header cell it marks with ``data-field`` too.
_ROSTER_CELLS = (
    "tr .jersey-number, tr td.number + th.name, "
    "tr td[data-field='number'] + th[data-field]"
)
_ROSTER_ROW = ", ".join(f"table {selector}" for selector in _ROSTER_CELLS.split(", "))


def has_schedule_markup(html: str) -> bool:
    """Whether the page carries server-rendered PrestoSports schedule rows."""
    return BeautifulSoup(html, "lxml").select_one(_SCHEDULE_ROW) is not None


def has_roster_markup(html: str) -> bool:
    """Whether the page carries a PrestoSports roster table."""
    return BeautifulSoup(html, "lxml").select_one(_ROSTER_ROW) is not None


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
    assert_served_body(response, year=year, kind=kind, url=url)
    page = PublishedPage(url, response.url, response.text)
    season_served(page.final_url, page.html, year, kind)
    return page


def assert_served_season(page: PublishedPage, year: int, kind: str) -> None:
    """The recipe's season proof: ``season_served`` over a fetched page.

    A statistics page must also be the print template that carries the
    player lines: the team page proves the same season and renders none,
    so a redirect back to it would otherwise read as an empty season.
    """
    season_served(page.final_url, page.html, year, kind)
    if kind == LAYER_STATS and not has_player_stats_markup(page.html):
        raise LiveCollectionError(
            f"[{year}] {page.final_url} proved its season but is not the "
            f"PrestoSports player statistics page (no individual table)"
        )


def assert_schedule_proven(
    html: str,
    *,
    year: int,
    page_url: str,
    fixtures: list[dict[str, object]],
    owner_slug: str,
) -> None:
    """Refuse a freshly served schedule with no schedule shape at all.

    A page that proved its season but renders no ``event-row`` card is not a
    season with no fixtures: it is a season the site has not released, or a
    page that is not a PrestoSports schedule.  The season proof already
    refuses a redirect to another season, so there is no payload trap to
    check here.
    """
    del owner_slug
    if not fixtures and not has_schedule_markup(html):
        raise LiveCollectionError(
            f"[{year}] {page_url} published no rendered games — either the "
            f"season is not released yet or the page is not PrestoSports"
        )


# --- Schedule ---------------------------------------------------------------

# Postseason structure rows name a round, not an opponent ("SSC
# Quarterfinals", "NCAA 1st Round", "NCAA Championship": nine such rows on
# the 2026-27 schedule) or nothing yet ("TBA").  Real matches from those
# rounds arrive later with actual opponents, as on SideArm.
_ROUND_NAME = re.compile(
    r"\b(?:tournament|championship|quarterfinals?|semifinals?"
    r"|\d{1,2}(?:st|nd|rd|th)\s+round)\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"tbd|tba", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"\([^)]*\)")
# A match settled on penalties after a draw: "L by PK, 1-1" beside a status
# of "Final - PK Alliance University" (ubknights.com, 2022-23).  The match
# itself is the draw the numbers print; the letter names the shoot-out.
_BY_PENALTIES = re.compile(r"\b[WLT]\s+by\s+PKs?\s*,?", re.IGNORECASE)
# The date and kickoff every event link label carries: "Men's Soccer event:
# September 4 07:00 PM: #13 West Florida vs. Tampa: Box Score".
_EVENT_LABEL = re.compile(
    r"\bevent:\s*([A-Za-z]+\s+\d{1,2})\s+(\d{1,2}:\d{2}\s*[AP]\.?M)", re.IGNORECASE
)


# Where each field sits on a schedule row, skin by skin (card, table, legacy
# table, mobile list; see the module docstring).  A selector list is read
# first match first, so a skin that carries two of the names (the mobile
# list's ``.result`` beside nothing else; the table's ``td.result``) reads
# the same field either way.
_ROW_OPPONENT = ".event-opponent-name, .team-name"
_ROW_SIDE = ".event-location-badge, .va"
_ROW_DAY = ".event-dateinfo .date, td.date, td.e_date, .data > .date"
_ROW_STATUS = ".event-dateinfo .status, td.status, td.e_status, .data > .time"
_ROW_RESULT = ".event-result, td.result, td.e_result, .data > .result"
_ROW_NOTES = ".event-notes, td.e_notes, .more"
_ROW_VENUE = ".event-dateinfo .venue, td.e_venue"
_ROW_NEUTRAL_SITE = ".event-neutralsite, .neutralsite"
# Text inside a row cell that is not the cell's value, dropped by
# ``_value_text``: the notation glyph and its screen-reader name beside a
# status ("Final * Conference ~ Region"), the narrow-screen label a cell
# repeats, and the links a mobile ``.more`` block carries after the round.


def _text(node: Tag | None, selector: str) -> str:
    """The collapsed text of the first ``selector`` match under ``node``, or ""."""
    found = node.select_one(selector) if node is not None else None
    if found is None:
        return ""
    return " ".join(found.get_text(" ", strip=True).split())


def _value_text(row: Tag, selector: str) -> str:
    """The first ``selector`` match's own text, without its decoration."""
    found = row.select_one(selector)
    if found is None:
        return ""
    parts: list[str] = []
    for text in found.find_all(string=True):
        parent = text.parent
        while parent is not None and parent is not found and not _decorates(parent):
            parent = parent.parent
        if parent is found:
            parts.append(str(text))
    return " ".join(" ".join(parts).split())


def _decorates(node: Tag) -> bool:
    classes = set(node.get("class") or [])
    return node.name == "a" or bool(classes & {"notation", "visually-hidden", "label"})


def _event_label(row: Tag) -> str:
    """The "{Month} {day} {kickoff}" the row's event links label, or ""."""
    for anchor in row.select("a[aria-label]"):
        match = _EVENT_LABEL.search(str(anchor.get("aria-label") or ""))
        if match:
            return f"{match.group(1)} {match.group(2)}"
    return ""


def _row_date(row: Tag, year: int) -> str | None:
    """The row's date by the skin's own rule.

    Card and table skins print the day under a month block ("September" +
    "Thu. 4"); the legacy table prints only the day, so its date comes from
    the event link labels ("September 4 06:30 PM"); the mobile list prints
    month and day together ("Sep 4").
    """
    section = row.find_parent(class_="section-event-month")
    month = _text(section, ".month-title") if section is not None else ""
    day_text = _value_text(row, _ROW_DAY)
    day = re.search(r"\d{1,2}", day_text)
    if month and day:
        return _dom_date(f"{month} {day.group(0)}", year)
    return _dom_date(_event_label(row), year) or _dom_date(day_text, year)


def _row_venue(row: Tag, notes: str) -> str:
    facility = _value_text(row, _ROW_VENUE)
    if facility:
        # The table skin prints "Jess Dow Field | New Haven, Conn.".
        return facility.split(" | ", 1)[0].strip()
    neutral_site = _value_text(row, _ROW_NEUTRAL_SITE)
    if neutral_site:
        return re.sub(r"^@\s*", "", neutral_site)
    # Only the card skin's notes lead with the town; the legacy table's
    # notes and the mobile list's ``.more`` text are promotions and round
    # names ("Homecoming", "CACC Tournament - First Round"), never a venue.
    if row.select_one(".event-notes") is None:
        return ""
    return notes.split(" / ", 1)[0].strip()


def _schedule_rows(soup: BeautifulSoup) -> dict[str, Tag]:
    """The page's schedule rows keyed by fixture id, first row per id.

    A skin that publishes event ids identifies rows by them, and a row
    without one on such a page is the "next event" banner repeating a row
    of the list.  A skin without any identifies a row by its date and
    opponent (``{yyyymmdd}-{opponent slug}``); the date is resolved later,
    so the key here is the row's position and the id is minted by the caller.
    """
    rows = [row for row in soup.select(".event-row") if row.select_one(_ROW_OPPONENT)]
    identified: dict[str, Tag] = {}
    for row in rows:
        event_id = str(row.get("data-event-id") or "").strip()
        if event_id and event_id not in identified:
            identified[event_id] = row
    if identified:
        return identified
    return {f"#{index}": row for index, row in enumerate(rows)}


def _minted_id(date: str, opponent_name: str) -> str:
    """The fixture id a skin without event ids gets: ``20250904-adelphi``."""
    return f"{date.replace('-', '')}-{programme_slug(opponent_name)}"


def parse_schedule(
    html: str,
    *,
    page_url: str,
    year: int,
    owner_slug: str,
    aliases: dict[str, str],
    members: set[str] | None = None,
    skips: list[str] | None = None,
    scope: ResolutionScope | None = None,
) -> list[dict[str, object]]:
    """Read a PrestoSports schedule page into fixture rows.

    Same row shape, and the same evidence-tiered conference flag, as the
    SideArm parser (``sidearm_live.parse_schedule_page``), under
    ``presto:{owner}:{event id}`` identifiers.  Where each field comes from,
    measured on https://www.tampaspartans.com/sports/msoc/2025-26/schedule
    and the 2026-27 page (2026-09-02):

    - ``id``: the card's ``data-event-id`` (the ``eid`` of its
      ``data-event-url``; a played row's box-score filename,
      ``20250904_rgbk.xml``, carries its first four characters).  The "next
      event" banner the page repeats above the list is a card without one
      and is skipped; the first card per id wins.
    - ``date``: the month is the ``.month-title`` of the enclosing
      ``.section-event-month`` block ("September"); the day is the card's
      ``.event-dateinfo .date`` text ("Thu. 4").  Neither carries a year, so
      the season supplies it by the SideArm rule (January to June belong to
      the calendar year after the season's).  A card outside a month block
      falls back to its event link labels ("Men's Soccer event: September 4
      07:00 PM: ...").
    - ``time``: the ``.event-dateinfo .status`` text when it is a kickoff
      ("11:00 AM EDT"; "TBA" yields no time).  A played row prints "Final"
      there instead, so the kickoff then comes from the event link labels.
    - ``home``/``away``: the ``.event-location-badge`` text, "vs" (owner at
      home) or "at" (owner away).  A ``neutral`` card class, or an
      ``.event-neutralsite`` block ("@ Morrow, Ga."), sets ``neutral`` and
      keeps the published sides, as the SideArm parser does.
    - opponent: the ``.event-opponent-name`` text with the poll rank the site
      prefixes stripped ("#13 West Florida" is West Florida), resolved
      through ``opponent_slug``.  Rows naming a round rather than an
      opponent ("SSC Quarterfinals", "NCAA 1st Round", "TBA") are not
      fixtures.
    - ``status``: a printed result or "Final" in the status text is final; a
      cancellation or postponement is read from either text the way the
      SideArm parser reads its result text (the two pages measured carry
      none); a status text saying live is live; otherwise scheduled.
    - scores: the ``.event-result`` text ("W , 3-1", "T, 1-1"), oriented by
      its letter through ``_oriented_scores``.  This site prints the
      winner's score first, so "L , 2-1" at Rollins is Tampa 1, Rollins 2.
    - ``conference_game``: the row's ``.notation[title="Conference"]``
      marker (which also rides the card as a ``conf`` class) when the page
      marks any row; otherwise derived from ``members`` and stamped
      ``conference_game_source: derived:membership``.
    - ``venue``: the ``.event-dateinfo .venue`` facility when the row names
      one ("Pepin Stadium"), else the neutral-site text without its "@",
      else the town that leads ``.event-notes`` ("Tampa, Fla. / Senior
      Night" keeps "Tampa, Fla."; the promotions after the slash are never
      the venue).
    - ``match_type``: an exhibition or friendly marker in the opponent name
      or the notes, as on SideArm.
    - ``source_url``: the page.

    The other skins (table, legacy table, mobile list) are read through the
    same fields at their own positions (the ``_ROW_*`` selectors above):
    the opponent is the ``team-name`` span, the side the ``va`` span ("vs."
    or "at") where there is no badge, the status the ``e_status`` cell or the
    mobile ``time`` cell, the result the ``e_result``/``result`` cell, the
    venue the table's ``e_venue`` facility, the notes the legacy ``e_notes``
    cell or the mobile ``more`` block's text (the round name), and the date
    by ``_row_date``.  A skin without event ids mints
    ``presto:{owner}:{yyyymmdd}-{opponent slug}``.

    A row whose opponent cell names two other teams ("A vs. B": a match the
    owner hosted but did not play, bead tl-v1q.14) is not the owner's
    fixture on any skin: it is never minted, and with a ``skips`` list it
    is named there for the collect summary, as on SideArm.
    """
    soup = BeautifulSoup(html, "lxml")
    rows = _schedule_rows(soup)

    def conference_marked(row: Tag) -> bool:
        return row.select_one(
            '.notation[title="Conference"]'
        ) is not None or "conf" in set(row.get("class") or [])

    theme_marks_conference = any(conference_marked(row) for row in rows.values())
    member_slugs = set(aliases.values()) if members is None else members

    fixtures: list[dict[str, object]] = []
    seen: set[str] = set()
    for event_id, row in rows.items():
        opponent_raw = _text(row, _ROW_OPPONENT)
        opponent_name = _clean_team_name(opponent_raw)
        date = _row_date(row, year)
        if not opponent_name or not date:
            continue
        # The table skin names a postseason opponent with its round in
        # parentheses ("No. 1 Seed Post (CACC Championship)"): a fixture, not
        # a round placeholder, so the round words are judged outside them.
        outside_parentheses = _PARENTHETICAL.sub(" ", opponent_name).strip()
        if _PLACEHOLDER.fullmatch(opponent_name) or _ROUND_NAME.search(
            outside_parentheses
        ):
            continue
        hosted = hosted_other_match(
            opponent_name, owner_slug=owner_slug, aliases=aliases, scope=scope
        )
        if hosted is not None:
            if skips is not None:
                skips.append(hosted_skip(date, hosted))
            continue
        opponent_name = own_side_opponent(
            opponent_name, owner_slug=owner_slug, aliases=aliases, scope=scope
        )
        if event_id.startswith("#"):
            event_id = _minted_id(date, opponent_name)
        if event_id in seen:
            continue
        seen.add(event_id)
        classes = set(row.get("class") or [])
        owner_is_home = not _text(row, _ROW_SIDE).lower().startswith("at")
        neutral = "neutral" in classes or row.select_one(_ROW_NEUTRAL_SITE) is not None
        other_slug = opponent_slug(
            opponent_name, aliases, scope=scope, owner=owner_slug
        )
        home, away = (
            (owner_slug, other_slug) if owner_is_home else (other_slug, owner_slug)
        )
        status_text = _value_text(row, _ROW_STATUS)
        result_text = _value_text(row, _ROW_RESULT)
        result = _dom_result(_BY_PENALTIES.sub("T,", result_text))
        notes = _value_text(row, _ROW_NOTES)
        exhibition = _exhibition_marked(opponent_raw, notes)
        printed = f"{status_text} {result_text}"
        if re.search(r"cancel", printed, re.IGNORECASE):
            status = "cancelled"
        elif re.search(r"postpon", printed, re.IGNORECASE):
            status = "postponed"
        elif re.search(r"\blive\b|in progress", status_text, re.IGNORECASE):
            status = "live"
        elif result or re.search(r"\bfinal\b", status_text, re.IGNORECASE):
            status = "final"
        else:
            status = "scheduled"

        fixture: dict[str, object] = {
            "id": f"presto:{owner_slug}:{event_id}",
            "date": date,
            "home": home,
            "away": away,
            "status": status,
            "source_url": page_url,
        }
        if neutral:
            fixture["neutral"] = True
        if exhibition:
            fixture["match_type"] = "exhibition"
        if theme_marks_conference:
            fixture["conference_game"] = conference_marked(row)
        else:
            fixture["conference_game"] = not exhibition and other_slug in member_slugs
            fixture["conference_game_source"] = "derived:membership"
        time = _dom_time(status_text) or _dom_time(_event_label(row))
        if time:
            fixture["time"] = time
        venue = _row_venue(row, notes)
        if venue:
            fixture["venue"] = venue
        oriented = (
            _oriented_scores(
                result[0], result[1], result[2], fixture_id=str(fixture["id"])
            )
            if result
            else None
        )
        if oriented:
            owner_score, other_score = oriented
            if owner_is_home:
                fixture["home_score"], fixture["away_score"] = owner_score, other_score
            else:
                fixture["home_score"], fixture["away_score"] = other_score, owner_score
        fixtures.append(fixture)
    return sorted(fixtures, key=lambda value: (str(value["date"]), str(value["id"])))


# --- Roster -----------------------------------------------------------------

# The header labels the roster table publishes, keyed without their trailing
# period, and the player-row field each names.  "High School" and "Previous
# College" have no field in the row shape and are left unread.
_ROSTER_COLUMNS = {
    "no": "number",
    "number": "number",
    "name": "name",
    "pos": "position",
    "position": "position",
    "ht": "height",
    "height": "height",
    "wt": "weight",
    "wgt": "weight",
    "weight": "weight",
    "cl": "class_year",
    "class": "class_year",
    "yr": "class_year",
    "year": "class_year",
    "hometown": "hometown",
}
_ROSTER_FIELDS = ("number", "position", "height", "weight", "hometown", "class_year")

# The abbreviations the roster table prints (measured on the 2026-27 Tampa
# roster: GK, Def., Mid., For.; Fr., So., Jr., Sr., Grad.) and the SideArm
# words they stand for, which are the words the consumers' vocabularies
# parse.  Keys are lower-cased with their trailing period dropped.
_ROSTER_POSITIONS = {
    "gk": "Goalkeeper",
    "g": "Goalkeeper",
    "def": "Defender",
    "d": "Defender",
    "mid": "Midfielder",
    "m": "Midfielder",
    "for": "Forward",
    "fwd": "Forward",
    "f": "Forward",
}
_ROSTER_CLASSES = {
    "fr": "Freshman",
    "so": "Sophomore",
    "jr": "Junior",
    "sr": "Senior",
    "gr": "Graduate Student",
    "grad": "Graduate Student",
    "5th": "Fifth Year",
}
_REDSHIRT = re.compile(r"^(?:redshirt|rs|r)[\s.-]*(.+)$", re.IGNORECASE)
_HEIGHT = re.compile(r"^(\d)\s*-\s*(\d{1,2}(?:\.\d+)?)$")
_WEIGHT = re.compile(r"^\d{2,3}$")


def _roster_position(text: str) -> str:
    """ "Def." is Defender; a two-position "Mid./For." is Midfielder/Forward."""
    parts = re.split(r"\s*/\s*", text.strip())
    words = [_ROSTER_POSITIONS.get(_column_key(part)) for part in parts]
    return "/".join(words) if parts and all(words) else text  # type: ignore[arg-type]


def _roster_class_year(text: str) -> str:
    """ "Sr." is Senior, "Grad." Graduate Student, "R-Fr." Redshirt Freshman."""
    key = _column_key(text)
    redshirt = _REDSHIRT.match(key)
    if redshirt:
        word = _ROSTER_CLASSES.get(_column_key(redshirt.group(1)))
        return f"Redshirt {word}" if word else text
    return _ROSTER_CLASSES.get(key, text)


def _roster_height(text: str) -> str:
    """ "6-4" is 6'4", the form every SideArm roster prints."""
    match = _HEIGHT.match(text.strip())
    return f"{match.group(1)}'{match.group(2)}\"" if match else text


def _roster_weight(text: str) -> str:
    """ "200" is 200 lbs."""
    return f"{text.strip()} lbs" if _WEIGHT.match(text.strip()) else text


_ROSTER_NORMALISERS: dict[str, Callable[[str], str]] = {
    "position": _roster_position,
    "class_year": _roster_class_year,
    "height": _roster_height,
    "weight": _roster_weight,
}


def _column_key(label: str) -> str:
    return re.sub(r"[.\s]+$", "", label.strip().lower())


def _roster_row_cells(row: Tag) -> list[Tag]:
    """The row's cells, one per header column.

    The doubled-number skin prints the jersey number twice in a row, a
    narrow-screen badge cell and a wide-screen cell side by side, both
    marked ``jersey-number``; the header names the column once, so the two
    fold into the wide-screen one (the badge is dropped) and the header
    index lines up with the rest of the row.
    """
    cells: list[Tag] = []
    for cell in row.find_all(["td", "th"], recursive=False):
        if (
            cells
            and "jersey-number" in cell.get("class", [])
            and "jersey-number" in cells[-1].get("class", [])
        ):
            cells[-1] = cell
            continue
        cells.append(cell)
    return cells


def parse_roster(html: str, *, page_url: str) -> list[dict[str, str]]:
    """Read a PrestoSports roster table into player rows.

    Same row shape as the SideArm parser (``sidearm_live.parse_roster_page``).
    Measured on https://www.tampaspartans.com/sports/msoc/2026-27/roster
    (2026-09-02): one sortable ``<table>`` whose header cells name the
    columns ("No.", "Name", "Pos.", "Ht.", "Wt.", "Cl.", "Hometown", "High
    School", "Previous College"; each header also carries its label as
    ``data-field-label``) and whose body rows carry a ``jersey-number``
    cell.  Columns are mapped by that header text, never by position.  Each
    body cell repeats its header in a ``.label`` span for narrow screens,
    which is dropped before the value is read.  The site abbreviates what
    SideArm spells out, so four fields are normalised to the SideArm
    vocabulary the consumers parse: position ("Def." is Defender), class
    year ("Sr." is Senior, "Grad." Graduate Student, "R-Fr." Redshirt
    Freshman), height ("6-4" is 6'4") and weight ("200" is 200 lbs); a value
    outside the measured forms is kept as published.  The name is the bio
    link's text ("Alex Hare")
    and ``source_url`` is that link resolved against the page; a print-only
    copy of the same link in the cell is the same player, so rows are
    deduplicated by bio URL (a row without one, by number and name), as the
    SideArm parser deduplicates by player id.

    Two further skins are read by the same header rule.  The doubled-number
    skin (udcfirebirds.com and gonorthwood.com, every season 2022-2026)
    prints the number column twice on each body row, a narrow-screen badge
    (``jersey-number d-md-none``) beside the wide-screen cell, under one
    "No." header, so the body row carries one cell more than the header
    names; ``_roster_row_cells`` folds the two into one before the header
    index is applied, otherwise every value lands one column to the left
    (the number as the name, the name as the position).  The datatables
    skin (chargerathletics.com, every season 2022-2026) carries no
    ``jersey-number`` class at all: its number cell is
    ``td[data-field="number"]`` and its name cell the ``th`` beside it, so
    that pair is the third row marker.  Its headers repeat their labels in
    ``data-field-label`` with a leading space (" No."), which the column key
    strips.  Neither skin's "Hometown/High School" header is a column the
    row shape names, so those rosters carry no hometown.
    """
    soup = BeautifulSoup(html, "lxml")
    players: list[dict[str, str]] = []
    seen: set[str] = set()
    for table in soup.select("table"):
        if table.select_one(_ROSTER_CELLS) is None:
            continue
        columns: dict[int, str] = {}
        for index, header in enumerate(table.select("thead th")):
            label = str(header.get("data-field-label") or "") or header.get_text(
                " ", strip=True
            )
            field = _ROSTER_COLUMNS.get(_column_key(label))
            if field and field not in columns.values():
                columns[index] = field
        if "name" not in columns.values():
            continue
        for row in table.select("tbody tr"):
            values: dict[str, str] = {}
            link: Tag | None = None
            for index, cell in enumerate(_roster_row_cells(row)):
                field = columns.get(index)
                if field is None:
                    continue
                for label_span in cell.select(".label"):
                    label_span.extract()
                if field == "name":
                    link = cell.select_one("a[href]")
                text = " ".join(cell.get_text(" ", strip=True).split())
                if text:
                    values[field] = text
            name = (
                " ".join(link.get_text(" ", strip=True).split())
                if link is not None
                else values.get("name", "")
            )
            if not name:
                continue
            path = str(link.get("href") or "").strip() if link is not None else ""
            key = path or f"{values.get('number', '')}:{name}"
            if key in seen:
                continue
            seen.add(key)
            player: dict[str, str] = {"name": name}
            for field in _ROSTER_FIELDS:
                if field in values:
                    normalise = _ROSTER_NORMALISERS.get(field)
                    player[field] = (
                        normalise(values[field]) if normalise else values[field]
                    )
            if path:
                player["source_url"] = urljoin(page_url, path)
            players.append(player)
    return players


# --- Season statistics ------------------------------------------------------

# The header labels the print template's two individual tables carry, and
# the season-line field each names.  The goalkeeping table is the one that
# names GA; the offensive table prints no minutes and no card column, so a
# PrestoSports field player's season line carries neither.
_STATS_PLAYER_FIELDS: dict[str, tuple[str, Callable[[str], object]]] = {
    "GP": ("gp", _stat_int),
    "GS": ("gs", _stat_int),
    "MIN": ("minutes", _stat_minutes),
    "G": ("goals", _stat_int),
    "A": ("assists", _stat_int),
    "PTS": ("points", _stat_int),
    "SH": ("shots", _stat_int),
    "SH%": ("shot_pct", _stat_float),
    "SOG": ("sog", _stat_int),
    "SOG%": ("sog_pct", _stat_float),
    "GW": ("game_winners", _stat_int),
}
_STATS_KEEPER_FIELDS: dict[str, tuple[str, Callable[[str], object]]] = {
    "GP": ("gp", _stat_int),
    "GS": ("gs", _stat_int),
    "MIN": ("minutes", _stat_minutes),
    "GA": ("goals_against", _stat_int),
    "GAA": ("gaa", _stat_float),
    "SV": ("saves", _stat_int),
    "SV%": ("save_pct", _stat_float),
    "W": ("wins", _stat_int),
    "L": ("losses", _stat_int),
    "T": ("ties", _stat_int),
    "SHUTOUTS": ("shutouts", _stat_int),
    "SHO": ("shutouts", _stat_int),
    "SF": ("shots_faced", _stat_int),
}
# The template pads every name to its column with dots ("Rodrigo Lopes......").
_DOT_LEADERS = re.compile(r"\.+$")
_FOOTER_ROWS = frozenset({"total", "opponents"})


def _cell_texts(cells: list[Tag]) -> list[str]:
    return [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]


def _individual_tables(soup: BeautifulSoup) -> list[tuple[list[str], list[list[str]]]]:
    """Each individual table as (column labels, rows of cell texts).

    The header is the row of ``th`` cells naming a Player column (the
    template prints a group row above it, "GOAL AVERAGE / SAVES / RECORD");
    a row counts when it is as wide as the header, which drops the
    ``<hr>`` spacer rows.
    """
    found: list[tuple[list[str], list[list[str]]]] = []
    for table in soup.select("table"):
        labels: list[str] | None = None
        rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            texts = _cell_texts(cells)
            if labels is None:
                if all(cell.name == "th" for cell in cells) and any(
                    text.lower() == "player" for text in texts
                ):
                    labels = [text.upper() for text in texts]
                continue
            if len(texts) == len(labels):
                rows.append(texts)
        if labels is not None:
            found.append((labels, rows))
    return found


def has_player_stats_markup(html: str) -> bool:
    """Whether the page is the print template carrying individual tables."""
    return bool(_individual_tables(BeautifulSoup(html, "lxml")))


def locate_stats(session: requests.Session, base_url: str, year: int) -> str:
    """Find the season's player statistics page through the site's own redirect.

    The team page's path carries a team segment ("tampa") the pipeline never
    derives from a school's name.  The site reveals it: ``{base}/{y}-{yy}/teams``
    answers HTTP 302 to ``…/teams/{segment}`` (measured 2026-09-02 on
    tampaspartans.com), so one unfollowed request names the segment without
    transferring a page.  A site that serves a page there instead is read for
    the same link (``team_segment``).  Anything else cannot locate the page
    and says what HTTP said.
    """
    url = f"{base_url.rstrip('/')}/{season_path(year)}/teams"
    try:
        response = session.get(url, timeout=30, allow_redirects=False)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LiveCollectionError(
            f"[{year}] failed to fetch {LAYER_STATS} page {url}: {exc}",
            status=http_status(exc),
        ) from exc
    segment: str | None = None
    location = str((response.headers or {}).get("Location") or "").strip()
    if 300 <= int(response.status_code) < 400 and location:
        match = _TEAM_LINK.search(urlparse(urljoin(url, location)).path)
        segment = match.group(1) if match else None
    else:
        assert_served_body(response, year=year, kind=LAYER_STATS, url=url)
        segment = team_segment(response.text)
    if segment is None:
        raise LiveCollectionError(
            f"[{year}] cannot locate the {LAYER_STATS} page: {url} neither "
            f"redirected to a team page nor linked one"
        )
    return player_stats_url(base_url, year, segment)


def parse_stats(
    html: str, *, page_url: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Read the print template's two individual tables into season lines.

    Same line shapes as the SideArm parser (``sidearm_live.parse_stats_page``).
    Measured on the 2025-26 Tampa template (2026-09-02): an offensive table
    headed "#, Player, GP, GS, G, A, PTS, SH, SH%, SOG, SOG%, PK-ATT, GW" and
    a goalkeeping table headed "#, Player, GP, GS, MIN, GA, GAA, SV, SV%, W,
    L, T, SHUTOUTS", columns mapped by that header text, never by position.
    Names print "First Last" padded with dot leaders, which are dropped.
    Both tables list the whole roster and print "-" for a player without an
    appearance (the goalkeeping table prints every field player that way),
    and the "Total" and "Opponents" footers close each: a row is a season
    line only when it counts a game played, as a SideArm table's rows do.
    The template links no bios, so no line carries a player id or bio URL;
    the consumers join these lines to the roster by name.
    """
    del page_url
    players: list[dict[str, object]] = []
    keepers: list[dict[str, object]] = []
    for labels, rows in _individual_tables(BeautifulSoup(html, "lxml")):
        keeping = "GA" in labels
        fields = _STATS_KEEPER_FIELDS if keeping else _STATS_PLAYER_FIELDS
        for texts in rows:
            cells = dict(zip(labels, texts))
            name = _DOT_LEADERS.sub("", cells.get("PLAYER", "")).strip()
            if not name or name.lower() in _FOOTER_ROWS:
                continue
            if "GP" in labels and _stat_int(cells.get("GP", "")) is None:
                continue
            entry: dict[str, object] = {"name": name}
            number = cells.get("#", "")
            if number:
                entry["number"] = number
            for label, (field, convert) in fields.items():
                value = convert(cells.get(label, ""))
                if value is not None:
                    entry[field] = value
            if not keeping:
                cards = _stat_pair(cells.get("YC-RC", ""))
                if cards:
                    entry["yellow"], entry["red"] = cards
                penalties = _stat_pair(cells.get("PK-ATT", "")) or _stat_pair(
                    cells.get("PG-PA", "")
                )
                if penalties:
                    entry["penalty_goals"], entry["penalty_attempts"] = penalties
            (keepers if keeping else players).append(entry)
    return players, keepers


# --- Box scores -------------------------------------------------------------

_BOX_PATH = re.compile(r"/boxscores/(\d{8})_([A-Za-z0-9]+)\.xml$")
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_LONG_DATE = re.compile(r"\b([A-Za-z]{3})[a-z.]*\s+(\d{1,2}),\s*(\d{4})\b")
# The team-statistics boxes, headed by the statistic's name in capitals.
_TEAM_STAT_LABELS = {
    "shots": "shots",
    "saves": "saves",
    "corner kicks": "corners",
    "fouls": "fouls",
    "offsides": "offsides",
}
# A play-by-play line names its side after one of these verbs ("Shot by AUM
# …", "Foul on Tampa.", "Offside against AUM.", "Alex Hare at goalie for
# Tampa.") or leads with it ("Tampa substitution: …").
_TEAM_VERBS = r"(?:by|on|against|for)"
_GOALIE_LINE = re.compile(r"^(?P<name>.+?) at goalie for (?P<team>.+?)\.?$")
_CARD_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("yellow", re.compile(r"\byellow\b", re.IGNORECASE)),
    ("red", re.compile(r"\bred\b", re.IGNORECASE)),
)
_CARD_PHRASE = re.compile(r"^\s*(?:yellow|red)?\s*card\s*-?\s*", re.IGNORECASE)
_LINEUP_FIELDS: dict[str, tuple[str, Callable[[str], object]]] = {
    "SH": ("shots", _stat_int),
    "SOG": ("sog", _stat_int),
    "G": ("goals", _stat_int),
    "A": ("assists", _stat_int),
    "MIN": ("minutes", _stat_minutes),
}
_GOALIE_FIELDS: dict[str, tuple[str, Callable[[str], object]]] = {
    "MIN": ("minutes", _stat_minutes),
    "GA": ("goals_against", _stat_int),
    "SV": ("saves", _stat_int),
}


def boxscore_links_by_event(html: str, page_url: str) -> dict[str, str]:
    """Event id → absolute box-score URL, from each schedule card's own link.

    The recipe's join: a PrestoSports fixture id is ``presto:{owner}:{event
    id}`` and the card carrying that ``data-event-id`` links its box score
    (a ``data-boxscore`` attribute and the "Box Score" link in its
    ``event-links`` block carry the same href).  The box-score filename
    repeats only the id's first four characters, so the join runs through
    the card, never the filename.  The first card per id wins, as in
    ``parse_schedule``.

    A skin without event ids (legacy table, mobile list) is joined on the id
    ``parse_schedule`` mints for the row, ``{yyyymmdd}-{opponent slug}``:
    the date is the box-score filename's (``20250904_j6bo.xml``) and the
    slug is the row's own ``team-name``, so no season or alias table is
    needed to rebuild it.
    """
    links: dict[str, str] = {}
    for event_id, row in _schedule_rows(BeautifulSoup(html, "lxml")).items():
        holder = (
            row if row.has_attr("data-boxscore") else row.select_one("[data-boxscore]")
        )
        href = str(holder.get("data-boxscore") or "").strip() if holder else ""
        if not href:
            anchor = row.select_one('a[href*="/boxscores/"]')
            href = str(anchor.get("href") or "").strip() if anchor is not None else ""
        if not href:
            continue
        if event_id.startswith("#"):
            stem = _BOX_PATH.search(urlparse(urljoin(page_url, href)).path)
            opponent = _clean_team_name(_text(row, _ROW_OPPONENT))
            if stem is None or not opponent:
                continue
            played = stem.group(1)
            date = f"{played[:4]}-{played[4:6]}-{played[6:]}"
            event_id = _minted_id(date, opponent)
        if event_id not in links:
            links[event_id] = urljoin(page_url, href)
    return links


def _person(text: str) -> str:
    """ "Hoffman, Benjamin" is Benjamin Hoffman; a name without a comma, or a
    list of names, is kept as printed."""
    text = " ".join(text.split())
    return _stats_player_name(text) if text.count(",") == 1 else text


def _box_title(soup: BeautifulSoup) -> str:
    """The Open Graph title: "AUM vs. Tampa - Box Score - 9/6/2025".

    The document title is the site's name on every box score measured, so
    the Open Graph title is the one the page names the match by.
    """
    meta = soup.select_one('meta[property="og:title"]')
    return " ".join(str(meta.get("content") or "").split()) if meta is not None else ""


def _box_date(soup: BeautifulSoup) -> str | None:
    """The match date the page names: the Open Graph title's M/D/YYYY, else
    the heading's "September 6, 2025", else the Game Information date."""
    match = _SLASH_DATE.search(_box_title(soup))
    if match:
        month, day, year = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    for text in (
        _text(soup, "article.game-boxscore .head h1"),
        _text(soup, ".game-info .date"),
    ):
        match = _LONG_DATE.search(text)
        month = _DOM_MONTHS.get(match.group(1).lower()) if match else None
        if match and month is not None:
            return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"
    return None


def _linescore_teams(soup: BeautifulSoup) -> list[dict[str, object]]:
    """The two sides as the score-by-period table lists them, visitor first.

    Each row's ``th`` names the side as the page spells it ("#21
    Auburn-Montgomery", rank and all), its ``td.score`` cells are the
    periods and ``td.score.total`` the final, and a ``winner`` row class
    marks the winner.  The abbreviation each side plays under is not in
    the table; the Open Graph title carries both in the same order ("AUM
    vs. Tampa", measured 2026-09-02 on two pages), and the play-by-play
    uses them ("Shot by AUM …").
    """
    teams: list[dict[str, object]] = []
    table = soup.select_one(".linescore table")
    for row in table.find_all("tr") if table is not None else []:
        header = row.find("th", scope="row")
        if header is None:
            continue
        name = " ".join(header.get_text(" ", strip=True).split())
        if not name:
            continue
        team: dict[str, object] = {"name": name}
        periods: list[int] = []
        for cell in row.find_all("td"):
            value = _stat_int(cell.get_text(strip=True))
            if "total" in set(cell.get("class") or []):
                if value is not None:
                    team["score"] = value
            elif value is not None:
                periods.append(value)
        team["periods"] = periods
        if "winner" in set(row.get("class") or []):
            team["winner"] = True
        teams.append(team)
    named = _box_title(soup).split(" - ")[0]
    abbrs = [part.strip() for part in re.split(r"\s+vs\.?\s+", named)]
    if len(abbrs) == len(teams) == 2:
        for team, abbr in zip(teams, abbrs):
            if abbr:
                team["abbr"] = abbr
    return teams


def _identifiers(team: dict[str, object], tokens: set[str]) -> set[str]:
    """Every spelling a page uses for one side: its linescore name, that
    name without its rank, its abbreviation, and the tokens its own
    play-by-play taught (``_learn_play_tokens``)."""
    values = {
        str(team.get("name") or ""),
        _clean_team_name(team.get("name")),
        str(team.get("abbr") or ""),
        *tokens,
    }
    return {value.lower() for value in values if value}


def _side_finder(
    teams: list[dict[str, object]], tokens: list[set[str]]
) -> Callable[[str], int | None]:
    """Resolve a published team reference to an index into ``teams``."""

    def side(reference: str) -> int | None:
        text = " ".join(reference.split()).lower()
        if not text:
            return None
        stripped = _clean_team_name(text).lower()
        for index, team in enumerate(teams):
            known = _identifiers(team, tokens[index])
            if text in known or stripped in known:
                return index
        return None

    return side


def _play_side(
    text: str, teams: list[dict[str, object]], tokens: list[set[str]]
) -> int | None:
    """The side a play narrates: the earliest team identifier the line names
    after a verb or leads with.  Two sides at the same place (one identifier
    spelling both) name nobody."""
    best: tuple[int, int] | None = None
    tie = False
    for index, team in enumerate(teams):
        for identifier in _identifiers(team, tokens[index]):
            pattern = re.compile(
                rf"(?:^|\b{_TEAM_VERBS}\s+){re.escape(identifier)}(?=$|[\s,.:;!])",
                re.IGNORECASE,
            )
            match = pattern.search(text)
            if match is None:
                continue
            if best is None or match.start() < best[0]:
                best, tie = (match.start(), index), False
            elif match.start() == best[0] and index != best[1]:
                tie = True
    return None if best is None or tie else best[1]


_SUBSTITUTION_LINE = re.compile(r"^(?P<team>.+?)\s+substitution:\s*(?P<rest>.*)$", re.I)
_LINEUP_LINE = re.compile(r"^FOR\s+(?P<team>[^:]+?)\s*:(?P<rest>.*)$")
_PRINTED_NAME = re.compile(r"(?P<last>[A-Z][^,;]*?)\s*,\s*(?P<first>[A-Z][\w'-]*)")
_VERB_TOKEN = re.compile(rf"\b{_TEAM_VERBS}\s+(?=[A-Z])")


def _candidate_tokens(text: str) -> list[tuple[str, str]]:
    """Every (team token, printed player name) pair a play could be read as.

    "Shot by UT Judge, Mason." offers ("UT", "Judge, Mason"); "Goal kick by
    Clayton St. Kuisma,Kalle." offers ("Clayton", "St. Kuisma,Kalle") and
    ("Clayton St.", "Kuisma,Kalle").  The caller keeps the pair whose name
    the lineup lists.
    """
    pairs: list[tuple[str, str]] = []
    for match in _VERB_TOKEN.finditer(text):
        rest = text[match.end() :]
        words = rest.split()
        for count in range(1, min(3, len(words)) + 1):
            token = " ".join(words[:count])
            tail = rest[len(token) :].lstrip()
            named = _PRINTED_NAME.match(tail)
            if named is not None:
                pairs.append((token, named.group(0)))
    return pairs


_COMMA_FIRST = re.compile(r",\s*(?P<first>[A-Z][\w'-]*)")


def _printed_people(text: str) -> list[str]:
    """Every "Last, First" a line could be naming: for each comma followed
    by a capitalised word, the one to three words before it.  "Foul on
    Bacar Said, Mikayil." offers "Said, Mikayil", "Bacar Said, Mikayil" and
    "on Bacar Said, Mikayil"; the caller keeps the one the lineup lists."""
    people: list[str] = []
    for match in _COMMA_FIRST.finditer(text):
        before = [
            word
            for word in text[: match.start()].split()
            if not word.startswith("#") and not word.isdigit()
        ]
        for count in range(1, min(3, len(before)) + 1):
            people.append(f"{' '.join(before[-count:])}, {match.group('first')}")
    return people


def _plausible_token(token: str) -> bool:
    """One to three capitalised words with no digit or comma, and not the
    side's own "TEAM" row."""
    words = token.strip(" .:;").split()
    return (
        0 < len(words) <= 3
        and "," not in token
        and all(word[0].isupper() for word in words)
        and not any(ch.isdigit() for ch in token)
        and " ".join(words).upper() != "TEAM"
    )


def _learn_play_tokens(
    texts: list[str], names_by_side: dict[str, int], tokens: list[set[str]]
) -> None:
    """Read each side's play-by-play token off every line that pairs a
    token with a lineup name.

    "Rosenkrantz, Viktor at goalie for AUM." names the keeper the lineup
    lists for one side and the token every later line uses for that side.
    The keeper's line is not enough on its own: one skin flavour names a
    side in full there ("Hare, Alex at goalie for Tampa") and abbreviates it
    everywhere else ("Shot by UT Judge, Mason.", "UT substitution: Tovar,
    Julian for Koerner, Tassilo.", "FOR UT : , #1 Hare, Alex, ..."), so the
    token is learned wherever a lineup name follows it.  A token both sides
    claim teaches nothing.
    """
    claims: dict[str, set[int]] = {}

    def claim(token: str, name: str) -> None:
        index = names_by_side.get(_person(name).lower())
        if index is not None and _plausible_token(token):
            claims.setdefault(token.strip(), set()).add(index)

    for text in texts:
        goalie = _GOALIE_LINE.match(text)
        if goalie is not None:
            claim(goalie.group("team"), goalie.group("name"))
            continue
        listed = _LINEUP_LINE.match(text) or _SUBSTITUTION_LINE.match(text)
        if listed is not None:
            for name in _printed_people(listed.group("rest")):
                claim(listed.group("team"), name)
            continue
        for token, name in _candidate_tokens(text):
            claim(token, name)
    for token, sides in claims.items():
        if len(sides) == 1:
            tokens[next(iter(sides))].add(token)


def _named_side(text: str, names_by_side: dict[str, int]) -> int | None:
    """The side of a play that names no team but names lineup players
    ("Foul on Hoffman, Benjamin."): their side when they share one, else
    nobody."""
    sides: set[int] = set()
    lowered = " ".join(text.split()).lower()
    for name in _printed_people(text):
        index = names_by_side.get(_person(name).lower())
        if index is not None:
            sides.add(index)
    for name, index in names_by_side.items():
        if re.search(rf"(?<![\w'-]){re.escape(name)}(?![\w'-])", lowered):
            sides.add(index)
    return next(iter(sides)) if len(sides) == 1 else None


def _period_name(caption: str) -> str:
    """The play-by-play caption in the SideArm period vocabulary: "1st" is
    "1", "OT" is "3", "2OT" is "4", a shootout is "SO"."""
    text = " ".join(caption.split()).lower()
    if re.search(r"shootout|penalt|\bpk\b|\bso\b", text):
        return "SO"
    ordinal = re.fullmatch(r"(\d+)(?:st|nd|rd|th)(?:\s+(?:half|period))?", text)
    if ordinal:
        return str(int(ordinal.group(1)))
    overtime = re.fullmatch(r"(\d*)\s*ot", text)
    if overtime:
        return str(2 + int(overtime.group(1) or 1))
    return caption.strip()


def _lineup_reference(caption: Tag) -> tuple[str, bool]:
    """The side a lineup table belongs to, and whether it is the goalie table."""
    named = caption.select_one(".team-name")
    text = " ".join(caption.get_text(" ", strip=True).split())
    goalies = re.search(r"\bgoalies?\b", text, re.IGNORECASE) is not None
    if named is not None:
        return " ".join(named.get_text(" ", strip=True).split()), goalies
    return re.sub(r"\s*goalies?\s*$", "", text, flags=re.IGNORECASE), goalies


_LOGO_URL = re.compile(r"url\((['\"]?)(?P<url>[^'\")]+)\1\)", re.I)


def _logo_url(holder: Tag | None) -> str:
    """The badge a ``team-logo`` holder shows: its background image, else
    its ``img``; a trimmed page shows none."""
    if holder is None:
        return ""
    match = _LOGO_URL.search(str(holder.get("style") or ""))
    if match:
        return match.group("url").strip()
    image = holder.find("img")
    return str(image.get("src") or "").strip() if image is not None else ""


def _row_side_label(header: Tag | None) -> str:
    """The side a summary row's header names: the offscreen span beside its
    badge, else the header text without its trailing period."""
    if header is None:
        return ""
    return _text(header, ".offscreen") or re.sub(
        r"\s+\S+$", "", header.get_text(" ", strip=True)
    )


def _carded_side(
    plays: list[dict[str, object]], clock: str, printed: str
) -> int | None:
    """The side of the play-by-play card line at ``clock`` that names the
    carded player as the summary prints them ("Polidori, Tommaso" beside
    "Yellow card on UT Polidori, Tommaso.")."""
    words = {word for word in re.split(r"[\s,]+", printed.lower()) if word}
    if not words:
        return None
    for play in plays:
        if play.get("type") not in {"yellow", "red"} or play.get("clock") != clock:
            continue
        text = str(play["text"]).lower()
        if "team" in play and all(
            re.search(rf"(?<![\w'-]){re.escape(word)}(?![\w'-])", text)
            for word in words
        ):
            return int(play["team"])
    return None


def parse_boxscore(html: str, *, page_url: str) -> dict[str, object]:
    """Read one match's published detail off its box-score page.

    Same detail shape as the SideArm parser (``sidearm_live.parse_boxscore_page``).
    Measured on https://www.tampaspartans.com/sports/msoc/2025-26/boxscores/20250906_4zcl.xml
    and 20250911_fjlo.xml (2026-09-02):

    - ``teams``: the ``linescore`` table, visitor first (``_linescore_teams``);
      the four ``stats-box team-stats`` tables (SHOTS, SAVES, CORNER KICKS,
      FOULS, each with per-period cells and a TOTAL) fill the team totals by
      the table's own heading, and shots on goal come from the lineup
      table's totals row, the one place the page sums them.
    - ``players`` and ``keepers``: the ``stats-box lineup`` tables, one per
      side, captioned with the side's name (the goalie tables add
      "Goalies").  A row's ``th`` carries the position, the uniform number
      and the name (a link for the site owner's players, a span for the
      opponent's); its cells are mapped by the header text (SH, SOG, G, A,
      MIN; GA, SV, Min).  The "TM TEAM" row and the totals row are not
      people.  The page marks no starters, so no line says ``started``, and
      its player links point into a different id space from the roster's
      bio links, so no line carries a player id.
    - ``scoring``: the Scoring Summary rows, each headed by the scoring side
      (an offscreen span beside its logo) and its period, with the clock and
      "Scorer (season total) (assist)".  A row whose scorer cell is empty
      (the play-by-play's "GOAL by AUM TEAM.") is the side's own goal and is
      kept with the scorer ``TEAM``, the lineup's word for the side.
    - ``cards``: the Penalty Summary rows, "Yellow card - Name" under the
      side and period; a card the page words some other way is ``unknown``.
      The rows' offscreen labels all repeat one side's name on every page
      measured, so a row's side is its logo (matched to the head's visitor
      and home badges and the scoring rows'), else the play-by-play card
      line at its clock naming its player, else the label only when the
      labels differ from row to row.
    - ``plays``: every play-by-play row, per period table ("1st", "2nd";
      overtime and shootout captions map onto the SideArm period names).
      A row's side is the team identifier its text names after "by", "on",
      "against" or "for", or leads with ("Tampa substitution: ..."); the
      identifiers are the linescore names, the Open Graph abbreviations and
      the tokens the play-by-play itself teaches, off every line that pairs
      a token with a lineup name (the keeper's opening line, "Shot by UT
      Judge, Mason.", "UT substitution: ...", "FOR UT : ...").  A row that
      names no side but names lineup players ("Foul on Hoffman, Benjamin.")
      is theirs when they share a side.  A goal row's running score
      (visitor, home) is stored in ``teams`` order.
    - ``stadium``, ``attendance``, ``kickoff`` and the labelled officials
      from the Game Information table.
    """
    soup = BeautifulSoup(html, "lxml")
    teams = _linescore_teams(soup)
    tokens: list[set[str]] = [set() for _ in teams]
    side = _side_finder(teams, tokens)

    for box in soup.select(".stats-box.team-stats"):
        rows = box.find_all("tr")
        if not rows:
            continue
        heading = rows[0].find("th")
        field = _TEAM_STAT_LABELS.get(
            " ".join(heading.get_text(" ", strip=True).split()).lower()
            if heading is not None
            else ""
        )
        if field is None:
            continue
        for row in rows[1:]:
            header = row.find("th")
            cells = row.find_all("td")
            if header is None or not cells:
                continue
            index = side(header.get_text(" ", strip=True))
            total = _stat_int(cells[-1].get_text(strip=True))
            if index is not None and total is not None:
                teams[index][field] = total

    names_by_side: dict[str, int] = {}
    for box in soup.select(".stats-box.lineup"):
        table = box.find("table")
        caption = table.find("caption") if table is not None else None
        if table is None or caption is None:
            continue
        reference, goalies = _lineup_reference(caption)
        index = side(reference)
        if index is None:
            continue
        labels: list[str] = []
        head = table.find("thead")
        for cell in head.find_all("th") if head is not None else []:
            labels.extend(
                [" ".join(cell.get_text(" ", strip=True).split()).upper()]
                * int(cell.get("colspan") or 1)
            )
        fields = _GOALIE_FIELDS if goalies else _LINEUP_FIELDS
        lines: list[dict[str, object]] = []
        for row in table.select("tbody tr"):
            header = row.find("th")
            if header is None:
                continue
            values = dict(
                zip(labels, _cell_texts([header, *row.find_all("td", recursive=False)]))
            )
            if "totals" in set(row.get("class") or []):
                on_goal = _stat_int(values.get("SOG", ""))
                if not goalies and on_goal is not None and "sog" not in teams[index]:
                    teams[index]["sog"] = on_goal
                continue
            number = _text(header, ".uniform").rstrip(" -").strip()
            name_node = header.select_one(".player-name")
            name = _person(name_node.get_text(" ", strip=True)) if name_node else ""
            if (
                not name
                or number.upper() == "TM"
                or name.lower() in {"team", "tm team"}
            ):
                continue
            line: dict[str, object] = {"name": name}
            position = _text(header, ".position")
            if position:
                line["position"] = position.upper()
            if number:
                line["number"] = number
            for label, (field, convert) in fields.items():
                value = convert(values.get(label, ""))
                if value is not None:
                    line[field] = value
            lines.append(line)
            names_by_side.setdefault(name.lower(), index)
        teams[index]["keepers" if goalies else "players"] = lines

    # The linescore, the Open Graph title and the lineup panels all list the
    # visitor first; the panel labels say which side that is.
    visitor = 0
    label = soup.select_one('.player-stats [data-panel-for="team-label-v"] .team-name')
    if label is not None:
        found = side(label.get_text(" ", strip=True))
        if found is not None:
            visitor = found
    home = 1 - visitor if len(teams) == 2 else None

    # Each side's logo, keyed by URL: the head's visitor and home badges,
    # then every scoring row's badge beside the side its label resolves to.
    logos: dict[str, int] = {}
    for holder, index in (
        (soup.select_one(".head .team.visitor .team-logo"), visitor),
        (soup.select_one(".head .team.home .team-logo"), home),
    ):
        logo = _logo_url(holder)
        if logo and index is not None:
            logos.setdefault(logo, index)

    scoring: list[dict[str, object]] = []
    for row in soup.select(".stats-box.scoring-summary tbody tr"):
        header = row.find("th")
        text = _text(row, "td.text")
        if header is None or not text:
            continue
        entry: dict[str, object] = {}
        clock = _text(row, "td.time")
        if clock:
            entry["time"] = clock
        index = side(_row_side_label(header))
        if index is not None:
            entry["team"] = index
            logo = _logo_url(header.select_one(".team-logo"))
            if logo:
                logos.setdefault(logo, index)
        # An empty scorer cell ("  (0) (unassisted)" beside the play-by-play's
        # "GOAL by AUM TEAM.") is the side's own goal credit, not a dropped
        # row: the goal stays on the record under the lineup's word for it.
        entry["scorer"] = _person(text.split("(", 1)[0]) or "TEAM"
        for part in re.findall(r"\(([^)]*)\)", text):
            note = part.strip()
            if note.isdigit():
                entry["season_total"] = int(note)
            elif re.search(r"unassisted", note, re.IGNORECASE):
                continue
            elif re.search(r"penalty|own goal|\bpk\b", note, re.IGNORECASE):
                entry["description"] = note
            elif note:
                entry["assist"] = _person(note)
        scoring.append(entry)

    narrated: list[tuple[str, str, str, list[int] | None]] = []
    for table in soup.select("#pbp-tabpanel table, .plays table"):
        period = _period_name(_text(table, "caption"))
        for row in table.find_all("tr"):
            cell = row.find("td", class_="play")
            if cell is None:
                continue
            score: list[int] | None = None
            visiting = _stat_int(_text(cell, ".v-score"))
            hosting = _stat_int(_text(cell, ".h-score"))
            if visiting is not None and hosting is not None and home is not None:
                score = [0, 0]
                score[visitor] = visiting
                score[home] = hosting
            for extra in cell.select(".action-title, strong"):
                extra.extract()
            text = " ".join(cell.get_text(" ", strip=True).split())
            if not re.search(r"[A-Za-z]", text):
                continue
            narrated.append((period, _text(row, "td.time"), text, score))
    _learn_play_tokens([text for _, _, text, _ in narrated], names_by_side, tokens)
    plays: list[dict[str, object]] = []
    for period, clock, text, score in narrated:
        play: dict[str, object] = {"period": period, "text": text}
        if re.fullmatch(r"\d+:\d{2}", clock):
            play["clock"] = clock
        index = _play_side(text, teams, tokens)
        if index is None:
            index = _named_side(text, names_by_side)
        if index is not None:
            play["team"] = index
        kind = _play_type(text)
        if kind:
            play["type"] = kind
        if score is not None:
            play["score"] = score
        plays.append(play)

    # The Penalty Summary's offscreen label repeats one side's name on every
    # row (every page measured: AUM on all five of 20250906_4zcl, AUM on all
    # four of 20260829_rvya, Clayton State on all three of 20260903_jdlp),
    # while the row's own badge is the right side's.  So a card's side is its
    # badge, else the play-by-play card line at its clock naming its player,
    # else the label only when the labels differ from row to row.
    rows = soup.select(".stats-box.penalty-summary tbody tr")
    labels = {_row_side_label(row.find("th")) for row in rows if row.find("th")}
    cards: list[dict[str, object]] = []
    for row in rows:
        header = row.find("th")
        cell = row.find("td", class_="text")
        if header is None or cell is None:
            continue
        text = " ".join(cell.get_text(" ", strip=True).split())
        kind = next(
            (name for name, pattern in _CARD_KINDS if pattern.search(text)), None
        )
        printed = _CARD_PHRASE.sub("", text)
        player = _person(printed)
        if not player:
            continue
        entry = {"type": kind or "unknown", "player": player}
        clock = _text(row, "td.time")
        if clock:
            entry["time"] = clock
        index = logos.get(_logo_url(header.select_one(".team-logo")))
        if index is None:
            index = _carded_side(plays, clock, printed)
        if index is None and len(labels) > 1:
            index = side(_row_side_label(header))
        if index is not None:
            entry["team"] = index
        cards.append(entry)

    detail: dict[str, object] = {"source_url": page_url, "teams": teams}
    if scoring:
        detail["scoring"] = scoring
    if cards:
        detail["cards"] = cards
    if plays:
        detail["plays"] = plays

    officials: list[str] = []
    for row in soup.select(".stats-box.game-info tr"):
        header = row.find("th")
        cell = row.find("td")
        if header is None or cell is None:
            continue
        label = " ".join(header.get_text(" ", strip=True).split())
        value = " ".join(cell.get_text(" ", strip=True).split())
        if label.endswith(":"):
            role = label.rstrip(":").strip()
            if role and value:
                officials.append(f"{role}: {value}")
            continue
        key = label.lower()
        if key == "date/time" and " - " in value:
            kickoff = value.split(" - ", 1)[1].strip()
            if kickoff:
                detail["kickoff"] = kickoff
        elif key == "stadium" and value:
            detail["stadium"] = value
        elif key == "attendance":
            attendance = _stat_int(value)
            if attendance is not None:
                detail["attendance"] = attendance
    if officials:
        detail["officials"] = officials
    return detail


def _names_both_sides(
    teams: list[dict[str, object]], fixture: dict[str, object]
) -> bool:
    """Whether the page's two sides name the fixture's two slugs, either way
    round, by the name affinity ``orient_match`` uses; an abbreviation counts
    ("AUM" for the slug ``aum`` where "#21 Auburn-Montgomery" would not)."""
    if len(teams) != 2:
        return False
    home, away = str(fixture.get("home") or ""), str(fixture.get("away") or "")

    def affinity(team: dict[str, object], slug: str) -> int:
        return max(
            _name_slug_affinity(str(team.get(key) or ""), slug)
            for key in ("name", "abbr")
        )

    straight = affinity(teams[0], home) and affinity(teams[1], away)
    crossed = affinity(teams[0], away) and affinity(teams[1], home)
    return bool(straight or crossed)


def assert_served_match(
    page: PublishedPage, year: int, fixture: dict[str, object]
) -> None:
    """A box score must prove WHICH match it is, not merely which season.

    The SideArm rule (``sidearm_live.assert_served_match``) on this
    platform's page: the served path must be a ``boxscores/{yyyymmdd}_{id}.xml``
    page carrying the requested id (a redirect that swaps it is a different
    match), the page must title itself a box score and name a match date,
    that date must equal the fixture's own, and the two sides it names must
    be the fixture's two slugs (``_names_both_sides``).
    """
    fixture_id = str(fixture.get("id", ""))
    served = _BOX_PATH.search(urlparse(page.final_url).path)
    if served is None:
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: {page.requested_url} redirected to "
            f"{page.final_url}, which is not a box-score page"
        )
    requested = _BOX_PATH.search(urlparse(page.requested_url).path)
    if requested is not None and requested.group(0) != served.group(0):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: requested box score {requested.group(2)} "
            f"but {page.final_url} served box score {served.group(2)}"
        )
    soup = BeautifulSoup(page.html, "lxml")
    if (
        not re.search(r"box\s*score", _box_title(soup), re.IGNORECASE)
        and soup.select_one("article.game-boxscore") is None
    ):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: {page.final_url} does not title itself a box score"
        )
    served_date = _box_date(soup)
    if served_date is None:
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: cannot prove which match {page.final_url} "
            f"served: its title names no match date"
        )
    if served_date != str(fixture.get("date")):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: requested the {fixture.get('date')} match "
            f"but {page.final_url} served the match of {served_date}"
        )
    teams = _linescore_teams(soup)
    if not _names_both_sides(teams, fixture):
        named = " and ".join(str(team.get("name")) for team in teams) or "no side"
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: {page.final_url} served {named}, which "
            f"does not name both {fixture.get('home')} and {fixture.get('away')}"
        )


def collect_match(
    session: requests.Session,
    url: str,
    year: int,
    fixture: dict[str, object],
) -> dict[str, object]:
    """Fetch one fixture's box score, prove it is that fixture's, and parse it.

    The fetch rides the shared session and the shared body check: a 2xx that
    is not the page (the site's HTTP 202 challenge after a burst) is refused
    with its status, never read as a box score with no teams.
    """
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LiveCollectionError(
            f"[{year}] {fixture.get('id')}: failed to fetch box score {url}: {exc}",
            status=http_status(exc),
        ) from exc
    assert_served_body(response, year=year, kind="box-score", url=url)
    page = PublishedPage(url, response.url, response.text)
    assert_served_match(page, year, fixture)
    detail = parse_boxscore(page.html, page_url=page.final_url)
    teams = detail.get("teams") or []
    if len(teams) != 2:  # type: ignore[arg-type]
        raise LiveCollectionError(
            f"[{year}] {fixture.get('id')}: {page.final_url} proved its match but "
            f"its score-by-period table rendered {len(teams)} team(s) "  # type: ignore[arg-type]
            f"where a match needs exactly two"
        )
    orient_match(detail, fixture)
    return detail
