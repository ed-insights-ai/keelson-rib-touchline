"""A collect resolves opponent text inside the conference-season it reads for.

Measured 2026-09-05 (tl-b3v, batch 5 backfill): Chaminade's 2025 schedule
page (goswords.com, game 8132) prints "Dominican" for Dominican of
California and "Concordia" for Concordia Irvine, both PacWest members. The
gender-wide map read the first as the CACC's Dominican, whose whole name it
is, and the second as an unresolved key, so each match sat in the PacWest
fixtures file twice: ``sidearm:chaminade:8132`` (dominican v chaminade)
beside ``sidearm:dominican-of-california:9578`` (dominican-of-california v
chaminade), and the dedupe never folded them because the slugs differ.

The rule: during a collect of conference C for season Y, a printed name a
member of C in Y claims (by name, alias, resolving abbreviation or member
alias) resolves to that member before any other programme. The member set
is the membership resolver's (``conference_members``), the scope applies to
every row of the collect, and a name no member claims resolves exactly as
before. ``display_name`` stays out of identity (tl-4an.31).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src import membership, presto
from src.config import SchoolConfig, load_schools
from src.membership import load_membership, resolution_stanzas
from src.sidearm_live import (
    LAYER_SCHEDULE,
    STATE_EMPTY,
    LayerOutcome,
    ProgrammeCollection,
    conference_members,
    hosted_other_match,
    identity_aliases,
    identity_collisions,
    level_identity_collisions,
    member_alias_collisions,
    opponent_slug,
    own_side_opponent,
    parse_schedule_page,
    programme_slug,
    resolution_scope,
)

FIXTURES = Path(__file__).parent / "fixtures"

SCHOOLS = load_schools()
MEMBERSHIP = load_membership()
MEN = identity_aliases(SCHOOLS, "men")


def _scope(conference: str, season: int):
    members = conference_members(
        SCHOOLS, "men", conference, season=season, document=MEMBERSHIP
    )
    return resolution_scope(
        SCHOOLS, "men", members, conference=conference, season=season
    )


def _chaminade_page(*opponents: str) -> str:
    """Chaminade's 2025 page, in the events-component shape, one row each."""
    events = [
        {
            "id": 8132 + index,
            "date": f"2025-09-{27 + index:02d}T12:30:00",
            "opponent": {"title": opponent},
            "location_indicator": "A",
            "is_conference": True,
            "schedule": {"title": "2025 Men's Soccer Schedule"},
            "result": {"status": "W", "team_score": 0, "opponent_score": 1},
        }
        for index, opponent in enumerate(opponents)
    ]
    component = {"type": "events", "data": events}
    return (
        "<html><head><title>2025 Men's Soccer Schedule - Chaminade</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )


# ── the rule, on the shipped config and membership ─────────────────────────


def test_the_member_set_is_the_membership_resolvers() -> None:
    pacwest = _scope("PACWEST", 2025)
    assert {"dominican-of-california", "concordia-irvine", "chaminade"} <= (
        pacwest.members
    )
    assert "dominican" not in pacwest.members
    assert "dominican" in _scope("CACC", 2025).members
    ecc = _scope("ECC", 2025)
    assert not {"dominican", "dominican-of-california"} & ecc.members


def test_dominican_under_pacwest_2025_is_the_pacwest_member() -> None:
    scope = _scope("PACWEST", 2025)
    assert opponent_slug("Dominican", MEN, scope=scope) == "dominican-of-california"
    # The same page prints a rank and the parenthetical the fold drops.
    assert opponent_slug("No. 4 Dominican", MEN, scope=scope) == (
        "dominican-of-california"
    )
    assert opponent_slug("Dominican (Calif.)", MEN, scope=scope) == (
        "dominican-of-california"
    )


def test_concordia_under_pacwest_2025_is_the_pacwest_member() -> None:
    scope = _scope("PACWEST", 2025)
    assert opponent_slug("Concordia", MEN, scope=scope) == "concordia-irvine"
    assert opponent_slug("Concordia University Irvine", MEN, scope=scope) == (
        "concordia-irvine"
    )


def test_dominican_under_cacc_2025_is_the_cacc_member_as_before() -> None:
    scope = _scope("CACC", 2025)
    assert opponent_slug("Dominican", MEN, scope=scope) == "dominican"
    assert opponent_slug("Dominican", MEN) == "dominican"
    assert scope.notes() == []


def test_dominican_under_ecc_2025_falls_to_todays_rule() -> None:
    # No ECC member claims the word, so the gender-wide map answers, and it
    # answers the way it did before the scope existed.
    scope = _scope("ECC", 2025)
    assert opponent_slug("Dominican", MEN, scope=scope) == "dominican"
    assert opponent_slug("Dominican", MEN, scope=scope) == opponent_slug(
        "Dominican", MEN
    )
    assert scope.notes() == []


def test_a_name_no_member_claims_resolves_exactly_as_before() -> None:
    scope = _scope("PACWEST", 2025)
    for published in (
        "Harding",
        "Lincoln Memorial",
        "Delta St.",
        "DBU",
        "Concordia St. Paul",
        "Dominican University of N.Y.",
        "Oklahoma Wesleyan (Exhibition)",
        "Hawaii Pacific",
        "Point Loma",
    ):
        assert opponent_slug(published, MEN, scope=scope) == opponent_slug(
            published, MEN
        ), published
    assert scope.notes() == []


def test_a_member_alias_enters_no_gender_wide_map() -> None:
    # Outside a PacWest collect the bare words read as they always did: the
    # incumbent by name, and an unresolved key for the Concordia nobody
    # claims gender-wide.
    assert "concordia" not in MEN
    assert MEN["dominican"] == "dominican"
    assert opponent_slug("Concordia", MEN) == "concordia"
    assert opponent_slug("Dominican", MEN) == "dominican"
    assert level_identity_collisions(SCHOOLS, document=MEMBERSHIP) == []
    assert member_alias_collisions(SCHOOLS) == []
    assert membership.validate(MEMBERSHIP, schools=SCHOOLS) == []


# ── the run log ─────────────────────────────────────────────────────────────


def test_the_scope_notes_each_re_pointed_text_once() -> None:
    scope = _scope("PACWEST", 2025)
    for published in ("Dominican", "Dominican", "#4 Dominican", "Concordia"):
        opponent_slug(published, MEN, scope=scope)
    # Chaminade's own name is claimed by a member too, but the gender-wide
    # map agrees, so nothing is noted for it.
    opponent_slug("Chaminade", MEN, scope=scope)
    assert scope.notes() == [
        "resolution: 'Dominican' read as dominican-of-california, "
        "a PACWEST 2025 member, not dominican",
        "resolution: 'Concordia' read as concordia-irvine, "
        "a PACWEST 2025 member, not concordia",
    ]


# ── the parsers read through the scope ──────────────────────────────────────


def test_the_chaminade_page_mints_the_match_under_the_members_slug() -> None:
    scope = _scope("PACWEST", 2025)
    fixtures = parse_schedule_page(
        _chaminade_page("Dominican", "Concordia"),
        page_url="https://goswords.com/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="chaminade",
        aliases=MEN,
        members=set(scope.members),
        scope=scope,
    )
    assert [
        (f["id"], f["home"], f["away"], f["conference_game"]) for f in fixtures
    ] == [
        ("sidearm:chaminade:8132", "dominican-of-california", "chaminade", True),
        ("sidearm:chaminade:8133", "concordia-irvine", "chaminade", True),
    ]
    # Without the scope the same page is the bug: the CACC incumbent and an
    # unresolved key, neither of which the dedupe can fold onto the member.
    unscoped = parse_schedule_page(
        _chaminade_page("Dominican", "Concordia"),
        page_url="https://goswords.com/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="chaminade",
        aliases=MEN,
        members=set(scope.members),
    )
    assert [f["home"] for f in unscoped] == ["dominican", "concordia"]


def test_a_two_team_row_on_the_members_own_page_reads_the_owner() -> None:
    # Dominican of California's own page, printing itself the way its peers
    # do: the row is its fixture, not a hosted other-match to skip.
    scope = _scope("PACWEST", 2025)
    owner = "dominican-of-california"
    row = "Dominican vs Chaminade"
    assert hosted_other_match(row, owner_slug=owner, aliases=MEN, scope=scope) is None
    assert own_side_opponent(row, owner_slug=owner, aliases=MEN, scope=scope) == (
        "Chaminade"
    )


def test_a_presto_page_is_byte_identical_under_a_scope_no_member_alias_touches():
    html = (FIXTURES / "prestosports_bridgeport_schedule_2025.html").read_text(
        encoding="utf-8"
    )
    scope = _scope("CACC", 2025)
    url = "https://www.ubknights.com/sports/msoc/2025-26/schedule"
    kwargs = dict(
        page_url=url,
        year=2025,
        owner_slug="bridgeport",
        aliases=MEN,
        members=set(scope.members),
    )
    assert presto.parse_schedule(html, **kwargs, scope=scope) == presto.parse_schedule(
        html, **kwargs
    )
    assert scope.notes() == []


# ── check-membership refuses a member alias a fellow member claims ──────────


def _school(name: str, conference: str, **fields: object) -> SchoolConfig:
    return replace(
        SchoolConfig(
            name=name,
            abbreviation=name,
            conference=conference,
            prefix="",
            base_url="",
            gender="men",
        ),
        **fields,
    )


def test_a_member_alias_may_be_another_conferences_whole_name() -> None:
    incumbent = _school("Dominican", "CACC")
    newcomer = _school(
        "Dominican of California", "PACWEST", member_aliases=["Dominican"]
    )
    assert identity_collisions([incumbent, newcomer]) == []
    assert member_alias_collisions([incumbent, newcomer]) == []


def test_a_member_alias_a_fellow_member_claims_is_refused() -> None:
    chaminade = _school("Chaminade", "PACWEST", aliases=["Dominican"])
    newcomer = _school(
        "Dominican of California", "PACWEST", member_aliases=["Dominican"]
    )
    assert member_alias_collisions([chaminade, newcomer]) == [
        (
            "men",
            "PACWEST",
            "dominican",
            [("chaminade", "alias"), ("dominican-of-california", "member_alias")],
        )
    ]
    # Two member aliases of one spelling in one conference collide too; the
    # same spelling in another gender's table does not.
    twin = _school("Dominican Twin", "PACWEST", member_aliases=["Dominican"])
    assert len(member_alias_collisions([twin, newcomer])) == 1
    assert member_alias_collisions([replace(twin, gender="women"), newcomer]) == []


def test_validate_names_a_member_alias_collision() -> None:
    document = {
        "version": 1,
        "seasons": {"from": 2025, "to": 2025},
        "conferences": ["PACWEST", "independent", "non_member"],
        "memberships": {},
    }
    chaminade = _school("Chaminade", "PACWEST", aliases=["Dominican"])
    newcomer = _school(
        "Dominican of California", "PACWEST", member_aliases=["Dominican"]
    )
    errors = membership.validate(document, schools=[chaminade, newcomer])
    assert any(
        error.startswith("member alias collision (men, PACWEST): 'dominican'")
        for error in errors
    ), errors


# ── collect builds one scope from the member set and threads it ────────────


def test_collect_threads_one_scope_built_from_the_seasons_members(
    monkeypatch, tmp_path: Path
) -> None:
    from scripts import collect_board

    schools = [
        SchoolConfig(
            name="Trevecca",
            abbreviation="TNU",
            conference="GSC",
            prefix="",
            base_url="https://trevecca.example",
            enabled=True,
            member_aliases=["Trojans"],
        ),
        SchoolConfig(
            name="Harding",
            abbreviation="HU",
            conference="GAC",
            prefix="",
            base_url="https://harding.example",
            enabled=True,
        ),
    ]
    window = {"source": "test fixture"}
    document = {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": ["G-MAC", "GSC", "independent", "non_member"],
        "memberships": {
            "trevecca": {
                "men": [
                    {
                        **window,
                        "conference": "G-MAC",
                        "from_season": 2022,
                        "to_season": 2023,
                    },
                    {
                        **window,
                        "conference": "GSC",
                        "from_season": 2024,
                        "to_season": 2026,
                    },
                ]
            },
        },
    }
    seen: list[object] = []

    def fake_programme(
        school,
        season,
        aliases,
        *,
        session=None,
        layers,
        members,
        page_cache=None,
        scope=None,
    ):
        del season, aliases, session, page_cache, members
        seen.append(scope)
        return ProgrammeCollection(
            slug=programme_slug(school.name),
            name=school.name,
            fixtures=[],
            players=[],
            outcomes={
                layer: LayerOutcome(layer=layer, state=STATE_EMPTY) for layer in layers
            },
        )

    monkeypatch.setattr(collect_board, "load_schools", lambda path: schools)
    monkeypatch.setattr(collect_board, "load_membership", lambda: document)
    monkeypatch.setattr(collect_board, "collect_programme", fake_programme)
    monkeypatch.setattr(collect_board, "write_raw_pages", lambda *args: None)
    monkeypatch.setattr(collect_board.paths, "data_root", lambda: tmp_path)

    def run(season: int) -> None:
        seen.clear()
        collect_board.collect(
            season=season,
            gender="men",
            conference="G-MAC",
            wanted=["trevecca", "harding"],
            layers=(LAYER_SCHEDULE,),
            config_path=tmp_path / "schools.toml",
            membership_extrapolated=False,
        )

    run(2022)
    # One scope object for the whole collect, every programme handed the same.
    assert len(seen) == 2 and seen[0] is seen[1]
    scope = seen[0]
    assert (scope.conference, scope.season) == ("G-MAC", 2022)
    assert scope.members == {"trevecca"}
    assert scope.claims == {
        "trevecca": "trevecca",
        "tnu": "trevecca",
        "trojans": "trevecca",
    }

    run(2024)
    scope = seen[0]
    assert scope.members == frozenset()
    assert scope.claims == {}


# ── an ambiguous name no member claims breaks by distance (tl-4sg.9.1) ─────
#
# After the member-first rule the CCAA and RMAC files still carried bare
# "dominican" rows for non-conference games against Dominican of
# California: under those scopes neither Dominican is a member, so the
# gender-wide map answered with the CACC's. The ruling: a printed text that
# folds to one programme's name or aliases AND to another's member aliases
# (at least two claimants), with no member of the collecting conference
# claiming it, resolves to the claimant whose programmes.json point is
# nearest the collecting school's. Any claimant or owner without a point,
# or a single claimant, falls to today's rule.

from src.programmes import load_programmes, programme_points  # noqa: E402
from src.sidearm_live import haversine_km  # noqa: E402

POINTS = programme_points(load_programmes())


def _scope_with_points(conference: str, season: int):
    # The collect's own table: the stanzas at the conference's level that
    # season. Over every stanza, Division I's homonyms ("California",
    # "Saint Mary's", "LMU", "SMU") would join the tiebreak.
    members = conference_members(
        SCHOOLS, "men", conference, season=season, document=MEMBERSHIP
    )
    return resolution_scope(
        resolution_stanzas(SCHOOLS, "men", conference, season, document=MEMBERSHIP),
        "men",
        members,
        conference=conference,
        season=season,
        points=POINTS,
    )


def _page(owner_title: str, *opponents: str) -> str:
    """One member's 2025 page, events-component shape, non-conference rows."""
    events = [
        {
            "id": 9000 + index,
            "date": f"2025-09-{1 + index:02d}T12:30:00",
            "opponent": {"title": opponent},
            "location_indicator": "H",
            "is_conference": False,
            "schedule": {"title": "2025 Men's Soccer Schedule"},
            "result": {"status": "W", "team_score": 2, "opponent_score": 1},
        }
        for index, opponent in enumerate(opponents)
    ]
    component = {"type": "events", "data": events}
    return (
        f"<html><head><title>2025 Men's Soccer Schedule - {owner_title}</title>"
        f"</head><body><script>\nvar obj = {json.dumps(component)};\n</script>"
        "</body></html>"
    )


def test_haversine_km_is_the_great_circle_distance() -> None:
    hayward = (37.6268, -122.104)
    san_rafael = (37.981, -122.5069)
    assert haversine_km(hayward, hayward) == 0.0
    assert 50 < haversine_km(hayward, san_rafael) < 56
    assert haversine_km(hayward, san_rafael) == haversine_km(san_rafael, hayward)
    # London to Paris, a textbook pair: 343 to 344 km.
    assert round(haversine_km((51.5074, -0.1278), (48.8566, 2.3522))) in (343, 344)


def test_every_shipped_programme_has_a_point() -> None:
    # Rib #100 gave every row coordinates (Simon Fraser via the stanza
    # point), so the tiebreak can never fall through for a shipped slug.
    document = load_programmes()
    assert set(POINTS) == set(document["programmes"])
    assert POINTS["simon-fraser"] == (49.242778, -122.972778)


def test_the_only_ambiguous_key_in_the_shipped_config_is_dominican() -> None:
    # "Concordia" has one claimant, Concordia Irvine's member alias: the
    # word is unambiguous by the ruling's definition, so the tiebreak never
    # sees it, and outside a PacWest collect it stays the unresolved key
    # (save on an NCAA tie: see ncaa_side below).
    scope = _scope_with_points("CCAA", 2025)
    assert dict(scope.claimants) == {
        "dominican": frozenset({"dominican", "dominican-of-california"})
    }


def test_dominican_on_a_ccaa_2025_page_is_the_nearer_dominican() -> None:
    scope = _scope_with_points("CCAA", 2025)
    assert "dominican" not in scope.claims
    assert opponent_slug("Dominican", MEN, scope=scope, owner="cal-state-east-bay") == (
        "dominican-of-california"
    )
    assert opponent_slug(
        "Dominican (Calif.)", MEN, scope=scope, owner="cal-state-east-bay"
    ) == ("dominican-of-california")
    # One line per distinct printed text, as #102's notes are keyed.
    assert scope.notes() == [
        "resolution: 'Dominican' on cal-state-east-bay's page read as "
        "dominican-of-california (53 km) over dominican (4,107 km)",
        "resolution: 'Dominican (Calif.)' on cal-state-east-bay's page read as "
        "dominican-of-california (53 km) over dominican (4,107 km)",
    ]


def test_dominican_on_an_rmac_2025_page_is_the_californian() -> None:
    scope = _scope_with_points("RMAC", 2025)
    assert opponent_slug("Dominican", MEN, scope=scope, owner="colorado-mesa") == (
        "dominican-of-california"
    )
    assert scope.notes() == [
        "resolution: 'Dominican' on colorado-mesa's page read as "
        "dominican-of-california (1,217 km) over dominican (2,935 km)"
    ]


def test_dominican_on_cacc_and_ecc_2025_pages_stays_the_new_yorker() -> None:
    # CACC: a member claims it, so the member-first rule answers first.
    cacc = _scope_with_points("CACC", 2025)
    assert opponent_slug("Dominican", MEN, scope=cacc, owner="bridgeport") == (
        "dominican"
    )
    assert cacc.notes() == []
    # ECC: no member claims it, both claimants have points, and Orangeburg
    # is the nearer one, which is also today's answer, so nothing is noted.
    ecc = _scope_with_points("ECC", 2025)
    assert opponent_slug("Dominican", MEN, scope=ecc, owner="molloy") == "dominican"
    assert ecc.notes() == []


def test_concordia_has_a_single_claimant_and_is_untouched() -> None:
    # Concordia Irvine's member alias is the word's only claim, so the
    # tiebreak never applies: on a CCAA page and on an LSC page alike the
    # word resolves exactly as today, to the unresolved key.
    for conference, owner in (
        ("CCAA", "cal-state-east-bay"),
        ("LSC", "dallas-baptist"),
    ):
        scope = _scope_with_points(conference, 2025)
        assert opponent_slug("Concordia", MEN, scope=scope, owner=owner) == (
            opponent_slug("Concordia", MEN)
        )
        assert opponent_slug("Concordia", MEN, scope=scope, owner=owner) == "concordia"
        assert scope.notes() == []


def test_a_single_claimant_name_resolves_exactly_as_before() -> None:
    scope = _scope_with_points("CCAA", 2025)
    for published in ("Chaminade", "Harding", "Delta St.", "DBU", "Point Loma"):
        assert opponent_slug(
            published, MEN, scope=scope, owner="cal-state-east-bay"
        ) == opponent_slug(published, MEN), published
    assert scope.notes() == []


def test_without_an_owner_or_points_the_tiebreak_never_applies() -> None:
    with_points = _scope_with_points("CCAA", 2025)
    assert opponent_slug("Dominican", MEN, scope=with_points) == "dominican"
    without_points = _scope("CCAA", 2025)
    assert opponent_slug(
        "Dominican", MEN, scope=without_points, owner="cal-state-east-bay"
    ) == ("dominican")
    assert with_points.notes() == without_points.notes() == []


def test_a_claimant_or_owner_with_no_point_falls_to_todays_rule() -> None:
    incumbent = _school("Dominican", "CACC")
    newcomer = _school(
        "Dominican of California", "PACWEST", member_aliases=["Dominican"]
    )
    host = _school("Cal State East Bay", "CCAA")
    schools = [incumbent, newcomer, host]
    aliases = identity_aliases(schools, "men")
    points = {
        "dominican": (41.0487, -73.9408),
        "dominican-of-california": (37.981, -122.5069),
        "cal-state-east-bay": (37.6268, -122.104),
    }

    def scope(**overrides: tuple[float, float]):
        kept = {**points, **overrides}
        kept = {slug: point for slug, point in kept.items() if point is not None}
        return resolution_scope(
            schools,
            "men",
            {"cal-state-east-bay"},
            conference="CCAA",
            season=2025,
            points=kept,
        )

    complete = scope()
    assert opponent_slug(
        "Dominican", aliases, scope=complete, owner="cal-state-east-bay"
    ) == ("dominican-of-california")
    for missing in ("dominican", "dominican-of-california", "cal-state-east-bay"):
        partial = scope(**{missing: None})
        assert opponent_slug(
            "Dominican", aliases, scope=partial, owner="cal-state-east-bay"
        ) == ("dominican"), missing
        assert partial.notes() == []


def test_a_ccaa_page_mints_the_match_under_the_nearer_slug() -> None:
    scope = _scope_with_points("CCAA", 2025)
    fixtures = parse_schedule_page(
        _page("Cal State East Bay", "Dominican"),
        page_url="https://eastbaypioneers.com/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="cal-state-east-bay",
        aliases=MEN,
        members=set(scope.members),
        scope=scope,
    )
    assert [(f["home"], f["away"], f["conference_game"]) for f in fixtures] == [
        ("cal-state-east-bay", "dominican-of-california", False)
    ]
    assert len(scope.notes()) == 1


def test_the_tiebreak_enters_the_fingerprint_only_while_a_key_is_ambiguous():
    scope = _scope_with_points("CCAA", 2025)
    # The configured abbreviations name a shootout's winner between two known
    # sides, so a scope built from stanzas that carry them fingerprints them;
    # the shipped config's member-only keys (ncaa_side) enter it too, and so
    # do the stanzas' home states and claimed keys a printed state qualifier
    # is held against (``_state_checked``).
    assert set(scope.fingerprint("cal-state-east-bay")) == {
        "conference",
        "season",
        "claims",
        "abbreviations",
        "member_only",
        "states",
        "spelled",
        "outside_states",
        "tiebreak",
        "origin",
    }
    assert scope.fingerprint("cal-state-east-bay") != scope.fingerprint("chico-state")
    plain = resolution_scope(
        [_school("Harding", "GAC")], "men", {"harding"}, conference="GAC", season=2025
    )
    assert set(plain.fingerprint("harding")) == {
        "conference",
        "season",
        "claims",
        "abbreviations",
    }


def test_collect_reads_the_points_once_and_survives_their_absence(monkeypatch):
    from scripts import collect_board

    assert collect_board._programme_points() == POINTS

    def missing():
        raise FileNotFoundError("no programmes.json")

    monkeypatch.setattr(collect_board, "load_programmes", missing)
    assert collect_board._programme_points() == {}


def test_a_division_word_after_a_seed_is_dropped_only_onto_a_member():
    """Bloomsburg's 2026 women's page (game 18292) seeds the PSAC tournament
    by division and prints "#4 East" before "Millersville University". The
    rank prefix stripped "#4" and left "East Millersville", filed as
    east-millersville beside Millersville's own record of the same match.
    The word goes only after a rank, only when nothing claims the whole key,
    and only onto a member of the collecting conference: the schools whose
    names begin with the word keep it, ranked or not."""
    women = identity_aliases(SCHOOLS, "women")
    members = conference_members(
        SCHOOLS, "women", "PSAC", season=2026, document=MEMBERSHIP
    )
    scope = resolution_scope(SCHOOLS, "women", members, conference="PSAC", season=2026)
    seeded = "#4 East Millersville University"
    assert opponent_slug(seeded, women, scope=scope) == "millersville"
    for ranked, plain in (
        ("#2 West Chester University", "West Chester University"),
        ("#1 East Stroudsburg", "East Stroudsburg"),
    ):
        own = opponent_slug(plain, women, scope=scope)
        assert own in members
        assert opponent_slug(ranked, women, scope=scope) == own
    # No rank, no scope, or a remainder no member claims: the key stands.
    assert opponent_slug("East Millersville University", women, scope=scope) == (
        "east-millersville"
    )
    assert opponent_slug(seeded, women) == "east-millersville"
    assert opponent_slug("#3 West Harding", women, scope=scope) == "west-harding"
    # The parsers clean the rank off before they resolve, so they say so.
    unranked = "East Millersville University"
    assert opponent_slug(unranked, women, scope=scope, seeded=True) == "millersville"


def test_the_bloomsburg_page_files_the_seeded_final_under_millersville() -> None:
    """The same row through the parser the collect runs. The resolver test
    above passed the raw string; the parser hands over the cleaned one, which
    is how the 2026 collect kept minting east-millersville after the rule
    landed. Held on the trimmed row, not the resolver."""
    women = identity_aliases(SCHOOLS, "women")
    members = conference_members(
        SCHOOLS, "women", "PSAC", season=2026, document=MEMBERSHIP
    )
    scope = resolution_scope(SCHOOLS, "women", members, conference="PSAC", season=2026)
    html = (FIXTURES / "sidearm_bloomsburg_women_schedule_2026_18292.html").read_text()
    url = "https://bloomsburgathletics.com/sports/womens-soccer/schedule/2026"

    def parse(scope):
        return parse_schedule_page(
            html,
            page_url=url,
            year=2026,
            owner_slug="bloomsburg",
            aliases=women,
            members=set(members),
            scope=scope,
        )

    [row] = parse(scope)
    assert row["id"] == "sidearm:bloomsburg:18292"
    assert (row["home"], row["away"]) == ("millersville", "bloomsburg")
    # Without the conference's scope the word stands, as it must.
    assert [r["home"] for r in parse(None)] == ["east-millersville"]


def test_a_programme_that_had_not_started_leaves_the_tiebreak():
    """McKendree's 2023 women's page prints "Wayne State College" for the
    NSIC's Wayne State (Neb.). Outside an NSIC collect the key is ambiguous
    between it (member alias) and Wayne State (Mich.) (name), and the
    distance tiebreak picked Detroit, whose women's soccer began in 2026.
    An explicit first_season takes the unborn programme out of the tiebreak
    for earlier seasons, and leaves it in from its first."""
    from scripts.collect_board import _programme_points

    points = _programme_points()

    def scope(season):
        members = conference_members(
            SCHOOLS, "women", "GLVC", season=season, document=MEMBERSHIP
        )
        return resolution_scope(
            SCHOOLS,
            "women",
            members,
            conference="GLVC",
            season=season,
            points=points,
        )

    women = identity_aliases(SCHOOLS, "women")
    early = scope(2023)
    assert early.claimants.get("wayne state") == frozenset({"wayne-state-nebraska"})
    assert (
        opponent_slug("Wayne State College", women, scope=early, owner="mckendree")
        == "wayne-state-nebraska"
    )
    assert any("the only claimant playing in 2023" in n for n in early.notes())
    later = scope(2026)
    assert later.claimants.get("wayne state") == frozenset(
        {"wayne-state", "wayne-state-nebraska"}
    )


# ── an NCAA tie reads a member-only spelling as its one programme ──────────
#
# lagoldeneagles.com 2026 women, game 6625 (NCAA second round at Irvine),
# prints "Concordia"; the CCAA collect minted the stranger concordia while
# Concordia Irvine's own page filed the tie under concordia-irvine. Both
# sides of an NCAA Division II tie are programmes of the division, so a key
# exactly one programme claims, and only by a member alias, names that one.
# Every other row keeps the stranger, as the ruling above says.

from src.sidearm_live import ncaa_side  # noqa: E402

WOMEN = identity_aliases(SCHOOLS, "women")


def _women_scope(conference: str, season: int):
    members = conference_members(
        SCHOOLS, "women", conference, season=season, document=MEMBERSHIP
    )
    return resolution_scope(
        SCHOOLS, "women", members, conference=conference, season=season
    )


def test_concordia_is_a_member_only_key() -> None:
    scope = _women_scope("CCAA", 2026)
    assert scope.member_only["concordia"] == "concordia-irvine"
    # A key some stanza claims by name or alias is never member-only.
    assert "dominican" not in scope.member_only
    assert "concordia irvine" not in scope.member_only


def test_concordia_on_a_ccaa_ncaa_tie_is_concordia_irvine() -> None:
    scope = _women_scope("CCAA", 2026)
    assert opponent_slug("Concordia", WOMEN, scope=scope) == "concordia"
    assert ncaa_side("concordia", WOMEN, scope, owner="cal-state-la") == (
        "concordia-irvine"
    )
    assert scope.notes() == [
        "resolution: concordia on cal-state-la's NCAA tie read as "
        "concordia-irvine, the only programme the spelling names"
    ]


def test_ncaa_side_leaves_every_other_slug_alone() -> None:
    scope = _women_scope("CCAA", 2026)
    for slug in ("cal-state-la", "concordia-irvine", "dominican", "some-stranger"):
        assert ncaa_side(slug, WOMEN, scope, owner="cal-state-la") == slug
    # The owner's own side, and a collect with no scope, are never read again.
    assert ncaa_side("concordia", WOMEN, scope, owner="concordia") == "concordia"
    assert ncaa_side("concordia", WOMEN, None, owner="cal-state-la") == "concordia"
    assert scope.notes() == []


def test_a_member_only_key_enters_the_parse_fingerprint() -> None:
    scope = _women_scope("CCAA", 2026)
    assert scope.fingerprint()["member_only"]["concordia"] == "concordia-irvine"
