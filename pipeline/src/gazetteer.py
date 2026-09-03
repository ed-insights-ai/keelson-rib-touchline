"""Resolve a programme's town to one U.S. Census Gazetteer place.

The Gazetteer is the source for a programme's point (the town centroid the
site's Footprint band plots). The 2023 Places file is pinned: a refresh is
a deliberate contract bump recorded in ``contracts/CHANGELOG.md``, never a
drift the build picks up on its own.

Two files are read, in a fixed order. The Places file (incorporated places
and CDPs) is always the first lookup. The County Subdivisions file (New
England towns, New Jersey townships, New York towns and the like, which the
Places file does not carry) is consulted only when the Places file has no
match at all: a town with two Places candidates is still an ambiguity to
pin, never a reason to read the second file. A row resolved through the
second file is flagged ``cousub`` so its provenance can name that file.

Each file has two copies. ``pipeline/data/gazetteer/2023_Gaz_place_trimmed.txt``
and ``2023_Gaz_cousubs_trimmed.txt`` are the offline fixtures: the rows every
published programme resolved to, in the Census file's own tab-separated
layout, so tests and a deterministic rebuild need no network. The full
national file is fetched once into a cache directory only when a town is not
in the fixture (a new programme), and the row it resolves to is appended to
the fixture by the build script. The county-subdivisions file has no LSAD
column and pads every line with spaces; both are tolerated on read.

Resolution rules (ratified on tl-891, 2026-09-02; the county-subdivisions
fallback ruled 2026-09-02): a town string resolves to exactly one place or
the build fails naming the candidates. Incorporated places outrank CDPs; a
pinned GEOID wins outright but must name a place in the same state whose
name begins with the town, otherwise the pin is wrong and the build fails
saying so. A pin may be either file's GEOID: place GEOIDs are 7 digits and
county-subdivision GEOIDs 10, so the two never collide.
"""

from __future__ import annotations

import csv
import io
import os
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

GAZETTEER_VINTAGE = 2023
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2023_Gazetteer/2023_Gaz_place_national.zip"
)
GAZETTEER_SOURCE = "U.S. Census Bureau, 2023 Gazetteer Files (Places, national)"
#: The Last-Modified date the Census server reports for the pinned file.
GAZETTEER_FILE_DATE = "2023-09-26"
GAZETTEER_MEMBER = "2023_Gaz_place_national.txt"
_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "data" / "gazetteer"
TRIMMED_FIXTURE = _FIXTURE_DIR / "2023_Gaz_place_trimmed.txt"
PLACES_HEADER = (
    "USPS\tGEOID\tANSICODE\tNAME\tLSAD\tFUNCSTAT\tALAND\tAWATER"
    "\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG"
)

#: The second source: county subdivisions, read only when the places file
#: has no match. Same vintage, same layout minus the LSAD column.
COUSUBS_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2023_Gazetteer/2023_Gaz_cousubs_national.zip"
)
COUSUBS_SOURCE = (
    "U.S. Census Bureau, 2023 Gazetteer Files (County Subdivisions, national)"
)
#: The Last-Modified date the Census server reports for the pinned file
#: (Tue, 26 Sep 2023 13:32:25 GMT, read 2026-09-02).
COUSUBS_FILE_DATE = "2023-09-26"
COUSUBS_MEMBER = "2023_Gaz_cousubs_national.txt"
TRIMMED_COUSUBS_FIXTURE = _FIXTURE_DIR / "2023_Gaz_cousubs_trimmed.txt"
COUSUBS_HEADER = (
    "USPS\tGEOID\tANSICODE\tNAME\tFUNCSTAT\tALAND\tAWATER"
    "\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG"
)
CDP_LSAD = "57"

#: AP-style state abbreviations (and the eight states AP spells out) to USPS.
AP_TO_USPS = {
    "Ala.": "AL", "Alaska": "AK", "Ariz.": "AZ", "Ark.": "AR", "Calif.": "CA",
    "Colo.": "CO", "Conn.": "CT", "Del.": "DE", "D.C.": "DC", "Fla.": "FL",
    "Ga.": "GA", "Hawaii": "HI", "Idaho": "ID", "Ill.": "IL", "Ind.": "IN",
    "Iowa": "IA", "Kan.": "KS", "Ky.": "KY", "La.": "LA", "Maine": "ME",
    "Md.": "MD", "Mass.": "MA", "Mich.": "MI", "Minn.": "MN", "Miss.": "MS",
    "Mo.": "MO", "Mont.": "MT", "Neb.": "NE", "Nev.": "NV", "N.H.": "NH",
    "N.J.": "NJ", "N.M.": "NM", "N.Y.": "NY", "N.C.": "NC", "N.D.": "ND",
    "Ohio": "OH", "Okla.": "OK", "Ore.": "OR", "Pa.": "PA", "R.I.": "RI",
    "S.C.": "SC", "S.D.": "SD", "Tenn.": "TN", "Texas": "TX", "Utah": "UT",
    "Vt.": "VT", "Va.": "VA", "Wash.": "WA", "W.Va.": "WV", "Wis.": "WI",
    "Wyo.": "WY",
}  # fmt: skip
USPS_TO_AP = {usps: ap for ap, usps in AP_TO_USPS.items()}
STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}  # fmt: skip

_TOWN_STATE = re.compile(r"^\s*([^,/]+?)\s*,\s*([A-Za-z. ]+?)\s*(?:/.*)?$")


class GazetteerError(ValueError):
    """A town that does not resolve to exactly one pinned-vintage place."""


@dataclass(frozen=True)
class Place:
    geoid: str
    name: str
    state: str
    lsad: str
    lat: float
    lon: float
    row: dict[str, str]
    #: True when the row came from the county-subdivisions file.
    cousub: bool = False

    @property
    def incorporated(self) -> bool:
        return self.lsad != CDP_LSAD


@dataclass(frozen=True)
class Town:
    """A town string reduced to its parts: "Alva, Oklahoma" -> Alva / OK."""

    name: str
    usps: str

    @property
    def ap(self) -> str:
        """The AP-style spelling the contract carries: "Alva, Okla."."""
        return f"{self.name}, {USPS_TO_AP[self.usps]}"


def parse_town(text: str) -> Town | None:
    """Read "Town, ST" / "Town, St." / "Town, State" from published location text.

    A trailing "/ Venue" (ECU prints "Ada, OK / Tiger Soccer Field") is
    dropped. Anything that is not a town and a recognisable state is None:
    the caller decides whether that is a gap or a failure.
    """
    match = _TOWN_STATE.match(text or "")
    if not match:
        return None
    name, state = match.group(1).strip(), match.group(2).strip()
    usps = (
        AP_TO_USPS.get(state)
        or STATE_NAMES.get(state)
        or (state.upper() if len(state) == 2 and state.isalpha() else None)
    )
    if not usps or usps not in USPS_TO_AP:
        return None
    return Town(name=name, usps=usps)


def _norm(text: str) -> str:
    text = text.lower().replace("saint ", "st. ").replace("st ", "st. ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _place(row: dict[str, str], *, cousub: bool = False) -> Place:
    # The county-subdivisions file has no LSAD column; an empty LSAD is not
    # a CDP, so such a row ranks as incorporated.
    return Place(
        geoid=row["GEOID"].strip(),
        name=row["NAME"].strip(),
        state=row["USPS"].strip(),
        lsad=(row.get("LSAD") or "").strip(),
        lat=round(float(row["INTPTLAT"]), 4),
        lon=round(float(row["INTPTLONG"]), 4),
        row={k.strip(): (v or "").strip() for k, v in row.items() if k is not None},
        cousub=cousub,
    )


def read_places(text: str, *, cousub: bool = False) -> list[Place]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    reader.fieldnames = [f.strip() for f in reader.fieldnames or []]
    return [_place(row, cousub=cousub) for row in reader]


def read_cousubs(text: str) -> list[Place]:
    return read_places(text, cousub=True)


def _header_and_lines(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    return lines[0].rstrip(), lines[1:]


def cache_dir() -> Path:
    override = os.environ.get("TOUCHLINE_GAZETTEER_CACHE")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "touchline" / "gazetteer"


def full_file_path() -> Path:
    override = os.environ.get("TOUCHLINE_GAZETTEER_FILE")
    return Path(override) if override else cache_dir() / GAZETTEER_MEMBER


def full_cousubs_path() -> Path:
    override = os.environ.get("TOUCHLINE_GAZETTEER_COUSUBS_FILE")
    return Path(override) if override else cache_dir() / COUSUBS_MEMBER


def _fetch(target: Path, url: str, member: str) -> Path:
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        text = archive.read(member).decode("utf-8")
    target.write_text(text, encoding="utf-8")
    return target


def fetch_full_file() -> Path:
    """Download the pinned national places file into the cache once."""
    return _fetch(full_file_path(), GAZETTEER_URL, GAZETTEER_MEMBER)


def fetch_full_cousubs_file() -> Path:
    """Download the pinned national county-subdivisions file into the cache once."""
    return _fetch(full_cousubs_path(), COUSUBS_URL, COUSUBS_MEMBER)


class Gazetteer:
    """Places from the trimmed fixtures, widened to the full files on demand.

    Places first, always; county subdivisions only when places has no match.
    """

    def __init__(
        self,
        places: list[Place],
        *,
        header: str,
        fetch_full: bool = True,
        cousubs: list[Place] | None = None,
        cousubs_header: str = COUSUBS_HEADER,
    ) -> None:
        self._places = list(places)
        self._header = header
        self._cousubs = list(cousubs or [])
        self._cousubs_header = cousubs_header
        self._fetch_full = fetch_full
        self._full_loaded = False
        self._cousubs_loaded = False
        self.used: dict[str, Place] = {}

    @classmethod
    def load(
        cls,
        fixture: Path = TRIMMED_FIXTURE,
        *,
        fetch_full: bool = True,
        cousubs_fixture: Path = TRIMMED_COUSUBS_FIXTURE,
    ) -> Gazetteer:
        if fixture.exists():
            text = fixture.read_text(encoding="utf-8")
        else:
            text = PLACES_HEADER + "\n"
        header, _ = _header_and_lines(text)
        if cousubs_fixture.exists():
            cousubs_text = cousubs_fixture.read_text(encoding="utf-8")
        else:
            cousubs_text = COUSUBS_HEADER + "\n"
        cousubs_header, _ = _header_and_lines(cousubs_text)
        return cls(
            read_places(text),
            header=header,
            fetch_full=fetch_full,
            cousubs=read_cousubs(cousubs_text),
            cousubs_header=cousubs_header,
        )

    def _widen(self) -> None:
        if self._full_loaded or not self._fetch_full:
            return
        self._full_loaded = True
        text = fetch_full_file().read_text(encoding="utf-8")
        known = {p.geoid for p in self._places}
        self._places.extend(p for p in read_places(text) if p.geoid not in known)

    def _widen_cousubs(self) -> None:
        if self._cousubs_loaded or not self._fetch_full:
            return
        self._cousubs_loaded = True
        text = fetch_full_cousubs_file().read_text(encoding="utf-8")
        known = {p.geoid for p in self._cousubs}
        self._cousubs.extend(p for p in read_cousubs(text) if p.geoid not in known)

    @staticmethod
    def _matching(rows: list[Place], town: Town) -> list[Place]:
        key = _norm(town.name)
        return [p for p in rows if p.state == town.usps and _name_matches(key, p.name)]

    def _candidates(self, town: Town) -> list[Place]:
        return self._matching(self._places, town)

    def _cousub_candidates(self, town: Town) -> list[Place]:
        return self._matching(self._cousubs, town)

    def _find_pin(self, pin: str) -> Place | None:
        # Place GEOIDs are 7 digits and county-subdivision GEOIDs 10, so a
        # pin names at most one row across both files; places is searched
        # first regardless, keeping the places-first rule.
        for rows in (self._places, self._cousubs):
            hit = next((p for p in rows if p.geoid == pin), None)
            if hit is not None:
                return hit
        return None

    def _resolve_pin(self, town: Town, pin: str) -> Place:
        hit = self._find_pin(pin)
        if hit is None:
            self._widen()
            hit = self._find_pin(pin)
        if hit is None:
            self._widen_cousubs()
            hit = self._find_pin(pin)
        if hit is None:
            raise GazetteerError(
                f"{town.ap}: pinned GEOID {pin} is not in the {GAZETTEER_VINTAGE} Gazetteer "
                "(neither the places file nor the county subdivisions file)"
            )
        if hit.state != town.usps or not _prefix_matches(_norm(town.name), hit.name):
            raise GazetteerError(
                f"{town.ap}: pinned GEOID {pin} names {hit.name!r} ({hit.state}), "
                "not the town in the city string"
            )
        return hit

    @staticmethod
    def _choose(found: list[Place]) -> list[Place]:
        incorporated = [p for p in found if p.incorporated]
        return incorporated or found

    def resolve(self, town: Town, *, pin: str = "") -> Place:
        """Exactly one place for the town, or a GazetteerError that names why."""
        if pin:
            hit = self._resolve_pin(town, pin)
            self.used[hit.geoid] = hit
            return hit
        # Places first: the fixture, then the full file. Only when neither
        # has a single candidate does the county-subdivisions file get read.
        chosen = self._choose(self._candidates(town))
        if not chosen:
            self._widen()
            chosen = self._choose(self._candidates(town))
        if not chosen:
            chosen = self._choose(self._cousub_candidates(town))
            if not chosen:
                self._widen_cousubs()
                chosen = self._choose(self._cousub_candidates(town))
        if len(chosen) == 1:
            self.used[chosen[0].geoid] = chosen[0]
            return chosen[0]
        if len(chosen) > 1:
            names = ", ".join(f"{p.geoid} {p.name}" for p in chosen)
            which = "county subdivisions" if chosen[0].cousub else "places"
            raise GazetteerError(
                f"{town.ap}: {len(chosen)} {GAZETTEER_VINTAGE} Gazetteer {which} match, "
                f"pin one with gazetteer_geoid: {names}"
            )
        raise GazetteerError(
            f"{town.ap}: no {GAZETTEER_VINTAGE} Gazetteer place in {town.usps} is named "
            f"{town.name!r} in the places file or the county subdivisions file: check "
            "the spelling, or pin a consolidated place with gazetteer_geoid"
        )

    @staticmethod
    def _rows_text(header: str, places: list[Place]) -> str:
        rows = [header]
        for place in sorted(places, key=lambda p: p.geoid):
            rows.append(
                "\t".join(place.row.get(col.strip(), "") for col in header.split("\t"))
            )
        return "\n".join(rows) + "\n"

    def trimmed_text(self, places: dict[str, Place]) -> str:
        """The places fixture text for the given rows, in GEOID order."""
        return self._rows_text(
            self._header, [p for p in places.values() if not p.cousub]
        )

    def trimmed_cousubs_text(self, places: dict[str, Place]) -> str:
        """The county-subdivisions fixture text for the given rows, in GEOID order."""
        return self._rows_text(
            self._cousubs_header, [p for p in places.values() if p.cousub]
        )


_DESCRIPTORS = (
    "city", "town", "village", "borough", "cdp", "municipality", "consolidated government",
    "metropolitan government", "urban county", "metro government", "comunidad", "zona urbana",
    "corporation", "city and borough", "plantation", "unified government", "government",
    "(balance)",
    # County-subdivision descriptors (townships, census county divisions,
    # unorganized territories, Puerto Rico barrios, New England grants).
    "township", "ccd", "ut", "barrio", "barrio-pueblo", "unorganized territory",
    "gore", "grant", "purchase", "location", "reservation",
)  # fmt: skip


def _stem(name: str) -> str:
    """ "Indianapolis city (balance)" -> "indianapolis"; "St. Leo town" -> "st leo".

    One descriptor comes off the end (after a "(balance)" suffix), never
    more: "Kansas City city" is the place named Kansas City.
    """
    key = _norm(name)
    if key.endswith(" balance"):
        key = key[: -len(" balance")].strip()
    for word in sorted((_norm(d) for d in _DESCRIPTORS), key=len, reverse=True):
        if word and key.endswith(" " + word):
            return key[: -len(word) - 1].strip()
    return key


def _name_matches(town_key: str, place_name: str) -> bool:
    return _stem(place_name) == town_key


def _prefix_matches(town_key: str, place_name: str) -> bool:
    stem = _stem(place_name)
    return (
        stem == town_key
        or stem.startswith(town_key + " ")
        or stem.startswith(town_key + "-")
    )
