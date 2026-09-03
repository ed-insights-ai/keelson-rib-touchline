"""Abbreviated team names printed on box scores resolve to the member.

Measured 2026-09-01 by the box-vs-fixture check (tl-4sg.23): 17 box scores
named a side no stanza alias covered, so the check could not compare them.
Each spelling below was read off one of those boxes; the box id is the
citation. The check needs only the owner's own side to resolve, so six
aliases cover all 17.
"""

import pytest

from src.config import load_schools
from src.sidearm_live import identity_aliases, opponent_slug

BOX_SPELLINGS = [
    # sidearm:oklahoma-christian:11178, 2022-10-08
    ("Okla. Christian", "oklahoma-christian"),
    # sidearm:oklahoma-christian:11183, 2022-10-26
    ("West Tex. A&M", "west-texas-a-m"),
    # sidearm:texas-a-m-international:7299, 2024-10-23
    ("Tex. A&M Int'l", "texas-a-m-international"),
    # sidearm:west-alabama:4498, 2017-11-12
    ("West Ala.", "west-alabama"),
    # sidearm:ouachita-baptist:4826, 2022-09-04
    ("Ouachita", "ouachita-baptist"),
    # sidearm:eastern-new-mexico:12464, 2022-10-15
    ("Eastern N.M.", "eastern-new-mexico"),
    # The RMAC alias round (tl-clk.2, 2026-09-02): spellings read off member
    # schedule pages that collected a member as a stranger.
    # sidearm:csu-pueblo:6579, 2022-09-30
    ("S.D. Mines", "south-dakota-mines"),
    # sidearm:csu-pueblo:6569, 2022-08-25
    ("Fort Hays", "fort-hays-state"),
    # sidearm:csu-pueblo:7640, 2024-09-14
    ("Texas-Tyler", "ut-tyler"),
    # sidearm:colorado-christian:7440, 2025-09-13
    ("The University of Texas at Tyler", "ut-tyler"),
    # sidearm:westminster:12070, 2023-09-02
    ("Midwestern", "midwestern-state"),
    # sidearm:colorado-school-of-mines:21603, 2022-09-04 (box-vs-fixture, unresolved)
    ("Colo. Sch. of Mines", "colorado-school-of-mines"),
    # The batch 1 alias round (2026-09-03): NE10, CACC and ECC spellings read
    # off member schedule pages that collected a member as a stranger.
    # sidearm:bentley:2659, 2022-10-11
    ("American Int'l", "american-international"),
    # sidearm:bentley:2663, 2022-10-25 (also box sidearm:southern-new-hampshire:13516)
    ("Southern Conn. St.", "southern-connecticut"),
    # sidearm:bentley:2658, 2022-10-08 (also box sidearm:southern-new-hampshire:13516)
    ("Southern N.H.", "southern-new-hampshire"),
    # sidearm:american-international:23214, 2022-09-03
    ("Dist. Columbia", "district-of-columbia"),
    # sidearm:jefferson:7857, 2026-09-19
    ("Dominican University of N.Y.", "dominican"),
    # sidearm:franklin-pierce:22612, 2022-12-03
    ("Colorado St.-Pueblo", "csu-pueblo"),
]


@pytest.fixture(scope="module")
def men_aliases() -> dict[str, str]:
    return identity_aliases(load_schools(), gender="men")


@pytest.mark.parametrize(("published", "slug"), BOX_SPELLINGS)
def test_box_spelling_resolves_to_the_member(
    men_aliases: dict[str, str], published: str, slug: str
) -> None:
    assert opponent_slug(published, men_aliases) == slug
