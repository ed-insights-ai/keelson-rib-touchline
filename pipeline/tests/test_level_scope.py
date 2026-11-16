"""Opponent text resolves against ONE NCAA level: the collected conference's.

Measured 2026-11-15 with 214 Division I men's programmes loaded beside the
483 Division II stanzas into one gender-wide table: replaying the 2,313
archived Division II schedule pages re-pointed 155 fixture-sides on 136
pages ("Penn State Abington" to Division I Penn State by token subset,
"Queens" to Queens of Charlotte, "California" to Cal in reverse), and every
Division II page's parse fingerprint changed. Scoped to the collecting
level, the same replay differs on 0 of 2,313 pages and 0 of 462 Division II
conference-season tables.

The rule: a collect of conference C for season Y builds its identity map,
member claims, member-only aliases and distance tiebreak from the stanzas
whose programme is at C's level in Y (``membership.resolution_stanzas``).
Text naming a school at another level mints its slug from the text.
"""

from __future__ import annotations

import copy

from scripts.collect_board import collect_identity
from src import membership
from src.config import SchoolConfig, programme_slug
from src.membership import (
    level_scopes,
    programme_level,
    shard_stanzas,
    stanzas_at_level,
)
from src.sidearm_live import (
    ConferenceHeaders,
    conference_members,
    identity_aliases,
    level_identity_collisions,
    ncaa_side,
    opponent_slug,
    resolution_scope,
)


def _school(name: str, conference: str, **fields: object) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=str(fields.pop("abbreviation", "")),
        conference=conference,
        prefix="",
        base_url="",
        gender="men",
        **fields,  # type: ignore[arg-type]
    )


def _window(conference: str, start: int, end: int) -> dict[str, object]:
    return {
        "conference": conference,
        "from_season": start,
        "to_season": end,
        "source": "test fixture",
    }


D2_SCHOOLS = [
    _school("West Chester", "PSAC", abbreviation="WCU"),
    _school("California Pa", "PSAC", abbreviation="CAL", aliases=["California"]),
    # Division II through 2023, Division I from 2024: one programme, one
    # stanza, two windows.
    _school("Mercyhurst", "PSAC", abbreviation="HURST"),
    _school("Charleston", "MEC", aliases=["University of Charleston"]),
]
D1_SCHOOLS = [
    _school("Penn State", "BIG10", abbreviation="PSU"),
    _school("Cal", "BIG10", aliases=["California"]),
    _school("College of Charleston", "CAA", aliases=["Charleston"]),
    _school("Saint Francis", "NEC", member_aliases=["SFU"]),
]


def _document(*, with_d1: bool) -> dict[str, object]:
    profiles: dict[str, object] = {
        "PSAC": {"level": "d2", "names": ["Pennsylvania State Athletic Conference"]},
        "MEC": {"level": "d2", "names": ["Mountain East Conference", "Mountain East"]},
    }
    memberships: dict[str, object] = {
        "west-chester": {"men": [_window("PSAC", 2022, 2026)]},
        "california-pa": {"men": [_window("PSAC", 2022, 2026)]},
        "mercyhurst": {"men": [_window("PSAC", 2022, 2023)]},
        "charleston": {"men": [_window("MEC", 2022, 2026)]},
    }
    conferences = ["MEC", "PSAC"]
    if with_d1:
        conferences += ["BIG10", "CAA", "NEC"]
        profiles |= {
            "BIG10": {"level": "d1", "names": ["Big Ten Conference", "Big Ten"]},
            "CAA": {"level": "d1", "names": ["Coastal Athletic Association"]},
            "NEC": {"level": "d1", "names": ["Northeast Conference"]},
        }
        memberships |= {
            "penn-state": {"men": [_window("BIG10", 2022, 2026)]},
            "cal": {"men": [_window("BIG10", 2022, 2026)]},
            "college-of-charleston": {"men": [_window("CAA", 2022, 2026)]},
            "saint-francis": {"men": [_window("NEC", 2022, 2026)]},
        }
        memberships["mercyhurst"] = {
            "men": [_window("PSAC", 2022, 2023), _window("NEC", 2024, 2026)]
        }
    return {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": [*conferences, "independent", "non_member"],
        "conference_profiles": profiles,
        "memberships": memberships,
    }


D2_ONLY = _document(with_d1=False)
BOTH = _document(with_d1=True)
ALL_SCHOOLS = [*D2_SCHOOLS, *D1_SCHOOLS]


def _slugs(schools: list[SchoolConfig]) -> list[str]:
    return [programme_slug(school.name) for school in schools]


# ── the level a programme holds in a season ────────────────────────────────


def test_a_reclassifier_sits_in_each_levels_table_for_the_seasons_its_windows_say():
    d2_2023 = _slugs(stanzas_at_level(ALL_SCHOOLS, "men", "d2", 2023, document=BOTH))
    d1_2023 = _slugs(stanzas_at_level(ALL_SCHOOLS, "men", "d1", 2023, document=BOTH))
    d2_2024 = _slugs(stanzas_at_level(ALL_SCHOOLS, "men", "d2", 2024, document=BOTH))
    d1_2024 = _slugs(stanzas_at_level(ALL_SCHOOLS, "men", "d1", 2024, document=BOTH))
    assert "mercyhurst" in d2_2023 and "mercyhurst" not in d1_2023
    assert "mercyhurst" in d1_2024 and "mercyhurst" not in d2_2024
    # File order is kept, so last-stanza-wins holds where it held.
    assert d2_2023 == ["west-chester", "california-pa", "mercyhurst", "charleston"]
    assert d1_2024 == [
        "mercyhurst",
        "penn-state",
        "cal",
        "college-of-charleston",
        "saint-francis",
    ]

    # Its abbreviation resolves in the table it sits in, and only there.
    def read(conference: str, season: int) -> str:
        aliases, _, scope = collect_identity(
            ALL_SCHOOLS, "men", conference, season, document=BOTH
        )
        return opponent_slug("HURST", aliases, scope=scope)

    assert read("PSAC", 2023) == "mercyhurst"
    assert read("NEC", 2023) == "hurst"
    assert read("PSAC", 2024) == "hurst"
    assert read("NEC", 2024) == "mercyhurst"


def test_a_season_no_level_bearing_window_covers_takes_the_nearest_one():
    document = {
        "conference_profiles": {
            "PSAC": {"level": "d2", "names": ["P"]},
            "NEC": {"level": "d1", "names": ["N"]},
        },
        "memberships": {
            "leaver": {"men": [_window("PSAC", 2022, 2023)]},
            "arrival": {
                "men": [_window("non_member", 2016, 2018), _window("NEC", 2019, 2026)]
            },
            "lapsed": {
                "men": [_window("PSAC", 2016, 2019), _window("non_member", 2020, 2025)]
            },
            "only-structural": {"men": [_window("independent", 2016, 2026)]},
        },
    }

    def level(slug: str, season: int, stanza: str = "") -> str | None:
        return programme_level(
            slug, "men", season, stanza_conference=stanza, document=document
        )

    # A leaver keeps the level it left from; before its first window it
    # takes that window's (the rule that leaves today's Division II tables
    # exactly as they were: Mercyhurst stays at d2 until its D1 window is
    # authored).
    assert [level("leaver", s) for s in (2016, 2022, 2023, 2024, 2030)] == ["d2"] * 5
    # A structural window names no conference and so no level: the nearest
    # level-bearing window answers, the earlier one first.
    assert level("arrival", 2017) == "d1"
    assert level("lapsed", 2022) == "d2"
    # No level-bearing window at all: the stanza's conference, else none.
    assert level("only-structural", 2020, "NEC") == "d1"
    assert level("unwindowed", 2020, "PSAC") == "d2"
    assert level("unwindowed", 2020, "") is None


def test_a_stanza_with_no_level_is_kept_at_every_level_and_refused_by_the_check():
    stray = _school("Stray", "UNDECLARED")
    for level in ("d1", "d2"):
        kept = stanzas_at_level([stray], "men", level, 2024, document=BOTH)
        assert _slugs(kept) == ["stray"]
    document = copy.deepcopy(D2_ONLY)
    document["memberships"]["stray"] = {"men": [_window("independent", 2022, 2026)]}  # type: ignore[index]
    errors = membership.validate(document, schools=[*D2_SCHOOLS, stray])
    assert errors == [
        "stray:men has no NCAA level: no window names a conference with a "
        "profile and its stanza conference 'UNDECLARED' has none, so it would "
        "resolve opponent text at every level"
    ]


# ── Division II unchanged, by construction ─────────────────────────────────


def test_adding_another_levels_stanzas_changes_nothing_a_d2_collect_reads():
    for conference in ("PSAC", "MEC"):
        for season in (2022, 2023):
            before = collect_identity(
                D2_SCHOOLS, "men", conference, season, document=D2_ONLY
            )
            after = collect_identity(
                ALL_SCHOOLS, "men", conference, season, document=BOTH
            )
            assert after[0] == before[0]
            assert after[1] == before[1]
            # The other level's stanzas resolve nothing here; the one thing
            # they add is their own keys, so text naming one of them whole is
            # never a token subset's capture (tests/test_foreign_key.py).
            shaped = after[2].fingerprint("west-chester")
            assert set(shaped.pop("foreign")) == {
                "penn state",
                "psu",
                "cal",
                "california",
                "charleston",
                "saint francis",
            }
            assert shaped == before[2].fingerprint("west-chester")
            assert after[2].level == before[2].level == "d2"
    # The header reader a D2 collect uses, whose signature enters the
    # schedule fingerprint, reads the d2 conferences' names as its own; the
    # other levels' names enter only to refuse a header that names nothing
    # but another level's conference, and the signature carries them after
    # the level's own entries.
    both, d2_only = ConferenceHeaders(BOTH, "d2"), ConferenceHeaders(D2_ONLY, "d2")
    assert both.signature[:-1] == d2_only.signature[:-1]
    assert d2_only.signature[:-1] == ConferenceHeaders(D2_ONLY).signature
    assert d2_only.signature[-1] == []
    assert [entry[0] for entry in both.signature[-1]] == ["BIG10", "CAA", "NEC"]


def test_d2_text_naming_a_d1_school_mints_its_slug_from_the_text():
    aliases, _, scope = collect_identity(
        ALL_SCHOOLS, "men", "PSAC", 2025, document=BOTH
    )
    read = {
        text: opponent_slug(text, aliases, scope=scope, owner="west-chester")
        for text in (
            "Penn State Abington",
            "Penn State",
            "PSU",
            "California",
            "Charleston",
            "College of Charleston",
        )
    }
    assert read == {
        # Across levels, "Penn State" is a token subset and took this.
        "Penn State Abington": "penn-state-abington",
        "Penn State": "penn-state",  # minted from the text, not resolved
        "PSU": "psu",
        "California": "california-pa",
        "Charleston": "charleston",
        "College of Charleston": "charleston",  # the fold's key, in D2's table
    }
    assert "penn-state" not in aliases.values()


def test_d1_text_resolves_to_the_d1_programme():
    aliases, _, scope = collect_identity(
        ALL_SCHOOLS, "men", "BIG10", 2025, document=BOTH
    )
    assert opponent_slug("California", aliases, scope=scope) == "cal"
    assert opponent_slug("Charleston", aliases, scope=scope) == (
        "college-of-charleston"
    )
    assert opponent_slug("PSU", aliases, scope=scope) == "penn-state"
    # A D2 school a D1 home meets in an exhibition is a stranger there.
    assert opponent_slug("West Chester", aliases, scope=scope) == "west-chester"
    assert "west-chester" not in aliases.values()
    assert opponent_slug("WCU", aliases, scope=scope) == "wcu"


def test_the_unscoped_table_shows_the_defect_the_scope_removes():
    # The pre-level table: every stanza of the gender, last stanza wins.
    everyone = identity_aliases(ALL_SCHOOLS, "men")
    assert opponent_slug("Penn State Abington", everyone) == "penn-state"
    assert opponent_slug("California", everyone) == "cal"
    # "University of Charleston" and "College of Charleston" meet on
    # "charleston" in one table, and only the institution word tells them
    # apart, so the bare word names neither: Charleston (W.Va.)'s own name
    # stops resolving to it and mints a text slug (which happens to be the
    # same string). Scoped, each level's table holds one Charleston and the
    # bare word resolves (above).
    assert opponent_slug("College of Charleston", everyone) == "college-of-charleston"
    assert opponent_slug("University of Charleston", everyone) == "charleston"
    assert "charleston" not in everyone


def test_ncaa_side_reads_member_only_aliases_of_the_collecting_level_only():
    aliases, _, scope = collect_identity(
        ALL_SCHOOLS, "men", "PSAC", 2025, document=BOTH
    )
    assert "sfu" not in scope.member_only
    assert ncaa_side("sfu", aliases, scope, owner="west-chester") == "sfu"

    # Built over every stanza, the D1 member alias would take the D2 tie.
    members = conference_members(ALL_SCHOOLS, "men", "PSAC", season=2025, document=BOTH)
    unscoped = resolution_scope(
        ALL_SCHOOLS, "men", members, conference="PSAC", season=2025
    )
    everyone = identity_aliases(ALL_SCHOOLS, "men")
    assert ncaa_side("sfu", everyone, unscoped, owner="west-chester") == (
        "saint-francis"
    )

    # In its own level's collect it still names the one programme.
    aliases, _, scope = collect_identity(ALL_SCHOOLS, "men", "CAA", 2025, document=BOTH)
    assert ncaa_side("sfu", aliases, scope, owner="college-of-charleston") == (
        "saint-francis"
    )


def test_every_mapping_of_a_d2_scope_names_d2_programmes_only():
    _, _, scope = collect_identity(ALL_SCHOOLS, "men", "PSAC", 2025, document=BOTH)
    d2 = {"west-chester", "california-pa", "mercyhurst", "charleston"}
    named = {
        *scope.claims.values(),
        *scope.member_only.values(),
        *scope.abbreviations,
        *(slug for slugs in scope.claimants.values() for slug in slugs),
    }
    assert named <= d2 - {"mercyhurst"}  # Mercyhurst is D1 in 2025


def test_a_header_is_read_for_the_collecting_levels_conferences():
    assert ConferenceHeaders(BOTH, "d1").names_a_conference("Big Ten Tournament")
    assert not ConferenceHeaders(BOTH, "d2").names_a_conference("Big Ten Tournament")
    assert ConferenceHeaders(BOTH, "d2").names_a_conference(
        "Mountain East Championship"
    )
    assert ConferenceHeaders(BOTH).names_a_conference("Big Ten Tournament")


# ── check-membership, within a level scope ─────────────────────────────────


def test_one_key_at_two_levels_is_no_collision():
    # "California" is California (Pa.)'s alias at d2 and Cal's at d1;
    # "Charleston" is the West Virginia school's name and the College of
    # Charleston's alias. They never share a table.
    assert membership.validate(BOTH, schools=ALL_SCHOOLS) == []
    assert level_identity_collisions(ALL_SCHOOLS, document=BOTH) == []


def test_one_key_inside_one_level_is_refused_naming_the_scope():
    # Boston College and Boston University fold to one key but the
    # institution word tells them apart (test_institution_word.py); two
    # stanzas claiming "Boston College" itself do collide.
    boston = [
        _school("Boston College", "BIG10"),
        _school("Boston Eagles", "BIG10", aliases=["Boston College"]),
    ]
    document = copy.deepcopy(BOTH)
    document["memberships"] |= {  # type: ignore[operator]
        "boston-college": {"men": [_window("BIG10", 2022, 2026)]},
        "boston-eagles": {"men": [_window("BIG10", 2022, 2026)]},
    }
    assert membership.validate(document, schools=[*ALL_SCHOOLS, *boston]) == [
        "identity collision (men, d1, seasons 2022-2026): 'boston college' is "
        "claimed by boston-college (name) and boston-eagles (alias); drop the "
        "alias or set abbreviation_resolves = false on the stanzas that share "
        "the initialism"
    ]


def test_a_reclassifier_collides_only_in_the_seasons_it_shares_a_table():
    # A D1 stanza claiming Mercyhurst's abbreviation meets it from 2024.
    hurst = _school("Hurst Tech", "NEC", aliases=["HURST"])
    document = copy.deepcopy(BOTH)
    document["memberships"]["hurst-tech"] = {"men": [_window("NEC", 2022, 2026)]}  # type: ignore[index]
    assert level_identity_collisions([*ALL_SCHOOLS, hurst], document=document) == [
        (
            "men",
            "d1, seasons 2024-2026",
            "hurst",
            [("mercyhurst", "abbreviation"), ("hurst-tech", "alias")],
        )
    ]


def test_level_scopes_are_one_table_per_level_held():
    tables = {
        (gender, level, season): _slugs(stanzas)
        for gender, level, season, stanzas in level_scopes(ALL_SCHOOLS, document=BOTH)
    }
    assert set(tables) == {
        ("men", level, season) for level in ("d1", "d2") for season in range(2022, 2027)
    }
    assert tables[("men", "d2", 2023)] == [
        "west-chester",
        "california-pa",
        "mercyhurst",
        "charleston",
    ]


# ── read-only checks re-read a season file in its collect's table ──────────


def test_a_season_files_stem_names_its_table():
    assert _slugs(shard_stanzas(ALL_SCHOOLS, "2025-men-psac", document=BOTH)) == [
        "west-chester",
        "california-pa",
        "charleston",
    ]
    assert "cal" in _slugs(shard_stanzas(ALL_SCHOOLS, "2025-men-big10", document=BOTH))
    # Unreadable, or no document: the whole gender, as before levels.
    assert len(shard_stanzas(ALL_SCHOOLS, "2025-men-nope", document=BOTH)) == 8
    assert len(shard_stanzas(ALL_SCHOOLS, "2025-men-psac", document=None)) == 8


# ── a structural code carries its programmes' level ─────────────────────────


def test_a_structural_collect_resolves_at_its_programmes_level():
    """UTRGV men 2025 is an ``independent``: the code has no profile, so the
    collect took no level, resolved against every level's stanzas, read
    "Charleston" as Division II Charleston (W.Va.) and read headers against
    every level's conferences. Its level is its programme's, Division I,
    for identity, the header reader and the shard readers alike."""
    import pytest

    from src.config import load_schools
    from src.membership import MixedLevels, collect_level, load_membership

    schools, document = load_schools(), load_membership()
    aliases, _, scope = collect_identity(
        schools, "men", "independent", 2025, document=document, programmes=["utrgv"]
    )
    assert scope.level == "d1"
    assert opponent_slug("Charleston", aliases, scope=scope, owner="utrgv") == (
        "charleston-south-carolina"
    )
    d1 = stanzas_at_level(schools, "men", "d1", 2025, document=document)
    # the identity map is the Division I table's, not every level's
    assert set(aliases.values()) <= {programme_slug(s.name) for s in d1}
    assert (
        shard_stanzas(
            schools, "2025-men-independent", programmes=["utrgv"], document=document
        )
        == d1
    )
    # a structural collect of programmes at two levels is refused by name
    with pytest.raises(MixedLevels) as mixed:
        collect_level(
            schools,
            "men",
            "independent",
            2025,
            programmes=["utrgv", "harding"],
            document=document,
        )
    assert mixed.value.levels == {"utrgv": "d1", "harding": "d2"}
    assert "utrgv (d1)" in str(mixed.value) and "harding (d2)" in str(mixed.value)
    # a profiled conference keeps its own level whatever is asked of it
    assert (
        collect_level(
            schools, "men", "GAC", 2025, programmes=["utrgv"], document=document
        )
        == "d2"
    )


def test_the_shard_readers_read_a_structural_files_level_off_its_programmes(
    tmp_path, monkeypatch
):
    """sweep_opponent_slugs and check_box_scores re-read a stored file in the
    table its collect used; for a structural shard that is its programmes'
    level, read off the file (``shard_programmes``)."""
    import json

    from scripts import check_box_scores, sweep_opponent_slugs
    from src.config import load_schools
    from src.membership import load_membership, shard_programmes

    schools, document = load_schools(), load_membership()
    payload = {
        "programmes": [{"slug": "utrgv"}],
        "fixtures": [{"id": "a", "date": "2025-09-02", "home": "utrgv", "away": "x"}],
    }
    assert shard_programmes(payload) == ["utrgv"]
    levelled = shard_stanzas(
        schools, "2025-men-independent", programmes=["utrgv"], document=document
    )
    assert levelled == stanzas_at_level(schools, "men", "d1", 2025, document=document)
    assert levelled != shard_stanzas(schools, "2025-men-independent", document=document)

    for layer in ("fixtures", "matches"):
        (tmp_path / "data" / layer).mkdir(parents=True)
    (tmp_path / "data" / "fixtures" / "2025-men-independent.json").write_text(
        json.dumps(payload)
    )
    (tmp_path / "data" / "matches" / "2025-men-independent.json").write_text(
        json.dumps({"matches": {}})
    )
    for module, run in (
        (sweep_opponent_slugs, sweep_opponent_slugs.sweep),
        (check_box_scores, check_box_scores.compare),
    ):
        asked: list[list[str]] = []
        real = module.shard_stanzas

        def spy(*args, programmes=(), _asked=asked, _real=real, **kwargs):
            _asked.append(list(programmes))
            return _real(*args, programmes=programmes, **kwargs)

        monkeypatch.setattr(module, "shard_stanzas", spy)
        run(tmp_path)
        assert asked == [["utrgv"]], module.__name__
