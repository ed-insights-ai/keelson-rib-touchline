"""Women's "Mary" is the University of Mary, not Maryville.

Measured 2026-11-16 by replaying the 2,313 archived Division II schedule
pages. "Mary" and "University of Mary" fold to "mary", the key the GLVC
Maryville women's resolving abbreviation "MARY" claimed, while UMary's long
name was a member alias that reached it outside the NSIC only through the
distance tiebreak. Four MIAA/GLIAC rows broke the tie toward Maryville; each
links goumary.com and has its twin on UMary's own page the same day:

- central-missouri 2023-09-10 "Mary" at Mankato
- grand-valley-state 2023-09-08 "Mary" at Mankato
- emporia-state 2024-09-15 "University of Mary" at Bismarck
- washburn 2025-09-14 "University of Mary" at Yager Stadium

The women's "MARY" no longer resolves and the long name is a plain alias:
the replay changes exactly those four sides, maryville -> umary.
"""

from __future__ import annotations

import pytest

from scripts.collect_board import collect_identity
from src.config import load_schools
from src.membership import load_membership
from src.programmes import load_programmes, programme_points
from src.sidearm_live import opponent_slug


@pytest.fixture(scope="module")
def identity():
    schools = load_schools()
    document = load_membership()
    points = programme_points(load_programmes())
    cache: dict[tuple[str, str, int, str], tuple[dict[str, str], object]] = {}

    def resolve(
        printed: str, owner: str, conference: str, season: int, gender: str
    ) -> str:
        key = (gender, conference, season, owner)
        if key not in cache:
            aliases, _, scope = collect_identity(
                schools,
                gender,
                conference,
                season,
                document=document,
                points=points,
                programmes=(owner,),
            )
            cache[key] = (aliases, scope)
        aliases, scope = cache[key]
        return opponent_slug(printed, aliases, scope=scope, owner=owner)  # type: ignore[arg-type]

    return resolve


CASES = [
    # The four rows that read as Maryville.
    ("Mary", "central-missouri", "MIAA", 2023, "women", "umary"),
    ("Mary", "grand-valley-state", "GLIAC", 2023, "women", "umary"),
    ("University of Mary", "emporia-state", "MIAA", 2024, "women", "umary"),
    ("University of Mary", "washburn", "MIAA", 2025, "women", "umary"),
    # Already UMary's, and still: inside the NSIC and by the old tiebreak.
    ("University of Mary", "minot-state", "NSIC", 2024, "women", "umary"),
    ("Mary", "bemidji-state", "NSIC", 2024, "women", "umary"),
    ("University of Mary", "montana-state-billings", "GNAC", 2025, "women", "umary"),
    ("UMary", "augustana", "NSIC", 2024, "women", "umary"),
    # Maryville's own spellings are untouched.
    ("Maryville", "missouri-st-louis", "GLVC", 2024, "women", "maryville"),
    ("Maryville University", "quincy", "GLVC", 2024, "women", "maryville"),
    ("Maryville (Mo.)", "ferris-state", "GLIAC", 2024, "women", "maryville"),
    # The men's "MARY" still resolves; no UMary men's stanza claims the key,
    # and the printed state still moves "Mary (N.D.)" off Maryville.
    ("MARY", "lewis", "GLVC", 2024, "men", "maryville"),
    ("Mary (N.D.)", "southern-nazarene", "GAC", 2016, "men", "mary-nd"),
]


@pytest.mark.parametrize(
    ("printed", "owner", "conference", "season", "gender", "slug"), CASES
)
def test_mary_reads_as_the_university_of_mary_on_womens_pages(
    identity,
    printed: str,
    owner: str,
    conference: str,
    season: int,
    gender: str,
    slug: str,
) -> None:
    assert identity(printed, owner, conference, season, gender) == slug


def test_the_womens_maryville_abbreviation_does_not_resolve() -> None:
    maryville = {
        school.gender: school for school in load_schools() if school.name == "Maryville"
    }
    assert maryville["women"].abbreviation_resolves is False
    assert maryville["men"].abbreviation_resolves is True
    umary = next(s for s in load_schools() if s.name == "UMary")
    assert "University of Mary" in umary.aliases
    assert "University of Mary" not in umary.member_aliases
