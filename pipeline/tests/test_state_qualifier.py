"""A printed state qualifier is evidence of which school a name means.

Measured 2026-11-16 by replaying every archived schedule page at 10a1308
(848 Division I, 2,313 Division II, all read): the fold drops the
parenthetical before any route reads the name, so "Columbia College (S.C.)"
resolved to Columbia (New York), "Georgetown College (Ky.)" to Georgetown
(Washington, D.C.), "Holy Cross College (Ind.)" to Holy Cross (Worcester),
"St. Thomas University (Fla.)" and "St. Thomas (TX)" to St. Thomas
(Minnesota), and on Division II pages "Lincoln (Calif.)" to Lincoln of
Missouri and "Mary (N.D.)" to Maryville. The rule is checked after every
route (``_state_checked``): a programme in another state is refused and the
side mints ``{key}-{state}``; a key exactly one claimant of which is in the
printed state resolves to it ("Loyola (Md.)" everywhere). Every row below is
an archived row; the slug is what the twin on the other school's page, the
row's link host or its venue says.
"""

from __future__ import annotations

import pytest

from scripts.collect_board import collect_identity
from src.config import SchoolConfig, load_schools
from src.membership import load_membership
from src.sidearm_live import (
    identity_aliases,
    opponent_slug,
    printed_state,
    resolution_scope,
    state_qualifier,
)


@pytest.fixture(scope="module")
def identity():
    schools = load_schools()
    document = load_membership()
    cache: dict[tuple[str, str, int], tuple[dict[str, str], object]] = {}

    def resolve(printed: str, conference: str, season: int, gender: str = "men") -> str:
        key = (gender, conference, season)
        if key not in cache:
            aliases, _, scope = collect_identity(
                schools, gender, conference, season, document=document
            )
            cache[key] = (aliases, scope)
        aliases, scope = cache[key]
        return opponent_slug(printed, aliases, scope=scope)  # type: ignore[arg-type]

    return resolve


@pytest.mark.parametrize(
    ("inner", "state"),
    [
        ("S.C.", "SC"),
        ("Ky.", "KY"),
        ("W.Va.", "WV"),
        ("W. Va.", "WV"),
        ("W.V.", "WV"),
        ("W,V.", "WV"),
        ("S.C", "SC"),
        ("Oh.", "OH"),
        ("TX", "TX"),
        ("Texas", "TX"),
        ("Tex.", "TX"),
        ("Tex", "TX"),
        ("Ohio", "OH"),
        ("New York", "NY"),
        ("MD", "MD"),
        ("Calif.", "CA"),
        ("D.C.", "DC"),
    ],
)
def test_a_state_is_read_in_every_spelling_the_archive_prints(
    inner: str, state: str
) -> None:
    assert state_qualifier(inner) == state


@pytest.mark.parametrize(
    "inner",
    [
        "Exhibition",
        "Exh.",
        "EX",
        "DH",
        "RV",
        "B.C.",
        "AUM",
        "Senior Day",
        "Syracuse",
        "in",
    ],
)
def test_a_parenthetical_that_is_not_a_state_names_none(inner: str) -> None:
    assert state_qualifier(inner) is None


def test_two_different_states_are_no_evidence() -> None:
    assert printed_state("St. Thomas (TX) (exh.)") == "TX"
    assert printed_state("Washington College (Md.)  (Exhibition)") == "MD"
    assert printed_state("Somewhere (Pa.) (N.Y.)") is None


# (printed, collecting conference, season, slug, the page that printed it)
REFUSED = [
    ("Columbia College (S.C.)", "BIGSOUTH", 2026, "columbia-sc", "winthrop"),
    ("Georgetown College (Ky.)", "ASUN", 2024, "georgetown-ky", "bellarmine"),
    ("Holy Cross College (Ind.)", "A10", 2025, "holy-cross-in", "loyola-chicago"),
    ("Holy Cross College (Ind.)", "MVC", 2026, "holy-cross-in", "western-michigan"),
    (
        "Washington College (Md.)  (Exhibition)",
        "NEC",
        2023,
        "washington-md",
        "howard",
    ),
    ("St. Thomas University (Fla.)", "AAC", 2026, "saint-thomas-fl", "fiu"),
    ("St. Thomas (TX) (exh.)", "OVC", 2023, "saint-thomas-tx", "hcu"),
    ("Charleston (W.Va.) (Exh.)", "SUNBELT", 2023, "charleston-wv", "west-virginia"),
    # A slug minted from text that equals a Division II programme's is checked
    # against that programme's state too: Union of Tennessee, Westminster of
    # Utah.
    ("Union College (Ky.)", "ASUN", 2026, "union-ky", "bellarmine"),
    ("Westminster College (MO)", "OVC", 2024, "westminster-mo", "lindenwood"),
]


@pytest.mark.parametrize(("printed", "conference", "season", "slug", "page"), REFUSED)
def test_a_programme_in_another_state_is_refused(
    identity, printed: str, conference: str, season: int, slug: str, page: str
) -> None:
    assert identity(printed, conference, season) == slug, page


# The one claimant of the bare word in the printed state: every Maryland twin
# is on Loyola Maryland's own page the same day.
CLAIMED = [
    ("Loyola (Md.)", "AE", 2026, "loyola-maryland"),  # umbc
    ("Loyola (Md.)", "SUNBELT", 2023, "loyola-maryland"),  # west-virginia
    ("Loyola (MD)", "IVY", 2023, "loyola-maryland"),  # princeton
    ("Loyola (MD) (Exh.)", "A10", 2026, "loyola-maryland"),  # george-washington
    ("Loyola (Md.)", "PATRIOT", 2026, "loyola-maryland"),  # holy-cross, as before
    # Loyola Chicago's A10 member alias "Loyola" makes it the Illinois
    # claimant of the bare word, read on any page that prints the state.
    ("Loyola (Ill.)", "OVC", 2025, "loyola-chicago"),
]


@pytest.mark.parametrize(("printed", "conference", "season", "slug"), CLAIMED)
def test_the_one_claimant_in_the_printed_state_is_the_school(
    identity, printed: str, conference: str, season: int, slug: str
) -> None:
    assert identity(printed, conference, season) == slug


# Unchanged: a matching state, a place-name parenthetical on a school of that
# state, a parenthetical that names no state, and the institution-word and
# level cases the rule must not touch.
UNCHANGED = [
    ("St. Thomas (Minn.)", "MVC", 2024, "st-thomas"),
    ("Saint Mary's (CA)", "MAAC", 2026, "saint-marys-california"),
    ("Saint Mary's (California)", "PAC12", 2023, "saint-marys-california"),
    ("Queens (N.C.)", "ASUN", 2023, "queens-charlotte"),
    ("Denver (Exhibition)", "WAC", 2025, "denver"),
    ("Denver (RV)", "BIGWEST", 2025, "denver"),
    ("Northern Kentucky  (DH)", "HORIZON", 2025, "northern-kentucky"),
    ("Boston College", "AE", 2025, "boston-college"),
    ("Boston University", "PATRIOT", 2026, "boston-university"),
    ("Charleston", "PATRIOT", 2025, "charleston-south-carolina"),
]


@pytest.mark.parametrize(("printed", "conference", "season", "slug"), UNCHANGED)
def test_what_the_rule_leaves_alone(
    identity, printed: str, conference: str, season: int, slug: str
) -> None:
    assert identity(printed, conference, season) == slug


# Division II rows (live data): the corrections the rule makes, and the head
# word it must not read as a claim.
D2 = [
    # academy-of-art 2022: Lincoln University of Oakland, not Lincoln (Mo.).
    ("Lincoln (Calif.)", "PACWEST", 2022, "women", "lincoln-ca"),
    # southern-nazarene 2016: the University of Mary, not Maryville ("MARY").
    ("Mary (N.D.)", "GAC", 2016, "men", "mary-nd"),
    # lincoln-memorial 2023: Union of Barbourville, not Union of Jackson, Tenn.
    ("Union College (Ky.)", "SAC", 2023, "men", "union-ky"),
    # The bare word is IUP's PSAC member alias; twins on IUP's pages.
    ("Indiana (Pa.)", "ECC", 2022, "women", "iup"),
    # The bare word is Concordia Irvine's PacWest member alias; twins on its
    # pages.
    ("Concordia (Calif.)", "GNAC", 2022, "women", "concordia-irvine"),
    # Concordia of Moorhead, no stanza: no twin on Concordia-St. Paul's pages,
    # and Concordia-St. Paul claims no bare "Concordia".
    ("Concordia College (Minn.)", "NSIC", 2024, "women", "concordia"),
    ("Concordia (Minn.)", "NSIC", 2026, "women", "concordia"),
    # A matching state and an institution word the stanza does not carry.
    ("Union (TN)", "SAC", 2024, "women", "union"),
    ("Harding University", "GSC", 2024, "women", "harding"),
    ("Simon Fraser (B.C.)", "GNAC", 2022, "women", "simon-fraser"),
    ("Lincoln (Pa.)", "CACC", 2024, "women", "lincoln-pa"),
]


@pytest.mark.parametrize(("printed", "conference", "season", "gender", "slug"), D2)
def test_division_ii_rows(
    identity, printed: str, conference: str, season: int, gender: str, slug: str
) -> None:
    assert identity(printed, conference, season, gender) == slug


def _school(name: str, conference: str, city: str, **fields: object) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=str(fields.pop("abbreviation", "")),
        conference=conference,
        prefix="",
        base_url="",
        city=city,
        **fields,  # type: ignore[arg-type]
    )


def test_the_runbooks_lincoln_example() -> None:
    """ "Lincoln (Pa.)" on a page whose table reads "Lincoln" as Missouri's.

    Not in the archive at 10a1308 (every printed "Lincoln (Pa.)" already
    resolved to lincoln-pa), so built: a men's table with no Lincoln (Pa.)
    stanza mints the qualified slug, and a women's table holding both picks
    the Pennsylvania claimant over the member the scope would have chosen.
    """
    missouri = _school(
        "Lincoln", "GLVC", "Jefferson City, Mo.", aliases=["Lincoln University"]
    )
    men = [missouri]
    scope = resolution_scope(men, "men", {"lincoln"}, conference="GLVC", season=2024)
    aliases = identity_aliases(men, "men")
    assert opponent_slug("Lincoln", aliases, scope=scope) == "lincoln"
    assert opponent_slug("Lincoln (Mo.)", aliases, scope=scope) == "lincoln"
    assert opponent_slug("Lincoln (Pa.)", aliases, scope=scope) == "lincoln-pa"

    women = [
        _school("Lincoln", "GLVC", "Jefferson City, Mo.", gender="women"),
        _school(
            "Lincoln PA",
            "CACC",
            "Lincoln University, Pa.",
            gender="women",
            member_aliases=["Lincoln University (Pa.)"],
        ),
    ]
    scope = resolution_scope(
        women, "women", {"lincoln"}, conference="GLVC", season=2024
    )
    aliases = identity_aliases(women, "women")
    assert opponent_slug("Lincoln", aliases, scope=scope) == "lincoln"
    assert opponent_slug("Lincoln (Pa.)", aliases, scope=scope) == "lincoln-pa"
    assert any("Lincoln (Pa.)" in note for note in scope.notes())


def test_a_stanza_with_no_state_behaves_as_before() -> None:
    nowhere = [_school("Simon Fraser", "GNAC", "Burnaby, B.C.")]
    scope = resolution_scope(
        nowhere, "men", {"simon-fraser"}, conference="GNAC", season=2024
    )
    aliases = identity_aliases(nowhere, "men")
    assert opponent_slug("Simon Fraser (Wash.)", aliases, scope=scope) == (
        "simon-fraser"
    )


def test_without_a_scope_nothing_changes() -> None:
    columbia = [_school("Columbia", "IVY", "New York, N.Y.")]
    assert opponent_slug("Columbia College (S.C.)", identity_aliases(columbia)) == (
        "columbia"
    )


def test_the_run_log_names_the_slug_the_state_check_gave() -> None:
    """The member route notes "Dominican (N.Y.)" as Dominican of California
    before the state check moves it to Dominican (N.Y.); the note it leaves
    must be the final one, since collect-board prints the scope's notes."""
    from src.programmes import load_programmes, programme_points

    aliases, _, scope = collect_identity(
        load_schools(),
        "women",
        "PACWEST",
        2024,
        document=load_membership(),
        points=programme_points(load_programmes()),
        programmes=("academy-of-art",),
    )
    printed = "Dominican (N.Y.)"
    slug = opponent_slug(printed, aliases, scope=scope, owner="academy-of-art")
    assert slug == "dominican"
    lines = [line for line in scope.notes() if repr(printed) in line]
    assert len(lines) == 1
    assert "read as dominican:" in lines[0]
    assert "dominican-of-california is in" in lines[0]
    # A text no later step changes keeps its first note.
    opponent_slug("Dominican", aliases, scope=scope, owner="academy-of-art")
    assert any(
        "'Dominican' read as dominican-of-california" in n for n in scope.notes()
    )
