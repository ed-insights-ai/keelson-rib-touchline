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
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import SchoolConfig


class LiveCollectionError(RuntimeError):
    """A live page could not be proven to represent the requested season."""


@dataclass(frozen=True)
class PublishedPage:
    requested_url: str
    final_url: str
    html: str


LAYER_SCHEDULE = "schedule"
LAYER_ROSTER = "roster"
DEFAULT_LAYERS: tuple[str, ...] = (LAYER_SCHEDULE, LAYER_ROSTER)

# The vocabulary the coverage manifest renders.  These three states are the
# whole reason the manifest exists: an empty results column means something
# different in each, and conflating them is how a data product loses trust.
STATE_COMPLETE = "complete"  # served, proven, and holds rows
STATE_EMPTY = "empty"  # served and proven, and genuinely holds nothing
STATE_UNAVAILABLE = "unavailable"  # could not be collected; `reason` says why


@dataclass(frozen=True)
class LayerOutcome:
    """What one collection layer produced for one programme."""

    layer: str
    state: str
    count: int = 0
    reason: str | None = None
    source_url: str | None = None


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

    def state(self, layer: str) -> str:
        outcome = self.outcomes.get(layer)
        return outcome.state if outcome else STATE_UNAVAILABLE


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (Touchline educational/research collector)"}
    )
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
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
    match = re.search(
        rf"\b(\d{{4}})(?:-\d{{2}})?\b.*\b{kind}\b", title.get_text(" "), re.I
    )
    return int(match.group(1)) if match else None


def assert_served_season(page: PublishedPage, year: int, kind: str) -> None:
    """Reject a silent redirect or fallback to another season.

    Some SideArm sites canonicalise the current season to ``/schedule``.  That
    is acceptable only when the title independently names the requested year.
    When both path and title name a season, both must agree.
    """
    path_year = _season_in_path(page.final_url, kind)
    title_year = _season_in_title(page.html, kind)
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


def fetch_published_page(
    session: requests.Session, base_url: str, year: int, kind: str
) -> PublishedPage:
    requested_url = f"{base_url.rstrip('/')}/{kind}/{year}"
    try:
        response = session.get(requested_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LiveCollectionError(
            f"[{year}] failed to fetch {kind} page {requested_url}: {exc}"
        ) from exc
    page = PublishedPage(requested_url, response.url, response.text)
    assert_served_season(page, year, kind)
    return page


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


def assert_payload_season(html: str, year: int, page_url: str) -> None:
    """Refuse a schedule whose own payload belongs to a different season.

    Raises with two distinguishable reasons, because the coverage manifest has to
    tell them apart: a site that serves its current schedule at every season URL
    is a permanent capability gap, while a season page that carries no fixtures
    yet is a temporary one that will fill in on its own.
    """
    served = payload_seasons(html)
    if not served:
        raise LiveCollectionError(
            f"[{year}] {page_url} published no schedule payload — "
            f"either the season is not released yet or the page is not SideArm"
        )
    if year not in served:
        listed = ", ".join(str(value) for value in sorted(served))
        raise LiveCollectionError(
            f"[{year}] {page_url} is published for season {listed} — "
            f"this site serves its current schedule at every season URL, "
            f"so {year} fixtures cannot be collected from it"
        )


def _clean_team_name(name: object) -> str:
    return re.sub(r"^#\d+\s+", "", str(name or "").strip())


def _identity_key(name: str) -> str:
    """Normalize a published opponent string toward a comparable identity.

    The parenthetical is dropped because sites use it for two different things
    and neither belongs in an institution's identity: a disambiguating region
    ("Rogers State University (Okla.)") and a match-type annotation ("Oklahoma
    Wesleyan (Exhibition)").
    """
    text = _clean_team_name(name).lower().replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\bst\.?\b", "state", text)
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
        for candidate in (school.name, school.abbreviation):
            key = _identity_key(candidate)
            if key:
                aliases[key] = slug
    return aliases


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
    """Resolve a rendered date like ``Aug 13 (Thu)`` against the season year."""
    match = re.search(r"([A-Za-z]{3})[a-z.]*\s+(\d{1,2})", text)
    if not match:
        return None
    month = _DOM_MONTHS.get(match.group(1).lower())
    if month is None:
        return None
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
    """Parse an owner-perspective result like ``W, 2-0`` or ``T, 1-1 (2OT)``."""
    match = re.search(r"\b([WLT])\s*,?\s*(\d+)\s*-\s*(\d+)", text)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def _parse_schedule_dom(
    html: str,
    *,
    page_url: str,
    year: int,
    owner_slug: str,
    aliases: dict[str, str],
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
    masquerade as a publisher's claim.  Membership means the school list this
    run was configured with, never a conference named in code.
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
    member_slugs = set(aliases.values())

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
            classes = set(row.get("class") or [])
            if "sidearm-schedule-neutral-game" in classes:
                # Neutral rows keep the "vs"/"at" span as the only side
                # indicator.
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
        if re.search(r"cancel", result_text, re.IGNORECASE):
            status = "cancelled"
        elif re.search(r"postpon", result_text, re.IGNORECASE):
            status = "postponed"
        elif result:
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
        if theme_marks_conference:
            fixture["conference_game"] = conference_marked(row)
        else:
            exhibition = bool(re.search(r"exhib", opponent_raw, re.IGNORECASE))
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
        location = row.select_one(".sidearm-schedule-game-location")
        if location is not None:
            facility = location.select_one("a")
            venue = (
                facility.get_text(" ", strip=True)
                if facility is not None
                else location.get_text(" ", strip=True)
            )
            if venue:
                fixture["venue"] = venue
        if result:
            _, owner_score, other_score = result
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
        opponent_name = _clean_team_name(
            opponent_dict.get("title") or opponent_dict.get("name")
        )
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
        if not event.get("tbd") and "T" in date_text:
            try:
                local = datetime.fromisoformat(date_text)
                fixture["time"] = local.strftime("%H:%M")
            except ValueError:
                pass
        facility = event.get("game_facility")
        facility_dict = facility if isinstance(facility, dict) else {}
        venue = str(facility_dict.get("title") or event.get("location") or "").strip()
        if venue:
            fixture["venue"] = venue
        if (
            status in {"final", "live"}
            and team_score is not None
            and opponent_score is not None
        ):
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
        html, page_url=page_url, year=year, owner_slug=owner_slug, aliases=aliases
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


def collect_programme(
    school: SchoolConfig,
    year: int,
    aliases: dict[str, str],
    session: requests.Session | None = None,
    layers: Sequence[str] = DEFAULT_LAYERS,
) -> ProgrammeCollection:
    """Collect the requested layers, each standing or falling on its own.

    Layer independence is the point.  For any past season the roster is served
    and the schedule is not, so a collector that fails the whole programme when
    the schedule fails can never retrieve a historical roster — which is the
    substrate the roster analysis work needs.
    """
    slug = programme_slug(school.name)
    wanted = tuple(layers)
    outcomes: dict[str, LayerOutcome] = {}
    fixtures: list[dict[str, object]] = []
    players: list[dict[str, str]] = []
    schedule_html = ""
    roster_html = ""
    schedule_url = ""
    roster_url = ""

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
        try:
            page = fetch_published_page(client, base_url, year, "schedule")
            assert_payload_season(page.html, year, page.final_url)
            schedule_html = page.html
            schedule_url = page.final_url
            fixtures = parse_schedule_page(
                page.html,
                page_url=page.final_url,
                year=year,
                owner_slug=slug,
                aliases=aliases,
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
        except LiveCollectionError as exc:
            outcomes[LAYER_SCHEDULE] = LayerOutcome(
                LAYER_SCHEDULE,
                STATE_UNAVAILABLE,
                reason=str(exc),
                source_url=schedule_url,
            )

    if LAYER_ROSTER in wanted:
        roster_url = f"{base_url}/roster/{year}"
        try:
            page = fetch_published_page(client, base_url, year, "roster")
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
        except LiveCollectionError as exc:
            outcomes[LAYER_ROSTER] = LayerOutcome(
                LAYER_ROSTER, STATE_UNAVAILABLE, reason=str(exc), source_url=roster_url
            )

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
    )


def write_raw_pages(
    root: Path, result: ProgrammeCollection, year: int, gender: str
) -> None:
    """Archive whatever was actually served, so any parse can be redone offline."""
    if not (result.schedule_html or result.roster_html):
        return
    directory = root / "data" / "raw_html" / result.slug
    directory.mkdir(parents=True, exist_ok=True)
    if result.schedule_html:
        (directory / f"{year}-{gender}-schedule.html").write_text(
            result.schedule_html, encoding="utf-8"
        )
    if result.roster_html:
        (directory / f"{year}-{gender}-roster.html").write_text(
            result.roster_html, encoding="utf-8"
        )
