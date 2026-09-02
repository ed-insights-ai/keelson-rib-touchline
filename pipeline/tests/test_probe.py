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
    derive_identity,
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


def _site_html(
    *,
    site_name: str,
    described: str,
    short_token: str,
    og_url: str,
    opponents: tuple[str, ...] = (),
) -> str:
    rows = "".join(
        f'<li class="sidearm-schedule-game">'
        f'<div class="sidearm-schedule-game-opponent-name">{name}</div></li>'
        for name in opponents
    )
    return f"""
    <html>
      <head>
        <title>2026 Men's Soccer Schedule - {site_name} Athletics</title>
        <meta property="og:site_name" content="{site_name} Athletics">
        <meta property="og:url" content="{og_url}">
        <meta name="description"
              content="The official 2026 Men's Soccer schedule for the {described}">
      </head>
      <body>
        <script>var obj = {{"type":"theme","site_name":"{short_token}"}};</script>
        <ul>{rows}</ul>
      </body>
    </html>
    """


def test_derive_identity_reads_mascot_and_published_name_off_the_site() -> None:
    html = _site_html(
        site_name="Truman State University",
        described="Truman State University Bulldogs",
        short_token="truman",
        og_url="https://trumanbulldogs.com/sports/mens-soccer/schedule/2026",
        opponents=("Quincy", "Truman State vs. Rockhurst", "Lewis (Ill.)"),
    )

    identity = derive_identity(
        name="Truman", pages=[html], url="https://trumanbulldogs.com/sports/mens-soccer"
    )

    assert identity.name == "Truman"
    assert identity.mascot == "Bulldogs"
    # The site's short token is only the first word of a long name, so the
    # abbreviation falls back to initials.  The published long name becomes
    # an alias; "Truman State" does not, because the collector's identity key
    # already folds it onto the same spelling.
    assert identity.abbreviation == "TS"
    assert identity.aliases == ["Truman State University"]


def test_derive_identity_keeps_the_site_short_form_and_multiword_mascot() -> None:
    uis = _site_html(
        site_name="UIS",
        described="UIS Prairie Stars",
        short_token="uis",
        og_url="https://uisprairiestars.com/sports/mens-soccer/schedule/2026",
    )
    uindy = _site_html(
        site_name="UIndy",
        described="University of Indianapolis Greyhounds",
        short_token="uindy",
        og_url="https://athletics.uindy.edu/sports/mens-soccer/schedule/2026",
    )
    umsl = _site_html(
        site_name="University of Missouri - St. Louis",
        described="University of Missouri - St. Louis Tritons",
        short_token="umsl",
        og_url="https://umsltritons.com/sports/mens-soccer/schedule/2026",
    )

    springfield = derive_identity(name="Illinois Springfield", pages=[uis])
    indianapolis = derive_identity(name="Indianapolis", pages=[uindy])
    st_louis = derive_identity(name="UMSL", pages=[umsl])

    assert (springfield.abbreviation, springfield.mascot) == ("UIS", "Prairie Stars")
    assert (indianapolis.abbreviation, indianapolis.mascot) == ("UIndy", "Greyhounds")
    assert indianapolis.aliases == ["University of Indianapolis"]
    assert (st_louis.abbreviation, st_louis.mascot) == ("UMSL", "Tritons")
    assert st_louis.aliases == ["University of Missouri - St. Louis"]


def test_derive_identity_falls_back_to_the_published_name_without_name() -> None:
    html = _site_html(
        site_name="Example University",
        described="Example University Owls",
        short_token="example",
        og_url="https://example.test/sports/mens-soccer/schedule/2026",
    )

    identity = derive_identity(name="", pages=[html])

    assert identity.name == "Example University"
    assert identity.abbreviation == "E"
    assert identity.mascot == "Owls"
    assert identity.aliases == []


def test_draft_stanza_uses_the_house_layout_with_mascot_and_aliases() -> None:
    stanza = draft_stanza(
        name="Truman",
        abbreviation="TRU",
        conference="GLVC",
        base_url="https://trumanbulldogs.com/sports/mens-soccer",
        gender="men",
        platform=PLATFORM_SIDEARM,
        seasons=[2025, 2026],
        mascot="Bulldogs",
        accessed="2026-09-02",
        aliases=["Truman State University", "Truman State"],
    )

    assert stanza == (
        "[[schools]]\n"
        'name         = "Truman"\n'
        'abbreviation = "TRU"\n'
        'conference   = "GLVC"\n'
        'mascot       = "Bulldogs"\n'
        'aliases      = ["Truman State University", "Truman State"]\n'
        'gender       = "men"\n'
        'base_url     = "https://trumanbulldogs.com/sports/mens-soccer"\n'
        "years        = [2025, 2026]\n"
        'scraper      = "sidearm"\n'
        'data_status  = "unverified"\n'
        "enabled      = false\n"
        '# city: the schedule page prints no home town; fill by hand as "Town, St."\n'
        "# city_source: cite where the town was read (default: the schedule page)\n"
        'identity_accessed = "2026-09-02"\n'
    )
    parsed = tomllib.loads(stanza)["schools"][0]
    assert parsed["mascot"] == "Bulldogs"
    assert parsed["aliases"] == ["Truman State University", "Truman State"]


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
    assert "mascot" not in parsed
    assert "# mascot:" in stanza


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
        _response(
            f"{base_url}/schedule/{year}",
            _site_html(
                site_name="Example University",
                described="Example University Owls",
                short_token="example",
                og_url=f"{base_url}/schedule/{year}",
            ),
        ),
    ]
    data_root = tmp_path / "touchline-data"
    monkeypatch.setenv("TOUCHLINE_DATA_DIR", str(data_root))

    exit_code = probe_cli.main(
        [
            "--url",
            base_url,
            "--name",
            "Example",
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
    assert 'name         = "Example"' in output
    assert 'mascot       = "Owls"' in output
    # "Example University" keys identically to "Example", so no alias line.
    assert "aliases" not in output
    assert not data_root.exists()


def test_cli_refuses_a_name_count_that_does_not_match_the_urls(capsys) -> None:
    try:
        probe_cli.main(
            [
                "--url",
                "https://a.test/sports/mens-soccer",
                "--url",
                "https://b.test/sports/mens-soccer",
                "--name",
                "Only One",
                "--conference",
                "LSC",
            ],
            session=MagicMock(),
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected argparse to exit")
    assert "--name given 1 times for 2 --url values" in capsys.readouterr().err


HOME_ROWS = """
<ul>
  <li class="sidearm-schedule-game sidearm-schedule-game-home">
    <div class="sidearm-schedule-game-location"><span>Alamosa, CO</span><span>ASU Soccer Field</span></div>
  </li>
  <li class="sidearm-schedule-game">
    <div class="sidearm-schedule-game-location"><span>Denver, CO</span></div>
  </li>
  <li class="sidearm-schedule-game sidearm-schedule-game-home">
    <div class="sidearm-schedule-game-location"><span>Alamosa, Colo.</span></div>
  </li>
  <li class="sidearm-schedule-game sidearm-schedule-game-home">
    <div class="sidearm-schedule-game-location"><span>TBA</span></div>
  </li>
</ul>
"""


def test_home_town_is_the_majority_of_marked_home_rows_in_ap_style() -> None:
    from src.probe import _home_town

    assert _home_town(HOME_ROWS) == "Alamosa, Colo."


def test_home_town_falls_back_to_every_row_and_needs_a_majority() -> None:
    from src.probe import _home_town

    unmarked = HOME_ROWS.replace(" sidearm-schedule-game-home", "")
    assert _home_town(unmarked) == "Alamosa, Colo."
    split = unmarked.replace("Alamosa, Colo.", "Pueblo, Colo.")
    assert _home_town(split) == ""
    assert _home_town("<ul></ul>") == ""


def test_draft_stanza_carries_the_town_and_the_accessed_date() -> None:
    stanza = draft_stanza(
        name="Adams State",
        abbreviation="ASU",
        conference="RMAC",
        base_url="https://asugrizzlies.com/sports/mens-soccer",
        gender="men",
        platform="sidearm",
        seasons=[2026],
        mascot="Grizzlies",
        city="Alamosa, Colo.",
        accessed="2026-09-02",
    )
    assert 'city         = "Alamosa, Colo."' in stanza
    assert 'identity_accessed = "2026-09-02"' in stanza
    blank = draft_stanza(
        name="Adams State",
        abbreviation="ASU",
        conference="RMAC",
        base_url="https://asugrizzlies.com/sports/mens-soccer",
        gender="men",
        platform="sidearm",
        seasons=[2026],
        accessed="2026-09-02",
    )
    assert "# city: the schedule page prints no home town" in blank
