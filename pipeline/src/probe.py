"""Read-only discovery helpers for onboarding athletics sites."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src import presto
from src.gazetteer import parse_town
from src.sidearm_live import (
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    LiveCollectionError,
    PublishedPage,
    _clean_team_name,
    _component_objects,
    _has_schedule_markup,
    _identity_key,
    boxscore_links,
    fetch_published_page,
    parse_roster_page,
    parse_schedule_page,
    parse_stats_page,
)

PLATFORM_SIDEARM = "sidearm"
PLATFORM_SIDEARM_LEGACY = "sidearm_legacy"
PLATFORM_STATCREW = "statcrew"
PLATFORM_PRESTOSPORTS = presto.PLATFORM
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
    if "sidearm.nextgen.sites" in lower:
        # The Nuxt skin's asset bucket, named on every page it serves; the
        # pages carry no li.sidearm-* markup and no events component.
        sidearm_evidence.append("SideArm nextgen asset bucket")
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

    # A SideArm page never carries PrestoSports markup, but the order is kept
    # explicit: SideArm first, PrestoSports next, then the advisory StatCrew
    # shape and the unknown fallback.
    presto_evidence = presto.is_presto(html)
    if presto_evidence:
        return PLATFORM_PRESTOSPORTS, presto_evidence

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


def _fetch_failed(exc: LiveCollectionError) -> bool:
    """Whether the page was never served, as opposed to served and unproven."""
    return exc.status is not None or isinstance(
        exc.__cause__, requests.RequestException
    )


def _layer_error(exc: LiveCollectionError) -> str:
    return f"{LAYER_ERROR} ({failure_detail(exc)})"


def fetch_schedule_page(
    session: requests.Session,
    base_url: str,
    year: int,
    platform: str = PLATFORM_SIDEARM,
) -> PublishedPage:
    """Fetch and prove one season's schedule page at the platform's own URL."""
    if platform == PLATFORM_PRESTOSPORTS:
        url = presto.layer_url(base_url, year, LAYER_SCHEDULE)
        return presto.fetch_page(session, url, year, LAYER_SCHEDULE)
    return fetch_published_page(session, base_url, year, LAYER_SCHEDULE)


def _schedule_markup(html: str, platform: str) -> bool:
    if platform == PLATFORM_PRESTOSPORTS:
        return presto.has_schedule_markup(html)
    return _has_schedule_markup(html)


def _sidearm_layers(
    session: requests.Session, base_url: str, year: int
) -> dict[str, str]:
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
    except LiveCollectionError as exc:
        layers[LAYER_SCHEDULE] = _layer_error(exc)
        layers[LAYER_MATCHES] = _layer_error(exc)

    try:
        roster = fetch_published_page(session, base_url, year, LAYER_ROSTER)
        players = parse_roster_page(roster.html, page_url=roster.final_url)
        layers[LAYER_ROSTER] = LAYER_PRESENT if players else LAYER_ABSENT
    except LiveCollectionError as exc:
        layers[LAYER_ROSTER] = _layer_error(exc)

    try:
        stats = fetch_published_page(session, base_url, year, LAYER_STATS)
        stat_players, stat_keepers = parse_stats_page(
            stats.html, page_url=stats.final_url
        )
        layers[LAYER_STATS] = (
            LAYER_PRESENT if stat_players or stat_keepers else LAYER_ABSENT
        )
    except LiveCollectionError as exc:
        layers[LAYER_STATS] = _layer_error(exc)
    return layers


def _presto_layers(
    session: requests.Session, base_url: str, year: int, landing_html: str
) -> dict[str, str]:
    layers: dict[str, str] = {}
    segment: str | None = None
    schedule_failure: LiveCollectionError | None = None
    try:
        schedule = presto.fetch_page(
            session,
            presto.layer_url(base_url, year, LAYER_SCHEDULE),
            year,
            LAYER_SCHEDULE,
        )
        layers[LAYER_SCHEDULE] = (
            LAYER_PRESENT if presto.has_schedule_markup(schedule.html) else LAYER_ABSENT
        )
        layers[LAYER_MATCHES] = (
            LAYER_PRESENT
            if presto.boxscore_links(schedule.html, schedule.final_url)
            else LAYER_ABSENT
        )
        segment = presto.team_segment(schedule.html)
    except LiveCollectionError as exc:
        layers[LAYER_SCHEDULE] = _layer_error(exc)
        layers[LAYER_MATCHES] = _layer_error(exc)
        schedule_failure = exc

    try:
        roster = presto.fetch_page(
            session, presto.layer_url(base_url, year, LAYER_ROSTER), year, LAYER_ROSTER
        )
        layers[LAYER_ROSTER] = (
            LAYER_PRESENT if presto.has_roster_markup(roster.html) else LAYER_ABSENT
        )
    except LiveCollectionError as exc:
        layers[LAYER_ROSTER] = _layer_error(exc)

    # The statistics URL carries the school's own segment, read from a link
    # the site publishes (the schedule page, else the landing page), never
    # guessed from the school's name.  A skin that publishes no such link
    # (the legacy table and mobile list skins) still reveals the segment
    # through the site's own redirect of ``{y}-{yy}/teams``, the way the
    # collector finds it (``presto.locate_stats``); the probe then judges
    # the print template that redirect leads to, which is the page the
    # collector reads.
    if segment is None and landing_html:
        segment = presto.team_segment(landing_html)
    if segment is None and schedule_failure is not None:
        layers[LAYER_STATS] = (
            f"{LAYER_ERROR} (team link not read: {failure_detail(schedule_failure)})"
        )
        return layers
    try:
        if segment is not None:
            stats = presto.fetch_page(
                session, presto.stats_url(base_url, year, segment), year, LAYER_STATS
            )
            present = presto.has_stats_markup(stats.html)
        else:
            stats = presto.fetch_page(
                session, presto.locate_stats(session, base_url, year), year, LAYER_STATS
            )
            present = presto.has_player_stats_markup(stats.html)
        layers[LAYER_STATS] = LAYER_PRESENT if present else LAYER_ABSENT
    except LiveCollectionError as exc:
        layers[LAYER_STATS] = _layer_error(exc)
    return layers


def probe_layers(
    session: requests.Session,
    base_url: str,
    year: int,
    platform: str = PLATFORM_SIDEARM,
    *,
    landing_html: str = "",
) -> dict[str, str]:
    """Report whether each live collection layer is present for one season.

    A layer whose page was not served reads ``error (HTTP 403)``, ``error
    (timeout)`` and so on: what HTTP said is a suffix on the error value,
    never a bare ``error``.  PrestoSports sites are probed at their own URLs
    with their own season proof and detectors; ``landing_html`` is where the
    team statistics segment is read when the schedule page did not carry it.
    Every other platform keeps the SideArm path.
    """
    if platform == PLATFORM_PRESTOSPORTS:
        layers = _presto_layers(session, base_url, year, landing_html)
    else:
        layers = _sidearm_layers(session, base_url, year)
    return {
        layer: layers[layer]
        for layer in (LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES)
    }


@dataclass(frozen=True)
class SeasonSurvey:
    """Which candidate seasons a site proved, and which it never showed."""

    served: list[int]
    #: Candidate seasons whose schedule fetch was refused, with what HTTP said.
    errors: dict[int, str]


def survey_seasons(
    session: requests.Session,
    base_url: str,
    years: Iterable[int],
    platform: str = PLATFORM_SIDEARM,
) -> SeasonSurvey:
    """Prove each candidate season's schedule page, naming the fetches refused.

    A season is served when its page proved the requested year and carries
    schedule markup.  A page the site served but that proves another season,
    or carries no markup, is not served and says nothing more, as before; a
    fetch the site refused is recorded with what HTTP said (bead tl-v1q.6),
    so a 403 on every season never reads as "none".
    """
    served: list[int] = []
    errors: dict[int, str] = {}
    for year in years:
        try:
            page = fetch_schedule_page(session, base_url, year, platform)
        except LiveCollectionError as exc:
            if _fetch_failed(exc):
                errors[year] = failure_detail(exc)
            continue
        if _schedule_markup(page.html, platform):
            served.append(year)
    return SeasonSurvey(served=served, errors=errors)


def served_seasons(
    session: requests.Session,
    base_url: str,
    years: Iterable[int],
    platform: str = PLATFORM_SIDEARM,
) -> list[int]:
    """Return candidate seasons whose schedule page proves the requested year."""
    return survey_seasons(session, base_url, years, platform).served


# Words that carry no identity when they lead a published name.  They are
# skipped when reading a mascot off the tail of a description and when minting
# initials ("Auburn University at Montgomery" mints AUM, not AUAM).
_FILLER_WORDS = frozenset({"university", "college", "of", "the", "at", "in", "and"})
_SITE_SUFFIX = re.compile(r"\s+athletics(?:\s+site)?$", re.I)
_DESCRIBED_FOR = re.compile(r"\bfor\s+the\s+(.+?)\s*$", re.I)
_SITE_NAME_JSON = re.compile(r'"site_name"\s*:\s*"([A-Za-z0-9-]+)"')
# PrestoSports titles lead with the season and the team ("2025 Tampa Spartans
# Men's Soccer Schedule"); SideArm titles lead with the season and the sport
# ("2026 Men's Soccer Schedule - …") and never match.
_TITLED_TEAM = re.compile(
    r"^\s*\d{4}(?:-\d{2})?\s+(.+?)\s+(?:men|women)[’']s\s+soccer\b", re.I
)


@dataclass(frozen=True)
class SchoolIdentity:
    """The identity fields a ``schools.toml`` stanza needs."""

    name: str
    abbreviation: str
    mascot: str
    aliases: list[str] = field(default_factory=list)
    #: The town the schedule page prints for home rows, normalised to AP style.
    city: str = ""


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


def _home_town(html: str) -> str:
    """The town the schedule page prints most often on its home rows, AP style.

    SideArm rows carry ``.sidearm-schedule-game-location`` ("Alamosa, CO" then
    the facility); a home row is marked ``sidearm-schedule-game-home`` on the
    row or an element inside it. When no row is marked home, every location
    on the page counts and the majority wins — a school plays most of its
    games at home. A page that prints no location, or towns that never
    agree, yields "" and the stanza says so.  PrestoSports rows print no
    location at all (only "vs"/"at" and the opponent), so they yield "".
    """
    soup = BeautifulSoup(html, "lxml")
    home: list[str] = []
    every: list[str] = []
    for node in soup.select(".sidearm-schedule-game-location"):
        first = node.find("span")
        town = parse_town((first or node).get_text(" ", strip=True))
        if town is None:
            continue
        every.append(town.ap)
        row = node
        for _ in range(8):
            row = row.parent
            if row is None:
                break
            classes = row.get("class") or []
            if (
                "sidearm-schedule-game" in classes
                or "sidearm-schedule-game-home" in classes
            ):
                if "sidearm-schedule-game-home" in classes or row.select_one(
                    ".sidearm-schedule-game-home"
                ):
                    home.append(town.ap)
                break
    counted = Counter(home or every)
    if not counted:
        return ""
    ((best, n),) = counted.most_common(1)
    return best if n * 2 > sum(counted.values()) else ""


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
    "for the {published name} {Mascot}", or on PrestoSports the title leads
    with "{season} {published name} {Mascot} Men's Soccer"; the theme
    payload's ``site_name`` is the site's own short token ("umsl").  Schedule
    opponent spellings that contain every word of the name are aliases the
    member sites publish.
    """
    site_names: list[str] = []
    described: list[str] = []
    short_tokens: list[str] = []
    opponents: list[str] = []
    city = ""
    hosts = [urlparse(url).hostname or ""]
    for html in pages:
        if not city:
            city = _home_town(html)
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
        title = soup.title.get_text(" ", strip=True) if soup.title is not None else ""
        titled = _TITLED_TEAM.match(title)
        if titled:
            described.append(titled.group(1).strip())
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
        abbreviation = _initials(name)
    # A single letter is no short form anyone prints (batch 4 minted "C"
    # for five hosts and "L" for Lee, bead tl-4an.29); it is refused rather
    # than padded into an initialism the site never used.
    if len(abbreviation) <= 1:
        abbreviation = ""

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
        name=name, abbreviation=abbreviation, mascot=mascot, aliases=aliases, city=city
    )


#: The comment a draft carries in place of a one-letter abbreviation.
ABBREVIATION_BY_HAND = (
    "# hand abbreviation required: the site prints no short form the probe could read"
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
    city: str = "",
    accessed: str = "",
) -> str:
    """Render a disabled, unverified ``schools.toml`` entry in the house layout.

    Keys pad to the width the hand-authored stanzas use so the draft pastes
    beside them unchanged.  A mascot the site did not yield becomes a comment
    naming the gap rather than an empty value; an abbreviation of one letter
    (or none) is written empty with a comment saying the short form must be
    set by hand, never padded into an initialism.  For PrestoSports,
    ``base_url`` is the sport landing page and both ``scraper`` and
    ``live_scraper`` name the platform.
    """
    scraper = platform
    live_scraper = platform
    alias_list = list(aliases)
    lines = ["[[schools]]", _toml_line("name", name)]
    if len(abbreviation) > 1:
        lines.append(_toml_line("abbreviation", abbreviation))
    else:
        lines.append(_toml_line("abbreviation", ""))
        lines.append(ABBREVIATION_BY_HAND)
    lines.append(_toml_line("conference", conference))
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
    # config.py reads a missing ``live_scraper`` as SideArm, so a platform
    # with a live path of its own is written out; the hand-authored StatCrew
    # stanzas leave it absent because their live sites are SideArm.
    if live_scraper != scraper or live_scraper == PLATFORM_PRESTOSPORTS:
        lines.append(_toml_line("live_scraper", live_scraper))
    lines.extend(
        [
            _toml_line("data_status", "unverified"),
            _toml_line("enabled", False),
        ]
    )
    # The programmes reference (tl-891) needs the town and the date the
    # identity facts were read; its build fails on a stanza without them.
    if city:
        lines.append(_toml_line("city", city))
    else:
        lines.append(
            '# city: the schedule page prints no home town; fill by hand as "Town, St."'
        )
        lines.append(
            "# city_source: cite where the town was read (default: the schedule page)"
        )
    lines.append(_toml_line("identity_accessed", accessed or date.today().isoformat()))
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
    #: What HTTP said when the landing page itself was refused ("HTTP 403"):
    #: the platform line then says so instead of claiming the site showed no
    #: evidence (bead tl-v1q.6).
    not_seen: str = ""
    #: Candidate seasons whose schedule fetch was refused, with what HTTP said.
    season_errors: dict[int, str] = field(default_factory=dict)
    #: Stanza fields the probe could not fill and a person must ("abbreviation").
    hand_edits: list[str] = field(default_factory=list)

    def render(self) -> str:
        if self.not_seen:
            platform = f"{self.platform} — {self.not_seen} from {self.url}"
            evidence = "site not seen"
        else:
            platform = self.platform
            evidence = "; ".join(self.evidence) if self.evidence else "none"
        seasons = ", ".join(str(year) for year in self.seasons) or "none"
        lines = [
            f"URL: {self.url}",
            f"Platform: {platform}",
            f"Evidence: {evidence}",
            "Layers:",
        ]
        lines.extend(
            f"  {layer}: {self.layers.get(layer, LAYER_ERROR)}"
            for layer in (LAYER_SCHEDULE, LAYER_ROSTER, LAYER_STATS, LAYER_MATCHES)
        )
        lines.append(f"Served seasons: {seasons}")
        if self.season_errors:
            lines.append(
                "Seasons not seen: "
                + ", ".join(
                    f"{year} ({detail})" for year, detail in self.season_errors.items()
                )
            )
        if self.hand_edits:
            lines.append("Hand edits still needed: " + ", ".join(self.hand_edits))
        lines.extend(
            [
                "",
                "Draft schools.toml stanza:",
                self.stanza.rstrip(),
            ]
        )
        return "\n".join(lines) + "\n"
