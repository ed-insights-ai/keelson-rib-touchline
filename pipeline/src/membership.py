"""Season-aware conference-membership reference data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import paths
from src.config import SchoolConfig, load_schools


def load_membership(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the authored membership document.

    With no explicit ``path``, the rib's packaged copy is preferred — it is
    the source of record — and the data home's mirrored copy is only the
    fallback for an install that ships no packaged data tree. Collect keeps
    the mirror fresh (scripts/collect_board.py) and the data-integrity
    workflow's membership-sync check reports any divergence, so the two
    surfaces can never quietly resolve different member lists.
    """
    if path is not None:
        membership_path = Path(path)
        if not membership_path.exists():
            raise FileNotFoundError(
                f"Membership file not found: {membership_path}"
            )
    else:
        packaged = paths.packaged_membership_path()
        membership_path = (
            packaged if packaged.exists() else paths.membership_path()
        )
        if not membership_path.exists():
            raise FileNotFoundError(
                "Membership file not found: no packaged copy at "
                f"{packaged} and no data home copy at {membership_path}"
            )

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


def _season_span(
    document: dict[str, Any],
    errors: list[str],
) -> tuple[int, int] | None:
    seasons = document.get("seasons")
    if not isinstance(seasons, dict):
        errors.append("seasons must be an object with integer 'from' and 'to'")
        return None

    from_season = seasons.get("from")
    to_season = seasons.get("to")
    if not _is_year(from_season) or not _is_year(to_season):
        errors.append("seasons 'from' and 'to' must be integers")
        return None
    if from_season > to_season:
        errors.append(
            "seasons 'from' must not exceed 'to' "
            f"({from_season} > {to_season})"
        )
        return None
    return from_season, to_season


def _declared_conferences(
    document: dict[str, Any],
    errors: list[str],
) -> set[str] | None:
    conferences = document.get("conferences")
    if not isinstance(conferences, list) or not all(
        isinstance(conference, str) for conference in conferences
    ):
        errors.append("conferences must be a list of strings")
        return None

    declared = set(conferences)
    if len(conferences) != len(declared):
        errors.append("conferences must not contain duplicate codes")

    missing_structural = sorted({"independent", "non_member"} - declared)
    if missing_structural:
        errors.append(
            f"conferences must declare structural codes: {missing_structural}"
        )
    return declared


def _validate_windows(
    programme: str,
    windows: list[object],
    errors: list[str],
    *,
    span: tuple[int, int] | None,
    declared: set[str] | None,
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
        if declared is not None and conference not in declared:
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
        if span is not None and (
            from_season < span[0] or to_season > span[1]
        ):
            errors.append(
                f"{label} falls outside {span[0]}-{span[1]}: "
                f"{from_season}-{to_season}"
            )

    if valid_ranges:
        authored_from = min(from_season for from_season, _ in valid_ranges)
        authored_to = max(to_season for _, to_season in valid_ranges)
        authored_counts = {
            year: 0 for year in range(authored_from, authored_to + 1)
        }
        for from_season, to_season in valid_ranges:
            for year in range(from_season, to_season + 1):
                authored_counts[year] += 1

        gaps = [
            year for year, count in authored_counts.items() if count == 0
        ]
        if gaps:
            errors.append(
                f"{programme} has membership gaps at seasons {gaps}; "
                "cover them explicitly with an independent or non_member window"
            )

    if span is not None:
        season_counts = {year: 0 for year in range(span[0], span[1] + 1)}
        for from_season, to_season in valid_ranges:
            for year in range(
                max(from_season, span[0]),
                min(to_season, span[1]) + 1,
            ):
                season_counts[year] += 1

        overlaps = [
            year for year, count in season_counts.items() if count > 1
        ]
        if overlaps:
            errors.append(
                f"{programme} has overlapping windows at seasons {overlaps}"
            )


def validate(
    document: dict[str, Any],
    *,
    schools: list[SchoolConfig] | None = None,
) -> list[str]:
    """Return every membership contract violation in a document."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["membership document root must be a JSON object"]

    if document.get("version") != 1:
        errors.append("version must be 1")

    span = _season_span(document, errors)
    declared = _declared_conferences(document, errors)

    if schools is None:
        schools = load_schools()
    from src.sidearm_live import programme_slug

    configured_programmes = {
        (programme_slug(school.name), school.gender) for school in schools
    }
    configured_slugs = {programme_slug(school.name) for school in schools}
    memberships = document.get("memberships")
    if not isinstance(memberships, dict):
        errors.append("memberships must be a JSON object")
        errors.append(
            f"missing configured programmes: {sorted(configured_programmes)}"
        )
        return errors

    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not slug:
            errors.append(f"invalid institution slug key: {slug!r}")
            continue
        if slug not in configured_slugs:
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
                errors,
                span=span,
                declared=declared,
            )

    covered = covered_programmes(document)
    missing = sorted(configured_programmes - covered)
    if missing:
        errors.append(f"missing configured programmes: {missing}")

    return errors
