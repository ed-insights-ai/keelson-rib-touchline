"""Who each box-score line is — ``player_ref`` coverage by route, per file.

A box score links a bio for the site owner's roster only, so ``player_id``
(the id as the page printed it) is absent on the opponent's side of every
match.  The writer resolves a ``player_ref`` on every line anyway, by four
routes in a fixed order — the page's own link, the opponent's own box of
the same match, the programme's season roster, or a synthetic key — and
this check measures how far each season file got: the owner side's
``page`` share (the parser's number, which must not fall), the opponent
side's share by route, the lines that fell to ``key`` and why, and every
line where the twin box and the roster named different ids (one of the two
sources is wrong).  A file still under ``touchline.matches/1`` carries no
refs at all and is named as such, not counted as zero coverage.

Output: one line per file, then one JSON verdict line the data-integrity
report reads.  The exit code is always 0 — a check that cannot run says so
in the verdict, never by dying.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from src.identity import SOURCES, IdentityReport, SeasonSources, resolve_matches
from src.paths import data_root

CHECK = "player-identity"
CURRENT_SCHEMA = "touchline.matches/2"


def _verdict(verdict: str, headline: str, cause: str = "") -> int:
    print(
        json.dumps(
            {"check": CHECK, "verdict": verdict, "headline": headline, "cause": cause}
        )
    )
    return 0


def _read(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _count_stored(matches: dict[str, object]) -> tuple[Counter[str], int]:
    """The refs a file carries, by source, and its lines without one."""
    by_source: Counter[str] = Counter()
    without = 0
    for match in matches.values():
        teams = match.get("teams") if isinstance(match, dict) else None
        for team in teams if isinstance(teams, list) else []:
            for key in ("players", "keepers"):
                for line in team.get(key) or []:
                    ref = line.get("player_ref") if isinstance(line, dict) else None
                    if isinstance(ref, dict) and ref.get("source") in SOURCES:
                        by_source[str(ref["source"])] += 1
                    else:
                        without += 1
    return by_source, without


def sweep(home: Path) -> dict[str, object]:
    """Every matches file under a data home: its stored refs, and a fresh
    resolution over the same season files, so a file the writer has not
    rewritten yet still reports what the resolver would give it."""
    lines: list[str] = []
    counts: Counter[str] = Counter()
    legacy: list[str] = []
    unresolved_files: list[str] = []
    disagreements: list[str] = []
    owner_page_shares: list[tuple[str, float]] = []
    matches_dir = home / "data" / "matches"
    seasons: dict[tuple[int, str], SeasonSources] = {}
    for path in sorted(matches_dir.glob("*-*-*.json")):
        parts = path.stem.split("-", 2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        season, gender = int(parts[0]), parts[1]
        payload = _read(path)
        fixtures = _read(home / "data" / "fixtures" / path.name)
        if payload is None or fixtures is None:
            unresolved_files.append(path.name)
            continue
        matches = payload.get("matches")
        if not isinstance(matches, dict):
            unresolved_files.append(path.name)
            continue
        counts["files"] += 1
        stored, without = _count_stored(matches)
        if payload.get("schema") != CURRENT_SCHEMA:
            legacy.append(path.name)
        elif without:
            counts["lines_without_ref"] += without
            lines.append(
                f"NO_REF {path.name}: {without} line(s) carry no player_ref under {CURRENT_SCHEMA}"
            )
        sources = seasons.get((season, gender))
        if sources is None:
            sources = SeasonSources()
            sources.load_disk(home, season, gender)
            seasons[(season, gender)] = sources
        report = IdentityReport()
        resolve_matches(
            json.loads(json.dumps(matches)),
            list(fixtures.get("fixtures") or []),  # type: ignore[arg-type]
            sources,
            report=report,
        )
        for (side, source), n in report.counts.items():
            counts[f"{side}_{source}"] += n
        for reason, n in report.misses.items():
            counts[f"miss_{reason}"] += n
        owner_page_shares.append((path.name, report.share("owner", "page")))
        for finding in report.disagreements:
            disagreements.append(f"DISAGREE {path.name} {finding}")
        opponent = report.lines("opponent")
        cells = " · ".join(
            f"{source} {report.counts[('opponent', source)]}"
            for source in SOURCES
            if report.counts[("opponent", source)]
        )
        stamp = (
            ""
            if payload.get("schema") == CURRENT_SCHEMA
            else "  [legacy file, no refs stored]"
        )
        lines.append(
            f"{path.name}: owner page {report.share('owner', 'page'):.1%} of "
            f"{report.lines('owner')}; opponent {opponent} lines: {cells or 'none'}"
            + (
                " (key by reason: "
                + ", ".join(f"{r} {n}" for r, n in sorted(report.misses.items()))
                + ")"
                if report.misses
                else ""
            )
            + stamp
        )
    return {
        "lines": lines,
        "counts": counts,
        "legacy": legacy,
        "unresolved_files": unresolved_files,
        "disagreements": disagreements,
        "owner_page_shares": owner_page_shares,
    }


def main() -> int:
    home = data_root()
    if not (home / "data" / "matches").is_dir():
        return _verdict(
            "alarm",
            f"CHECK DID NOT RUN — no data/matches under {home}. A missing layer directory is not an empty one.",
            "TOUCHLINE_DATA_DIR must point at a collected data home",
        )
    try:
        result = sweep(home)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return _verdict(
            "alarm",
            f"CHECK DID NOT RUN — {type(error).__name__}: {error}",
            "a season or match file could not be read in the shape this check knows; inspect it by hand",
        )
    counts = result["counts"]
    assert isinstance(counts, dict)
    if counts["files"] == 0:
        return _verdict(
            "alarm",
            f"CHECK DID NOT RUN — no matches file under {home}. Nothing was measured.",
            "collect a season with box scores first",
        )
    for line in result["lines"]:  # type: ignore[union-attr]
        print(line)
    for line in result["disagreements"]:  # type: ignore[union-attr]
        print(line)
    for name in result["unresolved_files"]:  # type: ignore[union-attr]
        print(
            f"UNREADABLE {name}: no fixtures file beside it, or not the shape this check knows"
        )
    opponent = sum(counts[f"opponent_{s}"] for s in SOURCES)
    owner = sum(counts[f"owner_{s}"] for s in SOURCES)
    resolved = opponent - counts["opponent_key"]
    misses = ", ".join(
        f"{k[5:]} {n}" for k, n in sorted(counts.items()) if k.startswith("miss_")
    )
    legacy = result["legacy"]
    disagreements = result["disagreements"]
    assert isinstance(legacy, list) and isinstance(disagreements, list)
    bad = counts["lines_without_ref"] or result["unresolved_files"]
    verdict = "alarm" if bad else "warn" if disagreements or legacy else "ok"
    return _verdict(
        verdict,
        f"opponent side: {resolved} of {opponent} lines resolved "
        f"(twin {counts['opponent_twin']}, roster {counts['opponent_roster']}, "
        f"page {counts['opponent_page']}; key {counts['opponent_key']}: {misses or 'none'}); "
        f"owner side: page {counts['owner_page']} of {owner}; "
        f"{len(disagreements)} twin/roster disagreement(s); "
        f"{len(legacy)} of {counts['files']} files still {CURRENT_SCHEMA[:-1]}1 (no refs stored); "
        f"{counts['lines_without_ref']} lines without a ref under {CURRENT_SCHEMA} — each named above",
        "a player_ref is a function of the season's files, so a line without one under the current "
        "schema is a writer fault; a legacy file is rewritten by the next collect of that season "
        "(the backfill workflow, no refetch); a disagreement means the twin box and the roster name "
        "different ids for one line — one of the two sources is wrong, inspect both pages.",
    )


if __name__ == "__main__":
    sys.exit(main())
