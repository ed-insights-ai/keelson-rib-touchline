"""Build the programmes reference: identity per programme slug, with provenance.

Contract ``touchline.programmes/2`` (contracts/programmes-2.json). Every
row carries the facts the site needs to name and place a programme —
name, nickname, abbreviation, town, point — and, beside each fact, where it
came from and when it was read. Nothing here is guessed from a slug: a
stanza that cannot complete a row stops the build naming the slug.

The facts come from ``pipeline/config/schools.toml`` (name, mascot,
abbreviation, city, city_source, identity_accessed, gazetteer_geoid,
gazetteer_note) and
the pinned Gazetteer (src/gazetteer.py): the places file first, the county
subdivisions file only for a town the places file lacks, in which case the
row's point provenance names that file and carries a note. The document's
``gazetteer`` block keeps describing the places file. The file is rebuilt
with ``uv run build-programmes`` and must equal a fresh build byte for byte.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import gazetteer as gz
from .config import SchoolConfig
from .sidearm_live import programme_slug

PROGRAMMES_SCHEMA = "touchline.programmes/2"
CITY_SOURCE_SCHEDULE = "schedule-page home venue location"
COUSUB_NOTE = "county subdivision; the places file has no entry for this town"

DESCRIPTION = (
    "Programme identity that no collected page publishes as data: the nickname "
    "a programme goes by, the town it plays in, and that town's point. One row "
    "per programme slug, gender-free; every fact carries its provenance and "
    "the date it was read. Built from pipeline/config/schools.toml and the "
    "pinned 2023 Census Gazetteer by `uv run build-programmes`; never edited "
    "by hand. Sibling in role to membership.json — identity, membership and "
    "results are separate axes."
)


class ProgrammeError(ValueError):
    """A stanza that cannot complete a row."""


@dataclass
class Build:
    document: dict[str, object]
    used_places: dict[str, gz.Place] = field(default_factory=dict)


def _row(school: SchoolConfig, place: gz.Place, town: gz.Town) -> dict[str, object]:
    live = school.live_sport_url() or school.base_url
    accessed = school.identity_accessed
    city_source: dict[str, object] = {
        "source": school.city_source or CITY_SOURCE_SCHEDULE,
        "accessed": accessed,
    }
    if not school.city_source or school.city_source == CITY_SOURCE_SCHEDULE:
        city_source["url"] = (
            f"{live}/schedule/{max(school.years)}" if school.years else live
        )
    point_source: dict[str, object] = {
        "source": gz.COUSUBS_SOURCE if place.cousub else gz.GAZETTEER_SOURCE,
        "url": gz.COUSUBS_URL if place.cousub else gz.GAZETTEER_URL,
        "geoid": place.geoid,
        "name": place.name,
        "state": place.state,
        "accessed": gz.COUSUBS_FILE_DATE if place.cousub else gz.GAZETTEER_FILE_DATE,
    }
    notes: list[str] = []
    if school.gazetteer_geoid:
        notes.append(
            f"matched explicitly by GEOID: the programme prints {town.name!r} and the "
            f"Gazetteer lists the place as {place.name!r}"
        )
    if place.cousub:
        notes.append(COUSUB_NOTE)
    if school.gazetteer_note:
        notes.append(school.gazetteer_note.strip())
    if notes:
        point_source["note"] = "; ".join(notes)
    row: dict[str, object] = {
        "name": school.display(),
        "nickname": school.mascot,
        "abbreviation": school.abbreviation,
        "city": town.ap,
        "point": {"lat": place.lat, "lon": place.lon},
        "provenance": {
            "nickname": {
                "source": "schools.toml mascot, as the site names itself",
                "url": live,
                "accessed": accessed,
            },
            "abbreviation": {
                "source": "schools.toml abbreviation, the site's own short form",
                "url": live,
                "accessed": accessed,
            },
            "city": city_source,
            "point": point_source,
        },
    }
    return row


def build(schools: list[SchoolConfig], gazetteer: gz.Gazetteer) -> Build:
    """One row per enabled programme slug, sorted; every failure named."""
    problems: list[str] = []
    rows: dict[str, dict[str, object]] = {}
    seen: dict[str, SchoolConfig] = {}
    for school in schools:
        if not school.enabled:
            continue
        slug = programme_slug(school.name)
        if slug in seen:
            # A women's stanza sharing a men's slug shares the row; the first
            # enabled stanza (config order) supplies it.
            continue
        seen[slug] = school
        missing = [
            f
            for f, v in (
                ("mascot", school.mascot),
                ("abbreviation", school.abbreviation),
                ("city", school.city),
                ("identity_accessed", school.identity_accessed),
            )
            if not v
        ]
        if missing:
            problems.append(f"{slug}: stanza has no {', '.join(missing)}")
            continue
        town = gz.parse_town(school.city)
        if town is None:
            problems.append(
                f"{slug}: city {school.city!r} is not 'Town, State' with a recognisable state"
            )
            continue
        try:
            place = gazetteer.resolve(
                town, pin=school.gazetteer_geoid, note=school.gazetteer_note
            )
        except gz.GazetteerError as error:
            problems.append(f"{slug}: {error}")
            continue
        rows[slug] = _row(school, place, town)
    if problems:
        raise ProgrammeError(
            "programmes reference cannot be built:\n  " + "\n  ".join(problems)
        )
    document: dict[str, object] = {
        "schema": PROGRAMMES_SCHEMA,
        "description": DESCRIPTION,
        "gazetteer": {
            "source": gz.GAZETTEER_SOURCE,
            "url": gz.GAZETTEER_URL,
            "file_date": gz.GAZETTEER_FILE_DATE,
            "license": "Public domain (work of the U.S. federal government)",
        },
        "programmes": {slug: rows[slug] for slug in sorted(rows)},
    }
    return Build(document=document, used_places=dict(gazetteer.used))


def render(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
