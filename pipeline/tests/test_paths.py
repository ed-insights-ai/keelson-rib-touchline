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
    assert paths.raw_html_dir() == root / "data" / "raw_html"
    assert paths.structured_root() == root / "data" / "structured"
    assert paths.source_urls_path() == root / "data" / "source_urls.csv"
    assert paths.reference_dir() == root / "data" / "reference"
    assert paths.canon_path() == root / "data" / "reference" / "canon.json"
    assert paths.errors_dir() == root / "data" / "errors"


def test_env_change_applies_at_call_time(monkeypatch, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(a))
    assert paths.data_root() == a.resolve()
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(b))
    assert paths.data_root() == b.resolve()


def test_default_database_url_prefers_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@h:5/db")
    assert paths.default_database_url() == "postgresql://x@h:5/db"
    monkeypatch.delenv("DATABASE_URL")
    assert paths.default_database_url() == paths.FALLBACK_DATABASE_URL
    assert "touchline" in paths.FALLBACK_DATABASE_URL


def test_consumers_route_through_seam(monkeypatch, tmp_path):
    """GameFetcher and storage defaults must land inside the configured root."""
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(tmp_path))
    from src.fetcher import GameFetcher

    fetcher = GameFetcher()
    assert fetcher.cache_dir == tmp_path.resolve() / "data" / "raw_html"
    fetcher.close()


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
