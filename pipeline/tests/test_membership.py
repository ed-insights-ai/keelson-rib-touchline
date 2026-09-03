"""Contract tests for season-aware conference membership."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src import membership, paths
from src.canon import PROGRAMMES, REGISTRY
from src.config import SchoolConfig
from src.sidearm_live import programme_slug
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
