"""Read-only discovery helpers for onboarding athletics sites."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.sidearm_live import (
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    LiveCollectionError,
    _clean_team_name,
    _component_objects,
    _has_schedule_markup,
    _identity_key,
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
    if re.search(r"\bvs?\.?\s+.+\([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\)", title):
        statcrew_evidence.append("StatCrew custompages title shape")
    if statcrew_evidence:
        return PLATFORM_STATCREW, statcrew_evidence

    return PLATFORM_UNKNOWN, []


def probe_layers(session: requests.Session, base_url: str, year: int) -> dict[str, str]:
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


# Words that carry no identity when they lead a published name.  They are
# skipped when reading a mascot off the tail of a description and when minting
# initials ("Auburn University at Montgomery" mints AUM, not AUAM).
_FILLER_WORDS = frozenset({"university", "college", "of", "the", "at", "in", "and"})
_SITE_SUFFIX = re.compile(r"\s+athletics(?:\s+site)?$", re.I)
_DESCRIBED_FOR = re.compile(r"\bfor\s+the\s+(.+?)\s*$", re.I)
_SITE_NAME_JSON = re.compile(r'"site_name"\s*:\s*"([A-Za-z0-9-]+)"')


@dataclass(frozen=True)
class SchoolIdentity:
    """The identity fields a ``schools.toml`` stanza needs."""

    name: str
    abbreviation: str
    mascot: str
    aliases: list[str] = field(default_factory=list)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'.&-]*", text)


def _initials(text: str) -> str:
    words = [w for w in _words(text) if w.lower() not in _FILLER_WORDS]
    return "".join(w[0] for w in words).upper()


def _meta(soup: BeautifulSoup, **attrs: str) -> str:
    tag = soup.find("meta", attrs=attrs)
    if tag is None:
        return ""
    return str(tag.get("content") or "").strip()


def _opponent_spellings(html: str) -> list[str]:
    """Every opponent string a schedule page publishes, either rendering."""
    spellings: list[str] = []
    soup = BeautifulSoup(html, "lxml")
    for node in soup.select(".sidearm-schedule-game-opponent-name"):
        spellings.append(node.get_text(" ", strip=True))
    for component in _component_objects(html):
        if component.get("type") != "events":
            continue
        data = component.get("data")
        if not isinstance(data, list):
            continue
        for raw in data:
            if not isinstance(raw, dict):
                continue
            opponent = raw.get("opponent")
            opponent_dict = opponent if isinstance(opponent, dict) else {}
            spellings.append(
                str(opponent_dict.get("title") or opponent_dict.get("name") or "")
            )
    halves: list[str] = []
    for spelling in spellings:
        for half in re.split(r"\s+vs\.?\s+", _clean_team_name(spelling)):
            half = re.sub(r"\([^)]*\)", " ", half).strip()
            if half:
                halves.append(half)
    return halves


def _mascot_after(published: str, known: Iterable[str]) -> str:
    """The published tail once every leading word is part of a known name.

    "University of Indianapolis Greyhounds" against the site name "UIndy" and
    the chosen name "Indianapolis" leaves "Greyhounds"; "UIS Prairie Stars"
    keeps both mascot words.
    """
    known_words = {
        w.lower().strip(".") for text in known for w in _words(text)
    } | _FILLER_WORDS
    words = _words(published)
    index = 0
    while index < len(words) and words[index].lower().strip(".") in known_words:
        index += 1
    if index == 0 or index == len(words):
        return ""
    return " ".join(words[index:])


def _hostname_suffix(tail: str, hosts: Iterable[str]) -> str:
    """The shortest trailing run of ``tail`` the site's own hostname spells.

    Mascots live in hostnames ("uisprairiestars.com", "umsltritons.com"), so
    a multi-word tail keeps every word the hostname carries ("Prairie Stars")
    and otherwise falls back to its last word.
    """
    words = _words(tail)
    joined = " ".join(host.lower() for host in hosts)
    for start in range(len(words)):
        if "".join(w.lower() for w in words[start:]) in joined:
            return " ".join(words[start:])
    return words[-1] if words else ""


def derive_identity(
    *, name: str, pages: Iterable[str], url: str = ""
) -> SchoolIdentity:
    """Mint abbreviation, mascot and aliases from what the site says of itself.

    ``name`` is the slug-minting name a person chose (``--name``); when empty
    the site's own ``og:site_name`` stands in.  The site is read in three
    places: ``og:site_name`` carries the published institution name, or the
    site's short form ("UIS Athletics"); the description meta ends with
    "for the {published name} {Mascot}"; the theme payload's ``site_name`` is
    the site's own short token ("umsl").  Schedule opponent spellings that
    contain every word of the name are aliases the member sites publish.
    """
    site_names: list[str] = []
    described: list[str] = []
    short_tokens: list[str] = []
    opponents: list[str] = []
    hosts = [urlparse(url).hostname or ""]
    for html in pages:
        soup = BeautifulSoup(html, "lxml")
        site_name = _SITE_SUFFIX.sub("", _meta(soup, property="og:site_name"))
        if site_name:
            site_names.append(site_name)
        hosts.append(urlparse(_meta(soup, property="og:url")).hostname or "")
        for content in (
            _meta(soup, name="description"),
            _meta(soup, property="og:description"),
        ):
            match = _DESCRIBED_FOR.search(content)
            if match:
                described.append(match.group(1).strip().rstrip("."))
        short_tokens.extend(_SITE_NAME_JSON.findall(html))
        opponents.extend(_opponent_spellings(html))

    site_name = site_names[0] if site_names else ""
    name = name.strip() or site_name
    known = [n for n in (name, site_name) if n]

    mascot = ""
    published_names: list[str] = []
    for text in described:
        tail = _hostname_suffix(_mascot_after(text, known), hosts)
        if tail and not mascot:
            mascot = tail
        published_names.append(text[: len(text) - len(tail)].strip() if tail else text)

    # The site's short token is the abbreviation when the site spells it as
    # its whole name ("UIndy Athletics", "UIS Athletics") or when it is an
    # opaque short form the long name does not contain ("umsl").  A token
    # that is merely the first word of a long name ("truman") is not one.
    abbreviation = ""
    site_words = _words(site_name)
    for token in short_tokens:
        spelled = next((w for w in site_words if w.lower() == token.lower()), "")
        if spelled and len(site_words) == 1:
            abbreviation = spelled
        elif not spelled and len(token) <= 5:
            abbreviation = token.upper()
        if abbreviation:
            break
    if not abbreviation:
        for candidate in (site_name, *published_names, name):
            if len(_words(candidate)) > 1:
                abbreviation = _initials(candidate)
                break
    if not abbreviation:
        abbreviation = _initials(name) or "TBD"

    name_key = _identity_key(name)
    name_tokens = set(name_key.split())
    seen = {name_key, _identity_key(abbreviation)}
    aliases: list[str] = []
    for candidate in (site_name, *published_names, *opponents):
        key = _identity_key(candidate)
        if not key or key in seen:
            continue
        if candidate in opponents and not name_tokens <= set(key.split()):
            continue
        seen.add(key)
        aliases.append(candidate)
    return SchoolIdentity(
        name=name, abbreviation=abbreviation, mascot=mascot, aliases=aliases
    )


def _toml_line(key: str, value: object) -> str:
    return f"{key:<12} = {json.dumps(value)}"


def draft_stanza(
    *,
    name: str,
    abbreviation: str,
    conference: str,
    base_url: str,
    gender: str,
    platform: str,
    seasons: Iterable[int],
    mascot: str = "",
    aliases: Iterable[str] = (),
) -> str:
    """Render a disabled, unverified ``schools.toml`` entry in the house layout.

    Keys pad to the width the hand-authored stanzas use so the draft pastes
    beside them unchanged.  A mascot the site did not yield becomes a comment
    naming the gap rather than an empty value.
    """
    scraper = platform
    live_scraper = platform
    alias_list = list(aliases)
    lines = [
        "[[schools]]",
        _toml_line("name", name),
        _toml_line("abbreviation", abbreviation),
        _toml_line("conference", conference),
    ]
    if mascot:
        lines.append(_toml_line("mascot", mascot))
    else:
        lines.append("# mascot: not published where the probe reads; fill by hand")
    if alias_list:
        rendered = ", ".join(json.dumps(alias) for alias in alias_list)
        lines.append(f"{'aliases':<12} = [{rendered}]")
    lines.extend(
        [
            _toml_line("gender", gender),
            _toml_line("base_url", base_url.rstrip("/")),
            f"{'years':<12} = [{', '.join(str(year) for year in seasons)}]",
            _toml_line("scraper", scraper),
        ]
    )
    if live_scraper != scraper:
        lines.append(_toml_line("live_scraper", live_scraper))
    lines.extend(
        [
            _toml_line("data_status", "unverified"),
            _toml_line("enabled", False),
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
