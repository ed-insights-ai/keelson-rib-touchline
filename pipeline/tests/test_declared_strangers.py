"""Spellings schools.toml declares NOT a programme at one level.

The residue no general rule reads. Measured 2026-11-16 by replaying the 848
Division I and 2,313 Division II archived schedule pages: 7 Division I and
13 Division II sides resolved to a programme of the level although the row's
own evidence (opponent link host, venue, no twin on the programme's page)
names another school ("Columbia College" on South Carolina's page is
Columbia College of Columbia, S.C.; "Shattuck-St. Mary's U19" is a
Minnesota school's U19 side). The general rule that suggested itself, a
"College" in the text against "University" in the programme's name, was
measured first and refused: of the 14 rows it would change, 11 are the
programme (renamed schools "Tusculum College", "Thomas More College",
"Mississippi Christian University"; misprints "Kentucky Wesleyan
University", "Truman College"). So each row set is declared, with its
evidence, in ``[[not_a_programme]]``; the replay with the list changes
exactly those 20 sides and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.collect_board import collect_identity
from src.config import (
    DeclaredStranger,
    SchoolConfig,
    load_declared_strangers,
    load_schools,
)
from src.membership import load_membership, validate
from src.programmes import load_programmes, programme_points
from src.sidearm_live import (
    declared_form,
    declared_stranger_errors,
    identity_aliases,
    opponent_slug,
    resolution_scope,
)


@pytest.fixture(scope="module")
def identity():
    schools = load_schools()
    document = load_membership()
    points = programme_points(load_programmes())
    cache: dict[tuple[str, str, int, str, bool], tuple[dict[str, str], object]] = {}

    def resolve(
        printed: str,
        owner: str,
        conference: str,
        season: int,
        gender: str,
        *,
        declared: bool = True,
    ) -> str:
        key = (gender, conference, season, owner, declared)
        if key not in cache:
            aliases, _, scope = collect_identity(
                schools,
                gender,
                conference,
                season,
                document=document,
                points=points,
                programmes=(owner,),
                declared=None if declared else [],
            )
            cache[key] = (aliases, scope)
        aliases, scope = cache[key]
        return opponent_slug(printed, aliases, scope=scope, owner=owner)  # type: ignore[arg-type]

    return resolve


# (printed, page owner, conference, season, gender, slug before, slug declared)
ROWS = [
    # Division I
    (
        "University of Health Sciences & Pharmacy in St. Louis",
        "lindenwood",
        "OVC",
        2023,
        "men",
        "saint-louis",
        "health-sciences-and-pharmacy-saint-louis",
    ),
    (
        "Charleston (Exhibition)",
        "marshall",
        "SUNBELT",
        2026,
        "men",
        "charleston-south-carolina",
        "charleston-wv",
    ),
    (
        "Columbia College",
        "south-carolina",
        "SUNBELT",
        2026,
        "men",
        "columbia",
        "columbia-sc",
    ),
    (
        "Jefferson College",
        "southern-indiana",
        "OVC",
        2025,
        "men",
        "jefferson",
        "jefferson-mo",
    ),
    (
        "St. Joseph's",
        "stony-brook",
        "CAA",
        2023,
        "men",
        "saint-josephs",
        "saint-josephs-ny",
    ),
    # The twin is on Division II St. Mary's (Texas)'s page the same day.
    (
        "St. Mary's (Exhibition)",
        "utrgv",
        "WAC",
        2023,
        "men",
        "saint-marys-california",
        "saint-marys",
    ),
    # UTRGV's 2025 independent collect resolves at Division I (2a66610), so
    # the same printed text reads as Saint Mary's of California there too;
    # the twin is again on St. Mary's (Texas)'s page (2025-08-19, Edinburg).
    (
        "St. Mary's (Exhibition)",
        "utrgv",
        "independent",
        2025,
        "men",
        "saint-marys-california",
        "saint-marys",
    ),
    # Division II
    (
        "Lincoln College",
        "dominican-of-california",
        "PACWEST",
        2022,
        "women",
        "lincoln",
        "lincoln-il",
    ),
    (
        "University of California",
        "dominican-of-california",
        "PACWEST",
        2024,
        "men",
        "california-pa",
        "california",
    ),
    ("Maryville College", "king", "CC", 2026, "women", "maryville", "maryville-tn"),
    (
        "Jefferson College (Scrimmage)",
        "lincoln",
        "GLVC",
        2026,
        "women",
        "jefferson",
        "jefferson-mo",
    ),
    (
        "Shattuck-St. Mary's U19",
        "msu-moorhead",
        "NSIC",
        2024,
        "women",
        "saint-marys",
        "shattuck-saint-marys",
    ),
    (
        "Shattuck-St. Mary's U19",
        "minnesota-crookston",
        "NSIC",
        2025,
        "women",
        "saint-marys",
        "shattuck-saint-marys",
    ),
    (
        "Shattuck - St. Mary’s U19",
        "southwest-minnesota-state",
        "NSIC",
        2025,
        "women",
        "saint-marys",
        "shattuck-saint-marys",
    ),
    (
        "Shattuck-St. Mary's (Exhibition)",
        "minnesota-crookston",
        "NSIC",
        2026,
        "women",
        "saint-marys",
        "shattuck-saint-marys",
    ),
    (
        "Columbia College",
        "missouri-st-louis",
        "GLVC",
        2023,
        "men",
        "columbia",
        "columbia-mo",
    ),
    (
        "Columbia College",
        "missouri-st-louis",
        "GLVC",
        2023,
        "women",
        "columbia",
        "columbia-mo",
    ),
    (
        "Notre Dame de Namur",
        "southern-nazarene",
        "GAC",
        2017,
        "men",
        "notre-dame-college",
        "notre-dame-de-namur",
    ),
    (
        "Saint Mary's",
        "stanislaus-state",
        "CCAA",
        2022,
        "men",
        "saint-marys",
        "saint-marys-california",
    ),
]


@pytest.mark.parametrize(
    ("printed", "owner", "conference", "season", "gender", "before", "after"), ROWS
)
def test_a_declared_spelling_mints_its_stranger_slug(
    identity,
    printed: str,
    owner: str,
    conference: str,
    season: int,
    gender: str,
    before: str,
    after: str,
) -> None:
    assert (
        identity(printed, owner, conference, season, gender, declared=False) == before
    )
    assert identity(printed, owner, conference, season, gender) == after


# Untouched: the same spellings on a page the declaration is not limited to,
# the namesakes the declared rows were read as, and the renamed schools the
# refused institution-word rule would have broken.
UNCHANGED = [
    ("Columbia College (S.C.)", "winthrop", "BIGSOUTH", 2026, "men", "columbia-sc"),
    ("Columbia College", "winthrop", "BIGSOUTH", 2026, "men", "columbia"),
    ("St. Joseph's", "loyola-maryland", "PATRIOT", 2023, "men", "saint-josephs"),
    (
        "Charleston",
        "boston-university",
        "PATRIOT",
        2025,
        "men",
        "charleston-south-carolina",
    ),
    (
        "Charleston (Exhibition)",
        "west-virginia",
        "SUNBELT",
        2026,
        "men",
        "charleston-south-carolina",
    ),
    ("Saint Mary's", "cal-state-la", "CCAA", 2022, "men", "saint-marys"),
    ("Maryville", "cedarville", "G-MAC", 2023, "women", "maryville"),
    ("Jefferson", "adelphi", "NE10", 2024, "women", "jefferson"),
    ("Tusculum College", "lee", "GSC", 2016, "men", "tusculum"),
    ("Thomas More College", "trevecca", "G-MAC", 2023, "men", "thomas-more"),
    (
        "Kentucky Wesleyan University",
        "trevecca",
        "GSC",
        2026,
        "women",
        "kentucky-wesleyan",
    ),
    ("Harding University", "lee", "GSC", 2024, "women", "harding"),
    ("Boston College", "boston-university", "PATRIOT", 2025, "men", "boston-college"),
    ("Boston University", "holy-cross", "PATRIOT", 2026, "men", "boston-university"),
]


@pytest.mark.parametrize(
    ("printed", "owner", "conference", "season", "gender", "slug"), UNCHANGED
)
def test_what_no_declaration_reaches(
    identity,
    printed: str,
    owner: str,
    conference: str,
    season: int,
    gender: str,
    slug: str,
) -> None:
    assert identity(printed, owner, conference, season, gender) == slug


def test_the_whole_spelling_is_matched_case_spacing_and_apostrophes_aside() -> None:
    assert declared_form("Shattuck-St. Mary's U19") == declared_form(
        "Shattuck - St. Mary’s  u19"
    )
    assert declared_form("University of Health Sciences & Pharmacy in St. Louis") == (
        "university of health sciences and pharmacy in st louis"
    )
    # A parenthetical is part of the spelling: the bare text is not declared.
    assert declared_form("Charleston (Exhibition)") != declared_form("Charleston")


@pytest.mark.parametrize(
    "variant",
    [
        "Charleston(Exhibition)",
        "Charleston ( Exhibition )",
        "Charleston  (Exhibition)",
        "charleston (EXHIBITION) ",
    ],
)
def test_spacing_around_a_parenthesis_is_not_part_of_the_spelling(
    identity, variant: str
) -> None:
    assert declared_form(variant) == "charleston (exhibition)"
    assert identity(variant, "marshall", "SUNBELT", 2026, "men") == "charleston-wv"


def test_what_the_parenthetical_says_still_counts() -> None:
    assert declared_form("Charleston(Exhibition)") != declared_form("Charleston")
    assert declared_form("Charleston(Exh.)") != declared_form("Charleston (Exhibition)")
    assert declared_form("St. Mary's(Exhibition)(DH)") == "st marys (exhibition) (dh)"


def test_schools_toml_declarations_are_valid() -> None:
    declared = load_declared_strangers()
    assert len(declared) == 16
    assert all(entry.source for entry in declared)
    errors = declared_stranger_errors(
        declared, load_schools(), document=load_membership()
    )
    assert errors == []


def test_a_declaration_without_its_evidence_is_refused(tmp_path: Path) -> None:
    config = tmp_path / "schools.toml"
    config.write_text(
        '[[not_a_programme]]\nlevel = "d2"\nspelling = "Somewhere College"\n'
        'slug = "somewhere"\n'
    )
    with pytest.raises(ValueError, match="no source"):
        load_declared_strangers(config)


def _entry(**fields: str) -> DeclaredStranger:
    base = {
        "level": "d1",
        "spelling": "Nowhere College",
        "slug": "nowhere",
        "source": "x",
    }
    base.update(fields)
    return DeclaredStranger(**base)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (_entry(level="naia"), "level must be one of"),
        (_entry(slug="Nowhere College"), "is not a slug"),
        # The level's own programme: the declaration would resolve to it.
        (_entry(slug="columbia"), "is a programme's at d1"),
        (_entry(owner="tusculum"), "is no programme at d1"),
        # A spelling a Division I stanza claims, declared for every page.
        (_entry(spelling="Saint Mary's"), "claims this spelling at d1"),
        # A resolving abbreviation is a claim too: an ownerless "SNHU" would
        # overrule Southern New Hampshire's on every Division II page.
        (
            _entry(level="d2", spelling="SNHU", slug="snhu-stranger"),
            "southern-new-hampshire claims this spelling at d2",
        ),
    ],
)
def test_check_membership_refuses_a_bad_declaration(
    entry: DeclaredStranger, message: str
) -> None:
    errors = declared_stranger_errors(
        [entry], load_schools(), document=load_membership()
    )
    assert any(message in error for error in errors), errors


def test_a_display_only_abbreviation_is_no_claim() -> None:
    """Saint Mary's of California prints "SMC" but does not resolve it
    (Saint Michael's shares it), so declaring it claims nothing away."""
    schools = load_schools()
    smc = next(s for s in schools if s.name == "Saint Marys California")
    assert smc.abbreviation == "SMC" and not smc.abbreviation_resolves
    entry = _entry(spelling="SMC", slug="smc-stranger")
    assert declared_stranger_errors([entry], schools, document=load_membership()) == []


def test_check_membership_reports_through_validate() -> None:
    document = load_membership()
    errors = validate(
        document, schools=load_schools(), strangers=[_entry(slug="columbia")]
    )
    assert any("is a programme's at d1" in error for error in errors)


def test_a_declaration_may_name_another_levels_programme_and_be_owner_limited() -> None:
    schools, document = load_schools(), load_membership()
    entries = [
        # Another level's programme slug: Division I Cal on a Division II page.
        _entry(level="d2", spelling="Golden Bears", slug="california"),
        # The same spelling for two owners, and once more for every page.
        _entry(spelling="Saint Mary's", owner="utrgv", slug="saint-marys"),
        _entry(spelling="Saint Mary's", owner="santa-clara", slug="saint-marys"),
    ]
    assert declared_stranger_errors(entries, schools, document=document) == []
    twice = [*entries, entries[1]]
    assert any(
        "declared twice" in error
        for error in declared_stranger_errors(twice, schools, document=document)
    )


def _school(name: str, conference: str, **fields: object) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=str(fields.pop("abbreviation", "")),
        conference=conference,
        prefix="",
        base_url="",
        **fields,  # type: ignore[arg-type]
    )


def test_only_the_collecting_levels_declarations_apply() -> None:
    schools = [_school("Columbia", "IVY")]
    aliases = identity_aliases(schools, "men")
    entries = [
        _entry(
            level="d1",
            spelling="Columbia College",
            owner="south-carolina",
            slug="columbia-sc",
        ),
        _entry(level="d2", spelling="Columbia College", slug="columbia-mo"),
    ]
    d1 = resolution_scope(
        schools,
        "men",
        set(),
        conference="IVY",
        season=2025,
        level="d1",
        declared=entries,
    )
    d2 = resolution_scope(
        schools,
        "men",
        set(),
        conference="IVY",
        season=2025,
        level="d2",
        declared=entries,
    )
    plain = resolution_scope(
        schools, "men", set(), conference="IVY", season=2025, level="d1"
    )
    printed = "Columbia College"
    assert (
        opponent_slug(printed, aliases, scope=d1, owner="south-carolina")
        == "columbia-sc"
    )
    assert opponent_slug(printed, aliases, scope=d1, owner="clemson") == "columbia"
    assert opponent_slug(printed, aliases, scope=d2, owner="clemson") == "columbia-mo"
    assert (
        opponent_slug(printed, aliases, scope=plain, owner="south-carolina")
        == "columbia"
    )
    assert opponent_slug(printed, aliases) == "columbia"
    assert "declared" in d1.fingerprint()
    assert "declared" not in plain.fingerprint()
    assert d1.fingerprint()["declared"] != d2.fingerprint()["declared"]
