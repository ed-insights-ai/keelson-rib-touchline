"""Box score versus fixture, BY TEAM NAME — the second source for a result.

A fixture stores a scoreline against two slugs; a box score stores the same
scoreline against two published team names. They are two copies of one fact
made by two parsers reading two pages, and they can only agree by being
right. The stored ``home_index`` on a box is NOT used here: it was derived
by matching scores to the fixture, so it inherits the fixture's mistakes —
which is exactly how twenty reversed Oklahoma Christian results passed
every check (tl-b39). Each team name is resolved to a slug through the
same identity rules the collector uses for opponents, then the score the
box gives the fixture's home slug must equal ``home_score``, and likewise
away. A box whose names resolve to neither slug is counted as unresolved
and named; it is not a pass.

Output: one line per finding, then one JSON verdict line the data-integrity
report reads. The exit code is always 0 — a check that cannot run says so
in the verdict, never by dying.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.config import load_schools
from src.membership import load_membership, shard_programmes, shard_stanzas
from src.paths import data_root
from src.sidearm_live import identity_aliases, opponent_slug

CHECK = "box-vs-fixture"


def _verdict(verdict: str, headline: str, cause: str = "") -> int:
    print(
        json.dumps(
            {"check": CHECK, "verdict": verdict, "headline": headline, "cause": cause}
        )
    )
    return 0


def _cell_of(path: Path) -> tuple[str, str] | None:
    parts = path.stem.split("-")
    if len(parts) < 3:
        return None
    return path.stem, parts[1]


def _side_of(
    name: str, abbr: str, aliases: dict[str, str], home: str, away: str
) -> str | None:
    """Which fixture slug a published team name is, or None when neither."""
    candidates = {opponent_slug(text, aliases) for text in (name, abbr) if text}
    hits = {
        side for side, slug in (("home", home), ("away", away)) if slug in candidates
    }
    return next(iter(hits)) if len(hits) == 1 else None


def compare(home: Path) -> dict[str, object]:
    """Sweep every (fixtures, matches) pair under a data home. Pure; no I/O beyond reading."""
    schools = load_schools()
    try:
        document: dict[str, object] | None = load_membership()
    except (OSError, ValueError):
        document = None
    findings: list[str] = []
    counts = {
        "cells": 0,
        "compared": 0,
        "reversed": 0,
        "differs": 0,
        "unresolved": 0,
        "home_index": 0,
    }
    fixtures_dir = home / "data" / "fixtures"
    for fpath in sorted(fixtures_dir.glob("*-*-*.json")):
        cell = _cell_of(fpath)
        if cell is None:
            continue
        name, gender = cell
        mpath = home / "data" / "matches" / f"{name}.json"
        if not mpath.exists():
            continue
        payload = json.loads(fpath.read_text())
        fixtures = {str(f["id"]): f for f in payload["fixtures"] if "id" in f}
        raw = json.loads(mpath.read_text())
        matches = raw.get("matches", raw) if isinstance(raw, dict) else {}
        # The table the file's collect resolved against: its conference's
        # NCAA level that season (a structural shard's, its programmes'), so
        # a slug is re-read the way it was minted.
        aliases = identity_aliases(
            shard_stanzas(
                schools,
                name,
                programmes=shard_programmes(payload),
                document=document,
            ),
            gender=gender,
        )
        counts["cells"] += 1
        for fid, box in matches.items():
            fixture = fixtures.get(str(fid))
            teams = box.get("teams") if isinstance(box, dict) else None
            if (
                fixture is None
                or not isinstance(teams, list)
                or len(teams) != 2
                or not all(isinstance(t.get("score"), int) for t in teams)
                or not isinstance(fixture.get("home_score"), int)
                or not isinstance(fixture.get("away_score"), int)
            ):
                continue
            home_slug, away_slug = str(fixture["home"]), str(fixture["away"])
            sides = [
                _side_of(
                    str(t.get("name") or ""),
                    str(t.get("abbr") or ""),
                    aliases,
                    home_slug,
                    away_slug,
                )
                for t in teams
            ]
            label = f"{name} {fid} {fixture.get('date')} {home_slug} v {away_slug}"
            named = [t.get("name") for t in teams]
            if (
                sides.count("home") == 1
                and sides.count("away") <= 1
                and sides[0] != sides[1]
            ):
                home_i = sides.index("home")
            elif sides.count("away") == 1 and sides[0] != sides[1]:
                home_i = 1 - sides.index("away")
            else:
                counts["unresolved"] += 1
                findings.append(
                    f"UNRESOLVED {label}: box names {named} resolve to {sides}"
                )
                continue
            box_home, box_away = teams[home_i]["score"], teams[1 - home_i]["score"]
            counts["compared"] += 1
            stored = (fixture["home_score"], fixture["away_score"])
            if (box_home, box_away) == stored:
                pass
            elif (box_away, box_home) == stored:
                counts["reversed"] += 1
                findings.append(
                    f"REVERSED {label}: fixture stores {stored[0]}-{stored[1]}, box by name says {box_home}-{box_away}"
                )
            else:
                counts["differs"] += 1
                findings.append(
                    f"DIFFERS {label}: fixture stores {stored[0]}-{stored[1]}, box by name says {box_home}-{box_away}"
                )
            hi = box.get("home_index")
            if hi in (0, 1) and hi != home_i:
                counts["home_index"] += 1
                findings.append(
                    f"HOME_INDEX {label}: stored home_index={hi}, the names say {home_i}"
                )
    return {"counts": counts, "findings": findings}


def main() -> int:
    home = data_root()
    if not (home / "data" / "fixtures").is_dir():
        return _verdict(
            "alarm",
            f"CHECK DID NOT RUN — no data/fixtures under {home}. A missing layer directory is not an empty one.",
            "TOUCHLINE_DATA_DIR must point at a collected data home",
        )
    try:
        result = compare(home)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return _verdict(
            "alarm",
            f"CHECK DID NOT RUN — {type(error).__name__}: {error}",
            "a season or match file could not be read in the shape this check knows; inspect it by hand",
        )
    counts = result["counts"]
    findings = result["findings"]
    assert isinstance(counts, dict) and isinstance(findings, list)
    if counts["cells"] == 0:
        return _verdict(
            "alarm",
            f"CHECK DID NOT RUN — no (fixtures, matches) cell pair under {home}. Nothing was compared.",
            "collect a season with box scores first",
        )
    for line in findings:
        print(line)
    bad = counts["reversed"] + counts["differs"]
    verdict = "warn" if bad or counts["home_index"] else "ok"
    return _verdict(
        verdict,
        f"{bad} of {counts['compared']} box scores contradict their fixture's scoreline by team name "
        f"({counts['reversed']} reversed, {counts['differs']} different) across {counts['cells']} cells; "
        f"{counts['home_index']} stored home_index values disagree with the names; "
        f"{counts['unresolved']} boxes name no side this check could resolve — each named above",
        "the box score names its teams and the fixture names its slugs, so the two can only agree by being right. "
        "A reversal is the schedule parser trusting a printed order over the W/L/T letter (tl-b39): re-collect the "
        "named season. A different score is one page updated after the other. An unresolved box is a team name no "
        "stanza alias covers — an alias round, not a pass.",
    )


if __name__ == "__main__":
    sys.exit(main())
