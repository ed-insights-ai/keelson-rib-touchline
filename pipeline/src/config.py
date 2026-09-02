"""School configuration loader — reads config/schools.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "schools.toml"
DEFAULT_LIVE_COLLECTOR = "sidearm"


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
    # already the published name. Use ``display()`` to resolve.
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


def load_schools(path: str | Path = DEFAULT_CONFIG) -> list[SchoolConfig]:
    """Load school configurations from a TOML file.

    Raises ``FileNotFoundError`` if the file doesn't exist.
    Raises ``ValueError`` if an enabled school has an empty ``base_url``.
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
            city=entry.get("city", ""),
            city_source=entry.get("city_source", ""),
            identity_accessed=entry.get("identity_accessed", ""),
            gazetteer_geoid=entry.get("gazetteer_geoid", ""),
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

    return schools
