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
from bs4 import BeautifulSoup

from src.probe import (
    ProbeReport,
    classify_platform,
    draft_stanza,
    probe_layers,
    served_seasons,
)
from src.sidearm_live import build_session


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


def _school_identity(url: str, html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title is not None else ""
    candidate = title.rsplit(" - ", 1)[-1].strip() if title else ""
    candidate = re.sub(r"\s+Athletics(?:\s+Site)?$", "", candidate, flags=re.I)
    if not candidate or re.search(r"\b(schedule|roster|soccer)\b", candidate, re.I):
        hostname = (urlparse(url).hostname or "school").removeprefix("www.")
        candidate = hostname.split(".", 1)[0].replace("-", " ").title()
    words = re.findall(r"[A-Za-z0-9]+", candidate)
    abbreviation = "".join(word[0] for word in words).upper() or "TBD"
    return candidate, abbreviation


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
    parser.add_argument("--conference", required=True, help="Conference for draft stanzas.")
    parser.add_argument(
        "--seasons",
        type=_season_range,
        default=list(range(datetime.now().year, 2015, -1)),
        help="Candidate season or inclusive range (default: current year through 2016).",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    client = session or build_session()
    reports: list[ProbeReport] = []
    had_error = False
    for raw_url in args.url:
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
        name, abbreviation = _school_identity(url, response.text)
        stanza = draft_stanza(
            name=name,
            abbreviation=abbreviation,
            conference=args.conference,
            base_url=url,
            gender=gender,
            platform=platform,
            seasons=sorted(seasons),
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
