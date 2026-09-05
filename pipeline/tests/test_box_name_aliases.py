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
    # The tl-kvn sweep (2026-09-03): a formal name the fold now keys to
    # "texas dallas", and two abbreviations no fold reaches.
    # sidearm:texas-a-m-international:7792, 2026-09-19
    ("University of Texas at Dallas", "ut-dallas"),
    # sidearm:oklahoma-christian:11182, 2022-10-22
    ("Texas-Permian Basin", "ut-permian-basin"),
    # sidearm:tiffin:6466, 2022-09-10 (also sidearm:walsh:4241)
    ("Ky. Wesleyan", "kentucky-wesleyan"),
    # The batch 5 alias round (tl-9vm, 2026-09-05): CCAA, PacWest and GNAC
    # spellings. First the box vocabulary the box-vs-fixture check could not
    # resolve, then the peer schedule spellings collected as strangers: a
    # backtick standing in for the okina, the long "California State
    # University, X" forms, and Hawaii Hilo's mascot-suffixed opponent names.
    # sidearm:cal-state-dominguez-hills:12905, 2023-09-18 (108 boxes)
    ("Cal St. Dom. Hills", "cal-state-dominguez-hills"),
    # sidearm:cal-state-san-bernardino:4366, 2022 (38 boxes)
    ("Cal St. San B'dino", "cal-state-san-bernardino"),
    # sidearm:cal-state-monterey-bay:9015, 2025
    ("Cal St. San Bernardino", "cal-state-san-bernardino"),
    # sidearm:san-francisco-state:6484, 2022 (37 boxes)
    ("San Fran. St.", "san-francisco-state"),
    # sidearm:montana-state-billings:9112, 2022 (38 boxes)
    ("Mont. St. Billings", "montana-state-billings"),
    # sidearm:northwest-nazarene:8314, 2024 (76 boxes, ranked form included)
    ("Western Ore.", "western-oregon"),
    ("#10 Western Ore.", "western-oregon"),
    # sidearm:sonoma-state:12040, 2023 (33 boxes)
    ("Western Wash.", "western-washington"),
    # sidearm:saint-martins:5531, 2023 (six boxes)
    ("Colo. Christian", "colorado-christian"),
    # sidearm:cal-state-san-marcos:5973, 2022 (four boxes)
    ("UC-Colo. Springs", "uccs"),
    # sidearm:cal-state-dominguez-hills:12905, 2023-09-18 (schedule row)
    ("Hawai`i Hilo", "hawaii-hilo"),
    # sidearm:cal-state-dominguez-hills:13140, 2024-09-07
    ("Hawai`i Pacific", "hawaii-pacific"),
    # sidearm:cal-state-dominguez-hills:13523, 2025-09-27
    ("California State University, Los Angeles", "cal-state-la"),
    # sidearm:simon-fraser:3710, 2022-08-27
    ("California State, Los Angeles", "cal-state-la"),
    # sidearm:fresno-pacific:9048, 2025-09-21
    ("California State University, San Bernardino", "cal-state-san-bernardino"),
    # sidearm:hawaii-pacific:10364, 2024-10-06
    ("Academy of Arts", "academy-of-art"),
    # sidearm:hawaii-pacific:10907, 2025-10-09 (the page's misspelling)
    ("Vangaurd", "vanguard"),
    # sidearm:hawaii-hilo:6167, 2022-10-22
    ("Biola Eagles", "biola"),
    # sidearm:hawaii-hilo:6160, 2022-09-23
    ("Chaminade Silverswords", "chaminade"),
    # sidearm:hawaii-hilo:7303, 2025-10-25
    ("Concordia Golden Eagles", "concordia-irvine"),
    # sidearm:hawaii-hilo:6161, 2022-09-26
    ("Dominican Penguins", "dominican-of-california"),
    # sidearm:hawaii-hilo:6159, 2022-09-17
    ("HPU Sharks", "hawaii-pacific"),
    # sidearm:hawaii-hilo:6785, 2024-10-12
    ("Jessup Warriors", "jessup"),
    # sidearm:hawaii-hilo:6792, 2024-10-15
    ("Menlo Oaks", "menlo"),
    # sidearm:hawaii-hilo:6786, 2024-10-19
    ("Vanguard Lions", "vanguard"),
    # sidearm:hawaii-hilo:6500, 2023-10-19
    ("Westmont Warriors", "westmont"),
    # sidearm:hawaii-hilo:7305, 2025-09-17
    ("UCCS Mountain Lions", "uccs"),
    # sidearm:hawaii-hilo:6156, 2022-09-09
    ("Westminster Griffins", "westminster"),
]


@pytest.fixture(scope="module")
def men_aliases() -> dict[str, str]:
    return identity_aliases(load_schools(), gender="men")


@pytest.mark.parametrize(("published", "slug"), BOX_SPELLINGS)
def test_box_spelling_resolves_to_the_member(
    men_aliases: dict[str, str], published: str, slug: str
) -> None:
    assert opponent_slug(published, men_aliases) == slug
