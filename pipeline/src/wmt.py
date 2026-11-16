"""What the pipeline knows about WMT Digital athletics sites.

WMT Digital is the third platform the pipeline recognises, and this module
holds everything the pipeline knows about it: the URL shapes, the season,
sport and match proofs, the location of every id a layer needs, and the
parsers for all four layers.  The recipe that hands these to
``collect_programme`` and the board collector is ``WMT`` in src/recipes.py.
The measured reconnaissance behind it is
``d1-soccer/data/scratch/authoring/wmt/FINDINGS.md`` (2026-11-15); the
captures it cites are this module's test fixtures.

Two generations share the platform.  The Nuxt generation (13 of the 15
programmes measured) renders every season page from a ``__NUXT_DATA__``
payload over an open JSON API at ``{origin}/website-api``; the WordPress
generation (South Carolina, Kentucky) server-renders its schedule and
roster.  Both send season statistics and box scores to one shared host,
``wmt.games``, whose ``/proxy-api`` answers JSON.

**A layer is a bundle.**  No WMT layer can be read from one URL: a Nuxt
schedule is the season page (season proof, schedule id, the site's
timezone) plus the schedule-events API; statistics are the season page
(team id) plus the ``wmt.games`` team season.  So ``fetch_layer`` (the
recipe member ``collect_programme`` calls in place of a single conditional
fetch) fetches every body the layer's parse relies on, proves each, and
returns them as one *bundle*: a JSON document naming the bundle schema, the
layer, the season, the generation, and one part per served body with its
role, requested and final URL, HTTP status, ETag, and the body itself as a
string, exactly as served.  A ``wmt.games`` body wrapped as ``{"__gz":
base64}`` is kept wrapped; ``decode_json_body`` unwraps it at parse time.
The bundle is what ``write_raw_pages`` archives as the layer's raw page and
what every parser reads, so a parser change re-reads the archive without
the network.  A bundle part that a ``wmt.games`` request answers 304 to
(``If-None-Match`` from the archived part's ETag) is the archived body,
reused verbatim.

**Ids are located, never guessed.**  The season slug is the plain year or
the academic year (``2025`` or ``2025-26``), chosen by the site: the year
is asked first and an honest 404 moves to the academic year, so Penn
State's ``2025`` fall schedule is never confused with its ``2025-26``
spring one.  The schedule id is the schedule page's own; the statistics
team id is the season roster's ``wmt_stats2_team_id``, proven by the team's
``academicYear`` (``year + 1`` for the fall ``year`` season) and, when that
proof fails or the id is missing, recovered from the owner's ``teamId`` in
the header of one of the season's own games.  A played match with no game
id on the site is joined to the ``wmt.games`` Game by Game table by its
local date.  The statistics host itself is read off the site's own iframe
URLs.

**Dates.**  The schedule API's ``datetime`` is UTC, which is the wrong
calendar day for most evening matches; it is converted with the site's own
``website_timezone``.  ``wmt.games`` ``gameDate`` is the venue's wall-clock
time labelled ``Z``; it is read, never converted.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import json
import logging
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from bs4 import BeautifulSoup

from src.page_state import BoxArchive, PageState, content_signature
from src.presto import _roster_class_year, _roster_position
from src.sidearm_live import (
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    ConditionalFetch,
    LiveCollectionError,
    PublishedPage,
    ResolutionScope,
    _clean_team_name,
    _identity_key,
    _name_slug_affinity,
    _nuxt_state,
    _seeded,
    _SHOOTOUT_MARKER,
    _stat_float,
    _stat_int,
    _stat_minutes,
    _stat_pair,
    assert_served_body,
    failure_detail,
    hosted_skip,
    http_status,
    opponent_slug,
    orient_match,
    placeholder_skip,
    round_placeholder,
)

_LOG = logging.getLogger(__name__)

PLATFORM = "wmt"
BUNDLE_SCHEMA = "touchline.wmt-bundle/1"
GENERATION_NUXT = "nuxt"
GENERATION_WORDPRESS = "wordpress"

#: ``wmt.games``'s code for men's soccer, on every team and game it serves.
SPORT_CODE = "MSO"

# --- Bodies and bundles -------------------------------------------------------


def decode_json_body(text: str, url: str) -> Any:
    """A served JSON body, with the ``{"__gz": base64}`` wrapper undone.

    Measured on wmt.games (FINDINGS.md section 3): 13 of 14 responses were
    the wrapper, one the plain object, with no rule found for which.  The
    wrapper is the whole body when present.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveCollectionError(
            f"{url} served a body that is not JSON: {exc}"
        ) from exc
    if isinstance(value, dict) and set(value) == {"__gz"}:
        try:
            value = json.loads(
                gzip.decompress(base64.b64decode(str(value["__gz"]))).decode("utf-8")
            )
        except (
            binascii.Error,
            OSError,
            EOFError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise LiveCollectionError(
                f"{url} served a __gz body that does not decode: {exc}"
            ) from exc
    return value


@dataclass(frozen=True)
class Part:
    """One served body a layer's parse relies on, as it was served."""

    role: str
    url: str
    final_url: str
    status: int
    body: str
    etag: str | None = None

    def json(self) -> Any:
        return decode_json_body(self.body, self.final_url)

    def record(self) -> dict[str, object]:
        return {
            "role": self.role,
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "etag": self.etag,
            "body": self.body,
        }


@dataclass(frozen=True)
class Bundle:
    """A layer's served bodies, in the order they were fetched."""

    layer: str
    season: int
    generation: str
    parts: tuple[Part, ...]
    notes: tuple[str, ...] = ()

    def first(self, role: str) -> Part | None:
        return next((part for part in self.parts if part.role == role), None)

    def all(self, role: str) -> list[Part]:
        return [part for part in self.parts if part.role == role]

    def text(self) -> str:
        return json.dumps(
            {
                "schema": BUNDLE_SCHEMA,
                "layer": self.layer,
                "season": self.season,
                "generation": self.generation,
                "notes": list(self.notes),
                "parts": [part.record() for part in self.parts],
            },
            indent=1,
            ensure_ascii=False,
        )

    def signature(self) -> str:
        """The bundle's content identity: the bodies and where they came
        from, not their validators (a fresh ETag over the same bytes is the
        same content)."""
        return content_signature(
            json.dumps(
                [[part.role, part.url, _stable_body(part)] for part in self.parts],
                ensure_ascii=False,
            )
        )

    @property
    def final_url(self) -> str:
        """The page a reader opens for this layer: the first part's."""
        return self.parts[0].final_url if self.parts else ""


def _stable_body(part: Part) -> str:
    """A part's body as its content identity sees it.

    A Nuxt season page stamps the moment its site configuration loaded
    (``pinia["oas-config"].configLoadedAt``, epoch milliseconds) into every
    render: measured as the one token two fetches of goseattleu.com's 2025
    statistics page differ by.  That stamp is masked so an unchanged page
    reads as unchanged; the archive keeps the body as served.

    A JSON part is identified by what it decodes to.  The ``{"__gz":
    base64}`` wrapper is re-compressed by the statistics host from time to
    time (measured 2026-11-15: South Carolina's team season answered a new
    ETag and new wrapper bytes over the same season), so its bytes are not
    its content.
    """
    if part.body.lstrip().startswith(("{", "[")):
        try:
            return json.dumps(
                decode_json_body(part.body, part.url),
                sort_keys=True,
                ensure_ascii=False,
            )
        except LiveCollectionError:
            return part.body
    if part.role != "page":
        return part.body
    pinia = _nuxt_state(part.body).get("pinia")
    config = pinia.get("oas-config") if isinstance(pinia, dict) else None
    stamp = config.get("configLoadedAt") if isinstance(config, dict) else None
    if isinstance(stamp, int) and not isinstance(stamp, bool):
        return re.sub(rf"(?<![0-9]){stamp}(?![0-9])", "0", part.body, count=1)
    return part.body


def read_bundle(text: str) -> Bundle:
    """Read an archived or freshly built bundle back, or refuse it."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveCollectionError(f"not a WMT layer bundle: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != BUNDLE_SCHEMA:
        raise LiveCollectionError("not a WMT layer bundle: no bundle schema")
    parts = tuple(
        Part(
            role=str(raw.get("role") or ""),
            url=str(raw.get("url") or ""),
            final_url=str(raw.get("final_url") or raw.get("url") or ""),
            status=int(raw.get("status") or 0),
            body=str(raw.get("body") or ""),
            etag=raw.get("etag") if isinstance(raw.get("etag"), str) else None,
        )
        for raw in value.get("parts") or []
        if isinstance(raw, dict)
    )
    return Bundle(
        layer=str(value.get("layer") or ""),
        season=int(value.get("season") or 0),
        generation=str(value.get("generation") or ""),
        parts=parts,
        notes=tuple(str(note) for note in value.get("notes") or []),
    )


def presume_paced(session: requests.Session, url: str) -> None:
    """Ask the collection's gate to pace ``url``'s host before the first
    request there.

    Every WMT programme measured sends statistics and box scores to one
    shared host (``wmt.games``), so it is treated as a paced host from the
    first request, never discovered to be one by a challenge.  The host is
    the one the site's own pages name (``stats_origin``), not a constant.
    A plain session (a test, a probe) has no gate and nothing to ask.
    """
    ask = getattr(session, "presume_paced", None)
    if callable(ask):
        ask(url)


class _Fetcher:
    """Every request a layer makes, through the collection's own session.

    The session is the board collector's host-gated one, so every request
    here holds its host's single slot and rides its pacing; nothing here
    adds headers of its own except ``If-None-Match``.  ``previous`` is the
    archived bundle's parts by URL: a ``conditional`` request asks with the
    archived part's ETag, and a 304 is that part, reused verbatim.
    """

    def __init__(
        self,
        session: requests.Session,
        year: int,
        kind: str,
        previous: dict[str, Part] | None = None,
    ) -> None:
        self.session = session
        self.year = year
        self.kind = kind
        self.previous = previous or {}
        #: Every URL asked conditionally: the parts whose archived ETag the
        #: next run sends in ``If-None-Match``.
        self.conditional: set[str] = set()

    def get(
        self,
        role: str,
        url: str,
        *,
        expect: str = "html",
        allow_404: bool = False,
        conditional: bool = False,
    ) -> Part | None:
        if conditional:
            # Every conditional part is a statistics-host body.
            presume_paced(self.session, url)
            self.conditional.add(url)
        prior = self.previous.get(url) if conditional else None
        headers = {"If-None-Match": prior.etag} if prior and prior.etag else None
        try:
            response = self.session.get(url, timeout=30, headers=headers)
            if headers is not None and response.status_code == 304:
                assert prior is not None
                return Part(
                    role, url, prior.final_url, prior.status, prior.body, prior.etag
                )
            if allow_404 and response.status_code == 404:
                return None
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LiveCollectionError(
                f"[{self.year}] failed to fetch {self.kind} {role} {url}: {exc}",
                status=http_status(exc),
            ) from exc
        assert_served_body(
            response, year=self.year, kind=f"{self.kind} {role}", url=url, body=expect
        )
        served = getattr(response, "headers", None) or {}
        return Part(
            role=role,
            url=url,
            final_url=str(getattr(response, "url", "") or url),
            status=int(response.status_code),
            body=response.text,
            etag=served.get("ETag") if hasattr(served, "get") else None,
        )

    def require(self, role: str, url: str, **kwargs: Any) -> Part:
        part = self.get(role, url, **kwargs)
        assert part is not None  # only allow_404 returns nothing
        return part


# --- Addresses -----------------------------------------------------------------

_SPORT_PATH = re.compile(r"^(?P<prefix>.*?/sports/(?P<sport>[A-Za-z0-9_-]+))/?$")


def sport_base(base_url: str) -> tuple[str, str, str]:
    """``(origin, sport, base)`` for a stanza's ``{origin}/sports/{sport}``.

    The sport path is the site's own (``mens-soccer`` on most, ``msoc`` on
    Virginia, Notre Dame and both WordPress sites) and is read from the
    stanza's URL, never assumed.
    """
    parsed = urlparse(base_url.strip())
    match = _SPORT_PATH.match(parsed.path)
    if not parsed.scheme or not parsed.netloc or match is None:
        raise LiveCollectionError(
            f"{base_url} is not a WMT sport landing page ({{origin}}/sports/{{sport}})"
        )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, match.group("sport"), f"{origin}{match.group('prefix')}"


def season_slugs(year: int) -> tuple[str, str]:
    """The two season slugs a WMT site may file the fall ``year`` season
    under, in the order they are asked: ``2025`` first, then ``2025-26``.

    Measured (FINDINGS.md section 1): eleven Nuxt sites file it as
    ``2025``, Virginia and Notre Dame as ``2025-26``, and Penn State has
    both, ``2025`` its 20-event fall schedule and ``2025-26`` a 5-event
    spring one, so the plain year must win whenever the site serves it.
    """
    return (str(year), f"{year}-{(year + 1) % 100:02d}")


def pick_season_slug(slugs: list[str], year: int) -> str | None:
    """The slug for the fall ``year`` season among the slugs a site lists:
    the plain year when listed, else the academic year, never a prefix
    match (Penn State's ``2025-26`` also starts with ``2025``)."""
    for wanted in season_slugs(year):
        if wanted in slugs:
            return wanted
    return None


def layer_url(base_url: str, year: int, kind: str) -> str:
    """The season page a reader opens for one layer, by the plain year.

    Informational: ``fetch_layer`` locates the page the site actually files
    the season under (``season_slugs``) and every outcome names the URL it
    was served from.
    """
    _, _, base = sport_base(base_url)
    if kind not in (LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS):
        raise ValueError(f"{kind!r} is not a WMT season layer")
    return f"{base}/{kind}/season/{year}"


def game_url(origin: str, game_id: object) -> str:
    return f"{origin}/proxy-api/games/{game_id}?view=full"


def team_season_url(origin: str, team_id: object) -> str:
    return f"{origin}/proxy-api/teams/{team_id}/season"


_STATS_LINK = re.compile(
    r"(https?://[A-Za-z0-9.-]+)/[A-Za-z0-9_-]+/stats/(?:season|match|roster)/"
)
_FRONTEND_BASE = re.compile(r'"frontend"\s*:\s*\{\s*"base"\s*:\s*"(https?:[^"]+)"')


def stats_origin(html: str) -> str | None:
    """The statistics host a site's own pages name, or nothing.

    Nuxt pages carry ``wmt_stats2_iframe_url`` values
    (``https://wmt.games/goseattleu/stats/season/604058``) on their rosters,
    events and players; WordPress pages declare ``var wmtGames =
    {"frontend":{"base":"https://wmt.games"}}``.  Both are read with the
    script escapes undone (``\\u002F``, ``\\/``).
    """
    text = html.replace("\\u002F", "/").replace("\\/", "/")
    match = _STATS_LINK.search(text)
    if match:
        return match.group(1)
    match = _FRONTEND_BASE.search(text)
    return match.group(1).rstrip("/") if match else None


# --- Proofs --------------------------------------------------------------------

_LEADING_YEAR = re.compile(r"^\s*(\d{4})\b")
_MENS_SOCCER = re.compile(r"^\s*men'?s\s+soccer\s*$", re.IGNORECASE)


def _leading_year(text: object) -> int | None:
    match = _LEADING_YEAR.match(str(text or ""))
    return int(match.group(1)) if match else None


def _is_mens_soccer(name: object) -> bool:
    return bool(_MENS_SOCCER.match(str(name or "").replace("’", "'")))


def _nuxt_data(state: dict[str, Any]) -> dict[str, Any]:
    data = state.get("data")
    return data if isinstance(data, dict) else {}


def _entity(state: dict[str, Any]) -> dict[str, Any]:
    inner = state.get("state")
    entity = (
        inner.get("$scurrent-dashboard-entity") if isinstance(inner, dict) else None
    )
    return entity if isinstance(entity, dict) else {}


def site_timezone(state: dict[str, Any]) -> str | None:
    """The site's own ``website_timezone`` from its page payload."""
    pinia = state.get("pinia")
    config = pinia.get("oas-config") if isinstance(pinia, dict) else None
    config = config.get("config") if isinstance(config, dict) else None
    settings = config.get("settings") if isinstance(config, dict) else None
    value = settings.get("website_timezone") if isinstance(settings, dict) else None
    return str(value) if value else None


#: The page-payload key holding the season object each layer's page proves
#: itself by, and the dashboard entity type the page renders under.  The
#: statistics page renders under the season roster (measured on all three
#: captured statistics pages), and carries that roster's team id.
_SEASON_OBJECT = {
    LAYER_SCHEDULE: ("sport-{sport}-schedule-by-slug-{slug}", "schedule"),
    LAYER_ROSTER: ("sport-{sport}-roster-season-{slug}", "roster"),
    LAYER_STATS: ("sport-{sport}-roster-season-{slug}", "roster"),
}


@dataclass(frozen=True)
class NuxtPage:
    """A season page that proved its sport and season."""

    state: dict[str, Any]
    #: The schedule (schedule page) or season roster (roster and
    #: statistics pages) the page renders.
    season_object: dict[str, Any]
    sport_view: dict[str, Any]
    slug: str


def prove_nuxt_page(
    html: str, *, year: int, kind: str, sport: str, slug: str, url: str
) -> NuxtPage:
    """Refuse a Nuxt season page that is not men's soccer's ``year`` season.

    Three witnesses, every one required.  The dashboard entity the page
    renders (``{"type": "schedule", "id": 75, "seasonSlug": "2025"}``) must
    be the layer's type and name the requested slug.  The sport view
    (``sport-view-{sport}``) must be the stanza's sport path and be named
    men's soccer.  The season object (``sport-{sport}-schedule-by-slug-
    {slug}`` or ``sport-{sport}-roster-season-{slug}``) must be the entity
    itself, belong to that sport, and carry a season whose slug is the one
    asked for and whose name leads with ``year`` ("2025", "2025-26";
    Clemson's slug ``2025`` is named "2025-26").  An unknown slug answers an
    honest 404 (measured on Seattle U 1999, Stanford and Clemson 2031,
    Virginia 2025), handled before this proof.
    """
    state = _nuxt_state(html)
    if not state:
        raise LiveCollectionError(
            f"[{year}] {url} carries no __NUXT_DATA__ payload: not a WMT Nuxt season page"
        )
    data = _nuxt_data(state)
    entity = _entity(state)
    key, entity_type = _SEASON_OBJECT[kind]
    served_slug = str(entity.get("seasonSlug") or "")
    if entity.get("type") != entity_type or served_slug != slug:
        raise LiveCollectionError(
            f"[{year}] requested the {kind} season {slug} but {url} rendered "
            f"{entity.get('type') or 'no'} season {served_slug or 'none'}"
        )
    view = data.get(f"sport-view-{sport}")
    if not isinstance(view, dict) or view.get("slug") != sport:
        raise LiveCollectionError(
            f"[{year}] {url} renders no sport view for /sports/{sport}"
        )
    if not _is_mens_soccer(view.get("name")):
        raise LiveCollectionError(
            f"[{year}] {url} is the {view.get('name')!r} sport, not men's soccer"
        )
    season_object = data.get(key.format(sport=sport, slug=slug))
    if not isinstance(season_object, dict):
        raise LiveCollectionError(
            f"[{year}] {url} carries no {kind} season object for {slug}"
        )
    season = season_object.get("season")
    season = season if isinstance(season, dict) else {}
    if str(season.get("slug") or "") != slug:
        raise LiveCollectionError(
            f"[{year}] {url} rendered the {kind} of season "
            f"{season.get('slug') or 'none'}, not {slug}"
        )
    if _leading_year(season.get("name")) != year or _leading_year(slug) != year:
        raise LiveCollectionError(
            f"[{year}] {url} rendered season {season.get('name')!r}, not the {year} season"
        )
    if season_object.get("id") != entity.get("id"):
        raise LiveCollectionError(
            f"[{year}] {url} renders {entity_type} {entity.get('id')} but carries "
            f"{kind} season object {season_object.get('id')}"
        )
    if season_object.get("sport_id") not in (None, view.get("id")):
        raise LiveCollectionError(
            f"[{year}] {url}: the {kind} season object belongs to sport "
            f"{season_object.get('sport_id')}, not {view.get('id')} ({sport})"
        )
    return NuxtPage(state, season_object, view, slug)


#: The generation each site origin has served in this process, so a later
#: layer asks the generation's own address first.  Measured 2026-11-15: a
#: WordPress site answers the Nuxt statistics path (``/stats/season/2025``)
#: with two redirects to an unrelated 2011 news article, and its season
#: pages without the trailing slash with one redirect.  A guess, never a
#: witness: every page is still proven by its own content.
_GENERATIONS: dict[str, str] = {}


def _season_candidates(base: str, year: int, kind: str) -> list[tuple[str, str]]:
    """``(url, slug)`` for each address the season page may live at, in the
    order asked: the plain year, then (statistics only) the WordPress
    generation's ``cumestats`` page, then the academic year.  A site already
    seen to be WordPress is asked its own addresses only."""
    plain, academic = season_slugs(year)
    if _GENERATIONS.get(urlparse(base).netloc) == GENERATION_WORDPRESS:
        path = "cumestats" if kind == LAYER_STATS else kind
        return [(f"{base}/{path}/season/{plain}/", plain)]
    candidates = [(f"{base}/{kind}/season/{plain}", plain)]
    if kind == LAYER_STATS:
        candidates.append((f"{base}/cumestats/season/{plain}/", plain))
    candidates.append((f"{base}/{kind}/season/{academic}", academic))
    return candidates


def _season_page(
    fetcher: _Fetcher, base: str, year: int, kind: str
) -> tuple[Part, str]:
    """The first season page the site serves for the season: the plain
    year's, else the academic year's (``season_slugs``).  An honest 404 on
    every candidate is the site saying it files no such season.  (A
    WordPress site never answers 404 here: it serves its current season
    under any season path, which ``prove_wordpress_page`` refuses.)"""
    tried: list[str] = []
    for url, slug in _season_candidates(base, year, kind):
        part = fetcher.get("page", url, allow_404=True)
        if part is not None:
            return part, slug
        tried.append(url)
    raise LiveCollectionError(
        f"[{year}] the site files no {year} {kind} season: "
        f"{' and '.join(tried)} answered HTTP 404",
        status=404,
    )


def prove_team_season(season: Any, *, team_id: object, year: int, url: str) -> None:
    """Refuse a ``wmt.games`` team season that is not men's soccer's
    ``year`` season for ``team_id``.

    ``academicYear`` names the spring the season ends in: 2026 for fall 2025
    (Seattle U's 604058 reads ``academicYear: 2026, seasonLabel:
    "2025-26"``).  Old Dominion's 2025 roster carries 587798, which answers
    ``academicYear: 2025`` ("2024-25"): the previous season's team, refused
    here (FINDINGS.md trap 6.4).
    """
    team = season.get("team") if isinstance(season, dict) else None
    if not isinstance(team, dict):
        raise LiveCollectionError(f"[{year}] {url} carries no team")
    if str(team.get("id")) != str(team_id):
        raise LiveCollectionError(
            f"[{year}] requested statistics team {team_id} but {url} served team {team.get('id')}"
        )
    if team.get("sportCode") != SPORT_CODE:
        raise LiveCollectionError(
            f"[{year}] statistics team {team_id} is sport {team.get('sportCode')!r}, "
            f"not men's soccer ({SPORT_CODE})"
        )
    academic = _stat_int(str(team.get("academicYear") or ""))
    if academic is None:
        academic = (_leading_year(team.get("seasonLabel")) or -2) + 1
    if academic != year + 1:
        raise LiveCollectionError(
            f"[{year}] statistics team {team_id} is the {team.get('seasonLabel') or academic} "
            f"season (academicYear {team.get('academicYear')}), not {year}-"
            f"{(year + 1) % 100:02d}"
        )


def prove_game(game: Any, *, game_id: object, year: int, url: str) -> dict[str, Any]:
    """The header of a ``wmt.games`` game that is the requested men's
    soccer game, or a refusal."""
    header = game.get("header") if isinstance(game, dict) else None
    if not isinstance(header, dict):
        raise LiveCollectionError(f"[{year}] {url} carries no game header")
    if str(header.get("gameId")) != str(game_id):
        raise LiveCollectionError(
            f"[{year}] requested game {game_id} but {url} served game {header.get('gameId')}"
        )
    if header.get("sportCode") != SPORT_CODE:
        raise LiveCollectionError(
            f"[{year}] game {game_id} is sport {header.get('sportCode')!r}, not men's soccer"
        )
    return header


# --- Tables -------------------------------------------------------------------


def _walk_tables(
    tabs: Any, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    """Every ``{title, head, body, footer}`` table under ``tabs``, with the
    titles of the tabs above it."""
    for tab in tabs if isinstance(tabs, list) else []:
        if not isinstance(tab, dict):
            continue
        here = (*path, str(tab.get("title") or ""))
        for table in tab.get("tables") or []:
            if isinstance(table, dict):
                yield here, table
        yield from _walk_tables(tab.get("children"), here)


def _cells(row: Any) -> dict[str, Any]:
    """A table row's cells by ``key`` (the column's machine name)."""
    found: dict[str, Any] = {}
    for cell in row if isinstance(row, list) else []:
        if isinstance(cell, dict) and cell.get("key"):
            found[str(cell["key"])] = cell
    return found


def _text(cell: Any) -> str:
    value = cell.get("value") if isinstance(cell, dict) else cell
    return "" if value is None else " ".join(str(value).split())


def _cell_int(cells: dict[str, Any], key: str) -> int | None:
    return _stat_int(_text(cells.get(key)))


def game_by_game(season: Any) -> list[tuple[str, int, str]]:
    """``(date, game id, title)`` for every row of the team season's Game
    by Game table: a second schedule, measured to list games whose id the
    site's own event lacks (FINDINGS.md trap 6.6).  The date cell reads
    ``08/21/2025`` and carries ``meta: {gameId, gameTitle}``."""
    rows: list[tuple[str, int, str]] = []
    seen: set[int] = set()
    for path, table in _walk_tables(
        season.get("tabs") if isinstance(season, dict) else None
    ):
        if not path or path[0] != "Game by Game":
            continue
        for row in table.get("body") or []:
            cell = _cells(row).get("gameDate")
            meta = cell.get("meta") if isinstance(cell, dict) else None
            game_id = _stat_int(str((meta or {}).get("gameId") or ""))
            date = _us_date(_text(cell))
            if game_id is None or date is None or game_id in seen:
                continue
            seen.add(game_id)
            rows.append((date, game_id, str((meta or {}).get("gameTitle") or "")))
    return rows


_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _us_date(text: str) -> str | None:
    match = _US_DATE.match(text.strip())
    if not match:
        return None
    month, day, year = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


# --- Locating the statistics team -------------------------------------------


def _played(event: dict[str, Any]) -> bool:
    return str(event.get("status") or "") == "completed"


def _unlinked_result(event: dict[str, Any]) -> bool:
    """A played event that published a result (win, loss, tie) but no game
    id: the events the Game by Game join exists for (trap 6.6).  A
    ``no_result`` exhibition published no match to link."""
    result = event.get("schedule_event_result")
    published = result.get("result") if isinstance(result, dict) else None
    return (
        _played(event)
        and not event.get("wmt_stats2_game_id")
        and published in _RESULT_LETTERS
    )


def locate_team_by_game(
    fetcher: _Fetcher, events: list[dict[str, Any]], *, year: int, origin: str
) -> tuple[list[Part], int]:
    """The season's statistics team, read off one of its own games.

    For a roster carrying no team id (Clemson 2026, trap 6.5) or the wrong
    one (Old Dominion 2025, trap 6.4), and for the Game by Game join: the
    first played home or away event with a game id is fetched, and the
    owner's side of its header (``venue_type`` says which: a neutral-site
    header lists the sides in no order the site's row can confirm, so those
    are passed over) names the team.  The team season must then prove its
    season (``prove_team_season``) and list that very game in its Game by
    Game table, so a team id read off the wrong side is refused rather than
    trusted.  Returns the game and season parts and the team id.
    """
    for event in events:
        side = str(event.get("venue_type") or "")
        game_id = event.get("wmt_stats2_game_id")
        if not _played(event) or not game_id or side not in ("home", "away"):
            continue
        url = game_url(origin, game_id)
        game_part = fetcher.require("game", url, expect="json", conditional=True)
        header = prove_game(game_part.json(), game_id=game_id, year=year, url=url)
        owner = header.get(side)
        team_id = owner.get("teamId") if isinstance(owner, dict) else None
        if not team_id:
            raise LiveCollectionError(
                f"[{year}] game {game_id} names no teamId on the {side} side"
            )
        season_url = team_season_url(origin, team_id)
        season_part = fetcher.require(
            "season", season_url, expect="json", conditional=True
        )
        season = season_part.json()
        prove_team_season(season, team_id=team_id, year=year, url=season_url)
        if int(game_id) not in {row[1] for row in game_by_game(season)}:
            raise LiveCollectionError(
                f"[{year}] statistics team {team_id} (the {side} side of game "
                f"{game_id}) does not list that game in its Game by Game table"
            )
        return [game_part, season_part], int(team_id)
    raise LiveCollectionError(
        f"[{year}] no played home or away match carries a statistics game id "
        f"to locate the team from"
    )


# --- The Nuxt layers ------------------------------------------------------------

_EVENT_INCLUDES = (
    "opponent,schedule.sport,scheduleEventResult,secondOpponent,tournament"
)
_MAX_EVENT_PAGES = 10


def events_url(origin: str, schedule_id: object, page: int = 1) -> str:
    query = {
        "filter[schedule_id]": schedule_id,
        "include": _EVENT_INCLUDES,
        "per_page": 100,
        "sort": "datetime",
    }
    if page > 1:
        query["page"] = page
    return f"{origin}/website-api/schedule-events?{urlencode(query)}"


def _fetch_events(
    fetcher: _Fetcher, origin: str, schedule_id: object
) -> tuple[list[Part], list[dict[str, Any]]]:
    """Every event of one schedule, page by page, as served."""
    parts: list[Part] = []
    events: list[dict[str, Any]] = []
    for page in range(1, _MAX_EVENT_PAGES + 1):
        part = fetcher.require(
            "events", events_url(origin, schedule_id, page), expect="json"
        )
        parts.append(part)
        body = part.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise LiveCollectionError(
                f"[{fetcher.year}] {part.final_url} carries no event list"
            )
        events.extend(event for event in data if isinstance(event, dict))
        meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        if int(meta.get("last_page") or 1) <= page:
            break
    return parts, events


def prove_events(
    events: list[dict[str, Any]],
    *,
    schedule_id: object,
    sport: str,
    year: int,
    timezone: str,
    url: str,
) -> None:
    """Refuse an event list that is not the proven schedule's.

    Every event must name the schedule the page proved (a filter the API
    does not know is silently ignored and answers every sport's events,
    FINDINGS.md section 2, which this catches) and that schedule's sport;
    and every event's local date must fall in the season's two calendar
    years (a season runs into the next one: spring friendlies, trap 6.8).
    """
    for event in events:
        if str(event.get("schedule_id")) != str(schedule_id):
            raise LiveCollectionError(
                f"[{year}] {url} answered event {event.get('id')} of schedule "
                f"{event.get('schedule_id')}, not schedule {schedule_id}"
            )
        schedule = event.get("schedule")
        served_sport = schedule.get("sport") if isinstance(schedule, dict) else None
        if not isinstance(served_sport, dict) or served_sport.get("slug") != sport:
            raise LiveCollectionError(
                f"[{year}] {url}: event {event.get('id')} does not name the {sport} sport"
            )
        local = local_kickoff(event.get("datetime"), timezone)
        if local is None or local.year not in (year, year + 1):
            raise LiveCollectionError(
                f"[{year}] {url}: event {event.get('id')} is dated "
                f"{event.get('datetime')!r}, outside the {year} season"
            )


def _zone(name: str, year: int) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise LiveCollectionError(
            f"[{year}] the site names an unknown timezone {name!r}"
        ) from exc


def local_kickoff(value: object, timezone: str) -> datetime | None:
    """A schedule ``datetime`` (UTC, ``2025-08-22T00:00:00.000000Z``) as the
    site's own wall-clock time."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(ZoneInfo(timezone))


def _fetch_nuxt(
    fetcher: _Fetcher, page: Part, slug: str, base_url: str, year: int, kind: str
) -> tuple[list[Part], list[str]]:
    origin, sport, _ = sport_base(base_url)
    proven = prove_nuxt_page(
        page.body, year=year, kind=kind, sport=sport, slug=slug, url=page.final_url
    )
    parts = [page]
    notes: list[str] = []
    data = _nuxt_data(proven.state)
    if kind == LAYER_SCHEDULE:
        timezone = site_timezone(proven.state)
        if not timezone:
            raise LiveCollectionError(
                f"[{year}] {page.final_url} names no website timezone, so its "
                f"UTC kickoffs cannot be dated"
            )
        _zone(timezone, year)
        schedule_id = proven.season_object.get("id")
        event_parts, events = _fetch_events(fetcher, origin, schedule_id)
        prove_events(
            events,
            schedule_id=schedule_id,
            sport=sport,
            year=year,
            timezone=timezone,
            url=event_parts[0].final_url,
        )
        parts.extend(event_parts)
        # The Game by Game join needs the team season; it is fetched only
        # when a played event lacks its game id (FINDINGS.md trap 6.6).
        if any(_unlinked_result(event) for event in events):
            origin_stats = stats_origin(page.body)
            try:
                if origin_stats is None:
                    raise LiveCollectionError(
                        f"[{year}] {page.final_url} names no statistics host"
                    )
                located, team_id = locate_team_by_game(
                    fetcher, events, year=year, origin=origin_stats
                )
                parts.extend(located)
                notes.append(
                    f"statistics team {team_id} located from a game header to join "
                    f"played events without a game id"
                )
            except LiveCollectionError as exc:
                # The schedule stands without the join; the matches the
                # join would have linked are named gaps there.
                _LOG.warning(
                    "%s: the Game by Game join is unavailable: %s", page.final_url, exc
                )
                notes.append(join_unavailable_note(exc))
    elif kind == LAYER_ROSTER:
        key = f"roster-{proven.season_object.get('id')}-players-list"
        if not isinstance(data.get(key), list):
            raise LiveCollectionError(
                f"[{year}] {page.final_url} proved its season but carries no "
                f"players list ({key})"
            )
    else:
        origin_stats = stats_origin(page.body)
        if origin_stats is None:
            raise LiveCollectionError(
                f"[{year}] {page.final_url} names no statistics host"
            )
        team_id = proven.season_object.get("wmt_stats2_team_id")
        refused = "the season roster carries no statistics team id"
        if team_id:
            url = team_season_url(origin_stats, team_id)
            season_part = fetcher.require(
                "season", url, expect="json", conditional=True
            )
            try:
                prove_team_season(
                    season_part.json(), team_id=team_id, year=year, url=url
                )
                parts.append(season_part)
                return parts, notes
            except LiveCollectionError as exc:
                refused = str(exc)
                parts.append(
                    Part(
                        "season-refused",
                        season_part.url,
                        season_part.final_url,
                        season_part.status,
                        season_part.body,
                        season_part.etag,
                    )
                )
        # Recover the team from the season's own games (traps 6.4, 6.5).
        schedule = data.get(
            f"sport-{sport}-schedule-{proven.season_object.get('season_id')}"
        )
        schedule_id = schedule.get("id") if isinstance(schedule, dict) else None
        if not schedule_id:
            raise LiveCollectionError(
                f"[{year}] {refused}, and {page.final_url} names no season schedule "
                f"to recover the team from"
            )
        event_parts, events = _fetch_events(fetcher, origin, schedule_id)
        parts.extend(event_parts)
        located, located_id = locate_team_by_game(
            fetcher, events, year=year, origin=origin_stats
        )
        parts.extend(located)
        notes.append(
            f"statistics team {located_id} recovered from a game header: {refused}"
        )
    return parts, notes


def fetch_layer(
    session: requests.Session,
    base_url: str,
    year: int,
    kind: str,
    *,
    state: PageState | None = None,
    want_validators: bool = False,
) -> ConditionalFetch:
    """Fetch, prove and bundle every body one season layer relies on.

    The recipe's replacement for the single conditional fetch: the returned
    page is the bundle (``Bundle.text``), proven part by part before it is
    returned.  With a ``state`` (the archived bundle's sidecar), the
    ``wmt.games`` parts ask with their archived ETags and a 304 reuses the
    archived part; when every body is the archived one the result is
    ``unchanged`` and the caller reuses the stored parse.
    """
    previous: dict[str, Part] = {}
    if state is not None:
        try:
            previous = {part.url: part for part in read_bundle(state.read_html()).parts}
        except (LiveCollectionError, OSError):
            previous = {}
    fetcher = _Fetcher(session, year, kind, previous)
    _, _, base = sport_base(base_url)
    first, slug = _season_page(fetcher, base, year, kind)
    _GENERATIONS[urlparse(base).netloc] = (
        GENERATION_WORDPRESS if is_wordpress(first.body) else GENERATION_NUXT
    )
    if is_wordpress(first.body):
        generation = GENERATION_WORDPRESS
        parts, notes = _fetch_wordpress(fetcher, first, base_url, year, kind)
    else:
        generation = GENERATION_NUXT
        parts, notes = _fetch_nuxt(fetcher, first, slug, base_url, year, kind)
    bundle = Bundle(kind, year, generation, tuple(parts), tuple(notes))
    text = bundle.text()
    page = PublishedPage(layer_url(base_url, year, kind), bundle.final_url, text)
    signature = bundle.signature()
    # The same content under a NEW validator is not unchanged: the statistics
    # host re-compresses a JSON body and answers a new ETag over the same
    # decoded season (the signature is blind to both, on purpose), and an
    # unchanged result is never written back, so the archive would keep the
    # old ETag and every later run would ask with it and download the whole
    # body again. A part whose ETag moved makes the bundle fresh: it is
    # parsed (to the same output) and archived with the new validator.
    unchanged = (
        state is not None
        and state.signature == signature
        and state.final_url == page.final_url
        and _validators_unchanged(bundle.parts, previous, fetcher.conditional)
    )
    return ConditionalFetch(
        page=page,
        unchanged=unchanged,
        signature=signature if want_validators or state is not None else None,
    )


#: How a bundle's notes record that the Game by Game join could not be read.
JOIN_UNAVAILABLE = "Game by Game join unavailable"
_JOIN_NOTE = re.compile(rf"^{re.escape(JOIN_UNAVAILABLE)}(?: \(([^)]*)\))?:")


def join_unavailable_note(exc: LiveCollectionError) -> str:
    """The note a schedule bundle carries when its Game by Game join failed.

    It keeps why: what HTTP said, a timeout or a refused connection
    (``failure_detail``), or ``not proven`` for a body that was served but
    could not be read as the team season, so a reader of the archived
    bundle (the probe) can report the failure rather than an empty join.
    """
    served = exc.status is not None or isinstance(
        exc.__cause__, requests.RequestException
    )
    reason = failure_detail(exc) if served else "not proven"
    return f"{JOIN_UNAVAILABLE} ({reason}): {exc}"


def join_failure(html: str) -> str | None:
    """Why a schedule bundle's Game by Game join failed, or None if it did not.

    The reason ``join_unavailable_note`` recorded (``HTTP 503``,
    ``timeout``); a bundle archived before reasons were recorded says only
    ``unavailable``.
    """
    for note in _bundle_of(html, LAYER_SCHEDULE).notes:
        match = _JOIN_NOTE.match(note)
        if match is not None:
            return match.group(1) or "unavailable"
    return None


def _validators_unchanged(
    parts: tuple[Part, ...], previous: dict[str, Part], conditional: set[str]
) -> bool:
    """Whether every conditionally asked part carries its archived ETag.

    Only those ETags are ever sent back (``_Fetcher.get``), so only they can
    go stale; a part with no archived counterpart is new content, which the
    signature already tells.
    """
    return all(
        previous[part.url].etag == part.etag
        for part in parts
        if part.url in conditional and part.url in previous
    )


def _bundle_of(html: str, kind: str, year: int | None = None) -> Bundle:
    bundle = read_bundle(html)
    if bundle.layer != kind:
        raise LiveCollectionError(f"a {bundle.layer} bundle is not the {kind} layer")
    if year is not None and bundle.season != year:
        raise LiveCollectionError(f"a {bundle.season} bundle is not the {year} season")
    if not bundle.parts:
        raise LiveCollectionError(f"the {kind} bundle carries no served body")
    return bundle


def assert_served_season(page: PublishedPage, year: int, kind: str) -> None:
    """The recipe's season proof over a bundle: every part proves again."""
    bundle = _bundle_of(page.html, kind, year)
    first = bundle.parts[0]
    _, sport, _ = sport_base(_base_of(first.final_url))
    if bundle.generation == GENERATION_WORDPRESS:
        prove_wordpress_page(
            first.body, year=year, kind=kind, sport=sport, url=first.final_url
        )
        return
    slug = _slug_of(first.final_url)
    prove_nuxt_page(
        first.body, year=year, kind=kind, sport=sport, slug=slug, url=first.final_url
    )


_SEASON_PAGE = re.compile(
    r"^(?P<base>.*?/sports/[^/]+)/[a-z]+/season/(?P<slug>[^/]+)/?$"
)


def _base_of(url: str) -> str:
    parsed = urlparse(url)
    match = _SEASON_PAGE.match(parsed.path)
    return f"{parsed.scheme}://{parsed.netloc}{match.group('base') if match else parsed.path}"


def _slug_of(url: str) -> str:
    match = _SEASON_PAGE.match(urlparse(url).path)
    return match.group("slug") if match else ""


def assert_schedule_proven(
    html: str,
    *,
    year: int,
    page_url: str,
    fixtures: list[dict[str, object]],
    owner_slug: str,
) -> None:
    """Every proof ran on the served bodies before the bundle was built, so
    a proven schedule whose event list is empty is a season with no
    fixtures, honestly ``empty``; only a bundle with no event list at all is
    refused."""
    del fixtures, owner_slug
    bundle = _bundle_of(html, LAYER_SCHEDULE, year)
    if bundle.generation == GENERATION_WORDPRESS:
        wordpress_rows(bundle.parts[0].body, year=year, url=page_url)
        return
    if bundle.first("events") is None:
        raise LiveCollectionError(f"[{year}] {page_url} bundle carries no event list")


# --- Schedule -----------------------------------------------------------------

_STATUSES = {
    "completed": "final",
    "as_scheduled": "scheduled",
    "scheduled": "scheduled",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "postponed": "postponed",
    "in_progress": "live",
    "live": "live",
}
_RESULT_LETTERS = {"win": "W", "loss": "L", "tie": "T"}


def _score(value: object) -> int | None:
    """ "4.0000" is 4; anything else is no score."""
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() and number >= 0 else None


def _owner_scores(result: dict[str, Any], fixture_id: str) -> tuple[int, int] | None:
    """The owner's score and the opponent's, from the event's typed result.

    ``result`` is the owner's (win, loss, tie) and the two numbers are the
    winner's and the loser's (measured: "On a loss the owner has
    ``losing_score``").  A tie with unequal numbers cannot be oriented and
    is refused, never guessed; ``no_result`` carries no score.
    """
    letter = _RESULT_LETTERS.get(str(result.get("result") or ""))
    winning = _score(result.get("winning_score"))
    losing = _score(result.get("losing_score"))
    if letter is None or winning is None or losing is None:
        return None
    if letter == "W" and winning >= losing:
        return winning, losing
    if letter == "L" and winning >= losing:
        return losing, winning
    if letter == "T" and winning == losing:
        return winning, losing
    _LOG.warning(
        "%s: result %r beside %s-%s cannot be oriented; scores refused",
        fixture_id,
        result.get("result"),
        winning,
        losing,
    )
    return None


def _schedule_events(bundle: Bundle) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for part in bundle.all("events"):
        body = part.json()
        data = body.get("data") if isinstance(body, dict) else None
        events.extend(event for event in data or [] if isinstance(event, dict))
    return events


def _programmes(
    aliases: dict[str, str], scope: ResolutionScope | None
) -> frozenset[str]:
    """Every programme slug the collect's identity can resolve text to."""
    known = set(aliases.values())
    if scope is not None:
        known.update(scope.claims.values())
        known.update(scope.member_only.values())
    return frozenset(known)


def _record_school_name(
    event: dict[str, Any],
    printed: str,
    *,
    date: str,
    owner_slug: str,
    aliases: dict[str, str],
    scope: ResolutionScope | None,
    programmes: frozenset[str],
) -> str:
    """The opponent's school, when the printed name is its opponent record's
    nickname; otherwise the printed name.

    Each event carries the site's opponent record: ``name`` (what
    ``opponent_name`` prints by default) and ``long_name``, which the event
    repeats as ``opponent_school_name`` on the sites that fill it.  Most
    sites use ``long_name`` for the formal name ("University of Portland"),
    one site keeps the nickname there ("Indiana" / "Hoosiers"), and on that
    site and one other the two are swapped on most rows: ``name`` "Tar
    Heels", ``long_name`` "North Carolina" (measured: fightingirish.com
    2023-2025, 55 events; clemsontigers.com 2023, 2).  The record publishes
    no field saying which of its two names is the school, so the
    collection's own identity decides: the printed name is replaced only
    when

    - it is the record's own ``name`` (an event that overrides the name,
      "GCU" over a record "Grand Canyon", printed what it meant to),
    - it names no programme at the collecting level, and
    - exactly one programme is named by the record's other names (a round
      placeholder never is).

    A printed name that resolves is never rewritten, so a school whose
    published name looks like a nickname keeps it.  When neither name
    resolves ("Yeomen" / "Oberlin", a school outside the level), nothing
    says which is the school: the printed name stands and the run log names
    the row.
    """
    record = event.get("opponent")
    if not isinstance(record, dict):
        return printed
    key = _identity_key(printed)
    if not key or _identity_key(str(record.get("name") or "")) != key:
        return printed
    others: list[str] = []
    for value in (record.get("long_name"), event.get("opponent_school_name")):
        name = _clean_team_name(str(value or "").strip())
        if name and _identity_key(name) not in ("", key) and name not in others:
            others.append(name)
    if not others:
        return printed

    def resolves(name: str) -> str | None:
        slug = opponent_slug(name, aliases, scope=scope, owner=owner_slug)
        return slug if slug in programmes else None

    if resolves(printed):
        return printed
    named = {
        name: slug
        for name in others
        if not round_placeholder(name) and (slug := resolves(name))
    }
    if len(set(named.values())) == 1:
        chosen = next(iter(named))
        if scope is not None:
            scope.note_page(
                owner_slug,
                printed,
                f"resolution: {printed!r} on {owner_slug}'s page names no "
                f"programme; read as {chosen!r} ({named[chosen]}), the other "
                "name its opponent record publishes",
            )
        return chosen
    if scope is not None:
        also = ", ".join(repr(name) for name in others)
        scope.note_page(
            owner_slug,
            printed,
            f"resolution: {printed!r} on {owner_slug}'s page ({date}) kept as "
            f"printed; its opponent record also names {also}, and "
            + (
                "those name different programmes"
                if named
                else "neither names a programme at this level"
            ),
        )
    return printed


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
    gender: str = "men",
) -> list[dict[str, object]]:
    """Read a WMT schedule bundle into fixture rows.

    Same row shape as the SideArm parser, under ``wmt:{owner}:{event id}``
    identifiers.  Field by field, from the schedule-events API (measured on
    goseattleu.com 2025 and twelve more sites' 2025 schedules):

    - ``date`` and ``time``: the event's UTC ``datetime`` in the site's
      ``website_timezone`` (trap 6.1: the UTC date is wrong for 13 of
      Seattle U's 17 matches).  A ``tba`` or all-day event keeps its date
      and prints no time.
    - ``home``/``away``: ``venue_type`` (``home``, ``away``); ``neutral``
      is ``venue_type == "neutral"`` (``neutral_event`` was false on all 363
      events measured, neutral sites included), with the sides as the
      event's own preposition puts them ("at" puts the owner away).
    - opponent: ``opponent_name`` ("Missouri State"; an annotation such as
      "(Exhibition)" is dropped by the identity fold), resolved through
      ``opponent_slug``; when it is its opponent record's nickname, the
      record's school name (``_record_school_name``).  A round placeholder
      is a named skip; a row naming
      a second opponent with neither side the owner is a hosted other-match
      and a named skip.
    - ``status``: ``completed`` is final, ``as_scheduled`` scheduled,
      ``cancelled`` and ``postponed`` themselves.
    - scores: the typed result, oriented from the owner (``_owner_scores``).
      A completed event with ``no_result`` is a final with no score: the
      site published completion and no score, and no score is invented.
    - ``conference_game`` and ``match_type``: the published ``is_conference``
      and ``is_exhibition`` flags, carried as published, never derived.
    - ``venue``: the facility when the row names one, else its location.
    - ``result_published``: a level score's result text when it names a
      shootout ("GCU advances 3-1 on penalties").

    ``gender`` and ``members`` select nothing: the schedule proved its sport
    and every conference flag is published.
    """
    del members, gender
    bundle = _bundle_of(html, LAYER_SCHEDULE, year)
    if bundle.generation == GENERATION_WORDPRESS:
        return _parse_wordpress_schedule(
            bundle,
            page_url=page_url,
            year=year,
            owner_slug=owner_slug,
            aliases=aliases,
            skips=skips,
            scope=scope,
        )
    first = bundle.parts[0]
    timezone = site_timezone(_nuxt_state(first.body))
    if not timezone:
        raise LiveCollectionError(f"[{year}] {page_url} names no website timezone")
    programmes = _programmes(aliases, scope)
    fixtures: list[dict[str, object]] = []
    for event in _schedule_events(bundle):
        event_id = str(event.get("id") or "")
        local = local_kickoff(event.get("datetime"), timezone)
        if not event_id or local is None:
            continue
        date = local.date().isoformat()
        opponent_raw = str(
            event.get("opponent_name")
            or (event.get("opponent") or {}).get("name")
            or ""
        ).strip()
        opponent_name = _clean_team_name(opponent_raw)
        if not opponent_name:
            continue
        if round_placeholder(opponent_name):
            if skips is not None:
                skips.append(placeholder_skip(date, opponent_name))
            continue
        second = str(event.get("second_opponent_name") or "").strip()
        if second:
            pair = (opponent_name, _clean_team_name(second))
            slugs = [
                opponent_slug(name, aliases, scope=scope, owner=owner_slug)
                for name in pair
            ]
            if owner_slug not in slugs:
                if skips is not None:
                    skips.append(hosted_skip(date, pair))
                continue
            opponent_name = pair[1] if slugs[0] == owner_slug else pair[0]
            opponent_raw = opponent_name
        else:
            opponent_name = _record_school_name(
                event,
                opponent_name,
                date=date,
                owner_slug=owner_slug,
                aliases=aliases,
                scope=scope,
                programmes=programmes,
            )
        other = opponent_slug(
            opponent_name,
            aliases,
            scope=scope,
            owner=owner_slug,
            seeded=_seeded(opponent_raw),
        )
        venue_type = str(event.get("venue_type") or "")
        neutral = venue_type == "neutral"
        if neutral:
            owner_is_home = (
                str(event.get("neutral_event_preposition") or "vs").lower() != "at"
            )
        else:
            owner_is_home = venue_type != "away"
        home, away = (owner_slug, other) if owner_is_home else (other, owner_slug)
        fixture_id = f"wmt:{owner_slug}:{event_id}"
        fixture: dict[str, object] = {
            "id": fixture_id,
            "date": date,
            "home": home,
            "away": away,
            "status": _STATUSES.get(str(event.get("status") or ""), "scheduled"),
            "source_url": page_url,
        }
        if neutral:
            fixture["neutral"] = True
        if event.get("is_exhibition") is True:
            fixture["match_type"] = "exhibition"
        fixture["conference_game"] = event.get("is_conference") is True
        if not event.get("tba") and not event.get("is_all_day"):
            fixture["time"] = local.strftime("%H:%M")
        venue = (
            str(event.get("venue") or "").strip()
            or str(event.get("location") or "").strip()
        )
        if venue:
            fixture["venue"] = venue
        result = event.get("schedule_event_result")
        if fixture["status"] == "final" and isinstance(result, dict):
            scores = _owner_scores(result, fixture_id)
            if scores is not None:
                owner_score, other_score = scores
                if owner_is_home:
                    fixture["home_score"], fixture["away_score"] = (
                        owner_score,
                        other_score,
                    )
                else:
                    fixture["home_score"], fixture["away_score"] = (
                        other_score,
                        owner_score,
                    )
                text = str(result.get("text") or "").strip()
                if (
                    owner_score == other_score
                    and text
                    and _SHOOTOUT_MARKER.search(text)
                ):
                    fixture["result_published"] = text
        fixtures.append(fixture)
    return sorted(fixtures, key=lambda value: (str(value["date"]), str(value["id"])))


def boxscore_links(html: str, page_url: str) -> dict[str, str]:
    """Event id → the ``wmt.games`` game the event's box score is.

    The event's own ``wmt_stats2_game_id`` first.  A played event without
    one is joined to the team season's Game by Game table (in the bundle
    when the schedule needed it) by its local date: exactly one game that
    day, not already claimed by another event, or no link (trap 6.6).
    """
    del page_url
    bundle = _bundle_of(html, LAYER_SCHEDULE)
    if bundle.generation == GENERATION_WORDPRESS:
        return _wordpress_links(bundle)
    first = bundle.parts[0]
    origin = stats_origin(first.body)
    if origin is None:
        return {}
    timezone = site_timezone(_nuxt_state(first.body))
    events = _schedule_events(bundle)
    links: dict[str, str] = {}
    claimed: set[int] = set()
    for event in events:
        game_id = _stat_int(str(event.get("wmt_stats2_game_id") or ""))
        if event.get("id") and game_id is not None:
            links[str(event["id"])] = game_url(origin, game_id)
            claimed.add(game_id)
    season_part = bundle.first("season")
    if season_part is None or not timezone:
        return links
    by_date: dict[str, list[int]] = {}
    for date, game_id, _title in game_by_game(season_part.json()):
        if game_id not in claimed:
            by_date.setdefault(date, []).append(game_id)
    for event in events:
        if str(event.get("id")) in links or not _unlinked_result(event):
            continue
        local = local_kickoff(event.get("datetime"), timezone)
        candidates = by_date.get(local.date().isoformat(), []) if local else []
        if len(candidates) == 1:
            links[str(event["id"])] = game_url(origin, candidates[0])
            claimed.add(candidates[0])
            by_date[local.date().isoformat()] = []  # type: ignore[union-attr]
    return links


# --- Roster -----------------------------------------------------------------


def _name_of(value: Any) -> str:
    return str(value.get("name") or "").strip() if isinstance(value, dict) else ""


def parse_roster(html: str, *, page_url: str) -> list[dict[str, str]]:
    """Read a WMT roster bundle into player rows.

    The Nuxt roster page renders from ``roster-{id}-players-list`` in its
    ``__NUXT_DATA__`` payload (no API serves it: the measured
    ``/website-api/roster-players`` and ``/rosters/{id}/players`` answer
    404).  Same row shape as the SideArm parser: ``full_name``, the jersey
    label, the roster entry's position (else the player's), its class level,
    ``height_feet``/``height_inches`` as 6'1", ``weight`` as "165 lbs",
    ``hometown``, and the entry's ``permalink`` as ``source_url``.  Position
    and class are put in the SideArm vocabulary the PrestoSports recipe
    uses ("D" is Defender, "Fr." Freshman); a value outside it is kept as
    published.  An absent field is omitted, never filled.
    """
    bundle = read_bundle(html)
    first = bundle.parts[0] if bundle.parts else None
    if first is None:
        return []
    if bundle.generation == GENERATION_WORDPRESS:
        return parse_wordpress_roster(first.body, page_url=first.final_url or page_url)
    data = _nuxt_data(_nuxt_state(first.body))
    players: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, value in data.items():
        if not (key.startswith("roster-") and key.endswith("-players-list")):
            continue
        for entry in value if isinstance(value, list) else []:
            if not isinstance(entry, dict):
                continue
            person = (
                entry.get("player") if isinstance(entry.get("player"), dict) else {}
            )
            name = str(
                person.get("full_name")
                or f"{person.get('first_name') or ''} {person.get('last_name') or ''}"
            ).strip()
            if not name:
                continue
            identity = str(entry.get("player_id") or person.get("id") or name)
            if identity in seen:
                continue
            seen.add(identity)
            player: dict[str, str] = {"name": " ".join(name.split())}
            number = str(
                entry.get("jersey_number_label")
                or person.get("jersey_number_label")
                or ""
            ).strip()
            if number:
                player["number"] = number
            position = _name_of(entry.get("player_position")) or _name_of(
                person.get("player_position")
            )
            if position:
                player["position"] = _roster_position(position)
            feet, inches = person.get("height_feet"), person.get("height_inches")
            if isinstance(feet, int) and isinstance(inches, int):
                player["height"] = f"{feet}'{inches}\""
            weight = person.get("weight")
            if isinstance(weight, int) and weight > 0:
                player["weight"] = f"{weight} lbs"
            hometown = str(person.get("hometown") or "").strip()
            if hometown:
                player["hometown"] = hometown
            class_year = _name_of(entry.get("class_level")) or _name_of(
                person.get("class_level")
            )
            if class_year:
                player["class_year"] = _roster_class_year(class_year)
            permalink = str(entry.get("permalink") or "").strip()
            if permalink:
                player["source_url"] = permalink
            players.append(player)
    return players


# --- Season statistics ---------------------------------------------------------

_PLAYER_FIELDS: dict[str, tuple[str, Any]] = {
    "sMinutes": ("minutes", _stat_minutes),
    "sGoals": ("goals", _stat_int),
    "sAssists": ("assists", _stat_int),
    "sPoints": ("points", _stat_int),
    "sShotAttempts": ("shots", _stat_int),
    "cShotPct": ("shot_pct", _stat_float),
    "sShotsOnGoal": ("sog", _stat_int),
    "cShotsOnGoalPct": ("sog_pct", _stat_float),
    "sGameWinningGoals": ("game_winners", _stat_int),
}
_KEEPER_FIELDS: dict[str, tuple[str, Any]] = {
    "sMinutes": ("minutes", _stat_minutes),
    "sGoalsAllowed": ("goals_against", _stat_int),
    "sGoalsAgainstAverage": ("gaa", _stat_float),
    "sSaves": ("saves", _stat_int),
    "sSavePercentage": ("save_pct", _stat_float),
    "sGoalieWins": ("wins", _stat_int),
    "sGoalieLoss": ("losses", _stat_int),
    "sGoalieTie": ("ties", _stat_int),
    "sShutouts": ("shutouts", _stat_int),
}


def parse_stats(
    html: str, *, page_url: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Read the proven team season into (players, keepers) season lines.

    Same line shapes as the SideArm parser.  The Individual tab's Offensive
    and Goalkeeping tables (``wmt.games`` team season, measured on Seattle
    U's 604058) are read by each cell's ``key``, never by position: "GP -
    GS" is ``gp``/``gs``, "YC - RC" ``yellow``/``red``, a percentage
    ("0.300") stays the fraction it is printed as.  TEAM, Totals and
    Opponents sit in each table's footer and are never read as people.  A
    line counts when it has a games-played number.  The table carries a
    ``personId`` that is not the site roster's player id, so no line carries
    a ``player_id``; consumers join by name, as for PrestoSports.
    """
    del page_url
    bundle = _bundle_of(html, LAYER_STATS)
    season_part = bundle.first("season")
    if season_part is None:
        raise LiveCollectionError("the statistics bundle carries no proven team season")
    players: list[dict[str, object]] = []
    keepers: list[dict[str, object]] = []
    for path, table in _walk_tables(season_part.json().get("tabs")):
        if len(path) < 2 or path[0] != "Individual":
            continue
        keeping = path[1] == "Goalkeeping"
        if not keeping and path[1] != "Offensive":
            continue
        fields = _KEEPER_FIELDS if keeping else _PLAYER_FIELDS
        for row in table.get("body") or []:
            cells = _cells(row)
            name = _text(cells.get("name"))
            played = _stat_pair(_text(cells.get("cGamesAndStarted")))
            if not name or played is None:
                continue
            entry: dict[str, object] = {"name": name}
            number = _text(cells.get("jersey"))
            if number:
                entry["number"] = number
            entry["gp"], entry["gs"] = played
            for key, (field, convert) in fields.items():
                value = convert(_text(cells.get(key)))
                if value is not None:
                    entry[field] = value
            if not keeping:
                cards = _stat_pair(_text(cells.get("cCards")))
                if cards:
                    entry["yellow"], entry["red"] = cards
            (keepers if keeping else players).append(entry)
    return players, keepers


def is_wmt(html: str) -> list[str]:
    """The evidence that a page is a WMT Digital site, or nothing.

    Measured on the landing and schedule pages of all three Nuxt and both
    WordPress sites captured: the Nuxt generation renders a
    ``__NUXT_DATA__`` payload carrying WMT's ``oas-config`` settings store
    (and links its ``wmt.games`` statistics); the WordPress generation loads
    the ``wmt-stats-wordpress-plugin`` and declares ``var wmtGames``.
    """
    evidence: list[str] = []
    if "__NUXT_DATA__" in html and "oas-config" in html:
        evidence.append("Nuxt __NUXT_DATA__ payload with the WMT oas-config store")
    if "wmt-stats-wordpress-plugin" in html:
        evidence.append("wmt-stats-wordpress-plugin assets")
    if re.search(r"\bvar\s+wmtGames\s*=", html):
        evidence.append("inline wmtGames statistics configuration")
    if evidence and stats_origin(html):
        evidence.append("WMT statistics host named")
    return evidence


def fetch_season_page(
    session: requests.Session, base_url: str, year: int, kind: str = LAYER_SCHEDULE
) -> PublishedPage:
    """One layer's season page, located and proven, with nothing else
    fetched: what the probe asks of a candidate season."""
    fetcher = _Fetcher(session, year, kind)
    _, sport, base = sport_base(base_url)
    page, slug = _season_page(fetcher, base, year, kind)
    wordpress = is_wordpress(page.body)
    _GENERATIONS[urlparse(base).netloc] = (
        GENERATION_WORDPRESS if wordpress else GENERATION_NUXT
    )
    if wordpress:
        prove_wordpress_page(
            page.body, year=year, kind=kind, sport=sport, url=page.final_url
        )
    else:
        prove_nuxt_page(
            page.body, year=year, kind=kind, sport=sport, slug=slug, url=page.final_url
        )
    return PublishedPage(page.url, page.final_url, page.body)


# --- The WordPress generation ------------------------------------------------
#
# South Carolina and Kentucky (FINDINGS.md section 4): the schedule and
# roster are server-rendered, the season is the plain year, and any season
# path answers HTTP 200 with the *current* season, so the path is never a
# witness.  The page's ``route_vars`` and ``<title>`` are.  Statistics are
# the ``wmt.games`` team season the ``cumestats`` page's iframe names, and
# box scores are joined to the schedule through that season's Game by Game
# table, by date: Kentucky's rows link only PDFs.

_ROUTE_VARS = re.compile(r"\bvar\s+route_vars\s*=\s*")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_WP_LAYER_TITLE = {
    LAYER_SCHEDULE: "Schedule",
    LAYER_ROSTER: "Roster",
    LAYER_STATS: "Cumulative Statistics",
}
_WP_ROWS = ("div.event.schedule-table_row", "div.schedule__item.schedule-item")
_WP_RESULT_NODE = ".schedule-list__result, .schedule-item__result"
_WP_RESULT = re.compile(r"^\s*([WLT])\s*,?\s*(\d+)\s*-\s*(\d+)\s*(.*)$", re.I)
_WP_PREPOSITION = re.compile(r"^\s*(?:at|vs\.?|versus)\s+", re.I)
_EXHIBITION = re.compile(r"\((?:exh|exhibition)\.?\)", re.I)
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}\s*[ap]\.?\s*m\b", re.I)
_LOCAL_START = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?")
_STATS_IFRAME = re.compile(
    r"<wmt-stats-iframe[^>]*\bpath=\"/[^/\"]+/stats/season/(\d+)\"", re.I
)


def wp_route_vars(html: str) -> dict[str, Any] | None:
    """The inline ``var route_vars = {...}`` a WordPress page declares."""
    match = _ROUTE_VARS.search(html)
    if match is None:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def is_wordpress(html: str) -> bool:
    return wp_route_vars(html) is not None and "__NUXT_DATA__" not in html


def _page_title(html: str) -> str:
    match = _TITLE.search(html)
    if match is None:
        return ""
    return " ".join(unescape(match.group(1)).replace("’", "'").split())


def prove_wordpress_page(
    html: str, *, year: int, kind: str, sport: str, url: str
) -> None:
    """Refuse a WordPress season page that is not men's soccer's ``year``.

    Two witnesses, both required, because the path proves nothing
    (``/schedule/season/2031/`` answers 200 with the 2026 season, measured
    on both sites): ``route_vars`` must name the stanza's sport category
    (slug and a men's soccer name) and the requested season as its
    ``current_season``, and the ``<title>`` must lead with "Men's Soccer
    {Schedule|Roster|Cumulative Statistics} {year}".
    """
    route = wp_route_vars(html)
    if route is None:
        raise LiveCollectionError(
            f"[{year}] {url} declares no route_vars: not a WMT WordPress season page"
        )
    category = (
        route.get("sport_category")
        if isinstance(route.get("sport_category"), dict)
        else {}
    )
    if category.get("slug") != sport or not _is_mens_soccer(category.get("name")):
        raise LiveCollectionError(
            f"[{year}] {url} renders sport category {category.get('slug')!r} "
            f"({category.get('name')!r}), not men's soccer at /sports/{sport}"
        )
    season = (
        route.get("current_season")
        if isinstance(route.get("current_season"), dict)
        else {}
    )
    served = str(season.get("slug") or "")
    if served != str(year):
        raise LiveCollectionError(
            f"[{year}] requested the {year} {kind} season but {url} served the "
            f"{served or 'unnamed'} season (route_vars current_season)"
        )
    title = _page_title(html)
    expected = f"Men's Soccer {_WP_LAYER_TITLE[kind]} {year}"
    if not re.match(rf"{re.escape(expected)}(?!\d)", title, re.I):
        raise LiveCollectionError(
            f"[{year}] {url} is titled {title!r}, not {expected!r}"
        )


@dataclass(frozen=True)
class WordPressRow:
    """One server-rendered schedule row with its JSON-LD event."""

    event_id: str
    date: str
    time: str | None
    side: str
    opponent: str
    exhibition: bool
    venue: str
    result: str


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def wordpress_rows(html: str, *, year: int, url: str) -> list[WordPressRow]:
    """Every schedule row, paired in order with its JSON-LD ``Event``.

    Both skins (South Carolina's ``schedule-table_row``, Kentucky's
    ``schedule-item``) add one ``Event`` per row whose ``startDate`` is the
    local wall-clock kickoff with its year ("2025-08-21T19:30") and whose
    ``name`` is the row as printed ("at Charleston", "vs. Lipscomb (EXH)").
    A row count that differs from the event count, or a date outside the
    season's two calendar years, refuses the page: the pairing could not be
    trusted.  Rows carry no ids, so each is named by its date and the
    opponent as printed (``20250821-charleston``).
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Any] = []
    for selector in _WP_ROWS:
        rows = soup.select(selector)
        if rows:
            break
    events: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            value = json.loads(script.string or "")
        except ValueError:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and item.get("@type") == "Event":
                events.append(item)
    if len(rows) != len(events):
        raise LiveCollectionError(
            f"[{year}] {url} renders {len(rows)} schedule rows beside {len(events)} "
            f"JSON-LD events; the rows cannot be dated"
        )
    out: list[WordPressRow] = []
    seen: Counter[str] = Counter()
    for row, event in zip(rows, events, strict=True):
        start = _LOCAL_START.match(str(event.get("startDate") or ""))
        if start is None:
            raise LiveCollectionError(
                f"[{year}] {url}: a schedule event carries no start date "
                f"({event.get('name')!r})"
            )
        date = start.group(1)
        if int(date[:4]) not in (year, year + 1):
            raise LiveCollectionError(
                f"[{year}] {url}: a schedule row is dated {date}, outside the {year} season"
            )
        name = " ".join(str(event.get("name") or "").split())
        opponent = re.sub(r"\s*\([^)]*\)", "", _WP_PREPOSITION.sub("", name)).strip()
        classes = set(row.get("class") or [])
        side = next(
            (value for value in ("home", "away", "neutral") if value in classes), ""
        )
        node = row.select_one(_WP_RESULT_NODE)
        result = " ".join(node.get_text(" ").split()) if node else ""
        printed = " ".join(row.get_text(" ").split())
        location = (
            event.get("location") if isinstance(event.get("location"), dict) else {}
        )
        base_id = f"{date.replace('-', '')}-{_fold(opponent)}"
        seen[base_id] += 1
        out.append(
            WordPressRow(
                event_id=base_id
                if seen[base_id] == 1
                else f"{base_id}-{seen[base_id]}",
                date=date,
                time=start.group(2)
                if start.group(2) and _CLOCK.search(printed)
                else None,
                side=side,
                opponent=opponent,
                exhibition=bool(_EXHIBITION.search(name)),
                venue=str(location.get("name") or "").strip(),
                result=result,
            )
        )
    return out


def _wordpress_result(row: WordPressRow, fixture_id: str) -> tuple[int, int] | None:
    """The owner's score and the opponent's, from a hand-typed result.

    The digits are typed in no fixed order ("L 0-1" owner first, "L 2-1
    2OT" winner first, FINDINGS.md section 4), so the letter orients them:
    a win gives the owner the larger number, a loss the smaller.  A tie
    with unequal numbers is refused, never guessed.
    """
    match = _WP_RESULT.match(row.result)
    if match is None:
        return None
    letter, first, second = (
        match.group(1).upper(),
        int(match.group(2)),
        int(match.group(3)),
    )
    high, low = max(first, second), min(first, second)
    if letter == "W" and high != low:
        return high, low
    if letter == "L" and high != low:
        return low, high
    if letter == "T" and first == second:
        return first, second
    _LOG.warning(
        "%s: result %r cannot be oriented; scores refused", fixture_id, row.result
    )
    return None


def _wordpress_status(row: WordPressRow) -> str:
    if _WP_RESULT.match(row.result):
        return "final"
    text = row.result.lower()
    if "cancel" in text:
        return "cancelled"
    if "postpon" in text:
        return "postponed"
    return "scheduled"


def _parse_wordpress_schedule(
    bundle: Bundle,
    *,
    page_url: str,
    year: int,
    owner_slug: str,
    aliases: dict[str, str],
    skips: list[str] | None,
    scope: ResolutionScope | None,
) -> list[dict[str, object]]:
    """Fixture rows from a WordPress schedule, same shape as the Nuxt ones.

    ``neutral`` is the row's ``neutral`` class; ``match_type`` exhibition
    is the row's own "(EXH)" marking.  The rows publish no conference flag
    a parser can read (South Carolina prints "(Sun Belt)" beside some
    opponents, Kentucky nothing), so ``conference_game`` is absent rather
    than derived.  A row with no typed result is not final (the sites print
    "N/A" or the kickoff time), and carries no score.
    """
    fixtures: list[dict[str, object]] = []
    for row in wordpress_rows(bundle.parts[0].body, year=year, url=page_url):
        opponent_name = _clean_team_name(row.opponent)
        if not opponent_name:
            continue
        if round_placeholder(opponent_name):
            if skips is not None:
                skips.append(placeholder_skip(row.date, opponent_name))
            continue
        other = opponent_slug(
            opponent_name,
            aliases,
            scope=scope,
            owner=owner_slug,
            seeded=_seeded(row.opponent),
        )
        owner_is_home = row.side != "away"
        home, away = (owner_slug, other) if owner_is_home else (other, owner_slug)
        fixture_id = f"wmt:{owner_slug}:{row.event_id}"
        fixture: dict[str, object] = {
            "id": fixture_id,
            "date": row.date,
            "home": home,
            "away": away,
            "status": _wordpress_status(row),
            "source_url": page_url,
        }
        if row.side == "neutral":
            fixture["neutral"] = True
        if row.exhibition:
            fixture["match_type"] = "exhibition"
        if row.time:
            fixture["time"] = row.time
        if row.venue:
            fixture["venue"] = row.venue
        scores = (
            _wordpress_result(row, fixture_id) if fixture["status"] == "final" else None
        )
        if scores is not None:
            owner_score, other_score = scores
            if owner_is_home:
                fixture["home_score"], fixture["away_score"] = owner_score, other_score
            else:
                fixture["home_score"], fixture["away_score"] = other_score, owner_score
            if owner_score == other_score and _SHOOTOUT_MARKER.search(row.result):
                fixture["result_published"] = row.result
        fixtures.append(fixture)
    return sorted(fixtures, key=lambda value: (str(value["date"]), str(value["id"])))


def _wordpress_links(bundle: Bundle) -> dict[str, str]:
    """Row id → its ``wmt.games`` game, by the Game by Game table's date:
    exactly one unclaimed game that day for a row with a typed result."""
    season_part = bundle.first("season")
    cume = bundle.first("cumestats")
    origin = stats_origin(cume.body) if cume is not None else None
    if season_part is None or origin is None:
        return {}
    by_date: dict[str, list[int]] = {}
    for date, game_id, _title in game_by_game(season_part.json()):
        by_date.setdefault(date, []).append(game_id)
    links: dict[str, str] = {}
    rows = wordpress_rows(
        bundle.parts[0].body, year=bundle.season, url=bundle.final_url
    )
    for row in rows:
        if not _WP_RESULT.match(row.result):
            continue
        candidates = by_date.get(row.date, [])
        if len(candidates) == 1:
            links[row.event_id] = game_url(origin, candidates[0])
            by_date[row.date] = []
    return links


def _wordpress_team_season(
    fetcher: _Fetcher, cume: Part, year: int
) -> tuple[Part, int]:
    """The team season the ``cumestats`` page's iframe names, proven."""
    match = _STATS_IFRAME.search(cume.body)
    origin = stats_origin(cume.body)
    if match is None or origin is None:
        raise LiveCollectionError(
            f"[{year}] {cume.final_url} names no statistics team "
            f"(no wmt-stats-iframe season path, or no statistics host)"
        )
    team_id = int(match.group(1))
    url = team_season_url(origin, team_id)
    season_part = fetcher.require("season", url, expect="json", conditional=True)
    prove_team_season(season_part.json(), team_id=team_id, year=year, url=url)
    return season_part, team_id


def _fetch_wordpress(
    fetcher: _Fetcher, page: Part, base_url: str, year: int, kind: str
) -> tuple[list[Part], list[str]]:
    _, sport, base = sport_base(base_url)
    notes: list[str] = []
    cume_url = f"{base}/cumestats/season/{year}/"
    if kind == LAYER_STATS and "/cumestats/" not in urlparse(page.final_url).path:
        page = fetcher.require("page", cume_url)
    prove_wordpress_page(
        page.body, year=year, kind=kind, sport=sport, url=page.final_url
    )
    parts = [page]
    if kind == LAYER_SCHEDULE:
        rows = wordpress_rows(page.body, year=year, url=page.final_url)
        if any(_WP_RESULT.match(row.result) for row in rows):
            try:
                cume = fetcher.require("cumestats", cume_url)
                prove_wordpress_page(
                    cume.body,
                    year=year,
                    kind=LAYER_STATS,
                    sport=sport,
                    url=cume.final_url,
                )
                season_part, team_id = _wordpress_team_season(fetcher, cume, year)
                parts.extend([cume, season_part])
                notes.append(f"box scores joined by date to statistics team {team_id}")
            except LiveCollectionError as exc:
                _LOG.warning(
                    "%s: the Game by Game join is unavailable: %s", page.final_url, exc
                )
                notes.append(join_unavailable_note(exc))
    elif kind == LAYER_ROSTER:
        if _wordpress_roster_table(page.body) is None:
            raise LiveCollectionError(
                f"[{year}] {page.final_url} proved its season but renders no roster table"
            )
    else:
        season_part, _ = _wordpress_team_season(fetcher, page, year)
        parts.append(season_part)
    return parts, notes


def _wordpress_roster_table(html: str) -> tuple[list[str], list[Any]] | None:
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        headers = [
            " ".join(th.get_text(" ").split()).lower()
            for th in table.select("thead th")
        ]
        if "name" in headers and "number" in headers:
            return headers, table.select("tbody tr")
    return None


_WP_HEIGHT = re.compile(r"^(\d)\s*-\s*(\d{1,2})$")
_WP_WEIGHT = re.compile(r"^(\d{2,3})\s*(?:lbs?\.?)?$", re.I)


def parse_wordpress_roster(html: str, *, page_url: str) -> list[dict[str, str]]:
    """Player rows from the server-rendered roster table (the first table
    with Number and Name columns; the second holds staff), read by header:
    "6-3" is 6'3", "185 lbs." 185 lbs; absent cells are omitted."""
    found = _wordpress_roster_table(html)
    if found is None:
        return []
    headers, rows = found
    players: list[dict[str, str]] = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        by = {header: cell for header, cell in zip(headers, cells, strict=False)}
        name_cell = by.get("name")
        name = " ".join(name_cell.get_text(" ").split()) if name_cell else ""
        if not name:
            continue
        text = {key: " ".join(cell.get_text(" ").split()) for key, cell in by.items()}
        player: dict[str, str] = {"name": name}
        if text.get("number"):
            player["number"] = text["number"]
        if text.get("position"):
            player["position"] = _roster_position(text["position"])
        height = _WP_HEIGHT.match(text.get("height", ""))
        if height:
            player["height"] = f"{height.group(1)}'{height.group(2)}\""
        weight = _WP_WEIGHT.match(text.get("weight", ""))
        if weight:
            player["weight"] = f"{weight.group(1)} lbs"
        if text.get("hometown"):
            player["hometown"] = text["hometown"]
        if text.get("class"):
            player["class_year"] = _roster_class_year(text["class"])
        link = name_cell.find("a", href=True) if name_cell else None
        if link is not None:
            player["source_url"] = urljoin(page_url, str(link["href"]))
        players.append(player)
    return players


# --- Box scores -------------------------------------------------------------------

_GAME_PATH = re.compile(r"/proxy-api/games/(\d+)")
_TEAM_STATS = {
    "shots": "shots",
    "saves": "saves",
    "corner kicks": "corners",
    "fouls": "fouls",
}
_SHOTS_TOTAL = re.compile(r"^(\d+)\s*\((\d+)\)$")
_CARD_PLAYER = re.compile(r"^#?\s*(?P<number>\d+)?\s*\((?P<name>[^)]*)\)\s*$")
_SCORE_PREFIX = re.compile(r"^\s*(\d+)")
# Play-by-play phrasings measured on five 2025 games (6412291, 6391102,
# 6393106, 6393084, 6418312), typed into the contract's vocabulary; a line
# no pattern names (Kickoff, Save, Assist, VAR review) keeps its text and no
# type, as on SideArm.
_PLAY_TYPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("goal", re.compile(r"^Goal\b", re.I)),
    ("penalty", re.compile(r"^Penalty kick\b", re.I)),
    ("shot", re.compile(r"^Shot\b", re.I)),
    ("goalie", re.compile(r"^Goalkeeper change\b", re.I)),
    ("foul", re.compile(r"^(?:Handball\s+)?Foul\b", re.I)),
    ("corner", re.compile(r"^Corner kick\b", re.I)),
    ("sub", re.compile(r"^Sub (?:In|Out)\b", re.I)),
    ("offside", re.compile(r"^Offside\b", re.I)),
    ("yellow", re.compile(r"^Yellow card\b", re.I)),
    ("red", re.compile(r"^Red card\b", re.I)),
    ("shootout", re.compile(r"^Shootout\b", re.I)),
)


def _play_type(text: str) -> str | None:
    for name, pattern in _PLAY_TYPES:
        if pattern.search(text):
            return name
    return None


def _period(title: str) -> str:
    """A Play-By-Play tab title in the SideArm period vocabulary: "1" and
    "2" are the halves, an overtime is "3" and up, a shootout "SO"."""
    text = " ".join(title.split()).lower()
    if re.search(r"shoot|penalt|\bpks?\b|\bso\b", text):
        return "SO"
    if text.isdigit():
        return str(int(text))
    overtime = re.fullmatch(r"(\d*)\s*ot", text)
    if overtime:
        return str(2 + int(overtime.group(1) or 1))
    return title.strip()


def parse_game(game: dict[str, Any], *, page_url: str) -> dict[str, object]:
    """Read one ``wmt.games`` game into the SideArm match-detail shape.

    Measured on games 6412291, 6391102, 6393084, 6393106 and 6418312
    (2025) and the thin 6487961:

    - ``teams``: the header's away side then its home side (the linescore
      lists them in that order), each with its name, score and ``winner``;
      ``periods`` from the linescore row; shots, shots on goal ("5 (4)"),
      saves, corners and fouls from Team Statistics.
    - ``players``/``keepers``: the Individual tab's "{Team} - Starters" and
      "- Substitutes" tables (``started`` is which table) and "-
      Goalkeeping"; minutes "84:16" are whole minutes.  No line carries a
      ``player_id``: the tables' ``seasonPlayerId`` is not the roster's id.
    - ``scoring``: Scoring Summary rows; "Name\\nAssisted by: A, B" and a
      "(PK)" note.
    - ``cards``: Cautions and Ejections; "#4 (Dylan Wojdyla)".
    - ``plays``: one Play-By-Play child per period; a play's side is the
      column its text sits in; the running score rides goal rows.
    - ``stadium``, ``attendance``, ``kickoff`` from the header details.
      Officials are not published.

    A thin box score yields what it has: 6487961 (Kentucky 0-0 Coastal
    Carolina, decided on penalties) publishes Team Statistics and the
    Individual tables only, so it carries no ``scoring``, ``cards`` or
    ``plays``; ``thin_box_lacks`` names what is missing.
    """
    header = game.get("header") if isinstance(game.get("header"), dict) else {}
    sides = [header.get("away") or {}, header.get("home") or {}]
    teams: list[dict[str, object]] = []
    for side in sides:
        team: dict[str, object] = {"name": str(side.get("name") or "").strip()}
        score = _stat_int(
            str(side.get("score") if side.get("score") is not None else "")
        )
        if score is not None:
            team["score"] = score
        team["periods"] = []
        if side.get("winner") is True:
            team["winner"] = True
        teams.append(team)
    names = {str(team["name"]).lower(): index for index, team in enumerate(teams)}

    def side_of(reference: str) -> int | None:
        return names.get(" ".join(reference.split()).lower())

    linescore = game.get("linescore") if isinstance(game.get("linescore"), dict) else {}
    for position, row in enumerate(linescore.get("body") or []):
        cells = _cells(row)
        index = side_of(_text(cells.get("team")))
        if index is None and position < len(teams):
            index = position
        if index is None:
            continue
        teams[index]["periods"] = [
            value
            for key, cell in cells.items()
            if key.startswith("period-")
            and (value := _stat_int(_text(cell))) is not None
        ]

    detail: dict[str, object] = {"source_url": page_url, "teams": teams}
    scoring: list[dict[str, object]] = []
    cards: list[dict[str, object]] = []
    plays: list[dict[str, object]] = []
    for path, table in _walk_tables(game.get("tabs")):
        title = str(table.get("title") or "")
        if path == ("Box Score",) and title == "Team Statistics":
            field: str | None = None
            for row in table.get("body") or []:
                cells = _cells(row)
                label = _text(cells.get("label"))
                index = side_of(label)
                if index is None:
                    field = _TEAM_STATS.get(label.lower())
                    continue
                total = _text(cells.get("total"))
                if field is None or not total:
                    continue
                pair = _SHOTS_TOTAL.match(total)
                if field == "shots" and pair:
                    teams[index]["shots"] = int(pair.group(1))
                    teams[index]["sog"] = int(pair.group(2))
                elif (value := _stat_int(total)) is not None:
                    teams[index][field] = value
        elif path == ("Box Score",) and title == "Scoring Summary":
            for row in table.get("body") or []:
                cells = _cells(row)
                raw = str((cells.get("text") or {}).get("value") or "")
                lines = [line.strip() for line in raw.split("\n") if line.strip()]
                if not lines:
                    continue
                entry: dict[str, object] = {}
                clock = _text(cells.get("time"))
                if clock:
                    entry["time"] = clock
                index = side_of(_text(cells.get("team")))
                if index is not None:
                    entry["team"] = index
                notes = re.findall(r"\(([^)]*)\)", lines[0])
                entry["scorer"] = (
                    re.sub(r"\s*\([^)]*\)", "", lines[0]).strip() or "TEAM"
                )
                for line in lines[1:]:
                    assisted = re.match(r"^Assisted by:\s*(.+)$", line, re.I)
                    if assisted:
                        entry["assist"] = assisted.group(1).strip()
                if notes:
                    entry["description"] = ", ".join(note.strip() for note in notes)
                scoring.append(entry)
        elif path == ("Box Score",) and title == "Cautions and Ejections":
            for row in table.get("body") or []:
                cells = _cells(row)
                kind_text = _text(cells.get("cardType")).lower()
                kind = (
                    "red"
                    if "red" in kind_text
                    else "yellow"
                    if "yellow" in kind_text
                    else "unknown"
                )
                printed = _text(cells.get("player"))
                match = _CARD_PLAYER.match(printed)
                name = match.group("name").strip() if match else printed
                card: dict[str, object] = {"type": kind, "player": name or "TEAM"}
                if name.lower() == "team":
                    card["player"] = "TEAM"
                if match and match.group("number"):
                    card["number"] = match.group("number")
                clock = _text(cells.get("time"))
                if clock:
                    card["time"] = clock
                index = side_of(_text(cells.get("team")))
                if index is not None:
                    card["team"] = index
                cards.append(card)
        elif path and path[0] == "Individual":
            team_name, _, table_kind = title.rpartition(" - ")
            index = side_of(team_name)
            if index is None or table_kind not in (
                "Starters",
                "Substitutes",
                "Goalkeeping",
            ):
                continue
            keeping = table_kind == "Goalkeeping"
            lines_out: list[dict[str, object]] = []
            for row in table.get("body") or []:
                cells = _cells(row)
                name = _text(cells.get("name"))
                if not name or name.lower() in {"team", "totals", "totals:", "total:"}:
                    continue
                line: dict[str, object] = {"name": name}
                position = _text(cells.get("position"))
                if position:
                    line["position"] = position.upper()
                number = _text(cells.get("uni"))
                if number:
                    line["number"] = number
                if keeping:
                    for key, out in (
                        ("minutes", "minutes"),
                        ("goalsAllowed", "goals_against"),
                        ("saves", "saves"),
                    ):
                        value = (_stat_minutes if key == "minutes" else _stat_int)(
                            _text(cells.get(key))
                        )
                        if value is not None:
                            line[out] = value
                else:
                    line["started"] = table_kind == "Starters"
                    for key, out in (
                        ("shots", "shots"),
                        ("shotsOnGoal", "sog"),
                        ("goals", "goals"),
                        ("assists", "assists"),
                        ("minutes", "minutes"),
                    ):
                        value = (_stat_minutes if key == "minutes" else _stat_int)(
                            _text(cells.get(key))
                        )
                        if value is not None:
                            line[out] = value
                lines_out.append(line)
            bucket = "keepers" if keeping else "players"
            existing = teams[index].get(bucket)
            teams[index][bucket] = [
                *(existing if isinstance(existing, list) else []),
                *lines_out,
            ]
        elif len(path) >= 2 and path[0] == "Play-By-Play":
            period = _period(path[1])
            for row in table.get("body") or []:
                cells = _cells(row)
                visiting = _SCORE_PREFIX.match(_text(cells.get("visitorScore")))
                hosting = _SCORE_PREFIX.match(_text(cells.get("homeScore")))
                for index, key in ((0, "visitorText"), (1, "homeText")):
                    text = _text(cells.get(key))
                    if not text:
                        continue
                    play: dict[str, object] = {"period": period, "text": text}
                    clock = _text(cells.get("time"))
                    if re.fullmatch(r"\d+:\d{2}", clock):
                        play["clock"] = clock
                    play["team"] = index
                    kind = _play_type(text)
                    if kind:
                        play["type"] = kind
                    if visiting and hosting:
                        play["score"] = [int(visiting.group(1)), int(hosting.group(1))]
                    plays.append(play)
    if scoring:
        detail["scoring"] = scoring
    if cards:
        detail["cards"] = cards
    if plays:
        detail["plays"] = plays
    venue = str(header.get("venue") or "").strip()
    if venue:
        detail["stadium"] = venue
    for item in header.get("details") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip().lower()
        value = str(item.get("value") or "").strip()
        if (
            label == "attendance"
            and (attendance := _stat_int(value.replace(",", ""))) is not None
        ):
            detail["attendance"] = attendance
        elif label == "time" and value:
            detail["kickoff"] = value
    return detail


def thin_box_lacks(game: dict[str, Any]) -> list[str]:
    """What a served box score does not publish, by its own tab list: the
    Play-By-Play tab, and the Scoring Summary and Cautions tables (a goalless
    match with no cards legitimately has neither, so those two are named
    only beside a missing play-by-play)."""
    titles = [
        (path, str(table.get("title") or ""))
        for path, table in _walk_tables(game.get("tabs"))
    ]
    lacks: list[str] = []
    if not any(path and path[0] == "Play-By-Play" for path, _ in titles):
        lacks.append("play-by-play")
        for name in ("Scoring Summary", "Cautions and Ejections"):
            if not any(title == name for _, title in titles):
                lacks.append(name.lower())
    return lacks


def _names_both_sides(
    teams: list[dict[str, object]], fixture: dict[str, object]
) -> bool:
    if len(teams) != 2:
        return False
    home, away = str(fixture.get("home") or ""), str(fixture.get("away") or "")
    first, second = (str(team.get("name") or "") for team in teams)
    straight = _name_slug_affinity(first, home) and _name_slug_affinity(second, away)
    crossed = _name_slug_affinity(first, away) and _name_slug_affinity(second, home)
    return bool(straight or crossed)


def assert_served_match(
    page: PublishedPage, year: int, fixture: dict[str, object]
) -> dict[str, Any]:
    """A ``wmt.games`` game must prove it is the fixture's match.

    The served game is the requested id (``header.gameId``), men's soccer
    (``sportCode == "MSO"``), finalized, dated the fixture's date by its own
    ``gameDate`` (the venue's wall-clock time labelled ``Z``: the date is
    read as printed, never converted, trap 6.2), and its two sides name the
    fixture's two slugs.  Returns the decoded game.
    """
    fixture_id = str(fixture.get("id", ""))
    requested = _GAME_PATH.search(urlparse(page.requested_url).path)
    if requested is None:
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: {page.requested_url} is not a wmt.games game"
        )
    game = decode_json_body(page.html, page.final_url)
    header = prove_game(game, game_id=requested.group(1), year=year, url=page.final_url)
    if header.get("finalized") is not True:
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: game {requested.group(1)} is not finalized on the statistics host"
        )
    served_date = str(header.get("gameDate") or "")[:10]
    if served_date != str(fixture.get("date")):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: requested the {fixture.get('date')} match but "
            f"game {requested.group(1)} is dated {served_date or 'nothing'}"
        )
    teams = [
        {"name": str((header.get(side) or {}).get("name") or "")}
        for side in ("away", "home")
    ]
    if not _names_both_sides(teams, fixture):
        raise LiveCollectionError(
            f"[{year}] {fixture_id}: game {requested.group(1)} is "
            f"{teams[0]['name']} at {teams[1]['name']}, which does not name both "
            f"{fixture.get('home')} and {fixture.get('away')}"
        )
    return game


def parse_match_page(
    page: PublishedPage, year: int, fixture: dict[str, object]
) -> dict[str, object]:
    """Prove a served or archived game is the fixture's, then read it."""
    game = assert_served_match(page, year, fixture)
    detail = parse_game(game, page_url=page.final_url)
    lacks = thin_box_lacks(game)
    if lacks:
        _LOG.warning(
            "%s: the statistics host's box score publishes no %s; collected what it has",
            fixture.get("id"),
            ", no ".join(lacks),
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
    """Fetch one fixture's ``wmt.games`` game, prove it, parse it, archive it.

    The served body is archived verbatim, ``__gz`` wrapper and all.
    """
    presume_paced(session, url)
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LiveCollectionError(
            f"[{year}] {fixture.get('id')}: failed to fetch box score {url}: {exc}",
            status=http_status(exc),
        ) from exc
    assert_served_body(response, year=year, kind="box-score", url=url, body="json")
    page = PublishedPage(url, str(getattr(response, "url", "") or url), response.text)
    detail = parse_match_page(page, year, fixture)
    if archive is not None:
        archive.save(
            requested_url=page.requested_url,
            final_url=page.final_url,
            html=page.html,
            parsed=detail,
        )
    return detail
