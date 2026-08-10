"""Render the preseason scouting briefing from the digest + a narrative file.

The digest supplies every figure; the narrative file (written by the report
workflow's analyst/research nodes, or absent) supplies prose. Offline by
design — collection and research happen upstream.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import paths
from src.report import render_appendix, render_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the preseason scouting briefing HTML."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--gender", choices=["men", "women"], required=True)
    parser.add_argument(
        "--narrative",
        help="Path to a touchline.report-narrative/1 JSON file; default "
        "data/reports/narrative-<season>-<gender>.json when present.",
    )
    args = parser.parse_args()

    root = paths.data_root()
    digest_path = root / "data" / "reports" / f"digest-{args.season}-{args.gender}.json"
    try:
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
    except OSError:
        print(f"no digest at {digest_path} — run build-digest first", file=sys.stderr)
        return 2

    narrative_path = (
        Path(args.narrative)
        if args.narrative
        else root / "data" / "reports" / f"narrative-{args.season}-{args.gender}.json"
    )
    narrative: dict = {}
    if narrative_path.exists():
        narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
        print(f"narrative: {narrative_path}")
    else:
        print("narrative: none — rendering the deterministic skeleton with placeholders")

    out = root / "data" / "reports" / f"preseason-{args.season}-{args.gender}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(digest, narrative), encoding="utf-8")
    print(f"wrote {out}")

    appendix = root / "data" / "reports" / f"preseason-{args.season}-{args.gender}-appendix.html"
    appendix.write_text(render_appendix(digest), encoding="utf-8")
    print(f"wrote {appendix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
