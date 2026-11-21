"""An independent's NCAA level, stated on its window.

A programme's level comes from a window naming a profiled conference, else
from its stanza conference's profile (``membership.programme_level``).
``independent`` is structural and has no profile, so a programme whose only
window is independent has no level, and check-membership refuses its stanza
("has no NCAA level": it would sit in every level's table). South Carolina
State, the NCAA RPI's lone "DI Independent" in 2026 women's soccer, is such a
programme.

An ``independent`` window may now say its level (``"level": "d1"``): the
NCAA classifies an independent's programme even though no conference
carries it. Only an independent window may: a window naming a profiled
conference takes the profile's level, and a ``non_member`` window names no
programme the NCAA classifies, so a ``level`` on either is refused, as is a
level that is not one of ``LEVELS``.
"""

from __future__ import annotations

import copy

import pytest

from src import membership
from src.config import SchoolConfig


def _school(name: str, conference: str) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation="",
        conference=conference,
        prefix="",
        base_url="",
        gender="women",
    )


def _window(conference: str, start: int, end: int, **extra: object) -> dict:
    return {
        "conference": conference,
        "from_season": start,
        "to_season": end,
        "source": "test fixture",
        **extra,
    }


SCHOOLS = [
    _school("South Carolina State", "independent"),
    _school("Winthrop", "BIGSOUTH"),
    _school("Lander", "PEACHBELT"),
]


def _document(independent: dict) -> dict:
    return {
        "version": 1,
        "seasons": {"from": 2024, "to": 2026},
        "conferences": ["BIGSOUTH", "PEACHBELT", "independent", "non_member"],
        "conference_profiles": {
            "BIGSOUTH": {"level": "d1", "names": ["Big South Conference"]},
            "PEACHBELT": {"level": "d2", "names": ["Peach Belt Conference"]},
        },
        "memberships": {
            "south-carolina-state": {"women": [independent]},
            "winthrop": {"women": [_window("BIGSOUTH", 2024, 2026)]},
            "lander": {"women": [_window("PEACHBELT", 2024, 2026)]},
        },
    }


STATED = _document(_window("independent", 2026, 2026, level="d1"))


def test_an_independent_window_with_no_level_still_has_none():
    document = _document(_window("independent", 2026, 2026))
    assert (
        membership.programme_level(
            "south-carolina-state",
            "women",
            2026,
            stanza_conference="independent",
            document=document,
        )
        is None
    )
    errors = membership.validate(document, schools=SCHOOLS)
    assert errors == [
        "south-carolina-state:women has no NCAA level: no window names a "
        "conference with a profile and its stanza conference 'independent' has "
        "none, so it would resolve opponent text at every level"
    ]


def test_an_independent_window_states_its_level():
    assert (
        membership.programme_level(
            "south-carolina-state",
            "women",
            2026,
            stanza_conference="independent",
            document=STATED,
        )
        == "d1"
    )
    assert membership.validate(STATED, schools=SCHOOLS) == []


def test_the_stated_level_puts_the_stanza_in_that_levels_table_alone():
    d1 = membership.stanzas_at_level(SCHOOLS, "women", "d1", 2026, document=STATED)
    d2 = membership.stanzas_at_level(SCHOOLS, "women", "d2", 2026, document=STATED)
    assert [school.name for school in d1] == ["South Carolina State", "Winthrop"]
    assert [school.name for school in d2] == ["Lander"]


def test_a_collect_of_independent_reads_its_programmes_stated_level():
    assert (
        membership.collect_level(
            SCHOOLS,
            "women",
            "independent",
            2026,
            programmes=["south-carolina-state"],
            document=STATED,
        )
        == "d1"
    )


def test_a_stated_level_governs_its_own_seasons_only():
    # A reclassifier: Division II through 2024, an independent at d1 in
    # 2025, then a Division I conference. Without the statement 2025 took
    # the level it left from.
    document = _document(_window("independent", 2026, 2026))
    document["memberships"]["south-carolina-state"]["women"] = [
        _window("PEACHBELT", 2024, 2024),
        _window("independent", 2025, 2025, level="d1"),
        _window("BIGSOUTH", 2026, 2026),
    ]
    levels = [
        membership.programme_level(
            "south-carolina-state", "women", season, document=document
        )
        for season in (2024, 2025, 2026)
    ]
    assert levels == ["d2", "d1", "d1"]
    unstated = copy.deepcopy(document)
    del unstated["memberships"]["south-carolina-state"]["women"][1]["level"]
    assert (
        membership.programme_level(
            "south-carolina-state", "women", 2025, document=unstated
        )
        == "d2"
    )


@pytest.mark.parametrize(
    ("window", "message"),
    [
        (
            _window("BIGSOUTH", 2026, 2026, level="d1"),
            "south-carolina-state:women window 0 states level 'd1', but only an "
            "independent window may: a conference's window takes its profile's "
            "level",
        ),
        (
            _window("non_member", 2026, 2026, level="d1"),
            "south-carolina-state:women window 0 states level 'd1', but only an "
            "independent window may: a non_member window has no level",
        ),
        (
            _window("independent", 2026, 2026, level="D-I"),
            "south-carolina-state:women window 0 level must be one of d1, d2, d3, not 'D-I'",
        ),
    ],
)
def test_a_level_anywhere_else_or_of_no_known_level_is_refused(window, message):
    errors = membership.validate(_document(window), schools=SCHOOLS)
    assert message in errors
