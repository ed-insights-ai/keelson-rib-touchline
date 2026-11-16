"""Contract tests for season-aware conference membership."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src import membership, paths
from src.canon import PROGRAMMES, REGISTRY
from src.config import SchoolConfig, load_schools
from src.sidearm_live import (
    identity_aliases,
    identity_collisions,
    level_identity_ambiguities,
    level_identity_collisions,
    opponent_slug,
    programme_slug,
)
from scripts.migrate_shard import SHARDED_NAME

CANON_PROGRAMMES = {
    (programme["institution_slug"], programme["gender"])
    for programme in PROGRAMMES.values()
}
MEMBERSHIP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "membership.json"
)


@pytest.fixture(scope="module")
def membership_document() -> dict:
    return membership.load_membership(MEMBERSHIP_PATH)


def _school(name: str, conference: str) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=name,
        conference=conference,
        prefix="",
        base_url="",
        gender="men",
    )


def _profiles(*codes: str, level: str = "d2") -> dict:
    """A profile per code, for a test document that must validate."""
    return {
        code: {"level": level, "names": [f"{code} Test Conference"]} for code in codes
    }


def _multi_conference_case() -> tuple[dict, list[SchoolConfig]]:
    schools = [
        _school("Harding", "GAC"),
        _school("East Central", "GAC"),
        _school("West Texas A&M", "LSC"),
        _school("Eastern New Mexico", "LSC"),
    ]
    document = {
        "version": 1,
        "seasons": {"from": 2019, "to": 2026},
        "conferences": ["GAC", "LSC", "independent", "non_member"],
        "conference_profiles": _profiles("GAC", "LSC"),
        "memberships": {
            "harding": {
                "men": [
                    {
                        "conference": "GAC",
                        "from_season": 2019,
                        "to_season": 2025,
                        "source": "test fixture",
                    }
                ]
            },
            "east-central": {
                "men": [
                    {
                        "conference": "GAC",
                        "from_season": 2022,
                        "to_season": 2025,
                        "source": "test fixture",
                    }
                ]
            },
            "west-texas-a-m": {
                "men": [
                    {
                        "conference": "LSC",
                        "from_season": 2022,
                        "to_season": 2026,
                        "source": "test fixture",
                    }
                ]
            },
            "eastern-new-mexico": {
                "men": [
                    {
                        "conference": "LSC",
                        "from_season": 2022,
                        "to_season": 2024,
                        "source": "test fixture",
                    }
                ]
            },
        },
    }
    return document, schools


def test_default_load_prefers_the_packaged_source_of_record(monkeypatch, tmp_path):
    # A data home carrying a DIFFERENT membership document must not steer
    # resolution: the packaged copy is the source of record, and the data
    # home copy is a mirrored deployment artifact.
    reference_dir = tmp_path / "data" / "reference"
    reference_dir.mkdir(parents=True)
    (reference_dir / "membership.json").write_text(
        json.dumps({"memberships": {"stale-programme": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))

    assert membership.load_membership() == json.loads(
        MEMBERSHIP_PATH.read_text(encoding="utf-8")
    )


def test_default_load_falls_back_to_the_data_home_copy(monkeypatch, tmp_path):
    # An install that ships no packaged data tree still resolves membership
    # from the mirrored data home copy.
    reference_dir = tmp_path / "data" / "reference"
    reference_dir.mkdir(parents=True)
    document = {"memberships": {}}
    (reference_dir / "membership.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        paths,
        "packaged_membership_path",
        lambda: tmp_path / "nowhere" / "membership.json",
    )

    assert membership.load_membership() == document


def test_default_load_names_both_paths_when_neither_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    missing_packaged = tmp_path / "nowhere" / "membership.json"
    monkeypatch.setattr(paths, "packaged_membership_path", lambda: missing_packaged)

    with pytest.raises(FileNotFoundError) as excinfo:
        membership.load_membership()
    assert str(missing_packaged) in str(excinfo.value)
    assert str(tmp_path / "data" / "reference" / "membership.json") in str(
        excinfo.value
    )


def test_document_is_valid(membership_document):
    assert membership.validate(membership_document) == []


def test_covers_every_canon_programme(membership_document):
    # Subset, not equality: the document now also covers programmes beyond the
    # canon registry (the LSC additions). Canon-era coverage must never shrink.
    assert CANON_PROGRAMMES <= membership.covered_programmes(membership_document)


def test_every_season_resolves(membership_document):
    # Every season a programme's own windows author must resolve to that
    # window's conference. A programme is NOT required to span the document's
    # global range — per-conference horizons differ (GAC 2025, LSC 2026).
    for slug, genders in membership_document["memberships"].items():
        for gender, windows in genders.items():
            for window in windows:
                for season_year in range(
                    window["from_season"], window["to_season"] + 1
                ):
                    resolved = membership.conference_for(
                        slug,
                        gender,
                        season_year,
                        document=membership_document,
                    )
                    assert resolved == window["conference"], (
                        f"{slug}:{gender}:{season_year}"
                    )


def test_windows_are_contiguous_and_non_overlapping(membership_document):
    # Contiguity is judged within each programme's OWN authored span — a hole
    # there means a forgotten season, while starting later or ending earlier
    # than the document span is just a shorter membership.
    for slug, genders in membership_document["memberships"].items():
        for gender, windows in genders.items():
            covered_seasons = []
            for window in sorted(windows, key=lambda item: item["from_season"]):
                covered_seasons.extend(
                    range(window["from_season"], window["to_season"] + 1)
                )
            expected_seasons = list(
                range(min(covered_seasons), max(covered_seasons) + 1)
            )
            assert covered_seasons == expected_seasons, f"{slug}:{gender}"


def test_every_window_has_a_citation(membership_document):
    for genders in membership_document["memberships"].values():
        for windows in genders.values():
            for window in windows:
                assert isinstance(window["source"], str)
                assert window["source"].strip()


@pytest.mark.parametrize(
    "slug",
    ["fort-hays-state", "newman", "northeastern-state", "rogers-state"],
)
def test_mens_affiliate_boundary(membership_document, slug):
    assert (
        membership.conference_for(
            slug,
            "men",
            2018,
            document=membership_document,
        )
        != "GAC"
    )
    assert (
        membership.conference_for(
            slug,
            "men",
            2019,
            document=membership_document,
        )
        == "GAC"
    )


def test_is_conference_member(membership_document):
    assert membership.is_conference_member(
        "harding",
        "women",
        2016,
        conference="GAC",
        document=membership_document,
    )
    assert membership.is_conference_member(
        "fort-hays-state",
        "women",
        2025,
        conference="MIAA",
        document=membership_document,
    )
    assert not membership.is_conference_member(
        "fort-hays-state",
        "women",
        2025,
        conference="GAC",
        document=membership_document,
    )
    assert not membership.is_conference_member(
        "unknown",
        "men",
        2025,
        conference="GAC",
        document=membership_document,
    )


def test_derivation_is_conference_agnostic():
    document = {
        "version": 1,
        "seasons": {"from": 2016, "to": 2025},
        "conferences": ["GAC", "MIAA", "independent", "non_member"],
        "memberships": {
            "harding": {
                "men": [
                    {
                        "conference": "GAC",
                        "from_season": 2016,
                        "to_season": 2025,
                        "source": "test",
                    }
                ]
            },
            "fort-hays-state": {
                "men": [
                    {
                        "conference": "MIAA",
                        "from_season": 2016,
                        "to_season": 2025,
                        "source": "test",
                    }
                ]
            },
        },
    }

    assert membership.conference_for("harding", "men", 2020, document=document) == "GAC"
    assert (
        membership.conference_for(
            "fort-hays-state",
            "men",
            2020,
            document=document,
        )
        == "MIAA"
    )
    assert membership.is_conference_member(
        "harding",
        "men",
        2020,
        conference="GAC",
        document=document,
    )
    assert membership.is_conference_member(
        "fort-hays-state",
        "men",
        2020,
        conference="MIAA",
        document=document,
    )
    assert not membership.is_conference_member(
        "harding",
        "men",
        2020,
        conference="MIAA",
        document=document,
    )
    assert not membership.is_conference_member(
        "fort-hays-state",
        "men",
        2020,
        conference="GAC",
        document=document,
    )


def test_validation_accepts_declared_conference(membership_document):
    # A code the shipped document does not declare — the point is that
    # declaring a NEW conference in data is all it takes. LSC and RMAC each
    # sat here until they graduated into the real file, so the code is now
    # one no conference will ever carry.
    document = copy.deepcopy(membership_document)
    assert "NEWC" not in document["conferences"]
    document["conferences"].append("NEWC")
    document["memberships"]["harding"]["men"][0]["conference"] = "NEWC"

    # Declaring it means the code AND its record: level and printed names.
    assert membership.validate(document) == [
        "conference 'NEWC' has no conference_profiles entry; every declared "
        "conference carries its level and printed names"
    ]
    document["conference_profiles"].update(_profiles("NEWC"))
    assert membership.validate(document) == []


def test_validation_rejects_contract_violations(membership_document):
    unknown_conference = copy.deepcopy(membership_document)
    unknown_conference["memberships"]["harding"]["men"][0]["conference"] = "other"
    assert any(
        "unknown conference code" in error
        for error in membership.validate(unknown_conference)
    )

    gap = copy.deepcopy(membership_document)
    gap["memberships"]["fort-hays-state"]["men"][1]["from_season"] = 2020
    assert any(
        "membership gaps" in error and "independent or non_member" in error
        for error in membership.validate(gap)
    )

    overlap = copy.deepcopy(membership_document)
    overlap["memberships"]["fort-hays-state"]["men"][1]["from_season"] = 2018
    assert any("overlapping windows" in error for error in membership.validate(overlap))

    missing_citation = copy.deepcopy(membership_document)
    missing_citation["memberships"]["harding"]["women"][0]["source"] = ""
    assert any(
        "non-empty source citation" in error
        for error in membership.validate(missing_citation)
    )

    out_of_span = copy.deepcopy(membership_document)
    out_of_span["memberships"]["harding"]["men"][0]["to_season"] = (
        membership_document["seasons"]["to"] + 1
    )
    assert any("falls outside" in error for error in membership.validate(out_of_span))

    unknown_slug = copy.deepcopy(membership_document)
    unknown_slug["memberships"]["unknown"] = {
        "women": copy.deepcopy(
            membership_document["memberships"]["east-central"]["women"]
        )
    }
    assert any(
        "unknown institution slug" in error
        for error in membership.validate(unknown_slug)
    )

    malformed = copy.deepcopy(membership_document)
    malformed["memberships"]["harding"] = []
    assert any(
        "memberships must be a JSON object" in error
        for error in membership.validate(malformed)
    )


def test_multi_conference_horizons_validate():
    document, schools = _multi_conference_case()

    assert membership.validate(document, schools=schools) == []


def test_window_conference_absent_from_declared_fails():
    document, schools = _multi_conference_case()
    document["memberships"]["harding"]["men"][0]["conference"] = "PAC"

    assert any(
        "unknown conference code" in error
        for error in membership.validate(document, schools=schools)
    )


def test_missing_structural_sentinel_fails():
    document, schools = _multi_conference_case()
    document["conferences"].remove("non_member")

    assert any(
        "structural codes" in error
        for error in membership.validate(document, schools=schools)
    )


def test_a_spelling_two_stanzas_claim_is_refused():
    # RU is Rockhurst's abbreviation and Roosevelt's: gender-wide,
    # last-stanza-wins, so the collect would hand every "RU" to Roosevelt.
    document, schools = _multi_conference_case()
    for slug, conference in (("rockhurst", "GAC"), ("roosevelt", "LSC")):
        document["memberships"][slug] = {
            "men": [
                {
                    "conference": conference,
                    "from_season": 2019,
                    "to_season": 2026,
                    "source": "t",
                }
            ]
        }
    rockhurst = replace(_school("Rockhurst", "GAC"), abbreviation="RU")
    roosevelt = replace(_school("Roosevelt", "LSC"), abbreviation="RU")
    errors = membership.validate(document, schools=[*schools, rockhurst, roosevelt])
    assert errors == [
        "identity collision (men, d2, seasons 2019-2026): 'ru' is claimed by "
        "rockhurst (abbreviation) "
        "and roosevelt (abbreviation); drop the alias or set "
        "abbreviation_resolves = false on the stanzas that share the initialism"
    ]

    # An alias that is another stanza's name collides the same way.
    aliased = replace(roosevelt, abbreviation="ROO", aliases=["Rockhurst"])
    errors = membership.validate(document, schools=[*schools, rockhurst, aliased])
    assert len(errors) == 1
    assert (
        "'rockhurst' is claimed by rockhurst (name) and roosevelt (alias)" in errors[0]
    )

    # Display-only abbreviations settle it; the map then resolves neither RU.
    settled = [
        replace(rockhurst, abbreviation_resolves=False),
        replace(roosevelt, abbreviation_resolves=False),
    ]
    assert membership.validate(document, schools=[*schools, *settled]) == []
    aliases = identity_aliases([*schools, *settled], "men")
    assert "ru" not in aliases
    assert opponent_slug("Roosevelt", aliases) == "roosevelt"
    assert opponent_slug("Rockhurst", aliases) == "rockhurst"

    # Women's stanzas are another table: the same initialism there is no
    # collision with a men's one.
    assert identity_collisions([rockhurst, replace(roosevelt, gender="women")]) == []


def test_the_shipped_config_claims_no_spelling_twice():
    # Per resolution table (one gender, one NCAA level, one season): since
    # Division I joined the file, the gender-wide list shares keys across
    # levels by design ("california" is California (Pa.)'s and Cal's), and
    # those two never share a table.
    schools, document = load_schools(), membership.load_membership()
    assert level_identity_collisions(schools, document=document) == []
    assert level_identity_ambiguities(schools, document=document) == []


def test_a_display_name_is_never_an_identity_claim():
    """display_name is reader-facing (tl-4an.31): a same-name pair prints
    "Dominican (N.Y.)" beside "Dominican (Calif.)", each of which folds to
    the other's key, and neither is a collision, in either file order. Name
    and alias collisions are still refused, and the map resolves by name
    and aliases only, so the display name never re-points the bare word."""
    incumbent = replace(
        _school("Dominican", "CACC"),
        abbreviation="DUNY",
        display_name="Dominican (N.Y.)",
    )
    newcomer = replace(
        _school("Dominican of California", "PACWEST"),
        abbreviation="DUC",
        display_name="Dominican (Calif.)",
        aliases=["Dominican California"],
    )
    assert identity_collisions([incumbent, newcomer]) == []
    assert identity_collisions([newcomer, incumbent]) == []

    # A display_name that is another stanza's exact name is not a claim
    # either: only name, aliases and a resolving abbreviation collide.
    exact = replace(newcomer, display_name="Dominican")
    assert identity_collisions([incumbent, exact]) == []
    claimed = replace(newcomer, aliases=["Dominican"])
    assert identity_collisions([incumbent, claimed]) == [
        (
            "men",
            "dominican",
            [("dominican", "name"), ("dominican-of-california", "alias")],
        )
    ]

    aliases = identity_aliases([incumbent, newcomer], "men")
    assert opponent_slug("Dominican", aliases) == "dominican"
    assert opponent_slug("Dominican California", aliases) == "dominican-of-california"
    # The fold still drops the parenthetical, so the printed "Dominican
    # (Calif.)" lands on the incumbent until tl-4sg.9 keeps the qualifier;
    # the display name plays no part in that either way.
    assert opponent_slug("Dominican (Calif.)", aliases) == "dominican"


def test_the_shipped_dominican_pair_carries_both_display_names():
    by_slug = {programme_slug(s.name): s for s in load_schools() if s.gender == "men"}
    assert by_slug["dominican"].display() == "Dominican (N.Y.)"
    assert by_slug["dominican-of-california"].display() == "Dominican (Calif.)"
    aliases = identity_aliases(load_schools(), "men")
    assert opponent_slug("Dominican", aliases) == "dominican"
    assert opponent_slug("Dominican University of California", aliases) == (
        "dominican-of-california"
    )


def test_missing_configured_programme_fails():
    document, schools = _multi_conference_case()
    schools.append(_school("Missing School", "LSC"))

    assert any(
        "missing configured programmes" in error
        for error in membership.validate(document, schools=schools)
    )


def test_registry_slugs_are_covered(membership_document):
    covered_slugs = {
        slug for slug, _gender in membership.covered_programmes(membership_document)
    }
    registry_slugs = {
        programme["institution_slug"] for programme in PROGRAMMES.values()
    }
    assert registry_slugs <= set(REGISTRY)
    assert registry_slugs <= covered_slugs


def _window(conference: str, from_season: int, to_season: int) -> dict:
    return {
        "conference": conference,
        "from_season": from_season,
        "to_season": to_season,
        "source": "test fixture",
    }


# ── conference profiles: the conference as a record ─────────────────────────


#: The twenty-one conferences the rib collected before any other level was
#: authored, every one Division II. A fact about them, not about the file:
#: the test below must keep passing on the day another level's conferences
#: join the reference.
DIVISION_TWO = {
    "CACC",
    "CC",
    "CCAA",
    "ECC",
    "G-MAC",
    "GAC",
    "GLIAC",
    "GLVC",
    "GNAC",
    "GSC",
    "LSC",
    "MEC",
    "MIAA",
    "NE10",
    "NSIC",
    "PACWEST",
    "PBC",
    "PSAC",
    "RMAC",
    "SAC",
    "SSC",
}


def test_every_shipped_conference_carries_a_profile(membership_document):
    profiles = membership.conference_profiles(membership_document)
    declared = set(membership_document["conferences"]) - membership.STRUCTURAL_CODES
    assert set(profiles) == declared
    assert all(profile.names for profile in profiles.values())
    # The levels partition the declared conferences: none is left out of a
    # level-filtered sweep, none is swept twice.
    by_level = {
        level: membership.conferences_at_level(level, document=membership_document)
        for level in membership.LEVELS
    }
    assert sorted(code for codes in by_level.values() for code in codes) == sorted(
        declared
    )
    assert len(DIVISION_TWO) == 21
    assert DIVISION_TWO <= set(by_level["d2"])
    assert membership.conference_level("GAC", document=membership_document) == "d2"
    assert profiles["GAC"].names == ("Great American Conference", "Great American")


def test_a_profile_reads_level_names_and_the_word_flag():
    document, _ = _multi_conference_case()
    document["conference_profiles"] = {
        "GAC": {"level": "d2", "names": ["Great  American Conference"]},
        "LSC": {"level": "d1", "names": ["Lone Star"], "code_is_word": True},
    }
    profiles = membership.conference_profiles(document)
    assert profiles["GAC"] == membership.ConferenceProfile(
        code="GAC", level="d2", names=("Great American Conference",)
    )
    assert profiles["LSC"].code_is_word is True
    assert membership.conference_level("LSC", document=document) == "d1"
    assert membership.conference_level("independent", document=document) is None
    assert membership.conferences_at_level("d1", document=document) == ["LSC"]
    assert membership.conferences_at_level("d3", document=document) == []
    with pytest.raises(ValueError, match="unknown level 'division-two'"):
        membership.conferences_at_level("division-two", document=document)


def test_a_declared_conference_without_a_profile_is_refused():
    document, schools = _multi_conference_case()
    del document["conference_profiles"]["LSC"]
    assert membership.validate(document, schools=schools) == [
        "conference 'LSC' has no conference_profiles entry; every declared "
        "conference carries its level and printed names"
    ]

    del document["conference_profiles"]
    assert membership.validate(document, schools=schools) == [
        "conference_profiles must be a JSON object keyed by conference code"
    ]


def test_a_profile_for_an_undeclared_code_is_refused():
    document, schools = _multi_conference_case()
    document["conference_profiles"].update(_profiles("NEWC"))
    assert membership.validate(document, schools=schools) == [
        "conference_profiles['NEWC'] names an undeclared conference code"
    ]

    document, schools = _multi_conference_case()
    document["conference_profiles"].update(_profiles("independent"))
    assert membership.validate(document, schools=schools) == [
        "conference_profiles['independent'] is a structural code, not a conference"
    ]


def test_a_malformed_profile_is_refused_field_by_field():
    document, schools = _multi_conference_case()
    document["conference_profiles"]["GAC"] = {
        "level": "II",
        "names": [],
        "code_is_word": "no",
        "division": "d2",
    }
    document["conference_profiles"]["LSC"] = {
        "level": "d2",
        "names": ["Lone Star", " ", "lone  star", 7],
    }
    errors = membership.validate(document, schools=schools)
    assert errors == [
        "conference_profiles['GAC'] has unknown fields: ['division']",
        "conference_profiles['GAC'] level must be one of ['d1', 'd2', 'd3'], not 'II'",
        "conference_profiles['GAC'] names must be a non-empty list of strings",
        "conference_profiles['GAC'] code_is_word must be true or false",
        "conference_profiles['LSC'] names must be non-empty strings, not ' '",
        "conference_profiles['LSC'] names repeat 'lone  star'",
        "conference_profiles['LSC'] names must be non-empty strings, not 7",
    ]
    # The reader leaves a malformed profile out rather than guess at it.
    assert set(membership.conference_profiles(document)) == {"LSC"}


def _mid_window_mover_document() -> dict:
    """Trevecca: G-MAC 2022-2023 then GSC from 2024, on one slug."""
    return {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": ["G-MAC", "GSC", "GAC", "independent", "non_member"],
        "memberships": {
            "trevecca": {
                "men": [_window("G-MAC", 2022, 2023), _window("GSC", 2024, 2026)]
            },
            "harding": {"men": [_window("GAC", 2022, 2026)]},
        },
    }


def test_members_of_resolves_a_mid_window_mover_per_season():
    document = _mid_window_mover_document()
    assert membership.members_of("G-MAC", "men", 2022, document=document) == {
        "trevecca"
    }
    assert membership.members_of("G-MAC", "men", 2023, document=document) == {
        "trevecca"
    }
    assert membership.members_of("GSC", "men", 2024, document=document) == {"trevecca"}
    assert membership.members_of("GSC", "men", 2023, document=document) == set()
    assert membership.members_of("G-MAC", "men", 2024, document=document) == set()
    # A one-window slug answers the same for every season it covers.
    assert membership.members_of("GAC", "men", 2022, document=document) == {"harding"}
    assert membership.members_of("GAC", "men", 2026, document=document) == {"harding"}
    # Gender scoping holds: no women's windows are authored here.
    assert membership.members_of("GAC", "women", 2022, document=document) == set()


# ── a season no window covers ────────────────────────────────────────────────


def _horizon_document() -> dict:
    """Two conferences with different horizons, and every way to be uncovered.

    UPPER is authored through 2026, LOWER through 2025 only. ``leaver`` left
    UPPER after 2023 (the Mercyhurst shape), ``arriver`` joined it in 2025,
    ``stayer`` is a LOWER member through LOWER's last authored season, and
    ``mover`` left LOWER for UPPER in 2025 (the Trevecca shape).
    """
    return {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": ["UPPER", "LOWER", "independent", "non_member"],
        "conference_profiles": _profiles("UPPER", "LOWER"),
        "memberships": {
            "anchor": {"men": [_window("UPPER", 2022, 2026)]},
            "leaver": {"men": [_window("UPPER", 2022, 2023)]},
            "arriver": {"men": [_window("UPPER", 2025, 2026)]},
            "stayer": {"men": [_window("LOWER", 2022, 2025)]},
            "mover": {
                "men": [_window("LOWER", 2022, 2024), _window("UPPER", 2025, 2026)]
            },
        },
    }


def test_a_conference_has_its_own_authored_horizon():
    document = _horizon_document()
    assert membership.authored_through("UPPER", "men", document=document) == 2026
    assert membership.authored_through("LOWER", "men", document=document) == 2025
    # Without case, as the rib's resolveConference compares the code.
    assert membership.authored_through(" lower ", "men", document=document) == 2025
    assert membership.authored_through("UPPER", "women", document=document) == 0
    assert membership.authored_through("independent", "men", document=document) == 0
    # A season is carried forward only past the conference's own horizon.
    assert membership.effective_season("LOWER", "men", 2026, document=document) == 2025
    assert membership.effective_season("LOWER", "men", 2024, document=document) == 2024
    assert membership.effective_season("UPPER", "men", 2026, document=document) == 2026
    assert (
        membership.effective_season("UPPER", "women", 2026, document=document) == 2026
    )


def test_a_programme_with_windows_is_governed_by_them_alone():
    document = _horizon_document()

    def reads(slug: str, season: int, conference: str) -> str | None:
        return membership.conference_in_effect(
            slug, "men", season, conference, document=document
        )

    assert membership.has_windows("leaver", "men", document=document)
    assert not membership.has_windows("leaver", "women", document=document)
    assert not membership.has_windows("stranger", "men", document=document)

    # Inside its windows a programme is where they say.
    assert reads("leaver", 2023, "UPPER") == "UPPER"
    # After its last window it is in no conference: UPPER is authored
    # through 2026, so nothing is carried forward for 2024.
    for season in (2024, 2025, 2026):
        assert reads("leaver", season, "UPPER") is None
    # Before its first window, the same.
    assert reads("arriver", 2024, "UPPER") is None
    assert reads("arriver", 2025, "UPPER") == "UPPER"


def test_a_conference_past_its_horizon_carries_its_last_members_forward():
    document = _horizon_document()

    def reads(slug: str, season: int, conference: str) -> str | None:
        return membership.conference_in_effect(
            slug, "men", season, conference, document=document
        )

    # LOWER is authored through 2025: its 2025 member is still read as its
    # member for a 2026 collect, the season the rib resolves as extrapolated.
    assert reads("stayer", 2026, "LOWER") == "LOWER"
    assert reads("stayer", 2026, "lower") == "LOWER"
    # Carried into the conference being read, never into another one.
    assert reads("stayer", 2026, "UPPER") is None
    # A programme whose own window covers the season is not carried anywhere:
    # the mover is UPPER's from 2025, whatever LOWER's horizon is.
    assert reads("mover", 2026, "LOWER") == "UPPER"
    assert reads("mover", 2024, "LOWER") == "LOWER"

    assert membership.members_in_effect("LOWER", "men", 2026, document=document) == {
        "stayer"
    }
    assert membership.members_in_effect("LOWER", "men", 2024, document=document) == {
        "stayer",
        "mover",
    }
    assert membership.members_in_effect("UPPER", "men", 2026, document=document) == {
        "anchor",
        "arriver",
        "mover",
    }
    # Where the conference authors the season the set is members_of exactly.
    for season in range(2022, 2027):
        assert membership.members_in_effect(
            "UPPER", "men", season, document=document
        ) == membership.members_of("UPPER", "men", season, document=document)


def _divisional_window(
    conference: str, division: str, from_season: int, to_season: int
) -> dict:
    return {**_window(conference, from_season, to_season), "division": division}


def _divisional_document() -> dict:
    """The Conference Carolinas shape (bead tl-4sg.40): three divisions from
    2023, North Greenville moving Southwest to Northwest across 2023/2024 on
    one slug, and a one-table conference beside it."""
    return {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": ["CC", "GAC", "independent", "non_member"],
        "conference_profiles": _profiles("CC", "GAC"),
        "memberships": {
            "north-greenville": {
                "men": [
                    _divisional_window("CC", "Southwest", 2023, 2023),
                    _divisional_window("CC", "Northwest", 2024, 2026),
                ]
            },
            "belmont-abbey": {"men": [_divisional_window("CC", "East", 2023, 2026)]},
            "mount-olive": {"men": [_divisional_window("CC", "East", 2023, 2026)]},
            "harding": {"men": [_window("GAC", 2022, 2026)]},
        },
    }


def _divisional_schools() -> list[SchoolConfig]:
    return [
        _school("North Greenville", "CC"),
        _school("Belmont Abbey", "CC"),
        _school("Mount Olive", "CC"),
        _school("Harding", "GAC"),
    ]


def test_a_window_with_a_division_resolves_and_carries_it():
    document = _divisional_document()
    assert (
        membership.conference_for("belmont-abbey", "men", 2024, document=document)
        == "CC"
    )
    assert (
        membership.division_for("belmont-abbey", "men", 2024, document=document)
        == "East"
    )
    # A one-table conference names none, and neither does an uncovered season.
    assert membership.division_for("harding", "men", 2024, document=document) is None
    assert (
        membership.division_for("belmont-abbey", "men", 2022, document=document) is None
    )


def test_a_split_window_resolves_its_division_per_season():
    document = _divisional_document()
    for season, division in (
        (2023, "Southwest"),
        (2024, "Northwest"),
        (2026, "Northwest"),
    ):
        assert (
            membership.conference_for(
                "north-greenville", "men", season, document=document
            )
            == "CC"
        )
        assert (
            membership.division_for(
                "north-greenville", "men", season, document=document
            )
            == division
        )
    # members_of is unchanged by the split: one slug, both seasons.
    assert membership.members_of("CC", "men", 2023, document=document) == {
        "north-greenville",
        "belmont-abbey",
        "mount-olive",
    }
    assert membership.divisions_of("CC", "men", 2023, document=document) == {
        "north-greenville": "Southwest",
        "belmont-abbey": "East",
        "mount-olive": "East",
    }
    assert (
        membership.divisions_of("CC", "men", 2024, document=document)[
            "north-greenville"
        ]
        == "Northwest"
    )
    assert membership.divisions_of("GAC", "men", 2024, document=document) == {}


def test_all_or_none_divisions_pass_on_a_divisional_and_a_plain_season():
    document = _divisional_document()
    assert membership.validate(document, schools=_divisional_schools()) == []


def test_the_shipped_conferences_carry_divisions_only_where_printed(
    membership_document,
):
    # The labelled conference-gender-seasons, each from the season its
    # standings first print divisions: Conference Carolinas men from 2023
    # (three divisions, batch 4), and three women's conferences, authored
    # 2022-2026 since the women's history backfill: the PSAC (East and West)
    # and the MEC (North and South) in every season, Conference Carolinas
    # (East, Northwest, Southwest) from 2023, its 2022 table being one
    # undivided list as the men's is. The MEC's men's
    # standings print North and South too, but the men's windows were
    # authored without them, so they stay unlabelled until a ruling adds
    # them. Two Division I men's conferences print divisions on their
    # standings: the Big East ("East Division", "Midwest Division") in every
    # authored season, 2023-2026, and the CAA ("North", "South") from 2025,
    # its 2023 and 2024 tables being one undivided list. The all-or-none rule
    # holds on the shipped
    # file, nothing is labelled anywhere else, and every member of a
    # labelled conference-season carries one of its printed divisions.
    divisional = {
        ("CC", "men"): (2023, {"East", "Northwest", "Southwest"}),
        ("PSAC", "women"): (2022, {"East", "West"}),
        ("CC", "women"): (2023, {"East", "Northwest", "Southwest"}),
        ("MEC", "women"): (2022, {"North", "South"}),
        ("BIGEAST", "men"): (2023, {"East Division", "Midwest Division"}),
        ("CAA", "men"): (2025, {"North", "South"}),
    }
    span = membership_document["seasons"]
    for conference in membership_document["conferences"]:
        for gender in ("men", "women"):
            for season in range(span["from"], span["to"] + 1):
                divisions = membership.divisions_of(
                    conference, gender, season, document=membership_document
                )
                labelled = divisional.get((conference, gender))
                if labelled is not None and season >= labelled[0]:
                    members = membership.members_of(
                        conference, gender, season, document=membership_document
                    )
                    assert set(divisions) == set(members)
                    assert set(divisions.values()) == labelled[1]
                else:
                    assert divisions == {}
    # The one split on a slug with the conference unchanged.
    assert (
        membership.division_for(
            "north-greenville", "men", 2023, document=membership_document
        )
        == "Southwest"
    )
    assert (
        membership.division_for(
            "north-greenville", "men", 2024, document=membership_document
        )
        == "Northwest"
    )


def test_a_mix_of_divisions_fails_naming_the_odd_member():
    document = _divisional_document()
    del document["memberships"]["mount-olive"]["men"][0]["division"]
    errors = membership.validate(document, schools=_divisional_schools())
    assert len(errors) == 4, errors
    for season, error in zip(range(2023, 2027), errors, strict=True):
        assert error == (
            f"CC men {season} mixes divisions: every member's window must carry "
            "a division or none may; without a division: ['mount-olive']"
        )
    # The minority side is the odd one whichever way the mix falls.
    lone = _divisional_document()
    for slug in ("belmont-abbey", "mount-olive"):
        del lone["memberships"][slug]["men"][0]["division"]
    errors = membership.validate(lone, schools=_divisional_schools())
    assert errors[0] == (
        "CC men 2023 mixes divisions: every member's window must carry "
        "a division or none may; carrying a division alone: ['north-greenville']"
    )


def test_a_blank_division_is_refused():
    document = _divisional_document()
    document["memberships"]["mount-olive"]["men"][0]["division"] = " "
    errors = membership.validate(document, schools=_divisional_schools())
    assert any("division must be a non-empty string" in error for error in errors)


def test_a_hyphenated_conference_code_keys_its_season_files():
    # G-MAC is the first conference code with a hyphen (batch 2, 2026-09-03).
    # The collect names its shard f"{season}-{gender}-{programme_slug(conference)}"
    # (scripts/collect_board.py), and the shard regex must read it back whole.
    assert programme_slug("G-MAC") == "g-mac"
    season_key = f"{2026}-{'men'}-{programme_slug('G-MAC')}"
    assert season_key == "2026-men-g-mac"
    match = SHARDED_NAME.match("2026-men-g-mac.json")
    assert match is not None
    assert match.groups() == ("2026", "men", "g-mac")


def test_g_mac_resolves_per_season_with_trevecca_in_its_earlier_window(
    membership_document,
):
    # The packaged file: eleven G-MAC members in 2026, twelve in 2023 when
    # Trevecca's first window still names the G-MAC, and GSC from 2024.
    now = membership.members_of("G-MAC", "men", 2026, document=membership_document)
    assert len(now) == 11
    assert "trevecca" not in now
    then = membership.members_of("G-MAC", "men", 2023, document=membership_document)
    assert len(then) == 12
    assert "trevecca" in then
    assert (
        membership.conference_for("trevecca", "men", 2023, document=membership_document)
        == "G-MAC"
    )
    assert (
        membership.conference_for("trevecca", "men", 2024, document=membership_document)
        == "GSC"
    )


# ── standings-archive evidence (a conference with no records pages) ──────────

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Per-season member counts from the batch 4 research (bead tl-4an.29): the
# SAC's site answers "no statistics available" for every records page, so
# the standings archive by id is the evidence, and these are what it lists.
SAC_STANDINGS = {
    2021: ("sidearm_sac_standings_2021_72.html", 12),
    2022: ("sidearm_sac_standings_2022_73.html", 12),
    2023: ("sidearm_sac_standings_2023_74.html", 12),
    2024: ("sidearm_sac_standings_2024_75.html", 12),
    2025: ("sidearm_sac_standings_2025_178.html", 11),
    2026: ("sidearm_sac_standings_2026_live.html", 11),
}


def _sac_page(season: int) -> str:
    return (FIXTURES / SAC_STANDINGS[season][0]).read_text(encoding="utf-8")


def test_standings_archive_url_is_data_not_code(membership_document):
    # The id-to-season map lives on the packaged file; the template and the
    # id compose the page the source sentence cites.
    assert (
        membership.standings_archive_url("SAC", 2022, document=membership_document)
        == "https://www.thesac.com/standings.aspx?standings=73"
    )
    assert (
        membership.standings_archive_url("SAC", 2025, document=membership_document)
        == "https://www.thesac.com/standings.aspx?standings=178"
    )
    # A season the archive does not name, and a records-page conference, get
    # nothing: their evidence is the records page the window already cites.
    assert (
        membership.standings_archive_url("SAC", 2019, document=membership_document)
        is None
    )
    assert (
        membership.standings_archive_url("PSAC", 2022, document=membership_document)
        is None
    )
    assert "PSAC" not in membership_document["standings_archives"]


@pytest.mark.parametrize("season", sorted(SAC_STANDINGS))
def test_sac_standings_pages_reproduce_the_research_counts(season):
    page = membership.parse_standings_page(_sac_page(season))
    assert page.season == season
    assert page.gender == "men"
    assert len(page.names) == SAC_STANDINGS[season][1]
    assert len(set(page.names)) == len(page.names)


def test_the_2021_boundary_page_lists_queens_nc():
    # 2021 is the season before the window opens: twelve programmes, Queens
    # (NC) among them, who left for Division I before 2022.
    names = membership.parse_standings_page(_sac_page(2021)).names
    assert len(names) == 12
    assert "Queens NC" in names
    assert "Emory & Henry" not in names
    assert "Emory & Henry" in membership.parse_standings_page(_sac_page(2022)).names


def _sac_case(season: int) -> tuple[dict, list[SchoolConfig]]:
    """A document and stanzas authored from what the page lists."""
    names = membership.parse_standings_page(_sac_page(season)).names
    schools = [_school(name, "SAC") for name in names]
    document = {
        "version": 1,
        "seasons": {"from": 2022, "to": 2026},
        "conferences": ["SAC", "independent", "non_member"],
        "conference_profiles": _profiles("SAC"),
        "standings_archives": {
            "SAC": {
                "url_template": "https://www.thesac.com/standings.aspx?standings={id}",
                "seasons": {str(season): "73"},
            }
        },
        "memberships": {
            programme_slug(name): {"men": [_window("SAC", 2022, 2026)]}
            for name in names
        },
    }
    return document, schools


def test_verify_standings_holds_a_page_against_the_windows():
    document, schools = _sac_case(2022)
    verdict = membership.verify_standings(
        _sac_page(2022), "SAC", "men", 2022, document=document, schools=schools
    )
    assert verdict.url == "https://www.thesac.com/standings.aspx?standings=73"
    assert verdict.agrees
    assert len(verdict.expected) == 12
    assert verdict.slugs["Emory & Henry"] == programme_slug("Emory & Henry")

    # A window the page does not support, and a name no window claims, are
    # both named rather than folded into a count.
    document["memberships"]["queens"] = {"men": [_window("SAC", 2022, 2026)]}
    del document["memberships"]["coker"]
    verdict = membership.verify_standings(
        _sac_page(2022), "SAC", "men", 2022, document=document, schools=schools
    )
    assert not verdict.agrees
    assert verdict.missing == {"queens"}
    assert verdict.strangers == {"coker"}


def test_verify_standings_mints_through_the_stanza_aliases():
    # The page prints "Queens NC"; a stanza named Queens claiming that
    # spelling resolves it to the stanza's slug, the way opponent text does.
    document, schools = _sac_case(2021)
    document["seasons"] = {"from": 2021, "to": 2026}
    document["memberships"] = {
        slug: {"men": [_window("SAC", 2021, 2026)]}
        for slug in document["memberships"]
        if slug != programme_slug("Queens NC")
    }
    document["memberships"]["queens"] = {"men": [_window("SAC", 2021, 2026)]}
    schools = [school for school in schools if school.name != "Queens NC"]
    schools.append(replace(_school("Queens", "SAC"), aliases=["Queens NC"]))
    verdict = membership.verify_standings(
        _sac_page(2021), "SAC", "men", 2021, document=document, schools=schools
    )
    assert verdict.slugs["Queens NC"] == "queens"
    assert verdict.agrees


def test_verify_standings_refuses_a_page_for_another_season():
    document, schools = _sac_case(2022)
    with pytest.raises(ValueError, match="2022 season, not 2023"):
        membership.verify_standings(
            _sac_page(2022), "SAC", "men", 2023, document=document, schools=schools
        )
    with pytest.raises(ValueError, match="men's soccer, not women's"):
        membership.verify_standings(
            _sac_page(2022), "SAC", "women", 2022, document=document, schools=schools
        )


def test_validate_checks_the_standings_archive_shape():
    document, schools = _multi_conference_case()
    assert membership.validate(document, schools=schools) == []

    document["standings_archives"] = {
        "GAC": {
            "url_template": "https://greatamericanconference.com/standings.aspx?standings={id}",
            "seasons": {"2022": "140"},
        }
    }
    assert membership.validate(document, schools=schools) == []

    document["standings_archives"] = {
        "GAC": {
            "url_template": "https://greatamericanconference.com/standings.aspx",
            "seasons": {"22": "140", "2030": "141", "2023": ""},
        }
    }
    errors = membership.validate(document, schools=schools)
    assert any("url_template must be a URL carrying '{id}'" in e for e in errors)
    assert any("season key '22' must be a 4-digit year" in e for e in errors)
    assert any("season 2030 falls outside 2019-2026" in e for e in errors)
    assert any("season 2023 id must be a non-empty string" in e for e in errors)


def test_check_membership_cli_reads_a_captured_standings_page(capsys):
    from scripts.check_membership import main

    # Bare: the validation the script always did.
    assert main([]) == 0
    assert "membership valid" in capsys.readouterr().out

    # With a page: the packaged file names the SAC archive and, since batch
    # 4, authors the twelve 2022 windows, so the page and the windows agree
    # and the verdict names the archive page it read against.
    page = str(FIXTURES / SAC_STANDINGS[2022][0])
    assert main(["--standings", page, "--conference", "SAC", "--season", "2022"]) == 0
    captured = capsys.readouterr()
    assert "https://www.thesac.com/standings.aspx?standings=73" in captured.out
    assert "page lists 12 teams" in captured.out
    assert "windows resolve 12 members" in captured.out
    assert "agreement" in captured.out
    assert captured.err == ""

    # The flags travel together.
    assert main(["--standings", page]) == 2
