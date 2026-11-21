"""Validate the authored conference-membership reference artifact.

Two modes, no network in either:

* bare, it validates membership.json against schools.toml and reports the
  coverage, as before;
* with ``--standings``, it also reads a captured SideArm ``standings.aspx``
  page and holds its team names against the members the windows resolve
  for one conference-season. That is the reproduction step for a conference
  whose site publishes no per-season records pages (the SAC): the page the
  ``source`` sentence cites, read back offline.

A page whose heading names no season or no gender ("2026 Soccer
Standings") is refused unless ``--assert-season`` or ``--assert-gender``
asserts it; the verdict prints every assertion, and a heading that says
otherwise is refused whatever is asserted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import membership


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-membership", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--standings",
        type=Path,
        help="a captured standings.aspx page to hold against the windows",
    )
    parser.add_argument(
        "--conference", help="conference code the page belongs to (with --standings)"
    )
    parser.add_argument(
        "--season", type=int, help="season the page shows (with --standings)"
    )
    parser.add_argument("--gender", default="men", help="men (default) or women")
    parser.add_argument(
        "--assert-season",
        action="store_true",
        help="assert the page is --season's when its heading names no season",
    )
    parser.add_argument(
        "--assert-gender",
        action="store_true",
        help="assert the page is --gender's when its heading names no gender",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate membership.json and report its coverage."""
    args = _parser().parse_args(argv)
    if args.standings is not None and (args.conference is None or args.season is None):
        print(
            "check-membership failed: --standings needs --conference and --season",
            file=sys.stderr,
        )
        return 2

    try:
        document = membership.load_membership()
    except (OSError, ValueError) as error:
        print(f"check-membership failed: {error}", file=sys.stderr)
        return 1

    errors = membership.validate(document)
    if errors:
        for error in errors:
            print(f"check-membership failed: {error}", file=sys.stderr)
        return 1

    window_count = sum(
        len(windows)
        for genders in document["memberships"].values()
        for windows in genders.values()
    )
    seasons = document.get("seasons", {})
    print(
        f"membership valid: "
        f"{len(membership.covered_programmes(document))} programmes, "
        f"{window_count} windows; "
        f"seasons {seasons['from']}-{seasons['to']}; "
        f"conferences {sorted(document.get('conferences', []))}"
    )
    if args.standings is None:
        return 0
    return _check_standings(
        args.standings,
        args.conference,
        args.gender,
        args.season,
        document,
        assert_season=args.assert_season,
        assert_gender=args.assert_gender,
    )


def _check_standings(
    path: Path,
    conference: str,
    gender: str,
    season: int,
    document: dict,
    *,
    assert_season: bool = False,
    assert_gender: bool = False,
) -> int:
    try:
        html = path.read_text(encoding="utf-8")
        verdict = membership.verify_standings(
            html,
            conference,
            gender,
            season,
            document=document,
            assert_season=assert_season,
            assert_gender=assert_gender,
        )
    except (OSError, ValueError) as error:
        print(f"check-membership failed: {error}", file=sys.stderr)
        return 1

    where = verdict.url or "no standings archive declared for this season"
    print(f"standings {conference} {gender} {season}: {where}")
    asserted = {"season": season, "gender": gender}
    for label in verdict.asserted:
        print(
            f"  {label} asserted, not read: {asserted[label]} (the page's heading "
            f"{verdict.page.heading!r} names no {label})"
        )
    print(f"  page lists {len(verdict.page.names)} teams:")
    for name, slug in verdict.slugs.items():
        division = verdict.page.divisions.get(name)
        print(f"    {name} -> {slug}" + (f" ({division})" if division else ""))
    print(f"  windows resolve {len(verdict.expected)} members")
    if verdict.agrees:
        print("  agreement: every name on the page is a member and nobody is missing")
        if verdict.page.divisions or verdict.divisions:
            print("  divisions: every member is printed under its window's division")
        return 0
    for slug in sorted(verdict.missing):
        print(f"  missing from page: {slug}", file=sys.stderr)
    for slug in sorted(verdict.strangers):
        print(f"  on page, no window: {slug}", file=sys.stderr)
    for slug, (printed, window) in verdict.division_mismatches.items():
        print(
            f"  division differs: {slug} is printed under {printed!r}, "
            f"its window says {window!r}",
            file=sys.stderr,
        )
    print(
        f"check-membership failed: {conference} {gender} {season} does not "
        "reproduce from the standings page",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
