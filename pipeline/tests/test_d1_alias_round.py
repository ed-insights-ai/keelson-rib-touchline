"""The Division I men's alias rounds: peer spellings fold onto the programme.

Measured 2026-11-15 over the 213 archived 2026 Division I men's schedule
pages: 228 of 6,182 fixture sides resolved to no Division I programme, and 72
of them were Division I programmes printed under a spelling no stanza
claimed, each confirmed by the opponent link on the printing page or by the
same match on the programme's own page that day. The unambiguous spellings
are stanza aliases; the ones another Division I school could also print
("Loyola", "USF", "CBU", bare "Boston", "Central Florida") are member
aliases, read only inside the programme's own conference.

The second round, over the 634 archived 2023-2025 pages, adds the spellings
only the history seasons print: IU Indy's old name and its long forms, and
the expanded names a token subset had been reading as North Carolina.
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

# (printed, the collecting conference, season, programme)
HISTORY_SPELLINGS = [
    ("IUPUI", "HORIZON", 2023, "iu-indy"),
    ("Indiana University-Purdue University Indianapolis", "OVC", 2023, "iu-indy"),
    ("IU Indianapolis", "BIGEAST", 2024, "iu-indy"),
    ("Indiana University Indianapolis", "ASUN", 2024, "iu-indy"),
    ("N.C. State", "AAC", 2024, "nc-state"),
    ("North Carolina State", "NEC", 2023, "nc-state"),
    ("North Carolina State University", "ASUN", 2023, "nc-state"),
    ("University of North Carolina Wilmington", "A10", 2024, "uncw"),
    ("SIU Edwardsville", "MVC", 2023, "siue"),
    ("Southern Illinois University Edwardsville", "OVC", 2023, "siue"),
    ("Detroit", "B1G", 2024, "detroit-mercy"),
    ("SeattleU", "WAC", 2023, "seattle-u"),
    ("Virginia Military", "SOCON", 2023, "vmi"),
    ("Fort Wayne", "MVC", 2025, "purdue-fort-wayne"),
    ("Upstate", "ACC", 2024, "usc-upstate"),
    # Member aliases, inside the programme's own conference.
    ("ODU", "SUNBELT", 2023, "old-dominion"),
    ("USF", "WCC", 2023, "san-francisco"),
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
    ("ODU", "ACC", "odu"),
    ("Central Florida", "AAC", "central-florida"),
]


@pytest.fixture(scope="module")
def identity():
    schools = load_schools()
    document = load_membership()
    cache: dict[tuple[str, int], tuple[dict[str, str], object]] = {}

    def resolve(printed: str, conference: str, season: int = 2026) -> str:
        if (conference, season) not in cache:
            aliases, _, scope = collect_identity(
                schools, "men", conference, season, document=document
            )
            cache[(conference, season)] = (aliases, scope)
        aliases, scope = cache[(conference, season)]
        return opponent_slug(printed, aliases, scope=scope)  # type: ignore[arg-type]

    return resolve


@pytest.mark.parametrize(("printed", "conference", "slug"), PEER_SPELLINGS)
def test_peer_spelling_resolves_to_the_programme(
    identity, printed: str, conference: str, slug: str
) -> None:
    assert identity(printed, conference) == slug


@pytest.mark.parametrize(("printed", "conference", "season", "slug"), HISTORY_SPELLINGS)
def test_history_spelling_resolves_to_the_programme(
    identity, printed: str, conference: str, season: int, slug: str
) -> None:
    assert identity(printed, conference, season) == slug


@pytest.mark.parametrize(("printed", "conference", "slug"), STAY_STRANGERS)
def test_an_ambiguous_spelling_stays_its_own_text(
    identity, printed: str, conference: str, slug: str
) -> None:
    assert identity(printed, conference) == slug
