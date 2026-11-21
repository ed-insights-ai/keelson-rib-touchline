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


def test_an_unflagged_claim_of_the_kept_spelling_collides_with_no_bare_name():
    # No stanza claims bare "Colorado", so nothing splits "colorado": the
    # unflagged alias registers under the folded key while the flagged
    # college holds "colorado college". Lookup reads the institution key
    # first, so the alias would silently resolve to Colorado College.
    table = [
        COLORADO_COLLEGE,
        _school("Wyoming", "MW"),
        _school("Tigers", "MW", aliases=["Colorado College"]),
    ]
    assert institution_split_keys(table, "women") == frozenset()
    aliases = identity_aliases(table, "women")
    assert opponent_slug("Colorado College", aliases) == "colorado-college"
    assert identity_collisions(table) == [
        (
            "women",
            "colorado college",
            [("colorado-college", "name"), ("tigers", "alias")],
        )
    ]
    document = _document()
    del document["memberships"]["colorado"]
    document["memberships"]["tigers"] = document["memberships"]["wyoming"]
    errors = membership.validate(document, schools=table)
    assert any("colorado college" in error for error in errors), errors


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


# The rule as it was before ``keep_institution_word`` (merge base f81e361,
# ``git show f81e361:pipeline/src/sidearm_live.py``): the three functions the
# flag changed, verbatim but for their names, docstrings and the module
# prefix on the helpers they call. ``identity_aliases``, ``resolution_scope``
# and ``identity_ambiguities`` reach them through the module, so patching
# these in rebuilds every table exactly as the merge base did.


def _institution_split_keys_as_it_was(
    schools: list[SchoolConfig], gender: str | None = None
) -> frozenset[str]:
    owners: dict[str, set[str]] = {}
    worded: set[str] = set()
    for school in schools:
        if gender is not None and school.gender != gender:
            continue
        slug = programme_slug(school.name)
        for candidate in sidearm_live._identity_spellings(school):
            key = _identity_key(candidate)
            if not key:
                continue
            owners.setdefault(key, set()).add(slug)
            if _institution_key(candidate) not in ("", key):
                worded.add(key)
    return frozenset(key for key in worded if len(owners[key]) > 1)


def _claim_keys_as_it_was(
    candidate: str, split: frozenset[str], **_: object
) -> tuple[str, ...]:
    key = _identity_key(candidate)
    if not key:
        return ()
    if key not in split:
        return (key,)
    institution = _institution_key(candidate)
    return (institution,) if institution and institution != key else ()


def _identity_collisions_as_it_was(
    schools: list[SchoolConfig],
) -> list[tuple[str, str, list[tuple[str, str]]]]:
    splits = sidearm_live._gender_splits(schools)
    claims: dict[tuple[str, str], dict[str, list[tuple[str, str]]]] = {}
    for school in schools:
        slug = programme_slug(school.name)
        for label, candidate in sidearm_live._claimed_fields(school):
            key = _identity_key(candidate)
            if not key:
                continue
            if key in splits[school.gender]:
                institution = _institution_key(candidate)
                if not institution or institution == key:
                    continue
                key = institution
            owners = claims.setdefault((school.gender, key), {})
            owners.setdefault(slug, []).append((slug, label))
    collisions = []
    for (gender, key), owners in claims.items():
        if len(owners) > 1:
            collisions.append(
                (gender, key, [pair for pairs in owners.values() for pair in pairs])
            )
    return collisions


def _shipped_tables(*, keepers: bool) -> list[tuple]:
    """Every shipped resolution table (each gender, level and season
    ``level_scopes`` yields), as the identity map, the scope's claims, the
    split keys, the collisions and the ambiguities the module's current
    functions build; without ``keepers``, from the stanzas that do not keep
    their institution word alone. Slugs of stanzas that keep it are left
    out of the maps either way: only their own claims may be new."""
    schools = load_schools()
    document = membership.load_membership()
    tables = list(membership.level_scopes(schools, document=document))
    assert {gender for gender, *_ in tables} == {"men", "women"}
    assert {level for _, level, *_ in tables} >= {"d1", "d2"}
    kept = {
        programme_slug(school.name)
        for school in schools
        if school.keep_institution_word
    }
    found = []
    for gender, level, season, table in tables:
        stanzas = [
            school
            for school in table
            if keepers or programme_slug(school.name) not in kept
        ]
        members = {programme_slug(school.name) for school in stanzas}
        scope = resolution_scope(
            stanzas, gender, members, conference="X", season=season, level=level
        )
        found.append(
            (
                (gender, level, season),
                {
                    key: slug
                    for key, slug in sidearm_live.identity_aliases(
                        stanzas, gender
                    ).items()
                    if slug not in kept
                },
                {key: slug for key, slug in scope.claims.items() if slug not in kept},
                sidearm_live.institution_split_keys(stanzas, gender),
                sidearm_live.identity_collisions(stanzas),
                sidearm_live.identity_ambiguities(stanzas),
            )
        )
    return found


def _as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sidearm_live, "institution_split_keys", _institution_split_keys_as_it_was
    )
    monkeypatch.setattr(sidearm_live, "_claim_keys", _claim_keys_as_it_was)
    monkeypatch.setattr(
        sidearm_live, "identity_collisions", _identity_collisions_as_it_was
    )


def test_every_shipped_resolution_is_unchanged(monkeypatch):
    """Table by table, men's and women's, at every level and season, the
    identity map, the scope's claims and check-membership's verdicts are
    what the rule as it was builds from every stanza that does not keep its
    institution word; a stanza that keeps it adds its own claims and
    changes nobody else's."""
    now = _shipped_tables(keepers=True)
    with monkeypatch.context() as patched:
        _as_it_was(patched)
        before = _shipped_tables(keepers=False)
    for built_now, built_before in zip(now, before, strict=True):
        assert built_now == built_before, built_now[0]


def test_the_comparison_sees_a_rule_that_changes_shipped_tables(monkeypatch):
    # The comparison is only as good as its "before": with the flag test in
    # institution_split_keys inverted, every unflagged worded spelling
    # (Boston College, Boston University) stops splitting its folded key.
    def inverted(schools, gender=None):
        flipped = [
            replace(school, keep_institution_word=not school.keep_institution_word)
            for school in schools
        ]
        return _current_split(flipped, gender)

    _current_split = sidearm_live.institution_split_keys
    with monkeypatch.context() as patched:
        _as_it_was(patched)
        before = _shipped_tables(keepers=False)
    monkeypatch.setattr(sidearm_live, "institution_split_keys", inverted)
    assert _shipped_tables(keepers=True) != before
