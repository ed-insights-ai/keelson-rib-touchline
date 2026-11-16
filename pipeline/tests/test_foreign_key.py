"""Text naming a school at another level is never a token subset's capture.

Measured 2026-11-16 by replaying the 848 archived Division I schedule pages:
the token-subset fallback read "Southern New Hampshire" (Dartmouth 2023-2026,
link host snhupenmen.com) and "Southern New Hampshire University"
(Merrimack 2023) as New Hampshire, and "Cal Poly Pomona" (CSUN 2023, San
Diego 2023, link host broncoathletics.com) as Cal Poly. Both are Division II
programmes whose stanzas the Division I table leaves out, so inside it the
longer name holds every token of the shorter one. A key a stanza of the
gender at another level claims whole now mints its own slug; the same
replay over the 2,313 Division II pages changes nothing.

An exact claim is NOT blocked the same way. Measured over the same replay,
511 Division I and 413 Division II sides resolve by exact claim to a key
another level also claims ("SMU", "Notre Dame", "Saint Mary's",
"Charleston", "Queens" at Division I; "Queens College", "University of
Charleston", "St. Mary's", "California (Pa.)" at Division II), and they are
the collecting level's own programmes.
"""

from __future__ import annotations

import pytest

from scripts.collect_board import collect_identity
from src.config import SchoolConfig, load_schools
from src.membership import load_membership
from src.sidearm_live import identity_aliases, opponent_slug, resolution_scope


@pytest.fixture(scope="module")
def identity():
    schools = load_schools()
    document = load_membership()
    cache: dict[tuple[str, int], tuple[dict[str, str], object]] = {}

    def resolve(printed: str, conference: str, season: int) -> str:
        if (conference, season) not in cache:
            aliases, _, scope = collect_identity(
                schools, "men", conference, season, document=document
            )
            cache[(conference, season)] = (aliases, scope)
        aliases, scope = cache[(conference, season)]
        return opponent_slug(printed, aliases, scope=scope)  # type: ignore[arg-type]

    return resolve


@pytest.mark.parametrize(
    ("printed", "conference", "season", "slug"),
    [
        ("Southern New Hampshire", "IVY", 2023, "southern-new-hampshire"),
        ("Southern New Hampshire", "IVY", 2026, "southern-new-hampshire"),
        ("Southern New Hampshire University", "NEC", 2023, "southern-new-hampshire"),
        ("Cal Poly Pomona", "BIGWEST", 2023, "cal-poly-pomona"),
        ("Cal Poly Pomona (Exh)", "WCC", 2023, "cal-poly-pomona"),
    ],
)
def test_another_levels_name_mints_its_own_slug(
    identity, printed: str, conference: str, season: int, slug: str
) -> None:
    assert identity(printed, conference, season) == slug


@pytest.mark.parametrize(
    ("printed", "conference", "season", "slug"),
    [
        # The exact claim still wins over another level's same key.
        ("Charleston", "PATRIOT", 2025, "charleston-south-carolina"),
        ("New Hampshire", "AE", 2025, "new-hampshire"),
        ("Cal Poly", "BIGWEST", 2025, "cal-poly"),
        # A token subset of a name no other level claims still resolves.
        ("Cal Poly San Luis Obispo", "WCC", 2024, "cal-poly"),
    ],
)
def test_the_collecting_levels_own_readings_stand(
    identity, printed: str, conference: str, season: int, slug: str
) -> None:
    assert identity(printed, conference, season) == slug


def _school(name: str, conference: str, **fields: object) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=str(fields.pop("abbreviation", "")),
        conference=conference,
        prefix="",
        base_url="",
        **fields,  # type: ignore[arg-type]
    )


def test_only_a_scope_that_knows_the_other_level_refuses_the_subset() -> None:
    d1 = [_school("New Hampshire", "AE", city="Durham, N.H.")]
    d2 = [_school("Southern New Hampshire", "NE10", aliases=["Southern N.H."])]
    aliases = identity_aliases(d1, "men")
    blind = resolution_scope(d1, "men", set(), conference="AE", season=2025)
    known = resolution_scope(d1, "men", set(), conference="AE", season=2025, outside=d2)
    printed = "Southern New Hampshire"
    assert opponent_slug(printed, aliases, scope=blind) == "new-hampshire"
    assert opponent_slug(printed, aliases, scope=known) == "southern-new-hampshire"
    assert "foreign" in known.fingerprint()
    assert "foreign" not in blind.fingerprint()
