"""Contract tests for the data-root seam.

Every durable-data path must route through src/paths.py, and setting
TOUCHLINE_DATA_DIR must reroute all of them at call time — this is what lets
the pipeline run from anywhere with cwd or env pointing at the consumer-owned
data repo.
"""

from __future__ import annotations

from pathlib import Path

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
            for needle in ('Path("data/', "'data/raw_html'", '"data/raw_html"', '"data/structured"'):
                if needle in text:
                    offenders.append(f"{file.relative_to(package_root)}: {needle}")
    assert not offenders, f"hardcoded data paths: {offenders}"
