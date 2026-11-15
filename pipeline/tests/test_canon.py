"""Contract tests for the canonical team-string identity map."""

from __future__ import annotations

import pytest

from src.canon import ADJUDICATIONS, ALIASES, normalize, resolve

VALID_CLASSIFICATIONS = {"institution_slug", "non_member", "artifact"}


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("#16 Fort Hays St.", "fort hays state"),
        ("#16 Northeastern State", "northeastern state"),
        ("#16 Southern Nazarene", "southern nazarene"),
        ("#19 Southern Nazarene", "southern nazarene"),
        ("Newman  NU", "newman"),
        ("Okla. Baptist  OKLA.", "oklahoma baptist"),
        ("Okla. Christian  OK", "oklahoma christian"),
    ],
)
def test_normalize_observed_source_variants(raw_value, expected):
    assert normalize(raw_value) == expected


def test_normalize_strips_every_published_rank_form():
    """Mirrors the live collector: "#4", "No. 4", bare "4", "RV", and slash pairs.

    The old pattern matched only "#4", so "No. 7 Harding" and "RV Lee" each
    minted an identity that drifted with the poll.
    """
    for published in (
        "#4 Harding",
        "No. 4 Harding",
        "no 4 Harding",
        "4 Harding",
        "No.4 Harding",
        "RV Harding",
        "rv Harding",
        "#RV Harding",
        "(4) Harding",
        "(RV) Harding",
        "(1) #3 Harding",
        "(5) RV Harding",
        "#10 (4) Harding",
        "[4] Harding",
        "#17 [7] Harding",
        "3-seed Harding",
        "#4-seed Harding",
        "5th-Seed Harding",
        "RV/#11 Harding",
        "#11/RV Harding",
        "#21-Harding",
    ):
        assert normalize(published) == normalize("Harding") == "harding"


def test_normalize_leaves_a_name_that_merely_starts_with_rv():
    """The trailing-whitespace requirement is what makes a bare "rv" safe."""
    assert normalize("Rverside") == "rverside"
    assert normalize("RVing Club") == "rving club"
    # An all-caps abbreviation leads far more often than a rank does.
    for abbr in ("UT Tyler", "MSU Denver", "CSU Pueblo", "USC Aiken"):
        assert normalize(abbr) == abbr.lower()


def test_normalize_preserves_distinguishing_parenthetical():
    assert normalize("Southwestern") != normalize("Southwestern (KS)")
    assert normalize("Southwestern (KS)") == "southwestern (ks)"


@pytest.mark.parametrize("raw_value", ["", " ", "\t"])
def test_normalize_rejects_empty_keys(raw_value):
    with pytest.raises(ValueError, match="must not be empty"):
        normalize(raw_value)


@pytest.mark.parametrize(
    ("raw_value", "expected_slug"),
    [
        ("Northwestern OSU", "northwestern-oklahoma-state"),
        ("Southwestern OSU", "southwestern-oklahoma-state"),
        ("Southwestern", "southwestern-oklahoma-state"),
        ("SOUTHWES", "southwestern-oklahoma-state"),
        ("NSU", "northeastern-state"),
        ("NC", "newman"),
    ],
)
def test_must_resolve_adjudications(raw_value, expected_slug):
    resolution = resolve(raw_value)

    assert resolution["classification"] == "institution_slug"
    assert resolution["institution_slug"] == expected_slug
    assert resolution["adjudicated"] is True
    assert resolution["note"]


@pytest.mark.parametrize(
    "raw_value",
    [
        "Southwest Baptist",
        "Dallas Baptist",
        "DBU",
        "Williams Baptist",
        "WBC",
        "Central Baptist",
        "Central Baptist (AR)",
        "CBC",
        "Southwestern Christ.",
        "Southwestern Christi",
        "SW Christian",
        "Southwestern (KS)",
        "Western",
        "ESU",
        "OU",
    ],
)
def test_must_not_resolve_adjudications(raw_value):
    resolution = resolve(raw_value)

    assert resolution["classification"] == "non_member"
    assert resolution["institution_slug"] is None
    assert resolution["adjudicated"] is True
    assert resolution["note"]


@pytest.mark.parametrize(
    ("raw_value", "expected_slug"),
    [
        ("HU", "harding"),
        ("OKBU", "oklahoma-baptist"),
        ("SNU", "southern-nazarene"),
    ],
)
def test_abbreviation_lookalikes_resolve_without_gender(raw_value, expected_slug):
    resolution = resolve(raw_value)

    assert resolution["institution_slug"] == expected_slug
    assert "gender" not in resolution


def test_aliases_are_disjoint_after_normalization():
    owners: dict[str, str] = {}
    for slug, aliases in ALIASES.items():
        for alias in aliases:
            assert normalize(alias) == alias
            assert alias not in owners or owners[alias] == slug
            owners[alias] = slug


def test_every_adjudication_carries_an_evidence_note():
    for raw_key, adjudication in ADJUDICATIONS.items():
        assert adjudication["note"], f"{raw_key!r} is adjudicated without evidence"
        assert adjudication["classification"] in VALID_CLASSIFICATIONS
