"""Same-date, same-side pairs whose OTHER side carries two slugs — read-only.

A programme plays one match a day, so two fixture rows in one season file
on one date with the same slug on one side and two different slugs on the
other are one fixture filed under two opponent identities: the collector
read the same opponent off two pages spelled two ways and minted two slugs
(tl-kvn: "ut-dallas" beside "of-texas-at-dallas"). The two records carry
distinct match identities, so no downstream fold can rejoin them, and when
the date arrives one takes the result while the other manufactures a
past-date silence.

Every fixture file under the data home is swept; nothing here names a
conference. For each pair the sweep re-folds each stored slug (its hyphens
read as spaces) through the collector's current identity rules and says
what a fresh collect would do: which fold rule joins them
(``src.sidearm_live.identity_fold_rules``), whether a stanza alias does, or
that they still stand apart and need a spelling decision. Not every pair is
this defect — a host can meet two visitors in a one-day tournament, and a
neutral-site match between two members is filed with either as home — so
every pair is listed and the verdict word says which kind it is.

Output: one line per pair, then one JSON verdict line. The exit code is
always 0; the data home is only read.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from src.config import load_schools
from src.membership import load_membership, shard_stanzas
from src.paths import data_root
from src.sidearm_live import (
    FOLD_INSTITUTION,
    _identity_key,
    identity_aliases,
    identity_fold_rules,
    opponent_slug,
)

CHECK = "opponent-slug-twins"


def _cell_of(path: Path) -> tuple[str, str] | None:
    parts = path.stem.split("-")
    if len(parts) < 3:
        return None
    return path.stem, parts[1]


def _spelling(slug: str) -> str:
    return slug.replace("-", " ")


def _how_joined(variants: list[str], aliases: dict[str, str]) -> tuple[str, str]:
    """(verdict, detail) for one set of same-side slugs re-folded today.

    ``fold`` when the fold alone makes one key of all of them, naming the
    rules that did it; ``alias`` when a stanza alias joins them, naming the
    slug; ``apart`` otherwise, naming what each still resolves to.
    """
    keys = {_identity_key(_spelling(slug)) for slug in variants}
    resolved = {opponent_slug(_spelling(slug), aliases) for slug in variants}
    rules = sorted(
        {
            rule
            for slug in variants
            for rule in identity_fold_rules(_spelling(slug))
            if rule != FOLD_INSTITUTION
        }
    )
    if len(keys) == 1:
        return "fold", "+".join(rules) or FOLD_INSTITUTION
    if len(resolved) == 1:
        return "alias", next(iter(resolved))
    return "apart", " | ".join(sorted(resolved))


def sweep(home: Path) -> dict[str, object]:
    """Pair every same-date same-side twin under a data home. Pure; reads only."""
    schools = load_schools()
    try:
        document: dict[str, object] | None = load_membership()
    except (OSError, ValueError):
        document = None
    findings: list[str] = []
    counts = {"files": 0, "pairs": 0, "fold": 0, "alias": 0, "apart": 0}
    variants: dict[str, set[str]] = defaultdict(set)
    fixtures_dir = home / "data" / "fixtures"
    for fpath in sorted(fixtures_dir.glob("*-*-*.json")):
        cell = _cell_of(fpath)
        if cell is None:
            continue
        name, gender = cell
        rows = json.loads(fpath.read_text()).get("fixtures", [])
        counts["files"] += 1
        # The table the file's collect resolved against: its conference's
        # NCAA level that season, so a slug is re-read the way it was minted.
        aliases = identity_aliases(
            shard_stanzas(schools, name, document=document), gender=gender
        )
        groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for row in rows:
            date, home_slug, away_slug = (
                str(row.get("date") or ""),
                str(row.get("home") or ""),
                str(row.get("away") or ""),
            )
            if not (date and home_slug and away_slug):
                continue
            groups[(date, "home", home_slug)].add(away_slug)
            groups[(date, "away", away_slug)].add(home_slug)
        for (date, side, shared), others in sorted(groups.items()):
            if len(others) < 2:
                continue
            listed = sorted(others)
            verdict, detail = _how_joined(listed, aliases)
            counts["pairs"] += 1
            counts[verdict] += 1
            variants[verdict].update(listed)
            findings.append(
                f"{verdict.upper()} {name} {date} {side}={shared}: "
                f"{' | '.join(listed)} -> {detail}"
            )
    return {
        "findings": findings,
        "counts": counts,
        "variants": {k: sorted(v) for k, v in variants.items()},
    }


def main() -> int:
    home = data_root()
    if not (home / "data" / "fixtures").is_dir():
        print(
            json.dumps(
                {
                    "check": CHECK,
                    "verdict": "alarm",
                    "headline": f"CHECK DID NOT RUN — no fixtures layer under {home}",
                    "cause": "TOUCHLINE_DATA_DIR (or the cwd) is not a collected data home",
                }
            )
        )
        return 0
    out = sweep(home)
    for line in out["findings"]:
        print(line)
    counts = out["counts"]
    print(
        json.dumps(
            {
                "check": CHECK,
                "verdict": "ok" if counts["pairs"] == 0 else "warn",
                "headline": (
                    f"{counts['pairs']} same-date same-side pairs across "
                    f"{counts['files']} files: {counts['fold']} the fold joins, "
                    f"{counts['alias']} an alias joins, {counts['apart']} stand apart"
                ),
                "counts": counts,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
