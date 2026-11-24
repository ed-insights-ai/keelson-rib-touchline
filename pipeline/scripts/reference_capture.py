"""Read the pages onboarding needs from sites that serve only our fixed address.

Conference standings and school schedules on some sites refuse GitHub-hosted
runners and serve the AWS runner. Onboarding a conference needs what those
pages print (who is listed in a season's standings, which games a school's
schedule marks as conference games), so this reads a list of pages through
the collector's own politeness (one request in flight per host, backfill
spacing, robots.txt, a host stopped on its first refusal, the collector's
user agent) and prints what each page says as JSON lines in the job log. It
writes nothing and keeps no page.

    uv run reference-capture reference/capture.txt

Each list line is ``label url``; blank lines and ``#`` lines are skipped.
Exit 0 when every page was read or recorded as refused, 2 when the list could
not be read.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.fetch_pool import GatedSession, HostGate, PacingPolicy
from src.sidearm_live import build_session

WORKERS = 8
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _text(fragment: str) -> str:
    return _SPACE.sub(" ", html_lib.unescape(_TAG.sub(" ", fragment))).strip()


def standings_rows(page: str) -> list[list[str]]:
    """Every table's rows, each row its cells' text joined by " | ", table by
    table under the table's caption. A PrestoSports schedule is a table too,
    so its rows (date, opponent, the conference mark, result) read the same."""
    tables = []
    for table in re.findall(r"<table\b.*?</table>", page, re.S | re.I):
        caption = re.search(r"<caption\b[^>]*>(.*?)</caption>", table, re.S | re.I)
        rows = [caption and _text(caption.group(1)) or ""]
        for row in re.findall(r"<tr\b.*?</tr>", table, re.S | re.I):
            cells = [
                _text(cell)
                for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S | re.I)
            ]
            if any(cells):
                rows.append(" | ".join(cells))
        tables.append(rows)
    return tables


def schedule_games(page: str) -> list[dict[str, object]]:
    """A SideArm schedule's games: opponent, the conference a game is marked
    with (the image alt the page prints in its conference column), and
    whether it is a tournament game."""
    games = []
    blocks = re.findall(
        r'<li[^>]*class="[^"]*sidearm-schedule-game[ "].*?</li>\s*(?=<li|</ul)',
        page,
        re.S,
    )
    for block in blocks:
        opening = re.match(r"<li[^>]*>", block)
        name = re.search(r'opponent-name">(.*?)</div>', block, re.S)
        conference = re.search(
            r'sidearm-schedule-game-conference[^"]*"[^>]*>(.*?)</div>', block, re.S
        )
        mark = None
        if conference:
            alt = re.search(r'alt="([^"]*)"', conference.group(1))
            mark = (alt.group(1) if alt else _text(conference.group(1))) or None
        games.append(
            {
                "opponent": _text(name.group(1)) if name else "",
                "conference": mark,
                "tournament": bool(opening and "tourney" in opening.group(0)),
            }
        )
    return games


def title(page: str) -> str:
    found = re.search(r"<title\b[^>]*>(.*?)</title>", page, re.S | re.I)
    return _text(found.group(1)) if found else ""


def platform(page: str) -> str:
    """Which site platform served the page, from its own markup."""
    if "sidearm" in page.lower():
        return "sidearm"
    if "prestosports" in page.lower() or "event-row" in page:
        return "prestosports"
    return "other"


def read_one(session: requests.Session, label: str, url: str) -> dict[str, object]:
    """What the page says, kept short enough to read in a job log: a
    standings page's rows; a schedule's game count and its conference-marked
    games (opponent and mark), or for a table schedule its rows' count."""
    record: dict[str, object] = {"label": label, "url": url}
    try:
        response = session.get(url, timeout=30)
    except requests.RequestException as exc:
        record["error"] = str(exc)[:200]
        return record
    record["status"] = response.status_code
    if response.url != url:
        record["final"] = response.url
    if response.status_code != 200:
        return record
    page = response.text
    record["title"] = title(page)[:120]
    record["platform"] = platform(page)
    if "standings" in urlparse(url).path:
        record["tables"] = [rows for rows in standings_rows(page) if len(rows) > 2]
        return record
    games = schedule_games(page)
    if games:
        record["games"] = len(games)
        record["marked"] = [
            [game["opponent"], game["conference"]]
            for game in games
            if game["conference"] and not game["tournament"]
        ]
    else:
        record["rows"] = sum(len(rows) - 1 for rows in standings_rows(page))
    return record


def read_list(path: Path) -> list[tuple[str, str]]:
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label, _, url = line.partition(" ")
        if not url.strip().startswith("https://"):
            raise ValueError(f"not a 'label https-url' line: {line!r}")
        pairs.append((label, url.strip()))
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("list", type=Path)
    args = parser.parse_args(argv)
    try:
        pairs = read_list(args.list)
    except (OSError, ValueError) as exc:
        print(f"reference-capture: {exc}", file=sys.stderr)
        return 2
    policy = PacingPolicy.from_env(
        lambda name: {"TOUCHLINE_FETCH_PROFILE": "backfill"}.get(name)
    )
    session = build_session(GatedSession(HostGate(policy=policy)))
    by_host: dict[str, list[tuple[str, str]]] = {}
    for label, url in pairs:
        by_host.setdefault(urlparse(url).netloc, []).append((label, url))

    def host_job(items: list[tuple[str, str]]) -> list[dict[str, object]]:
        return [read_one(session, label, url) for label, url in items]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for records in pool.map(host_job, by_host.values()):
            for record in records:
                print("CAPTURE " + json.dumps(record, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
