"""Collect published schedule and roster pages into the Touchline board contract.

Layers are collected independently.  For the current season a site serves both
its schedule and its roster; for a past season it serves only the roster, and
answers every schedule URL with the current season's fixtures.  A collector that
treated a programme as one indivisible unit could therefore never retrieve a
historical roster, which is the substrate roster analysis needs.

Every run writes `data/coverage.json`, and the exit code reports only whether
that manifest was written.  Named gaps are data, not failures: a run that
collects twelve of thirteen programmes has produced twelve useful cells and one
cell carrying a reason, and discarding that would be worse than keeping it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import coverage, paths
from src.config import DEFAULT_CONFIG, load_schools
from src.sidearm_live import (
    DEFAULT_LAYERS,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    STATE_COMPLETE,
    STATE_EMPTY,
    collect_programme,
    identity_aliases,
    programme_slug,
    write_raw_pages,
)

FIXTURES_SCHEMA = "touchline.fixtures/1"
ROSTERS_SCHEMA = "touchline.rosters/1"

COLLECTOR = "sidearm-live"


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _dedupe_fixtures(
    fixtures: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    by_match: dict[tuple[str, str, str], dict[str, object]] = {}
    duplicates = 0
    for fixture in fixtures:
        home = str(fixture["home"])
        away = str(fixture["away"])
        pair = sorted((home, away))
        key = (str(fixture["date"]), pair[0], pair[1])
        existing = by_match.get(key)
        if existing is None:
            by_match[key] = fixture
            continue
        duplicates += 1
        # Prefer the source that has reached the later lifecycle stage, then
        # retain whichever published more detail.
        rank = {"scheduled": 0, "postponed": 1, "cancelled": 1, "live": 2, "final": 3}
        existing_score = rank.get(str(existing["status"]), 0) * 10 + len(existing)
        candidate_score = rank.get(str(fixture["status"]), 0) * 10 + len(fixture)
        if candidate_score > existing_score:
            by_match[key] = fixture
    values = sorted(
        by_match.values(), key=lambda value: (str(value["date"]), str(value["id"]))
    )
    return values, duplicates


def collect(
    *,
    season: int,
    gender: str,
    conference: str,
    wanted: list[str],
    layers: tuple[str, ...],
    config_path: Path,
    membership_extrapolated: bool,
) -> tuple[
    dict[str, object], dict[str, object], dict[str, dict[str, object]], list[str], int
]:
    schools = load_schools(config_path)
    # `enabled = false` records a programme whose site we have no working recipe
    # for.  Attempting it anyway spends a request to produce a failure we already
    # predicted, and — before the exit contract was fixed — sank the whole run.
    candidates = {
        programme_slug(school.name): school
        for school in schools
        if school.gender == gender and school.enabled
    }
    disabled = {
        programme_slug(school.name): school
        for school in schools
        if school.gender == gender and not school.enabled
    }
    # Scoped to the gender being collected: an opponent string carries no
    # gender, so an unscoped map resolves a men's fixture to a women's-only
    # programme.
    aliases = identity_aliases(schools, gender)
    results = []
    errors: list[str] = []
    cells: dict[str, dict[str, object]] = {}
    root = paths.data_root()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def record(programme: str, layer: str, state: str, **extra: object) -> None:
        cells[coverage.cell_key(season, gender, programme, layer)] = {
            "season": season,
            "gender": gender,
            "programme": programme,
            "layer": layer,
            "state": state,
            "confirmed_at": now,
            "collector": COLLECTOR,
            **{key: value for key, value in extra.items() if value is not None},
        }

    for slug in wanted:
        school = candidates.get(slug)
        if school is None:
            blocked = disabled.get(slug)
            reason = (
                f"{slug}: {blocked.notes or 'programme is disabled in schools.toml'}"
                if blocked is not None
                else f"{slug}: no configured {gender} programme recipe"
            )
            errors.append(reason)
            for layer in layers:
                record(slug, layer, coverage.STATE_NO_COLLECTOR, reason=reason)
            continue

        result = collect_programme(school, season, aliases, layers=layers)
        write_raw_pages(root, result, season, gender)
        results.append(result)
        for layer in layers:
            outcome = result.outcomes.get(layer)
            if outcome is None:
                continue
            record(
                slug,
                layer,
                outcome.state,
                count=outcome.count,
                reason=outcome.reason,
                source_url=outcome.source_url,
            )
            if outcome.reason:
                errors.append(f"{slug} {layer}: {outcome.reason}")

    all_fixtures = [fixture for result in results for fixture in result.fixtures]
    fixtures, duplicates = _dedupe_fixtures(all_fixtures)

    def _served(layer: str) -> list[str]:
        return [
            result.slug
            for result in results
            if result.state(layer) in {STATE_COMPLETE, STATE_EMPTY}
        ]

    schedule_served = set(_served(LAYER_SCHEDULE))
    roster_served = set(_served(LAYER_ROSTER))

    fixture_payload: dict[str, object] = {
        "schema": FIXTURES_SCHEMA,
        "season": season,
        "gender": gender,
        "conference": conference,
        "collected_at": now,
        "membership_extrapolated": membership_extrapolated,
        "conference_game_source": "published:schedule-page",
        "programmes": [
            {
                "slug": slug,
                "name": candidates[slug].name
                if slug in candidates
                else slug.replace("-", " ").title(),
                **(
                    {"abbr": candidates[slug].abbreviation}
                    if slug in candidates and candidates[slug].abbreviation
                    else {}
                ),
            }
            for slug in wanted
        ],
        "fixtures": fixtures,
    }
    schedule_missing = [slug for slug in wanted if slug not in schedule_served]
    if schedule_missing and LAYER_SCHEDULE in layers:
        fixture_payload["missing"] = schedule_missing

    rosters = {
        result.slug: {
            "programme": result.slug,
            "source_url": result.roster_url,
            "players": result.players,
        }
        for result in results
        if result.state(LAYER_ROSTER) in {STATE_COMPLETE, STATE_EMPTY}
    }
    roster_payload: dict[str, object] = {
        "schema": ROSTERS_SCHEMA,
        "season": season,
        "gender": gender,
        "collected_at": now,
        "rosters": rosters,
    }
    roster_missing = sorted(
        {slug for slug in wanted if slug not in roster_served}
        | {
            result.slug
            for result in results
            if not result.players and result.slug in roster_served
        }
    )
    if roster_missing and LAYER_ROSTER in layers:
        roster_payload["missing"] = roster_missing

    return fixture_payload, roster_payload, cells, errors, duplicates


def widen_to_existing_scope(
    wanted: list[str], fixtures_path: Path, rosters_path: Path
) -> tuple[list[str], list[str]]:
    """A season file's scope only ever widens.

    The season files are written wholesale by each run, so a narrower ask
    against a data home that already covers a wider field would rewrite the
    file and silently discard every other programme's data.  Instead the run
    absorbs the existing scope: asking for one programme after a conference
    collection refreshes the whole unit.  Returns the widened list and the
    slugs that were added to it.
    """
    existing: set[str] = set()
    for path in (fixtures_path, rosters_path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for entry in payload.get("programmes") or []:
            if isinstance(entry, dict) and entry.get("slug"):
                existing.add(str(entry["slug"]))
        rosters = payload.get("rosters")
        if isinstance(rosters, dict):
            existing.update(str(slug) for slug in rosters)
        for slug in payload.get("missing") or []:
            existing.add(str(slug))
    added = sorted(existing - set(wanted))
    return wanted + added, added


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect published schedule and roster pages into board JSON."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--gender", choices=["men", "women"], required=True)
    parser.add_argument("--conference", required=True)
    parser.add_argument("--programmes", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--membership-extrapolated", action="store_true")
    parser.add_argument(
        "--layers",
        default=",".join(DEFAULT_LAYERS),
        help=(
            "Comma-separated layers to collect: schedule, roster. Past seasons "
            "serve rosters but not schedules, so a historical ask is roster-only."
        ),
    )
    args = parser.parse_args()

    wanted = [value.strip() for value in args.programmes.split(",") if value.strip()]
    if not wanted:
        print("--programmes resolved to an empty list", file=sys.stderr)
        return 2

    data_root = paths.data_root()
    fixture_path = data_root / "data" / "fixtures" / f"{args.season}-{args.gender}.json"
    roster_path = data_root / "data" / "rosters" / f"{args.season}-{args.gender}.json"
    wanted, widened = widen_to_existing_scope(wanted, fixture_path, roster_path)
    if widened:
        print(
            f"scope widened to the season unit: this data home's {args.season} {args.gender} "
            f"collection already covers {', '.join(widened)}; a run refreshes the whole "
            "unit rather than narrowing the file."
        )

    layers = tuple(value.strip() for value in args.layers.split(",") if value.strip())
    unknown = [layer for layer in layers if layer not in DEFAULT_LAYERS]
    if unknown:
        print(
            f"unknown layer(s): {', '.join(unknown)}. Known: {', '.join(DEFAULT_LAYERS)}",
            file=sys.stderr,
        )
        return 2
    if not layers:
        print("--layers resolved to an empty list", file=sys.stderr)
        return 2

    fixtures, rosters, cells, errors, duplicates = collect(
        season=args.season,
        gender=args.gender,
        conference=args.conference,
        wanted=wanted,
        layers=layers,
        config_path=Path(args.config),
        membership_extrapolated=args.membership_extrapolated,
    )
    written: list[Path] = []
    if LAYER_SCHEDULE in layers:
        _atomic_json(fixture_path, fixtures)
        written.append(fixture_path)
    if LAYER_ROSTER in layers:
        _atomic_json(roster_path, rosters)
        written.append(roster_path)

    # The manifest is the run's real deliverable: it is what lets the next ask
    # be about what is missing rather than about everything.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        manifest = coverage.merge_cells(data_root, cells, updated_at=now)
        manifest_path = coverage.write_coverage(data_root, manifest)
    except (OSError, ValueError) as exc:
        print(f"FAILED to write the coverage manifest: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {', '.join(str(path) for path in written)} and {manifest_path}")

    if LAYER_SCHEDULE in layers:
        played = sum(
            1 for fixture in fixtures["fixtures"] if fixture["status"] == "final"
        )
        upcoming = sum(
            1 for fixture in fixtures["fixtures"] if fixture["status"] == "scheduled"
        )
        served = len(wanted) - len(fixtures.get("missing", []))
        print(
            f"schedule: {served}/{len(wanted)} programmes, "
            f"{len(fixtures['fixtures'])} fixtures ({played} played, {upcoming} upcoming)"
        )
        print("conference flags PUBLISHED by each programme's official schedule page")
    if LAYER_ROSTER in layers:
        players = sum(len(roster["players"]) for roster in rosters["rosters"].values())
        served = len(wanted) - len(rosters.get("missing", []))
        print(f"roster: {served}/{len(wanted)} programmes, {players} players")

    if duplicates:
        print(
            f"collapsed {duplicates} duplicate fixture row(s) published by both programmes"
        )

    if errors:
        error_path = (
            data_root
            / "data"
            / "errors"
            / f"collect-board-{args.season}-{args.gender}.json"
        )
        _atomic_json(
            error_path, {"season": args.season, "gender": args.gender, "errors": errors}
        )
        print(
            f"\n{len(errors)} named gap(s) — recorded in the manifest, not discarded:"
        )
        for error in errors:
            print(f"  GAP: {error}")

    # Exit 0 means the manifest was written and describes reality, gaps and all.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
