"""Truncated peer spellings of followed programmes fold onto the programme.

Measured 2026-09-06 (tl-yqj): peer schedules abbreviate a followed
programme's name with a trailing period, the identity key keeps the stub
("Palm Beach Atl." keys to "palm beach atl"), and nothing in the stanza
matched, so the data home carried palm-beach-atl beside palm-beach-atlantic,
northern-mich beside northern-michigan and mississippi-col beside
mississippi-college. Each spelling below was read off the printing
programme's cached schedule page (Tusculum 2025 and Carson-Newman 2026 for
Palm Beach Atlantic, Northwood 2023 through 2026 for Northern Michigan,
Harding 2019, 2023 and 2024 for Mississippi College) and is stated as an
alias on the stanza, not as a truncation rule in the resolver.

"Georgia Southwestern State", the fourth spelling the bead named, already
resolved when measured (the PBC stanza claims it), so only the stale rows
remain. "Saint Mary (Kan.)", the fifth, is the University of Saint Mary in
Leavenworth, Kansas, not St. Mary's of San Antonio, and stays apart.
"""

import pytest

from src.config import load_schools
from src.sidearm_live import identity_aliases, opponent_slug

PEER_SPELLINGS = [
    ("Palm Beach Atl.", "palm-beach-atlantic"),
    ("Northern Mich.", "northern-michigan"),
    ("Mississippi Col.", "mississippi-college"),
    ("Georgia Southwestern State", "georgia-southwestern"),
]


@pytest.fixture(scope="module")
def men_aliases() -> dict[str, str]:
    return identity_aliases(load_schools(), gender="men")


@pytest.mark.parametrize(("published", "slug"), PEER_SPELLINGS)
def test_truncated_spelling_resolves_to_the_programme(
    men_aliases: dict[str, str], published: str, slug: str
) -> None:
    assert opponent_slug(published, men_aliases) == slug


def test_a_whole_name_is_not_a_truncation(men_aliases: dict[str, str]) -> None:
    # Southwest Baptist (GAC through 2021) is a real opponent in the archive
    # and a followed programme in its own right; it must not fold onto any
    # other followed slug because it shares a leading word with one.
    assert opponent_slug("Southwest Baptist", men_aliases) == "southwest-baptist"


def test_the_kansas_saint_mary_stays_apart(men_aliases: dict[str, str]) -> None:
    # William Jewell's 2022 and 2024 schedules print "Saint Mary (Kan.)" for
    # the University of Saint Mary in Leavenworth, an NAIA programme; it is
    # not St. Mary's of San Antonio and must not fold onto saint-marys.
    assert opponent_slug("Saint Mary (Kan.)", men_aliases) != "saint-marys"
