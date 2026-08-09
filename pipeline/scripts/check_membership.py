"""Validate the authored conference-membership reference artifact."""

from __future__ import annotations

import sys

from src import membership


def main() -> int:
    """Validate membership.json and report its coverage."""
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
    print(
        f"membership valid: "
        f"{len(membership.covered_programmes(document))} programmes, "
        f"{window_count} windows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
