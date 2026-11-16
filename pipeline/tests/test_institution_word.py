"""The institution word, kept where it is all that tells two schools apart.

The identity fold drops "university", "college" and "the", which is right
almost always ("Harding University" is Harding) and wrong exactly where the
word is the only difference: Boston College (ACC) and Boston University
(Patriot League) both fold to "boston". Before this rule the pair could not
both claim their own names (check-membership refused the collision), so the
stanzas were renamed around it and every schedule's "Boston College" and
"Boston University" minted the one stranger slug ``boston``.

The rule (``sidearm_live.institution_split_keys``): a folded key two or more
programmes of one table claim, where at least one claim carries an
institution word, is withdrawn, and each spelling that folds to it is held
under its institution key (the fold with the word kept, spelled one way and
moved to the end). Bare "Boston" then names neither school. The answer is a
set over the table's claims, so stanza order cannot change it.
"""

from __future__ import annotations

import copy
import itertools

from scripts.collect_board import collect_identity
from src import membership
from src.config import SchoolConfig, load_schools, programme_slug
from src.sidearm_live import (
    identity_aliases,
    identity_ambiguities,
    identity_collisions,
    institution_split_keys,
    opponent_slug,
    resolution_scope,
)


def _school(name: str, conference: str = "X", **fields: object) -> SchoolConfig:
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


def _document(windows: dict[str, str]) -> dict[str, object]:
    conferences = sorted(set(windows.values()))
    return {
        "version": 1,
        "seasons": {"from": 2024, "to": 2026},
        "conferences": [*conferences, "independent", "non_member"],
        "conference_profiles": {
            code: {"level": "d1", "names": [f"{code} Conference"]}
            for code in conferences
        },
        "memberships": {
            slug: {"men": [_window(code, 2024, 2026)]} for slug, code in windows.items()
        },
    }


# ── a pair that differs only by the institution word ───────────────────────

PAIR = [_school("Union College", "EAST"), _school("Union University", "WEST")]
PAIR_DOC = _document({"union-college": "EAST", "union-university": "WEST"})


def test_a_pair_split_by_the_institution_word_resolves_each_by_its_word():
    aliases = identity_aliases(PAIR, "men")
    assert institution_split_keys(PAIR, "men") == {"union"}
    assert aliases == {
        "union college": "union-college",
        "union university": "union-university",
    }
    for printed in (
        "Union College",
        "Union Coll.",
        "College of Union",
        "The Union College",
    ):
        assert opponent_slug(printed, aliases) == "union-college", printed
    for printed in (
        "Union University",
        "Union Univ.",
        "Union U.",
        "Union U",
        "University of Union",
    ):
        assert opponent_slug(printed, aliases) == "union-university", printed
    # Bare, the word names both schools, so it names neither.
    assert opponent_slug("Union", aliases) == "union"


def test_the_split_cannot_depend_on_stanza_order():
    forward = identity_aliases(PAIR, "men")
    backward = identity_aliases(list(reversed(PAIR)), "men")
    assert forward == backward


def test_check_membership_accepts_the_pair():
    assert identity_collisions(PAIR) == []
    assert identity_ambiguities(PAIR) == []
    assert membership.validate(PAIR_DOC, schools=PAIR) == []


def test_each_collect_scope_reads_the_pair_the_same_way():
    for conference in ("EAST", "WEST"):
        aliases, members, scope = collect_identity(
            PAIR, "men", conference, 2025, document=PAIR_DOC
        )
        assert "union" not in scope.claims
        assert "union" not in scope.claimants
        assert opponent_slug("Union College", aliases, scope=scope) == "union-college"
        assert opponent_slug("Union University", aliases, scope=scope) == (
            "union-university"
        )
        assert opponent_slug("Union", aliases, scope=scope) == "union"
        assert scope.notes() == []


def test_bare_word_never_reaches_the_distance_tiebreak():
    points = {"union-college": (42.8, -73.9), "union-university": (35.6, -88.8)}
    scope = resolution_scope(
        PAIR, "men", {"union-college"}, conference="EAST", season=2025, points=points
    )
    aliases = identity_aliases(PAIR, "men")
    assert (
        opponent_slug("Union", aliases, scope=scope, owner="union-college") == "union"
    )


# ── a triple ────────────────────────────────────────────────────────────────

TRIPLE = [
    _school("Alpha College"),
    _school("Alpha University"),
    _school("Alpha University College"),
]


def test_a_triple_split_by_the_institution_word_resolves_each_by_its_words():
    maps = [
        identity_aliases(list(order), "men") for order in itertools.permutations(TRIPLE)
    ]
    assert all(found == maps[0] for found in maps)
    aliases = maps[0]
    assert "alpha" not in aliases
    assert opponent_slug("Alpha College", aliases) == "alpha-college"
    assert opponent_slug("Alpha Univ.", aliases) == "alpha-university"
    assert opponent_slug("Alpha University College", aliases) == (
        "alpha-university-college"
    )
    assert opponent_slug("Alpha", aliases) == "alpha"
    assert identity_collisions(TRIPLE) == []


def test_a_third_stanza_claiming_the_word_bare_is_refused_as_ambiguous():
    triple = [*PAIR, _school("Union", "EAST")]
    document = _document(
        {"union-college": "EAST", "union-university": "WEST", "union": "EAST"}
    )
    assert membership.validate(document, schools=triple) == [
        "ambiguous identity (men, d1, seasons 2024-2026): 'union' is claimed "
        "bare by union (name), but only an institution word tells apart the "
        "programmes it folds to (union-college (name) and union-university "
        "(name)), so it resolves to none of them; drop the spelling or keep "
        "its institution word"
    ]
    aliases = identity_aliases(triple, "men")
    assert opponent_slug("Union", aliases) == "union"  # the text, not the stanza
    assert "union" not in aliases


# ── one spelling also claims the folded key bare ───────────────────────────


def test_an_alias_equal_to_the_folded_key_is_refused_and_resolves_nobody():
    claimed = [
        _school("Union College", "EAST", aliases=["Union"]),
        _school("Union University", "WEST"),
    ]
    errors = membership.validate(PAIR_DOC, schools=claimed)
    assert errors == [
        "ambiguous identity (men, d1, seasons 2024-2026): 'union' is claimed "
        "bare by union-college (alias), but only an institution word tells "
        "apart the programmes it folds to (union-college (name) and "
        "union-university (name)), so it resolves to none of them; drop the "
        "spelling or keep its institution word"
    ]
    for order in (claimed, list(reversed(claimed))):
        aliases = identity_aliases(order, "men")
        assert opponent_slug("Union", aliases) == "union"
        assert opponent_slug("Union College", aliases) == "union-college"
        assert opponent_slug("Union University", aliases) == "union-university"


def test_a_member_alias_may_read_the_bare_word_inside_its_conference():
    with_member_alias = [
        _school("Union College", "EAST", member_aliases=["Union"]),
        _school("Union University", "WEST"),
    ]
    assert membership.validate(PAIR_DOC, schools=with_member_alias) == []
    east = collect_identity(with_member_alias, "men", "EAST", 2025, document=PAIR_DOC)
    west = collect_identity(with_member_alias, "men", "WEST", 2025, document=PAIR_DOC)
    assert opponent_slug("Union", east[0], scope=east[2]) == "union-college"
    assert opponent_slug("Union", west[0], scope=west[2]) == "union"
    assert opponent_slug("Union University", east[0], scope=east[2]) == (
        "union-university"
    )


def test_two_stanzas_claiming_one_institution_key_still_collide():
    clash = [
        _school("Union College"),
        _school("Union Dutchmen", aliases=["College of Union"]),
    ]
    assert identity_collisions(clash) == [
        (
            "men",
            "union college",
            [("union-college", "name"), ("union-dutchmen", "alias")],
        )
    ]
    for order in (clash, list(reversed(clash))):
        assert "union college" not in identity_aliases(order, "men")


# ── the ordinary fold is untouched ─────────────────────────────────────────


def test_the_fold_still_applies_where_the_word_tells_nobody_apart():
    schools = [_school("Harding", aliases=["Harding University"]), *PAIR]
    aliases = identity_aliases(schools, "men")
    assert institution_split_keys(schools, "men") == {"union"}
    assert aliases["harding"] == "harding"
    assert "harding university" not in aliases
    for printed in (
        "Harding University",
        "Harding Univ.",
        "Harding",
        "The Harding University",
    ):
        assert opponent_slug(printed, aliases) == "harding", printed
    # One programme spelling its own key both ways splits nothing.
    lone = [_school("Harding", aliases=["Harding University"])]
    assert institution_split_keys(lone, "men") == frozenset()
    assert identity_aliases(lone, "men") == {"harding": "harding"}


def test_a_folded_key_every_claimant_spells_bare_is_an_ordinary_collision():
    bare = [_school("Lincoln"), _school("Lincoln Tigers", aliases=["Lincoln"])]
    assert institution_split_keys(bare, "men") == frozenset()
    assert identity_collisions(bare) == [
        ("men", "lincoln", [("lincoln", "name"), ("lincoln-tigers", "alias")])
    ]


# ── the shipped Division I pair ────────────────────────────────────────────

SCHOOLS = load_schools()
MEMBERSHIP = membership.load_membership()


def test_boston_college_and_boston_university_in_every_d1_2026_scope():
    for conference in ("ACC", "PATRIOT", "BIGEAST"):
        aliases, _, scope = collect_identity(
            SCHOOLS, "men", conference, 2026, document=MEMBERSHIP
        )
        for printed in ("Boston College", "Boston Coll."):
            assert opponent_slug(printed, aliases, scope=scope) == "boston-college"
        for printed in ("Boston University", "Boston U.", "Boston U", "Boston Univ."):
            assert opponent_slug(printed, aliases, scope=scope) == "boston-university"
        # Bare "Boston" names neither school, except inside the Patriot
        # League, where Boston University's member alias reads it (Lafayette
        # 2026, sidearm:lafayette:13995, a league game at Boston, Mass.).
        bare = "boston-university" if conference == "PATRIOT" else "boston"
        assert opponent_slug("Boston", aliases, scope=scope) == bare
        # "BC" is display-only: Bloomfield (Division II) prints it too.
        assert opponent_slug("BC", aliases, scope=scope) == "bc"


def test_a_bare_boston_alias_on_either_stanza_is_refused():
    for slug in ("boston-college", "boston-university"):
        schools = copy.deepcopy(SCHOOLS)
        stanza = next(
            s for s in schools if s.gender == "men" and programme_slug(s.name) == slug
        )
        stanza.aliases.append("Boston")
        errors = membership.validate(MEMBERSHIP, schools=schools)
        assert len(errors) == 1, errors
        assert errors[0].startswith(
            "ambiguous identity (men, d1, seasons 2016-2026): 'boston' is "
            f"claimed bare by {slug} (alias)"
        )
