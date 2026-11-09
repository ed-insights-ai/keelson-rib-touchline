"""School configuration loader — reads config/schools.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "schools.toml"
DEFAULT_LIVE_COLLECTOR = "sidearm"


def programme_slug(name: str) -> str:
    """The institution slug a published name mints: lower-case ASCII words
    joined by hyphens ("Lincoln Memorial" -> "lincoln-memorial"). Every slug
    the archive carries, a stanza's and an opponent's alike, comes from this
    one function, so disambiguation is always carried in the words themselves
    and never in a separate key."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@dataclass
class SchoolConfig:
    """Configuration for a single school's data source."""

    name: str
    abbreviation: str
    conference: str
    prefix: str
    base_url: str
    # Reader-facing name, when it differs from ``name``. ``name`` does double
    # duty: programme_slug(name) mints the institution slug that keys
    # membership.json and every coverage cell, so it must stay
    # ASCII-plain and stable even when the school's published name carries
    # punctuation ("St. Mary's" → name "Saint Marys", slug "saint-marys") or
    # the school renames (slugs never rename). ``display_name`` carries the
    # published spelling for reader-facing surfaces; empty means ``name`` is
    # already the published name. Use ``display()`` to resolve. It is never
    # an identity claim: opponent resolution and check-membership's
    # collision check read ``name`` and ``aliases`` (and a resolving
    # abbreviation) only, so a display name may carry a qualifier that
    # folds to another stanza's key ("Dominican (Calif.)" beside the
    # incumbent "Dominican"). A spelling that should resolve is an alias.
    # The slug is also the identity of every map the collect keys by
    # programme, so two enabled stanzas of one gender may not mint the same
    # one: load_schools refuses the pair. A same-named institution (a second
    # "Lincoln") qualifies ``name`` the way opponent text already does
    # ("Lincoln Memorial" beside "Lincoln"), minting its own slug, and keeps
    # the published spelling in ``display_name``.
    display_name: str = ""
    years: list[int] = field(default_factory=list)
    enabled: bool = False
    data_status: str = "unverified"
    notes: str = ""
    mascot: str = ""
    # Published name variants opponents use for this school. The live
    # collector resolves an opponent string against name/abbreviation and
    # falls back to token matching; a formal name ("Auburn University at
    # Montgomery") shares no token with a short one ("AUM") and so needs
    # to be stated. Scoped per stanza, which keeps the map gender-correct.
    aliases: list[str] = field(default_factory=list)
    # Whether ``abbreviation`` also resolves opponent text. The identity map
    # is one table per gender across every stanza, last stanza wins, so a
    # bare initialism two stanzas share ("BU", "RU", "SCSU") would silently
    # re-point one school's spelling to another's; such a stanza sets this
    # false and its abbreviation stays display-only (coverage cells, the
    # programmes reference) while only its name and aliases resolve.
    # check-membership refuses any spelling two stanzas of one gender claim.
    abbreviation_resolves: bool = True
    # Published spellings that identify this programme only among its
    # conference peers. A peer's schedule page prints the short name the
    # conference uses ("Dominican" for Dominican of California on Chaminade's
    # page, "Concordia" for Concordia Irvine), and that short name may be
    # another stanza's whole name in another conference, so it cannot be a
    # gender-wide alias without colliding. A member alias enters no
    # gender-wide map: it resolves only during a collect of a conference this
    # programme is a member of that season (the membership windows decide),
    # where the collecting conference's members are preferred over every
    # other programme. check-membership refuses a member alias that another
    # stanza of the same conference and gender claims.
    member_aliases: list[str] = field(default_factory=list)
    # The programme's first season, for a programme that STARTED inside the
    # rib's depth (Wayne State (Mich.) women, 2026). 0, the default, says
    # nothing: a window's from_season is often a depth decision, not a
    # founding, so it is never read as one. A claimant whose first season is
    # after the season being collected drops out of the distance tiebreak
    # (resolution_scope): a name cannot mean a team that did not exist yet.
    first_season: int = 0
    # The town the programme plays in, as its schedule page prints it
    # ("Alamosa, Colo.", "Ada, OK"); the programmes reference normalises it to
    # AP style and resolves it to one Gazetteer place. city_source cites where
    # the string was read (default: the schedule page's home venue location);
    # identity_accessed is the date the identity facts were read off the site.
    city: str = ""
    city_source: str = ""
    identity_accessed: str = ""
    # A GEOID pin for a town the name lookup cannot settle (consolidated
    # cities, a "St." the programme spells "Saint", two places of one name).
    gazetteer_geoid: str = ""
    # Why a pin's Gazetteer row is not named for the town the school prints:
    # the printed town is an unincorporated community inside the pinned
    # place. Required for such a pin (the build refuses a name mismatch
    # without it); written through to the programmes row's point provenance.
    gazetteer_note: str = ""
    # A point for a town the Gazetteer does not cover at all (Simon Fraser
    # plays in Burnaby, B.C.; the Gazetteer is US-only): (lat, lon) in
    # decimal degrees, with point_source saying where the pair was read. The
    # programmes build honours it only when the Gazetteer resolves the city
    # to nothing, and refuses it on a city the Gazetteer does resolve, so a
    # pin can never silently override a real place. Never beside a GEOID pin.
    point: tuple[float, float] | None = None
    point_source: str = ""
    # Namespaces the legacy game_id space (ordinal * 1_000_000 + year * 100 +
    # game_num), so it must be globally unique among the schools that have one.
    # Only the StatCrew lineage builds game_ids; the live collector never reads
    # this field, so a SideArm-only school leaves it 0, meaning unassigned.
    ordinal: int = 0
    gender: str = "men"
    scraper: str = "statcrew"
    # The current schedule/roster site. Historical StatCrew sources use a
    # different host, so Harding supplies this explicitly; SideArm sources can
    # use base_url directly.
    live_base_url: str = ""
    live_scraper: str = ""

    def display(self) -> str:
        """The reader-facing programme name — published spelling over slug source."""
        return self.display_name or self.name

    def build_game_url(self, year: int, game_num: int) -> str:
        """Build a game URL from the template, substituting {year}, {prefix}, {num:02d}."""
        return self.base_url.format(year=year, prefix=self.prefix, num=game_num)

    def live_sport_url(self) -> str:
        """Return the season schedule/roster base, or empty when unknown."""
        if self.live_base_url:
            return self.live_base_url.rstrip("/")
        if "/sports/" in self.base_url and "{" not in self.base_url:
            return self.base_url.rstrip("/")
        return ""

    def live_collector(self) -> str:
        """Return the live-path platform, independently of historical ``scraper``.

        ``scraper`` identifies the historical box-score platform. ``live_scraper``
        overrides the live collector and defaults to SideArm-new.
        """
        return self.live_scraper or DEFAULT_LIVE_COLLECTOR


def _read_point(entry: dict) -> tuple[float, float] | None:
    """The stanza's ``point`` table as (lat, lon), validated at load.

    A point is a coordinate pair for a town the Gazetteer does not cover;
    the loader checks its shape and range, and that the stanza says where
    the pair was read, so a malformed pin never reaches the build. Whether
    the Gazetteer does cover the town is the build's question, not this one.
    """
    raw = entry.get("point")
    if raw is None:
        return None
    label = f"School '{entry.get('name', '?')}' ({entry.get('abbreviation', '?')})"
    if (
        not isinstance(raw, dict)
        or set(raw) != {"lat", "lon"}
        or any(
            isinstance(raw[k], bool) or not isinstance(raw[k], (int, float))
            for k in raw
        )
    ):
        raise ValueError(
            f"{label}: point must be a table {{ lat = <float>, lon = <float> }} "
            "in decimal degrees"
        )
    lat, lon = float(raw["lat"]), float(raw["lon"])
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(
            f"{label}: point ({lat}, {lon}) is outside the range of decimal degrees"
        )
    if not str(entry.get("point_source", "")).strip():
        raise ValueError(
            f"{label}: point needs point_source saying where the coordinates were read"
        )
    if entry.get("gazetteer_geoid"):
        raise ValueError(
            f"{label}: point and gazetteer_geoid are alternatives: a GEOID pin "
            "names a Gazetteer place, a point stands in for a town the "
            "Gazetteer does not cover"
        )
    return (lat, lon)


def load_schools(path: str | Path = DEFAULT_CONFIG) -> list[SchoolConfig]:
    """Load school configurations from a TOML file.

    Raises ``FileNotFoundError`` if the file doesn't exist.
    Raises ``ValueError`` if an enabled school has an empty ``base_url``, if
    two schools share an assigned ordinal, if two enabled stanzas of one
    gender mint the same programme slug, or if a stanza's ``point`` is
    malformed, out of range, unsourced, or beside a GEOID pin.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    schools: list[SchoolConfig] = []
    for entry in data.get("schools", []):
        school = SchoolConfig(
            name=entry["name"],
            display_name=entry.get("display_name", ""),
            abbreviation=entry["abbreviation"],
            conference=entry.get("conference", ""),
            prefix=entry.get("prefix", ""),
            base_url=entry.get("base_url", ""),
            years=entry.get("years", []),
            enabled=entry.get("enabled", False),
            data_status=entry.get("data_status", "unverified"),
            notes=entry.get("notes", ""),
            mascot=entry.get("mascot", ""),
            aliases=entry.get("aliases", []),
            abbreviation_resolves=entry.get("abbreviation_resolves", True),
            member_aliases=entry.get("member_aliases", []),
            first_season=int(entry.get("first_season", 0)),
            city=entry.get("city", ""),
            city_source=entry.get("city_source", ""),
            identity_accessed=entry.get("identity_accessed", ""),
            gazetteer_geoid=entry.get("gazetteer_geoid", ""),
            gazetteer_note=entry.get("gazetteer_note", ""),
            point=_read_point(entry),
            point_source=entry.get("point_source", ""),
            ordinal=entry.get("ordinal", 0),
            gender=entry.get("gender", "men"),
            scraper=entry.get("scraper", "statcrew"),
            live_base_url=entry.get("live_base_url", ""),
            live_scraper=entry.get("live_scraper", ""),
        )
        if school.enabled and not school.base_url:
            raise ValueError(
                f"School '{school.name}' ({school.abbreviation}) is enabled "
                f"but has no base_url configured"
            )
        schools.append(school)

    # Ordinal 0 means unassigned, and any number of schools may be unassigned:
    # only the StatCrew lineage builds game_ids from it. Validating assigned
    # ordinals alone is what lets a new conference of SideArm-only schools be
    # added anywhere in the file. The previous default was the entry's file
    # position, which silently manufactured a collision with an explicitly
    # numbered school whenever an entry was inserted rather than appended.
    seen_ordinals: dict[int, str] = {}
    for s in schools:
        if not s.ordinal:
            continue
        if s.ordinal in seen_ordinals:
            raise ValueError(
                f"Duplicate ordinal {s.ordinal}: '{s.abbreviation}' and "
                f"'{seen_ordinals[s.ordinal]}'. Ordinals namespace the legacy "
                f"game_id space and must be unique; the next free value is "
                f"{max(seen_ordinals) + 1}. Leave it unset for a school the "
                f"StatCrew lineage never reads."
            )
        seen_ordinals[s.ordinal] = s.abbreviation

    # The slug ``name`` mints keys every per-programme map the collect builds
    # (candidates, coverage cells, membership windows, the programmes
    # reference), each of them a dict that would keep the later stanza and
    # drop the earlier one without a word. A men's and a women's stanza of one
    # school share a slug on purpose, so the identity is (gender, slug), and a
    # disabled stanza takes part in no map, so only enabled ones are checked.
    seen_slugs: dict[tuple[str, str], SchoolConfig] = {}
    for s in schools:
        if not s.enabled:
            continue
        key = (s.gender, programme_slug(s.name))
        if key in seen_slugs:
            other = seen_slugs[key]
            raise ValueError(
                f"Duplicate programme slug '{key[1]}' ({s.gender}): "
                f"'{s.name}' ({s.abbreviation}, {s.conference}) and "
                f"'{other.name}' ({other.abbreviation}, {other.conference}) "
                f"both mint it. Two institutions of one name each need their "
                f"own slug: qualify name the way opponent text already does "
                f'("Lincoln Memorial" beside "Lincoln") and carry the '
                f"published spelling in display_name."
            )
        seen_slugs[key] = s

    return schools
