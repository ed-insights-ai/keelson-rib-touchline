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

The women's rounds follow the same rule. The third (2026-11-21) is the
same-day duplicates left after the first collect: a typo ("Middle
Tennesse"), initials no stanza resolved ("GCU", "UNR"), "SLU", which is
Saint Louis's too and so a Southland member alias, and a nickname printed
alone ("Ragin' Cajuns").

The fourth (2026-11-21) is the 2022-2025 history: the long and old forms
peers print ("LeMoyne", "California Riverside", "Youngstown", "Alabama at
Birmingham", "Illinois Chicago", "Tennessee at Martin", "Mizzou", "HBU",
"UL Monroe", "SC State") and one box abbreviation ("Central Mich.").
"Mississippi" is an SEC member alias on Ole Miss: the institution-word fold
reads "Mississippi College" (Division II) as the same key, so the bare
state name is Ole Miss only inside an SEC collect.
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
    ("Loyola", "A10", 2022, "loyola-chicago"),  # dayton, rhode-island
    # The 2022 round: box-score spellings box-vs-fixture could not resolve.
    ("Northern Ky.", "SUMMIT", 2022, "northern-kentucky"),
    ("Southern Ind.", "HORIZON", 2022, "southern-indiana"),
    ("Harvard Crimson", "IVY", 2022, "harvard"),
    ("Columbia Lions", "IVY", 2022, "columbia"),
    ("Ga. Southern", "CAA", 2023, "georgia-southern"),
    ("Col. of Charleston", "SUNBELT", 2023, "charleston-south-carolina"),
    ("South Fla.", "AAC", 2024, "south-florida"),
    ("Howard Bison", "NEC", 2024, "howard"),
    ("Mercyhurst Lakers", "NEC", 2024, "mercyhurst"),
]

# Ambiguous outside the conference that reads them one way: they stay the
# text's own slug rather than guess (Loyola Chicago on Horizon, OVC and MVC
# pages; South Florida on ASUN and Sun Belt pages; Queen's and Santa Barbara
# City by the fold).
#
# "Loyola (Md.)" left this list when a printed state became evidence: it is
# Loyola Maryland on every page (tests/test_state_qualifier.py). "Loyola
# (Ill.)" left it when Loyola Chicago took bare "Loyola" as an A10 member
# alias (the 2022 round): the Illinois qualifier now has its claimant.
STAY_STRANGERS = [
    ("Loyola", "MVC", "loyola"),
    ("USF", "ASUN", "usf"),
    ("Boston", "ACC", "boston"),
    ("CBU", "WCC", "cbu"),
    ("Santa Barbara", "WCC", "santa-barbara"),
    ("Queens U. (N.C.)", "BIGSOUTH", "queens-u"),
    ("ODU", "ACC", "odu"),
    ("Central Florida", "AAC", "central-florida"),
]

# The third women's round (bead tui-l57): same-day duplicates of the 2026
# women's collect, each a peer's spelling of a member on the printing page
# (printed, the collecting conference whose page printed it, programme).
WOMEN_SPELLINGS = [
    ("Middle Tennesse", "CUSA", "mtsu"),  # nmstatesports.com, game 19305
    ("GCU", "MW", "grand-canyon"),  # nevadawolfpack.com, game 14181
    ("GCU", "BIG12", "grand-canyon"),  # arizonawildcats.com, game 31801
    ("UNR", "MW", "nevada"),  # unlvrebels.com, game 17890
    ("SLU", "SOUTHLAND", "southeastern-louisiana"),  # sfajacks.com, game 14219
    ("Ragin' Cajuns", "SUNBELT", "louisiana"),  # ulmwarhawks.com, game 16604
]

# "SLU" is Saint Louis's too: outside a Southland collect it stays its text.
WOMEN_STAY_STRANGERS = [
    ("SLU", "A10", "slu"),
    ("SLU", "SEC", "slu"),
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


@pytest.fixture(scope="module")
def women_identity():
    schools = load_schools()
    document = load_membership()

    def resolve(printed: str, conference: str) -> str:
        aliases, _, scope = collect_identity(
            schools, "women", conference, 2026, document=document
        )
        return opponent_slug(printed, aliases, scope=scope)  # type: ignore[arg-type]

    return resolve


@pytest.mark.parametrize(("printed", "conference", "slug"), WOMEN_SPELLINGS)
def test_womens_peer_spelling_resolves_to_the_programme(
    women_identity, printed: str, conference: str, slug: str
) -> None:
    assert women_identity(printed, conference) == slug


@pytest.mark.parametrize(("printed", "conference", "slug"), WOMEN_STAY_STRANGERS)
def test_a_womens_ambiguous_spelling_stays_its_own_text(
    women_identity, printed: str, conference: str, slug: str
) -> None:
    assert women_identity(printed, conference) == slug


# The fourth women's round: same-day duplicates and unresolved box names of
# the 2022-2025 backfill (printed, conference, season, programme).
HISTORY_SPELLINGS = [
    ("LeMoyne", "NEC", 2023, "le-moyne"),  # sfuathletics.com, game 11648
    ("LeMoyne College", "NEC", 2024, "le-moyne"),  # dsuhornets.com, game 7791
    ("LeMoyne", "AAC", 2025, "le-moyne"),  # owlsports.com, game 14637
    ("#13 Mississippi", "SEC", 2022, "ole-miss"),  # floridagators.com, 25237
    ("Mississippi", "SEC", 2025, "ole-miss"),  # floridagators.com, game 27350
    ("California Riverside", "BIGSKY", 2023, "uc-riverside"),  # goviks.com
    ("University of California Riverside", "BIGWEST", 2023, "uc-riverside"),
    ("Youngstown", "HORIZON", 2023, "youngstown-state"),  # rmucolonials.com
    ("University of Alabama at Birmingham", "CUSA", 2022, "uab"),  # fiusports
    ("Illinois Chicago", "MVC", 2022, "uic"),  # gosycamores.com, game 14092
    ("University of Illinois Chicago (Exhibition)", "OVC", 2022, "uic"),
    ("University of Tennessee at Martin", "OVC", 2022, "ut-martin"),
    ("Mizzou", "SEC", 2022, "missouri"),  # ukathletics.com (WMT)
    ("Mizzou", "SUMMIT", 2022, "missouri"),  # omahamavs.com, game 17689
    ("HBU", "SOUTHLAND", 2022, "hcu"),  # goislanders.com, game 6886
    ("UL Monroe", "SUNBELT", 2022, "ulm"),  # gseagles.com, game 13594
    ("UL-Monroe (Exhibition)", "SOUTHLAND", 2023, "ulm"),  # mcneesesports.com
    ("UL-Monroe", "AAC", 2026, "ulm"),  # riceowls.com, game 28901
    ("SC State", "BIGSOUTH", 2023, "south-carolina-state"),  # gwusports.com
    ("SC State University", "independent", 2022, "south-carolina-state"),
    ("Central Mich.", "MAC", 2023, "central-michigan"),  # cmuchippewas.com box
]

# Outside an SEC collect the bare state name stays its own text, and so does
# "Mississippi College", which folds to the same key.
HISTORY_STAY_STRANGERS = [
    ("Mississippi College", "ASUN", 2022, "mississippi"),  # queensathletics.com
    ("Mississippi", "SWAC", 2024, "mississippi"),
    ("Mississippi State", "SEC", 2025, "mississippi-state"),
]


@pytest.fixture(scope="module")
def season_identity():
    schools = load_schools()
    document = load_membership()
    cache: dict[tuple[str, int], tuple[dict[str, str], object]] = {}

    def resolve(printed: str, conference: str, season: int) -> str:
        if (conference, season) not in cache:
            aliases, _, scope = collect_identity(
                schools, "women", conference, season, document=document
            )
            cache[(conference, season)] = (aliases, scope)
        aliases, scope = cache[(conference, season)]
        return opponent_slug(printed, aliases, scope=scope)  # type: ignore[arg-type]

    return resolve


@pytest.mark.parametrize(("printed", "conference", "season", "slug"), HISTORY_SPELLINGS)
def test_a_history_spelling_resolves_to_the_programme(
    season_identity, printed: str, conference: str, season: int, slug: str
) -> None:
    assert season_identity(printed, conference, season) == slug


@pytest.mark.parametrize(
    ("printed", "conference", "season", "slug"), HISTORY_STAY_STRANGERS
)
def test_a_history_spelling_another_school_shares_stays_its_text(
    season_identity, printed: str, conference: str, season: int, slug: str
) -> None:
    assert season_identity(printed, conference, season) == slug
