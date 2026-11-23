"""Compare two data homes record by record: the cloud pipeline's cutover gate.

    uv run check-parity EXPECTED ACTUAL [options]

EXPECTED and ACTUAL are each a data-home directory, or a commit of a
data-home clone written ``PATH@REF`` (read with git, nothing checked out):

    uv run check-parity ~/keelson/d2-soccer@main ~/keelson/d2-soccer@shadow \\
        --record collect-record.json --report parity.md --json parity.json
    uv run check-parity ../samples/d2-soccer /tmp/dry-run/d2-soccer

Every fixture, box score, roster, team's season statistics, coverage cell and
reference entry is a match, a timing difference (a game the later collection
could see and the earlier could not), or a disagreement. See
``src/parity.py`` for the rules.

Options:

    --record FILE      a cloud collect's collect-record.json (repeatable; a
                       later file wins per unit). Units it marks skipped,
                       failed or lost are excluded; units it marks changed or
                       no-change are vouched for at the record's collected_at.
    --lag-days N       how many days before the earlier collection a game may
                       still be settling (default 3).
    --require-complete fail unless every file was compared: nothing unproven,
                       nothing excluded. The cutover gate sets this.
    --compare-inherited
                       compare files and cells that carry the same collection
                       stamp on both sides instead of setting them aside as
                       unproven (two commits of one home, a sample against
                       itself). Same-stamp records are judged as collected at
                       the same moment, so any difference disagrees.
    --report FILE      write the Markdown report here ("-" for stdout, the
                       default when neither --report nor --json is given).
    --json FILE        write the touchline.parity/1 result here.
    --summary FILE     append the Markdown report (e.g. $GITHUB_STEP_SUMMARY).

Last line on stdout is always one JSON verdict line, like check-contracts.
Exit 0 when the homes are at parity, 1 when any record disagrees (or, with
--require-complete, when coverage is incomplete), 2 when the check could not
run: an unreadable home, an unknown schema, a file it has no rule for. A 2 is
an alarm, never mistaken for parity.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src import parity

CHECK = "parity"


def _error(exc: object) -> int:
    print(f"ERROR {exc}", file=sys.stderr)
    print(json.dumps({"check": CHECK, "verdict": "error", "error": str(exc)}))
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="check-parity", description=__doc__.split("\n\n")[0]
    )
    ap.add_argument(
        "expected",
        help="data home (dir or PATH@REF) holding the reference copy, e.g. main",
    )
    ap.add_argument(
        "actual", help="data home (dir or PATH@REF) under test, e.g. shadow"
    )
    ap.add_argument(
        "--record",
        action="append",
        type=Path,
        default=[],
        help="collect-record.json (repeatable)",
    )
    ap.add_argument("--lag-days", type=int, default=parity.DEFAULT_LAG_DAYS)
    ap.add_argument("--require-complete", action="store_true")
    ap.add_argument("--compare-inherited", action="store_true")
    ap.add_argument("--report", help='Markdown report path, "-" for stdout')
    ap.add_argument(
        "--json", dest="json_path", type=Path, help="touchline.parity/1 result path"
    )
    ap.add_argument(
        "--summary", type=Path, help="append the Markdown report to this file"
    )
    args = ap.parse_args(argv)
    if args.lag_days < 0:
        ap.error("--lag-days must be 0 or more")

    trees: list[parity.Tree] = []
    try:
        records = parity.load_records(args.record)
        trees = [parity.open_tree(args.expected), parity.open_tree(args.actual)]
        result = parity.compare(
            trees[0],
            trees[1],
            lag_days=args.lag_days,
            records=records,
            require_complete=args.require_complete,
            compare_inherited=args.compare_inherited,
        )
    except (parity.ParityError, OSError, subprocess.SubprocessError) as exc:
        return _error(exc)
    finally:
        for t in trees:
            t.close()

    report = parity.render_markdown(result)
    doc = result.to_json()
    try:
        if args.report == "-" or (args.report is None and args.json_path is None):
            print(report)
        elif args.report:
            Path(args.report).write_text(report + "\n")
        if args.json_path:
            args.json_path.write_text(json.dumps(doc, indent=2) + "\n")
        if args.summary:
            with args.summary.open("a") as fh:
                fh.write(report + "\n")
    except OSError as exc:
        return _error(f"cannot write output: {exc}")

    print(
        json.dumps(
            {
                "check": CHECK,
                "verdict": doc["verdict"],
                "complete": doc["complete"],
                **doc["totals"],
                "files": doc["files"],
                "errors": len(doc["errors"]),
            }
        )
    )
    return {"pass": 0, "fail": 1, "error": 2}[doc["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
