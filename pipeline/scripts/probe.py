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
    PLATFORM_UNKNOWN,
    ProbeReport,
    classify_platform,
    derive_identity,
    draft_stanza,
    fetch_schedule_page,
    probe_layers,
    survey_seasons,
)
from src.sidearm_live import LiveCollectionError, build_session, http_status


def _season_range(value: str) -> list[int]:
    match = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", value)
    if match is None:
        raise argparse.ArgumentTypeError("use YYYY or YYYY-YYYY")
    first = int(match.group(1))
    second = int(match.group(2) or first)
    high, low = max(first, second), min(first, second)
    return list(range(high, low - 1, -1))


def _landing_url(raw_url: str) -> str:
    """Normalise a sport URL to its landing page.

    PrestoSports links the sport as ``/sports/msoc/index`` and as the bare
    ``/sports/msoc``; both are the same landing page, so the trailing
    ``/index`` is dropped before the platform is judged and the season
    paths are built, and the drafted stanza records the bare form.
    """
    url = raw_url.rstrip("/")
    if url.lower().endswith("/index"):
        url = url[: -len("/index")].rstrip("/")
    return url


def _gender_from_url(url: str) -> str:
    sport_slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].lower()
    if sport_slug.startswith("mens-") or sport_slug == "msoc":
        return "men"
    if sport_slug.startswith("womens-") or sport_slug == "wsoc":
        return "women"
    raise ValueError(
        f"{url}: sport slug must start with 'mens-' or 'womens-' (or be the "
        "PrestoSports 'msoc' or 'wsoc') to derive gender"
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
        url = _landing_url(raw_url)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            print(f"{raw_url}: expected an absolute HTTP(S) URL", file=sys.stderr)
            had_error = True
            continue
        landing_html = ""
        not_seen = ""
        try:
            gender = _gender_from_url(url)
            response = client.get(url, timeout=30)
            response.raise_for_status()
            landing_html = response.text
        except requests.RequestException as exc:
            print(str(exc), file=sys.stderr)
            had_error = True
            status = http_status(exc)
            if status is None:
                continue
            # The site answered: say what it said (bead tl-v1q.6) and probe
            # on, so a 403 never again reads as "unknown, none".
            not_seen = f"HTTP {status}"
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            had_error = True
            continue

        if not_seen:
            platform, evidence = PLATFORM_UNKNOWN, []
        else:
            platform, evidence = classify_platform(landing_html)
        layer_year = max(args.seasons)
        layers = probe_layers(
            client, url, layer_year, platform, landing_html=landing_html
        )
        survey = survey_seasons(client, url, args.seasons, platform)
        seasons = survey.served
        # The schedule page is where a site describes itself ("The official
        # 2026 Men's Soccer schedule for the Truman State University
        # Bulldogs") and where opponents spell the school; read the newest
        # season the site proved, or the landing page alone if none was.
        pages = [landing_html] if landing_html else []
        if seasons:
            try:
                schedule = fetch_schedule_page(client, url, max(seasons), platform)
                pages.append(schedule.html)
            except LiveCollectionError:
                pass
        identity = derive_identity(
            name=args.name[index] if args.name else "", pages=pages, url=url
        )
        # A one-letter guess is refused (bead tl-4an.29): the stanza prints
        # an empty abbreviation and the summary names the host.
        hand_edits = [] if len(identity.abbreviation) > 1 else ["abbreviation"]
        stanza = draft_stanza(
            name=identity.name,
            abbreviation=identity.abbreviation,
            conference=args.conference,
            base_url=url,
            gender=gender,
            platform=platform,
            seasons=sorted(seasons),
            mascot=identity.mascot,
            city=identity.city,
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
                not_seen=not_seen,
                season_errors=survey.errors,
                hand_edits=hand_edits,
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
        summary = _hand_edit_summary(reports)
        if summary:
            print()
            print(summary, end="")
    return 1 if had_error else 0


def _hand_edit_summary(reports: list[ProbeReport]) -> str:
    """List, per field still needing a hand edit, the hosts that need it."""
    hosts_by_field: dict[str, list[str]] = {}
    for report in reports:
        host = urlparse(report.url).netloc
        for field in report.hand_edits:
            hosts_by_field.setdefault(field, []).append(host)
    lines: list[str] = []
    for field, hosts in hosts_by_field.items():
        lines.append(f"hand edits still needed: {field}")
        lines.extend(f"  {host}" for host in hosts)
    return "\n".join(lines) + "\n" if lines else ""


if __name__ == "__main__":
    raise SystemExit(main())
