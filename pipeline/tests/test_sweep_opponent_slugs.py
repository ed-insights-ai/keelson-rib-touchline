"""The opponent-slug sweep pairs one fixture filed under two slugs, read-only."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.sweep_opponent_slugs import sweep

# The tl-kvn shape: TAMIU's own page names UT Dallas formally and the
# collector minted "of-texas-at-dallas"; UT Dallas's page filed the same
# fixture under "ut-dallas". The Tyler pair is the same defect on the away
# side. The Sep 5 rows are a host meeting two visitors, not twins of one
# fixture, and stay listed as apart; the Sep 12 row is alone.
ROWS = [
    {
        "id": "a",
        "date": "2026-09-19",
        "home": "texas-a-m-international",
        "away": "of-texas-at-dallas",
    },
    {
        "id": "b",
        "date": "2026-09-19",
        "home": "texas-a-m-international",
        "away": "ut-dallas",
    },
    {
        "id": "c",
        "date": "2026-10-03",
        "home": "of-texas-at-tyler",
        "away": "saint-edwards",
    },
    {"id": "d", "date": "2026-10-03", "home": "ut-tyler", "away": "saint-edwards"},
    {"id": "e", "date": "2026-09-05", "home": "saint-edwards", "away": "kutztown"},
    {"id": "f", "date": "2026-09-05", "home": "saint-edwards", "away": "bridgeport"},
    {"id": "g", "date": "2026-09-12", "home": "ut-dallas", "away": "saint-edwards"},
]


def _home(tmp_path: Path, rows: list[dict]) -> Path:
    fixtures = tmp_path / "data" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "2026-men-lsc.json").write_text(json.dumps({"fixtures": rows}))
    return tmp_path


def test_the_sweep_pairs_twins_and_says_what_joins_them(tmp_path: Path) -> None:
    before = {p: p.stat().st_mtime for p in _home(tmp_path, ROWS).rglob("*")}
    out = sweep(tmp_path)
    counts = out["counts"]
    assert counts == {"files": 1, "pairs": 3, "fold": 0, "alias": 2, "apart": 1}
    findings = out["findings"]
    assert any(
        line.startswith("ALIAS 2026-men-lsc 2026-09-19 home=texas-a-m-international:")
        and "of-texas-at-dallas | ut-dallas -> ut-dallas" in line
        for line in findings
    )
    assert any(
        line.startswith("ALIAS 2026-men-lsc 2026-10-03 away=saint-edwards:")
        and "of-texas-at-tyler | ut-tyler -> ut-tyler" in line
        for line in findings
    )
    assert any(
        line.startswith("APART 2026-men-lsc 2026-09-05 home=saint-edwards:")
        for line in findings
    )
    assert out["variants"]["alias"] == [
        "of-texas-at-dallas",
        "of-texas-at-tyler",
        "ut-dallas",
        "ut-tyler",
    ]
    # Read-only: nothing under the data home was touched.
    assert {p: p.stat().st_mtime for p in tmp_path.rglob("*")} == before


def test_a_pair_the_fold_alone_joins_names_the_rule(tmp_path: Path) -> None:
    rows = [
        {"id": "a", "date": "2026-09-19", "home": "harding", "away": "of-tampa"},
        {"id": "b", "date": "2026-09-19", "home": "harding", "away": "tampa"},
        {
            "id": "c",
            "date": "2026-09-26",
            "home": "harding",
            "away": "of-pittsburgh-at-johnstown",
        },
        {
            "id": "d",
            "date": "2026-09-26",
            "home": "harding",
            "away": "pittsburgh-johnstown",
        },
    ]
    out = sweep(_home(tmp_path, rows))
    assert out["counts"]["fold"] == 2 and out["counts"]["pairs"] == 2
    assert any(
        line.endswith("of-tampa | tampa -> of-prefix") for line in out["findings"]
    )
    assert any(
        line.endswith("-> locative-joiner+of-prefix") for line in out["findings"]
    )


def test_a_clean_data_home_reports_no_pairs(tmp_path: Path) -> None:
    out = sweep(_home(tmp_path, ROWS[-1:]))
    assert out["counts"]["pairs"] == 0 and out["findings"] == []
