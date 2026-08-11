"""Build the deterministic scouting digest for one (season, gender) unit.

Reads the data home's season files and writes ``data/reports/digest-<season>-
<gender>.json`` — the only source of figures a generated scouting report may
cite.  Run after a collect; this command never touches the network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import paths
from src.digest import build_digest


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute the scouting digest from collected season files."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--gender", choices=["men", "women"], required=True)
    parser.add_argument(
        "--focus",
        required=True,
        help="Programme slug the report is being prepared for, e.g. 'harding'.",
    )
    args = parser.parse_args()

    root = paths.data_root()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        digest = build_digest(
            root,
            season=args.season,
            gender=args.gender,
            focus=args.focus,
            generated_at=generated_at,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    out = root / "data" / "reports" / f"digest-{args.season}-{args.gender}-{args.focus}.json"
    _atomic_json(out, digest)

    sections = digest["programmes"]
    with_h2h = sum(1 for section in sections.values() if "head_to_head" in section)
    with_turnover = sum(1 for section in sections.values() if "turnover" in section)
    print(f"wrote {out}")
    print(
        f"digest: {len(sections)} programmes ({digest['conference']} {args.gender} "
        f"{args.season}, focus {args.focus}), previous season {digest['previous_season']}, "
        f"seasons held {digest['seasons_held'][0]}-{digest['seasons_held'][-1]}"
        if digest["seasons_held"]
        else f"digest: {len(sections)} programmes"
    )
    print(
        f"turnover computed for {with_turnover}/{len(sections)} programmes; "
        f"head-to-head held for {with_h2h}/{max(len(sections) - 1, 0)} opponents"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
