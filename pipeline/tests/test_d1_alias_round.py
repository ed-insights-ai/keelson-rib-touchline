"""The Division I men's 2026 alias round: peer spellings fold onto the programme.

Measured 2026-11-15 over the 213 archived 2026 Division I men's schedule
pages: 228 of 6,182 fixture sides resolved to no Division I programme, and 72
of them were Division I programmes printed under a spelling no stanza
claimed, each confirmed by the opponent link on the printing page or by the
same match on the programme's own page that day. The unambiguous spellings
are stanza aliases; the ones another Division I school could also print
("Loyola", "USF", "CBU", bare "Boston", "Central Florida") are member
aliases, read only inside the programme's own conference.
"""

import pytest

from scripts.collect_board import collect_identity
from src.config import load_schools
from src.membership import load_membership
from src.sidearm_live import opponent_slug

# (printed, the collecting conference whose page printed it, programme)
PEER_SPELLINGS = [
    ("Pittsburgh", "B1G", "pitt"),
    ("University of Pittsburgh", "IVY", "pitt"),
    ("CSU Bakersfield", "MW", "cal-state-bakersfield"),
    ("CSU Bakersfield (Big West Crossover)", "PAC12", "cal-state-bakersfield"),
    ("University of Massachusetts Lowell", "AE", "umass-lowell"),
    ("Massachusetts-Lowell", "PATRIOT", "umass-lowell"),
    ("Cal Baptist", "WCC", "california-baptist"),
    ("UT Rio Grande Valley", "OVC", "utrgv"),
    ("Southern Methodist University", "ACC", "smu"),
    ("University of Nebraska at Omaha", "IVY", "omaha"),
    ("Nebraska at Omaha", "SUMMIT", "omaha"),
    ("Cal St. Fullerton", "WCC", "cal-state-fullerton"),
    ("California State Fullerton", "PAC12", "cal-state-fullerton"),
    ("CSU Fullerton", "PAC12", "cal-state-fullerton"),
    ("UMKC", "ACC", "kansas-city"),
    ("Albany", "IVY", "ualbany"),
    ("Loyola Md.", "PATRIOT", "loyola-maryland"),
    ("Coastal Caro.", "SUNBELT", "coastal-carolina"),
    ("Western Mich.", "WCC", "western-michigan"),
    ("Cal State Northridge", "OVC", "csun"),
    # Member aliases, inside the programme's own conference.
    ("Loyola", "PATRIOT", "loyola-maryland"),
    ("Loyola (Md.)", "PATRIOT", "loyola-maryland"),
    ("Boston", "PATRIOT", "boston-university"),
    ("USF", "AAC", "south-florida"),
    ("CBU", "PAC12", "california-baptist"),
    ("Central Florida", "SUNBELT", "ucf"),
]

# Ambiguous outside the conference that reads them one way: they stay the
# text's own slug rather than guess (Loyola Chicago on Horizon, OVC and MVC
# pages; South Florida on ASUN and Sun Belt pages; Queen's and Santa Barbara
# City by the fold).
STAY_STRANGERS = [
    ("Loyola", "MVC", "loyola"),
    ("Loyola (Ill.)", "OVC", "loyola"),
    ("Loyola (Md.)", "AE", "loyola"),
    ("USF", "ASUN", "usf"),
    ("Boston", "ACC", "boston"),
    ("CBU", "WCC", "cbu"),
    ("Santa Barbara", "WCC", "santa-barbara"),
    ("Queens U. (N.C.)", "BIGSOUTH", "queens-u"),
]


@pytest.fixture(scope="module")
def identity():
    schools = load_schools()
    document = load_membership()
    cache: dict[str, tuple[dict[str, str], object]] = {}

    def resolve(printed: str, conference: str) -> str:
        if conference not in cache:
            aliases, _, scope = collect_identity(
                schools, "men", conference, 2026, document=document
            )
            cache[conference] = (aliases, scope)
        aliases, scope = cache[conference]
        return opponent_slug(printed, aliases, scope=scope)  # type: ignore[arg-type]

    return resolve


@pytest.mark.parametrize(("printed", "conference", "slug"), PEER_SPELLINGS)
def test_peer_spelling_resolves_to_the_programme(
    identity, printed: str, conference: str, slug: str
) -> None:
    assert identity(printed, conference) == slug


@pytest.mark.parametrize(("printed", "conference", "slug"), STAY_STRANGERS)
def test_an_ambiguous_spelling_stays_its_own_text(
    identity, printed: str, conference: str, slug: str
) -> None:
    assert identity(printed, conference) == slug
