"""Season-aware conference-membership reference data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import paths
from src.canon import PROGRAMMES, REGISTRY

SEASON_FROM = 2016
SEASON_TO = 2025
REQUIRED_CONFERENCES = {"independent", "non_member"}


def load_membership(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the authored membership document."""
    membership_path = Path(path) if path is not None else paths.membership_path()
    if not membership_path.exists():
        raise FileNotFoundError(f"Membership file not found: {membership_path}")

    with membership_path.open(encoding="utf-8") as membership_file:
        document = json.load(membership_file)

    if not isinstance(document, dict):
        raise ValueError("membership.json root must be a JSON object")
    return document


def conference_for(
    slug: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """Return the programme's conference for one season, if declared."""
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return None

    genders = memberships.get(slug)
    if not isinstance(genders, dict):
        return None
    windows = genders.get(gender)
    if not isinstance(windows, list):
        return None

    for window in windows:
        if not isinstance(window, dict):
            continue
        from_season = window.get("from_season")
        to_season = window.get("to_season")
        conference = window.get("conference")
        if (
            _is_year(from_season)
            and _is_year(to_season)
            and from_season <= season_year <= to_season
            and isinstance(conference, str)
        ):
            return conference
    return None


def is_conference_member(
    slug: str,
    gender: str,
    season_year: int,
    conference: str,
    *,
    document: dict[str, Any] | None = None,
) -> bool:
    """Return whether a programme belongs to a conference for one season."""
    return (
        conference_for(
            slug,
            gender,
            season_year,
            document=document,
        )
        == conference
    )


def covered_programmes(document: dict[str, Any]) -> set[tuple[str, str]]:
    """Return every slug and gender pair represented by the document."""
    memberships = document.get("memberships")
    if not isinstance(memberships, dict):
        return set()

    covered: set[tuple[str, str]] = set()
    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not isinstance(genders, dict):
            continue
        for gender in genders:
            if isinstance(gender, str):
                covered.add((slug, gender))
    return covered


def _is_year(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_windows(
    programme: str,
    windows: list[object],
    declared_conferences: set[str],
    errors: list[str],
) -> None:
    if not windows:
        errors.append(f"{programme} must declare at least one membership window")
        return

    valid_ranges: list[tuple[int, int]] = []
    for index, window in enumerate(windows):
        label = f"{programme} window {index}"
        if not isinstance(window, dict):
            errors.append(f"{label} must be a JSON object")
            continue

        conference = window.get("conference")
        if conference not in declared_conferences:
            errors.append(f"{label} has unknown conference code {conference!r}")

        source = window.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"{label} must have a non-empty source citation")

        from_season = window.get("from_season")
        to_season = window.get("to_season")
        if not _is_year(from_season):
            errors.append(f"{label} from_season must be an integer")
        if not _is_year(to_season):
            errors.append(f"{label} to_season must be an integer")
        if not _is_year(from_season) or not _is_year(to_season):
            continue
        if from_season > to_season:
            errors.append(
                f"{label} has from_season greater than to_season "
                f"({from_season} > {to_season})"
            )
            continue

        valid_ranges.append((from_season, to_season))
        if from_season < SEASON_FROM or to_season > SEASON_TO:
            errors.append(
                f"{label} falls outside {SEASON_FROM}-{SEASON_TO}: "
                f"{from_season}-{to_season}"
            )

    season_counts = {year: 0 for year in range(SEASON_FROM, SEASON_TO + 1)}
    for from_season, to_season in valid_ranges:
        for year in range(
            max(from_season, SEASON_FROM),
            min(to_season, SEASON_TO) + 1,
        ):
            season_counts[year] += 1

    gaps = [year for year, count in season_counts.items() if count == 0]
    overlaps = [year for year, count in season_counts.items() if count > 1]
    if gaps:
        errors.append(f"{programme} has membership gaps at seasons {gaps}")
    if overlaps:
        errors.append(f"{programme} has overlapping windows at seasons {overlaps}")


def validate(document: dict[str, Any]) -> list[str]:
    """Return every membership contract violation in a document."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["membership document root must be a JSON object"]

    if document.get("version") != 1:
        errors.append("version must be 1")

    seasons = document.get("seasons")
    expected_seasons = {"from": SEASON_FROM, "to": SEASON_TO}
    if seasons != expected_seasons:
        errors.append(f"seasons must equal {expected_seasons}")

    conferences = document.get("conferences")
    declared_conferences: set[str] = set()
    if not isinstance(conferences, list) or not all(
        isinstance(conference, str) for conference in conferences
    ):
        errors.append("conferences must be a list of strings")
    else:
        declared_conferences = set(conferences)
        missing_conferences = sorted(REQUIRED_CONFERENCES - declared_conferences)
        if missing_conferences:
            errors.append(
                f"conferences omits required codes: {missing_conferences}"
            )
        if len(conferences) != len(declared_conferences):
            errors.append("conferences must not contain duplicate codes")

    memberships = document.get("memberships")
    expected_programmes = {
        (programme["institution_slug"], programme["gender"])
        for programme in PROGRAMMES.values()
    }
    if not isinstance(memberships, dict):
        errors.append("memberships must be a JSON object")
        errors.append(
            f"missing canon programmes: {sorted(expected_programmes)}"
        )
        return errors

    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not slug:
            errors.append(f"invalid institution slug key: {slug!r}")
            continue
        if slug not in REGISTRY:
            errors.append(f"unknown institution slug: {slug!r}")
        if not isinstance(genders, dict):
            errors.append(f"{slug} memberships must be a JSON object")
            continue

        for gender, windows in genders.items():
            programme = f"{slug}:{gender}"
            if not isinstance(gender, str) or not gender:
                errors.append(f"{slug} has invalid gender key: {gender!r}")
                continue
            if not isinstance(windows, list):
                errors.append(f"{programme} windows must be a JSON array")
                continue
            _validate_windows(
                programme,
                windows,
                declared_conferences,
                errors,
            )

    actual_programmes = covered_programmes(document)
    missing_programmes = sorted(expected_programmes - actual_programmes)
    extra_programmes = sorted(actual_programmes - expected_programmes)
    if missing_programmes:
        errors.append(f"missing canon programmes: {missing_programmes}")
    if extra_programmes:
        errors.append(f"undeclared canon programmes: {extra_programmes}")

    return errors
