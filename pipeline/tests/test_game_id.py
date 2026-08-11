"""Tests for game_id generation — verifies no collisions across schools."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from src.config import load_schools

SCHOOLS_TOML = Path(__file__).resolve().parent.parent / "config" / "schools.toml"


def test_game_id_no_collision_across_schools():
    """HU (ordinal=1) and HUW (ordinal=8) must produce non-overlapping game_ids."""
    schools = load_schools()
    hu = next(s for s in schools if s.abbreviation == "HU")
    huw = next(s for s in schools if s.abbreviation == "HUW")

    assert hu.ordinal != huw.ordinal

    # Same year, same game_num → different game_ids
    year, game_num = 2024, 1
    hu_id = hu.ordinal * 1_000_000 + year * 100 + game_num
    huw_id = huw.ordinal * 1_000_000 + year * 100 + game_num
    assert hu_id != huw_id


def test_assigned_ordinals_are_explicit_and_unique():
    """Every school the StatCrew lineage reads carries an explicit unique ordinal.

    Narrowed from "every school": an ordinal only namespaces the legacy game_id
    space, and the live collector never reads it, so a SideArm-only school added
    for a new conference may leave it unset. Every school in the file today is
    StatCrew-era and does carry one, which this still asserts.
    """
    with open(SCHOOLS_TOML, "rb") as f:
        data = tomllib.load(f)

    ordinals = []
    for entry in data["schools"]:
        assert "ordinal" in entry, f"Missing ordinal for {entry['abbreviation']}"
        ordinals.append(entry["ordinal"])

    assert len(ordinals) == len(set(ordinals)), "Duplicate ordinals found"


def _toml(*entries: str) -> str:
    return "\n".join(entries)


def _entry(abbr: str, *, ordinal: int | None = None) -> str:
    lines = [
        "[[schools]]",
        f'name = "{abbr} School"',
        f'abbreviation = "{abbr}"',
        'conference = "TEST"',
    ]
    if ordinal is not None:
        lines.append(f"ordinal = {ordinal}")
    return "\n".join(lines)


def test_a_school_without_an_ordinal_loads_as_unassigned(tmp_path):
    """A SideArm-only school needs no ordinal, and several may go unassigned.

    The loader used to default a missing ordinal to the entry's file position,
    which meant inserting an unnumbered school ahead of a numbered one
    manufactured a duplicate and refused the whole run. Grouping a new
    conference mid-file is the natural edit, so it must not raise.
    """
    config = tmp_path / "schools.toml"
    config.write_text(
        _toml(
            _entry("AAA", ordinal=1),
            _entry("MID"),  # inserted mid-file, no ordinal
            _entry("BBB", ordinal=2),
            _entry("OTHER"),  # a second unassigned school must not collide
        )
    )

    schools = load_schools(config)
    by_abbr = {s.abbreviation: s.ordinal for s in schools}
    assert by_abbr == {"AAA": 1, "MID": 0, "BBB": 2, "OTHER": 0}


def test_duplicate_assigned_ordinals_still_refuse_the_load(tmp_path):
    """The game_id namespace is still enforced where it is real."""
    config = tmp_path / "schools.toml"
    config.write_text(_toml(_entry("AAA", ordinal=3), _entry("BBB", ordinal=3)))

    with pytest.raises(ValueError, match="Duplicate ordinal 3"):
        load_schools(config)


def test_ordinals_survive_reorder():
    """Shuffling schools.toml entries doesn't change ordinals."""
    schools = load_schools()
    ordinal_map = {s.abbreviation: s.ordinal for s in schools}

    # Verify specific known ordinals that shouldn't change regardless of order
    assert ordinal_map["HU"] == 1
    assert ordinal_map["FHSU"] == 2
    assert ordinal_map["HUW"] == 8
    assert ordinal_map["SWOSU"] == 14
