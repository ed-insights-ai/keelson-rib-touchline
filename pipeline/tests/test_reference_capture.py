from pathlib import Path

import pytest

from scripts import reference_capture as rc

SCHEDULE = """<ul>
<li class="sidearm-schedule-game sidearm-schedule-home-game"><div class="sidearm-schedule-game-opponent-name"><a href="https://a.example">Alpha College</a></div>
<div class="sidearm-schedule-game-conference x"><span><img alt="Sample Conference" src="/c.png"></span></div></li>
<li class="sidearm-schedule-game sidearm-schedule-away-game tourney"><div class="sidearm-schedule-game-opponent-name">(2) Beta</div>
<div class="sidearm-schedule-game-conference x"></div></li>
</ul>"""

STANDINGS = """<table><caption>2025 Men's Soccer</caption><tr><th>Team</th><th>W</th></tr>
<tr><td><a href="/t">Gamma</a></td><td>3</td></tr><tr><td>Delta &amp; Co</td><td>1</td></tr></table>"""


def test_schedule_games_carry_the_conference_mark_and_tournament() -> None:
    games = rc.schedule_games(SCHEDULE)
    assert games == [
        {
            "opponent": "Alpha College",
            "conference": "Sample Conference",
            "tournament": False,
        },
        {"opponent": "(2) Beta", "conference": None, "tournament": True},
    ]


def test_standings_rows_are_row_cells_under_the_caption() -> None:
    assert rc.standings_rows(STANDINGS) == [
        ["2025 Men's Soccer", "Team | W", "Gamma | 3", "Delta & Co | 1"]
    ]


def test_the_list_refuses_a_line_without_an_https_url(tmp_path: Path) -> None:
    good = tmp_path / "good.txt"
    good.write_text("# note\n\nsunyac-m-2025 https://example.org/standings\n")
    assert rc.read_list(good) == [("sunyac-m-2025", "https://example.org/standings")]
    bad = tmp_path / "bad.txt"
    bad.write_text("label http://example.org/\n")
    with pytest.raises(ValueError):
        rc.read_list(bad)


class _Response:
    def __init__(self, text: str, status: int = 200, url: str = "") -> None:
        self.text = text
        self.status_code = status
        self.url = url


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response

    def get(self, url: str, timeout: int) -> _Response:
        self.response.url = self.response.url or url
        return self.response


def test_read_one_keeps_a_schedule_to_its_marked_games() -> None:
    page = "<title>2025 Men's Soccer Schedule</title><!-- sidearm -->" + SCHEDULE
    record = rc.read_one(
        _Session(_Response(page)), "x", "https://a.example/schedule/2025"
    )
    assert record["platform"] == "sidearm"
    assert record["games"] == 2
    assert record["marked"] == [["Alpha College", "Sample Conference"]]


def test_read_one_records_a_refusal_without_a_body() -> None:
    record = rc.read_one(
        _Session(_Response("no", 405)), "x", "https://a.example/standings"
    )
    assert record == {"label": "x", "url": "https://a.example/standings", "status": 405}


def test_the_home_away_label_is_not_a_conference_mark() -> None:
    page = """<ul>
<li class="sidearm-schedule-game"><div class="sidearm-schedule-game-opponent-name">Epsilon</div>
<div class="sidearm-schedule-game-conference-vs">vs.</div></li>
</ul>"""
    assert rc.schedule_games(page) == [
        {"opponent": "Epsilon", "conference": None, "tournament": False}
    ]


def test_presto_events_carry_the_conference_star() -> None:
    page = """<table>
<tr class="event-row"><td>Sep 6</td><td>at Zeta *</td><td>W 2-1</td></tr>
<tr class="event-row"><td>Sep 9</td><td>vs Eta</td><td>L 0-1</td></tr>
</table>"""
    assert rc.presto_games(page) == [
        {"event": "Sep 6 at Zeta * W 2-1", "conference": True},
        {"event": "Sep 9 vs Eta L 0-1", "conference": False},
    ]
    record = rc.read_one(
        _Session(_Response(page)), "zeta", "https://z.example/schedule"
    )
    assert record["games"] == 2
    assert record["marked"] == ["Sep 6 at Zeta * W 2-1"]
