"""Cloud-runner collection trial: do athletics sites serve a GitHub-hosted runner?

The pilot moves the daily collect from a Mac at home to GitHub Actions, and the
untested risk is that school sites block or challenge cloud IP addresses.  This
script answers that question with the real collector and nothing else: it runs
``collect-board`` (the one collector, unchanged) for a small spread of
programmes on each live platform, into a throwaway data home under a temporary
directory, and reports only how each coverage cell came out.

What it never does:

* write anywhere but its own temporary directory, which it deletes on exit
  (``--keep`` exists for local debugging only);
* print, upload or return collected rows.  The collector's own output is
  captured to a file inside the temporary home and never echoed; the report
  carries states, counts of cells, HTTP status codes and hosts — no fixture,
  roster, statistic or page body;
* touch a real data home.  ``TOUCHLINE_DATA_DIR`` is always the temp home.

StatCrew has no live collector (``live_scraper`` falls back to SideArm for
Harding), so its one host is checked by a single plain GET of a published
custompages box score through the collector's own session, classified with
the probe's platform test.

Exit code is 0 when the report was produced, whatever it says; blocks are the
finding, not a failure.  It is 2 only when the trial itself could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.config import load_schools
from src.sidearm_live import build_session, programme_slug

# One collect-board call per group: a conference-season of one gender, a few
# programmes on distinct hosts.  Groups run concurrently because no two share
# a host; collect-board's per-host gate still keeps each host at one politely
# spaced request at a time.  Chosen for spread: Division I and II, men and
# women, and every PrestoSports conference shape the config carries.
TRIAL_GROUPS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("prestosports", "SAC", "men", ("tusculum", "coker", "mars-hill", "carson-newman")),
    ("prestosports", "CACC", "women", ("bridgeport", "dominican", "wilmington")),
    ("prestosports", "NEC", "women", ("central-connecticut",)),
    ("wmt", "ACC", "women", ("virginia", "clemson", "stanford", "miami")),
    ("wmt", "SEC", "women", ("lsu", "texas-a-m", "vanderbilt")),
    (
        "sidearm",
        "GAC",
        "men",
        ("harding", "fort-hays-state", "newman", "ouachita-baptist"),
    ),
    ("sidearm", "BIGEAST", "women", ("villanova", "georgetown", "uconn")),
)

# Division III has no stanzas yet (the next dataset), so its sites cannot go
# through collect-board.  They are probed instead with the read-only probe
# (src/probe.py), current season only: landing page, platform, and whether
# each layer's page is served.  The URLs are the schools' own sport pages; a
# 404 here means the URL needs correcting, not that the site blocked us.
D3_PROBES: tuple[tuple[str, str], ...] = (
    ("https://ephsports.williams.edu/sports/msoc", "men"),
    ("https://athletics.amherst.edu/sports/wsoc", "women"),
    ("https://gotuftsjumbos.com/sports/mens-soccer", "men"),
    ("https://hopkinssports.com/sports/womens-soccer", "women"),
    ("https://bearsports.wustl.edu/sports/mens-soccer", "men"),
    ("https://athletics.uchicago.edu/sports/msoc", "men"),
)

PLATFORMS = ("sidearm", "prestosports", "wmt", "statcrew", "d3-probe")
PASS_STATES = {"complete", "empty"}

_STATUS = re.compile(r"\b([1-5]\d\d) (?:Client|Server) Error|\bHTTP (\d{3})\b")


@dataclass
class CellOutcome:
    platform: str
    group: str
    programme: str
    layer: str
    state: str
    cls: str  # ok | no-collector | challenge | http-NNN | timeout | connect | proxy | unproven
    host: str = ""


@dataclass
class GroupRun:
    platform: str
    group: str
    exit_code: int
    seconds: float
    cells: list[CellOutcome] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def classify_reason(state: str, reason: str) -> str:
    """Reduce a coverage cell to a failure class, dropping everything else."""
    if state in PASS_STATES:
        return "ok"
    if state == "no-collector":
        return "no-collector"
    text = reason or ""
    if "no proven schedule to take box-score links from" in text:
        # Box scores follow the schedule; this is the schedule's failure
        # again, not a second request refused.
        return "no-collector"
    if (
        "served a challenge" in text
        or "459 Client Error" in text
        or "cooling down after HTTP" in text
    ):
        return "challenge"
    if "ProxyError" in text or "Unable to connect to proxy" in text:
        return "proxy"
    match = _STATUS.search(text)
    if match:
        return f"http-{match.group(1) or match.group(2)}"
    if re.search(r"timed? ?out|Timeout|budget", text, re.I):
        return "timeout"
    if re.search(
        r"ConnectionError|Max retries|Connection reset|RemoteDisconnected|"
        r"Name or service not known|SSLError|CERTIFICATE",
        text,
    ):
        return "connect"
    return "unproven"


def is_block(cls: str) -> bool:
    """A class that says the site refused us, as opposed to a flaky minute."""
    return cls == "challenge" or cls in {
        "http-401",
        "http-403",
        "http-406",
        "http-202",
        "http-429",
        "http-451",
        "http-459",
    }


def _run_group(
    root: Path,
    season: int,
    platform: str,
    conference: str,
    gender: str,
    programmes: Iterable[str],
    layers: str,
    timeout: float,
) -> GroupRun:
    label = f"{conference} {gender}"
    home = root / f"{conference.lower()}-{gender}"
    home.mkdir(parents=True)
    wanted = list(programmes)
    env = {**os.environ, "TOUCHLINE_DATA_DIR": str(home)}
    log_path = home / "collect.log"
    started = time.monotonic()
    with log_path.open("w") as log:
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.collect_board",
                    "--season",
                    str(season),
                    "--gender",
                    gender,
                    "--conference",
                    conference,
                    "--programmes",
                    ",".join(wanted),
                    "--layers",
                    layers,
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124
    run = GroupRun(platform, label, code, time.monotonic() - started)

    coverage_path = home / "data" / "coverage.json"
    cells: dict = {}
    if coverage_path.exists():
        try:
            cells = json.loads(coverage_path.read_text()).get("cells", {})
        except (OSError, ValueError):
            cells = {}
    seen: set[str] = set()
    for cell in cells.values():
        programme = str(cell.get("programme", ""))
        if programme not in wanted:
            continue
        seen.add(programme)
        state = str(cell.get("state") or "unavailable")
        run.cells.append(
            CellOutcome(
                platform=platform,
                group=label,
                programme=programme,
                layer=str(cell.get("layer", "")),
                state=state,
                cls=classify_reason(state, str(cell.get("reason", ""))),
                host=urlparse(str(cell.get("source_url", ""))).netloc,
            )
        )
    run.missing = [p for p in wanted if p not in seen]
    return run


def _statcrew_check(season: int) -> list[CellOutcome]:
    """One GET per StatCrew stanza host: its first box score of last season."""
    from src.probe import PLATFORM_STATCREW, classify_platform

    outcomes: list[CellOutcome] = []
    hosts_done: set[str] = set()
    session = build_session()
    for school in load_schools():
        if not school.enabled or school.scraper != "statcrew":
            continue
        try:
            url = school.base_url.format(year=season - 1, prefix=school.prefix, num=1)
        except (KeyError, IndexError, ValueError):
            continue
        host = urlparse(url).netloc
        if host in hosts_done:
            continue
        hosts_done.add(host)
        slug = programme_slug(school.name)
        try:
            response = session.get(url, timeout=30)
            status = response.status_code
            if status == 200:
                platform, _ = classify_platform(response.text)
                state, cls = (
                    ("complete", "ok")
                    if platform == PLATFORM_STATCREW
                    else ("unavailable", "unproven")
                )
            else:
                state, cls = "unavailable", f"http-{status}"
        except Exception as exc:  # noqa: BLE001 - every failure is a finding
            state, cls = "unavailable", classify_reason("unavailable", repr(exc))
        outcomes.append(
            CellOutcome(
                "statcrew", "static box score", slug, "matches", state, cls, host
            )
        )
    return outcomes


_PROBE_ERROR = re.compile(r"error \((.*)\)")


def _probe_class(value: str) -> str:
    if value in {"present", "absent"}:
        return "ok"
    detail = _PROBE_ERROR.search(value)
    text = detail.group(1) if detail else value
    status = re.search(r"HTTP (\d{3})", text)
    if status:
        return f"http-{status.group(1)}"
    if "timeout" in text:
        return "timeout"
    if "connection" in text or "request failed" in text:
        return "connect"
    return "unproven"


def _d3_probe(season: int) -> list[CellOutcome]:
    """Probe each Division III sport page for one season, read-only."""
    import requests

    from src.probe import classify_platform, probe_layers

    session = build_session()
    outcomes: list[CellOutcome] = []
    for url, gender in D3_PROBES:
        host = urlparse(url).netloc
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            cls = (
                f"http-{status}"
                if status
                else classify_reason("unavailable", repr(exc))
            )
            outcomes.append(
                CellOutcome(
                    "d3-probe", "D3 probe", host, "landing", "unavailable", cls, host
                )
            )
            continue
        platform, _ = classify_platform(response.text)
        outcomes.append(
            CellOutcome(
                "d3-probe",
                f"D3 probe ({platform})",
                host,
                "landing",
                "complete",
                "ok",
                host,
            )
        )
        try:
            layers = probe_layers(
                session,
                url,
                season,
                platform,
                landing_html=response.text,
                gender=gender,
            )
        except Exception as exc:  # noqa: BLE001
            layers = {"schedule": f"error ({exc.__class__.__name__})"}
        for layer, value in layers.items():
            cls = _probe_class(value)
            outcomes.append(
                CellOutcome(
                    "d3-probe",
                    f"D3 probe ({platform})",
                    host,
                    layer,
                    "complete" if cls == "ok" else "unavailable",
                    cls,
                    host,
                )
            )
    return outcomes


def verdict(cells: list[CellOutcome], runs: list[GroupRun], platform: str) -> str:
    mine = [c for c in cells if c.platform == platform and c.cls != "no-collector"]
    missing = sum(len(r.missing) for r in runs if r.platform == platform)
    if not mine and not missing:
        return "not tested"
    if any(is_block(c.cls) for c in mine):
        blocked = sum(is_block(c.cls) for c in mine)
        return "BLOCKED" if blocked == len(mine) else "PARTLY BLOCKED"
    if all(c.cls == "ok" for c in mine) and not missing:
        return "PASS"
    return "DEGRADED"


def render(
    season: int, runs: list[GroupRun], cells: list[CellOutcome], elapsed: float
) -> tuple[str, dict]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    runner = os.environ.get("RUNNER_NAME", "local")
    lines = [
        f"# Cloud collection trial — {now}",
        "",
        f"Season {season}, runner `{runner}`, {elapsed:.0f}s wall. "
        "States and failure classes only; no collected data is shown or kept.",
        "",
        "| Platform | Verdict | Cells ok | Cells failed | Failure classes |",
        "|---|---|---|---|---|",
    ]
    result: dict = {"at": now, "season": season, "runner": runner, "platforms": {}}
    for platform in PLATFORMS:
        mine = [c for c in cells if c.platform == platform and c.cls != "no-collector"]
        ok = sum(c.cls == "ok" for c in mine)
        failed = Counter(c.cls for c in mine if c.cls != "ok")
        v = verdict(cells, runs, platform)
        classes = ", ".join(f"{k} ×{n}" for k, n in sorted(failed.items())) or "—"
        lines.append(
            f"| {platform} | {v} | {ok} | {sum(failed.values())} | {classes} |"
        )
        result["platforms"][platform] = {
            "verdict": v,
            "ok": ok,
            "failed": dict(failed),
        }
    lines += [
        "",
        "## By group",
        "",
        "| Group | Platform | Exit | Seconds | Layers ok / tried | Not in manifest |",
        "|---|---|---|---|---|---|",
    ]
    for run in runs:
        tried = [c for c in run.cells if c.cls != "no-collector"]
        ok = sum(c.cls == "ok" for c in tried)
        lines.append(
            f"| {run.group} | {run.platform} | {run.exit_code} | {run.seconds:.0f} | "
            f"{ok} / {len(tried)} | {', '.join(run.missing) or '—'} |"
        )
    bad = [c for c in cells if c.cls not in {"ok", "no-collector"}]
    if bad:
        lines += [
            "",
            "## Failed cells",
            "",
            "| Programme | Layer | Platform | Class | Host |",
            "|---|---|---|---|---|",
        ]
        for c in sorted(bad, key=lambda c: (c.platform, c.programme, c.layer)):
            lines.append(
                f"| {c.programme} | {c.layer} | {c.platform} | {c.cls} | {c.host or '—'} |"
            )
    result["groups"] = [
        {
            "group": r.group,
            "platform": r.platform,
            "exit": r.exit_code,
            "seconds": round(r.seconds),
            "missing": r.missing,
        }
        for r in runs
    ]
    result["failed_cells"] = [
        {
            "programme": c.programme,
            "layer": c.layer,
            "platform": c.platform,
            "class": c.cls,
            "host": c.host,
        }
        for c in bad
    ]
    return "\n".join(lines) + "\n", result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--layers", default="schedule,roster,stats,matches")
    parser.add_argument(
        "--group-timeout",
        type=float,
        default=1200.0,
        help="Seconds per collect-board call.",
    )
    parser.add_argument("--summary", help="Append the markdown report to this file.")
    parser.add_argument("--json", help="Write the counts-only result to this file.")
    parser.add_argument(
        "--keep", action="store_true", help="Keep the temp home (local debugging)."
    )
    args = parser.parse_args(argv)

    root = Path(tempfile.mkdtemp(prefix="touchline-cloud-trial-"))
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=len(TRIAL_GROUPS)) as pool:
            futures = [
                pool.submit(
                    _run_group,
                    root,
                    args.season,
                    platform,
                    conference,
                    gender,
                    programmes,
                    args.layers,
                    args.group_timeout,
                )
                for platform, conference, gender, programmes in TRIAL_GROUPS
            ]
            statcrew = _statcrew_check(args.season)
            d3 = _d3_probe(args.season)
            runs = [f.result() for f in futures]
        cells = [c for r in runs for c in r.cells] + statcrew + d3
        report, result = render(args.season, runs, cells, time.monotonic() - started)
    except Exception as exc:  # noqa: BLE001
        print(f"trial could not run: {exc!r}", file=sys.stderr)
        return 2
    finally:
        if args.keep:
            print(f"kept temp home: {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)

    print(report)
    print("TRIAL-RESULT " + json.dumps(result, separators=(",", ":")))
    if args.summary:
        with open(args.summary, "a") as fh:
            fh.write(report)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
