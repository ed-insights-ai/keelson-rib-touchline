"""The site bundle: every season's JSON of a home, no raw pages, with a manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cut_bundle

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "d9-soccer"
    (home / "data" / "fixtures").mkdir(parents=True)
    (home / "data" / "matches").mkdir()
    (home / "data" / "reference").mkdir()
    (home / "data" / "raw").mkdir()
    (home / "touchline-data.yaml").write_text(
        "kind: touchline-data\nversion: 1\nlevel: d2\n"
    )
    for name in ("2025-men-aaa.json", "2026-men-aaa.json", "2026-women-bbb.json"):
        (home / "data" / "fixtures" / name).write_text('{"fixtures": []}\n')
    (home / "data" / "matches" / "2026-men-aaa.json").write_text("{}\n")
    (home / "data" / "coverage.json").write_text('{"cells": {}}\n')
    (home / "data" / "reference" / "programmes.json").write_text("{}\n")
    (home / "data" / "raw" / "page.html").write_text("<html></html>")
    return home


def test_cuts_every_season_and_no_raw_pages(tmp_path: Path) -> None:
    home = _home(tmp_path)
    out = tmp_path / "bundle"
    m = cut_bundle.cut(home, out, "abc1234")
    paths = {f["path"] for f in m["files"]}
    assert paths == {
        "touchline-data.yaml",
        "data/fixtures/2025-men-aaa.json",
        "data/fixtures/2026-men-aaa.json",
        "data/fixtures/2026-women-bbb.json",
        "data/matches/2026-men-aaa.json",
        "data/coverage.json",
        "data/reference/programmes.json",
    }
    assert m["season"] == 2026 and m["level"] == "d2" and m["sample"] is False
    assert m["source"] == {"home": "d9-soccer", "sha": "abc1234"}
    on_disk = json.loads((out / "data" / "bundle.json").read_text())
    assert on_disk["files"] == m["files"]
    assert not (out / "data" / "raw").exists()


def test_refuses_a_non_empty_out(tmp_path: Path) -> None:
    home = _home(tmp_path)
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "x").write_text("")
    with pytest.raises(SystemExit):
        cut_bundle.cut(home, out, "abc1234")


def test_sample_home_keeps_its_sample_manifest(tmp_path: Path) -> None:
    m = cut_bundle.cut(SAMPLES / "d2-soccer", tmp_path / "b", "sample")
    assert m["sample"] is True
    assert (tmp_path / "b" / "data" / "sample.json").is_file()
    want = {
        f["path"]: f["sha256"]
        for f in json.loads(
            (SAMPLES / "d2-soccer" / "data" / "sample.json").read_text()
        )["files"]
    }
    got = {f["path"]: f["sha256"] for f in m["files"]}
    assert all(got[p] == h for p, h in want.items())
