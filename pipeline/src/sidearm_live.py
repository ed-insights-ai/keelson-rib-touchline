"""Collect published SideArm schedules and rosters.

The historical pipeline starts from box scores, which necessarily omits every
future fixture.  SideArm season pages publish the schedule twice: as embedded
component JSON and as server-rendered ``li.sidearm-schedule-game`` markup.
Only some themes embed the full season in the JSON — most ship a short
"upcoming" stub there (measured 2026-08-09 across one conference: 1 of 27
games on one theme) while the DOM always carries every game.  Both sources
share one event-id space, so this module reads the JSON first (it is richer:
ISO timestamps, typed results, an explicit conference flag) and fills the
rest from the DOM, without turning an unplayed match into a result.

The two sources also disagree about PAST seasons, in opposite directions.
The embedded payload names the current season no matter which season URL
served it, so it can never prove — or supply — a past season.  The DOM is
the reverse: measured 2026-08-09 across seven sites and seasons back to
2016, ``/schedule/{year}`` renders the genuine requested season (honest
title, game-id sets fully disjoint from the current season's, complete
results).  A past season is therefore collected DOM-only: the season filter
in ``parse_schedule_page`` drops the current-season payload events, and
``assert_untrapped_schedule`` refuses the one dangerous shape — a page whose
rendered games ARE the payload's current-season events under a past URL.

The stats layer reads ``/stats/{year}`` — SideArm's cumulative-statistics
page.  It is fully server-rendered with an honest per-year title on every
site measured (2026-08-10, seven sites, back to 2016), so the wrapper check
in ``assert_served_season`` is the whole guard; there is no payload to trap
it.  ``parse_stats_page`` reads the individual offensive and goalkeeping
tables into per-player season lines.

The matches layer reads the per-game box-score pages that every schedule
page links for its played fixtures (measured 2026-08-10, 63 (site, season)
cells across seven sites back to 2016, COVID 2020 included): the link's
trailing id IS the schedule's own game id, and the page is fully
server-rendered — captioned tables for score by period, scoring summary,
cautions, team statistics, and per-team player and goalie lines.  The page
proves WHICH match it is: its title reads "vs <Opponent> on M/D/YYYY - Box
Score", and ``assert_served_match`` requires that date to equal the
fixture's own date.  The season year alone would be the wrong anchor — the
COVID 2020 season's matches were played in spring 2021 and their titles
honestly say so.  A goalless match legitimately omits the Scoring Summary
table, so no guard may require it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from urllib3.util.retry import Retry

from src.config import SchoolConfig
from src.page_state import PageState, PageStateStore, content_signature
from src.tls import TruststoreHTTPAdapter

_LOG = logging.getLogger(__name__)


class LiveCollectionError(RuntimeError):
    """A live page could not be proven to represent the requested season."""


@dataclass(frozen=True)
class PublishedPage:
    requested_url: str
    final_url: str
    html: str


LAYER_SCHEDULE = "schedule"
LAYER_ROSTER = "roster"
LAYER_STATS = "stats"
# Collected per deduplicated fixture by the board collector, not per programme
# in `collect_programme` — a conference game appears on two schedules but its
# box score should be fetched once.
LAYER_MATCHES = "matches"
DEFAULT_LAYERS: tuple[str, ...] = (
    LAYER_SCHEDULE,
    LAYER_ROSTER,
    LAYER_STATS,
    LAYER_MATCHES,
)

# The vocabulary the coverage manifest renders.  These three states are the
# whole reason the manifest exists: an empty results column means something
# different in each, and conflating them is how a data product loses trust.
STATE_COMPLETE = "complete"  # served, proven, and holds rows
STATE_EMPTY = "empty"  # served and proven, and genuinely holds nothing
STATE_UNAVAILABLE = "unavailable"  # could not be collected; `reason` says why
STATE_NO_COLLECTOR = "no-collector"
LIVE_COLLECTORS: frozenset[str] = frozenset({"sidearm"})


@dataclass(frozen=True)
class LayerOutcome:
    """What one collection layer produced for one programme."""

    layer: str
    state: str
    count: int = 0
    reason: str | None = None
    source_url: str | None = None
    #: The page was verified still current (a 304, or identical bytes) and its
    #: stored data was reused: the parse was skipped and the archived bytes
    #: must not be rewritten.
    unchanged: bool = False


@dataclass(frozen=True)
class ProgrammeCollection:
    slug: str
    name: str
    fixtures: list[dict[str, object]]
    players: list[dict[str, str]]
    outcomes: dict[str, LayerOutcome]
    schedule_url: str = ""
    roster_url: str = ""
    schedule_html: str = ""
    roster_html: str = ""
    stat_players: list[dict[str, object]] | None = None
    stat_keepers: list[dict[str, object]] | None = None
    stats_url: str = ""
    stats_html: str = ""

    def state(self, layer: str) -> str:
        outcome = self.outcomes.get(layer)
        return outcome.state if outcome else STATE_UNAVAILABLE


def build_session(session: requests.Session | None = None) -> requests.Session:
    """Configure the collector's session — headers, retries, OS-trust TLS.

    A caller may supply the session instance (the board collector hands in a
    host-gated one so the politeness contract rides every request); by
    default a plain one is built.
    """
    session = session if session is not None else requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (Touchline educational/research collector)"}
    )
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = TruststoreHTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def programme_slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return text


def _season_in_path(url: str, kind: str) -> int | None:
    path = urlparse(url).path.rstrip("/")
    match = re.search(rf"/{kind}/(\d{{4}})(?:-\d{{2}})?$", path)
    return int(match.group(1)) if match else None


def _season_in_title(html: str, kind: str) -> int | None:
    title = BeautifulSoup(html, "lxml").title
    if title is None:
        return None
    # Prefix match, not whole-word: the /stats/ URL kind appears in titles as
    # "Cumulative Statistics", and "schedule"/"roster" only ever gain suffixes.
    match = re.search(
        rf"\b(\d{{4}})(?:-\d{{2}})?\b.*\b{kind}", title.get_text(" "), re.I
    )
    return int(match.group(1)) if match else None


TITLE_WORDS = {LAYER_STATS: "statistic"}


def assert_served_season(page: PublishedPage, year: int, kind: str) -> None:
    """Reject a silent redirect or fallback to another season.

    Some SideArm sites canonicalise the current season to ``/schedule``.  That
    is acceptable only when the title independently names the requested year.
    When both path and title name a season, both must agree.
    """
    path_year = _season_in_path(page.final_url, kind)
    title_year = _season_in_title(page.html, TITLE_WORDS.get(kind, kind))
    observed = [value for value in (path_year, title_year) if value is not None]
    if not observed:
        raise LiveCollectionError(
            f"[{year}] cannot prove which {kind} season was served at {page.final_url}"
        )
    wrong = sorted({value for value in observed if value != year})
    if wrong:
        raise LiveCollectionError(
            f"[{year}] requested {page.requested_url} but {page.final_url} served "
            f"{kind} season {', '.join(str(value) for value in wrong)}"
        )


@dataclass(frozen=True)
class ConditionalFetch:
    """What one conditional request learned about a published page.

    ``unchanged`` with no ``page`` is a 304: the server confirmed the archived
    bytes are current and sent nothing.  ``unchanged`` with a ``page`` is the
    content-hash tier: the body arrived but is byte-identical to the archive,
    so the parse and the write are still skipped.  Neither is a gap — the data
    home already holds this page and its parse.
    """

    page: PublishedPage | None
    unchanged: bool
    etag: str | None = None
    last_modified: str | None = None
    signature: str | None = None


def fetch_published_page_conditional(
    session: requests.Session,
    base_url: str,
    year: int,
    kind: str,
    state: PageState | None = None,
    want_validators: bool = False,
) -> ConditionalFetch:
    """Fetch a page, asking the server first whether it changed at all.

    Two tiers, cheapest first.  With stored validators the request carries
    ``If-None-Match``/``If-Modified-Since`` and a 304 is an immediate skip —
    no body, no parse.  Servers that answer 200 anyway are caught by the
    content hash: identical bytes under the same final URL still skip the
    parse, costing only the transfer.  The season assertion runs only on
    genuinely new content — an unchanged page already proved its season when
    it was archived, and the assertion's title parse is exactly the work the
    skip exists to avoid.
    """
    requested_url = f"{base_url.rstrip('/')}/{kind}/{year}"
    headers: dict[str, str] = {}
    if state is not None:
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
    try:
        response = session.get(requested_url, timeout=30, headers=headers or None)
        if state is not None and response.status_code == 304:
            return ConditionalFetch(page=None, unchanged=True)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LiveCollectionError(
            f"[{year}] failed to fetch {kind} page {requested_url}: {exc}"
        ) from exc
    page = PublishedPage(requested_url, response.url, response.text)
    etag: str | None = None
    last_modified: str | None = None
    signature: str | None = None
    if want_validators:
        served = getattr(response, "headers", None) or {}
        etag = served.get("ETag")
        last_modified = served.get("Last-Modified")
        signature = content_signature(page.html)
        if (
            state is not None
            and state.signature == signature
            and state.final_url == page.final_url
        ):
            return ConditionalFetch(
                page=page,
                unchanged=True,
                etag=etag,
                last_modified=last_modified,
                signature=signature,
            )
    assert_served_season(page, year, kind)
    return ConditionalFetch(
        page=page,
        unchanged=False,
        etag=etag,
        last_modified=last_modified,
        signature=signature,
    )


def fetch_published_page(
    session: requests.Session, base_url: str, year: int, kind: str
) -> PublishedPage:
    fetched = fetch_published_page_conditional(session, base_url, year, kind)
    if fetched.page is None:  # unreachable without stored validators
        raise LiveCollectionError(
            f"[{year}] {kind} page returned no content without a conditional request"
        )
    return fetched.page


def _component_objects(html: str) -> list[dict[str, object]]:
    """Decode SideArm's one-line ``var obj = {...};`` component payloads."""
    objects: list[dict[str, object]] = []
    prefix = "var obj = "
    for line in html.splitlines():
        source = line.strip()
        if not source.startswith(prefix) or not source.endswith(";"):
            continue
        try:
            value = json.loads(source[len(prefix) : -1])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def payload_seasons(html: str) -> set[int]:
    """Seasons named by the schedule payload itself, not by the page wrapper.

    Measured 2026-08-09: ``/sports/mens-soccer/schedule/2019`` answers 200, keeps
    ``/2019`` through every redirect, and carries a page title that names 2019 —
    while every embedded ``events`` component carries
    ``schedule.title == "2026 Men's Soccer Schedule"``.  The wrapper is honest and
    the payload is the current season.  ``assert_served_season`` cannot see that,
    because it only ever reads the wrapper.
    """
    years: set[int] = set()
    for component in _component_objects(html):
        if component.get("type") != "events":
            continue
        data = component.get("data")
        if not isinstance(data, list):
            continue
        for raw in data:
            if not isinstance(raw, dict):
                continue
            schedule = raw.get("schedule")
            schedule_dict = schedule if isinstance(schedule, dict) else {}
            match = re.search(r"\b(\d{4})\b", str(schedule_dict.get("title") or ""))
            if match:
                years.add(int(match.group(1)))
    return years


def _payload_event_ids(html: str, owner_slug: str) -> set[str]:
    """Fixture ids of every embedded event, whatever season the payload claims."""
    ids: set[str] = set()
    for component in _component_objects(html):
        if component.get("type") != "events":
            continue
        data = component.get("data")
        if not isinstance(data, list):
            continue
        for raw in data:
            if isinstance(raw, dict) and raw.get("id"):
                ids.add(f"sidearm:{owner_slug}:{raw['id']}")
    return ids


def _has_schedule_markup(html: str) -> bool:
    """Whether the page carries any SideArm schedule shape at all."""
    if any(component.get("type") == "events" for component in _component_objects(html)):
        return True
    return (
        BeautifulSoup(html, "lxml").select_one("li.sidearm-schedule-game") is not None
    )


def assert_untrapped_schedule(
    html: str,
    year: int,
    page_url: str,
    fixtures: list[dict[str, object]],
    owner_slug: str,
) -> None:
    """Refuse a season page whose rendered games are the current season's.

    The embedded payload names the current season at every season URL, so a
    payload naming another year proves nothing by itself — the DOM alongside it
    is genuinely the requested season on every site measured (2026-08-09, id
    sets fully disjoint).  The one dangerous shape is a server that canonicalises
    a past URL to the current schedule under an honest-looking wrapper: there the
    rendered games and the payload's events are the same games, so any parsed
    fixture sharing an id with the payload betrays it.
    """
    served = payload_seasons(html)
    if year in served:
        return
    overlap = _payload_event_ids(html, owner_slug) & {
        str(fixture["id"]) for fixture in fixtures
    }
    if overlap:
        listed = ", ".join(str(value) for value in sorted(served)) or "another season"
        raise LiveCollectionError(
            f"[{year}] {page_url} renders the season-{listed} schedule at this "
            f"season URL, so {year} fixtures cannot be collected from it"
        )


# A poll or tournament rank moves week to week, so leaving it in the name mints
# a new identity every time it changes: the archive holds no-4-csu-pueblo
# beside no-15-csu-pueblo, and three separate slugs for Midwestern State.
#
# Scanning 231 archived schedule pages for any leading run that is not a plain
# capitalised word, these are the forms published:
#
#   #9  No. 23  No.11  9        a poll rank, with or without a marker
#   RV  #RV                     receiving votes: a rank carrying no digits at
#                               all, which every numeric form missed
#   (3)  [7]                    a seed, bracketed either way
#   3-seed  #4-seed  5th-Seed   a seed spelled as a word
#   #5 Seed  #8 Seed  #4 seed   a seed spelled as a separate word: the
#                               tournament theme renders "<span>#5 Seed</span>"
#                               before the opponent link (measured
#                               "#5 Seed Maryville University" on
#                               mckbearcats.com 2025, "#8 Seed Drury
#                               University" on uisprairiestars.com 2023,
#                               "#4 seed DBU" on uttylerpatriots.com 2025).
#                               The hyphenated form alone stripped the "#5"
#                               and left "Seed", filing the match under
#                               seed-maryville, seed-drury, seed-dbu
#   RV/#11  #4/#5               ranked in two polls at once, slash-joined
#   (1) #3   #17 [7]   (5) RV   a bracketed seed in front of a second rank
#
# So a token is a value carrying an optional marker or bracket, tokens may be
# slash-joined, and the whole prefix repeats.
#
# Two limits stop it eating real names. Two digits is the whole range a poll
# uses, and every token must be followed by whitespace — which is why
# "5th-Seed Oklahoma Christian" loses the seed and keeps the school, and why
# the bare "rv" alternative does not bite Rverside. What leads an opponent
# string far more often than a rank is an all-caps abbreviation: UT Tyler at
# 127 rows, MSU Denver at 17, CSU Pueblo and USC Aiken behind them. None of
# those match.
_RANK_VALUE = r"(?:rv|\d{1,2})"
_RANK_TOKEN = (
    r"(?:"
    rf"\(\s*{_RANK_VALUE}\s*\)|\[\s*{_RANK_VALUE}\s*\]"
    r"|(?:#|no\.?)?\s*\d{1,2}(?:st|nd|rd|th)?[-\s]seed"
    rf"|(?:#|no\.?)?\s*{_RANK_VALUE}"
    r")"
)
_RANK_PREFIX = re.compile(
    rf"^(?:{_RANK_TOKEN}(?:\s*/\s*{_RANK_TOKEN})*\s+)+", re.IGNORECASE
)


def _clean_team_name(name: object) -> str:
    return _RANK_PREFIX.sub("", str(name or "").strip())


def _identity_key(name: str) -> str:
    """Normalize a published opponent string toward a comparable identity.

    The parenthetical is dropped because sites use it for two different things
    and neither belongs in an institution's identity: a disambiguating region
    ("Rogers State University (Okla.)") and a match-type annotation ("Oklahoma
    Wesleyan (Exhibition)").

    "St." is two different words and position tells them apart. Trailing, it
    abbreviates State ("Northeastern St."); before another word it abbreviates
    Saint ("St. Edward's", "Missouri-St. Louis"). Expanding it to State
    unconditionally corrupted every Saint school in the archive, and the Lone
    Star Conference alone brings two more.
    """
    text = _clean_team_name(name).lower().replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"\bst\.?\s*$", " state", text)
    text = re.sub(r"\b(?:st\.\s*|st\s+)(?=[a-z])", "saint ", text)
    text = re.sub(r"\buniv(?:ersity)?\b|\bcollege\b|\bthe\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def identity_aliases(
    schools: list[SchoolConfig], gender: str | None = None
) -> dict[str, str]:
    """Build the identity map for ONE gender's collection.

    Gender scoping is not optional. Opponent strings carry no gender, so an
    unscoped map lets a men's fixture resolve to a women's-only programme —
    measured: "Southwestern" on a men's schedule resolved to Southwestern
    Oklahoma State, which fields no men's soccer. The platform audit found the
    same class of error at 103 rows when the historical derivation ran
    gender-blind.
    """
    aliases: dict[str, str] = {}
    for school in schools:
        if gender is not None and school.gender != gender:
            continue
        slug = programme_slug(school.name)
        for candidate in (
            school.name,
            school.display_name,
            school.abbreviation,
            *school.aliases,
        ):
            key = _identity_key(candidate)
            if key:
                aliases[key] = slug
    return aliases


def conference_members(
    schools: list[SchoolConfig], gender: str, conference: str
) -> set[str]:
    """Programme slugs belonging to ONE conference, for the conference-game test.

    Deliberately a different set from ``identity_aliases``.  That map should span
    every configured school, because an out-of-conference opponent still deserves
    a canonical slug.  Membership must not: deriving it from the whole alias map
    marks a cross-conference fixture as a conference game, which is correct only
    while exactly one conference is configured.

    Scoped to the conference rather than to the run's requested programmes, since
    a fixture against a member we did not happen to collect is still a conference
    game.
    """
    return {
        programme_slug(school.name)
        for school in schools
        if school.gender == gender and school.conference == conference
    }


def opponent_slug(name: str, aliases: dict[str, str]) -> str:
    """Resolve a published opponent string to a stable identity, or record it.

    The fallback is deliberately conservative. A bare substring test treats a
    PREFIX as an identity — "Southwestern" sits inside "southwestern oklahoma
    state" — so the rule is instead that every token of a configured school's
    name must appear in the published string, and that school must be the only
    such match. A one-token alias is never enough on its own, because a bare
    surname-like token matches far too much.

    When nothing resolves, the normalized key becomes the slug rather than the
    raw string. That alone folds "Delta St." onto "Delta State" and "Oklahoma
    Christian University" onto "Oklahoma Christian". Genuinely opaque
    abbreviations such as "DBU" still stand apart from "Dallas Baptist": no
    algorithm should guess that, and guessing is what produced the defect above.
    """
    key = _identity_key(name)
    if not key:
        return programme_slug(_clean_team_name(name))
    if key in aliases:
        return aliases[key]

    published = set(key.split())
    candidates = {
        slug
        for alias, slug in aliases.items()
        if len(alias.split()) >= 2 and set(alias.split()) <= published
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    return programme_slug(key)


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_status(event: dict[str, object]) -> str:
    result = event.get("result")
    result_dict = result if isinstance(result, dict) else {}
    status = str(result_dict.get("status") or event.get("status") or "").lower()
    if "cancel" in status:
        return "cancelled"
    if "postpon" in status:
        return "postponed"
    if event.get("type") == "live" or "live" in status or "progress" in status:
        return "live"
    # A status naming Final outranks the score check: a played game whose
    # score was never entered (measured on exhibitions) is final, and calling
    # it scheduled makes the board show a finished game as upcoming.
    if "final" in status:
        return "final"
    if (
        _integer(result_dict.get("team_score")) is not None
        and _integer(result_dict.get("opponent_score")) is not None
    ):
        return "final"
    return "scheduled"


_DOM_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _dom_date(text: str, year: int) -> str | None:
    """Resolve a rendered date like ``Aug 13 (Thu)`` against the season year.

    The rendered date carries no year, and a fall season can finish in the
    following spring — the COVID 2020 season was played into spring 2021 —
    so January–June belongs to the calendar year after the season's.
    """
    match = re.search(r"([A-Za-z]{3})[a-z.]*\s+(\d{1,2})", text)
    if not match:
        return None
    month = _DOM_MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    if month < 7:
        year += 1
    return f"{year:04d}-{month:02d}-{int(match.group(2)):02d}"


def _dom_time(text: str) -> str | None:
    """Parse rendered kickoff text: ``7:00 p.m.``, ``3 PM``, ``Noon``, ``TBD``."""
    cleaned = text.strip().lower()
    if "noon" in cleaned:
        return "12:00"
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b", cleaned)
    if not match:
        return None
    hour = int(match.group(1)) % 12
    if match.group(3) == "p":
        hour += 12
    return f"{hour:02d}:{int(match.group(2) or 0):02d}"


def _dom_result(text: str) -> tuple[str, int, int] | None:
    """Parse a result like ``W, 2-0`` or ``T, 1-1 (2OT)`` as it is printed.

    The two numbers are returned in PAGE ORDER, which is not an orientation:
    ``_oriented_scores`` decides which is the owner's. See it for why.
    """
    match = re.search(r"\b([WLT])\s*,?\s*(\d+)\s*-\s*(\d+)", text)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def _oriented_scores(
    letter: str | None, first: int, second: int, *, fixture_id: str
) -> tuple[int, int] | None:
    """The owner's score and the other side's, in that order, or nothing.

    Sites do not agree on which number comes first. Most print the owner's
    score first ("L, 0-1" on a schedule the owner lost 0-1); oceagles.com
    prints the winner's first ("L, 3-2" for a match Oklahoma Christian lost
    2-3, verified on the live 2025 schedule 2026-09-02). Trusting the order
    stored twenty of Oklahoma Christian's results reversed, and the box-score
    orienter, matching scores to the reversed fixture, put home_index on the
    wrong side so the two errors cancelled on every surface (tl-b39).

    The letter is the only orientation the page actually publishes, so it
    wins: W means the owner scored more, L less, T the same. A pair the
    letter contradicts is swapped and the swap is logged by fixture id; a T
    beside unequal numbers, or a letter this function does not know, cannot
    be put right by swapping and is refused — the row keeps its status and
    stores no score, which the coverage and twin checks name rather than a
    reversed result nothing would catch.
    """
    if letter == "W":
        if first > second:
            return first, second
        if second > first:
            _LOG.warning(
                "%s: W printed %s-%s; stored owner %s-%s",
                fixture_id,
                first,
                second,
                second,
                first,
            )
            return second, first
    elif letter == "L":
        if first < second:
            return first, second
        if second < first:
            _LOG.warning(
                "%s: L printed %s-%s; stored owner %s-%s",
                fixture_id,
                first,
                second,
                second,
                first,
            )
            return second, first
    elif letter == "T" and first == second:
        return first, second
    _LOG.warning(
        "%s: result letter %r contradicts %s-%s and no swap can honour it; scores refused",
        fixture_id,
        letter,
        first,
        second,
    )
    return None


# Sites publish the marker in two places: the opponent's own title
# ("Oklahoma Wesleyan (Exhibition)") or the schedule row's location text
# (measured: "Friendly" beside "Tulsa, Okla." on goriverhawksgo.com 2026).
# Word boundaries keep "Friends University" from reading as a friendly.
_EXHIBITION_MARKER = re.compile(r"\bexhib|\bfriendl(?:y|ies)\b", re.IGNORECASE)


def _exhibition_marked(*texts: str) -> bool:
    return any(_EXHIBITION_MARKER.search(text) for text in texts)


def _parse_schedule_dom(
    html: str,
    *,
    page_url: str,
    year: int,
    owner_slug: str,
    aliases: dict[str, str],
    members: set[str] | None = None,
) -> list[dict[str, object]]:
    """Read the server-rendered game list.

    Emits the same fixture shape and the same ``sidearm:{owner}:{game-id}``
    identifiers as the component-JSON path, so the two sources merge by id.

    The conference flag is evidence-tiered.  Some themes render a conference
    marker per game and their word is taken as published truth; some render no
    marker anywhere (measured: two of six themes in one conference), and there
    the flag is derived from configured membership — both sides configured for
    this collection and the game not an exhibition — and stamped
    ``conference_game_source: derived:membership`` so no derived value can
    masquerade as a publisher's claim.  Membership means one conference's member
    list, resolved from configuration, never a conference named in code — and
    never the whole configured school list, which silently marks a GAC-versus-LSC
    fixture as a conference game the moment a second conference is configured.
    """
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("li.sidearm-schedule-game")

    def conference_marked(row: object) -> bool:
        """A theme marks conference games with text ("GAC") or a bare logo.

        Measured: one site renders only ``<img alt="Great American Conference">``
        inside the conference cell — no text — so text alone under-detects.
        """
        marker = row.select_one(".sidearm-schedule-game-conference")  # type: ignore[attr-defined]
        if marker is None:
            return False
        return bool(marker.get_text(strip=True)) or marker.select_one("img") is not None

    theme_marks_conference = any(conference_marked(row) for row in rows)
    # Falling back to the whole alias map preserves single-conference behaviour
    # for callers that have no member list to give, which is every test fixture
    # and nothing on the collection path.
    member_slugs = set(aliases.values()) if members is None else members

    fixtures: list[dict[str, object]] = []
    for row in rows:
        game_id = str(row.get("data-game-id") or "").strip()
        opponent_raw = _first_text(row, ".sidearm-schedule-game-opponent-name") or ""
        opponent_name = _clean_team_name(opponent_raw)
        date = _dom_date(
            _first_text(row, ".sidearm-schedule-game-opponent-date") or "", year
        )
        if not game_id or not opponent_name or not date:
            continue
        # Postseason structure rows are events, not fixtures: "TBA" hotel
        # blocks and "NCAA Tournament First and Second Rounds" carry no
        # opponent, and their date is a range.  Real matches from those rounds
        # arrive later with actual opponents.
        if re.fullmatch(r"tbd|tba", opponent_name, re.IGNORECASE) or re.search(
            r"tournament|championship", opponent_name, re.IGNORECASE
        ):
            continue
        classes = set(row.get("class") or [])
        # The theme's own word for a neutral site is a row class (measured:
        # "sidearm-schedule-neutral-game" on goriverhawksgo.com 2022 game
        # 12745, Maryville at "Springfield, Mo."; mckbearcats.com 2025 game
        # 19843 at "Creve Coeur, Mo."). Both twins of such a game name a
        # different home side, so the fold on the site had only their
        # disagreement to go on; the flag is that first-hand source.
        neutral = "sidearm-schedule-neutral-game" in classes
        location = row.select_one(".sidearm-schedule-game-location")
        location_text = (
            location.get_text(" ", strip=True) if location is not None else ""
        )
        exhibition = _exhibition_marked(opponent_raw, location_text)
        hosted = re.split(r"\s+vs\.?\s+", opponent_name)
        if len(hosted) == 2:
            # A tournament host lists other teams' games on its own schedule
            # ("Southern Nazarene vs. Maryville" on the host's page).  That is
            # a real fixture between the two named teams at the host's venue —
            # the owner is not in it.
            home = opponent_slug(hosted[0], aliases)
            away = opponent_slug(hosted[1], aliases)
            owner_is_home = None
            participant_slugs = (home, away)
        else:
            other_slug = opponent_slug(opponent_name, aliases)
            if neutral:
                # Neutral rows keep the "vs"/"at" span as the only side
                # indicator; home/away stay as published, the flag says
                # neither side hosted.
                indicator = _first_text(
                    row, ".sidearm-schedule-game-home, .sidearm-schedule-game-away"
                )
                owner_is_home = (indicator or "vs").strip().lower() != "at"
            else:
                owner_is_home = "sidearm-schedule-home-game" in classes
            home, away = (
                (owner_slug, other_slug) if owner_is_home else (other_slug, owner_slug)
            )
            participant_slugs = (other_slug,)

        result_text = _first_text(row, ".sidearm-schedule-game-result") or ""
        result = _dom_result(result_text) if owner_is_home is not None else None
        # A played game whose score was never entered (measured on the modern
        # theme, which fills scores client-side: the served DOM carries only a
        # completed class on the row and a Final span whose class the result
        # selector does not match) is final, not scheduled — leaving it
        # scheduled makes the board show a finished game as upcoming.
        completed = (
            "sidearm-schedule-game-completed" in classes
            or row.select_one(".sidearm-schedule-game-result-final") is not None  # type: ignore[attr-defined]
        )
        if re.search(r"cancel", result_text, re.IGNORECASE):
            status = "cancelled"
        elif re.search(r"postpon", result_text, re.IGNORECASE):
            status = "postponed"
        elif result or completed:
            status = "final"
        else:
            status = "scheduled"

        fixture: dict[str, object] = {
            "id": f"sidearm:{owner_slug}:{game_id}",
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
            fixture["conference_game"] = not exhibition and all(
                slug in member_slugs for slug in participant_slugs
            )
            fixture["conference_game_source"] = "derived:membership"
        # Some themes render kickoff in a dedicated element; at least one packs
        # it into the date text ("Aug 27 (Thu) 3:00 p.m.").
        time = _dom_time(
            _first_text(row, ".sidearm-schedule-game-time") or ""
        ) or _dom_time(_first_text(row, ".sidearm-schedule-game-opponent-date") or "")
        if time:
            fixture["time"] = time
        if location is not None:
            # measured: the "Friendly" marker rides in a distinct child node
            # (div.sidearm-schedule-game-opponent-promotion) inside the
            # location element, which get_text flattened into a stored venue
            # of "Tulsa, Okla. Friendly". A promotion is never the venue.
            for promo in location.select(".sidearm-schedule-game-opponent-promotion"):
                promo.extract()
            facility = location.select_one("a")
            venue = (
                facility.get_text(" ", strip=True)
                if facility is not None
                else location.get_text(" ", strip=True)
            )
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
    return fixtures


def parse_schedule_page(
    html: str,
    *,
    page_url: str,
    year: int,
    owner_slug: str,
    aliases: dict[str, str],
    members: set[str] | None = None,
) -> list[dict[str, object]]:
    events: dict[str, dict[str, object]] = {}
    for component in _component_objects(html):
        if component.get("type") != "events":
            continue
        data = component.get("data")
        if not isinstance(data, list):
            continue
        for raw in data:
            if not isinstance(raw, dict):
                continue
            schedule = raw.get("schedule")
            schedule_dict = schedule if isinstance(schedule, dict) else {}
            title = str(schedule_dict.get("title") or "")
            date = str(raw.get("date") or "")
            if not re.search(rf"\b{year}\b", title) or not date.startswith(str(year)):
                continue
            event_id = str(raw.get("id") or "")
            if event_id:
                events[event_id] = raw

    fixtures: list[dict[str, object]] = []
    for event_id, event in events.items():
        opponent = event.get("opponent")
        opponent_dict = opponent if isinstance(opponent, dict) else {}
        published_title = str(
            opponent_dict.get("title") or opponent_dict.get("name") or ""
        )
        opponent_name = _clean_team_name(published_title)
        if not opponent_name:
            continue
        other_slug = opponent_slug(opponent_name, aliases)
        indicator = str(event.get("location_indicator") or "").upper()
        owner_is_home = indicator == "H" or (
            indicator == "N" and bool(event.get("neutral_hometeam"))
        )
        home, away = (
            (owner_slug, other_slug) if owner_is_home else (other_slug, owner_slug)
        )
        result = event.get("result")
        result_dict = result if isinstance(result, dict) else {}
        team_score = _integer(result_dict.get("team_score"))
        opponent_score = _integer(result_dict.get("opponent_score"))
        status = _event_status(event)
        date_text = str(event.get("date"))
        fixture: dict[str, object] = {
            "id": f"sidearm:{owner_slug}:{event_id}",
            "date": date_text[:10],
            "home": home,
            "away": away,
            "status": status,
            "conference_game": bool(event.get("is_conference")),
            "source_url": page_url,
        }
        # The payload's word for a neutral site is the indicator itself
        # (measured: "location_indicator":"N" with "neutral_hometeam":true,
        # Maryville University at "Claremore, OK" in the snuathletics.com
        # events component). Same flag as the DOM path, same meaning.
        if indicator == "N":
            fixture["neutral"] = True
        facility = event.get("game_facility")
        facility_dict = facility if isinstance(facility, dict) else {}
        venue = str(facility_dict.get("title") or event.get("location") or "").strip()
        # The payload has no exhibition field — the site says it in the
        # opponent's own published title ("Oklahoma Wesleyan (Exhibition)")
        # or beside the venue in its location text ("Tulsa, Okla. Friendly").
        if _exhibition_marked(published_title, venue):
            fixture["match_type"] = "exhibition"
        if not event.get("tbd") and "T" in date_text:
            try:
                local = datetime.fromisoformat(date_text)
                fixture["time"] = local.strftime("%H:%M")
            except ValueError:
                pass
        if venue:
            fixture["venue"] = venue
        if (
            status in {"final", "live"}
            and team_score is not None
            and opponent_score is not None
        ):
            # The payload names the fields team_score / opponent_score, and
            # the same site that prints the winner first in the DOM fills
            # them the same way. The letter (result.status) decides, as in
            # the DOM path; a live match carries no letter yet and is taken
            # as filled.
            letter = str(result_dict.get("status") or "").strip().upper() or None
            oriented = (
                (team_score, opponent_score)
                if status == "live" and letter is None
                else _oriented_scores(
                    letter, team_score, opponent_score, fixture_id=str(fixture["id"])
                )
            )
            if oriented:
                team_score, opponent_score = oriented
                if owner_is_home:
                    fixture["home_score"], fixture["away_score"] = (
                        team_score,
                        opponent_score,
                    )
                else:
                    fixture["home_score"], fixture["away_score"] = (
                        opponent_score,
                        team_score,
                    )
        fixtures.append(fixture)

    # The component JSON is authoritative where it speaks; the DOM supplies
    # every game the JSON stub left out, under the same identifiers.
    json_ids = {str(fixture["id"]) for fixture in fixtures}
    for fixture in _parse_schedule_dom(
        html,
        page_url=page_url,
        year=year,
        owner_slug=owner_slug,
        aliases=aliases,
        members=members,
    ):
        if str(fixture["id"]) not in json_ids:
            fixtures.append(fixture)
    return sorted(fixtures, key=lambda value: (str(value["date"]), str(value["id"])))


def _first_text(node: object, selector: str) -> str | None:
    found = node.select_one(selector)  # type: ignore[attr-defined]
    if found is None:
        return None
    text = found.get_text(" ", strip=True)
    return text or None


def parse_roster_page(html: str, *, page_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    players: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in soup.select("li.sidearm-roster-player"):
        player_path = str(row.get("data-player-url") or "")
        player_id = str(row.get("data-player-id") or player_path)
        if not player_id or player_id in seen:
            continue
        name = _first_text(row, ".sidearm-roster-player-name a")
        if not name:
            continue
        seen.add(player_id)
        player: dict[str, str] = {"name": name}
        fields = {
            "number": ".sidearm-roster-player-jersey-number",
            "position": ".sidearm-roster-player-position-long-short.hide-on-small-down",
            "height": ".sidearm-roster-player-height",
            "weight": ".sidearm-roster-player-weight",
            "hometown": ".sidearm-roster-player-hometown",
        }
        for field, selector in fields.items():
            value = _first_text(row, selector)
            if value:
                player[field] = value
        if "position" not in player:
            # Themes without the long-short span pack everything into one
            # container: "D 5'11\" 165 lbs".  Peel height and weight off the
            # blob (keeping any dedicated-element value), and what remains is
            # the published position abbreviation.
            blob = _first_text(row, ".sidearm-roster-player-position") or ""
            height = re.search(r"\d+'\s*\d+(?:\.\d+)?\"", blob)
            if height and "height" not in player:
                player["height"] = re.sub(r"'\s+", "'", height.group(0))
            weight = re.search(r"(\d+)\s*lbs\b", blob)
            if weight and "weight" not in player:
                player["weight"] = f"{weight.group(1)} lbs"
            position = blob
            for token in (height, weight):
                if token:
                    position = position.replace(token.group(0), " ")
            position = " ".join(position.split()).strip()
            if position:
                player["position"] = position
        class_values = [
            element.get_text(" ", strip=True)
            for element in row.select(".sidearm-roster-player-academic-year")
            if element.get_text(" ", strip=True)
        ]
        if class_values:
            player["class_year"] = max(class_values, key=len)
        if player_path:
            player["source_url"] = urljoin(page_url, player_path)
        players.append(player)
    return players


def _stat_int(text: str) -> int | None:
    text = text.strip()
    if not text or text in {"-", "–"}:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _stat_float(text: str) -> float | None:
    text = text.strip().rstrip("%")
    if not text or text in {"-", "–"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _stat_minutes(text: str) -> int | None:
    """Minutes as printed: outfield rows are plain ("1753"), keeper rows carry
    seconds ("956:15"). Whole minutes are enough for anything downstream."""
    match = re.fullmatch(r"(\d+)(?::\d{2})?", text.strip())
    return int(match.group(1)) if match else None


def _stat_pair(text: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _stats_player_name(published: str) -> str:
    """Flip the stats page's "Last, First" to the roster's "First Last"."""
    head, _, tail = published.partition(",")
    return (
        f"{tail.strip()} {head.strip()}".strip() if tail.strip() else published.strip()
    )


def parse_stats_page(
    html: str, *, page_url: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Read the two individual tables off a cumulative-statistics page.

    Measured 2026-08-10 across seven sites and seasons back to 2016: every
    ``/stats/{year}`` page server-renders an "Individual Overall Offensive
    Statistics" and an "Individual Overall Goalkeeping Statistics" table, each
    stat cell labelled with ``data-label``, each player row anchored by
    ``a[data-player-id]`` — and the Total/Opponents footer rows carry no such
    anchor, which is what keeps them out.  Unlike schedules there is no payload
    trap: the pages are honest per year on every site, including the two whose
    schedule pages canonicalise the COVID season.
    """
    soup = BeautifulSoup(html, "lxml")

    def rows_of(caption: str) -> list[dict[str, object]]:
        for table in soup.find_all("table"):
            found = table.find("caption")
            if found is None or found.get_text(strip=True) != caption:
                continue
            out: list[dict[str, object]] = []
            seen: set[str] = set()
            for row in table.find_all("tr"):
                anchor = row.find("a", attrs={"data-player-id": True})
                if anchor is None:
                    continue
                player_id = str(anchor.get("data-player-id") or "").strip()
                name = _stats_player_name(anchor.get_text(" ", strip=True))
                if not name or player_id in seen:
                    continue
                seen.add(player_id)
                cells = {
                    str(cell.get("data-label")): cell.get_text(" ", strip=True)
                    for cell in row.find_all("td")
                    if cell.get("data-label")
                }
                entry: dict[str, object] = {"name": name}
                if player_id:
                    entry["player_id"] = player_id
                jersey = row.find("td")
                number = jersey.get_text(strip=True) if jersey is not None else ""
                if number:
                    entry["number"] = number
                bio = row.find("a", href=re.compile(r"/roster/"))
                if bio is not None:
                    entry["bio_url"] = urljoin(page_url, str(bio["href"]))
                entry["cells"] = cells
                out.append(entry)
            return out
        return []

    def take(
        entry: dict[str, object],
        cells: dict[str, str],
        fields: dict[str, tuple[str, object]],
    ) -> None:
        for label, (field, convert) in fields.items():
            value = convert(cells.get(label, ""))
            if value is not None:
                entry[field] = value

    players: list[dict[str, object]] = []
    for raw in rows_of("Individual Overall Offensive Statistics"):
        cells = raw.pop("cells")
        take(
            raw,
            cells,  # type: ignore[arg-type]
            {
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
            },
        )
        cards = _stat_pair(cells.get("YC-RC", ""))  # type: ignore[union-attr]
        if cards:
            raw["yellow"], raw["red"] = cards
        penalties = _stat_pair(cells.get("PG-PA", ""))  # type: ignore[union-attr]
        if penalties:
            raw["penalty_goals"], raw["penalty_attempts"] = penalties
        players.append(raw)

    keepers: list[dict[str, object]] = []
    for raw in rows_of("Individual Overall Goalkeeping Statistics"):
        cells = raw.pop("cells")
        take(
            raw,
            cells,  # type: ignore[arg-type]
            {
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
                "SHO": ("shutouts", _stat_int),
                "SF": ("shots_faced", _stat_int),
            },
        )
        keepers.append(raw)

    return players, keepers


def boxscore_links(schedule_html: str, base_url: str) -> dict[str, str]:
    """Map game id → absolute box-score URL from a schedule page's own links.

    The trailing id in ``…/boxscore/<id>`` is the same game id the schedule's
    fixtures carry, so this is an exact join.  The opponent slug inside the
    URL is cosmetic — the id alone selects the match — but the served href is
    kept verbatim rather than reconstructed.
    """
    links: dict[str, str] = {}
    for match in re.finditer(r'href="([^"]*?/boxscore/(\d+))"', schedule_html):
        links.setdefault(match.group(2), urljoin(base_url, match.group(1)))
    return links


def _title_box_date(html: str) -> tuple[str | None, str]:
    title = BeautifulSoup(html, "lxml").title
    text = title.get_text(" ") if title is not None else ""
    match = re.search(r"\bon\s+(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not match:
        return None, text
    month, day, year = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}", text


def assert_served_match(
    page: PublishedPage, year: int, fixture: dict[str, object]
) -> None:
    """A box score must prove WHICH match it is, not merely which season.

    The title reads "vs <Opponent> on M/D/YYYY - Box Score" and that date must
    equal the fixture's own date.  Matching on the season year instead would
    wrongly refuse every COVID-2020 match — played in spring 2021, and titled
    so, under an honest ``/stats/2020/`` URL.
    """
    fixture_id = str(fixture.get("id", ""))
    if "/boxscore/" not in urlparse(page.final_url).path:
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: {page.requested_url} redirected to "
            f"{page.final_url}, which is not a box-score page"
        )
    # The trailing game id is the identity join, so a redirect that swaps it
    # is a different match even when the destination shares the fixture date
    # (a tournament day can put two same-day matches on one site).
    requested_game = re.search(r"/boxscore/(\d+)", urlparse(page.requested_url).path)
    served_game = re.search(r"/boxscore/(\d+)", urlparse(page.final_url).path)
    if (
        requested_game is not None
        and served_game is not None
        and requested_game.group(1) != served_game.group(1)
    ):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: requested box score {requested_game.group(1)} "
            f"but {page.final_url} served box score {served_game.group(1)}"
        )
    served_date, title_text = _title_box_date(page.html)
    if not re.search(r"box\s*score", title_text, re.I):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: {page.final_url} does not title itself a box score"
        )
    if served_date is None:
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: cannot prove which match {page.final_url} "
            f"served — its title names no match date"
        )
    if served_date != str(fixture.get("date")):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: requested the {fixture.get('date')} match "
            f"but {page.final_url} served the match of {served_date}"
        )


def _box_span_pair(node: object) -> tuple[str, str]:
    """SideArm renders team identity twice per cell: full name for wide
    viewports, abbreviation for narrow ones."""
    full = node.find("span", class_="hide-on-small-down")  # type: ignore[attr-defined]
    abbr = node.find("span", class_="hide-on-medium")  # type: ignore[attr-defined]
    return (
        full.get_text(strip=True) if full is not None else "",
        abbr.get_text(strip=True) if abbr is not None else "",
    )


# Visible header-group text → detail field.  Keyed by text, not element id:
# the SideArm template mislabels the Fouls group with id="offsides".
_TEAM_STAT_LABELS = {
    "shots": "shots",
    "saves": "saves",
    "corner kicks": "corners",
    "fouls": "fouls",
    "offsides": "offsides",
}


def _box_player_name(cell: object) -> tuple[str, str | None]:
    anchor = cell.find("a")  # type: ignore[attr-defined]
    node = anchor if anchor is not None else cell
    name = _stats_player_name(node.get_text(" ", strip=True))
    player_id = None
    if anchor is not None:
        match = re.search(r"/(\d+)/?$", str(anchor.get("href", "")))
        if match:
            player_id = match.group(1)
    return name, player_id


# Play-by-play lines are free text typed by each home stat crew, so a play is
# typed only when its wording matches a known SideArm phrasing — the raw text
# is the record, the type is an index into it.  First match wins: a penalty
# goal reads "PENALTY KICK GOAL by …" and is a goal before it is a penalty.
_PLAY_TYPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("goal", re.compile(r"\bGOAL by\b", re.I)),
    ("penalty", re.compile(r"\bPENALTY KICK\b", re.I)),
    ("shot", re.compile(r"\bShot by\b", re.I)),
    ("goalie", re.compile(r"\bat goalie for\b", re.I)),
    ("foul", re.compile(r"^Foul\b", re.I)),
    ("corner", re.compile(r"^Corner kick\b", re.I)),
    ("sub", re.compile(r"\bsubstitution\b", re.I)),
    ("offside", re.compile(r"^Offside\b", re.I)),
    ("yellow", re.compile(r"\bYellow card\b", re.I)),
    ("red", re.compile(r"\bRed card\b", re.I)),
    ("shootout", re.compile(r"^Shootout attempt\b", re.I)),
    ("lineup", re.compile(r"^FOR [A-Z].*#\d", re.I)),
    ("period", re.compile(r"^(?:Start|End) of\b", re.I)),
)


def _play_type(text: str) -> str | None:
    for name, pattern in _PLAY_TYPE_PATTERNS:
        if pattern.search(text):
            return name
    return None


def parse_boxscore_page(html: str, *, page_url: str) -> dict[str, object]:
    """Read one match's published detail off its box-score page.

    Team references (scoring summary, cautions, player-table captions) use
    whatever abbreviation the page chose — consistent within a page, not
    across pages, and sometimes truncated ("Hardin") — so every reference is
    resolved against the score-by-period table's own name/abbreviation pairs
    and stored as an index into ``teams``.
    """
    soup = BeautifulSoup(html, "lxml")

    def captioned(predicate: object) -> list[tuple[str, object]]:
        found = []
        for table in soup.find_all("table"):
            caption = table.find("caption")
            if caption is None:
                continue
            text = re.sub(r"\s+", " ", caption.get_text(strip=True))
            if predicate(text):  # type: ignore[operator]
                found.append((text, table))
        return found

    teams: list[dict[str, object]] = []
    for _, table in captioned(lambda text: text == "Team Score By Period"):
        for row in table.find_all("tr"):
            header = row.find("th", scope="row")
            if header is None:
                continue
            name, abbr = _box_span_pair(header)
            if not name and not abbr:
                continue
            cells = [
                _stat_int(cell.get_text(strip=True)) for cell in row.find_all("td")
            ]
            team: dict[str, object] = {"name": name or abbr}
            if abbr:
                team["abbr"] = abbr
            if cells and cells[-1] is not None:
                team["score"] = cells[-1]
            team["periods"] = [value for value in cells[:-1] if value is not None]
            if header.find("span", class_="boxscore-winner") is not None:
                team["winner"] = True
            teams.append(team)
        break

    def side(reference: str) -> int | None:
        text = reference.strip()
        if not text:
            return None
        for index, team in enumerate(teams):
            if text in {team.get("abbr"), team.get("name")}:
                return index
        return None

    for _, table in captioned(lambda text: text == "Team Statistics"):
        field = None
        for row in table.find_all("tr"):
            group = row.find("th", class_="header-group")
            if group is not None:
                field = _TEAM_STAT_LABELS.get(group.get_text(strip=True).lower())
                continue
            cells = row.find_all("td")
            if field is None or not cells:
                continue
            index = side(cells[0].get_text(strip=True))
            if index is None:
                continue
            total_cell = cells[-1]
            bold = total_cell.find("span", class_="text-bold")
            total = _stat_int(
                bold.get_text(strip=True)
                if bold is not None
                else total_cell.get_text(strip=True)
            )
            if total is not None:
                teams[index][field] = total
            if field == "shots":
                italic = total_cell.find("span", class_="text-italic")
                on_goal = re.search(
                    r"\((\d+)\)", italic.get_text() if italic is not None else ""
                )
                if on_goal:
                    teams[index]["sog"] = int(on_goal.group(1))
        break

    scoring: list[dict[str, object]] = []
    for _, table in captioned(lambda text: text == "Scoring Summary"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            entry: dict[str, object] = {}
            clock = cells[0].get_text(strip=True)
            if clock:
                entry["time"] = clock
            hidden = cells[1].find("span", class_="hide")
            image = cells[1].find("img")
            reference = (
                hidden.get_text(strip=True)
                if hidden is not None
                else str(image.get("alt", ""))
                if image is not None
                else cells[1].get_text(strip=True)
            )
            index = side(reference)
            if index is not None:
                entry["team"] = index
            bold = cells[2].find("span", class_="text-bold")
            scorer = bold.get_text(" ", strip=True) if bold is not None else ""
            count = re.search(r"^(.*?)\s*\((\d+)\)\s*$", scorer)
            if count:
                entry["scorer"] = count.group(1)
                entry["season_total"] = int(count.group(2))
            elif scorer:
                entry["scorer"] = scorer
            italic = cells[2].find("span", class_="text-italic")
            if italic is not None:
                assist = re.sub(
                    r"^Assisted\s+By:\s*",
                    "",
                    italic.get_text(" ", strip=True),
                    flags=re.I,
                )
                if assist:
                    entry["assist"] = assist
            described = cells[2].find("span", class_="text-capitalize")
            if described is not None:
                description = described.get_text(" ", strip=True)
                if description:
                    entry["description"] = description
            if entry.get("scorer"):
                scoring.append(entry)
        break

    cards: list[dict[str, object]] = []
    for _, table in captioned(lambda text: text == "Cautions and Ejections"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            kind_classes = set(cells[0].get("class") or [])
            kind = next(
                (value for value in ("yellow", "red") if value in kind_classes), None
            )
            player_text = cells[3].get_text(" ", strip=True)
            number = re.match(r"#(\d+)\s+(.*)", player_text)
            entry = {
                "type": kind or "unknown",
                "player": number.group(2) if number else player_text,
            }
            if number:
                entry["number"] = number.group(1)
            clock = cells[1].get_text(strip=True)
            if clock:
                entry["time"] = clock
            index = side(cells[2].get_text(strip=True))
            if index is not None:
                entry["team"] = index
            if entry["player"]:
                cards.append(entry)
        break

    # The play-by-play panel renders one table per period section, each row
    # holding the event twice: two team-attributed desktop columns and one
    # unattributed mobile cell.  Only the desktop columns are read — the
    # column an event lives in IS its team attribution, resolved through the
    # column header's abbreviation ("HAR - Play Description").  The header
    # also fixes the layout: the left column is the visiting side, sitting
    # beside the "Visiting Team Score" cell that fills in on goals.
    plays: list[dict[str, object]] = []
    panel = soup.find(id="play-by-play")
    sections = (
        panel.find_all("section", id=re.compile(r"^period-"))
        if panel is not None
        else []
    )
    for section in sections:
        period = str(section.get("id", ""))[len("period-") :]
        table = section.find("table", class_="play-by-play")
        if table is None or not period:
            continue
        abbrs: list[str] = []
        head = table.find("thead")
        for th in head.find_all("th") if head is not None else []:
            classes = set(th.get("class") or [])
            if "text-center" in classes and "hide-on-medium-down" in classes:
                abbrs.append(next(th.stripped_strings, ""))
        left = side(abbrs[0]) if len(abbrs) == 2 else None
        right = side(abbrs[1]) if len(abbrs) == 2 else None
        body = table.find("tbody")
        for row in body.find_all("tr") if body is not None else []:
            cells = [
                td
                for td in row.find_all("td")
                if "hide-on-large" not in (td.get("class") or [])
            ]
            if len(cells) != 6:
                continue
            left_text = cells[1].get_text(" ", strip=True)
            right_text = cells[5].get_text(" ", strip=True)
            text = left_text or right_text
            # A row with no letters ("*" footnote markers) narrates nothing.
            if not re.search(r"[A-Za-z]", text):
                continue
            play: dict[str, object] = {"period": period, "text": text}
            clock = cells[0].get_text(strip=True)
            if re.fullmatch(r"\d+:\d{2}", clock):
                play["clock"] = clock
            team_index = left if left_text else right
            if team_index is not None:
                play["team"] = team_index
            kind = _play_type(text)
            if kind:
                play["type"] = kind
            visiting = _stat_int(cells[2].get_text(strip=True))
            home = _stat_int(cells[4].get_text(strip=True))
            if visiting is not None and home is not None and {left, right} == {0, 1}:
                score = [0, 0]
                score[left] = visiting  # type: ignore[index]
                score[right] = home  # type: ignore[index]
                play["score"] = score
            plays.append(play)

    def match_lines(suffix: str) -> dict[int, object]:
        by_side: dict[int, object] = {}
        for text, table in captioned(
            lambda value, suffix=suffix: value.endswith(suffix)
        ):
            index = side(text[: -len(suffix)].strip())
            if index is None:
                continue
            lines: list[dict[str, object]] = []
            started: bool | None = None
            for row in table.find_all("tr"):
                group = row.find("th", class_="header-group")
                if group is not None:
                    label = group.get_text(strip=True).lower()
                    started = (
                        True
                        if label == "starters"
                        else False
                        if label == "substitutes"
                        else None
                    )
                    continue
                cells = row.find_all("td")
                labelled = {
                    str(cell.get("data-label")): cell.get_text(" ", strip=True)
                    for cell in cells
                    if cell.get("data-label")
                }
                name_cell = next(
                    (
                        cell
                        for cell in cells
                        if not cell.get("data-label") and cell.find("a") is not None
                    ),
                    None,
                )
                if name_cell is None:
                    name_cell = next(
                        (
                            cell
                            for cell in cells
                            if not cell.get("data-label")
                            and re.search(r"[A-Za-z]{2}", cell.get_text(strip=True))
                            and "hide-on-small-down" not in (cell.get("class") or [])
                        ),
                        None,
                    )
                if not labelled or name_cell is None:
                    continue
                jersey = name_cell.find("span", class_="mobile-jersey-number")
                if jersey is not None:
                    jersey.extract()
                name, player_id = _box_player_name(name_cell)
                # Footer rows ("Totals", "TM Team") carry data-labelled cells
                # too; only real people belong in a match line.
                if not name or name.lower() in {
                    "totals",
                    "team",
                    "tm",
                    "tm team",
                    "team tm",
                }:
                    continue
                line: dict[str, object] = {"name": name}
                if player_id:
                    line["player_id"] = player_id
                plain = [
                    cell.get_text(strip=True)
                    for cell in cells
                    if not cell.get("data-label") and cell is not name_cell
                ]
                position = next(
                    (value for value in plain if re.fullmatch(r"[A-Za-z]{1,3}", value)),
                    None,
                )
                number = next(
                    (value for value in plain if re.fullmatch(r"\d{1,3}", value)), None
                )
                if position:
                    line["position"] = position
                if number:
                    line["number"] = number
                if started is not None:
                    line["started"] = started
                for label, (field, convert) in (
                    {
                        "SH": ("shots", _stat_int),
                        "SOG": ("sog", _stat_int),
                        "G": ("goals", _stat_int),
                        "A": ("assists", _stat_int),
                        "MIN": ("minutes", _stat_minutes),
                        "Mins.": ("minutes", _stat_minutes),
                        "GA": ("goals_against", _stat_int),
                        "S": ("saves", _stat_int),
                    }
                ).items():
                    value = convert(labelled.get(label, ""))
                    if value is not None:
                        line[field] = value
                lines.append(line)
            by_side[index] = lines
        return by_side

    for index, lines in match_lines(" - Player Stats").items():
        teams[index]["players"] = lines
    for index, lines in match_lines(" - Goalie Statistics").items():
        teams[index]["keepers"] = lines

    detail: dict[str, object] = {"source_url": page_url, "teams": teams}
    if scoring:
        detail["scoring"] = scoring
    if cards:
        detail["cards"] = cards
    if plays:
        detail["plays"] = plays

    for block in soup.find_all("dl"):
        entries: dict[str, list[str]] = {}
        key = None
        for child in block.find_all(["dt", "dd"]):
            if child.name == "dt":
                key = child.get_text(strip=True).rstrip(":").lower()
                entries.setdefault(key, [])
            elif key is not None:
                entries[key].append(child.get_text(" ", strip=True))
        if "stadium" not in entries and "attendance" not in entries:
            continue
        stadium = next(iter(entries.get("stadium", [])), "")
        if stadium:
            detail["stadium"] = stadium
        attendance = _stat_int(next(iter(entries.get("attendance", [])), ""))
        if attendance is not None:
            detail["attendance"] = attendance
        kickoff = next(iter(entries.get("time", [])), "")
        if kickoff:
            detail["kickoff"] = kickoff
        officials = [value for value in entries.get("officials", []) if ":" in value]
        if officials:
            detail["officials"] = officials
        break

    return detail


def _name_slug_affinity(name: str, slug: str) -> int:
    """How strongly a served team name resembles a fixture slug, by token
    overlap with prefix credit — "Northeastern St." must beat "Harding" for
    the slug ``northeastern-state``."""
    name_tokens = re.findall(r"[a-z0-9]+", name.lower())
    slug_tokens = [token for token in slug.split("-") if token]
    score = 0
    for left in name_tokens:
        for right in slug_tokens:
            if left == right:
                score += 2
            elif left.startswith(right) or right.startswith(left):
                score += 1
    return score


def orient_match(detail: dict[str, object], fixture: dict[str, object]) -> None:
    """Record which served side is the fixture's home team, when provable.

    A decided match orients by score; a draw falls back to name affinity
    against the fixture's own slugs.  When neither is conclusive the match
    stays unoriented — the served order still renders honestly.
    """
    teams = detail.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        return
    home_score = fixture.get("home_score")
    away_score = fixture.get("away_score")
    first, second = (team.get("score") for team in teams)
    if (
        isinstance(home_score, int)
        and isinstance(away_score, int)
        and home_score != away_score
        and first is not None
        and second is not None
    ):
        if (first, second) == (home_score, away_score):
            detail["home_index"] = 0
        elif (first, second) == (away_score, home_score):
            detail["home_index"] = 1
        return
    home_slug, away_slug = str(fixture.get("home", "")), str(fixture.get("away", ""))
    straight = _name_slug_affinity(
        str(teams[0].get("name", "")), home_slug
    ) + _name_slug_affinity(str(teams[1].get("name", "")), away_slug)
    crossed = _name_slug_affinity(
        str(teams[0].get("name", "")), away_slug
    ) + _name_slug_affinity(str(teams[1].get("name", "")), home_slug)
    if straight > crossed:
        detail["home_index"] = 0
    elif crossed > straight:
        detail["home_index"] = 1


def collect_match(
    session: requests.Session,
    url: str,
    year: int,
    fixture: dict[str, object],
) -> dict[str, object]:
    """Fetch one fixture's box score, prove it is that fixture's, and parse it."""
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LiveCollectionError(
            f"[{year}] {fixture.get('id')}: failed to fetch box score {url}: {exc}"
        ) from exc
    page = PublishedPage(url, response.url, response.text)
    assert_served_match(page, year, fixture)
    detail = parse_boxscore_page(response.text, page_url=response.url)
    teams = detail.get("teams") or []
    if len(teams) != 2:  # type: ignore[arg-type]
        raise LiveCollectionError(
            f"[{year}] {fixture.get('id')}: {response.url} proved its match but "
            f"its score-by-period table rendered {len(teams)} team(s) "  # type: ignore[arg-type]
            f"where a match needs exactly two"
        )
    orient_match(detail, fixture)
    return detail


def parse_fingerprint(*inputs: object) -> str:
    """The identity of a parse: what, besides the page's bytes, shapes output.

    A cached parse is only reusable while the function that produced it and
    every configured input it read are unchanged.  The parser's own source is
    hashed rather than hand-versioned — a hand-bumped constant is exactly the
    kind of thing a parser bugfix forgets, and forgetting it would silently
    serve the old parse of an unchanged page.  Callers append the inputs that
    steer their parse (the identity aliases and conference membership for a
    schedule; the season year everywhere, since date resolution depends on
    it), so a schools.toml edit invalidates cached parses without costing a
    single extra fetch — the archived bytes are simply read again.
    """
    digest = hashlib.sha256(Path(__file__).read_bytes())
    for value in inputs:
        digest.update(b"\x00")
        digest.update(json.dumps(value, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


def collect_programme(
    school: SchoolConfig,
    year: int,
    aliases: dict[str, str],
    session: requests.Session | None = None,
    layers: Sequence[str] = DEFAULT_LAYERS,
    members: set[str] | None = None,
    page_cache: PageStateStore | None = None,
) -> ProgrammeCollection:
    """Collect the requested layers, each standing or falling on its own.

    Layer independence is the point.  Each layer is served or refused per
    (site, season) — a site can hold a full schedule archive and no roster for
    a year, or refuse one COVID season while serving every neighbour — so a
    collector that fails the whole programme when one layer fails discards the
    layers that worked.

    With a ``page_cache``, each fetch first asks whether the page changed at
    all: an unchanged page (a 304, or byte-identical content) reuses the
    cached parse output and marks its outcome ``unchanged`` instead of
    re-parsing, and a page whose bytes are current but whose cached parse is
    stale (parser or identity config changed) is re-parsed from the archive
    without another transfer of the body.
    """
    slug = programme_slug(school.name)
    wanted = tuple(layers)
    platform = school.live_collector()
    if platform not in LIVE_COLLECTORS:
        reason = (
            f"{school.name} {school.gender}: no live collector for platform "
            f"'{platform}' — the '{platform}' recipe is not implemented"
        )
        return ProgrammeCollection(
            slug=slug,
            name=school.name,
            fixtures=[],
            players=[],
            outcomes={
                layer: LayerOutcome(layer, STATE_NO_COLLECTOR, reason=reason)
                for layer in wanted
            },
        )

    outcomes: dict[str, LayerOutcome] = {}
    fixtures: list[dict[str, object]] = []
    players: list[dict[str, str]] = []
    stat_players: list[dict[str, object]] = []
    stat_keepers: list[dict[str, object]] = []
    schedule_html = ""
    roster_html = ""
    stats_html = ""
    schedule_url = ""
    roster_url = ""
    stats_url = ""

    base_url = school.live_sport_url()
    if not base_url:
        reason = f"{school.name} {school.gender} has no live schedule/roster recipe"
        return ProgrammeCollection(
            slug=slug,
            name=school.name,
            fixtures=[],
            players=[],
            outcomes={
                layer: LayerOutcome(layer, STATE_UNAVAILABLE, reason=reason)
                for layer in wanted
            },
        )

    client = session or build_session()

    if LAYER_SCHEDULE in wanted:
        schedule_url = f"{base_url}/schedule/{year}"
        # The schedule parse reads more than the page: opponent identity comes
        # from the alias map and the conference flag from membership, so both
        # belong to the cached parse's identity.
        fingerprint = parse_fingerprint(
            year, aliases, sorted(members) if members is not None else None
        )
        state = (
            page_cache.load(slug, LAYER_SCHEDULE, fingerprint) if page_cache else None
        )
        try:
            fetched = fetch_published_page_conditional(
                client,
                base_url,
                year,
                LAYER_SCHEDULE,
                state=state,
                want_validators=page_cache is not None,
            )
            if fetched.unchanged and state is not None and page_cache is not None:
                schedule_url = state.final_url
                # The archived bytes still stand, and downstream consumers
                # (box-score link extraction) read them without a parse.
                schedule_html = state.read_html()
                if state.parsed is not None:
                    fixtures = list(state.parsed.get("fixtures") or [])  # type: ignore[arg-type]
                    outcomes[LAYER_SCHEDULE] = LayerOutcome(
                        LAYER_SCHEDULE,
                        state.outcome_state,
                        count=state.outcome_count,
                        reason=state.outcome_reason,
                        source_url=state.final_url,
                        unchanged=True,
                    )
                    page_cache.mark_verified(
                        slug,
                        LAYER_SCHEDULE,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                    )
                else:
                    # Unchanged page, stale parse: read the archive again.
                    fixtures = parse_schedule_page(
                        schedule_html,
                        page_url=state.final_url,
                        year=year,
                        owner_slug=slug,
                        aliases=aliases,
                        members=members,
                    )
                    outcomes[LAYER_SCHEDULE] = LayerOutcome(
                        LAYER_SCHEDULE,
                        STATE_COMPLETE if fixtures else STATE_EMPTY,
                        count=len(fixtures),
                        reason=None
                        if fixtures
                        else f"[{year}] the {year} schedule page proved its season but listed no fixtures",
                        source_url=state.final_url,
                        unchanged=True,
                    )
                    page_cache.mark_verified(
                        slug,
                        LAYER_SCHEDULE,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                        fingerprint=fingerprint,
                        outcome_state=outcomes[LAYER_SCHEDULE].state,
                        outcome_count=len(fixtures),
                        outcome_reason=outcomes[LAYER_SCHEDULE].reason,
                        parsed={"fixtures": fixtures},
                    )
            else:
                page = fetched.page
                assert page is not None
                schedule_html = page.html
                schedule_url = page.final_url
                fixtures = parse_schedule_page(
                    page.html,
                    page_url=page.final_url,
                    year=year,
                    owner_slug=slug,
                    aliases=aliases,
                    members=members,
                )
                assert_untrapped_schedule(
                    page.html, year, page.final_url, fixtures, slug
                )
                if not fixtures and not _has_schedule_markup(page.html):
                    raise LiveCollectionError(
                        f"[{year}] {page.final_url} published no schedule payload "
                        f"and no rendered games — either the season is not "
                        f"released yet or the page is not SideArm"
                    )
                outcomes[LAYER_SCHEDULE] = LayerOutcome(
                    LAYER_SCHEDULE,
                    STATE_COMPLETE if fixtures else STATE_EMPTY,
                    count=len(fixtures),
                    reason=None
                    if fixtures
                    else f"[{year}] the {year} schedule page proved its season but listed no fixtures",
                    source_url=page.final_url,
                )
                if page_cache is not None and fetched.signature is not None:
                    page_cache.save(
                        slug,
                        LAYER_SCHEDULE,
                        requested_url=page.requested_url,
                        final_url=page.final_url,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                        signature=fetched.signature,
                        fingerprint=fingerprint,
                        outcome_state=outcomes[LAYER_SCHEDULE].state,
                        outcome_count=len(fixtures),
                        outcome_reason=outcomes[LAYER_SCHEDULE].reason,
                        parsed={"fixtures": fixtures},
                    )
        except (LiveCollectionError, OSError) as exc:
            outcomes[LAYER_SCHEDULE] = LayerOutcome(
                LAYER_SCHEDULE,
                STATE_UNAVAILABLE,
                reason=str(exc),
                source_url=schedule_url,
            )
            if page_cache is not None and schedule_html:
                # The refused page's bytes will overwrite the archive, so a
                # sidecar describing the previous good page would lie.
                page_cache.invalidate(slug, LAYER_SCHEDULE)

    if LAYER_ROSTER in wanted:
        roster_url = f"{base_url}/roster/{year}"
        fingerprint = parse_fingerprint(year)
        state = page_cache.load(slug, LAYER_ROSTER, fingerprint) if page_cache else None
        try:
            fetched = fetch_published_page_conditional(
                client,
                base_url,
                year,
                LAYER_ROSTER,
                state=state,
                want_validators=page_cache is not None,
            )
            if fetched.unchanged and state is not None and page_cache is not None:
                roster_url = state.final_url
                if state.parsed is not None:
                    players = list(state.parsed.get("players") or [])  # type: ignore[arg-type]
                    outcomes[LAYER_ROSTER] = LayerOutcome(
                        LAYER_ROSTER,
                        state.outcome_state,
                        count=state.outcome_count,
                        reason=state.outcome_reason,
                        source_url=state.final_url,
                        unchanged=True,
                    )
                    page_cache.mark_verified(
                        slug,
                        LAYER_ROSTER,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                    )
                else:
                    players = parse_roster_page(
                        state.read_html(), page_url=state.final_url
                    )
                    outcomes[LAYER_ROSTER] = LayerOutcome(
                        LAYER_ROSTER,
                        STATE_COMPLETE if players else STATE_EMPTY,
                        count=len(players),
                        reason=None
                        if players
                        else f"[{year}] the {year} roster page proved its season but listed no players",
                        source_url=state.final_url,
                        unchanged=True,
                    )
                    page_cache.mark_verified(
                        slug,
                        LAYER_ROSTER,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                        fingerprint=fingerprint,
                        outcome_state=outcomes[LAYER_ROSTER].state,
                        outcome_count=len(players),
                        outcome_reason=outcomes[LAYER_ROSTER].reason,
                        parsed={"players": players},
                    )
            else:
                page = fetched.page
                assert page is not None
                roster_html = page.html
                roster_url = page.final_url
                players = parse_roster_page(page.html, page_url=page.final_url)
                outcomes[LAYER_ROSTER] = LayerOutcome(
                    LAYER_ROSTER,
                    STATE_COMPLETE if players else STATE_EMPTY,
                    count=len(players),
                    reason=None
                    if players
                    else f"[{year}] the {year} roster page proved its season but listed no players",
                    source_url=page.final_url,
                )
                if page_cache is not None and fetched.signature is not None:
                    page_cache.save(
                        slug,
                        LAYER_ROSTER,
                        requested_url=page.requested_url,
                        final_url=page.final_url,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                        signature=fetched.signature,
                        fingerprint=fingerprint,
                        outcome_state=outcomes[LAYER_ROSTER].state,
                        outcome_count=len(players),
                        outcome_reason=outcomes[LAYER_ROSTER].reason,
                        parsed={"players": players},
                    )
        except (LiveCollectionError, OSError) as exc:
            outcomes[LAYER_ROSTER] = LayerOutcome(
                LAYER_ROSTER, STATE_UNAVAILABLE, reason=str(exc), source_url=roster_url
            )
            if page_cache is not None and roster_html:
                page_cache.invalidate(slug, LAYER_ROSTER)

    if LAYER_STATS in wanted:
        stats_url = f"{base_url}/stats/{year}"
        fingerprint = parse_fingerprint(year)
        state = page_cache.load(slug, LAYER_STATS, fingerprint) if page_cache else None
        try:
            fetched = fetch_published_page_conditional(
                client,
                base_url,
                year,
                LAYER_STATS,
                state=state,
                want_validators=page_cache is not None,
            )
            if fetched.unchanged and state is not None and page_cache is not None:
                stats_url = state.final_url
                if state.parsed is not None:
                    stat_players = list(state.parsed.get("players") or [])  # type: ignore[arg-type]
                    stat_keepers = list(state.parsed.get("keepers") or [])  # type: ignore[arg-type]
                    outcomes[LAYER_STATS] = LayerOutcome(
                        LAYER_STATS,
                        state.outcome_state,
                        count=state.outcome_count,
                        reason=state.outcome_reason,
                        source_url=state.final_url,
                        unchanged=True,
                    )
                    page_cache.mark_verified(
                        slug,
                        LAYER_STATS,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                    )
                else:
                    stat_players, stat_keepers = parse_stats_page(
                        state.read_html(), page_url=state.final_url
                    )
                    count = len(stat_players) + len(stat_keepers)
                    outcomes[LAYER_STATS] = LayerOutcome(
                        LAYER_STATS,
                        STATE_COMPLETE if count else STATE_EMPTY,
                        count=count,
                        reason=None
                        if count
                        else f"[{year}] the {year} statistics page proved its season but listed no players",
                        source_url=state.final_url,
                        unchanged=True,
                    )
                    page_cache.mark_verified(
                        slug,
                        LAYER_STATS,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                        fingerprint=fingerprint,
                        outcome_state=outcomes[LAYER_STATS].state,
                        outcome_count=count,
                        outcome_reason=outcomes[LAYER_STATS].reason,
                        parsed={"players": stat_players, "keepers": stat_keepers},
                    )
            else:
                page = fetched.page
                assert page is not None
                stats_html = page.html
                stats_url = page.final_url
                stat_players, stat_keepers = parse_stats_page(
                    page.html, page_url=page.final_url
                )
                count = len(stat_players) + len(stat_keepers)
                outcomes[LAYER_STATS] = LayerOutcome(
                    LAYER_STATS,
                    STATE_COMPLETE if count else STATE_EMPTY,
                    count=count,
                    reason=None
                    if count
                    else f"[{year}] the {year} statistics page proved its season but listed no players",
                    source_url=page.final_url,
                )
                if page_cache is not None and fetched.signature is not None:
                    page_cache.save(
                        slug,
                        LAYER_STATS,
                        requested_url=page.requested_url,
                        final_url=page.final_url,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                        signature=fetched.signature,
                        fingerprint=fingerprint,
                        outcome_state=outcomes[LAYER_STATS].state,
                        outcome_count=count,
                        outcome_reason=outcomes[LAYER_STATS].reason,
                        parsed={"players": stat_players, "keepers": stat_keepers},
                    )
        except (LiveCollectionError, OSError) as exc:
            outcomes[LAYER_STATS] = LayerOutcome(
                LAYER_STATS, STATE_UNAVAILABLE, reason=str(exc), source_url=stats_url
            )
            if page_cache is not None and stats_html:
                page_cache.invalidate(slug, LAYER_STATS)

    return ProgrammeCollection(
        slug=slug,
        name=school.name,
        fixtures=fixtures,
        players=players,
        outcomes=outcomes,
        schedule_url=schedule_url,
        roster_url=roster_url,
        schedule_html=schedule_html,
        roster_html=roster_html,
        stat_players=stat_players,
        stat_keepers=stat_keepers,
        stats_url=stats_url,
        stats_html=stats_html,
    )


def write_raw_pages(
    root: Path, result: ProgrammeCollection, year: int, gender: str
) -> None:
    """Archive whatever was actually served, so any parse can be redone offline.

    A layer verified unchanged is not rewritten: the archive already holds
    exactly those bytes, and skipping the write is half of what the
    conditional check buys.
    """
    if not (result.schedule_html or result.roster_html or result.stats_html):
        return

    def fresh(layer: str) -> bool:
        outcome = result.outcomes.get(layer)
        return outcome is None or not outcome.unchanged

    directory = root / "data" / "raw_html" / result.slug
    directory.mkdir(parents=True, exist_ok=True)
    if result.schedule_html and fresh(LAYER_SCHEDULE):
        (directory / f"{year}-{gender}-schedule.html").write_text(
            result.schedule_html, encoding="utf-8"
        )
    if result.roster_html and fresh(LAYER_ROSTER):
        (directory / f"{year}-{gender}-roster.html").write_text(
            result.roster_html, encoding="utf-8"
        )
    if result.stats_html and fresh(LAYER_STATS):
        (directory / f"{year}-{gender}-stats.html").write_text(
            result.stats_html, encoding="utf-8"
        )
