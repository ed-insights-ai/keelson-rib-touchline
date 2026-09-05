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
row's point provenance names that file and carries a note. A town the
Gazetteer covers nowhere (Burnaby, B.C.) takes the stanza's own ``point``,
and only then: a point on a town the Gazetteer resolves is refused. The document's
``gazetteer`` block keeps describing the places file. The file is rebuilt
with ``uv run build-programmes`` and must equal a fresh build byte for byte.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import gazetteer as gz
from . import paths
from .config import SchoolConfig
from .sidearm_live import programme_slug

PROGRAMMES_SCHEMA = "touchline.programmes/2"
CITY_SOURCE_SCHEDULE = "schedule-page home venue location"
COUSUB_NOTE = "county subdivision; the places file has no entry for this town"
POINT_NOTE = (
    "stanza point: the Gazetteer covers no place for this town, so the point "
    "is the stanza's own, read from point_source"
)

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


def load_programmes(path: str | Path | None = None) -> dict[str, object]:
    """Load the built programmes reference.

    With no explicit ``path`` the rib's packaged copy is preferred, as
    ``load_membership`` prefers its packaged membership.json, and the data
    home's mirror is the fallback for an install that ships no packaged data
    tree.
    """
    if path is not None:
        programmes_path = Path(path)
        if not programmes_path.exists():
            raise FileNotFoundError(f"Programmes file not found: {programmes_path}")
    else:
        packaged = paths.packaged_programmes_path()
        programmes_path = packaged if packaged.exists() else paths.programmes_path()
        if not programmes_path.exists():
            raise FileNotFoundError(
                "Programmes file not found: no packaged copy at "
                f"{packaged} and no data home copy at {programmes_path}"
            )
    with programmes_path.open(encoding="utf-8") as programmes_file:
        document = json.load(programmes_file)
    if not isinstance(document, dict):
        raise ValueError("programmes.json root must be a JSON object")
    return document


def programme_points(document: dict[str, object]) -> dict[str, tuple[float, float]]:
    """Every programme's point, by slug, as (lat, lon) in decimal degrees.

    A row with no usable point is left out rather than guessed, so a lookup
    that misses says the programme has no point.
    """
    rows = document.get("programmes")
    points: dict[str, tuple[float, float]] = {}
    if not isinstance(rows, dict):
        return points
    for slug, row in rows.items():
        point = row.get("point") if isinstance(row, dict) else None
        if not isinstance(point, dict):
            continue
        lat, lon = point.get("lat"), point.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            points[str(slug)] = (float(lat), float(lon))
    return points


@dataclass
class Build:
    document: dict[str, object]
    used_places: dict[str, gz.Place] = field(default_factory=dict)


def _row(
    school: SchoolConfig, place: gz.Place | None, town: gz.Town | None
) -> dict[str, object]:
    """One row. ``place`` is None only for a stanza whose own ``point`` stands
    in for a town the Gazetteer does not cover; then the city is carried as
    the stanza prints it and the point's provenance is the stanza's
    ``point_source``, with no GEOID."""
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
    if place is None:
        assert school.point is not None
        lat, lon = school.point
        point_source: dict[str, object] = {
            "source": school.point_source,
            "accessed": accessed,
            "note": POINT_NOTE,
        }
        city = town.ap if town is not None else school.city
    else:
        assert town is not None
        lat, lon = place.lat, place.lon
        city = town.ap
        point_source = {
            "source": gz.COUSUBS_SOURCE if place.cousub else gz.GAZETTEER_SOURCE,
            "url": gz.COUSUBS_URL if place.cousub else gz.GAZETTEER_URL,
            "geoid": place.geoid,
            "name": place.name,
            "state": place.state,
            "accessed": gz.COUSUBS_FILE_DATE
            if place.cousub
            else gz.GAZETTEER_FILE_DATE,
        }
    notes: list[str] = []
    if place is not None and school.gazetteer_geoid:
        notes.append(
            f"matched explicitly by GEOID: the programme prints {town.name!r} and the "
            f"Gazetteer lists the place as {place.name!r}"
        )
    if place is not None and place.cousub:
        notes.append(COUSUB_NOTE)
    if school.gazetteer_note:
        notes.append(school.gazetteer_note.strip())
    if notes:
        point_source["note"] = "; ".join(notes)
    row: dict[str, object] = {
        "name": school.display(),
        "nickname": school.mascot,
        "abbreviation": school.abbreviation,
        "city": city,
        "point": {"lat": lat, "lon": lon},
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
        if school.point is not None:
            # The stanza's own point stands in only where the Gazetteer has
            # nothing: a town outside the United States parses to no state
            # at all, and a US town the files lack resolves to no candidate.
            # A city the Gazetteer does resolve, to one place or several, is
            # refused: the pin would otherwise override a real place in
            # silence, and a several-place town wants gazetteer_geoid.
            found = gazetteer.candidates(town) if town is not None else []
            if found:
                names = ", ".join(f"{p.geoid} {p.name}" for p in found)
                problems.append(
                    f"{slug}: point refused: the {gz.GAZETTEER_VINTAGE} Gazetteer "
                    f"resolves {school.city!r} ({names}); drop point, or pin one "
                    "of them with gazetteer_geoid"
                )
                continue
            rows[slug] = _row(school, None, town)
            continue
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
