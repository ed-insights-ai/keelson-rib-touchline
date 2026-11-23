"""Cut the sample data homes from real ones.

The full Division I and II datasets live only in their private data homes.
Every public repo builds and tests against a small slice of them instead:
one conference per division, the current season, both genders, cut from what
the collector actually wrote. This script is the only way that slice is made,
so it can be re-cut after any collect and nobody hand-edits it.

What it copies, per (home, conference, season):

- data/{fixtures,rosters,stats,matches}/{season}-{gender}-{conf}.json,
  byte for byte, for each gender whose fixtures file exists;
- data/coverage.json, keeping only that season's cells for the conference's
  members;
- data/reference/programmes.json, keeping only the programmes the copied
  fixtures name (members and opponents);
- data/reference/membership.json, keeping only the conference's members and,
  for each, only the window that covers the season (or the latest one, which
  the collector carries forward when none is authored for it yet);
- touchline-data.yaml, as is, and data/sample.json, the manifest that tells a
  reader this home is a sample and which season files it holds.

Raw HTML, errors, research, reports and every other season stay behind.

Usage (from pipeline/):

    uv run python -m scripts.cut_sample \
        --home ~/keelson/d2-soccer --conference gac \
        --out ../samples/d2-soccer

Stdlib only; reads the source home, never writes to it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

LAYERS = ("fixtures", "rosters", "stats", "matches")
GENDERS = ("men", "women")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cut(home: Path, conference: str, season: int, out: Path) -> dict:
    data = home / "data"
    marker = home / "touchline-data.yaml"
    if not marker.is_file():
        raise SystemExit(
            f"{home} is not a Touchline data home (no touchline-data.yaml)"
        )

    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    shutil.copy2(marker, out / "touchline-data.yaml")

    files: list[dict] = []
    genders: list[str] = []
    members: dict[str, set[str]] = {}
    named: set[str] = set()
    for gender in GENDERS:
        key = f"{season}-{gender}-{conference}"
        if not (data / "fixtures" / f"{key}.json").is_file():
            continue
        genders.append(gender)
        for layer in LAYERS:
            src = data / layer / f"{key}.json"
            if not src.is_file():
                continue
            dst = out / "data" / layer / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files.append(
                {
                    "path": f"data/{layer}/{src.name}",
                    "bytes": src.stat().st_size,
                    "sha256": _sha256(src),
                }
            )
        fixtures = _load(data / "fixtures" / f"{key}.json")
        members[gender] = {p["slug"] for p in fixtures.get("programmes", [])}
        named |= members[gender]
        for row in fixtures.get("fixtures", []):
            for side in ("home", "away"):
                if isinstance(row.get(side), str):
                    named.add(row[side])

    if not genders:
        raise SystemExit(
            f"no {season} fixtures for conference {conference!r} under {data}"
        )

    # Coverage: this season's cells for the members, per gender.
    coverage = _load(data / "coverage.json")
    coverage["cells"] = {
        k: v
        for k, v in coverage["cells"].items()
        if (parts := k.split("/"))[0] == str(season)
        and parts[1] in members
        and parts[2] in members[parts[1]]
    }
    _dump(out / "data" / "coverage.json", coverage)

    ref = data / "reference"
    # Programmes: identity rows for every programme the fixtures name.
    if (ref / "programmes.json").is_file():
        programmes = _load(ref / "programmes.json")
        programmes["programmes"] = {
            slug: row for slug, row in programmes["programmes"].items() if slug in named
        }
        _dump(out / "data" / "reference" / "programmes.json", programmes)

    # Membership: the conference's members, only the windows covering the season.
    if (ref / "membership.json").is_file():
        membership = _load(ref / "membership.json")
        code = conference.upper()
        kept: dict[str, dict] = {}
        for slug, by_gender in membership["memberships"].items():
            for gender, windows in by_gender.items():
                if gender not in members or slug not in members[gender]:
                    continue
                hit = [
                    w
                    for w in windows
                    if w.get("from_season", 0) <= season <= w.get("to_season", season)
                ]
                if not hit:
                    # Windows end at the last authored season; the collector
                    # carries the latest one forward (membership_extrapolated),
                    # so the sample keeps that window.
                    past = [w for w in windows if w.get("to_season", 0) < season]
                    hit = [max(past, key=lambda w: w["to_season"])] if past else []
                if hit:
                    kept.setdefault(slug, {})[gender] = hit
        membership["memberships"] = kept
        membership["seasons"] = {"from": season, "to": season}
        if "standings_archives" in membership:
            membership["standings_archives"] = {
                k: v for k, v in membership["standings_archives"].items() if k == code
            }
        _dump(out / "data" / "reference" / "membership.json", membership)

    manifest = {
        "schema": "touchline.sample/1",
        "description": (
            "A sample data home: one conference, one season, cut from the real home by "
            "pipeline/scripts/cut_sample.py. Readers that see this file build only the "
            "season files it lists."
        ),
        "level": _level(marker),
        "season": season,
        "conference": conference,
        "genders": genders,
        "programmes": {g: sorted(members[g]) for g in genders},
        "cut_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "files": files,
    }
    _dump(out / "data" / "sample.json", manifest)
    return manifest


def _level(marker: Path) -> str | None:
    for line in marker.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("level:"):
            return line.split(":", 1)[1].strip()
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--home", required=True, type=Path, help="the real data home (contains data/)"
    )
    ap.add_argument(
        "--conference", required=True, help="conference file key, e.g. gac or a10"
    )
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument(
        "--out", required=True, type=Path, help="the sample home to (re)write"
    )
    args = ap.parse_args(argv)
    manifest = cut(args.home.expanduser(), args.conference, args.season, args.out)
    total = sum(f["bytes"] for f in manifest["files"])
    print(
        f"cut {manifest['level']} {manifest['conference']} {manifest['season']} "
        f"({', '.join(manifest['genders'])}): {len(manifest['files'])} season files, "
        f"{total / 1e6:.1f} MB -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
