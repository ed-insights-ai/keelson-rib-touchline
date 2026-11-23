"""Hold a real data home to the published contracts, before anything ships.

``tests/test_contracts.py`` proves the writers stay within ``contracts/`` on a
synthetic collect. This is the same rule run over what the collector actually
wrote: every season file, the coverage manifest, and the two reference files
under the data home are reduced to shape facts, and any fact no contract
sample carries is drift. Drift means the published files now carry a field,
a type, or an enumerated value that the contract never promised, so a strict
reader (the site, the desk) may refuse it or, worse, read it without knowing
what it means.

Run it after a collect and before a publish:

    TOUCHLINE_DATA_DIR=~/keelson/d2-soccer uv run check-contracts
    uv run check-contracts ~/keelson/d2-soccer samples/d1-soccer

Output: one line per drift fact (with how many files carry it and one of
them), one line per missing file, then one JSON verdict line per home.
Exit 0 when every home is within the contracts, 1 when any is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import contracts
from src.paths import data_root

CHECK = "contracts"


def _report(report: contracts.HomeReport) -> None:
    for (name, (path, kind)), files in sorted(report.drift.items()):
        where = "/".join(path) or "<root>"
        print(
            f"DRIFT {name}: {where}: {kind} "
            f"({len(files)} file{'s' if len(files) != 1 else ''}, e.g. {files[0]})"
        )
    for path in report.missing:
        print(f"MISSING {path.relative_to(report.root)}")
    checked = sum(report.checked.values())
    if report.ok:
        verdict = "pass"
        headline = f"{checked} files within the contracts"
    else:
        verdict = "fail"
        headline = (
            f"{len(report.drift)} shape facts beyond the contracts, "
            f"{len(report.missing)} files missing, across {checked} files"
        )
    print(
        json.dumps(
            {
                "check": CHECK,
                "verdict": verdict,
                "home": str(report.root),
                "headline": headline,
                "checked": report.checked,
            }
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check-contracts",
        description="Check data homes against the published contract samples.",
    )
    parser.add_argument(
        "homes",
        nargs="*",
        type=Path,
        help="data homes to check (default: TOUCHLINE_DATA_DIR, else the cwd)",
    )
    args = parser.parse_args(argv)
    homes = [home.expanduser().resolve() for home in args.homes] or [data_root()]
    ok = True
    for home in homes:
        if not (home / "data").is_dir():
            print(f"MISSING {home}/data: not a Touchline data home")
            print(
                json.dumps(
                    {
                        "check": CHECK,
                        "verdict": "fail",
                        "home": str(home),
                        "headline": "no data/ directory",
                    }
                )
            )
            ok = False
            continue
        report = contracts.check_home(home)
        _report(report)
        ok = ok and report.ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
