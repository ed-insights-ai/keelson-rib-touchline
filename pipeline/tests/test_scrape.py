"""Tests for scrape completeness and exit-code signaling."""

from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from scripts import scrape
from src.config import SchoolConfig
from src.errors import DiscoveryError
from src.models import GameURL


class _Progress:
    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def add_task(self, *_args, **_kwargs):
        return 1

    def advance(self, *_args, **_kwargs):
        pass


def _school() -> SchoolConfig:
    return SchoolConfig(
        name="Harding",
        abbreviation="HU",
        conference="GAC",
        prefix="hu",
        base_url="https://example.com/{year}/{prefix}-{num:02d}.htm",
        years=[2025],
        enabled=True,
        ordinal=7,
    )


def _configure_main(monkeypatch, discovery, *, school_args=None):
    output = StringIO()
    console = Console(file=output, color_system=None, force_terminal=False, width=160)
    fetcher = MagicMock()
    save_season = MagicMock()
    merge_all_seasons = MagicMock()

    monkeypatch.setattr(scrape, "console", console)
    monkeypatch.setattr(scrape, "Progress", _Progress)
    monkeypatch.setattr(scrape, "load_schools", lambda _config: [_school()])
    monkeypatch.setattr(scrape, "discover_season_games", discovery)
    monkeypatch.setattr(scrape, "GameFetcher", MagicMock(return_value=fetcher))
    monkeypatch.setattr(scrape, "parse_game", lambda _html, game_id, *_args, **_kwargs: {"game_id": game_id})
    monkeypatch.setattr(scrape, "log_parse_error", MagicMock())
    monkeypatch.setattr(scrape, "save_season", save_season)
    monkeypatch.setattr(scrape, "merge_all_seasons", merge_all_seasons)
    monkeypatch.setattr(scrape, "merge_all_schools", MagicMock())
    monkeypatch.setattr(
        sys,
        "argv",
        ["scrape", "--school", *(school_args or ["HU"]), "--year", "2025"],
    )

    return output, fetcher, save_season, merge_all_seasons


def test_partial_run_exits_one_names_failure_and_saves_completed_games(monkeypatch):
    urls = [
        GameURL(year=2025, game_num=game_num, url=f"https://example.com/{game_num}")
        for game_num in range(1, 4)
    ]
    output, fetcher, save_season, _merge = _configure_main(
        monkeypatch,
        lambda *_args, **_kwargs: urls,
    )

    def fetch(_url, _year, game_num, **_kwargs):
        if game_num == 2:
            raise RuntimeError("HTTP 500")
        return "<html></html>"

    fetcher.fetch.side_effect = fetch

    with pytest.raises(SystemExit) as exc_info:
        scrape.main()

    assert exc_info.value.code == 1
    assert "HU 2025: 1/3 games failed: 7202502" in output.getvalue()
    parsed_games = save_season.call_args.args[0]
    assert [game["game_id"] for game in parsed_games] == [7202501, 7202503]


def test_rejected_discovery_exits_one_and_names_season(monkeypatch):
    def reject(*_args, **_kwargs):
        raise DiscoveryError("wrong season")

    output, _fetcher, save_season, merge_all_seasons = _configure_main(
        monkeypatch,
        reject,
    )

    with pytest.raises(SystemExit) as exc_info:
        scrape.main()

    assert exc_info.value.code == 1
    assert "HU 2025: discovery rejected — wrong season" in output.getvalue()
    save_season.assert_not_called()
    merge_all_seasons.assert_called_once()


def test_genuine_empty_season_exits_zero(monkeypatch):
    output, _fetcher, save_season, merge_all_seasons = _configure_main(
        monkeypatch,
        lambda *_args, **_kwargs: [],
    )

    assert scrape.main() is None
    assert "No games found for 2025" in output.getvalue()
    save_season.assert_not_called()
    merge_all_seasons.assert_called_once()


def test_complete_run_exits_zero_and_reports_saved_games(monkeypatch):
    urls = [GameURL(year=2025, game_num=1, url="https://example.com/1")]
    output, fetcher, save_season, _merge = _configure_main(
        monkeypatch,
        lambda *_args, **_kwargs: urls,
    )
    fetcher.fetch.return_value = "<html></html>"

    assert scrape.main() is None
    assert "Saved 1 games for 2025" in output.getvalue()
    save_season.assert_called_once()


def test_unknown_school_exits_two(monkeypatch):
    output, _fetcher, _save_season, _merge = _configure_main(
        monkeypatch,
        lambda *_args, **_kwargs: [],
        school_args=["XX"],
    )

    with pytest.raises(SystemExit) as exc_info:
        scrape.main()

    assert exc_info.value.code == 2
    assert "No enabled school found with abbreviation 'XX'" in output.getvalue()
