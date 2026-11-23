"""Cut the current-season site bundle from a data home.

The site is built from current-season JSON only (it reads no other season), so
the publish workflow does not hand it a whole data home. It cuts this bundle
first, from the home at a known commit, and builds the site from the bundle:

- data/{fixtures,rosters,stats,matches}/{season}-*.json, byte for byte, every
  conference and gender the home holds for the season;
- data/coverage.json and data/reference/*.json, as they are (small, and the
  site reads them whole);
- touchline-data.yaml, as is, and data/sample.json when the home is a sample
  (so a sample bundle still narrows the build to its one conference);
- data/bundle.json, the manifest: level, season, the source home's commit, and
  every copied file with its size and SHA-256.

Raw HTML, errors, research, reports and every other season stay behind. The
snapshot step (DuckDB, signed) reads the same homes at the same commits; the
manifest's ``source`` is what ties the two together.

Usage (from pipeline/):

    uv run python -m scripts.cut_bundle \
        --home ~/keelson/d2-soccer --source-sha "$(git -C ~/keelson/d2-soccer rev-parse HEAD)" \
        --out /tmp/bundle/d2-soccer

Stdlib only; reads the source home, never writes to it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.paths import UNDECLARED_HOME_LEVEL, marker_level

LAYERS = ("fixtures", "rosters", "stats", "matches")
SEASON_FILE = re.compile(r"^(?P<season>\d{4})-(?:men|women)-[a-z0-9-]+\.json$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_season(home: Path) -> int:
    """The latest season the home has fixtures for."""
    seasons = {
        int(m.group("season"))
        for p in (home / "data" / "fixtures").glob("*.json")
        if (m := SEASON_FILE.match(p.name))
    }
    if not seasons:
        raise SystemExit(f"no season fixtures under {home / 'data' / 'fixtures'}")
    return max(seasons)


def _level(marker: Path) -> str:
    try:
        level = marker_level(marker.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"{marker} {exc}") from exc
    return level or UNDECLARED_HOME_LEVEL


def cut(home: Path, out: Path, source_sha: str, season: int | None = None) -> dict:
    home, out = home.resolve(), out.resolve()
    marker = home / "touchline-data.yaml"
    if not marker.is_file():
        raise SystemExit(
            f"{home} is not a Touchline data home (no touchline-data.yaml)"
        )
    if out == home or out.is_relative_to(home) or home.is_relative_to(out):
        raise SystemExit(f"--out {out} overlaps the source home {home}; refusing")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(
            f"--out {out} is not empty; a bundle is cut into a fresh directory"
        )
    season = season or current_season(home)
    data = home / "data"

    copied: list[Path] = []

    def copy(src: Path) -> None:
        dst = out / src.relative_to(home)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)

    copy(marker)
    for layer in LAYERS:
        for src in sorted((data / layer).glob(f"{season}-*.json")):
            if SEASON_FILE.match(src.name):
                copy(src)
    if not any(p.parent.name == "fixtures" for p in copied):
        raise SystemExit(f"no {season} fixtures under {data / 'fixtures'}")
    for name in ("coverage.json", "sample.json"):
        if (data / name).is_file():
            copy(data / name)
    for src in sorted((data / "reference").glob("*.json")):
        copy(src)

    manifest = {
        "schema": "touchline.bundle/1",
        "description": (
            "The current-season site bundle, cut from a data home by "
            "pipeline/scripts/cut_bundle.py. The site builds from it."
        ),
        "level": _level(marker),
        "season": season,
        "sample": (data / "sample.json").is_file(),
        "source": {"home": home.name, "sha": source_sha},
        "cut_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "files": [
            {
                "path": p.relative_to(out).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": _sha256(p),
            }
            for p in copied
        ],
    }
    (out / "data" / "bundle.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--home", required=True, type=Path, help="the data home (contains data/)"
    )
    ap.add_argument("--out", required=True, type=Path, help="a new, empty directory")
    ap.add_argument(
        "--source-sha",
        required=True,
        help="the home's commit, recorded in the manifest",
    )
    ap.add_argument(
        "--season", type=int, help="default: the latest season with fixtures"
    )
    args = ap.parse_args(argv)
    m = cut(args.home.expanduser(), args.out, args.source_sha, args.season)
    total = sum(f["bytes"] for f in m["files"])
    print(
        f"bundle {m['level']} {m['season']}{' (sample)' if m['sample'] else ''} "
        f"from {m['source']['home']}@{m['source']['sha'][:7]}: "
        f"{len(m['files'])} files, {total / 1e6:.1f} MB -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
