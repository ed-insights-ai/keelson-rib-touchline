"""The GLVC's members resolve from the spellings their peers actually publish.

Measured 2026-09-02 (tl-v7p): peer schedules print "Lincoln University of
Missouri", the identity key reduces it to "lincoln of missouri", and nothing
in the stanza matched — six 2026 fixtures were collected twice, once under
lincoln and once under lincoln-of-missouri. Each spelling below was read off
a member's own 2026 schedule page (McKendree, Truman), so this is the alias
round every conference add pays, pinned.
"""

import pytest

from src.config import load_schools
from src.sidearm_live import identity_aliases, opponent_slug

PEER_SPELLINGS = [
    ("Lincoln University of Missouri", "lincoln"),
    ("Lincoln (Mo.)", "lincoln"),
    ("University of Missouri - St. Louis", "missouri-st-louis"),
    ("Missouri -St. Louis", "missouri-st-louis"),
    ("Truman State University", "truman"),
    ("Truman", "truman"),
    ("University of Illinois Springfield", "illinois-springfield"),
    ("Illinois-Springfield", "illinois-springfield"),
    ("University of Indianapolis", "indianapolis"),
    ("UIndy", "indianapolis"),
    ("Missouri S&T", "missouri-s-t"),
]


@pytest.fixture(scope="module")
def men_aliases() -> dict[str, str]:
    return identity_aliases(load_schools(), gender="men")


@pytest.mark.parametrize(("published", "slug"), PEER_SPELLINGS)
def test_peer_spelling_resolves_to_the_member(
    men_aliases: dict[str, str], published: str, slug: str
) -> None:
    assert opponent_slug(published, men_aliases) == slug


def test_the_other_lincoln_stays_apart(men_aliases: dict[str, str]) -> None:
    # Lincoln Memorial (SAC) is a real opponent in the archive and must not
    # fold onto the GLVC's Lincoln because both start with the word.
    assert opponent_slug("Lincoln Memorial", men_aliases) != "lincoln"
