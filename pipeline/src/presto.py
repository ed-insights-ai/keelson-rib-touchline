"""What the pipeline knows about PrestoSports athletics sites.

PrestoSports is the second platform the pipeline recognises (Tampa in the
SSC; Westmont, Wilmington and St. Thomas Aquinas are next), and this module
holds everything the pipeline knows about it: the URL shapes, the markup the
probe fingerprints, the season proof, and the schedule and roster parsers.
The stats and box-score parsers land here in the change that follows (bead
tl-v1q.5, PR 3); nothing about the platform lives anywhere else.  The recipe
that hands these to ``collect_programme`` is ``PRESTO`` in src/recipes.py.

The parsers emit the same fixture and player rows the SideArm parsers do,
and they read rendered text by the SideArm DOM path's own rules (its date,
kickoff, result, orientation and exhibition helpers are imported below), so
a date, a kickoff or a "L, 2-1" resolves the same way on both platforms.

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
from bs4 import BeautifulSoup, Tag

from src.sidearm_live import (
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LiveCollectionError,
    PublishedPage,
    _clean_team_name,
    _dom_date,
    _dom_result,
    _dom_time,
    _exhibition_marked,
    _oriented_scores,
    assert_served_body,
    http_status,
    opponent_slug,
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
    assert_served_body(response, year=year, kind=kind, url=url)
    page = PublishedPage(url, response.url, response.text)
    season_served(page.final_url, page.html, year, kind)
    return page


def assert_served_season(page: PublishedPage, year: int, kind: str) -> None:
    """The recipe's season proof: ``season_served`` over a fetched page."""
    season_served(page.final_url, page.html, year, kind)


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
# The date and kickoff every event link label carries: "Men's Soccer event:
# September 4 07:00 PM: #13 West Florida vs. Tampa: Box Score".
_EVENT_LABEL = re.compile(
    r"\bevent:\s*([A-Za-z]+\s+\d{1,2})\s+(\d{1,2}:\d{2}\s*[AP]\.?M)", re.IGNORECASE
)


def _text(node: Tag | None, selector: str) -> str:
    """The collapsed text of the first ``selector`` match under ``node``, or ""."""
    found = node.select_one(selector) if node is not None else None
    if found is None:
        return ""
    return " ".join(found.get_text(" ", strip=True).split())


def _event_label(card: Tag) -> str:
    """The "{Month} {day} {kickoff}" the card's event links label, or ""."""
    for anchor in card.select(".event-links a[aria-label]"):
        match = _EVENT_LABEL.search(str(anchor.get("aria-label") or ""))
        if match:
            return f"{match.group(1)} {match.group(2)}"
    return ""


def _card_date(card: Tag, year: int) -> str | None:
    section = card.find_parent(class_="section-event-month")
    month = _text(section, ".month-title") if section is not None else ""
    day = re.search(r"\d{1,2}", _text(card, ".event-dateinfo .date"))
    if month and day:
        return _dom_date(f"{month} {day.group(0)}", year)
    return _dom_date(_event_label(card), year)


def _card_venue(card: Tag, notes: str) -> str:
    facility = _text(card, ".event-dateinfo .venue")
    if facility:
        return facility
    neutral_site = _text(card, ".event-neutralsite")
    if neutral_site:
        return re.sub(r"^@\s*", "", neutral_site)
    return notes.split(" / ", 1)[0].strip()


def parse_schedule(
    html: str,
    *,
    page_url: str,
    year: int,
    owner_slug: str,
    aliases: dict[str, str],
    members: set[str] | None = None,
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
    """
    soup = BeautifulSoup(html, "lxml")
    cards: dict[str, Tag] = {}
    for card in soup.select(".event-row[data-event-id]"):
        event_id = str(card.get("data-event-id") or "").strip()
        if event_id and event_id not in cards:
            cards[event_id] = card

    def conference_marked(card: Tag) -> bool:
        return card.select_one(
            '.notation[title="Conference"]'
        ) is not None or "conf" in set(card.get("class") or [])

    theme_marks_conference = any(conference_marked(card) for card in cards.values())
    member_slugs = set(aliases.values()) if members is None else members

    fixtures: list[dict[str, object]] = []
    for event_id, card in cards.items():
        opponent_raw = _text(card, ".event-opponent-name")
        opponent_name = _clean_team_name(opponent_raw)
        date = _card_date(card, year)
        if not opponent_name or not date:
            continue
        if _PLACEHOLDER.fullmatch(opponent_name) or _ROUND_NAME.search(opponent_name):
            continue
        classes = set(card.get("class") or [])
        owner_is_home = _text(card, ".event-location-badge").lower() != "at"
        neutral = (
            "neutral" in classes or card.select_one(".event-neutralsite") is not None
        )
        other_slug = opponent_slug(opponent_name, aliases)
        home, away = (
            (owner_slug, other_slug) if owner_is_home else (other_slug, owner_slug)
        )
        status_text = _text(card, ".event-dateinfo .status")
        result_text = _text(card, ".event-result")
        result = _dom_result(result_text)
        notes = _text(card, ".event-notes")
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
            fixture["conference_game"] = conference_marked(card)
        else:
            fixture["conference_game"] = not exhibition and other_slug in member_slugs
            fixture["conference_game_source"] = "derived:membership"
        time = _dom_time(status_text) or _dom_time(_event_label(card))
        if time:
            fixture["time"] = time
        venue = _card_venue(card, notes)
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
    "weight": "weight",
    "cl": "class_year",
    "class": "class_year",
    "yr": "class_year",
    "year": "class_year",
    "hometown": "hometown",
}
_ROSTER_FIELDS = ("number", "position", "height", "weight", "hometown", "class_year")


def _column_key(label: str) -> str:
    return re.sub(r"[.\s]+$", "", label.strip().lower())


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
    which is dropped before the value is read; values are kept as published
    ("6-4", "200", "Sr.").  The name is the bio link's text ("Alex Hare")
    and ``source_url`` is that link resolved against the page; a print-only
    copy of the same link in the cell is the same player, so rows are
    deduplicated by bio URL (a row without one, by number and name), as the
    SideArm parser deduplicates by player id.
    """
    soup = BeautifulSoup(html, "lxml")
    players: list[dict[str, str]] = []
    seen: set[str] = set()
    for table in soup.select("table"):
        if table.select_one("tr .jersey-number") is None:
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
            for index, cell in enumerate(row.find_all(["td", "th"], recursive=False)):
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
                    player[field] = values[field]
            if path:
                player["source_url"] = urljoin(page_url, path)
            players.append(player)
    return players
