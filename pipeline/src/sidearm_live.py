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

Two more skins publish the season as a payload only, with no rendered rows
at all (measured 2026-09-03): the legacy list skin (``schedule_template_3``)
ships one inline ``schedule : {...}`` object a Vue component renders in the
browser, and the Nuxt "nextgen" skin ships its whole Pinia state in
``#__NUXT_DATA__`` — schedule, roster and cumulative statistics alike.  Both
carry the events component's game contract, and both name the season they
are, so ``_payload_events`` reads all three payload shapes as one and marks
which of them can be trusted about the season.

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
import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from urllib3.util.retry import Retry

from src.config import SchoolConfig, programme_slug
from src.gazetteer import AP_TO_USPS, STATE_NAMES, USPS_TO_AP, parse_town
from src.membership import (
    STRUCTURAL_CODES,
    conference_in_effect,
    conference_profiles,
    has_windows,
    level_scopes,
    load_membership,
    members_in_effect,
)
from src.page_state import BoxArchive, PageState, PageStateStore, content_signature
from src.tls import TruststoreHTTPAdapter

if TYPE_CHECKING:
    from src.recipes import Recipe

_LOG = logging.getLogger(__name__)


class LiveCollectionError(RuntimeError):
    """A live page could not be proven to represent the requested season.

    ``status`` is the HTTP status the server answered when the failure was a
    non-2xx response, so a report can say what HTTP said rather than reading
    a 403 as nothing (bead tl-v1q.6).  It is None for a timeout, a refused
    connection, or a page that was served but proves the wrong season.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def http_status(exc: requests.RequestException) -> int | None:
    """The status code of the response a failed request carries, if any."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def failure_detail(exc: LiveCollectionError) -> str:
    """What HTTP said, in the words the report prints after ``error``.

    A 403 is not nothing (bead tl-v1q.6): the status rides the exception when
    the server answered one; a timeout or a refused connection is named as
    such; the remaining case is a page that was served but could not prove
    its season.
    """
    if exc.status is not None:
        return f"HTTP {exc.status}"
    cause = exc.__cause__
    if isinstance(cause, requests.Timeout):
        return "timeout"
    if isinstance(cause, requests.ConnectionError):
        return "connection failed"
    if isinstance(cause, requests.RequestException):
        return "request failed"
    return "season not proven"


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
    #: Rows the page published that the parse read and deliberately did not
    #: mint, each named ("hosted other-match skipped: 2026-08-27, A v B").
    #: Not a gap: the layer is complete without them.
    skips: tuple[str, ...] = ()


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


def layer_url(base_url: str, year: int, kind: str) -> str:
    """The SideArm URL of one season layer: ``{base}/{kind}/{year}``."""
    return f"{base_url.rstrip('/')}/{kind}/{year}"


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


_HTML_TAG = re.compile(r"<[A-Za-z!][^>]*>")


def assert_served_body(
    response: requests.Response,
    *,
    year: int,
    kind: str,
    url: str,
    body: str = "html",
) -> None:
    """Refuse a 2xx answer that is not the page.

    Measured 2026-09-02 on tampaspartans.com: after a burst of requests from
    one client the site answers HTTP 202 with an empty body (CloudFront,
    ``Cache-Control: no-store``), a WAF challenge rather than the page.
    ``raise_for_status`` passes a 202, and the season proof then fails with
    "cannot prove which season was served" and no status, which reads as a
    parser problem.  A 2xx other than 200, or a body with no HTML in it, is
    refused here with the status attached, so the layer's outcome and the
    probe say what HTTP said.  No challenge is answered or bypassed.

    ``body="json"`` is for an API answer (the WMT recipe's schedule-events
    and ``wmt.games`` bodies): the body must then parse as a JSON object or
    array, so an HTML challenge page served in place of the JSON is refused
    the same way.  The default, ``"html"``, is exactly the check every
    SideArm and PrestoSports page has always had.
    """
    if body not in ("html", "json"):
        raise ValueError(f"{body!r} is not a served body kind (html, json)")
    status = response.status_code
    text = response.text or ""
    if not text.strip():
        served = "an empty body"
    elif body == "json" and not _is_json_document(text):
        served = "a body that is not a JSON document"
    elif body == "html" and _HTML_TAG.search(text) is None:
        served = "a body carrying no HTML"
    elif status != 200 and status in range(200, 300):
        served = "a JSON body" if body == "json" else "an HTML body"
    else:
        return
    raise LiveCollectionError(
        f"[{year}] {kind} page {url} answered HTTP {status} with {served} "
        f"(served a challenge, not the page)",
        status=status,
    )


def _is_json_document(text: str) -> bool:
    try:
        value = json.loads(text)
    except ValueError:
        return False
    return isinstance(value, (dict, list))


def fetch_published_page_conditional(
    session: requests.Session,
    requested_url: str,
    year: int,
    kind: str,
    state: PageState | None = None,
    want_validators: bool = False,
    served_season: Callable[[PublishedPage, int, str], None] = assert_served_season,
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

    The URL and the season proof are the platform recipe's (src/recipes.py):
    this seam builds no URL of its own, and ``served_season`` defaults to
    the SideArm proof.
    """
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
            f"[{year}] failed to fetch {kind} page {requested_url}: {exc}",
            status=http_status(exc),
        ) from exc
    assert_served_body(response, year=year, kind=kind, url=requested_url)
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
    served_season(page, year, kind)
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
    """Fetch one SideArm season page and prove it is the requested season."""
    fetched = fetch_published_page_conditional(
        session, layer_url(base_url, year, kind), year, kind
    )
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


_VUE_SCHEDULE_LINE = re.compile(r"^\s*schedule\s*:\s*(\{.*\})\s*,?\s*$")


def _vue_schedule_objects(html: str) -> list[dict[str, object]]:
    """Decode the legacy list skin's inline ``schedule : {...}`` object.

    Measured 2026-09-03 on two sites serving ``schedule_template_3`` (the
    page's own ``content_template`` value): the schedule page carries no
    ``events`` component and no ``li.sidearm-schedule-game`` rows at all.  The
    whole season rides as one JSON object on one line of a ``require([...])``
    script — ``Vue.component('vue-schedules', {data: () => ({settings: ...,
    schedule : {...games: [...]}})})`` — and a browser renders the list from
    it.  Each game there has the ``events`` component's shape (id, ISO date,
    ``location_indicator``, ``opponent.title``, ``result``) and the schedule
    names ITS OWN season in ``title``: unlike the events stub, a past-season
    URL serves that past season's object.
    """
    objects: list[dict[str, object]] = []
    if "schedule" not in html:
        return objects
    for line in html.splitlines():
        match = _VUE_SCHEDULE_LINE.match(line)
        if match is None:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("games"), list):
            objects.append(value)
    return objects


_NUXT_REF_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef"}


def _nuxt_state(html: str) -> dict[str, object]:
    """Decode the modern Nuxt skin's ``#__NUXT_DATA__`` state, or ``{}``.

    Measured 2026-09-03 on the SideArm "nextgen" skin: every season page is
    server-rendered from a Pinia state the page also ships whole in a
    ``<script type="application/json" id="__NUXT_DATA__">`` element.  The
    element holds a devalue array — each value sits at an index, and an array
    or object refers to its members by index — with reactivity wrappers
    (``["Reactive", 3]``, ``["Ref", 7]``) around the store roots and a few
    typed holders (``["Set", ...]``, ``["Date", ...]``).  Revived, it is one
    plain tree whose ``pinia`` branch carries the schedule, roster and
    cumulative-statistics stores the skin renders from.
    """
    if "__NUXT_DATA__" not in html:
        return {}
    element = BeautifulSoup(html, "lxml").find("script", id="__NUXT_DATA__")
    if element is None:
        return {}
    try:
        values = json.loads(element.get_text() or "")
    except json.JSONDecodeError:
        return {}
    if not isinstance(values, list) or not values:
        return {}
    revived: dict[int, object] = {}

    def revive(index: object) -> object:
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        if index < 0 or index >= len(values):
            return None  # devalue's negative holes: undefined, NaN, ±Infinity
        if index in revived:
            return revived[index]
        value = values[index]
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                if value[0] in _NUXT_REF_WRAPPERS:
                    if len(value) < 2:
                        revived[index] = None
                        return None
                    revived[index] = None  # placeholder breaks a cycle
                    inner = revive(value[1])
                    revived[index] = inner
                    return inner
                members: list[object] = []
                revived[index] = members
                # Typed holders keep their members in order; the first
                # element names the type and is not data.
                members.extend(revive(item) for item in value[1:])
                return members
            items: list[object] = []
            revived[index] = items
            items.extend(revive(item) for item in value)
            return items
        if isinstance(value, dict):
            mapping: dict[str, object] = {}
            revived[index] = mapping
            for key, item in value.items():
                mapping[key] = revive(item)
            return mapping
        revived[index] = value
        return value

    root = revive(0)
    return root if isinstance(root, dict) else {}


def _nuxt_store(html: str, name: str) -> dict[str, object]:
    """One Pinia store off the Nuxt state, or ``{}``."""
    pinia = _nuxt_state(html).get("pinia")
    store = pinia.get(name) if isinstance(pinia, dict) else None
    return store if isinstance(store, dict) else {}


def _nuxt_schedule_objects(html: str) -> list[dict[str, object]]:
    """Schedule objects (``title`` + ``games``) in the Nuxt schedule store.

    The store keys each season's schedule by sport and year
    (``schedules-mens-soccer,2025``); the object is the legacy skin's schedule
    object under another roof, games included.  The store's separate
    ``nextUpcomingEvents`` and the ``event`` store are the current-season
    stub the events component carries on other skins, and are not read.
    """
    schedules = _nuxt_store(html, "schedule").get("schedules")
    if not isinstance(schedules, dict):
        return []
    return [
        value
        for value in schedules.values()
        if isinstance(value, dict) and isinstance(value.get("games"), list)
    ]


#: SideArm's global code for the soccer programme of each gender, the
#: ``sport.global_sport_shortname`` every embedded event carries (measured
#: 2026-09-07 across 1,677 events on the cached 2026 schedule pages: every
#: event names one, ``msoc`` on all but eight).
SOCCER_SPORT_CODES = {"men": "msoc", "women": "wsoc"}


def _event_sport_code(raw: dict[str, object]) -> str:
    """The sport an embedded event says it belongs to, or ``""``."""
    sport = raw.get("sport")
    if not isinstance(sport, dict):
        return ""
    return str(
        sport.get("global_sport_shortname") or sport.get("shortname") or ""
    ).lower()


def _payload_events(
    html: str, gender: str | None = None
) -> list[tuple[str, dict[str, object], bool]]:
    """Every embedded soccer game as ``(schedule title, event, honest)``.

    Three payload shapes carry the same event contract.  The ``events``
    component's title names the current season whatever URL served it, so
    those rows come back ``honest=False`` and a caller must filter them by
    season.  A schedule object — the legacy list skin's inline Vue data or
    the Nuxt store's schedule — names its own season, so its games are the
    served season's and come back ``honest=True``.

    The ``events`` component is not always the sport's own.  A skin's
    all-sports upcoming-events block rides on the men's soccer page under
    the same component type (smcathletics.com 2026-09-07: women's soccer,
    volleyball, field hockey, tennis and a cross-country invitational
    beside the men's games, bead tl-4sg.41), and every event names its
    sport.  An event naming a sport that is not soccer is never a row, and
    with a ``gender`` the other gender's soccer is not one either.  An
    event naming no sport is kept: the schedule objects name none, and
    they are the sport's own schedule by construction.
    """
    wanted = SOCCER_SPORT_CODES.get(gender or "")
    rows: list[tuple[str, dict[str, object], bool]] = []
    for component in _component_objects(html):
        if component.get("type") != "events":
            continue
        data = component.get("data")
        if not isinstance(data, list):
            continue
        for raw in data:
            if not isinstance(raw, dict):
                continue
            code = _event_sport_code(raw)
            if code and code not in SOCCER_SPORT_CODES.values():
                continue
            if code and wanted and code != wanted:
                continue
            schedule = raw.get("schedule")
            schedule_dict = schedule if isinstance(schedule, dict) else {}
            rows.append((str(schedule_dict.get("title") or ""), raw, False))
    for schedule in _vue_schedule_objects(html) + _nuxt_schedule_objects(html):
        title = str(schedule.get("title") or "")
        for raw in schedule.get("games") or []:  # type: ignore[union-attr]
            if isinstance(raw, dict):
                rows.append((title, raw, True))
    return rows


def payload_seasons(html: str) -> set[int]:
    """Seasons named by the schedule payload itself, not by the page wrapper.

    Measured 2026-08-09: ``/sports/mens-soccer/schedule/2019`` answers 200, keeps
    ``/2019`` through every redirect, and carries a page title that names 2019 —
    while every embedded ``events`` component carries
    ``schedule.title == "2026 Men's Soccer Schedule"``.  The wrapper is honest and
    the payload is the current season.  ``assert_served_season`` cannot see that,
    because it only ever reads the wrapper.  The schedule-object payloads of the
    legacy list skin and the Nuxt skin name the served season instead.
    """
    years: set[int] = set()
    for title, _, _ in _payload_events(html):
        match = re.search(r"\b(\d{4})\b", title)
        if match:
            years.add(int(match.group(1)))
    return years


def _payload_event_ids(html: str, owner_slug: str) -> set[str]:
    """Fixture ids of every embedded event, whatever season the payload claims."""
    return {
        f"sidearm:{owner_slug}:{raw['id']}"
        for _, raw, _ in _payload_events(html)
        if raw.get("id")
    }


def _has_schedule_markup(html: str) -> bool:
    """Whether the page carries any SideArm schedule shape at all."""
    if any(component.get("type") == "events" for component in _component_objects(html)):
        return True
    if _vue_schedule_objects(html) or _nuxt_schedule_objects(html):
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
    # A schedule object names the season it IS, so one naming another year
    # under this URL is the trap outright — there is no DOM beside it to
    # carry the requested season, and no fixtures to overlap.
    honest = {
        int(match.group(1))
        for title, _, honest in _payload_events(html)
        if honest and (match := re.search(r"\b(\d{4})\b", title))
    }
    if honest and year not in honest:
        listed = ", ".join(str(value) for value in sorted(honest))
        raise LiveCollectionError(
            f"[{year}] {page_url} renders the season-{listed} schedule at this "
            f"season URL, so {year} fixtures cannot be collected from it"
        )
    overlap = _payload_event_ids(html, owner_slug) & {
        str(fixture["id"]) for fixture in fixtures
    }
    if overlap:
        listed = ", ".join(str(value) for value in sorted(served)) or "another season"
        raise LiveCollectionError(
            f"[{year}] {page_url} renders the season-{listed} schedule at this "
            f"season URL, so {year} fixtures cannot be collected from it"
        )


def assert_schedule_proven(
    html: str,
    *,
    year: int,
    page_url: str,
    fixtures: list[dict[str, object]],
    owner_slug: str,
) -> None:
    """Refuse a freshly served schedule that parsed but cannot be trusted.

    Two shapes.  ``assert_untrapped_schedule`` refuses a past-season URL whose
    rendered games are the payload's current-season events.  And a page with
    neither a schedule payload nor rendered games is not a season with no
    fixtures but a page that is not a SideArm schedule at all (or a season
    the site has not released).  Runs on new content only: an archived page
    proved itself when it was archived.
    """
    assert_untrapped_schedule(html, year, page_url, fixtures, owner_slug)
    if not fixtures and not _has_schedule_markup(html):
        raise LiveCollectionError(
            f"[{year}] {page_url} published no schedule payload "
            f"and no rendered games — either the season is not "
            f"released yet or the page is not SideArm"
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
# A second scan (bead tl-cgb, 755 archived pages) found the forms that grammar
# still let through, each minting a ranked twin of a real slug:
#
#   /#5  /No. 10                two polls with the first slot empty: the
#                               theme prints "<span>/#5</span>" before the
#                               link (measured "/#5 Mercy College" on
#                               queensknights.com 2023 game 6816 and "/#8
#                               Mercy University" 2025 game 7618, filed as
#                               5-mercy and 8-mercy beside mercy; "/#9
#                               Adelphi University" is 9-adelphi)
#   #17 | #3 Seed               two polls joined by a pipe
#   #T-15                       a tied rank
#   #7 (#1 Seed)  (#3A)  (#7)   a bracketed seed carrying its own marker,
#                               its "Seed" word, or a division letter
#   No. 1/ No. 1 seed - Lynn    a lone dash between the prefix and the name
#
# So a token is a value carrying an optional marker or bracket, tokens may be
# slash- or pipe-joined with the first slot allowed empty, the whole prefix
# repeats, and a lone dash after it belongs to the prefix.
#
# Two limits stop it eating real names. Two digits is the whole range a poll
# uses, and every token must be followed by whitespace — which is why
# "5th-Seed Oklahoma Christian" loses the seed and keeps the school, and why
# the bare "rv" alternative does not bite Rverside. What leads an opponent
# string far more often than a rank is an all-caps abbreviation: UT Tyler at
# 127 rows, MSU Denver at 17, CSU Pueblo and USC Aiken behind them. None of
# those match.
#
# A conference that seeds its tournament by division writes the division
# letter onto the seed (measured "No. 2E West Chester (PSAC Quarterfinal)" on
# lockhavenathletics.com 2025), so a value may carry one trailing letter; the
# whitespace rule still keeps "2E" from being the start of a word.
_RANK_VALUE = r"(?:rv|t-\d{1,2}|\d{1,2}[a-z]?)"
_RANK_MARKER = r"(?:#|no\.?)?"
_RANK_BRACKETED = rf"{_RANK_MARKER}\s*{_RANK_VALUE}(?:\s*seed)?"
_RANK_TOKEN = (
    r"(?:"
    rf"\(\s*{_RANK_BRACKETED}\s*\)|\[\s*{_RANK_BRACKETED}\s*\]"
    rf"|{_RANK_MARKER}\s*\d{{1,2}}(?:st|nd|rd|th)?[-\s]seed"
    rf"|{_RANK_MARKER}\s*{_RANK_VALUE}"
    r")"
)
_RANK_JOINER = r"\s*[/|]\s*"
# One theme glues the rank to the name with a hyphen and no space (measured:
# wsuathletics.com 2026 women, games 12026 and 12036, "#21-McKendree" and
# "#15-Ashland", minted as 21-mckendree and 15-ashland beside the schools'
# own records). Only a hash-marked poll value may end this way, and only
# before a letter: no school's name begins with "#", so "2Excellent College"
# and "T-Bird College" stay whole, and a bare "21-" is never read as a rank.
_RANK_HASH_HYPHEN = r"#\s*\d{1,2}-(?=[a-z])(?!seed\b)"
_RANK_PREFIX = re.compile(
    rf"^(?:{_RANK_JOINER})?(?:{_RANK_TOKEN}(?:{_RANK_JOINER}{_RANK_TOKEN})*\s+)*"
    rf"(?:{_RANK_TOKEN}(?:{_RANK_JOINER}{_RANK_TOKEN})*\s+|{_RANK_HASH_HYPHEN})"
    r"(?:-\s+)?",
    re.IGNORECASE,
)


def _clean_team_name(name: object) -> str:
    return _RANK_PREFIX.sub("", str(name or "").strip())


def _seeded(name: object) -> bool:
    """True when the published string carried a rank or seed prefix.

    The schedule parsers clean the prefix off before resolving, so they ask
    this of the raw string and pass the answer to ``opponent_slug``.
    """
    return _RANK_PREFIX.match(str(name or "").strip()) is not None


# The orientation word some skins print inside the opponent cell ("vs
# Molloy", "at Molloy", "@ Molloy") rather than in a dedicated span.
_ORIENTATION_PREFIX = re.compile(r"^\s*(vs\.?|v\.?|at|@)\s+", re.IGNORECASE)


def _split_orientation(name: str) -> tuple[str | None, str]:
    """Peel a leading orientation word off a published opponent string.

    Returns the word normalised to ``"vs"`` or ``"at"`` (``None`` when the
    string carries none) and the remainder.  Measured: the two-team list skin
    (daemenwildcats.com 2026) prints upcoming rows as ``<span>at</span>``
    followed by the opponent link inside one ``-opponent-name`` span, so the
    flattened text reads "at Molloy" and would otherwise be minted as the
    slug ``at-molloy``; its played rows carry no such word.
    """
    match = _ORIENTATION_PREFIX.match(name)
    if match is None:
        return None, name
    word = match.group(1).lower()
    return ("at" if word in {"at", "@"} else "vs"), name[match.end() :]


# The word between two team names on a row a tournament host publishes for
# a match it staged but did not play: "0 Colorado Mesa vs 1 Midwestern"
# (westminstergriffins.com 2023), "Western Oregon University vs Metropolitan
# State University of Denver" (the same site, 2026).
_TWO_TEAM_SPLIT = re.compile(r"\s+(?:vs\.?|v\.?)\s+", re.IGNORECASE)


def _two_team_names(opponent_name: str) -> tuple[str, str] | None:
    parts = _TWO_TEAM_SPLIT.split(opponent_name, maxsplit=1)
    if len(parts) != 2:
        return None
    first, second = (_clean_team_name(part) for part in parts)
    if not first or not second:
        return None
    return first, second


def hosted_other_match(
    opponent_name: str,
    *,
    owner_slug: str,
    aliases: dict[str, str],
    scope: ResolutionScope | None = None,
) -> tuple[str, str] | None:
    """The two teams a published row names when the page owner is neither.

    A fixture read from a programme's own schedule page must have that
    programme as one side.  A tournament host lists the other pair's match
    on its own page ("A vs B" in the opponent cell, the host's ground as the
    venue), and minting it as the host's fixture produced a phantom row on
    the host and a duplicate of the real match, which one of the two named
    teams publishes on its own page (beads tl-clk.10, tl-5ru).  Each side is
    folded through the alias-aware identity (``opponent_slug``), never
    compared as a string, so the owner's own published spellings count.

    Returns the two cleaned names when neither folds to the owner, and
    ``None`` for every row the owner is in — a single-name row, or a
    two-team row naming the owner on one side (``own_side_opponent`` then
    reads the other).
    """
    pair = _two_team_names(opponent_name)
    if pair is None:
        return None
    if owner_slug in (
        opponent_slug(pair[0], aliases, scope=scope, owner=owner_slug),
        opponent_slug(pair[1], aliases, scope=scope, owner=owner_slug),
    ):
        return None
    return pair


def own_side_opponent(
    opponent_name: str,
    *,
    owner_slug: str,
    aliases: dict[str, str],
    scope: ResolutionScope | None = None,
) -> str:
    """The other side of a row that names the owner beside its opponent.

    "Westminster vs Colorado Mesa" on Westminster's page is a Westminster
    fixture v Colorado Mesa; a single-name row is returned as it is.
    """
    pair = _two_team_names(opponent_name)
    if pair is None:
        return opponent_name
    if opponent_slug(pair[0], aliases, scope=scope, owner=owner_slug) == owner_slug:
        return pair[1]
    if opponent_slug(pair[1], aliases, scope=scope, owner=owner_slug) == owner_slug:
        return pair[0]
    return opponent_name


def hosted_skip(date: str, pair: tuple[str, str]) -> str:
    """The named skip the collect summary prints for one hosted row."""
    return f"hosted other-match skipped: {date}, {pair[0]} v {pair[1]}"


def calendar_event_skip(date: str, name: str) -> str:
    """The named skip the collect summary prints for one calendar-event row."""
    return f"calendar event skipped: {date}, {name}"


# A postseason structure row names a round, a bracket or a conference where
# an opponent should be, or nothing yet: "NCAA First Round", "GLVC
# Quarterfinals", "PBC Quartefinals" (sic), "CCAA Tournament Semifinals (at
# Cal Poly Pomona)", "NCAA Selection Show", "Gulf South Conference", "TBA".
# Measured 2026-09-12 over every archived schedule payload (rib issue #41):
# 27 distinct strings, the conference-name shape on 78 rows across six
# conferences, and every one on a row the site would otherwise draw as a
# match — "gulf-south-conference" landed on four rows flagged as conference
# games. Real matches from those rounds arrive later with actual opponents,
# so the row is a named skip, never a fixture (PrestoSports has read it that
# way since #71; this is the one grammar for both).
#
# The round words are judged OUTSIDE parentheses: "No. 2E West Chester (PSAC
# Quarterfinal)" and "No. 1 Seed Post (CACC Championship)" are fixtures whose
# round sits in the annotation, and "NCAA Semifinals (MIAA)" is a placeholder
# whose parenthetical names the host. The bare word "conference" is a tell
# because no programme carries it in its name (checked over every archived
# opponent string); a school's own conference in a parenthetical is dropped
# before the test. "TBA" and "TBD" must be the whole string. Once a bracket
# fills, the slot names the match that decides it: "USCA/Lander Winner", "#6
# Seed Dallas Baptist OR #3 Seed St. Mary's" — no programme carries "or",
# "winner" or "loser" as a word in its name either.
#
# A bare "NCAA" is the same slot before the field is named: flagler 2026,
# games 13737 and 13738; findlay 2026, game 12542; cal-state-dominguez-hills
# 2024, games 13162 and 13163 — five rows that minted a programme called
# "ncaa". Like "TBA" it must be the whole string, so "NCAA Selection Show"
# stays with the round words and no name merely containing it is caught.
# The level the slot may carry is any of the three, spelled any way a site
# does ("NCAA D2", "NCAA DI", "NCAA Division III", "NCAA Division 1"): the
# rib is not one NCAA division's, and no programme is named for one. The
# Division I championship's final rounds print as "NCAA College Cup", which
# no programme is named for either.
_ROUND_PLACEHOLDER = re.compile(
    r"\b(?:tournament|championships?|quarte(?:r)?-?finals?|semi-?finals?|finals?"
    r"|(?:\d{1,2}(?:st|nd|rd|th)|first|second|third|fourth|opening)\s+rounds?"
    r"|selection\s+show|playoffs?|regionals?|\bconference\b|college\s+cup"
    r"|or|winner|loser)\b",
    re.IGNORECASE,
)
_UNNAMED_OPPONENT = re.compile(
    r"tbd|tba|ncaa(?:\s+(?:d(?:ivision)?[\s-]*)?(?:i{1,3}|[123]))?", re.IGNORECASE
)
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def round_placeholder(name: str) -> bool:
    """Whether a published opponent string is a postseason slot, not a side."""
    outside = _PARENTHETICAL.sub(" ", name).strip()
    return bool(
        _UNNAMED_OPPONENT.fullmatch(outside) or _ROUND_PLACEHOLDER.search(outside)
    )


def placeholder_skip(date: str, name: str) -> str:
    """The named skip the collect summary prints for one postseason slot row."""
    return f"round placeholder skipped: {date}, {name}"


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

    The institutional words are dropped in two steps, and the order matters.
    Dropping "university" and "college" alone left the preposition behind:
    "University of Texas at Dallas" keyed to "of texas at dallas" and was
    filed beside "UT Dallas" as a second programme (tl-kvn; the data home
    held thirty-odd such of- slugs, "of-tampa" beside "tampa", "of-findlay"
    beside "findlay"). So a leading "of" — the residue of "University of",
    "College of" and "The University of the" — goes too, and a locative
    "at"/"in" between two words ("Texas at Dallas", "Alabama in Huntsville",
    "Auburn at Montgomery") folds onto the hyphenated spelling peers use
    ("Texas-Dallas", "Alabama-Huntsville", "Auburn Montgomery"). Only a
    leading "of" is dropped: "Colorado School of Mines" and "Dominican
    University of N.Y." keep theirs, since there the preposition sits inside
    the name rather than in front of it.
    """
    return _identity_fold(name)[0]


# The words the fold removes, each named so a sweep can say which rule folded
# a pair (scripts/sweep_opponent_slugs.py).
FOLD_INSTITUTION = "institution-word"
FOLD_OF_PREFIX = "of-prefix"
FOLD_LOCATIVE = "locative-joiner"

_INSTITUTION_WORDS = re.compile(r"\buniv(?:ersity)?\b|\bcollege\b|\bthe\b")
_OF_PREFIX = re.compile(r"^(?:of\s+)+")
_LOCATIVE_JOINER = re.compile(r"(?<=[a-z0-9])\s+(?:at|in)\s+(?=[a-z0-9])")


def _identity_fold(name: str) -> tuple[str, tuple[str, ...]]:
    """The identity key of a published string, with the fold rules that fired.

    The key is what ``_identity_key`` returns; the rules are the names above,
    in the order applied, for every rewrite that changed the string.
    """
    rules: list[str] = []
    text = _identity_text(name)

    stripped = re.sub(r"\s+", " ", _INSTITUTION_WORDS.sub(" ", text)).strip()
    if stripped != text:
        rules.append(FOLD_INSTITUTION)
    text = stripped

    text, rest = _fold_prepositions(text)
    rules.extend(rest)
    return text, tuple(rules)


def _identity_text(name: str) -> str:
    """A published string lower-cased, Saint/State read, punctuation gone."""
    text = _clean_team_name(name).lower().replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"\bst\.?\s*$", " state", text)
    text = re.sub(r"\b(?:st\.\s*|st\s+)(?=[a-z])", "saint ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _fold_prepositions(text: str) -> tuple[str, list[str]]:
    """The of-prefix and locative-joiner folds, with the rules that fired."""
    rules: list[str] = []
    stripped = _OF_PREFIX.sub("", text)
    if stripped != text:
        rules.append(FOLD_OF_PREFIX)
    text = stripped

    stripped = _LOCATIVE_JOINER.sub(" ", text)
    if stripped != text:
        rules.append(FOLD_LOCATIVE)
    text = stripped
    return re.sub(r"\s+", " ", text).strip(), rules


def identity_fold_rules(name: str) -> tuple[str, ...]:
    """Which fold rules rewrite ``name`` on the way to its identity key."""
    return _identity_fold(name)[1]


# The institution word is the one thing that tells some pairs of schools
# apart: Boston College (ACC) and Boston University (Patriot League) both
# fold to "boston". So beside the folded key every spelling has an
# INSTITUTION KEY: the same fold with the institution words kept, each
# spelled one way ("Univ." and a trailing "U" are University, "Coll." is
# College) and moved to the end in a fixed order, so "College of Boston",
# "Boston College" and "Boston Coll." share one, and "Boston U." and
# "Boston University" share another. "The" is dropped as the fold drops it:
# it never tells two schools apart. A folded key never carries "college" or
# "university" (the fold removes them), so an institution key can sit in the
# same map as the folded keys without ever meaning one of them.
_INSTITUTION_FORMS = {
    "university": "university",
    "univ": "university",
    "u": "university",
    "college": "college",
    "coll": "college",
}
_INSTITUTION_ORDER = ("college", "university")


def _institution_key(name: str) -> str:
    """The identity key with the institution words kept, or "" without one.

    "" when the string carries no institution word (its folded key is the
    whole of its identity) or nothing but institution words.
    """
    tokens = _identity_text(name).split()
    words = {_INSTITUTION_FORMS[t] for t in tokens if t in _INSTITUTION_FORMS}
    if not words:
        return ""
    rest = " ".join(t for t in tokens if t not in _INSTITUTION_FORMS and t != "the")
    base, _ = _fold_prepositions(rest)
    if not base:
        return ""
    return " ".join([base, *(w for w in _INSTITUTION_ORDER if w in words)])


def _lookup_keys(name: str) -> tuple[str, ...]:
    """The keys a published string is looked up under, most specific first.

    Its institution key, when it has one, then its folded key. The
    institution key can only ever hit a programme whose folded key the
    table withdrew (``institution_split_keys``), so for every other string
    the lookup is the folded key alone, exactly as before.
    """
    folded = _identity_key(name)
    institution = _institution_key(name)
    if institution and institution != folded:
        return (institution, folded)
    return (folded,)


def institution_split_keys(
    schools: list[SchoolConfig], gender: str | None = None
) -> frozenset[str]:
    """The folded keys an institution word splits between programmes.

    A folded key two or more programmes of one table claim, where at least
    one claim carries an institution word: "boston", from "Boston College"
    and "Boston University". Dropping the word is what made the spellings
    meet, so the word is what tells them apart, and the table keeps it for
    that key: the folded key resolves to nobody (bare "Boston" names neither
    school and mints its slug from the text) and each spelling is claimed
    under its institution key instead. A folded key every claimant spells
    bare is an ordinary collision, which check-membership refuses
    (``identity_collisions``).

    The table is the stanza list given, the same one ``identity_aliases``
    builds from (on the collection path, one gender at one NCAA level in
    one season: ``membership.resolution_stanzas``), and the claims read are
    exactly the ones that map reads: name, aliases and a resolving
    abbreviation. ``display_name`` and ``member_aliases`` never split a key.
    The answer is a set over every claim of the table, so it cannot depend
    on stanza order.
    """
    owners: dict[str, set[str]] = {}
    worded: set[str] = set()
    for school in schools:
        if gender is not None and school.gender != gender:
            continue
        slug = programme_slug(school.name)
        for candidate in _identity_spellings(school):
            key = _identity_key(candidate)
            if not key:
                continue
            owners.setdefault(key, set()).add(slug)
            if _institution_key(candidate) not in ("", key):
                worded.add(key)
    return frozenset(key for key in worded if len(owners[key]) > 1)


# A parenthetical that names a U.S. state is evidence of which school a
# printed name means: "Columbia College (S.C.)" is not the Columbia in New
# York, "Holy Cross College (Ind.)" not the one in Worcester, "Loyola (Ill.)"
# is Loyola Chicago and "Loyola (Md.)" Loyola Maryland. Sites spell the state
# AP style ("(W.Va.)"), postal ("(TX)"), spelled out ("(Ohio)", "(New
# York)") and in the archive's own variants ("(W. Va.)", "(W.V.)", "(W,V.)",
# "(S.C)", "(Oh.)"), so a form is read with its spaces, periods and commas
# removed, against the Gazetteer's AP and state-name tables plus the one
# spelling neither carries. A bare two-letter postal code is read only in
# capitals or with a period ("(TX)", "(Oh.)"), so a lower-case word is never
# taken for one; every other parenthetical ("(Exhibition)", "(DH)", "(RV)",
# "(B.C.)", "(Senior Day)", "(Syracuse)") names no state and changes nothing.
_STATE_QUALIFIER_EXTRA = {"Tex.": "TX"}


def _qualifier_form(text: str) -> str:
    return re.sub(r"[\s.,]+", "", text).lower()


_STATE_QUALIFIERS = {
    **{_qualifier_form(form): usps for form, usps in AP_TO_USPS.items()},
    **{_qualifier_form(form): usps for form, usps in STATE_NAMES.items()},
    **{_qualifier_form(form): usps for form, usps in _STATE_QUALIFIER_EXTRA.items()},
}
_PARENTHETICAL_INNER = re.compile(r"\(([^()]*)\)")


def state_qualifier(text: str) -> str | None:
    """The USPS code a parenthetical's inner text names, or None.

    "S.C." -> "SC", "W. Va." -> "WV", "TX" -> "TX", "Ohio" -> "OH";
    "Exhibition", "DH", "B.C." -> None.
    """
    form = _qualifier_form(text)
    if form in _STATE_QUALIFIERS:
        return _STATE_QUALIFIERS[form]
    letters = re.sub(r"[^A-Za-z]", "", text)
    if (
        len(form) == 2
        and form.upper() in USPS_TO_AP
        and (letters.isupper() or "." in text)
    ):
        return form.upper()
    return None


def printed_state(name: str) -> str | None:
    """The one U.S. state a published opponent string's parentheticals name.

    None when no parenthetical names a state, or when two name different
    states (no evidence either way).
    """
    states = {
        state
        for inner in _PARENTHETICAL_INNER.findall(name or "")
        if (state := state_qualifier(inner)) is not None
    }
    return next(iter(states)) if len(states) == 1 else None


def stanza_state(school: SchoolConfig) -> str | None:
    """A stanza's home state (USPS) from its ``city``, or None when unparseable."""
    town = parse_town(school.city)
    return None if town is None else town.usps


def _claim_keys(candidate: str, split: frozenset[str]) -> tuple[str, ...]:
    """The keys one claimed spelling registers under, given the split keys.

    Its folded key, unless an institution word splits that key: then its
    institution key, or nothing for a bare spelling, which names every
    programme the split key joins.
    """
    key = _identity_key(candidate)
    if not key:
        return ()
    if key not in split:
        return (key,)
    institution = _institution_key(candidate)
    return (institution,) if institution and institution != key else ()


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

    Level scoping is not optional either, and it is the caller's: a collect
    passes the stanzas of its conference's NCAA level for the season
    (``membership.resolution_stanzas``), never the whole file. Division I
    and Division II share names and name tokens ("California" is California
    (Pa.) in one and Cal in the other; "Penn State Abington" holds every
    token of "Penn State"), so one table across levels hands one level's
    text to the other's programmes. Text naming a school at another level
    mints its slug from the text, as text naming an unknown school does.

    A folded key an institution word splits between two programmes of the
    table (``institution_split_keys``: "boston", Boston College's and Boston
    University's) is withdrawn, and each spelling that folds to it is held
    under its institution key ("boston college", "boston university")
    instead. An institution key two programmes claim is withdrawn too, so
    nothing this rule adds depends on stanza order. A table no institution
    word splits is built exactly as before.
    """
    split = institution_split_keys(schools, gender)
    aliases: dict[str, str] = {}
    contested: set[str] = set()
    for school in schools:
        if gender is not None and school.gender != gender:
            continue
        slug = programme_slug(school.name)
        for candidate in _identity_spellings(school):
            for key in _claim_keys(candidate, split):
                if key != _identity_key(candidate) and aliases.get(key, slug) != slug:
                    contested.add(key)
                aliases[key] = slug
    for key in contested:
        del aliases[key]
    return aliases


def _identity_spellings(school: SchoolConfig) -> list[str]:
    """The published spellings one stanza claims for its slug.

    The abbreviation is claimed only while the stanza says it resolves: a
    bare initialism two stanzas share identifies nobody, and the map above
    would otherwise hand it to whichever stanza comes last in the file.
    ``display_name`` is never claimed: it is the reader-facing spelling, not
    an identity, so a same-name pair may print "Dominican (N.Y.)" beside
    "Dominican (Calif.)" while the bare "Dominican" resolves by name and
    aliases alone (tl-4an.31). A published spelling that should resolve is
    stated as an alias. ``member_aliases`` are not claimed here either: they
    resolve only inside a collect's scope (``resolution_scope``), so the
    gender-wide map never sees them.
    """
    spellings = [school.name, *school.aliases]
    if school.abbreviation_resolves:
        spellings.append(school.abbreviation)
    return spellings


def _claimed_fields(school: SchoolConfig) -> list[tuple[str, str]]:
    """The (field, spelling) pairs ``_identity_spellings`` claims, labelled."""
    fields = [("name", school.name)]
    if school.abbreviation_resolves:
        fields.append(("abbreviation", school.abbreviation))
    fields.extend(("alias", alias) for alias in school.aliases)
    return fields


def _gender_splits(schools: list[SchoolConfig]) -> dict[str, frozenset[str]]:
    genders = {school.gender for school in schools}
    return {gender: institution_split_keys(schools, gender) for gender in genders}


def identity_collisions(
    schools: list[SchoolConfig],
) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Every spelling two stanzas of one gender both claim.

    One entry per (gender, key): the identity key and the (slug, field)
    pairs that claim it, in file order. ``identity_aliases`` would resolve
    such a key to the last stanza only, silently; check-membership refuses
    the config instead, so the collision is settled in the data (an alias
    dropped, or ``abbreviation_resolves = false`` on the stanzas that share
    an initialism). The fields checked are exactly the ones
    ``_identity_spellings`` claims; ``display_name`` is not among them.

    A folded key an institution word splits (``institution_split_keys``) is
    not itself a collision: the map holds those spellings under their
    institution keys, so Boston College and Boston University may both fold
    to "boston". Their institution keys are checked instead, so two stanzas
    that both claim "Boston College" still collide, on "boston college". A
    bare spelling of a split key is ``identity_ambiguities``'s to report.
    """
    splits = _gender_splits(schools)
    claims: dict[tuple[str, str], dict[str, list[tuple[str, str]]]] = {}
    for school in schools:
        slug = programme_slug(school.name)
        for label, candidate in _claimed_fields(school):
            key = _identity_key(candidate)
            if not key:
                continue
            if key in splits[school.gender]:
                institution = _institution_key(candidate)
                if not institution or institution == key:
                    continue
                key = institution
            owners = claims.setdefault((school.gender, key), {})
            owners.setdefault(slug, []).append((slug, label))
    collisions = []
    for (gender, key), owners in claims.items():
        if len(owners) > 1:
            collisions.append(
                (gender, key, [pair for pairs in owners.values() for pair in pairs])
            )
    return collisions


def identity_ambiguities(
    schools: list[SchoolConfig],
) -> list[tuple[str, str, list[tuple[str, str]], list[tuple[str, str]]]]:
    """Every bare spelling of a folded key an institution word splits.

    One entry per (gender, key) as ``(gender, key, bare, worded)``: the
    (slug, field) pairs claiming the key with no institution word, and
    those claiming it with one, in file order. Bare "Boston" beside "Boston
    College" and "Boston University" names both schools, so the map
    resolves it to neither and the stanza's claim would silently resolve
    nothing; check-membership refuses it instead.
    """
    splits = _gender_splits(schools)
    bare: dict[tuple[str, str], list[tuple[str, str]]] = {}
    worded: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for school in schools:
        slug = programme_slug(school.name)
        for label, candidate in _claimed_fields(school):
            key = _identity_key(candidate)
            if not key or key not in splits[school.gender]:
                continue
            institution = _institution_key(candidate)
            side = bare if not institution or institution == key else worded
            side.setdefault((school.gender, key), []).append((slug, label))
    return [
        (gender, key, claimants, worded.get((gender, key), []))
        for (gender, key), claimants in bare.items()
    ]


def level_identity_collisions(
    schools: list[SchoolConfig],
    *,
    document: dict[str, object],
) -> list[tuple[str, str, str, list[tuple[str, str]]]]:
    """Every spelling two stanzas of one resolution table both claim.

    ``identity_collisions`` within each table a collect can resolve against
    (``membership.level_scopes``: one gender, one NCAA level, one season),
    one entry per (gender, level, key, claimants) as ``(gender, scope, key,
    claimants)``, where ``scope`` names the level and the seasons the pair
    is in that table together ("d2, seasons 2016-2026"). Two stanzas that
    are never at one level in one season never share a table, so a key both
    claim is no collision: Charleston (W.Va.), Division II, and the College of
    Charleston, Division I, may both claim "charleston". Two that are, even
    for one season (a reclassifier beside a school of the level it left),
    may not. Programme slugs stay unique across every level: that is the
    loader's duplicate ``(gender, slug)`` refusal, not this.
    """
    found: dict[tuple[str, str, str, tuple[tuple[str, str], ...]], list[int]] = {}
    for gender, level, season, stanzas in level_scopes(schools, document=document):
        for _, key, claimants in identity_collisions(stanzas):
            found.setdefault((gender, level, key, tuple(claimants)), []).append(season)
    return [
        (gender, f"{level}, seasons {_season_ranges(seasons)}", key, list(claimants))
        for (gender, level, key, claimants), seasons in found.items()
    ]


def level_identity_ambiguities(
    schools: list[SchoolConfig],
    *,
    document: dict[str, object],
) -> list[tuple[str, str, str, list[tuple[str, str]], list[tuple[str, str]]]]:
    """``identity_ambiguities`` within each resolution table, scoped.

    ``(gender, scope, key, bare, worded)``, with ``scope`` as
    ``level_identity_collisions`` names it: a key splits only inside a
    table, so the pair must be at one level in one season for a bare
    spelling of it to be ambiguous.
    """
    found: dict[
        tuple[str, str, str, tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]],
        list[int],
    ] = {}
    for gender, level, season, stanzas in level_scopes(schools, document=document):
        for _, key, bare, worded in identity_ambiguities(stanzas):
            found.setdefault(
                (gender, level, key, tuple(bare), tuple(worded)), []
            ).append(season)
    return [
        (
            gender,
            f"{level}, seasons {_season_ranges(seasons)}",
            key,
            list(bare),
            list(worded),
        )
        for (gender, level, key, bare, worded), seasons in found.items()
    ]


def _season_ranges(seasons: Sequence[int]) -> str:
    """2016, 2017, 2018, 2021 as "2016-2018, 2021"."""
    runs: list[list[int]] = []
    for season in sorted(set(seasons)):
        if runs and season == runs[-1][1] + 1:
            runs[-1][1] = season
        else:
            runs.append([season, season])
    return ", ".join(
        str(start) if start == end else f"{start}-{end}" for start, end in runs
    )


def conference_members(
    schools: list[SchoolConfig],
    gender: str,
    conference: str,
    *,
    season: int | None = None,
    document: dict[str, object] | None = None,
) -> set[str]:
    """Programme slugs belonging to ONE conference, for the conference-game test.

    Deliberately a different set from ``identity_aliases``.  That map should span
    every configured school at the collecting level, because an
    out-of-conference opponent still deserves a canonical slug.  Membership
    must not: deriving it from the whole alias map marks a cross-conference
    fixture as a conference game, which is correct only while exactly one
    conference is configured.

    Scoped to the conference rather than to the run's requested programmes, since
    a fixture against a member we did not happen to collect is still a conference
    game.

    Membership is per season.  A stanza carries one ``conference``, the current
    one, but a programme can change conference inside the backfill window:
    Trevecca played G-MAC men's soccer in 2022 and 2023 and GSC from 2024, and
    its stanza says GSC.  Read as if it held for every season, the stanza drops
    Trevecca from the G-MAC's 2022 member set and every Trevecca fixture that
    year stops being a conference game.  With a ``season`` each school's
    conference is therefore the membership window covering that season, and the
    stanza field is only the default for a programme with no window declared
    for it at all.

    A programme that HAS authored windows is governed by them alone: a season
    none of them covers is a season it is in no conference.  The stanza used
    to answer for such a season too, and it answered with the conference the
    programme had already left: Mercyhurst, whose PSAC windows end in 2023,
    stayed a PSAC member for 2024, 2025 and 2026 because its stanza still
    says PSAC.  The one uncovered season still answered is one past the
    CONFERENCE's own authored horizon, where its last authored season's
    members are carried forward (``membership.conference_in_effect``): the
    rule the rib's ``resolveConference`` resolves an extrapolated collect by,
    so the GAC authored through 2025 keeps its members for a 2026 collect.

    A slug the windows place in the conference but no stanza configures (a
    dead host recorded membership-only) is a member too: a fixture against it
    is still a conference game.  Without a ``season`` the set is the stanza
    field alone, as before.
    """
    if season is None:
        return {
            programme_slug(school.name)
            for school in schools
            if school.gender == gender and school.conference == conference
        }

    membership_document = document if document is not None else load_membership()
    members: set[str] = set()
    for school in schools:
        if school.gender != gender:
            continue
        slug = programme_slug(school.name)
        resolved = (
            conference_in_effect(
                slug, gender, season, conference, document=membership_document
            )
            if has_windows(slug, gender, document=membership_document)
            else school.conference
        )
        if resolved == conference:
            members.add(slug)
    return members | members_in_effect(
        conference, gender, season, document=membership_document
    )


@dataclass(frozen=True)
class ResolutionScope:
    """The conference-season a collect reads for, and what its members claim.

    Opponent text on a member's page is written for that conference's
    readers: Chaminade's 2025 page prints "Dominican" for Dominican of
    California, a fellow PacWest member, and the gender-wide map reads it as
    the CACC's Dominican, whose whole name it is (tl-b3v: every such match
    landed in the PacWest file twice, once under each slug). So a collect
    resolves inside a scope: the conference-season it is collecting, with
    the identity keys its members claim by name, alias, resolving
    abbreviation and ``member_aliases``. A key a member claims resolves to
    that member before any other programme; every other key resolves as it
    always has. The scope is one object per collect, built from the
    membership resolver's member set, and it applies to every row of every
    page in the collect, conference and non-conference alike.

    ``note`` records each printed text the scope re-pointed, once per
    collect, for the run log.
    """

    conference: str
    season: int
    members: frozenset[str]
    claims: Mapping[str, str]
    # The NCAA level the collect resolves at (``membership.collect_level``):
    # the conference profile's, or for a structural code (independent,
    # non_member) the level of the programmes collected; None only when
    # neither says. Every mapping below was built
    # from that level's stanzas alone (``membership.resolution_stanzas``); a
    # tournament header is read against that level's conferences only
    # (``conference_headers``). Not in ``fingerprint``: the header signature
    # the schedule fingerprint carries beside it is already the level's.
    level: str | None = None
    # An AMBIGUOUS key and every programme of the gender that claims it: one
    # by name, alias or resolving abbreviation and another by a member alias
    # (two stanzas claiming one spelling gender-wide is a collision the
    # config refuses, so every entry here involves a member alias). Only keys
    # with two or more claimants are kept. When no member of the collecting
    # conference claims such a key, the claimant whose point is nearest the
    # collecting school's decides (tl-4sg.9.1).
    claimants: Mapping[str, frozenset[str]] = dataclass_field(default_factory=dict)
    # Every programme's point by slug, from programmes.json, loaded once per
    # collect. A claimant or a collecting school with no point sends the key
    # to the gender-wide rule instead.
    points: Mapping[str, tuple[float, float]] = dataclass_field(default_factory=dict)
    # A key exactly one programme of the gender claims, and only through a
    # member alias: "concordia" is Concordia Irvine's PacWest-only spelling
    # and no stanza's name. Outside that conference's collect the key stays
    # a stranger, because the bare word has meant Concordia Selma and
    # Concordia Texas in the data home. An NCAA Division II tie is the one
    # place it cannot: both sides of one are programmes of the division, so
    # a key that names exactly one of them names that one (``ncaa_side``).
    member_only: Mapping[str, str] = dataclass_field(default_factory=dict)
    # Every programme's configured abbreviation by slug, resolving or not. It
    # never resolves an opponent: it only tells which of a shootout's two
    # known sides a printed initialism names ("T, 1-1 RU wins on PKs, 4-3",
    # rockhurst 2025, where "RU" is display-only because Roosevelt shares it).
    abbreviations: Mapping[str, str] = dataclass_field(default_factory=dict)
    # Every programme of the table by slug, with its home state (USPS) read
    # from the stanza's ``city``, or None when the city names none. A printed
    # state qualifier is held against it (``_state_checked``).
    states: Mapping[str, str | None] = dataclass_field(default_factory=dict)
    # Every plain-folded key a programme of the table claims, by name, alias,
    # resolving abbreviation or member alias, and the programmes claiming it
    # (programmes not yet started that season left out): the candidates a
    # printed state picks between (``state_claimant``).
    spelled: Mapping[str, frozenset[str]] = dataclass_field(default_factory=dict)
    # The gender's programmes OUTSIDE the table (another NCAA level that
    # season), by slug, with their home state. A slug minted from text that
    # equals one of them must not stand for it when the printed state says
    # otherwise ("Union College (Ky.)" is not Union of Tennessee).
    outside_states: Mapping[str, str] = dataclass_field(default_factory=dict)
    # Every identity key a stanza of the gender OUTSIDE the table claims by
    # name, alias or resolving abbreviation ("southern new hampshire",
    # "cal poly pomona"). Text whose whole key is one of them names that
    # school, so the token-subset fallback never reads it as a programme of
    # the table whose key is a subset of it (``_unscoped_slug``).
    foreign: frozenset[str] = frozenset()
    _notes: dict[str, str] = dataclass_field(
        default_factory=dict, compare=False, repr=False
    )
    _lock: threading.Lock = dataclass_field(
        default_factory=threading.Lock, compare=False, repr=False
    )

    def note(self, printed: str, chosen: str, otherwise: str) -> None:
        """Record that ``printed`` read as ``chosen``, not ``otherwise``."""
        self._record(
            printed,
            f"resolution: {printed!r} read as {chosen}, a {self.conference} "
            f"{self.season} member, not {otherwise}",
        )

    def note_distance(
        self, printed: str, owner: str, ranked: Sequence[tuple[str, float]]
    ) -> None:
        """Record that ``printed`` on ``owner``'s page read as the nearest claimant."""
        chosen, nearest = ranked[0]
        others = ", ".join(f"{slug} ({km:,.0f} km)" for slug, km in ranked[1:])
        over = (
            f"over {others}"
            if others
            else f"the only claimant playing in {self.season}"
        )
        self._record(
            printed,
            f"resolution: {printed!r} on {owner}'s page read as {chosen} "
            f"({nearest:,.0f} km) {over}",
        )

    def note_page(self, owner: str, printed: str, line: str) -> None:
        """Record a run-log ``line`` about ``printed`` on ``owner``'s page.

        For a recipe that reads an opponent from a field other than the
        printed one, or declines to: once per page owner and printed text.
        """
        self._record(f"{owner}\x00{printed}", line)

    def _record(self, printed: str, line: str) -> None:
        with self._lock:
            self._notes.setdefault(printed, line)

    def notes(self) -> list[str]:
        """One run-log line per distinct printed text the scope re-pointed."""
        with self._lock:
            return list(self._notes.values())

    def nearest_claimant(self, key: str, owner: str) -> list[tuple[str, float]] | None:
        """The claimants of an ambiguous ``key`` ranked by distance from ``owner``.

        None when the key is not ambiguous, or when the owner or any claimant
        has no point: the tiebreak then never applies and the gender-wide
        rule answers as it always has.
        """
        claimants = self.claimants.get(key)
        if not claimants:
            return None
        origin = self.points.get(owner)
        if origin is None:
            return None
        ranked: list[tuple[str, float]] = []
        for slug in claimants:
            point = self.points.get(slug)
            if point is None:
                return None
            ranked.append((slug, haversine_km(origin, point)))
        ranked.sort(key=lambda pair: (pair[1], pair[0]))
        return ranked

    def state_claimant(self, key: str, state: str) -> str | None:
        """The one programme a key and a printed state name together, or None.

        The candidates are the programmes of the table that claim ``key``
        itself, by name, alias, resolving abbreviation or member alias, read
        through the plain fold (so "boston" is claimed by Boston College and
        Boston University alike). The state decides only when exactly one
        candidate is in it: "Loyola (Md.)" names Loyola Maryland, whose
        Patriot League member alias the bare word is, on every page.

        A programme whose spelling merely BEGINS with the key is no
        candidate. Measured: "Concordia College (Minn.)" on MSU Moorhead's
        and Minot State's pages and "Concordia (Minn.)" on Jamestown's is
        Concordia of Moorhead, a school no stanza configures, and a
        head-word rule handed all three to Concordia-St. Paul, the one
        Minnesota programme whose name begins "Concordia".
        """
        inside = [
            slug for slug in self.spelled.get(key, ()) if self.states.get(slug) == state
        ]
        return inside[0] if len(inside) == 1 else None

    def note_state(self, printed: str, chosen: str, refused: str, state: str) -> None:
        """Record that ``printed``'s state qualifier moved it off ``refused``."""
        home = self.states.get(refused) or self.outside_states.get(refused)
        self._record(
            printed,
            f"resolution: {printed!r} read as {chosen}: it prints {state}, "
            f"and {refused} is in {home}"
            if home
            else f"resolution: {printed!r} read as {chosen}, the one {state} "
            "programme claiming the name",
        )

    def fingerprint(self, owner: str | None = None) -> dict[str, object]:
        """What of the scope shapes a parse, for ``parse_fingerprint``.

        The tiebreak reads the claimants' points and the collecting school's,
        so both enter the fingerprint, but only while a key is ambiguous:
        a scope with none is fingerprinted exactly as before.
        """
        fingerprint: dict[str, object] = {
            "conference": self.conference,
            "season": self.season,
            "claims": dict(sorted(self.claims.items())),
        }
        if self.abbreviations:
            fingerprint["abbreviations"] = dict(sorted(self.abbreviations.items()))
        if self.member_only:
            fingerprint["member_only"] = dict(sorted(self.member_only.items()))
        # A table whose stanzas name no state can be refused nothing, so it
        # fingerprints exactly as before.
        if any(self.states.values()) or self.outside_states:
            fingerprint["states"] = dict(sorted(self.states.items()))
            fingerprint["spelled"] = {
                key: sorted(slugs) for key, slugs in sorted(self.spelled.items())
            }
            fingerprint["outside_states"] = dict(sorted(self.outside_states.items()))
        if self.foreign:
            fingerprint["foreign"] = sorted(self.foreign)
        if self.claimants:
            fingerprint["tiebreak"] = {
                key: {slug: self.points.get(slug) for slug in sorted(slugs)}
                for key, slugs in sorted(self.claimants.items())
            }
            fingerprint["origin"] = None if owner is None else self.points.get(owner)
        return fingerprint


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres between two (lat, lon) points."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    half = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(half))


EARTH_RADIUS_KM = 6371.0088


def resolution_scope(
    schools: list[SchoolConfig],
    gender: str,
    members: set[str],
    *,
    conference: str,
    season: int,
    points: Mapping[str, tuple[float, float]] | None = None,
    level: str | None = None,
    outside: Sequence[SchoolConfig] = (),
) -> ResolutionScope:
    """The scope one collect resolves inside: ``members`` and their claims.

    ``members`` is the membership resolver's answer for the conference-season
    (``conference_members``), never a conference literal; a member with no
    stanza (a dead host recorded membership-only) claims nothing.

    ``schools`` is the collect's level-scoped stanza list
    (``membership.resolution_stanzas``), the same list its identity map is
    built from, so every claimant, member-only alias and tiebreak candidate
    here is a programme at the collecting level that season: a Division I
    stanza can never win a Division II page's text by distance or by being
    the only claimant, nor the reverse. ``level`` is that level, carried
    for the tournament-header reader.

    ``points`` is every programme's point by slug (``programme_points`` over
    the loaded programmes.json), read once per collect; with it the scope can
    break an ambiguous key no member claims by distance. Without it the
    tiebreak never applies.

    Every programme of the table carries its home state (its stanza's
    ``city``), so a printed state qualifier can be held against the
    programme a name resolves to. ``outside`` is the gender's stanzas at
    every other level that season (``membership.outside_stanzas``): they
    never resolve anything here, but a slug minted from text that equals
    one of theirs is checked against their state the same way, and text
    whose whole key one of them claims is never read by the token-subset
    fallback as a programme of the table (``ResolutionScope.foreign``).
    """
    claims: dict[str, str] = {}
    claimed: dict[str, set[str]] = {}
    abbreviations: dict[str, str] = {}
    # Programmes that had not started by this season (an explicit
    # first_season, never inferred from a window): a printed name cannot
    # mean them, so they leave the tiebreak. McKendree's and Rockhurst's 2023
    # pages print "Wayne State College" for the NSIC's Wayne State (Neb.),
    # and the nearest claimant was Wayne State (Mich.), whose women's soccer
    # began in 2026.
    unborn = {
        programme_slug(school.name)
        for school in schools
        if school.gender == gender and school.first_season > season
    }
    # Keys are registered the way the identity map registers them
    # (``_claim_keys``): a folded key an institution word splits between two
    # programmes of the table is claimed by neither, and each spelling that
    # folds to it claims its institution key instead. A member alias is the
    # one claim that may hold a split key bare: it is a conference's own
    # reading of the word, scoped to the collects that read for it.
    split = institution_split_keys(schools, gender)
    spelled: set[str] = set()
    states: dict[str, str | None] = {}
    folded: dict[str, set[str]] = {}
    for school in schools:
        if school.gender != gender:
            continue
        slug = programme_slug(school.name)
        states[slug] = stanza_state(school)
        if slug not in unborn:
            for candidate in (*_identity_spellings(school), *school.member_aliases):
                if key := _identity_key(candidate):
                    folded.setdefault(key, set()).add(slug)
        if school.abbreviation:
            abbreviations[slug] = school.abbreviation
        identity = [
            key
            for candidate in _identity_spellings(school)
            for key in _claim_keys(candidate, split)
        ]
        member = [
            key
            for candidate in school.member_aliases
            for key in (_claim_keys(candidate, split) or (_identity_key(candidate),))
        ]
        for key in (*identity, *member):
            if not key:
                continue
            claimed.setdefault(key, set()).add(slug)
            if slug in members:
                claims[key] = slug
        spelled.update(identity)
    member_only = {
        key: next(iter(slugs - unborn))
        for key, slugs in claimed.items()
        if key not in spelled and len(slugs - unborn) == 1
    }
    return ResolutionScope(
        conference=conference,
        season=season,
        members=frozenset(members),
        claims=claims,
        level=level,
        claimants={
            key: frozenset(slugs - unborn or slugs)
            for key, slugs in claimed.items()
            if len(slugs) > 1
        },
        points=dict(points or {}),
        member_only=member_only,
        abbreviations=abbreviations,
        states=states,
        spelled={key: frozenset(slugs) for key, slugs in folded.items()},
        outside_states={
            programme_slug(school.name): state
            for school in outside
            if school.gender == gender
            and programme_slug(school.name) not in states
            and (state := stanza_state(school)) is not None
        },
        foreign=frozenset(
            key
            for school in outside
            if school.gender == gender and programme_slug(school.name) not in states
            for candidate in _identity_spellings(school)
            if (key := _identity_key(candidate))
        ),
    )


def ncaa_side(
    slug: str,
    aliases: dict[str, str],
    scope: ResolutionScope | None,
    *,
    owner: str,
) -> str:
    """The programme a stranger slug on an NCAA tie names, or the slug.

    Measured: lagoldeneagles.com 2026 women, game 6625, the NCAA second
    round at Irvine, prints "Concordia"; the CCAA collect resolved it to the
    stranger concordia while Concordia Irvine's own page filed the same tie
    under concordia-irvine, so the match stood twice. Only a slug the
    gender-wide rule left unresolved is read again, and only to the one
    programme whose member alias it is (``ResolutionScope.member_only``); a
    key two programmes claim, or none, stays as it was.

    "The only programme" means the only one at the collecting level that
    season: an NCAA tie is between two programmes of one division, and the
    scope's ``member_only`` and the ``aliases`` passed here are both built
    from that level's stanzas (``membership.resolution_stanzas``). Read
    across every stanza of the gender, a Division II tie's stranger could be
    handed to a Division I programme's member alias.
    """
    if scope is None or slug == owner:
        return slug
    key = _identity_key(slug.replace("-", " "))
    chosen = scope.member_only.get(key)
    if (
        chosen is None
        or chosen == slug
        or _unscoped_slug(key, aliases, scope.foreign) != slug
    ):
        return slug
    scope._record(
        f"ncaa:{slug}",
        f"resolution: {slug} on {owner}'s NCAA tie read as {chosen}, the only "
        "programme the spelling names",
    )
    return chosen


def member_alias_collisions(
    schools: list[SchoolConfig],
) -> list[tuple[str, str, str, list[tuple[str, str]]]]:
    """Every member alias another stanza of the same conference also claims.

    One entry per (gender, conference, key): a member alias resolves only
    inside its conference's scope, so the only spelling it may not share is
    one a fellow member claims there, by name, alias, resolving abbreviation
    or member alias. The stanza's ``conference`` field stands for the
    conference here, as it does for a programme with no membership window.
    A member alias that is another conference's whole name is the point of
    the field, not a collision.
    """
    claims: dict[tuple[str, str, str], dict[str, list[tuple[str, str]]]] = {}
    for school in schools:
        slug = programme_slug(school.name)
        fields = [("name", school.name)]
        if school.abbreviation_resolves:
            fields.append(("abbreviation", school.abbreviation))
        fields.extend(("alias", alias) for alias in school.aliases)
        fields.extend(("member_alias", alias) for alias in school.member_aliases)
        for label, candidate in fields:
            key = _identity_key(candidate)
            if not key:
                continue
            owners = claims.setdefault((school.gender, school.conference, key), {})
            owners.setdefault(slug, []).append((slug, label))
    collisions = []
    for (gender, conference, key), owners in claims.items():
        if len(owners) < 2:
            continue
        pairs = [pair for pairs in owners.values() for pair in pairs]
        if any(label == "member_alias" for _, label in pairs):
            collisions.append((gender, conference, key, pairs))
    return collisions


def opponent_slug(
    name: str,
    aliases: dict[str, str],
    *,
    scope: ResolutionScope | None = None,
    owner: str | None = None,
    seeded: bool = False,
) -> str:
    """Resolve a published opponent string to a stable identity, or record it.

    The routes are ``_resolved_slug``'s. Inside a scope, a printed state
    qualifier is then held against the answer (``_state_checked``): a
    programme in another state is not the school the text names.
    """
    slug = _resolved_slug(name, aliases, scope=scope, owner=owner, seeded=seeded)
    if scope is None:
        return slug
    return _state_checked(name, slug, scope)


def _state_checked(name: str, slug: str, scope: ResolutionScope) -> str:
    """``slug``, unless the state ``name`` prints says it is someone else.

    A parenthetical naming a U.S. state ("Columbia College (S.C.)",
    "St. Thomas (TX)", "Loyola (Ill.)") is the site telling its reader which
    of two same-named schools it means, and the fold drops it before any
    route reads the name. So the answer is checked against it afterwards:

    * a programme of the table whose stanza is in the printed state, or
      whose stanza names no state, stands, exactly as before;
    * otherwise, when exactly one programme of the table that claims the
      key is in the printed state, that one is the school: "Loyola (Md.)" is
      Loyola Maryland on every page, not only on the pages of the conference
      whose member alias the bare word is, and "Lincoln (Pa.)" is Lincoln
      (Pa.) wherever distance would have picked Lincoln of Missouri
      (``ResolutionScope.state_claimant``);
    * otherwise a programme in another state is refused, and so is a slug
      minted from text that equals a programme of another level in another
      state ("Union College (Ky.)", not Union of Tennessee). The side mints
      the key with the state kept, ``{key}-{state}`` ("columbia-sc",
      "saint-thomas-tx", "lincoln-pa"), so two same-named schools never
      share a slug and the bare name's slug is never taken from the
      programme that owns it;
    * a text with no state qualifier, or a slug no programme owns, is
      untouched: "Emmanuel (Ga.)" still mints ``emmanuel``.
    """
    state = printed_state(name)
    if state is None:
        return slug
    if slug in scope.states and scope.states[slug] in (None, state):
        return slug
    key = _identity_key(name)
    if not key:
        return slug
    printed = _clean_team_name(name)
    chosen = scope.state_claimant(key, state)
    if chosen is not None:
        if chosen != slug:
            scope.note_state(printed, chosen, slug, state)
        return chosen
    if slug in scope.states or scope.outside_states.get(slug, state) != state:
        minted = programme_slug(f"{key} {state}")
        scope.note_state(printed, minted, slug, state)
        return minted
    return slug


def _resolved_slug(
    name: str,
    aliases: dict[str, str],
    *,
    scope: ResolutionScope | None = None,
    owner: str | None = None,
    seeded: bool = False,
) -> str:
    """Resolve a published opponent string by name alone, or record it.

    With a ``scope`` (the conference-season a collect is reading for), a key
    one of its members claims resolves to that member before any other
    programme, and the scope notes the re-pointing when the gender-wide map
    would have read it otherwise. Without one, or for every key no member
    claims, the gender-wide rule below applies unchanged.

    One exception sits between the two (tl-4sg.9.1): an AMBIGUOUS key, one
    that folds to one programme's name or aliases and to another's member
    aliases, which no member of the collecting conference claims. A CCAA
    page prints "Dominican" for Dominican of California, a non-conference
    opponent, and the gender-wide map reads the CACC's Dominican. Such a key
    resolves to the claimant whose point (programmes.json) is nearest the
    collecting school's, ``owner``; the scope logs the re-pointing once per
    printed text. With no ``owner``, or when the owner or any claimant has
    no point, the key falls to the gender-wide rule. A key with a single
    claimant is never touched.

    The fallback is deliberately conservative. A bare substring test treats a
    PREFIX as an identity — "Southwestern" sits inside "southwestern oklahoma
    state" — so the rule is instead that every token of a configured school's
    name must appear in the published string, and that school must be the only
    such match. A one-token alias is never enough on its own, because a bare
    surname-like token matches far too much.

    A string with an institution word is first looked up under its
    institution key, the fold with that word kept: "Boston College" and
    "Boston University" both fold to "boston", and a table whose stanzas
    hold both withdraws "boston" and holds each under its institution key
    (``institution_split_keys``). Only such a table holds institution keys,
    so everywhere else the lookup is the folded key's, unchanged; bare
    "Boston" there names neither school and mints its slug from the text.

    When nothing resolves, the normalized key becomes the slug rather than the
    raw string. That alone folds "Delta St." onto "Delta State" and "Oklahoma
    Christian University" onto "Oklahoma Christian". Genuinely opaque
    abbreviations such as "DBU" still stand apart from "Dallas Baptist": no
    algorithm should guess that, and guessing is what produced the defect above.
    """
    key = _identity_key(name)
    if not key:
        return programme_slug(_clean_team_name(name))
    foreign = frozenset() if scope is None else scope.foreign
    # An institution key ("boston college") is held only for a folded key an
    # institution word splits (``institution_split_keys``), so it is tried
    # first and can only ever name one of those programmes; every other
    # string falls straight through to its folded key, as before.
    institution = _institution_key(name)
    if institution and institution != key:
        if scope is not None and institution in scope.claims:
            chosen = scope.claims[institution]
            otherwise = aliases.get(institution) or _unscoped_slug(
                key, aliases, foreign
            )
            if chosen != otherwise:
                scope.note(_clean_team_name(name), chosen, otherwise)
            return chosen
        if institution in aliases:
            return aliases[institution]
    key = _division_seed_key(name, key, aliases, scope, seeded=seeded)
    if scope is not None and key in scope.claims:
        chosen = scope.claims[key]
        otherwise = _unscoped_slug(key, aliases, foreign)
        if chosen != otherwise:
            scope.note(_clean_team_name(name), chosen, otherwise)
        return chosen
    if scope is not None and owner is not None:
        ranked = scope.nearest_claimant(key, owner)
        if ranked is not None:
            chosen = ranked[0][0]
            if chosen != _unscoped_slug(key, aliases, foreign):
                scope.note_distance(_clean_team_name(name), owner, ranked)
            return chosen
    return _unscoped_slug(key, aliases, foreign)


# A conference that seeds its tournament by division can spell the division
# out as a word after the seed: bloomsburgathletics.com 2026 (women, game
# 18292) prints "<span>#4 East</span>" before "Millersville University", so
# the rank prefix strips "#4" and leaves "East Millersville", minted as
# east-millersville beside Millersville's own record of the same match. The
# word cannot be stripped by grammar: "#2 West Chester" and "#4 East
# Stroudsburg" are ranked schools whose names begin with it. So the word goes
# only when everything else agrees it is not a name: the string carried a
# rank prefix, the whole key is claimed by no programme and no member, and
# the rest of the key is claimed by a MEMBER of the collecting conference,
# the only side a conference tournament's seed is ever printed for. The
# schedule parsers clean the rank off before they resolve, so they pass
# ``seeded`` from the raw string; a name that still carries its rank (the
# standings check) is read directly.
_DIVISION_WORDS = frozenset({"east", "west", "north", "south"})


def _division_seed_key(
    name: str,
    key: str,
    aliases: dict[str, str],
    scope: ResolutionScope | None,
    *,
    seeded: bool = False,
) -> str:
    """The key without a spelled-out division word after a seed, or the key."""
    if scope is None or not (seeded or _seeded(name)):
        return key
    head, _, rest = key.partition(" ")
    if (
        head in _DIVISION_WORDS
        and rest
        and key not in aliases
        and key not in scope.claims
        and rest in scope.claims
    ):
        return rest
    return key


def _unscoped_slug(
    key: str, aliases: dict[str, str], foreign: frozenset[str] = frozenset()
) -> str:
    """The table-wide rule: exact claim, unique multi-token match, or the key.

    "Table-wide" is the ``aliases`` given: on the collection path that is
    one gender's stanzas at the collecting level for the season
    (``membership.resolution_stanzas``), so the token-subset fallback can
    only ever pick a programme of that level. Over every level at once,
    "Penn State Abington" is a token superset of Division I "Penn State" and
    re-points to it, and "North Carolina Wesleyan" to "North Carolina".

    The level scope keeps the other level's programmes out of the table,
    but not out of the text: a Division I page still prints "Southern New
    Hampshire", and inside the Division I table that key holds every token
    of "New Hampshire". Measured over the 848 archived Division I pages at
    10a1308, the subset read "Southern New Hampshire" (Dartmouth, Merrimack)
    as New Hampshire and "Cal Poly Pomona" (CSUN, San Diego) as Cal Poly.
    So a key that is ``foreign``, claimed whole by a stanza of the gender at
    another level, names that school: the subset is not tried and the key
    mints its own slug. An exact claim still wins first ("Charleston" on a
    Division I page is the College of Charleston, though a Division II
    Charleston claims the word too).
    """
    if key in aliases:
        return aliases[key]
    if key in foreign:
        return programme_slug(key)

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


def _status_word(text: str) -> str | None:
    """The status a result cell or status string spells out, if any.

    A status word outranks every other signal on the row: a completed class,
    a Final span, a score. Staten Island's 2026 schedule carried the Aug 27
    row v Assumption on a past date with the completed class and a result
    cell reading "Make Up Date TBD" (archived 2026-09-03); reading the class
    alone stored it final with no score, and the site's fold refused it
    against Assumption's cancelled record. Rescheduling is spelled several
    ways across skins ("Postponed", "PPD", "Make Up Date TBD", "Makeup TBA")
    and all of them mean postponed.

    Three more spellings, each measured in the archive (beads tl-d69,
    tl-md2), join the postponed family: "Rescheduled for 10/21" (eckerd
    2024, game 8371, result cell), "Post." (barry 2025, game 14613, result
    cell beside a Final span; the abbreviation needs its period so "Post"
    in a name stays a name) and "Suspended Due To Lightning" (georgian-court
    2025, game 6377; also pitt-johnstown 2023, game 5521, "SUSPENDED-TO BE
    FINISHED 10/30"). A suspended match is unfinished, which is what
    postponed means here: no score, to be completed on another date.

    The word is read from the whole row, not only the result cell, because
    the skins print it in different places: daemen 2023, game 7070 (list
    skin), carries "PPD to 10/25" in a game-cancelled div and no result
    element; colorado-christian 2025, game 7363, carries "Postponed Due to
    Inclement Weather" in a promotion span beside a result cell reading
    "I, -". Outside the cell the word ranks below a parsed score: the
    reparse of every archived schedule page (2026-09-03, 721 pages) found
    31 rows where a W/L/T score and such a word share a row, every one a
    played make-up date still naming the date it was moved from (caldwell
    2023, game 6141, "rescheduled from 9/23" beside "L, 2-3";
    florida-southern 2023, game 19817, "Rescheduled from 8/31 due to
    Hurricane Idalia" beside "L, 2-3"; davis-elkins 2023, game 8463,
    "Completion of Sept. 10 Suspended Contest" beside "L, 0-1"), and none
    where the word stood in the result cell itself. So the DOM caller asks
    the row's other text only when the cell parsed no score.
    """
    if re.search(r"cancel", text, re.IGNORECASE):
        return "cancelled"
    if re.search(
        r"postpon|make[\s-]?up|\bppd\b|reschedul|\bpost\.|suspend", text, re.IGNORECASE
    ):
        return "postponed"
    return None


_EVENT_STATUS_LETTERS = {"C": "cancelled", "P": "postponed"}


def _event_status(event: dict[str, object]) -> str:
    """The status the payload's own words derive, before the score check.

    A status naming Final is provisional: ``parse_schedule_page`` demotes a
    final that stores no oriented score pair to scheduled (beads tl-d69,
    tl-md2). The earlier reading, that a played game whose score was never
    entered is final, is retired: two collectors of one match must agree on
    played-versus-unplayed, the opponent's own page for such a row reads
    scheduled (newman 2023, game 6929, v Oklahoma Christian; ouachita-baptist
    2024, game 5655, v Delta State), and the site's fold refuses the
    contradiction. Final requires scores.
    """
    result = event.get("result")
    result_dict = result if isinstance(result, dict) else {}
    status = str(result_dict.get("status") or event.get("status") or "").lower()
    word = _status_word(status)
    if word is not None:
        return word
    # The event's own status is a single letter, not a word (bead tl-0y9u):
    # A upcoming, O over, C cancelled, P postponed. Measured across the
    # 1,073 archived schedule pages (2026-10-18): every C or P event the
    # rendered list also carries reads Canceled or Postponed there, and none
    # holds a score. Read as a word, "c" matched nothing, and catawba 2026,
    # game 7931 at Davis & Elkins, printed Canceled and stored scheduled.
    letter = _EVENT_STATUS_LETTERS.get(str(event.get("status") or "").strip().upper())
    if letter is not None:
        return letter
    if event.get("type") == "live" or "live" in status or "progress" in status:
        return "live"
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


def _dom_aria_time(row: object) -> str | None:
    """Read the kickoff a completed game-list row publishes only in aria-labels.

    Measured csidolphins.com 2026: an upcoming row prints its time in
    ``span.sidearm-schedule-game-time`` ("2:30 PM") and repeats it in the
    opponent link's aria-label ("Dominican University (N.Y.) on September 5
    2:30 PM"); every one of the twelve rows carrying both agrees.  A completed
    row (12026, "Make Up Date TBD"; 12027, final) renders no time element at
    all, so its kickoff, "Assumption University on August 27 1:00 PM" and
    matching Assumption's own 13:00, is read from the labels in document
    order, the opponent link first.  The label is the page's own local-time
    wording, so it is parsed as rendered text, never shifted.
    """
    for link in row.select("a[aria-label]"):  # type: ignore[attr-defined]
        label = str(link.get("aria-label") or "")
        if not re.search(r"\b(?:on|at)\b", label):
            continue
        time = _dom_time(label)
        if time:
            return time
    return None


def _dom_result(text: str) -> tuple[str, int, int] | None:
    """Parse a result like ``W, 2-0`` or ``T, 1-1 (2OT)`` as it is printed.

    The two numbers are returned in PAGE ORDER, which is not an orientation:
    ``_oriented_scores`` decides which is the owner's. See it for why.
    """
    match = re.search(r"\b([WLT])\s*,?\s*(\d+)\s*-\s*(\d+)", text)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


# A shootout decides advancement, not goals: the printed score is the draw
# and the letter says who went through. Measured: lincoln 2025, game 4402,
# "W, 1-1 (SO, 4-3)"; delta-state 2020, game 12951, "W, 1-1 (PK-5-4)".
# Word-bounded so "so" inside a word and "pens" inside a name stay text.
_SHOOTOUT_MARKER = re.compile(r"\b(?:pks?|so|shootout|penalties|pens)\b", re.IGNORECASE)

# A forfeit is a decided match with no measured scoreline. The one archived
# form (upper-iowa 2024, game 9017; every archived schedule page grepped
# 2026-09-04, two hits, both that row's mobile and desktop renders) is a
# promotion reading "Win by forfeit" beside a result cell of "W, 2-2". The
# rule also admits "Loss by forfeit", "forfeited" and a bare "(forfeit)".
# Word bounded so a name never carries it.
_FORFEIT_MARKER = re.compile(r"\bforfeit(?:ed|s)?\b", re.IGNORECASE)


def _forfeit_marked(*texts: str) -> bool:
    return any(_FORFEIT_MARKER.search(text) for text in texts)


def _forfeit_side(letter: str | None, *, owner_is_home: bool) -> str | None:
    """The side a forfeit was awarded to, ``home`` or ``away``, from the letter.

    W on the owner's page awards the owner's side, L the opponent's. A row
    carrying the word with no letter names no side, so no forfeit is set and
    the row falls to the ordinary refusal (bead tl-wyv: never a forfeit
    without the word, never a side the page did not award).
    """
    if letter == "W":
        return "home" if owner_is_home else "away"
    if letter == "L":
        return "away" if owner_is_home else "home"
    return None


def _forfeit_scores(side: str) -> tuple[int, int]:
    """The sport's 1-0 convention as a (home_score, away_score) pair."""
    return (1, 0) if side == "home" else (0, 1)


# ---------------------------------------------------------------------------
# Postseason stage.
#
# SideArm groups a run of schedule rows under ``div.sidearm-schedule-
# tournament``, a ``<p>`` header naming the group and a ``<ul>`` of rows
# (lincoln 2025: "GLVC Championship", then "NCAA Division II Championship").
# The same markup wraps groups that are not postseason at all. Measured over
# every archived men's schedule 2016-2026: "Senior Day", "Homecoming",
# "Preseason", "Colorado Mesa Men's Soccer Showcase", "Adelphi Kick-Off
# Tournament", "Georgian Court Univ. Tournament", "CBU Invitational
# Tournament", and "NCCAA National Championships", which is another
# governing body's postseason. So the block alone says nothing, and neither
# does a championship word alone. The header must name the competition:
#
# * NCAA, as a word, beside a postseason word: "NCAA Tournament", "NCAA II
#   Final Four", "NCAA Division II Super Region 3". Another body ("NCCAA",
#   "USCAA", "NAIA", "NJCAA") is a postseason this contract has no
#   competition for, so its rows are stamped ``unknown`` and never counted
#   as either split.
# * A conference, beside a championship word: the word "conference", a
#   conference code the membership reference lists ("GLVC Championship",
#   "GAC/MIAA Men's Soccer Championship"), or one of the long names the
#   archive prints without either ("Northeast 10 Championship", "Great
#   Midwest Tournament", "GULF SOUTH CHAMPIONSHIPS"). Codes and names are
#   both data: the reference's ``conference_profiles`` (``ConferenceHeaders``
#   below). No conference is named in this module.
#
# The round is the row's own ``.sidearm-schedule-game-promotion-name``, kept
# verbatim and only when it names a round: the same element carries "Watch
# on YouTube", "Kids 12 & under free" and "Note Time Change" inside these
# blocks. Placement in a bracket is the site's to derive; this is the label.
_NCAA_BODY = re.compile(r"\bNCAA\b")
_NCAA_POSTSEASON_WORD = re.compile(
    r"\b(?:tournament|championships?|regionals?|super\s+region|final\s+four"
    r"|elite\s+eight|rounds?|(?:quarter|semi)-?finals?)\b",
    re.IGNORECASE,
)
_OTHER_BODY = re.compile(r"\b(?:NCCAA|USCAA|NAIA|NJCAA)\b", re.IGNORECASE)
# The Division I championship's final rounds, its semifinals and final, are
# the College Cup: "NCAA College Cup", "College Cup Semifinal", "College Cup
# Final". The phrase is the NCAA's alone, so it names the competition with
# or without the body beside it, and it is a round. Measured 2026-11-15: no
# archived Division II schedule page (2,313, both genders, 2016-2026) prints
# it, so no Division II row is read differently.
_COLLEGE_CUP = re.compile(r"\bcollege\s+cup\b", re.IGNORECASE)
_CHAMPIONSHIP = r"(?:tournament|championships?|final\s+four)\b"
_CHAMPIONSHIP_WORD = re.compile(rf"\b{_CHAMPIONSHIP}", re.IGNORECASE)
_CONFERENCE_WORD = re.compile(r"\bconference\b", re.IGNORECASE)
_ROUND_WORD = re.compile(
    r"\b(?:rounds?|(?:quarter|semi)-?finals?|finals?|championship|final\s+four"
    r"|elite\s+eight|college\s+cup)\b",
    re.IGNORECASE,
)

# What may stand between a one-word name and the championship word it
# qualifies: the season, the gender, the sport ("American Men's Soccer
# Championship"). Anything else between them is another event's name.
_HEADER_QUALIFIER = r"(?:\d{4}|(?:wo)?men['’]?s|soccer)"
_NEVER = r"(?!x)x"


class ConferenceHeaders:
    """How a tournament header names a conference, read from the reference.

    Built from the membership document's ``conferences`` and
    ``conference_profiles``, never from a table here, so a conference added
    to the reference is recognised in a header the day it is added. A
    conference is named by:

    * its code as a bare token, any case ("GLVC Championship", "PacWest
      Tournament"), unless its profile says ``code_is_word``: a code that is
      an ordinary English word (PATRIOT, SUMMIT, IVY) would read "Patriot
      Invitational Tournament" and "Summit City Tournament" as conference
      postseason, so such a code never names its conference alone;
    * one of its profile's ``names`` as a whole phrase, any case, a space or
      hyphen in the name matching any run of either ("Northeast-10" reads
      "Northeast 10 Championship"; "Great Midwest" reads "Great Midwest
      Tournament");
    * a ``names`` entry that is a single alphabetic word ("American"), only
      where it directly qualifies the championship word, with nothing but
      the season, gender and sport between: "American Championship" and
      "American Men's Soccer Championship", never "American International
      Tournament". One word is not a phrase; alone it is as ambiguous as a
      word code.

    A declared code with no profile is still read as a bare token, as it
    was before profiles existed, so an older mirrored reference degrades to
    the code rule instead of to nothing.

    With a ``level`` only that level's conferences (and any declared code
    with no profile) are read: a collect reads its pages for its own
    level's postseasons, as it resolves their opponent text against its own
    level's stanzas. A Division II page that printed a Division I
    conference's name beside a championship word would otherwise be stamped
    a conference postseason the day that name landed.

    The other levels' conferences are still known, for one question only
    (``names_another_level``): a header the generic word "conference"
    would classify ("Big Ten Conference Tournament" on a Division II page)
    is another level's postseason when the names it carries are all another
    level's. So the other levels' names do steer this level's reading, and
    the signature carries them beside the level's own.
    """

    def __init__(
        self, document: Mapping[str, object], level: str | None = None
    ) -> None:
        declared = [
            str(code)
            for code in document.get("conferences") or []  # type: ignore[union-attr]
            if code not in STRUCTURAL_CODES
        ]
        profiles = conference_profiles(dict(document))
        sources: dict[str, list[str]] = {}
        signature: list[tuple[str, bool, tuple[str, ...]]] = []
        for code in sorted({*declared, *profiles}):
            profile = profiles.get(code)
            if level is not None and profile is not None and profile.level != level:
                continue
            code_is_word = profile is not None and profile.code_is_word
            names = () if profile is None else profile.names
            signature.append((code, code_is_word, names))
            alternatives = sources.setdefault(code, [])
            if not code_is_word:
                alternatives.append(rf"(?<![\w-]){re.escape(code)}(?![\w-])")
            # Longest name first, so the span a name claims is its widest.
            for name in sorted(names, key=len, reverse=True):
                words = [word for word in re.split(r"[\s-]+", name) if word]
                if not words:
                    continue
                if len(words) == 1 and words[0].isalpha():
                    alternatives.append(
                        rf"(?<![\w-]){re.escape(words[0])}"
                        rf"(?=(?:\s+{_HEADER_QUALIFIER})*\s+{_CHAMPIONSHIP})"
                    )
                else:
                    phrase = r"[\s-]+".join(re.escape(word) for word in words)
                    alternatives.append(rf"(?<!\w){phrase}(?!\w)")
        self._patterns = {
            code: re.compile("|".join(alternatives), re.IGNORECASE)
            for code, alternatives in sources.items()
            if alternatives
        }
        self._any = re.compile(
            "|".join(pattern.pattern for pattern in self._patterns.values()) or _NEVER,
            re.IGNORECASE,
        )
        #: Every conference of every level, for ``names_another_level``;
        #: None when this reader is already every level's.
        self._every_level: ConferenceHeaders | None = (
            None if level is None else ConferenceHeaders(document, None)
        )
        #: What of the reference shapes a header's reading, for
        #: ``parse_fingerprint``: the names used to live in this module's
        #: source, which the fingerprint hashes, and a name edited in the
        #: data must re-read the archive the same way. A levelled reader's
        #: signature carries the other levels' entries after its own.
        self.signature: list[object] = list(signature)
        if self._every_level is not None:
            self.signature.append(
                [
                    entry
                    for entry in self._every_level.signature
                    if isinstance(entry, tuple) and entry[0] not in self._patterns
                ]
            )

    def names_a_conference(self, header: str) -> bool:
        """Whether the header carries any of this reader's conferences' codes
        or printed names.

        A levelled reader decides with every level's names in view, so a
        name of its own level printed inside another level's longer name is
        the longer one's (``named``): a Division I reader does not take
        "Great American Conference Tournament" for the American's because
        "American Conference" sits inside it.
        """
        if self._every_level is None:
            return self._any.search(header) is not None
        return any(code in self._patterns for code in self._every_level.named(header))

    def names_another_level(self, header: str) -> bool:
        """Whether every conference the header names is another level's.

        Read with every level's names (``named``, so a name inside a longer
        one is the longer one's): true when the header names at least one
        conference and none of them is this reader's. Always false for a
        reader of every level.
        """
        if self._every_level is None:
            return False
        named = self._every_level.named(header)
        return bool(named) and not any(code in self._patterns for code in named)

    def named(self, header: str) -> list[str]:
        """The conferences the header names, in the order it names them.

        A name inside another conference's longer name is the longer one's:
        "Great American Conference Tournament" is the Great American's, not
        also a conference printed as "American Conference". A name two
        conferences are both printed under ("Great Lakes") names both.
        """
        spans: list[tuple[int, int, str]] = []
        for code, pattern in self._patterns.items():
            spans.extend(
                (match.start(), match.end(), code) for match in pattern.finditer(header)
            )
        kept = [
            (start, end, code)
            for start, end, code in spans
            if not any(
                other_start <= start
                and end <= other_end
                and (other_end - other_start) > (end - start)
                for other_start, other_end, _ in spans
            )
        ]
        named: list[str] = []
        for _, _, code in sorted(kept):
            if code not in named:
                named.append(code)
        return named


_conference_headers_cache: dict[str | None, ConferenceHeaders] = {}


def conference_headers(level: str | None = None) -> ConferenceHeaders:
    """The header reader for the loaded membership reference, built once per level.

    ``level`` None reads every conference; a collect passes its own level
    (``ResolutionScope.level``).
    """
    if level not in _conference_headers_cache:
        _conference_headers_cache[level] = ConferenceHeaders(load_membership(), level)
    return _conference_headers_cache[level]


def conference_header_signature(level: str | None = None) -> object:
    """The reference's contribution to a schedule parse's fingerprint.

    The signature of the reader the parse uses: the collecting level's
    (``conference_headers``). None on an install with no readable membership
    reference, where a collect already runs on the stanza defaults.
    """
    try:
        return conference_headers(level).signature
    except (OSError, ValueError):
        return None


def tournament_stage(
    header: str,
    *,
    headers: ConferenceHeaders | None = None,
    level: str | None = None,
) -> dict[str, str] | None:
    """The stage a tournament block's header publishes, or nothing.

    Nothing means the block is not a postseason (a senior day, an
    invitational): its rows are classified like any row outside a block.
    ``headers`` is how a conference is recognised; by default the loaded
    membership reference's at ``level`` (``conference_headers``).
    """
    text = " ".join(header.split())
    if not text:
        return None
    if (_NCAA_BODY.search(text) and _NCAA_POSTSEASON_WORD.search(text)) or (
        _COLLEGE_CUP.search(text) and not _OTHER_BODY.search(text)
    ):
        return {"phase": "postseason", "competition": "ncaa", "source": text}
    if _OTHER_BODY.search(text):
        return {"phase": "unknown", "source": text}
    if _CHAMPIONSHIP_WORD.search(text):
        reader = headers or conference_headers(level)
        # A conference of the reading level named outright, or the generic
        # word ("Conference Tournament", the unnamed header) unless the
        # header names only another level's conferences: "Big Ten Conference
        # Tournament" on a Division II page is no Division II postseason,
        # exactly as "Big Ten Tournament" is not.
        if reader.names_a_conference(text) or (
            _CONFERENCE_WORD.search(text) and not reader.names_another_level(text)
        ):
            return {
                "phase": "postseason",
                "competition": "conference",
                "source": text,
            }
    return None


def _dom_stages(
    rows: Sequence[object],
    dates: Mapping[int, str],
    *,
    level: str | None = None,
) -> dict[int, dict[str, str]]:
    """Each row's stage, keyed by ``id(row)``; a row with no stage is absent.

    A row inside a postseason block takes the block's stage and its own
    round label. ``regular`` is evidence-tiered like the conference flag: it
    is stamped only on a page that marks at least one postseason block, and
    only on rows dated before that page's first postseason row. A page that
    groups nothing says nothing about phase, so its rows carry no stage and
    the site reads them as unknown, never as regular season. A row after the
    first postseason date but outside every block is left unknown too
    (bentley 2025 prints "NCAA Championship Second Round" in a promotion on
    a row no block holds; the promotion element also carries "Stats and
    Results will not count per NCAA rules", so it never classifies).

    A row outside every postseason block may still name its competition in
    the opponent cell's annotation, the same place round text already rides
    ("No. 2E West Chester (PSAC Quarterfinal)"): roberts-wesleyan 2025, game
    5530, "Wilimington (DE) University (NCAA Division II Tournament First
    Round at Franklin Pierce University)", the one NCAA tie of 39 published
    nowhere else on that page. Measured over every archived men's schedule
    2022-2026, seven annotations name a postseason, all read by the header
    rule ("Conference Carolinas Championship First Round", "East Coast
    Conference Tournament").
    """
    stages: dict[int, dict[str, str]] = {}
    for row in rows:
        stage: dict[str, str] | None = None
        block = row.find_parent("div", class_="sidearm-schedule-tournament")  # type: ignore[attr-defined]
        if block is not None:
            header = block.find("p", recursive=False)
            stage = tournament_stage(
                header.get_text(" ", strip=True) if header else "", level=level
            )
            if stage is not None and stage["phase"] == "postseason":
                stage = dict(stage)
                label = _first_text(row, ".sidearm-schedule-game-promotion-name")
                if label and _ROUND_WORD.search(label):
                    stage["round_published"] = " ".join(label.split())
        if stage is None:
            opponent = _first_text(row, ".sidearm-schedule-game-opponent-name") or ""
            for annotation in _PARENTHETICAL.findall(opponent):
                found = tournament_stage(annotation.strip("() "), level=level)
                if found is not None and found["phase"] == "postseason":
                    stage = dict(found)
                    if _ROUND_WORD.search(found["source"]):
                        stage["round_published"] = found["source"]
                    break
        if stage is not None:
            stages[id(row)] = stage
    postseason_dates = [
        dates[key]
        for key, stage in stages.items()
        if stage["phase"] == "postseason" and key in dates
    ]
    if not postseason_dates:
        return stages
    first = min(postseason_dates)
    for row in rows:
        key = id(row)
        if key in stages or key not in dates:
            continue
        if dates[key] < first:
            stages[key] = {"phase": "regular"}
    return stages


# ---------------------------------------------------------------------------
# Shootouts.
#
# A level tie decided on penalties prints the shootout beside the draw, and
# the archive (2025, every NCAA level tie) spells it eight ways:
#
#   "W, 1-1 (SO, 4-3)"                    lincoln: the leading letter
#   "T, 0-0 (W by PK, 5-4)"               an inner letter
#   "T, 0-0 (W, 3-2 PK)"                  an inner letter
#   "T, 1-1 (L, 8-7 PK)"                  anderson: an inner letter, winner's
#                                         count first
#   "T, 1-1 RU wins on PKs, 4-3"          rockhurst: a side named
#   "T, 3-3 (UCCS Advances on PKs 4-2)"   a side named
#   "T, 2-2 (PLNU Advances on PK's, 3-2)" a side named
#   "T, 0-0 , 2-3 Penalty Kicks"          lincoln-memorial: own count first,
#                                         no letter, no name
#
# The winner is read from a letter or a name, never from digit order:
# anderson prints the winner's count first, lincoln-memorial its own. The
# winner takes the larger count; equal counts are refused. A name counts
# only when it names exactly one of the tie's two sides, by the identity map
# or by a side's configured abbreviation. A row that says shootout and names
# no winner keeps its printed text and no shootout.
_SHOOTOUT_WORDS = re.compile(
    r"\b(?:pks?|so|shootout|penalties|pens|penalty\s+kicks?)\b", re.IGNORECASE
)
_SCORE_PAIR = re.compile(r"(\d+)\s*-\s*(\d+)")
_INNER_LETTER = re.compile(r"\(\s*([WL])\b")
# The owner's verdict as a word, opening what follows the score: "(Lost 4-2
# in PKs)" on harding's page, "Lost 4-3 in PK's" on lenoir-rhyne's. Anchored,
# so "(Quincy won …)" is somebody's name and goes to the named-winner rule.
_OWNER_WORD = re.compile(r"^[\s,(]*(won|win|lost|loss)\b", re.IGNORECASE)
_NAMED_WINNER = re.compile(
    r"([A-Za-z][\w.&'’ -]*?)\s+(?:advances|advanced|wins|won)\b", re.IGNORECASE
)


def _names_side(
    name: str,
    sides: tuple[str, str],
    *,
    aliases: Mapping[str, str],
    scope: ResolutionScope | None,
) -> str | None:
    """The one side of ``sides`` a printed name identifies, or nothing."""
    printed = " ".join(name.split()).strip(" .,(")
    if not printed:
        return None
    # The keys in ``opponent_slug``'s order, institution key first, and the
    # first one that names a side decides: "Union University" is read under
    # its institution key and never also under its folded "union", which
    # Union College's member alias claims, or every institution-qualified
    # name of a split pair would name both sides again.
    hits: set[str] = set()
    for key in _lookup_keys(printed):
        hits = {
            resolved
            for resolved in (
                aliases.get(key),
                scope.claims.get(key) if scope is not None else None,
            )
            if resolved in sides
        }
        if hits:
            break
    if scope is not None:
        for side in sides:
            abbreviation = scope.abbreviations.get(side, "")
            if abbreviation and abbreviation.casefold() == printed.casefold():
                hits.add(side)
    return next(iter(hits)) if len(hits) == 1 else None


def reoriented_shootout(
    shootout: Mapping[str, object], *, home: str, to_home: str
) -> dict[str, object]:
    """A shootout read with ``home`` as the home side, told with ``to_home``."""
    if home == to_home:
        return dict(shootout)
    return {
        "winner": shootout["winner"],
        "home": shootout["away"],
        "away": shootout["home"],
    }


def shootout_published(result_text: str) -> bool:
    """Whether a result cell prints a shootout beside a level score."""
    main = re.search(r"\b([WLT])\s*,?\s*(\d+)\s*-\s*(\d+)", result_text)
    if main is None or main.group(2) != main.group(3):
        return False
    return bool(_SHOOTOUT_WORDS.search(result_text[main.end() :]))


def parse_shootout(
    result_text: str,
    *,
    owner_slug: str,
    other_slug: str,
    owner_is_home: bool,
    aliases: Mapping[str, str],
    scope: ResolutionScope | None = None,
) -> dict[str, object] | None:
    """``{winner, home, away}`` for a shootout the cell decides, else nothing."""
    if not shootout_published(result_text):
        return None
    main = re.search(r"\b([WLT])\s*,?\s*(\d+)\s*-\s*(\d+)", result_text)
    assert main is not None
    rest = result_text[main.end() :]
    counts = _SCORE_PAIR.search(rest)
    if counts is None:
        return None
    first, second = int(counts.group(1)), int(counts.group(2))
    if first == second:
        return None
    winner: str | None = None
    lead = main.group(1)
    inner = _INNER_LETTER.search(rest)
    word = _OWNER_WORD.search(rest)
    if lead in {"W", "L"}:
        winner = owner_slug if lead == "W" else other_slug
    elif inner is not None:
        winner = owner_slug if inner.group(1) == "W" else other_slug
    elif word is not None:
        winner = owner_slug if word.group(1).lower().startswith("w") else other_slug
    else:
        named = _NAMED_WINNER.search(rest)
        if named is not None:
            winner = _names_side(
                named.group(1),
                (owner_slug, other_slug),
                aliases=aliases,
                scope=scope,
            )
    if winner is None or owner_slug == other_slug:
        return None
    high, low = max(first, second), min(first, second)
    winner_is_home = (winner == owner_slug) == owner_is_home
    return {
        "winner": winner,
        "home": high if winner_is_home else low,
        "away": low if winner_is_home else high,
    }


def _oriented_scores(
    letter: str | None,
    first: int,
    second: int,
    *,
    fixture_id: str,
    result_text: str = "",
    forfeit: bool = False,
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
    be put right by swapping and is refused: the row stores no score, and
    since final requires scores (beads tl-d69, tl-md2) the callers store it
    scheduled and name it, which the coverage and twin checks see rather
    than a reversed result nothing would catch.

    One exception, decided by ``result_text``: a W or L beside EQUAL numbers
    is the drawn score of a match settled on penalties when the result text
    carries a shootout marker (``_SHOOTOUT_MARKER``; lincoln 2025, game
    4402, "W, 1-1 (SO, 4-3)"; delta-state 2020, game 12951, "W, 1-1
    (PK-5-4)"). The letter records advancement, the numbers are the goals,
    and the pair is stored as the draw and logged at info.

    The second exception is ``forfeit``, which the callers set when the row
    carries the word (``_FORFEIT_MARKER``): upper-iowa 2024, game 9017,
    prints "W, 2-2" with a promotion reading "Win by forfeit". A forfeit's
    scoreline is not a measured result, so the letter is not asked to agree
    with it: the level pair is stored as printed and logged at info, and the
    caller records the awarded side in the fixture's ``forfeit`` field (bead
    tl-wyv, closing tl-49e). Without either marker the refusal stands.
    """
    if letter in {"W", "L"} and first == second:
        if _SHOOTOUT_MARKER.search(result_text):
            _LOG.info(
                "%s: %s beside a level score %s-%s with a shootout marker (%r); "
                "stored as the draw",
                fixture_id,
                letter,
                first,
                second,
                result_text,
            )
            return first, second
        if forfeit:
            _LOG.info(
                "%s: %s beside a level score %s-%s on a forfeit row (%r); "
                "stored as printed",
                fixture_id,
                letter,
                first,
                second,
                result_text,
            )
            return first, second
    elif letter == "W":
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
# "Scrimmage" is a third spelling of the same marker (measured: bloomsburg
# 2022, game 14253, promotion "Scrimmage" beside "Chestnut Hill College",
# whose own row is stored as an exhibition; south-dakota-mines 2025,
# "Blue-Grey Scrimmage"); bounded on both sides so a name that merely
# contains the letters stays a name (no archived opponent name carries the
# word, checked 2026-09-03).
#
# Sites also abbreviate the mark inside a parenthetical of its own: "(Exh.)"
# (242 opponent cells over both data homes, 2026-11-15), "(EXH)" 48, "(Ex.)"
# 28, "(EX)" 24, "(exh.)" 18, "(EXH.)" 9, "(Exh)" 6, "(ex)" 5, "(EXB.)" 4,
# "(ex.)" 3, "(EXB)" 2 ("Blue & Gold Game (Exh.)", "Michigan (EXB)"). Only
# the whole parenthetical is the mark, so "(Texas)", "(Tex.)" and a name
# that merely begins "Ex" stay names: of 324 distinct opponent-cell
# parentheticals, every other one starting "ex" is a spelled-out form the
# marker already reads ("(Exhibition)", "(Exhib.)", "(Exhibtion)"), and the
# only "ex" word outside one was a calendar event ("Wall of Excellence
# Unveiling").
_EXHIBITION_MARKER = re.compile(
    r"\bexhib|\bfriendl(?:y|ies)\b|\bscrimmage\b|\((?:ex|exh|exb)\.?\)",
    re.IGNORECASE,
)


def _exhibition_marked(*texts: str) -> bool:
    return any(_EXHIBITION_MARKER.search(text) for text in texts)


# A schedule row whose opponent is not a team (bead tl-11p7): an alumni game
# ("Alumni Game", "Alumni Match"), an intrasquad ("Intrasquad Game", "Blue
# vs. Gold", "Green & White Game"), a club side with no programme ("FC
# United", "UDA") or the school listed against itself. The ruling keeps the
# row and marks it exhibition, so the schedule stays as published and the
# row stays out of every count; the opponent slug stays whatever the text
# mints. Three tells, measured 2026-09-06 over every archived men's schedule
# page (1073 pages, 18,214 rendered rows past the hosted and calendar skips,
# 9,799 payload events):
#
# 1. The opponent text says "alumni game/match" or "intrasquad". The bare
#    word "alumni" is NOT a tell: "Barry University (Alumni Night)",
#    "Millersville (Alumni Day)" and "Embry-Riddle University (Teal Out and
#    Alumni Night)" are real matches with a promotion in the opponent cell,
#    and "Alumni Field", "Alumni Day" and "Alumni Appreciation Game" sit in
#    the venue of real matches, so this marker reads the opponent text only,
#    never the location. "Scrimmage" already belongs to _EXHIBITION_MARKER.
# 2. The minted opponent slug is the owner's own (christian-brothers 2025,
#    game 9364, "Christian Brothers University" at "Signaigo Field Alumni
#    Game"; the utpbfalcons.com payload's "UT Permian Basin - Orange & Black
#    Scrimmage"). A programme never plays itself.
# 3. The opponent link points at the site's own root. A real opponent's
#    link points at the opponent's site (17,383 rows) or a page on it (714);
#    an opponent with no website prints no link at all (73 rows: "Oakland
#    Roots", "Paradise SC"); no row on the owner's host reaches a path. The
#    31 rows that link to the own root are all alumni games, intrasquads,
#    scrimmages, club sides or the self-row, and it is the only tell the
#    colour games ("HPU Grey and Black Game") and club sides carry. The
#    hosted other-match skip and the calendar-event skip run first, so a
#    hosted pair and the media-day row never reach it.
#
# The payload cannot see the anchor; its copy of the third tell is the
# ``opponent.website`` field, which the events component carries on 768 of
# the archived events (gochoctaws.com's "Alumni Game" rows point it at the
# own root) and the schedule objects omit, so a colour game or club side
# that reaches the payload without a website and without a word is minted
# unmarked there (none archived does).
_NON_MATCH_OPPONENT_MARKER = re.compile(
    r"\balumni (?:game|match)\b|\bintrasquad\b", re.IGNORECASE
)


def _non_match_opponent(text: str) -> bool:
    """Whether the opponent text names an alumni game or an intrasquad."""
    return _NON_MATCH_OPPONENT_MARKER.search(text) is not None


def _own_root_link(href: str, page_url: str) -> bool:
    """Whether an opponent link points at the schedule's own site root."""
    if not href:
        return False
    link, page = urlparse(href.strip()), urlparse(page_url)
    if not link.netloc or not page.netloc:
        return False
    own = page.netloc.lower().removeprefix("www.")
    return (
        link.netloc.lower().removeprefix("www.") == own and link.path.strip("/") == ""
    )


def _non_match_row(
    opponent_text: str, *, other_slug: str, owner_slug: str, href: str, page_url: str
) -> bool:
    """The three tells of a row whose opponent is not a team, any one of them."""
    return (
        _non_match_opponent(opponent_text)
        or other_slug == owner_slug
        or _own_root_link(href, page_url)
    )


# A calendar event SideArm files under an opponent record (bead tl-ttr:
# gohilltoppers.com 2026, game 8813, "Men's Soccer Media Day" with an
# opponent id, a logo and a JSON-LD SportsEvent) prints a start-to-end time
# range where a match prints its kickoff: "11:25 AM-12:40 PM" in the date
# cell and again in the opponent link's aria-label. A match has one kickoff
# and no end time. Measured 2026-09-06 over every archived men's schedule
# page (1073 pages, 18,530 rendered rows, 9,799 payload events): the range
# marks that one row and no match; no payload event carries an end_date
# after its date (the one end_date that differs, cal-state-east-bay 7008, is
# earlier than its start). The other tell the row carries, an opponent link
# to the site's own root, also marks alumni games, intrasquads and club
# scrimmages that ARE played, so it is not the rule. Left-hand time must
# carry its meridiem, or both sides must be H:MM, so a score ("2-1") and a
# bare date never read as a range.
_TIME_RANGE_MARKER = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?\s*[-\u2013\u2014]\s*"
    r"\d{1,2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?\b"
    r"|\b\d{1,2}:\d{2}\s*[-\u2013\u2014]\s*\d{1,2}:\d{2}\s*[ap]\.?m\.?",
    re.IGNORECASE,
)


def _calendar_event_marked(*texts: str) -> bool:
    """Whether any of the row's time texts prints a start-to-end range."""
    return any(_TIME_RANGE_MARKER.search(text) for text in texts)


def _payload_ends_after_start(event: dict[str, object]) -> bool:
    """The payload's form of the same marker: an ``end_date`` after ``date``.

    Every archived payload event carries ``end_date: null`` or an end no
    later than its start, and no archived events component carries the
    media-day row at all (the St. Edward's stub is windowed to upcoming
    games), so this reading is the field the rendered range must come from,
    not a measured payload row.
    """
    start, end = str(event.get("date") or ""), str(event.get("end_date") or "")
    if not start or not end:
        return False
    try:
        return datetime.fromisoformat(end) > datetime.fromisoformat(start)
    except ValueError:
        return False


def _dom_bare_letter(result_text: str, classes: set[str]) -> str | None:
    """The result letter of a row whose cell parsed no score.

    A lone W, L or T printed in the cell ("W (forfeit)"), else the single
    letter class the game-list skin stamps on the row (upper-iowa 2024, game
    9017: ``class="... upcoming-game W sidearm-schedule-game-completed"``).
    Nothing when neither speaks, or the classes disagree.
    """
    match = re.search(r"\b([WLT])\b", result_text)
    if match:
        return match.group(1)
    letters = classes & {"W", "L", "T"}
    if len(letters) == 1:
        return next(iter(letters))
    return None


def _dom_two_team_result(row: object, classes: set[str]) -> tuple[str, int, int] | None:
    """A result printed as one score per team, the owner's side named.

    The two-team list skin (measured daemenwildcats.com 2025) prints no
    "W, 2-1" cell.  Each team block carries its own
    ``.sidearm-schedule-game-result`` holding a bare number, the blocks are
    told apart by ``-team-opponent`` and ``-team-school``, and the row's
    class list carries the letter (``W``, ``L`` or ``T``) beside the
    ``sidearm-schedule-*`` classes.  Returned in the printed contract's
    order — letter, owner's score, other side's — so ``_oriented_scores``
    reads it like any other result.  A letter the row does not carry is
    the comparison the scores themselves make.
    """
    own = _first_text(
        row, ".sidearm-schedule-game-team-school .sidearm-schedule-game-result"
    )
    other = _first_text(
        row, ".sidearm-schedule-game-team-opponent .sidearm-schedule-game-result"
    )
    if own is None or other is None:
        return None
    own_score, other_score = _integer(own.strip()), _integer(other.strip())
    if own_score is None or other_score is None:
        return None
    letters = classes & {"W", "L", "T"}
    if len(letters) == 1:
        letter = next(iter(letters))
    elif own_score > other_score:
        letter = "W"
    elif own_score < other_score:
        letter = "L"
    else:
        letter = "T"
    return letter, own_score, other_score


def _dom_row_date(row: object, year: int) -> str | None:
    """A rendered row's date. Most skins date the row beside the opponent;
    the two-team list skin (measured daemenwildcats.com 2025: "Saturday,
    Nov 1" in div.sidearm-schedule-game-date, no opponent-date element)
    dates it in the details column."""
    return _dom_date(
        _first_text(row, ".sidearm-schedule-game-opponent-date")
        or _first_text(row, ".sidearm-schedule-game-date")
        or "",
        year,
    )


def _parse_schedule_dom(
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
    stages = _dom_stages(
        rows,
        {
            id(row): date
            for row in rows
            if (date := _dom_row_date(row, year)) is not None
        },
        # A header is read for the collecting level's conferences only.
        level=None if scope is None else scope.level,
    )
    # Falling back to the whole alias map preserves single-conference behaviour
    # for callers that have no member list to give, which is every test fixture
    # and nothing on the collection path.
    member_slugs = set(aliases.values()) if members is None else members

    fixtures: list[dict[str, object]] = []
    for row in rows:
        game_id = str(row.get("data-game-id") or "").strip()
        opponent_raw = _first_text(row, ".sidearm-schedule-game-opponent-name") or ""
        orientation, opponent_raw = _split_orientation(opponent_raw)
        opponent_name = _clean_team_name(opponent_raw)
        seeded = _seeded(opponent_raw)
        date = _dom_row_date(row, year)
        if not game_id or not opponent_name or not date:
            continue
        # Postseason structure rows are events, not fixtures: "TBA" hotel
        # blocks and "NCAA Tournament First and Second Rounds" carry no
        # opponent, and their date is a range.  Real matches from those rounds
        # arrive later with actual opponents. Named, never minted.
        if round_placeholder(opponent_name):
            if skips is not None:
                skips.append(placeholder_skip(date, opponent_name))
            continue
        # A calendar event filed under an opponent record (a media day)
        # prints a start-to-end time range where a match prints its kickoff;
        # named for the collect summary, never minted (bead tl-ttr).
        opponent_link = row.select_one(".sidearm-schedule-game-opponent-name a")
        if _calendar_event_marked(
            _first_text(row, ".sidearm-schedule-game-opponent-date") or "",
            _first_text(row, ".sidearm-schedule-game-time") or "",
            str(opponent_link.get("aria-label") or "") if opponent_link else "",
        ):
            if skips is not None:
                skips.append(calendar_event_skip(date, opponent_name))
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
        # A tournament host lists the other pair's match on its own schedule
        # ("0 Colorado Mesa vs 1 Midwestern" on westminstergriffins.com
        # 2023, a neutral row at the host's own ground).  The owner is not
        # in it, so it is not the owner's fixture: skipped by name, never
        # minted under the owner's id.
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
        other_slug = opponent_slug(
            opponent_name, aliases, scope=scope, owner=owner_slug, seeded=seeded
        )
        # An alumni game, intrasquad, club side or the school against
        # itself is kept and marked exhibition, never skipped (bead
        # tl-11p7). The link is the rendered list's own tell.
        if not exhibition and _non_match_row(
            opponent_raw,
            other_slug=other_slug,
            owner_slug=owner_slug,
            href=str(opponent_link.get("href") or "") if opponent_link else "",
            page_url=page_url,
        ):
            exhibition = True
        if neutral:
            # Neutral rows keep the "vs"/"at" span as the only side
            # indicator; home/away stay as published, the flag says
            # neither side hosted.
            indicator = _first_text(
                row, ".sidearm-schedule-game-home, .sidearm-schedule-game-away"
            )
            owner_is_home = (indicator or orientation or "vs").strip().lower() != "at"
        elif "sidearm-schedule-home-game" in classes:
            owner_is_home = True
        elif "sidearm-schedule-away-game" in classes:
            owner_is_home = False
        else:
            # No side class: the word in the opponent cell is the only
            # orientation the row publishes.
            owner_is_home = orientation == "vs"
        home, away = (
            (owner_slug, other_slug) if owner_is_home else (other_slug, owner_slug)
        )

        result_text = _first_text(row, ".sidearm-schedule-game-result") or ""
        result = _dom_result(result_text)
        if result is None:
            result = _dom_two_team_result(row, classes)
        # The completed class and the Final span say the row is past, not
        # that it was played: newman 2023, game 6929 ("Final" beside an
        # EXHIBITION promotion, empty result spans) and ouachita-baptist 2024,
        # game 5655, carry both and no score, and their opponents' own pages
        # read scheduled. The earlier reading, that such a row is a final
        # whose score was never entered, is retired (beads tl-d69, tl-md2):
        # two collectors of one match must agree on played-versus-unplayed
        # or the site's fold throws. A final here is provisional until the
        # oriented scores below confirm it; a status word in the result cell
        # (#76's rule) still outranks both signals, and a word elsewhere on
        # the row counts only when no score was parsed: see _status_word for
        # the measured rows where a played match still says "Rescheduled
        # from 9/23" beside its score.
        final_span = _first_text(row, ".sidearm-schedule-game-result-final")
        completed = (
            "sidearm-schedule-game-completed" in classes or final_span is not None
        )
        row_text = row.get_text(" ", strip=True)  # type: ignore[attr-defined]
        word = _status_word(result_text)
        if word is None and result is None:
            word = _status_word(row_text)
        # A forfeit is read from the whole row because the theme prints the
        # word in a promotion div, not the result cell (upper-iowa 2024, game
        # 9017: "Win by forfeit" beside "W, 2-2"). The letter that awards the
        # side is the result cell's, else a bare letter printed there ("W
        # (forfeit)"), else the row's own W/L class, which the same theme
        # stamps beside its sidearm-schedule-* classes.
        forfeit_side: str | None = None
        if _forfeit_marked(row_text):
            letter = result[0] if result else _dom_bare_letter(result_text, classes)
            forfeit_side = _forfeit_side(letter, owner_is_home=owner_is_home)
        if word is not None:
            status = word
        elif result or completed or forfeit_side:
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
            fixture["conference_game"] = not exhibition and other_slug in member_slugs
            fixture["conference_game_source"] = "derived:membership"
        stage = stages.get(id(row))
        if stage is not None:
            fixture["stage"] = dict(stage)
        # Some themes render kickoff in a dedicated element; at least one packs
        # it into the date text ("Aug 27 (Thu) 3:00 p.m.").  The game-list
        # skin drops the time element once a row is completed, and the
        # kickoff then survives only in the row's link aria-labels (bead
        # tl-4sg.31).
        time = (
            _dom_time(_first_text(row, ".sidearm-schedule-game-time") or "")
            or _dom_time(_first_text(row, ".sidearm-schedule-game-opponent-date") or "")
            or _dom_aria_time(row)
        )
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
                result[0],
                result[1],
                result[2],
                fixture_id=str(fixture["id"]),
                result_text=result_text,
                forfeit=forfeit_side is not None,
            )
            if result
            else None
        )
        if status == "final" and forfeit_side is not None:
            fixture["forfeit"] = forfeit_side
        if oriented:
            owner_score, other_score = oriented
            if owner_is_home:
                fixture["home_score"], fixture["away_score"] = owner_score, other_score
            else:
                fixture["home_score"], fixture["away_score"] = other_score, owner_score
            if owner_score == other_score and shootout_published(result_text):
                fixture["result_published"] = " ".join(result_text.split())
                shootout = parse_shootout(
                    result_text,
                    owner_slug=owner_slug,
                    other_slug=other_slug,
                    owner_is_home=owner_is_home,
                    aliases=aliases,
                    scope=scope,
                )
                if shootout is not None:
                    fixture["shootout"] = shootout
        elif status == "final" and forfeit_side is not None:
            # A forfeit the page did not score takes the sport's 1-0
            # convention to the awarded side (bead tl-wyv).
            fixture["home_score"], fixture["away_score"] = _forfeit_scores(forfeit_side)
            _LOG.info(
                "%s: forfeit awarded to the %s side with no printed score; stored 1-0",
                fixture["id"],
                forfeit_side,
            )
        elif status == "final":
            # Final requires scores (beads tl-d69, tl-md2): a completed class
            # or Final span with no oriented score pair is stored scheduled
            # and named, in _oriented_scores' voice.
            _LOG.warning(
                "%s: page reads final with no score (%r); stored scheduled, no score",
                fixture["id"],
                result_text or final_span or "sidearm-schedule-game-completed",
            )
            fixture["status"] = "scheduled"
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
    skips: list[str] | None = None,
    scope: ResolutionScope | None = None,
    gender: str = "men",
) -> list[dict[str, object]]:
    """Read a SideArm schedule page into fixture rows.

    The component JSON is authoritative where it speaks; the DOM supplies
    every game the JSON stub left out, under the same identifiers.  A row
    naming two other teams (a match the owner hosted but did not play) is
    never minted; with a ``skips`` list it is named there, one line per
    row, for the collect summary.  With a ``scope`` (the collect's
    conference-season), an opponent a member of that conference claims
    resolves to the member first (``opponent_slug``).  ``gender`` is the
    programme's (``SchoolConfig.gender``): an embedded event naming another
    sport, or the other gender's soccer, is not this schedule's game.
    """
    events: dict[str, dict[str, object]] = {}
    for title, raw, honest in _payload_events(html, gender):
        date = str(raw.get("date") or "")
        if not re.search(rf"\b{year}\b", title):
            continue
        # The events stub names the current season at every URL, so only its
        # games dated in the requested year can be that season's.  A schedule
        # object is the served season whole, spring games of a fall season
        # included (the COVID 2020 season was played in 2021).
        if not honest and not date.startswith(str(year)):
            continue
        event_id = str(raw.get("id") or "")
        if event_id and date:
            events[event_id] = raw

    fixtures: list[dict[str, object]] = []
    for event_id, event in events.items():
        opponent = event.get("opponent")
        opponent_dict = opponent if isinstance(opponent, dict) else {}
        published_title = str(
            opponent_dict.get("title") or opponent_dict.get("name") or ""
        )
        opponent_name = _clean_team_name(published_title)
        seeded = _seeded(published_title)
        if not opponent_name:
            continue
        date_text = str(event.get("date"))
        # The payload's copy of a postseason slot: the same strings the
        # rendered list prints, under opponent.title. The rendered-list rule
        # never reached this path, which is how every 2026 shard came to hold
        # "ncaa-first-round" and "gulf-south-conference" as programmes.
        if round_placeholder(opponent_name):
            if skips is not None:
                skips.append(placeholder_skip(date_text[:10], opponent_name))
            continue
        # The payload's copy of the calendar-event tell: the rendered time
        # string printing a range, or an end_date after the start (bead
        # tl-ttr). Named for the collect summary, never minted.
        if _calendar_event_marked(
            str(event.get("time") or "")
        ) or _payload_ends_after_start(event):
            if skips is not None:
                skips.append(calendar_event_skip(date_text[:10], opponent_name))
            continue
        # The payload publishes a hosted other-match under the same shape
        # as the DOM: "Western Oregon University vs Metropolitan State
        # University of Denver" as the opponent title, location_indicator
        # "N" (westminstergriffins.com 2026).  Not the owner's fixture.
        hosted = hosted_other_match(
            opponent_name, owner_slug=owner_slug, aliases=aliases, scope=scope
        )
        if hosted is not None:
            if skips is not None:
                skips.append(hosted_skip(date_text[:10], hosted))
            continue
        opponent_name = own_side_opponent(
            opponent_name, owner_slug=owner_slug, aliases=aliases, scope=scope
        )
        other_slug = opponent_slug(
            opponent_name, aliases, scope=scope, owner=owner_slug, seeded=seeded
        )
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
        # The letter (result.status) decides orientation and, on a forfeit
        # row, the awarded side. The payload has no forfeit field; the word
        # is read from the strings it does carry (the result's status and
        # pre/postscore info, the event's promotion, noplay_text and status),
        # the same rule as the DOM row. A forfeit with a letter is final even
        # when the payload prints no score.
        letter = str(result_dict.get("status") or "").strip().upper() or None
        result_text = " ".join(
            str(result_dict.get(key))
            for key in ("status", "postscore_info", "prescore_info")
            if isinstance(result_dict.get(key), str)
        )
        forfeit_side: str | None = None
        if _forfeit_marked(
            result_text,
            *(
                str(event.get(key))
                for key in ("promotion", "noplay_text", "status")
                if isinstance(event.get(key), str)
            ),
        ):
            forfeit_side = _forfeit_side(letter, owner_is_home=owner_is_home)
            if forfeit_side is not None and status == "scheduled":
                status = "final"
        # The events component spells the flag ``is_conference``; the schedule
        # objects spell it ``conference`` as a bare boolean (their
        # ``opponent.conference`` is the opponent's own flag, not the game's).
        conference = event.get("is_conference")
        if conference is None and isinstance(event.get("conference"), bool):
            conference = event.get("conference")
        fixture: dict[str, object] = {
            "id": f"sidearm:{owner_slug}:{event_id}",
            "date": date_text[:10],
            "home": home,
            "away": away,
            "status": status,
            "conference_game": bool(conference),
            "source_url": page_url,
        }
        # The payload's word for a neutral site is the indicator itself
        # (measured: "location_indicator":"N" with "neutral_hometeam":true,
        # Maryville University at "Claremore, OK" in the snuathletics.com
        # events component). Same flag as the DOM path, same meaning.
        if indicator == "N":
            fixture["neutral"] = True
        # The events component names the ground ``game_facility``; the
        # schedule objects name it ``facility``.
        facility = event.get("game_facility") or event.get("facility")
        facility_dict = facility if isinstance(facility, dict) else {}
        venue = str(facility_dict.get("title") or event.get("location") or "").strip()
        # The payload has no exhibition field — the site says it in the
        # opponent's own published title ("Oklahoma Wesleyan (Exhibition)")
        # or beside the venue in its location text ("Tulsa, Okla. Friendly").
        # An alumni game, intrasquad, club side or the school against itself
        # is the same exhibition (bead tl-11p7); the payload's copy of the
        # rendered link is ``opponent.website``, where the event carries one.
        if _exhibition_marked(published_title, venue) or _non_match_row(
            published_title,
            other_slug=other_slug,
            owner_slug=owner_slug,
            href=str(opponent_dict.get("website") or ""),
            page_url=page_url,
        ):
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
            # as filled. The payload has no shootout field (measured: no
            # archived events payload prints W or L beside a level score, and
            # result carries only status, the two scores, line_scores and the
            # pre/postscore info strings), so the marker is read from the
            # strings it does carry, the same rule as the DOM cell.
            oriented = (
                (team_score, opponent_score)
                if status == "live" and letter is None
                else _oriented_scores(
                    letter,
                    team_score,
                    opponent_score,
                    fixture_id=str(fixture["id"]),
                    result_text=result_text,
                    forfeit=forfeit_side is not None,
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
                # The payload's copy of a shootout lives in the same
                # strings as its result text, so the cell grammar reads it.
                printed = f"{letter or ''}, {team_score}-{opponent_score} {result_text}"
                if team_score == opponent_score and shootout_published(printed):
                    fixture["result_published"] = " ".join(result_text.split())
                    shootout = parse_shootout(
                        printed,
                        owner_slug=owner_slug,
                        other_slug=other_slug,
                        owner_is_home=owner_is_home,
                        aliases=aliases,
                        scope=scope,
                    )
                    if shootout is not None:
                        fixture["shootout"] = shootout
        if status == "final" and forfeit_side is not None:
            fixture["forfeit"] = forfeit_side
            if "home_score" not in fixture:
                # A forfeit the payload did not score takes the sport's 1-0
                # convention to the awarded side (bead tl-wyv).
                fixture["home_score"], fixture["away_score"] = _forfeit_scores(
                    forfeit_side
                )
                _LOG.info(
                    "%s: forfeit awarded to the %s side with no printed score; "
                    "stored 1-0",
                    fixture["id"],
                    forfeit_side,
                )
        if status == "final" and "home_score" not in fixture:
            # Final requires scores (beads tl-d69, tl-md2): a result.status of
            # "Final" over null team_score/opponent_score, or a pair the
            # letter refused, is stored scheduled and named, in
            # _oriented_scores' voice. A live match keeps its status: it has
            # no score yet.
            _LOG.warning(
                "%s: page reads final with no score (%r); stored scheduled, no score",
                fixture["id"],
                str(result_dict.get("status") or event.get("status") or ""),
            )
            fixture["status"] = "scheduled"
        fixtures.append(fixture)

    # The component JSON is authoritative where it speaks; the DOM supplies
    # every game the JSON stub left out, under the same identifiers.  A
    # hosted row both carry is one skip, not two (measured: the host's 2026
    # page publishes each such row in the payload and in the rendered list).
    by_id = {str(fixture["id"]): fixture for fixture in fixtures}
    dom_skips: list[str] = []
    for fixture in _parse_schedule_dom(
        html,
        page_url=page_url,
        year=year,
        owner_slug=owner_slug,
        aliases=aliases,
        members=members,
        skips=dom_skips,
        scope=scope,
    ):
        twin = by_id.get(str(fixture["id"]))
        if twin is None:
            fixtures.append(fixture)
            continue
        # The payload has no tournament grouping and its result strings
        # rarely carry the shootout; the rendered row of the same game does.
        # Its stage always rides along; its shootout only when both copies
        # store the same level score.
        if "stage" in fixture and "stage" not in twin:
            twin["stage"] = fixture["stage"]
        # The two copies may orient the match differently (a neutral row
        # the rendered list reads "vs" and the payload "N" away), so the
        # shootout's counts follow the side, not the column (measured:
        # kentucky-wesleyan 2026, game 11458).
        level = "home_score" in twin and twin.get("home_score") == twin.get(
            "away_score"
        )
        if (
            level
            and fixture.get("home_score") == twin.get("home_score")
            and "result_published" in fixture
            and "result_published" not in twin
        ):
            twin["result_published"] = fixture["result_published"]
            if "shootout" in fixture:
                twin["shootout"] = reoriented_shootout(
                    fixture["shootout"],  # type: ignore[arg-type]
                    home=str(fixture["home"]),
                    to_home=str(twin["home"]),
                )
    if skips is not None:
        skips.extend(line for line in dom_skips if line not in skips)
    # Only now does every row carry its stage (the payload copy takes the
    # rendered row's), so an NCAA tie's opponent is read again here.
    for fixture in fixtures:
        stage = fixture.get("stage")
        if isinstance(stage, dict) and stage.get("competition") == "ncaa":
            for side in ("home", "away"):
                fixture[side] = ncaa_side(
                    str(fixture[side]), aliases, scope, owner=owner_slug
                )
    return sorted(fixtures, key=lambda value: (str(value["date"]), str(value["id"])))


def _first_text(node: object, selector: str) -> str | None:
    found = node.select_one(selector)  # type: ignore[attr-defined]
    if found is None:
        return None
    text = found.get_text(" ", strip=True)
    return text or None


def _parse_nuxt_roster(html: str, *, page_url: str) -> list[dict[str, str]]:
    """Read the Nuxt skin's roster store: the list its cards are rendered from.

    Measured 2026-09-03: the roster page renders ``s-person-card`` blocks
    from ``pinia.roster.roster[<key>].players``, each player a camelCase
    record — ``firstName``/``lastName``, ``jerseyNumber``, ``positionShort``,
    ``heightFeet``/``heightInches``, ``weight`` (a bare number of pounds),
    ``hometown``, ``academicYearLong`` and the bio path in
    ``call_to_action``.  The record is the page's own source, so it is read
    in place of the cards.
    """
    players: list[dict[str, str]] = []
    seen: set[str] = set()
    rosters = _nuxt_store(html, "roster").get("roster")
    if not isinstance(rosters, dict):
        return players
    for roster in rosters.values():
        if not isinstance(roster, dict):
            continue
        for raw in roster.get("players") or []:  # type: ignore[union-attr]
            if not isinstance(raw, dict):
                continue
            name = " ".join(
                str(raw.get(key) or "").strip() for key in ("firstName", "lastName")
            ).strip()
            path = str(raw.get("call_to_action") or "").strip()
            player_id = str(
                raw.get("rosterPlayerId") or raw.get("playerId") or path
            ).strip()
            if not name or not player_id or player_id in seen:
                continue
            seen.add(player_id)
            player: dict[str, str] = {"name": name}
            number = str(raw.get("jerseyNumber") or "").strip()
            if number:
                player["number"] = number
            position = str(
                raw.get("positionShort") or raw.get("positionLong") or ""
            ).strip()
            if position:
                player["position"] = position
            feet, inches = (
                _integer(raw.get("heightFeet")),
                _integer(raw.get("heightInches")),
            )
            if feet is not None and inches is not None:
                player["height"] = f"{feet}'{inches}\""
            weight = _integer(raw.get("weight"))
            if weight is not None:
                player["weight"] = f"{weight} lbs"
            hometown = str(raw.get("hometown") or "").strip()
            if hometown:
                player["hometown"] = hometown
            class_year = str(
                raw.get("academicYearLong") or raw.get("academicYearShort") or ""
            ).strip()
            if class_year:
                player["class_year"] = class_year
            if path:
                player["source_url"] = urljoin(page_url, path)
            players.append(player)
    return players


def parse_roster_page(html: str, *, page_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    players: list[dict[str, str]] = []
    seen: set[str] = set()
    rows = soup.select("li.sidearm-roster-player")
    if not rows:
        return _parse_nuxt_roster(html, page_url=page_url)
    for row in rows:
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


def _parse_nuxt_stats(
    html: str, *, page_url: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    """Read the Nuxt skin's cumulative-statistics store, or None without one.

    Measured 2026-09-03: the page renders uncaptioned tables from
    ``pinia.statsSeason.cumulativeStats[<key>].overallIndividualStats`` —
    ``individualOffensiveStats`` (or ``individualStats`` on a site that
    fills that list instead) and ``goalieStats``, each row a camelCase
    record carrying the same columns the captioned tables print, every
    value a string, and the Total row flagged ``isAFooterStat``.  Names come
    as "Last, First" like the tables' anchors, with the bio id in
    ``playerRosterBioId`` and the bio path in ``playerUrl``.
    """
    seasons = _nuxt_store(html, "statsSeason").get("cumulativeStats")
    if not isinstance(seasons, dict):
        return None

    def lines(rows: object, fields: dict[str, tuple[str, object]]) -> list[dict]:
        out: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw in rows if isinstance(rows, list) else []:
            if not isinstance(raw, dict) or raw.get("isAFooterStat"):
                continue
            name = _stats_player_name(str(raw.get("playerName") or ""))
            player_id = str(raw.get("playerRosterBioId") or "").strip()
            key = player_id or name
            if not name or key in seen:
                continue
            seen.add(key)
            entry: dict[str, object] = {"name": name}
            if player_id:
                entry["player_id"] = player_id
            number = str(raw.get("playerUniform") or "").strip()
            if number:
                entry["number"] = number
            path = str(raw.get("playerUrl") or "").strip()
            if path:
                entry["bio_url"] = urljoin(page_url, path)
            for source, (field, convert) in fields.items():
                value = convert(str(raw.get(source) or ""))
                if value is not None:
                    entry[field] = value
            cards = _stat_pair(str(raw.get("yellowCardsRedCards") or ""))
            if cards:
                entry["yellow"], entry["red"] = cards
            penalties = _stat_pair(str(raw.get("penaltyKicksAndAttempts") or ""))
            if penalties:
                entry["penalty_goals"], entry["penalty_attempts"] = penalties
            out.append(entry)
        return out

    players: list[dict[str, object]] = []
    keepers: list[dict[str, object]] = []
    for season in seasons.values():
        individual = (
            season.get("overallIndividualStats") if isinstance(season, dict) else None
        )
        if not isinstance(individual, dict):
            continue
        players.extend(
            lines(
                individual.get("individualOffensiveStats")
                or individual.get("individualStats"),
                {
                    "gamesPlayed": ("gp", _stat_int),
                    "gamesStarted": ("gs", _stat_int),
                    "minutesPlayed": ("minutes", _stat_minutes),
                    "goals": ("goals", _stat_int),
                    "assists": ("assists", _stat_int),
                    "points": ("points", _stat_int),
                    "shots": ("shots", _stat_int),
                    "shotPercentage": ("shot_pct", _stat_float),
                    "shotsOnGoal": ("sog", _stat_int),
                    "shotsOnGoalPercentage": ("sog_pct", _stat_float),
                    "gameWinners": ("game_winners", _stat_int),
                },
            )
        )
        keepers.extend(
            lines(
                individual.get("goalieStats"),
                {
                    "gamesPlayed": ("gp", _stat_int),
                    "gamesStarted": ("gs", _stat_int),
                    "minutesPlayed": ("minutes", _stat_minutes),
                    "goalsAllowed": ("goals_against", _stat_int),
                    "goalsAgainstAverage": ("gaa", _stat_float),
                    "saves": ("saves", _stat_int),
                    "savesPercentage": ("save_pct", _stat_float),
                    "wins": ("wins", _stat_int),
                    "losses": ("losses", _stat_int),
                    "ties": ("ties", _stat_int),
                    "shutouts": ("shutouts", _stat_int),
                    "shotsFaced": ("shots_faced", _stat_int),
                },
            )
        )
    return players, keepers


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
    if soup.find("table", recursive=True) is None or soup.find("caption") is None:
        nuxt = _parse_nuxt_stats(html, page_url=page_url)
        if nuxt is not None:
            return nuxt

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
    # The list skins that render client-side publish no href at all; the
    # link rides in the payload as ``result.boxscore.url`` beside the score.
    for _, event, _ in _payload_events(schedule_html):
        result = event.get("result")
        boxscore = result.get("boxscore") if isinstance(result, dict) else None
        url = str(boxscore.get("url") or "") if isinstance(boxscore, dict) else ""
        match = re.search(r"/boxscore/(\d+)", url)
        if match:
            links.setdefault(match.group(1), urljoin(base_url, url))
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
# "MIL Roy Parkyn PENALTY KICK GOAL." (no "by") stays a penalty: the site
# reads every penalty kick by that type and its goal-ness from the score.
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


#: Names that label a footer row of a box score's player table, never a
#: person (shared by the captioned tables and the Nuxt store's player lists).
_BOX_FOOTER_NAMES = {"totals", "team", "tm", "tm team", "team tm"}


def _nuxt_text(value: object) -> str:
    """A store scalar as the text it publishes, or ``""`` for a non-scalar."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return str(value).strip()


def _parse_nuxt_boxscore(html: str, *, page_url: str) -> dict[str, object] | None:
    """Read the Nuxt skin's box-score store into the classic parser's shape.

    Measured 2026-11-08 on millersvilleathletics.com and scsuhuskies.com: the
    "nextgen" box score server-renders uncaptioned ``s-table`` markup from
    ``pinia.boxscore.boxscore[<key>]`` — ``visitingTeam``/``homeTeam`` (each
    with ``id``, ``name``, ``scoreSummary`` and ``players``), ``scores``,
    ``penalties``, ``plays`` and ``venue`` — every figure a string.  None
    if the page carries no such store, or carries more than one match.

    The page's renderings follow the store field for field, so each is read
    from the field the page prints: team order is visiting then home, the
    order the score-by-period table lists them; the Team Statistics table's
    per-period rows are ``scoreSummary.periodSummaries`` and its total column
    their sum, with shots on goal from ``totals.shots.shotsOnGoal`` (the
    store's ``totals.miscStats`` corner and offside counts read zero beside a
    table that prints them, and are not used); the winner is the side both
    ``winningTeamId`` and ``losingTeamId`` agree on (a draw names the same
    side as both); player lines are the squad members with
    ``gamePlayed`` above zero — the page's own cut — with the position
    upper-cased as the page prints it (a substitute keeper the page shows
    only in its goalkeeping table keeps his played line too); officials
    join ``title: name`` as the page prints them; and a play's text is the
    stat crew's line verbatim.  A line's name is the one the page's player
    table prints: the stat crew's ``checkName`` as the page recases it
    ("WOODFILL,NICHOLAS" prints "Woodfill, Nicholas"), read off the rendered
    cell whose letters match it, never the store's ``name`` — that is the
    roster's name ("Woodfill, Nick"), which this page does not print.
    Measured on all twelve pages (2026-11-08): 474 of 474 played lines
    matched exactly one rendered cell, and 52 differ from the roster name.
    With no unique cell the ``checkName`` stands as the store publishes it.

    Team references — ``teamId`` on a goal, card or play — resolve against
    the two sides' ``id`` and agree with the ``isAHomeTeam`` flag beside
    them, or stay unattributed: the period markers carry ``team: "0"``.
    The store publishes no running score, so a scoring play's ``score`` is
    the count of scoring plays so far — the figure the page prints beside
    it — kept only when every ``scores`` entry matched exactly one
    attributed play and the counts end on both sides' published scores;
    otherwise no play carries one.  Measured on all twelve pages
    (2026-11-08): every play's text is the line the page prints, except
    the "End of period [45:00]." markers, which the page replaces with its
    own "End of Period" label and which the classic skin kept as the stat
    crew wrote them.
    """
    store = _nuxt_store(html, "boxscore").get("boxscore")
    if not isinstance(store, dict):
        return None
    boxes = [
        value
        for value in store.values()
        if isinstance(value, dict)
        and isinstance(value.get("visitingTeam"), dict)
        and isinstance(value.get("homeTeam"), dict)
    ]
    if len(boxes) != 1:
        return None
    box = boxes[0]

    sides: list[dict[str, object]] = [box["visitingTeam"], box["homeTeam"]]  # type: ignore[list-item]
    ids = [_nuxt_text(side.get("id")) for side in sides]

    def side_of(reference: object, home_flag: object = None) -> int | None:
        text = _nuxt_text(reference)
        if not text or ids.count(text) != 1:
            return None
        index = ids.index(text)
        if isinstance(home_flag, bool) and home_flag != (index == 1):
            return None
        return index

    def int_list(values: object) -> list[int] | None:
        if not isinstance(values, list):
            return None
        out = [_stat_int(_nuxt_text(value)) for value in values]
        return [value for value in out if value is not None]

    def name_key(text: str) -> str:
        return re.sub(r"[^A-Z0-9,]", "", text.upper())

    printed: dict[str, set[str]] = {}
    for cell in BeautifulSoup(html, "lxml").select("td.s-table-whole-td-clickable"):
        shown = re.sub(r"\s+", " ", cell.get_text(" ", strip=True))
        if shown:
            printed.setdefault(name_key(shown), set()).add(shown)

    def line_of(raw: dict[str, object]) -> dict[str, object] | None:
        check = _nuxt_text(raw.get("checkName"))
        shown = printed.get(name_key(check), set()) if check else set()
        published = (
            next(iter(shown))
            if len(shown) == 1
            else check or _nuxt_text(raw.get("name"))
        )
        name = _stats_player_name(published)
        if not name or name.lower() in _BOX_FOOTER_NAMES:
            return None
        line: dict[str, object] = {"name": name}
        player_id = _nuxt_text(raw.get("rosterPlayerId"))
        if player_id:
            line["player_id"] = player_id
        position = _nuxt_text(raw.get("position"))
        if re.fullmatch(r"[A-Za-z]{1,3}", position):
            line["position"] = position.upper()
        number = _nuxt_text(raw.get("uniform"))
        if re.fullmatch(r"\d{1,3}", number):
            line["number"] = number
        return line

    teams: list[dict[str, object]] = []
    for index, (side, prefix, periods_key) in enumerate(
        (
            (sides[0], "visitingTeam", "periodScoresAway"),
            (sides[1], "homeTeam", "periodScoresHome"),
        )
    ):
        summary = side.get("scoreSummary")
        summary = summary if isinstance(summary, dict) else {}
        name = _nuxt_text(side.get("name")) or _nuxt_text(box.get(f"{prefix}Name"))
        abbr = ids[index] or _nuxt_text(box.get(f"{prefix}Id"))
        if not name and not abbr:
            return None
        team: dict[str, object] = {"name": name or abbr}
        if abbr:
            team["abbr"] = abbr
        score = _stat_int(_nuxt_text(summary.get("score")))
        if score is None:
            score = _stat_int(_nuxt_text(box.get(f"{prefix}Score")))
        if score is not None:
            team["score"] = score
        periods = int_list(box.get(periods_key))
        if periods is None:
            by_period = _nuxt_text(summary.get("scoreByPeriod"))
            periods = int_list(by_period.split(",")) if by_period else []
        team["periods"] = periods or []
        other = ids[1 - index]
        if (
            ids[index]
            and other
            and ids[index] != other
            and _nuxt_text(box.get("winningTeamId")) == ids[index]
            and _nuxt_text(box.get("losingTeamId")) == other
        ):
            team["winner"] = True

        per_period = summary.get("periodSummaries")
        if isinstance(per_period, list) and per_period:
            for source, field in (
                ("shots", "shots"),
                ("saves", "saves"),
                ("corners", "corners"),
                ("fouls", "fouls"),
                ("offsides", "offsides"),
            ):
                counts = [
                    _stat_int(_nuxt_text(row.get(source)))
                    if isinstance(row, dict)
                    else None
                    for row in per_period
                ]
                if all(count is not None for count in counts):
                    team[field] = sum(counts)  # type: ignore[arg-type]
        totals = side.get("totals")
        shot_totals = totals.get("shots") if isinstance(totals, dict) else None
        if isinstance(shot_totals, dict):
            on_goal = _stat_int(_nuxt_text(shot_totals.get("shotsOnGoal")))
            if on_goal is not None:
                team["sog"] = on_goal

        players: list[dict[str, object]] = []
        keepers: list[dict[str, object]] = []
        roster = side.get("players")
        for raw in roster if isinstance(roster, list) else []:
            if not isinstance(raw, dict):
                continue
            # The store lists the whole squad; the page lists who played.
            if _integer(_nuxt_text(raw.get("gamePlayed"))) == 0:
                continue
            line = line_of(raw)
            if line is None:
                continue
            minutes = _stat_minutes(_nuxt_text(raw.get("minutesPlayed")))
            player = dict(line)
            started = _integer(_nuxt_text(raw.get("gameStarted")))
            if started is not None:
                player["started"] = started > 0
            shots = raw.get("shots")
            shots = shots if isinstance(shots, dict) else {}
            for source, field in (
                ("numberOfShots", "shots"),
                ("shotsOnGoal", "sog"),
                ("goals", "goals"),
                ("assists", "assists"),
            ):
                value = _stat_int(_nuxt_text(shots.get(source)))
                if value is not None:
                    player[field] = value
            if minutes is not None:
                player["minutes"] = minutes
            players.append(player)
            goalie = raw.get("goalie")
            if raw.get("isAGoalie") is True and isinstance(goalie, dict):
                keeper = dict(line)
                if minutes is not None:
                    keeper["minutes"] = minutes
                for source, field in (
                    ("goalsAllowed", "goals_against"),
                    ("saves", "saves"),
                ):
                    value = _stat_int(_nuxt_text(goalie.get(source)))
                    if value is not None:
                        keeper[field] = value
                keepers.append(keeper)
        if players:
            # Starters first, as the page groups them; the store's own
            # (shirt-number) order holds within each group.
            players.sort(key=lambda entry: entry.get("started") is not True)
            team["players"] = players
        if keepers:
            team["keepers"] = keepers
        teams.append(team)

    scoring: list[dict[str, object]] = []
    goals = box.get("scores")
    for raw in goals if isinstance(goals, list) else []:
        if not isinstance(raw, dict):
            continue
        entry: dict[str, object] = {}
        clock = _nuxt_text(raw.get("time"))
        if clock:
            entry["time"] = clock
        index = side_of(raw.get("teamId"), raw.get("isAHomeTeam"))
        if index is not None:
            entry["team"] = index
        scorer = _nuxt_text(raw.get("nameOfPlayer"))
        if not scorer:
            continue
        entry["scorer"] = scorer
        season_total = _stat_int(_nuxt_text(raw.get("seasonGoalNumber")))
        if season_total is not None:
            entry["season_total"] = season_total
        assist = _nuxt_text(raw.get("scoringAssistsOutput"))
        if assist:
            entry["assist"] = assist
        description = _nuxt_text(raw.get("description"))
        if description:
            entry["description"] = description
        scoring.append(entry)

    cards: list[dict[str, object]] = []
    penalties = box.get("penalties")
    for raw in penalties if isinstance(penalties, list) else []:
        if not isinstance(raw, dict):
            continue
        player = _nuxt_text(raw.get("nameOfPlayer"))
        if not player:
            continue
        kind = _nuxt_text(raw.get("type")).lower()
        card: dict[str, object] = {
            "type": kind if kind in {"yellow", "red"} else "unknown",
            "player": player,
        }
        number = _nuxt_text(raw.get("uniformNumber"))
        if re.fullmatch(r"\d+", number):
            card["number"] = number
        clock = _nuxt_text(raw.get("time"))
        if clock:
            card["time"] = clock
        index = side_of(raw.get("teamId"))
        if index is not None:
            card["team"] = index
        cards.append(card)

    # A play is a scoring play when it is one of the store's ``scores``
    # entries — same team, clock and text — which is how the page marks the
    # rows it renders a running score beside (a penalty logged as PENSHOT
    # included, which no action or wording test would catch).
    unmatched = [
        (
            _nuxt_text(raw.get("teamId")),
            _nuxt_text(raw.get("time")),
            _nuxt_text(raw.get("description")),
        )
        for raw in (goals if isinstance(goals, list) else [])
        if isinstance(raw, dict)
    ]
    plays: list[dict[str, object]] = []
    goal_plays: list[dict[str, object]] = []
    feed = box.get("plays")
    for raw in feed if isinstance(feed, list) else []:
        if not isinstance(raw, dict):
            continue
        text = _nuxt_text(raw.get("text"))
        period = _nuxt_text(raw.get("period"))
        if not period or not re.search(r"[A-Za-z]", text):
            continue
        play: dict[str, object] = {"period": period, "text": text}
        clock = _nuxt_text(raw.get("clock"))
        if re.fullmatch(r"\d+:\d{2}", clock):
            play["clock"] = clock
        index = side_of(raw.get("team"), raw.get("isAHomeTeam"))
        if index is not None:
            play["team"] = index
        kind = _play_type(text)
        if kind:
            play["type"] = kind
        key = (_nuxt_text(raw.get("team")), clock, text)
        if key in unmatched:
            unmatched.remove(key)
            goal_plays.append(play)
        plays.append(play)
    if not unmatched and all("team" in play for play in goal_plays):
        tally = [0, 0]
        running: list[list[int]] = []
        for play in goal_plays:
            tally[play["team"]] += 1  # type: ignore[index]
            running.append(list(tally))
        if tally == [team.get("score") for team in teams]:
            for play, score in zip(goal_plays, running, strict=True):
                play["score"] = score

    detail: dict[str, object] = {"source_url": page_url, "teams": teams}
    if scoring:
        detail["scoring"] = scoring
    if cards:
        detail["cards"] = cards
    if plays:
        detail["plays"] = plays

    venue = box.get("venue")
    venue = venue if isinstance(venue, dict) else {}
    stadium = _nuxt_text(venue.get("stadium"))
    if stadium:
        detail["stadium"] = stadium
    attendance = _stat_int(_nuxt_text(venue.get("attendance")))
    if attendance is not None:
        detail["attendance"] = attendance
    kickoff = _nuxt_text(venue.get("start"))
    if kickoff:
        detail["kickoff"] = kickoff
    officials = [
        f"{_nuxt_text(raw.get('title'))}: {_nuxt_text(raw.get('name'))}"
        for raw in venue.get("officials") or []  # type: ignore[union-attr]
        if isinstance(raw, dict)
        and _nuxt_text(raw.get("title"))
        and _nuxt_text(raw.get("name"))
    ]
    if officials:
        detail["officials"] = officials
    return detail


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

    # The Nuxt ("nextgen") skin captions none of these tables; its page
    # carries the whole match in the Pinia store it renders from.  A page
    # with neither layout falls through with no teams, and is refused.
    if not teams:
        nuxt = _parse_nuxt_boxscore(html, page_url=page_url)
        if nuxt is not None:
            return nuxt

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
                if not name or name.lower() in _BOX_FOOTER_NAMES:
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


def parse_match_page(
    page: PublishedPage, year: int, fixture: dict[str, object]
) -> dict[str, object]:
    """Prove a served box-score page is the fixture's, then read it.

    The half of ``collect_match`` after the fetch, on its own so the board
    collector can run exactly the same proof and parse over an archived
    page when the parser's fingerprint has moved (bead tl-ir6).
    """
    assert_served_match(page, year, fixture)
    detail = parse_boxscore_page(page.html, page_url=page.final_url)
    teams = detail.get("teams") or []
    if len(teams) != 2:  # type: ignore[arg-type]
        raise LiveCollectionError(
            f"[{year}] {fixture.get('id')}: {page.final_url} proved its match but "
            f"its score-by-period table rendered {len(teams)} team(s) "  # type: ignore[arg-type]
            f"where a match needs exactly two"
        )
    orient_match(detail, fixture)
    return detail


def collect_match(
    session: requests.Session,
    url: str,
    year: int,
    fixture: dict[str, object],
    *,
    archive: BoxArchive | None = None,
) -> dict[str, object]:
    """Fetch one fixture's box score, prove it is that fixture's, and parse it.

    With an ``archive``, the proven page and its parse are written to the
    fetch cache beside the layer pages, so a later parser change re-reads
    the bytes from disk instead of the site.
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
    detail = parse_match_page(page, year, fixture)
    if archive is not None:
        archive.save(
            requested_url=page.requested_url,
            final_url=page.final_url,
            html=page.html,
            parsed=detail,
        )
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
    single extra fetch — the archived bytes are simply read again.  A recipe
    whose parsers live in another module appends that module's source digest
    (``Recipe.parse_identity``), so a PrestoSports parser fix re-reads the
    archive the same way.
    """
    digest = hashlib.sha256(Path(__file__).read_bytes())
    for value in inputs:
        digest.update(b"\x00")
        digest.update(json.dumps(value, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


def _fetch_layer(
    recipe: Recipe,
    client: requests.Session,
    base_url: str,
    url: str,
    year: int,
    kind: str,
    *,
    state: PageState | None,
    want_validators: bool,
) -> ConditionalFetch:
    """One season layer through the recipe's own fetch when it has one.

    A recipe whose layer is more than one served body (WMT: a season page
    plus the API answers it names) carries ``fetch_layer``, which fetches,
    proves and bundles them and answers the same ``ConditionalFetch`` this
    seam does; every other recipe is one conditional fetch of ``url``.
    """
    if recipe.fetch_layer is not None:
        return recipe.fetch_layer(
            client,
            base_url,
            year,
            kind,
            state=state,
            want_validators=want_validators,
        )
    return fetch_published_page_conditional(
        client,
        url,
        year,
        kind,
        state=state,
        want_validators=want_validators,
        served_season=recipe.assert_served_season,
    )


def collect_programme(
    school: SchoolConfig,
    year: int,
    aliases: dict[str, str],
    session: requests.Session | None = None,
    layers: Sequence[str] = DEFAULT_LAYERS,
    members: set[str] | None = None,
    page_cache: PageStateStore | None = None,
    scope: ResolutionScope | None = None,
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
    # The recipe table is built from this module's own functions, so it can
    # only be imported once they exist: here, at call time.
    from src.recipes import NoCollector, live_recipe

    recipe = live_recipe(platform)
    if recipe is None:
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
        schedule_skips: list[str] = []
        # The schedule parse reads more than the page: opponent identity comes
        # from the alias map and the conference flag from membership, so both
        # belong to the cached parse's identity, beside the recipe's parsers.
        fingerprint = parse_fingerprint(
            year,
            aliases,
            sorted(members) if members is not None else None,
            # A scope re-points what its members claim, so it is part of the
            # parse's identity when there is one; without one the inputs are
            # exactly what they were.
            *(() if scope is None else (scope.fingerprint(slug),)),
            # The codes and printed names a tournament header is read by
            # are reference data, so an edited name re-reads the archive.
            # Only the collecting level's: another level's conference added
            # to the reference re-reads nothing here.
            conference_header_signature(None if scope is None else scope.level),
            *recipe.parse_identity,
        )
        state = (
            page_cache.load(slug, LAYER_SCHEDULE, fingerprint) if page_cache else None
        )
        try:
            schedule_url = recipe.layer_url(base_url, year, LAYER_SCHEDULE)
            fetched = _fetch_layer(
                recipe,
                client,
                base_url,
                schedule_url,
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
                        skips=tuple(
                            str(skip) for skip in state.parsed.get("skips") or []
                        ),
                    )
                    page_cache.mark_verified(
                        slug,
                        LAYER_SCHEDULE,
                        etag=fetched.etag,
                        last_modified=fetched.last_modified,
                    )
                else:
                    # Unchanged page, stale parse: read the archive again.
                    fixtures = recipe.parse_schedule(
                        schedule_html,
                        page_url=state.final_url,
                        year=year,
                        owner_slug=slug,
                        aliases=aliases,
                        members=members,
                        skips=schedule_skips,
                        scope=scope,
                        gender=school.gender,
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
                        skips=tuple(schedule_skips),
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
                        parsed={"fixtures": fixtures, "skips": schedule_skips},
                    )
            else:
                page = fetched.page
                assert page is not None
                schedule_html = page.html
                schedule_url = page.final_url
                fixtures = recipe.parse_schedule(
                    page.html,
                    page_url=page.final_url,
                    year=year,
                    owner_slug=slug,
                    aliases=aliases,
                    members=members,
                    skips=schedule_skips,
                    scope=scope,
                    gender=school.gender,
                )
                recipe.assert_schedule_proven(
                    page.html,
                    year=year,
                    page_url=page.final_url,
                    fixtures=fixtures,
                    owner_slug=slug,
                )
                outcomes[LAYER_SCHEDULE] = LayerOutcome(
                    LAYER_SCHEDULE,
                    STATE_COMPLETE if fixtures else STATE_EMPTY,
                    count=len(fixtures),
                    reason=None
                    if fixtures
                    else f"[{year}] the {year} schedule page proved its season but listed no fixtures",
                    source_url=page.final_url,
                    skips=tuple(schedule_skips),
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
                        parsed={"fixtures": fixtures, "skips": schedule_skips},
                    )
        except NoCollector as exc:
            outcomes[LAYER_SCHEDULE] = LayerOutcome(
                LAYER_SCHEDULE, STATE_NO_COLLECTOR, reason=exc.reason(school)
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
        fingerprint = parse_fingerprint(year, *recipe.parse_identity)
        state = page_cache.load(slug, LAYER_ROSTER, fingerprint) if page_cache else None
        try:
            roster_url = recipe.layer_url(base_url, year, LAYER_ROSTER)
            fetched = _fetch_layer(
                recipe,
                client,
                base_url,
                roster_url,
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
                    players = recipe.parse_roster(
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
                players = recipe.parse_roster(page.html, page_url=page.final_url)
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
        except NoCollector as exc:
            outcomes[LAYER_ROSTER] = LayerOutcome(
                LAYER_ROSTER, STATE_NO_COLLECTOR, reason=exc.reason(school)
            )
        except (LiveCollectionError, OSError) as exc:
            outcomes[LAYER_ROSTER] = LayerOutcome(
                LAYER_ROSTER, STATE_UNAVAILABLE, reason=str(exc), source_url=roster_url
            )
            if page_cache is not None and roster_html:
                page_cache.invalidate(slug, LAYER_ROSTER)

    if LAYER_STATS in wanted:
        fingerprint = parse_fingerprint(year, *recipe.parse_identity)
        state = page_cache.load(slug, LAYER_STATS, fingerprint) if page_cache else None
        try:
            # A platform whose statistics page the base URL alone cannot
            # name locates it first, through this collection's session.
            # A recipe that fetches its own layers locates them itself.
            stats_url = (
                recipe.locate_stats(client, base_url, year)
                if recipe.locate_stats is not None and recipe.fetch_layer is None
                else recipe.layer_url(base_url, year, LAYER_STATS)
            )
            fetched = _fetch_layer(
                recipe,
                client,
                base_url,
                stats_url,
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
                    stat_players, stat_keepers = recipe.parse_stats(
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
                stat_players, stat_keepers = recipe.parse_stats(
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
        except NoCollector as exc:
            outcomes[LAYER_STATS] = LayerOutcome(
                LAYER_STATS, STATE_NO_COLLECTOR, reason=exc.reason(school)
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
