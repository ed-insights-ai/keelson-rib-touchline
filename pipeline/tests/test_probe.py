"""Tests for read-only athletics-site discovery."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock

from scripts import probe as probe_cli
from src.probe import (
    LAYER_PRESENT,
    PLATFORM_SIDEARM,
    PLATFORM_SIDEARM_LEGACY,
    PLATFORM_STATCREW,
    PLATFORM_UNKNOWN,
    ProbeReport,
    classify_platform,
    draft_stanza,
    probe_layers,
    served_seasons,
)

FIXTURES = Path("tests/fixtures")


def _response(url: str, html: str) -> MagicMock:
    response = MagicMock()
    response.url = url
    response.text = html
    return response


def _schedule_html(year: int) -> str:
    return f"""
    <html>
      <head><title>{year} Men's Soccer Schedule - Example</title></head>
      <body>
        <li class="sidearm-schedule-game">
          <a href="/sports/mens-soccer/stats/{year}/example/boxscore/42">
            Box Score
          </a>
        </li>
      </body>
    </html>
    """


def test_classify_platform_recognizes_supported_and_advisory_shapes() -> None:
    sidearm = (FIXTURES / "sidearm_boxscore_6126.html").read_text()
    statcrew = (FIXTURES / "statcrew_harding_home.html").read_text()
    legacy = """
    <html>
      <head><meta name="generator" content="SIDEARM Sports"></head>
      <body><div id="app">Loading schedule...</div></body>
    </html>
    """

    assert "data-bind" in sidearm
    assert classify_platform(sidearm)[0] == PLATFORM_SIDEARM
    assert classify_platform(statcrew)[0] == PLATFORM_STATCREW
    assert classify_platform(legacy)[0] == PLATFORM_SIDEARM_LEGACY
    assert classify_platform("<html><p>Plain site</p></html>") == (
        PLATFORM_UNKNOWN,
        [],
    )


def test_probe_layers_detects_each_published_layer() -> None:
    base_url = "https://example.test/sports/mens-soccer"
    year = 2026
    roster_html = f"""
    <title>{year} Men's Soccer Roster - Example</title>
    <li class="sidearm-roster-player" data-player-id="9"
        data-player-url="/sports/mens-soccer/roster/alex-example/9">
      <span class="sidearm-roster-player-name"><a>Alex Example</a></span>
    </li>
    """
    stats_html = f"""
    <title>{year} Men's Soccer Cumulative Statistics - Example</title>
    <table>
      <caption>Individual Overall Offensive Statistics</caption>
      <tr><td>5</td><td><a data-player-id="9">Example, Alex</a></td></tr>
    </table>
    """
    session = MagicMock()
    session.get.side_effect = [
        _response(f"{base_url}/schedule/{year}", _schedule_html(year)),
        _response(f"{base_url}/roster/{year}", roster_html),
        _response(f"{base_url}/stats/{year}", stats_html),
    ]

    assert probe_layers(session, base_url, year) == {
        "schedule": LAYER_PRESENT,
        "roster": LAYER_PRESENT,
        "stats": LAYER_PRESENT,
        "matches": LAYER_PRESENT,
    }


def test_served_seasons_keeps_only_proven_schedule_years() -> None:
    base_url = "https://example.test/sports/mens-soccer"
    session = MagicMock()
    session.get.side_effect = [
        _response(f"{base_url}/schedule/2026", _schedule_html(2026)),
        _response(f"{base_url}/schedule/2026", _schedule_html(2026)),
    ]

    assert served_seasons(session, base_url, [2026, 2025]) == [2026]


def test_draft_stanza_is_parseable_and_disabled() -> None:
    stanza = draft_stanza(
        name="Example University",
        abbreviation="EX",
        conference="LSC",
        base_url="https://example.test/sports/mens-soccer/",
        gender="men",
        platform=PLATFORM_SIDEARM,
        seasons=[2024, 2025, 2026],
    )

    parsed = tomllib.loads(stanza)["schools"][0]
    assert parsed["scraper"] == PLATFORM_SIDEARM
    assert parsed["years"] == [2024, 2025, 2026]
    assert parsed["enabled"] is False
    assert "live_scraper" not in parsed


def test_probe_report_renders_verdict_layers_seasons_and_stanza() -> None:
    stanza = draft_stanza(
        name="Example University",
        abbreviation="EX",
        conference="LSC",
        base_url="https://example.test/sports/mens-soccer",
        gender="men",
        platform=PLATFORM_SIDEARM,
        seasons=[2026],
    )
    report = ProbeReport(
        url="https://example.test/sports/mens-soccer",
        platform=PLATFORM_SIDEARM,
        evidence=["SideArm events component"],
        layers={
            "schedule": "present",
            "roster": "present",
            "stats": "absent",
            "matches": "present",
        },
        seasons=[2026],
        stanza=stanza,
    )

    rendered = report.render()
    assert "Platform: sidearm" in rendered
    assert "stats: absent" in rendered
    assert "Served seasons: 2026" in rendered
    assert "[[schools]]" in rendered


def test_cli_prints_report_without_writing_to_data_home(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    base_url = "https://example.test/sports/mens-soccer"
    year = 2026
    session = MagicMock()
    session.get.side_effect = [
        _response(base_url, _schedule_html(year)),
        _response(f"{base_url}/schedule/{year}", _schedule_html(year)),
        _response(
            f"{base_url}/roster/{year}",
            f"<title>{year} Men's Soccer Roster - Example</title>",
        ),
        _response(
            f"{base_url}/stats/{year}",
            f"<title>{year} Men's Soccer Cumulative Statistics - Example</title>",
        ),
        _response(f"{base_url}/schedule/{year}", _schedule_html(year)),
    ]
    data_root = tmp_path / "touchline-data"
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(data_root))

    exit_code = probe_cli.main(
        [
            "--url",
            base_url,
            "--conference",
            "LSC",
            "--seasons",
            str(year),
        ],
        session=session,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Platform: sidearm" in output
    assert "[[schools]]" in output
    assert not data_root.exists()
