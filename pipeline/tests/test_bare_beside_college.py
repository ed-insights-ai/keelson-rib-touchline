"""A bare name beside a "College" name: Colorado and Colorado College.

Colorado College (Mountain West, an affiliate in women's soccer) folds to
``colorado``, the key Colorado (Big 12) claims bare, and both are Division I
women's programmes in 2026. The institution-word rule
(``institution_split_keys``) splits that key and holds each worded spelling
under its institution key, which is right for "Colorado College"; but it
also withdraws the bare key, so "Colorado" resolves to neither programme and
check-membership refuses Colorado's own name as an ambiguous identity.
Renaming around the fold would file every printed "Colorado College" under
Colorado (the Boston failure).

Whether a bare name may also mean the worded school is a fact about how
sites print it, which no rule can read: peers print "Union" for Union
College, so bare "Union" beside Union College and Union University stays
refused, but nobody prints "Colorado" for Colorado College. So the stanza
says it: ``keep_institution_word = true`` holds the stanza's worded
spellings under their institution keys alone, and they take no part in the
fold, so nothing splits "colorado" and bare "Colorado" stays Colorado's.
Without the flag every verdict is the one it was, so every shipped
resolution is unchanged, which the last test proves table by table against
the rule as it was: only the claims of a stanza that sets the flag are new.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src import membership, sidearm_live
from src.config import SchoolConfig, load_schools, programme_slug
from src.sidearm_live import (
    _identity_key,
    _institution_key,
    identity_aliases,
    identity_ambiguities,
    identity_collisions,
    institution_split_keys,
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
        gender="women",
        **fields,  # type: ignore[arg-type]
    )


COLORADO = _school("Colorado", "BIG12", abbreviation="COLO")
COLORADO_COLLEGE = _school(
    "Colorado College", "MW", abbreviation="CC", keep_institution_word=True
)
TABLE = [COLORADO, COLORADO_COLLEGE, _school("Wyoming", "MW")]


def _document() -> dict[str, object]:
    def window(conference: str) -> list[dict[str, object]]:
        return [
            {
                "conference": conference,
                "from_season": 2026,
                "to_season": 2026,
                "source": "test fixture",
            }
        ]

    return {
        "version": 1,
        "seasons": {"from": 2026, "to": 2026},
        "conferences": ["BIG12", "MW", "independent", "non_member"],
        "conference_profiles": {
            "BIG12": {"level": "d1", "names": ["Big 12 Conference"]},
            "MW": {"level": "d1", "names": ["Mountain West Conference"]},
        },
        "memberships": {
            "colorado": {"women": window("BIG12")},
            "colorado-college": {"women": window("MW")},
            "wyoming": {"women": window("MW")},
        },
    }


def test_without_the_flag_the_pair_is_refused_as_before():
    table = [COLORADO, replace(COLORADO_COLLEGE, keep_institution_word=False), TABLE[2]]
    assert institution_split_keys(table, "women") == {"colorado"}
    assert "colorado" not in identity_aliases(table, "women")
    errors = membership.validate(_document(), schools=table)
    assert len(errors) == 1
    assert errors[0].startswith(
        "ambiguous identity (women, d1, seasons 2026): 'colorado' is claimed "
        "bare by colorado (name)"
    )


def test_the_kept_word_holds_the_college_apart_and_leaves_the_bare_key_alone():
    assert institution_split_keys(TABLE, "women") == frozenset()
    aliases = identity_aliases(TABLE, "women")
    assert aliases["colorado"] == "colorado"
    assert aliases["colorado college"] == "colorado-college"
    assert "colorado" not in {
        key for key, slug in aliases.items() if slug == "colorado-college"
    }


@pytest.mark.parametrize(
    ("printed", "slug"),
    [
        ("Colorado", "colorado"),
        ("University of Colorado", "colorado"),
        ("Colorado College", "colorado-college"),
        ("Colorado Coll.", "colorado-college"),
        ("Colorado College (Colo.)", "colorado-college"),
    ],
)
def test_printed_text_resolves_to_its_own_programme(printed: str, slug: str):
    aliases = identity_aliases(TABLE, "women")
    assert opponent_slug(printed, aliases) == slug
    scope = resolution_scope(
        TABLE,
        "women",
        {"colorado-college", "wyoming"},
        conference="MW",
        season=2026,
        level="d1",
    )
    assert opponent_slug(printed, aliases, scope=scope) == slug


def test_with_no_bare_claimant_the_bare_name_is_never_the_college():
    alone = [COLORADO_COLLEGE]
    aliases = identity_aliases(alone, "women")
    assert opponent_slug("Colorado", aliases) == "colorado"  # minted from the text
    assert opponent_slug("Colorado College", aliases) == "colorado-college"


def test_check_membership_accepts_the_pair():
    assert identity_ambiguities(TABLE) == []
    assert identity_collisions(TABLE) == []
    assert membership.validate(_document(), schools=TABLE) == []


def test_two_stanzas_claiming_the_kept_spelling_still_collide():
    clash = [*TABLE, _school("Tigers", "MW", aliases=["Colorado College"])]
    assert identity_collisions(clash) == [
        (
            "women",
            "colorado college",
            [("colorado-college", "name"), ("tigers", "alias")],
        )
    ]


def test_the_flag_on_a_stanza_with_no_worded_spelling_is_refused():
    table = [replace(COLORADO, keep_institution_word=True), *TABLE[1:]]
    errors = membership.validate(_document(), schools=table)
    assert errors == [
        "colorado:women sets keep_institution_word, but none of its claimed "
        "spellings carries an institution word (University, College)"
    ]


def test_the_flag_is_read_from_schools_toml(tmp_path):
    config = tmp_path / "schools.toml"
    config.write_text(
        '[[schools]]\nname = "Colorado College"\nabbreviation = "CC"\n'
        'conference = "MW"\ngender = "women"\nkeep_institution_word = true\n',
        encoding="utf-8",
    )
    [school] = load_schools(config)
    assert school.keep_institution_word is True


def _claim_keys_as_it_was(candidate: str, split: frozenset[str], **_: object):
    """``_claim_keys`` before ``keep_institution_word``, verbatim."""
    key = _identity_key(candidate)
    if not key:
        return ()
    if key not in split:
        return (key,)
    institution = _institution_key(candidate)
    return (institution,) if institution and institution != key else ()


def test_every_shipped_resolution_is_unchanged(monkeypatch):
    """Table by table, men's and women's, the identity map, the scope's
    claims and check-membership's verdicts are what the rule as it was
    builds from every stanza that does not keep its institution word; a
    stanza that keeps it adds its own claims and changes nobody else's."""
    schools = load_schools()
    document = membership.load_membership()
    tables = list(membership.level_scopes(schools, document=document))
    assert {gender for gender, *_ in tables} == {"men", "women"}
    kept = {
        programme_slug(school.name)
        for school in schools
        if school.keep_institution_word
    }

    def built(*, keepers: bool):
        found = []
        for gender, _, _, table in tables:
            stanzas = [
                school
                for school in table
                if keepers or programme_slug(school.name) not in kept
            ]
            members = {programme_slug(school.name) for school in stanzas}
            scope = resolution_scope(
                stanzas, gender, members, conference="X", season=2026, level="d1"
            )
            found.append(
                (
                    {
                        key: slug
                        for key, slug in identity_aliases(stanzas, gender).items()
                        if slug not in kept
                    },
                    {
                        key: slug
                        for key, slug in scope.claims.items()
                        if slug not in kept
                    },
                    institution_split_keys(stanzas, gender),
                    identity_collisions(stanzas),
                    identity_ambiguities(stanzas),
                )
            )
        return found

    now = built(keepers=True)
    monkeypatch.setattr(sidearm_live, "_claim_keys", _claim_keys_as_it_was)
    assert built(keepers=False) == now
