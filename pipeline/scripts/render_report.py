"""Render the preseason scouting briefing from the digest + a narrative file.

The digest supplies every figure; the narrative file (written by the report
workflow's analyst/research nodes, or absent) supplies prose. Offline by
design — collection and research happen upstream.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src import paths
from src.report import render_appendix, render_report

_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
)


def _chrome() -> str | None:
    """Path to a Chrome/Chromium binary for PDF printing, or None."""
    override = os.environ.get("TOUCHLINE_CHROME")
    if override:
        return override
    for cand in _CHROME_CANDIDATES:
        if Path(cand).exists():
            return cand
        found = shutil.which(cand)
        if found:
            return found
    return None


def _to_pdf(chrome: str, html: Path) -> Path:
    pdf = html.with_suffix(".pdf")
    subprocess.run(
        [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf}",
            html.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return pdf


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the preseason scouting briefing HTML."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--gender", choices=["men", "women"], required=True)
    parser.add_argument("--focus", required=True, help="Focus programme slug the report is prepared for.")
    parser.add_argument(
        "--narrative",
        help="Path to a touchline.report-narrative/1 JSON file; default "
        "data/reports/narrative-<season>-<gender>.json when present.",
    )
    args = parser.parse_args()

    root = paths.data_root()
    digest_path = root / "data" / "scratch" / f"digest-{args.season}-{args.gender}-{args.focus}.json"
    try:
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
    except OSError:
        print(f"no digest at {digest_path} — run build-digest first", file=sys.stderr)
        return 2

    narrative_path = (
        Path(args.narrative)
        if args.narrative
        else root / "data" / "reports" / f"narrative-{args.season}-{args.gender}-{args.focus}.json"
    )
    narrative: dict = {}
    if narrative_path.exists():
        narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
        print(f"narrative: {narrative_path}")
    else:
        print("narrative: none — rendering the deterministic skeleton with placeholders")

    out = root / "data" / "reports" / f"preseason-{args.season}-{args.gender}-{args.focus}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(digest, narrative), encoding="utf-8")
    print(f"wrote {out}")

    appendix = root / "data" / "reports" / f"preseason-{args.season}-{args.gender}-{args.focus}-appendix.html"
    appendix.write_text(render_appendix(digest), encoding="utf-8")
    print(f"wrote {appendix}")

    for html in (out, appendix):
        html.with_suffix(".pdf").unlink(missing_ok=True)
    chrome = _chrome()
    if chrome is None:
        print("no Chrome/Chromium found — PDF skipped, HTML only", file=sys.stderr)
        return 0
    for html in (out, appendix):
        try:
            print(f"wrote {_to_pdf(chrome, html)}")
        except (subprocess.SubprocessError, OSError) as exc:
            detail = ""
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                detail = f"\n{exc.stderr.decode(errors='replace').strip()}"
            print(f"PDF failed for {html.name}: {exc}{detail}", file=sys.stderr)
            return 3
        # The PDF is the deliverable; the HTML intermediate survives only
        # when PDF generation cannot happen (no Chrome, or a failure above).
        html.unlink()
        print(f"removed intermediate {html.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
