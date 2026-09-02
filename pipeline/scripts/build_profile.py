"""Build or refresh one player profile in the data home.

Without ``--findings`` this recomputes the deterministic record (identity,
career, appearances, availability flags) — offline, from the season files.
With ``--findings`` it additionally merges a verified research findings file
additively (deduplicated on url+text), which is how the player-profile
workflow lands its research.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import paths
from src.profile import upsert_profile


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble or refresh a player profile from collected data."
    )
    parser.add_argument(
        "--programme", required=True, help="Programme slug, e.g. harding."
    )
    parser.add_argument("--gender", choices=["men", "women"], required=True)
    parser.add_argument("--conference", required=True)
    parser.add_argument("--player", required=True, help="Player name as published.")
    parser.add_argument(
        "--findings",
        help="Path to a verified findings JSON file to merge additively.",
    )
    args = parser.parse_args()

    root = paths.data_root()
    findings_file = Path(args.findings) if args.findings else None
    if findings_file is not None and not findings_file.exists():
        print(f"findings file not found: {findings_file}", file=sys.stderr)
        return 2

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        path = upsert_profile(
            root,
            programme=args.programme,
            gender=args.gender,
            conference=args.conference,
            player=args.player,
            generated_at=generated_at,
            findings_file=findings_file,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    profile = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path}")
    print(
        json.dumps(
            {
                "player": profile["player"],
                "programme": profile["programme"],
                "identity": profile.get("identity", {}),
                "career_seasons": [
                    line["season"] for line in profile.get("career", [])
                ],
                "keeper_seasons": [
                    line["season"] for line in profile.get("keeper_career", [])
                ],
                "appearance_seasons": [
                    block["season"] for block in profile.get("appearances", [])
                ],
                "availability_flags": len(profile.get("availability_flags", [])),
                "findings": len(profile.get("findings", [])),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
