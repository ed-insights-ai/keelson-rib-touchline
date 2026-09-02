"""CLI for read-only athletics-site discovery."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import datetime
from urllib.parse import urlparse

import requests

from src.probe import (
    ProbeReport,
    classify_platform,
    derive_identity,
    draft_stanza,
    probe_layers,
    served_seasons,
)
from src.sidearm_live import (
    LAYER_SCHEDULE,
    LiveCollectionError,
    build_session,
    fetch_published_page,
)


def _season_range(value: str) -> list[int]:
    match = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", value)
    if match is None:
        raise argparse.ArgumentTypeError("use YYYY or YYYY-YYYY")
    first = int(match.group(1))
    second = int(match.group(2) or first)
    high, low = max(first, second), min(first, second)
    return list(range(high, low - 1, -1))


def _gender_from_url(url: str) -> str:
    sport_slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].lower()
    if sport_slug.startswith("mens-"):
        return "men"
    if sport_slug.startswith("womens-"):
        return "women"
    raise ValueError(
        f"{url}: sport slug must start with 'mens-' or 'womens-' to derive gender"
    )


def main(
    argv: list[str] | None = None, *, session: requests.Session | None = None
) -> int:
    """Probe one or more athletics sport URLs without writing local data."""
    parser = argparse.ArgumentParser(
        description="Identify athletics-site collectors and published data layers."
    )
    parser.add_argument(
        "--url",
        action="append",
        required=True,
        help="Sport base URL, repeatable (for example, .../sports/mens-soccer).",
    )
    parser.add_argument(
        "--conference", required=True, help="Conference for draft stanzas."
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help=(
            "Slug-minting school name for the matching --url, in order, repeatable "
            "(default: the site's own published name)."
        ),
    )
    parser.add_argument(
        "--seasons",
        type=_season_range,
        default=list(range(datetime.now().year, 2015, -1)),
        help="Candidate season or inclusive range (default: current year through 2016).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    args = parser.parse_args(argv)
    if args.name and len(args.name) != len(args.url):
        parser.error(
            f"--name given {len(args.name)} times for {len(args.url)} --url values; "
            "pass one per URL, in order, or none"
        )

    client = session or build_session()
    reports: list[ProbeReport] = []
    had_error = False
    for index, raw_url in enumerate(args.url):
        url = raw_url.rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            print(f"{raw_url}: expected an absolute HTTP(S) URL", file=sys.stderr)
            had_error = True
            continue
        try:
            gender = _gender_from_url(url)
            response = client.get(url, timeout=30)
            response.raise_for_status()
        except (ValueError, requests.RequestException) as exc:
            print(str(exc), file=sys.stderr)
            had_error = True
            continue

        platform, evidence = classify_platform(response.text)
        layer_year = max(args.seasons)
        layers = probe_layers(client, url, layer_year)
        seasons = served_seasons(client, url, args.seasons)
        # The schedule page is where a site describes itself ("The official
        # 2026 Men's Soccer schedule for the Truman State University
        # Bulldogs") and where opponents spell the school; read the newest
        # season the site proved, or the landing page alone if none was.
        pages = [response.text]
        if seasons:
            try:
                schedule = fetch_published_page(
                    client, url, max(seasons), LAYER_SCHEDULE
                )
                pages.append(schedule.html)
            except LiveCollectionError:
                pass
        identity = derive_identity(
            name=args.name[index] if args.name else "", pages=pages, url=url
        )
        stanza = draft_stanza(
            name=identity.name,
            abbreviation=identity.abbreviation,
            conference=args.conference,
            base_url=url,
            gender=gender,
            platform=platform,
            seasons=sorted(seasons),
            mascot=identity.mascot,
            aliases=identity.aliases,
        )
        reports.append(
            ProbeReport(
                url=url,
                platform=platform,
                evidence=evidence,
                layers=layers,
                seasons=seasons,
                stanza=stanza,
            )
        )

    if args.json:
        payloads = [asdict(report) for report in reports]
        payload: object = payloads[0] if len(payloads) == 1 else payloads
        print(json.dumps(payload, indent=2))
    else:
        for index, report in enumerate(reports):
            if index:
                print()
            print(report.render(), end="")
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
