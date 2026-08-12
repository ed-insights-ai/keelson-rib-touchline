"""Collect published schedule, roster, statistics, and box-score pages into the board contract.

Layers are collected independently.  A site can serve a past season's schedule
from its DOM archive while its embedded payload still names the current season,
serve a roster for a year whose schedule it refuses, or the reverse — each
layer is proven and lands (or is refused with a named reason) on its own, so
one layer's failure never discards another's data.

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
import time
from datetime import datetime, timezone
from pathlib import Path

from src import coverage, paths
from src.config import DEFAULT_CONFIG, load_schools
from src.sidearm_live import (
    DEFAULT_LAYERS,
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    STATE_EMPTY,
    STATE_NO_COLLECTOR,
    STATE_UNAVAILABLE,
    LiveCollectionError,
    boxscore_links,
    build_session,
    collect_match,
    collect_programme,
    conference_members,
    identity_aliases,
    programme_slug,
    write_raw_pages,
)

FIXTURES_SCHEMA = "touchline.fixtures/2"
ROSTERS_SCHEMA = "touchline.rosters/1"
STATS_SCHEMA = "touchline.stats/1"
MATCHES_SCHEMA = "touchline.matches/1"

COLLECTOR = "sidearm-live"


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _merge_conference_claim(
    winner: dict[str, object], loser: dict[str, object]
) -> None:
    """Resolve one conference flag from a game's two published rows.

    A publisher's own marking (no ``conference_game_source``) outranks a flag
    we derived from membership; between two claims of the same rank a positive
    marking wins, because themes that mark conference games at all only mark
    the positives.
    """

    def claim(row: dict[str, object]) -> tuple[int, bool]:
        published = "conference_game_source" not in row
        return (1 if published else 0, bool(row.get("conference_game")))

    winning_rank, winning_flag = claim(winner)
    losing_rank, losing_flag = claim(loser)
    if losing_rank > winning_rank or (
        losing_rank == winning_rank and losing_flag and not winning_flag
    ):
        winner["conference_game"] = losing_flag
        source = loser.get("conference_game_source")
        winner.pop("conference_game_source", None)
        if source is not None:
            winner["conference_game_source"] = source


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
            by_match[key] = dict(fixture)
            continue
        duplicates += 1
        # Prefer the source that has reached the later lifecycle stage, then
        # retain whichever published more detail — but never lose detail the
        # other side published: each site is authoritative for its own extras
        # (kickoff time, facility), and the conference claim resolves by rank.
        rank = {"scheduled": 0, "postponed": 1, "cancelled": 1, "live": 2, "final": 3}
        existing_score = rank.get(str(existing["status"]), 0) * 10 + len(existing)
        candidate_score = rank.get(str(fixture["status"]), 0) * 10 + len(fixture)
        winner, loser = (
            (dict(fixture), existing)
            if candidate_score > existing_score
            else (existing, dict(fixture))
        )
        for field in ("time", "venue"):
            if field not in winner and field in loser:
                winner[field] = loser[field]
        _merge_conference_claim(winner, loser)
        by_match[key] = winner
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
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, object]],
    list[str],
    int,
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
    # Identity and membership are different questions and must use different
    # sets. Aliases span every configured school so an out-of-conference
    # opponent still gets a canonical slug; membership is one conference, so a
    # cross-conference fixture is not derived into a conference game.
    members = conference_members(schools, gender, conference)
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

        result = collect_programme(
            school, season, aliases, layers=layers, members=members
        )
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
                "conference": candidates[slug].conference
                if slug in candidates
                else conference,
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

    stats_served = set(_served(LAYER_STATS))
    stats_teams = {
        result.slug: {
            "programme": result.slug,
            "source_url": result.stats_url,
            "players": result.stat_players or [],
            "keepers": result.stat_keepers or [],
        }
        for result in results
        if result.state(LAYER_STATS) in {STATE_COMPLETE, STATE_EMPTY}
    }
    stats_payload: dict[str, object] = {
        "schema": STATS_SCHEMA,
        "season": season,
        "gender": gender,
        "collected_at": now,
        "teams": stats_teams,
    }
    stats_missing = sorted(
        {slug for slug in wanted if slug not in stats_served}
        | {
            result.slug
            for result in results
            if result.slug in stats_served
            and not (result.stat_players or result.stat_keepers)
        }
    )
    if stats_missing and LAYER_STATS in layers:
        stats_payload["missing"] = stats_missing

    matches: dict[str, object] = {}
    matches_missing: dict[str, str] = {}
    if LAYER_MATCHES in layers:
        # One box score per deduplicated fixture: a conference game sits on two
        # schedules, and each publishes its own link to the same match under its
        # own game id.  Every published (owner, id) pair is a candidate, so a
        # missing or refusing link on the surviving row's site can still be
        # collected through the other programme's link.
        links_by_owner = {
            result.slug: boxscore_links(
                result.schedule_html, result.schedule_url or ""
            )
            for result in results
            if result.schedule_html
        }
        candidates_by_match: dict[tuple[str, str, str], list[str]] = {}
        for fixture in all_fixtures:
            pair = sorted((str(fixture["home"]), str(fixture["away"])))
            key = (str(fixture["date"]), pair[0], pair[1])
            owner, _, game_id = str(fixture["id"]).rpartition(":")
            owner = owner.split(":")[-1]
            url = links_by_owner.get(owner, {}).get(game_id)
            if url:
                candidates_by_match.setdefault(key, []).append(url)

        session = build_session()
        for fixture in fixtures:
            if str(fixture.get("status")) != "final":
                continue
            fixture_id = str(fixture["id"])
            pair = sorted((str(fixture["home"]), str(fixture["away"])))
            key = (str(fixture["date"]), pair[0], pair[1])
            urls = candidates_by_match.get(key, [])
            if not urls:
                matches_missing[fixture_id] = (
                    "no box-score link on any collected schedule page"
                )
                errors.append(
                    f"match {fixture_id}: no box-score link on any collected schedule page"
                )
                continue
            failures: list[str] = []
            for url in urls:
                try:
                    matches[fixture_id] = collect_match(session, url, season, fixture)
                    break
                except LiveCollectionError as exc:
                    failures.append(str(exc))
                finally:
                    time.sleep(0.2)
            else:
                matches_missing[fixture_id] = "; ".join(failures)
                errors.append(f"match {fixture_id}: {'; '.join(failures)}")

        for result in results:
            if result.state(LAYER_SCHEDULE) == STATE_NO_COLLECTOR:
                record(
                    result.slug,
                    LAYER_MATCHES,
                    coverage.STATE_NO_COLLECTOR,
                    reason=result.outcomes[LAYER_SCHEDULE].reason,
                )
                continue
            if result.state(LAYER_SCHEDULE) not in {STATE_COMPLETE, STATE_EMPTY}:
                record(
                    result.slug,
                    LAYER_MATCHES,
                    STATE_UNAVAILABLE,
                    reason=f"[{season}] no proven schedule to take box-score links from",
                )
                continue
            involved = [
                fixture
                for fixture in fixtures
                if str(fixture.get("status")) == "final"
                and result.slug in (str(fixture["home"]), str(fixture["away"]))
            ]
            collected = [
                fixture for fixture in involved if str(fixture["id"]) in matches
            ]
            if not involved:
                record(
                    result.slug,
                    LAYER_MATCHES,
                    STATE_EMPTY,
                    count=0,
                    reason=f"[{season}] no played fixtures to detail",
                )
            elif len(collected) == len(involved):
                record(
                    result.slug, LAYER_MATCHES, STATE_COMPLETE, count=len(collected)
                )
            else:
                gaps = [
                    str(fixture["id"])
                    for fixture in involved
                    if str(fixture["id"]) not in matches
                ]
                record(
                    result.slug,
                    LAYER_MATCHES,
                    STATE_COMPLETE if collected else STATE_UNAVAILABLE,
                    count=len(collected),
                    reason=(
                        f"[{season}] box scores missing for "
                        f"{len(gaps)} of {len(involved)} played fixtures: "
                        + ", ".join(gaps)
                    ),
                )

    matches_payload: dict[str, object] = {
        "schema": MATCHES_SCHEMA,
        "season": season,
        "gender": gender,
        "collected_at": now,
        "matches": matches,
    }
    if matches_missing:
        matches_payload["missing"] = matches_missing

    return (
        fixture_payload,
        roster_payload,
        stats_payload,
        matches_payload,
        cells,
        errors,
        duplicates,
    )


def widen_to_existing_scope(
    wanted: list[str], *season_paths: Path
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
    for path in season_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for entry in payload.get("programmes") or []:
            if isinstance(entry, dict) and entry.get("slug"):
                existing.add(str(entry["slug"]))
        for field in ("rosters", "teams"):
            keyed = payload.get(field)
            if isinstance(keyed, dict):
                existing.update(str(slug) for slug in keyed)
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
        help="Comma-separated layers to collect: schedule, roster, stats, matches.",
    )
    args = parser.parse_args()

    wanted = [value.strip() for value in args.programmes.split(",") if value.strip()]
    if not wanted:
        print("--programmes resolved to an empty list", file=sys.stderr)
        return 2

    conference_slug = programme_slug(args.conference)
    if not conference_slug:
        print("--conference must contain at least one letter or number", file=sys.stderr)
        return 2

    data_root = paths.data_root()
    season_key = f"{args.season}-{args.gender}-{conference_slug}"
    fixture_path = data_root / "data" / "fixtures" / f"{season_key}.json"
    roster_path = data_root / "data" / "rosters" / f"{season_key}.json"
    stats_path = data_root / "data" / "stats" / f"{season_key}.json"
    matches_path = data_root / "data" / "matches" / f"{season_key}.json"
    wanted, widened = widen_to_existing_scope(
        wanted, fixture_path, roster_path, stats_path
    )
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
    if LAYER_MATCHES in layers and LAYER_SCHEDULE not in layers:
        print(
            "matches are collected through the schedule's own box-score links, "
            "so the schedule layer is included as well."
        )
        layers = (LAYER_SCHEDULE, *layers)

    fixtures, rosters, stats, matches, cells, errors, duplicates = collect(
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
    if LAYER_STATS in layers:
        _atomic_json(stats_path, stats)
        written.append(stats_path)
    if LAYER_MATCHES in layers:
        _atomic_json(matches_path, matches)
        written.append(matches_path)

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
    if LAYER_STATS in layers:
        lines = sum(
            len(team["players"]) + len(team["keepers"])
            for team in stats["teams"].values()
        )
        served = len(wanted) - len(stats.get("missing", []))
        print(f"stats: {served}/{len(wanted)} programmes, {lines} player season lines")
    if LAYER_MATCHES in layers:
        played = sum(
            1 for fixture in fixtures["fixtures"] if fixture["status"] == "final"
        )
        print(
            f"matches: {len(matches['matches'])} of {played} played fixtures "
            f"carry a collected box score"
        )

    if duplicates:
        print(
            f"collapsed {duplicates} duplicate fixture row(s) published by both programmes"
        )

    if errors:
        error_path = (
            data_root
            / "data"
            / "errors"
            / f"collect-board-{season_key}.json"
        )
        _atomic_json(
            error_path,
            {
                "season": args.season,
                "gender": args.gender,
                "conference": args.conference,
                "errors": errors,
            },
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
