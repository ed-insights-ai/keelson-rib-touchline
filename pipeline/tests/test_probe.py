"""Tests for read-only athletics-site discovery."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import requests

from scripts import probe as probe_cli
from src.presto import STATS_TEMPLATE
from src.probe import (
    ABBREVIATION_BY_HAND,
    LAYER_PRESENT,
    PLATFORM_PRESTOSPORTS,
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
    survey_seasons,
)

FIXTURES = Path(__file__).parent / "fixtures"
PRESTO_BASE = "https://www.tampaspartans.com/sports/msoc"


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
    # "University of Indianapolis" folds onto "Indianapolis" (tl-kvn), so the
    # probe drafts no alias for it; "UMSL" shares no token with its formal
    # name, so that one is still stated.
    assert indianapolis.aliases == []
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
    # One initial is no short form; the guess is refused, not padded.
    assert identity.abbreviation == ""
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
    # "Example University" yields one initial (university is filler), which
    # is refused and named in the summary rather than drafted.
    assert 'abbreviation = ""' in output
    assert output.endswith("hand edits still needed: abbreviation\n  example.test\n")
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


def _presto_page(name: str) -> str:
    return (FIXTURES / f"prestosports_tampa_{name}.html").read_text()


def _refused(url: str, status: int) -> MagicMock:
    """A response the server answered with a non-2xx status."""
    response = MagicMock()
    response.url = url
    response.text = ""
    response.status_code = status
    response.raise_for_status.side_effect = requests.HTTPError(
        f"{status} Client Error for url: {url}", response=response
    )
    return response


def _session_by_url(pages: dict[str, object]) -> MagicMock:
    """A session answering each URL with its response, or raising its exception."""
    session = MagicMock()

    def get(url: str, **_: object) -> object:
        answer = pages[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    session.get.side_effect = get
    return session


def test_classify_platform_recognizes_prestosports_from_its_markup() -> None:
    for name in ("schedule_2025", "roster_2026", "teams_2026"):
        platform, evidence = classify_platform(_presto_page(name))
        assert platform == PLATFORM_PRESTOSPORTS, name
        assert "prestosports theme asset host" in evidence, name
    _, evidence = classify_platform(_presto_page("schedule_2025"))
    assert "server-rendered PrestoSports schedule markup" in evidence


def test_classify_platform_recognizes_the_payload_only_sidearm_skins() -> None:
    """Bead tl-4sg.34: the legacy list skin and the Nuxt skin render no
    li.sidearm-* rows and embed no events component; the schedule is a
    payload, and a Nuxt page names its asset bucket on every layer."""
    for name in (
        "sidearm_lock_haven_schedule_2025.html",
        "sidearm_millersville_schedule_2025.html",
    ):
        platform, evidence = classify_platform((FIXTURES / name).read_text())
        assert platform == PLATFORM_SIDEARM, name
        assert "server-rendered SideArm schedule markup" in evidence, name
    platform, evidence = classify_platform(
        (FIXTURES / "sidearm_millersville_roster_2025.html").read_text()
    )
    assert platform == PLATFORM_SIDEARM
    assert evidence == ["SideArm nextgen asset bucket"]


def test_probe_layers_reads_a_prestosports_site_at_its_own_urls() -> None:
    year = 2026
    schedule_url = f"{PRESTO_BASE}/2026-27/schedule"
    roster_url = f"{PRESTO_BASE}/2026-27/roster"
    teams_url = f"{PRESTO_BASE}/2026-27/teams/tampa"
    # The saved schedule is the played 2025 season, kept for its box-score
    # links; only its title year moves so the season proof passes at the
    # 2026-27 URL beside the saved 2026 roster and statistics pages.
    schedule = _presto_page("schedule_2025").replace("<title>2025 ", "<title>2026 ", 1)
    session = _session_by_url(
        {
            schedule_url: _response(schedule_url, schedule),
            roster_url: _response(roster_url, _presto_page("roster_2026")),
            teams_url: _response(teams_url, _presto_page("teams_2026")),
        }
    )

    assert probe_layers(session, PRESTO_BASE, year, PLATFORM_PRESTOSPORTS) == {
        "schedule": LAYER_PRESENT,
        "roster": LAYER_PRESENT,
        "stats": LAYER_PRESENT,
        "matches": LAYER_PRESENT,
    }
    assert [call.args[0] for call in session.get.call_args_list] == [
        schedule_url,
        roster_url,
        teams_url,
    ]


def test_probe_layers_says_what_http_said() -> None:
    year = 2026
    schedule_url = f"{PRESTO_BASE}/2026-27/schedule"
    schedule = _presto_page("schedule_2025").replace("<title>2025 ", "<title>2026 ", 1)
    session = _session_by_url(
        {
            schedule_url: _response(schedule_url, schedule),
            f"{PRESTO_BASE}/2026-27/roster": _refused(
                f"{PRESTO_BASE}/2026-27/roster", 403
            ),
            f"{PRESTO_BASE}/2026-27/teams/tampa": requests.ReadTimeout(
                "read timed out"
            ),
        }
    )

    assert probe_layers(session, PRESTO_BASE, year, PLATFORM_PRESTOSPORTS) == {
        "schedule": LAYER_PRESENT,
        "roster": "error (HTTP 403)",
        "stats": "error (timeout)",
        "matches": LAYER_PRESENT,
    }

    sidearm = MagicMock()
    sidearm.get.side_effect = lambda url, **_: _refused(url, 500)
    assert probe_layers(sidearm, "https://example.test/sports/mens-soccer", year) == {
        "schedule": "error (HTTP 500)",
        "roster": "error (HTTP 500)",
        "stats": "error (HTTP 500)",
        "matches": "error (HTTP 500)",
    }


def test_probe_layers_reads_the_prestosports_team_link_off_the_landing_page() -> None:
    year = 2026
    roster_url = f"{PRESTO_BASE}/2026-27/roster"
    teams_url = f"{PRESTO_BASE}/2026-27/teams/tampa"
    pages = {
        f"{PRESTO_BASE}/2026-27/schedule": _refused(
            f"{PRESTO_BASE}/2026-27/schedule", 403
        ),
        roster_url: _response(roster_url, _presto_page("roster_2026")),
        teams_url: _response(teams_url, _presto_page("teams_2026")),
    }

    # Without the schedule page there is no team link to read, and the
    # statistics page is not guessed from the school's name.
    blind = probe_layers(
        _session_by_url(pages), PRESTO_BASE, year, PLATFORM_PRESTOSPORTS
    )
    assert blind["schedule"] == "error (HTTP 403)"
    assert blind["stats"] == "error (team link not read: HTTP 403)"

    landing = '<a href=" /sports/msoc/2026-27/teams/tampa ">Current Season</a>'
    seen = probe_layers(
        _session_by_url(pages),
        PRESTO_BASE,
        year,
        PLATFORM_PRESTOSPORTS,
        landing_html=landing,
    )
    assert seen["stats"] == LAYER_PRESENT


def test_survey_seasons_names_the_seasons_the_site_refused() -> None:
    schedule_2025 = f"{PRESTO_BASE}/2025-26/schedule"
    session = _session_by_url(
        {
            f"{PRESTO_BASE}/2026-27/schedule": _refused(
                f"{PRESTO_BASE}/2026-27/schedule", 403
            ),
            schedule_2025: _response(schedule_2025, _presto_page("schedule_2025")),
        }
    )

    survey = survey_seasons(session, PRESTO_BASE, [2026, 2025], PLATFORM_PRESTOSPORTS)
    assert survey.served == [2025]
    assert survey.errors == {2026: "HTTP 403"}
    assert served_seasons(
        session, PRESTO_BASE, [2026, 2025], PLATFORM_PRESTOSPORTS
    ) == [2025]


def test_derive_identity_reads_the_mascot_off_a_prestosports_title() -> None:
    identity = derive_identity(
        name="Tampa", pages=[_presto_page("schedule_2025")], url=PRESTO_BASE
    )

    assert identity.name == "Tampa"
    assert identity.mascot == "Spartans"
    # "University of Tampa" keys to "tampa" — the fold carries it (tl-kvn),
    # so it is not worth a stated alias.
    assert identity.aliases == []
    # PrestoSports rows print no town, and the site publishes no short token,
    # so the city stays blank (the stanza says so) and the one-letter initial
    # is refused: the abbreviation is left for the reviewer to set.
    assert identity.city == ""
    assert identity.abbreviation == ""


def test_draft_stanza_for_prestosports_names_both_scrapers() -> None:
    stanza = draft_stanza(
        name="Tampa",
        abbreviation="UT",
        conference="SSC",
        base_url=f"{PRESTO_BASE}/",
        gender="men",
        platform=PLATFORM_PRESTOSPORTS,
        seasons=[2025, 2026],
        mascot="Spartans",
        accessed="2026-09-02",
    )

    parsed = tomllib.loads(stanza)["schools"][0]
    assert parsed["scraper"] == "prestosports"
    assert parsed["live_scraper"] == "prestosports"
    assert parsed["base_url"] == PRESTO_BASE
    assert 'scraper      = "prestosports"\nlive_scraper = "prestosports"\n' in stanza


def test_cli_reports_what_http_said_when_the_site_refuses(capsys) -> None:
    session = MagicMock()
    session.get.side_effect = lambda url, **_: _refused(url, 403)

    exit_code = probe_cli.main(
        [
            "--url",
            PRESTO_BASE,
            "--name",
            "Tampa",
            "--conference",
            "SSC",
            "--seasons",
            "2026",
        ],
        session=session,
    )

    out, err = capsys.readouterr()
    assert exit_code == 1
    assert f"Platform: unknown — HTTP 403 from {PRESTO_BASE}" in out
    assert "Evidence: site not seen" in out
    assert "  schedule: error (HTTP 403)" in out
    assert "  stats: error (HTTP 403)" in out
    assert "Served seasons: none" in out
    assert "Seasons not seen: 2026 (HTTP 403)" in out
    assert "[[schools]]" in out
    assert "403" in err


def _presto_session() -> MagicMock:
    """Tampa as the probe sees it: the landing page answers at the bare
    sport URL, 2026 is refused and 2025 is served."""
    landing = f"""
    <html>
      <head>
        <title>Men's Soccer - University of Tampa Athletics</title>
        <meta property="og:site_name" content="University of Tampa Athletics">
        <meta property="og:url" content="{PRESTO_BASE}/index">
        <link rel="stylesheet"
              href="https://theme-assets.prestosports.com/theme-assets/generic/assets/css/global-reset.css">
      </head>
      <body><a href=" /sports/msoc/2026-27/teams/tampa ">Current Season</a></body>
    </html>
    """
    schedule_2025 = f"{PRESTO_BASE}/2025-26/schedule"
    roster_url = f"{PRESTO_BASE}/2026-27/roster"
    teams_url = f"{PRESTO_BASE}/2026-27/teams/tampa"
    return _session_by_url(
        {
            PRESTO_BASE: _response(f"{PRESTO_BASE}/index", landing),
            f"{PRESTO_BASE}/2026-27/schedule": _refused(
                f"{PRESTO_BASE}/2026-27/schedule", 404
            ),
            roster_url: _response(roster_url, _presto_page("roster_2026")),
            teams_url: _response(teams_url, _presto_page("teams_2026")),
            schedule_2025: _response(schedule_2025, _presto_page("schedule_2025")),
        }
    )


def test_cli_probes_a_prestosports_site_end_to_end(capsys) -> None:
    session = _presto_session()

    exit_code = probe_cli.main(
        [
            "--url",
            f"{PRESTO_BASE}/",
            "--name",
            "Tampa",
            "--conference",
            "SSC",
            "--seasons",
            "2025-2026",
        ],
        session=session,
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Platform: prestosports" in out
    assert "Evidence: prestosports theme asset host" in out
    assert "  schedule: error (HTTP 404)" in out
    assert "  roster: present" in out
    assert "  stats: present" in out
    assert "  matches: error (HTTP 404)" in out
    assert "Served seasons: 2025" in out
    assert "Seasons not seen: 2026 (HTTP 404)" in out
    assert 'name         = "Tampa"' in out
    assert 'mascot       = "Spartans"' in out
    # The formal name folds onto the plain one, so no alias line is drafted.
    assert "aliases" not in out
    assert f'base_url     = "{PRESTO_BASE}"' in out
    assert "years        = [2025]" in out
    assert 'scraper      = "prestosports"' in out
    assert 'live_scraper = "prestosports"' in out
    assert "# city: the schedule page prints no home town" in out
    # The site prints no short form and "Tampa" has one initial: refused.
    assert "Hand edits still needed: abbreviation" in out
    assert 'abbreviation = ""\n' + ABBREVIATION_BY_HAND in out
    assert out.endswith(
        "hand edits still needed: abbreviation\n  www.tampaspartans.com\n"
    )


def test_cli_accepts_the_prestosports_index_landing_form(capsys) -> None:
    """Bead tl-4an.29: ``/sports/msoc/index`` is the same landing page as
    ``/sports/msoc``; both forms draft one identical stanza at the bare URL."""
    outputs: list[str] = []
    fetched: list[list[str]] = []
    for given in (f"{PRESTO_BASE}/index", f"{PRESTO_BASE}/index/", PRESTO_BASE):
        session = _presto_session()
        exit_code = probe_cli.main(
            ["--url", given, "--name", "Tampa", "--conference", "SSC"]
            + ["--seasons", "2025-2026"],
            session=session,
        )
        assert exit_code == 0, given
        outputs.append(capsys.readouterr().out)
        fetched.append([call.args[0] for call in session.get.call_args_list])

    assert outputs[0] == outputs[1] == outputs[2]
    assert fetched[0] == fetched[1] == fetched[2]
    assert fetched[0][0] == PRESTO_BASE
    assert f"URL: {PRESTO_BASE}\n" in outputs[0]
    assert f'base_url     = "{PRESTO_BASE}"' in outputs[0]
    assert "/index" not in outputs[0].replace(f"{PRESTO_BASE}/index", "")
    # Women's soccer takes the same form.
    assert probe_cli._landing_url("https://x.test/sports/wsoc/index") == (
        "https://x.test/sports/wsoc"
    )


def test_draft_stanza_refuses_a_one_letter_abbreviation() -> None:
    def draft(abbreviation: str) -> str:
        return draft_stanza(
            name="Lee",
            abbreviation=abbreviation,
            conference="GSC",
            base_url="https://leeuflames.com/sports/mens-soccer",
            gender="men",
            platform=PLATFORM_SIDEARM,
            seasons=[2026],
            accessed="2026-09-04",
        )

    refused = draft("L")
    assert (
        'name         = "Lee"\n'
        'abbreviation = ""\n'
        "# hand abbreviation required: the site prints no short form the probe "
        "could read\n"
        'conference   = "GSC"\n'
    ) in refused
    assert tomllib.loads(refused)["schools"][0]["abbreviation"] == ""
    assert draft("") == refused
    kept = draft("LEE")
    assert 'abbreviation = "LEE"\n' in kept
    assert "hand abbreviation required" not in kept


def test_probe_layers_locates_the_statistics_page_through_the_redirect() -> None:
    """The legacy table skin publishes no team link anywhere (measured
    2026-09-02 on wildcats.athletics.wilmu.edu and stacathletics.com), so
    the probe follows the site's own redirect of ``{y}-{yy}/teams``, the way
    the collector does, and judges the print template it leads to."""
    base = "https://wildcats.athletics.wilmu.edu/sports/msoc"
    year = 2025
    schedule_url = f"{base}/2025-26/schedule"
    roster_url = f"{base}/2025-26/roster"
    teams_url = f"{base}/2025-26/teams"
    stats_url = f"{base}/2025-26/teams/wilmingtondel?tmpl={STATS_TEMPLATE}"
    redirect = MagicMock()
    redirect.status_code = 302
    redirect.headers = {"Location": "/sports/msoc/2025-26/teams/wilmingtondel"}
    session = _session_by_url(
        {
            schedule_url: _response(
                schedule_url,
                (FIXTURES / "prestosports_wilmington_schedule_2025.html").read_text(),
            ),
            roster_url: _response(
                roster_url,
                (FIXTURES / "prestosports_wilmington_roster_2025.html").read_text(),
            ),
            teams_url: redirect,
            stats_url: _response(stats_url, _presto_page("stats_2025")),
        }
    )

    assert probe_layers(session, base, year, PLATFORM_PRESTOSPORTS) == {
        "schedule": LAYER_PRESENT,
        "roster": LAYER_PRESENT,
        "stats": LAYER_PRESENT,
        "matches": LAYER_PRESENT,
    }
    assert [call.args[0] for call in session.get.call_args_list] == [
        schedule_url,
        roster_url,
        teams_url,
        stats_url,
    ]
