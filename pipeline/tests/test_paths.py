"""Contract tests for the data-root seam.

Every durable-data path must route through src/paths.py, and setting
TOUCHLINE_DATA_DIR must reroute all of them at call time — this is what lets
the pipeline run from anywhere with cwd or env pointing at the consumer-owned
data repo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import paths


def test_default_data_root_is_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("TOUCHLINE_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.data_root() == tmp_path.resolve()


def test_env_reroutes_every_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    root = tmp_path.resolve()
    assert paths.data_root() == root
    assert paths.reference_dir() == root / "data" / "reference"
    assert paths.membership_path() == root / "data" / "reference" / "membership.json"
    assert paths.errors_dir() == root / "data" / "errors"


def test_packaged_membership_path_ignores_the_data_root(monkeypatch, tmp_path):
    # The packaged copy is the SOURCE OF RECORD and ships with the rib, so it
    # must resolve package-relative — never through TOUCHLINE_DATA_DIR — the
    # same deliberate exception as config/schools.toml.
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    package_root = Path(__file__).resolve().parents[2]
    assert paths.package_root() == package_root
    assert (
        paths.packaged_membership_path()
        == package_root / "data" / "reference" / "membership.json"
    )
    # In this checkout the source of record actually exists.
    assert paths.packaged_membership_path().is_file()


def test_env_change_applies_at_call_time(monkeypatch, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(a))
    assert paths.data_root() == a.resolve()
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(b))
    assert paths.data_root() == b.resolve()


def test_no_hardcoded_data_paths_remain():
    """No source or script may construct data/... paths outside paths.py."""
    package_root = Path(__file__).resolve().parents[1]
    offenders = []
    for folder in ("src", "scripts"):
        for file in (package_root / folder).rglob("*.py"):
            if file.name == "paths.py":
                continue
            text = file.read_text(encoding="utf-8")
            for needle in (
                'Path("data/',
                "'data/raw_html'",
                '"data/raw_html"',
                '"data/structured"',
            ):
                if needle in text:
                    offenders.append(f"{file.relative_to(package_root)}: {needle}")
    assert not offenders, f"hardcoded data paths: {offenders}"


# ── the marker's NCAA level ──────────────────────────────────────────────────


def _mark(root: Path, body: str) -> None:
    (root / paths.MARKER_FILE).write_text(body, encoding="utf-8")


def test_home_level_reads_the_marker(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    assert paths.home_level() is None  # no marker: nothing to check
    _mark(tmp_path, "kind: touchline-data\nversion: 1\nlevel: d1\n")
    assert paths.home_level() == paths.HomeLevel("d1", declared=True)
    _mark(tmp_path, "kind: touchline-data\nversion: 1\n")
    assert paths.home_level() == paths.HomeLevel("d2", declared=False)
    _mark(tmp_path, "kind: touchline-data\nversion: 1\nlevel: D4\n")
    with pytest.raises(paths.MarkerError, match="level: D4"):
        paths.home_level()
    _mark(tmp_path, "kind: something-else\n")
    with pytest.raises(paths.MarkerError, match="kind: something-else"):
        paths.home_level()


def test_an_unreadable_marker_refuses_rather_than_reads_as_absent(
    monkeypatch, tmp_path
):
    import pytest

    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    (tmp_path / paths.MARKER_FILE).mkdir()  # present, but read_text raises
    with pytest.raises(paths.MarkerError, match="could not be read"):
        paths.home_level()


def test_home_levels_are_the_membership_levels():
    from src import membership

    assert paths.HOME_LEVELS == membership.LEVELS


# One set of vectors for every marker reader: this module's ``marker_level``
# and ``home_level``, and src/datahome.ts ``markerLevel``/``readMarker`` with
# bin/resolve-membership.ts home-level (test/datahome.test.ts reads the
# same file).
MARKER_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "marker_levels.json").read_text(
        encoding="utf-8"
    )
)["vectors"]


@pytest.mark.parametrize(
    "vector", MARKER_VECTORS, ids=[vector["name"] for vector in MARKER_VECTORS]
)
def test_the_marker_level_vectors(monkeypatch, tmp_path, vector):
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    (tmp_path / paths.MARKER_FILE).write_bytes(vector["text"].encode("utf-8"))
    expect = vector["expect"]
    if expect == "invalid":
        with pytest.raises(ValueError):
            paths.marker_level(vector["text"])
        with pytest.raises(paths.MarkerError):
            paths.home_level()
    elif expect == "absent":
        assert paths.marker_level(vector["text"]) is None
        assert paths.home_level() == paths.HomeLevel("d2", declared=False)
    else:
        assert paths.marker_level(vector["text"]) == expect
        assert paths.home_level() == paths.HomeLevel(expect, declared=True)


def test_a_commented_d1_marker_refuses_a_d2_collect(monkeypatch, tmp_path, capsys):
    """The reviewer's case: ``level: d1 # Division I`` read as absent made the
    home an assumed d2 one, so collect-board admitted a Division II
    conference into a Division I home."""
    from scripts.collect_board import level_refusal
    from src.membership import conferences_at_level

    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    _mark(tmp_path, "kind: touchline-data\nversion: 1\nlevel: d1 # Division I\n")
    refusal = level_refusal(conferences_at_level("d2")[0])
    assert refusal is not None and "collects d1 (declared in its marker)" in refusal
    _mark(tmp_path, "kind: touchline-data\nversion: 1\nlevel: d4 extra\n")
    refusal = level_refusal(conferences_at_level("d2")[0])
    assert refusal is not None and "level: d4 extra" in refusal
