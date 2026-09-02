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
]


@pytest.fixture(scope="module")
def men_aliases() -> dict[str, str]:
    return identity_aliases(load_schools(), gender="men")


@pytest.mark.parametrize(("published", "slug"), BOX_SPELLINGS)
def test_box_spelling_resolves_to_the_member(
    men_aliases: dict[str, str], published: str, slug: str
) -> None:
    assert opponent_slug(published, men_aliases) == slug
