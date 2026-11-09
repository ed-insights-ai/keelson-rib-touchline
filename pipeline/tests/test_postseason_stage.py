"""Postseason stage, shootouts and the bare "NCAA" slot on a schedule page.

The markup is the measured SideArm shape (lincoln 2025, fort-hays-state 2025):
a ``div.sidearm-schedule-tournament`` holding a ``<p>`` header and a ``<ul>``
of ordinary game rows, the round in ``.sidearm-schedule-game-promotion-name``.
"""

from __future__ import annotations

from scripts.collect_board import _dedupe_fixtures, postseason_strangers
from src.config import SchoolConfig, programme_slug
from src.sidearm_live import (
    identity_aliases,
    parse_schedule_page,
    parse_shootout,
    resolution_scope,
    round_placeholder,
    tournament_stage,
)


def _school(
    name: str, abbr: str, conference: str = "GLVC", **extra: object
) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation=abbr,
        conference=conference,
        prefix=abbr.lower(),
        base_url="https://example.test/sports/mens-soccer",
        gender="men",
        **extra,  # type: ignore[arg-type]
    )


SCHOOLS = [
    _school("Lincoln", "LU"),
    _school("Tiffin", "TU", "G-MAC"),
    _school("Rockhurst", "RU", abbreviation_resolves=False),
    _school("Maryville", "MU"),
    _school("Missouri S&T", "MST"),
    _school("Quincy", "QU"),
]
ALIASES = identity_aliases(SCHOOLS, "men")
SCOPE = resolution_scope(SCHOOLS, "men", set(), conference="GLVC", season=2025)


def _row(
    game_id: str, date: str, opponent: str, result: str = "", round_: str = ""
) -> str:
    promotion = (
        f'<div class="sidearm-schedule-game-promotion-name">{round_}</div>'
        if round_
        else ""
    )
    result_html = (
        f'<div class="sidearm-schedule-game-result">{result}</div>' if result else ""
    )
    return f"""
    <li class="sidearm-schedule-game sidearm-schedule-home-game" data-game-id="{game_id}">
      <span class="sidearm-schedule-game-opponent-date"><span>{date}</span></span>
      <div class="sidearm-schedule-game-opponent-text">
        <span class="sidearm-schedule-game-home">vs</span>
        <span class="sidearm-schedule-game-opponent-name"><a>{opponent}</a></span>
      </div>
      {promotion}
      {result_html}
    </li>"""


def _block(header: str, rows: str) -> str:
    return (
        f'<li><div class="sidearm-schedule-tournament"><p>{header}</p>'
        f"<ul>{rows}</ul></div></li>"
    )


def _page(body: str) -> str:
    return (
        "<html><head><title>2025 Men's Soccer Schedule</title></head>"
        f"<body><ul>{body}</ul></body></html>"
    )


def _parse(html: str, owner: str = "lincoln") -> dict[str, dict[str, object]]:
    fixtures = parse_schedule_page(
        html,
        page_url="https://example.test/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug=owner,
        aliases=ALIASES,
        scope=SCOPE,
    )
    return {str(f["id"]).rsplit(":", 1)[1]: f for f in fixtures}


def test_a_postseason_block_stamps_its_rows_and_the_regular_season_before_it() -> None:
    html = _page(
        _row("1", "Oct 25 (Sat)", "Quincy", "W, 2-0")
        + _block(
            "GLVC Championship",
            _row("2", "Nov 9 (Sun)", "Missouri S&T", "W, 4-0", "GLVC Semifinal"),
        )
        + _block(
            "NCAA Division II Championship",
            _row("3", "Nov 23 (Sun)", "Tiffin", "W, 1-1 (SO, 4-3)"),
        )
    )
    rows = _parse(html)
    assert rows["1"]["stage"] == {"phase": "regular"}
    assert rows["2"]["stage"] == {
        "phase": "postseason",
        "competition": "conference",
        "source": "GLVC Championship",
        "round_published": "GLVC Semifinal",
    }
    assert rows["3"]["stage"] == {
        "phase": "postseason",
        "competition": "ncaa",
        "source": "NCAA Division II Championship",
    }


def test_a_page_with_no_postseason_block_says_nothing_about_phase() -> None:
    """Senior Day and an invitational use the same markup; neither is a
    postseason, so the page states no phase and no row is called regular."""
    html = _page(
        _block(
            "Adelphi Kick-Off Tournament", _row("1", "Aug 28 (Thu)", "Quincy", "W, 1-0")
        )
        + _block("Senior Day", _row("2", "Oct 25 (Sat)", "Maryville", "L, 0-1"))
    )
    rows = _parse(html)
    assert "stage" not in rows["1"]
    assert "stage" not in rows["2"]


def test_a_row_after_the_postseason_began_outside_every_block_stays_unknown() -> None:
    html = _page(
        _block("GLVC Tournament", _row("1", "Nov 8 (Sat)", "Quincy", "W, 2-1"))
        + _row("2", "Nov 23 (Sun)", "Maryville", "W, 2-0")
    )
    rows = _parse(html)
    assert rows["1"]["stage"]["phase"] == "postseason"
    assert "stage" not in rows["2"]


def test_tournament_headers_measured_in_the_archive() -> None:
    conference = [
        "GLVC Championship",
        "2025 GAC Men's Soccer Tournament",
        "GAC/MIAA Men's Soccer Championship",
        "Northeast 10 Championship",
        "Great Midwest Tournament",
        "GULF SOUTH CHAMPIONSHIPS",
        "Conference Carolinas Tournament",
        "PacWest Championships",
    ]
    ncaa = [
        "NCAA Tournament",
        "NCAA II Final Four",
        "NCAA Division II Super Region 3",
        "NCAA West Regionals",
        "2025 NCAA Division II Men's Soccer Championship",
    ]
    neither = [
        "Senior Day",
        "Homecoming",
        "Preseason Matches",
        "Colorado Mesa Men's Soccer Showcase",
        "Adelphi Kick-Off Tournament",
        "Georgian Court Univ. Tournament",
        "CBU Invitational Tournament",
        "Simon Fraser Tournament",
    ]
    assert {tournament_stage(h)["competition"] for h in conference} == {"conference"}  # type: ignore[index]
    assert {tournament_stage(h)["competition"] for h in ncaa} == {"ncaa"}  # type: ignore[index]
    assert [h for h in neither if tournament_stage(h) is not None] == []
    assert tournament_stage("NCCAA National Championships") == {
        "phase": "unknown",
        "source": "NCCAA National Championships",
    }


def _shootout(
    text: str, owner: str = "lincoln", other: str = "tiffin", home: bool = True
):
    return parse_shootout(
        text,
        owner_slug=owner,
        other_slug=other,
        owner_is_home=home,
        aliases=ALIASES,
        scope=SCOPE,
    )


def test_every_measured_shootout_phrasing_reads_its_winner_from_a_letter_or_name() -> (
    None
):
    win = {"winner": "lincoln", "home": 4, "away": 3}
    assert _shootout("W, 1-1 (SO, 4-3)") == win
    assert _shootout("T, 0-0 (W by PK, 5-4)") == {
        "winner": "lincoln",
        "home": 5,
        "away": 4,
    }
    assert _shootout("T, 0-0 (W, 3-2 PK)") == {
        "winner": "lincoln",
        "home": 3,
        "away": 2,
    }
    # Winner's count first, and the owner lost: the other side takes the 8.
    assert _shootout("T, 1-1 (L, 8-7 PK)") == {"winner": "tiffin", "home": 7, "away": 8}
    # The owner away flips the counts, not the winner.
    assert _shootout("T, 1-1 (L, 8-7 PK)", home=False) == {
        "winner": "tiffin",
        "home": 8,
        "away": 7,
    }


def test_the_owners_result_spelled_out_as_a_word_reads_like_its_letter() -> None:
    """Harding 2026 women 15540 and Lenoir-Rhyne 2026 men 15034: the owner's
    verdict on the shootout written as a word, in parentheses or bare."""
    # The owner lost, winner's count first: the other side takes the 4.
    assert _shootout("T, 0-0 (Lost 4-2 in PKs)") == {
        "winner": "tiffin",
        "home": 2,
        "away": 4,
    }
    assert _shootout("T, 1-1 Lost 4-3 in PK's", home=False) == {
        "winner": "tiffin",
        "home": 4,
        "away": 3,
    }
    assert _shootout("T, 2-2 (Won 5-4 on penalties)") == {
        "winner": "lincoln",
        "home": 5,
        "away": 4,
    }
    # A word in someone else's sentence is not the owner's verdict.
    assert _shootout("T, 1-1 (Quincy won 4-2 on PKs)") is None


def test_a_display_only_abbreviation_names_one_side_of_the_tie() -> None:
    """Rockhurst's "RU" does not resolve (Roosevelt shares it), but between
    Rockhurst and Maryville it names exactly one side."""
    assert _shootout(
        "T, 1-1 RU wins on PKs, 4-3", owner="rockhurst", other="maryville"
    ) == {"winner": "rockhurst", "home": 4, "away": 3}
    assert _shootout(
        "T, 3-3 (Maryville Advances on PKs 4-2)", owner="rockhurst", other="maryville"
    ) == {"winner": "maryville", "home": 2, "away": 4}


def test_a_shootout_with_no_letter_or_name_is_never_read_from_digit_order() -> None:
    assert _shootout("T, 0-0 , 2-3 Penalty Kicks") is None
    # A name that is neither side, and equal counts, decide nothing.
    assert _shootout("T, 1-1 (Quincy Advances on PKs 4-2)") is None
    assert _shootout("T, 1-1 (W, 3-3 PK)") is None
    # No marker, no shootout.
    assert _shootout("T, 1-1 (2OT)") is None


def test_the_row_keeps_the_draw_the_text_and_the_shootout() -> None:
    html = _page(
        _block(
            "NCAA Tournament",
            _row("1", "Nov 23 (Sun)", "Tiffin", "W, 1-1 (SO, 4-3)")
            + _row("2", "Nov 30 (Sun)", "Maryville", "T, 0-0 , 2-3 Penalty Kicks"),
        )
    )
    rows = _parse(html)
    assert (rows["1"]["home_score"], rows["1"]["away_score"]) == (1, 1)
    assert rows["1"]["result_published"] == "W, 1-1 (SO, 4-3)"
    assert rows["1"]["shootout"] == {"winner": "lincoln", "home": 4, "away": 3}
    assert rows["2"]["result_published"] == "T, 0-0 , 2-3 Penalty Kicks"
    assert "shootout" not in rows["2"]


def test_a_bare_ncaa_is_a_slot_not_a_programme() -> None:
    for slot in ("NCAA", "ncaa", "NCAA D2", "NCAA Division II"):
        assert round_placeholder(slot), slot
    html = _page(_row("1", "Nov 13 (Thu)", "NCAA"))
    assert _parse(html) == {}


def test_dedupe_keeps_a_fact_one_row_published_and_flips_it_to_the_kept_orientation() -> (
    None
):
    stage = {"phase": "postseason", "competition": "ncaa", "source": "NCAA Tournament"}
    kept = {
        "id": "sidearm:maryville:1",
        "date": "2025-11-23",
        "home": "maryville",
        "away": "rockhurst",
        "status": "final",
        "home_score": 1,
        "away_score": 1,
        "conference_game": False,
        "venue": "St. Louis",
        "time": "13:00",
    }
    other = {
        "id": "sidearm:rockhurst:2",
        "date": "2025-11-23",
        "home": "rockhurst",
        "away": "maryville",
        "status": "final",
        "home_score": 1,
        "away_score": 1,
        "conference_game": False,
        "stage": stage,
        "result_published": "T, 1-1 RU wins on PKs, 4-3",
        "shootout": {"winner": "rockhurst", "home": 4, "away": 3},
    }
    rows, duplicates = _dedupe_fixtures([kept, other])
    assert duplicates == 1
    (row,) = rows
    assert row["stage"] == stage
    assert row["result_published"] == "T, 1-1 RU wins on PKs, 4-3"
    assert row["home"] == "maryville" or row["home"] == "rockhurst"
    shootout = row["shootout"]
    winner_is_home = row["home"] == "rockhurst"
    assert shootout == {
        "winner": "rockhurst",
        "home": 4 if winner_is_home else 3,
        "away": 3 if winner_is_home else 4,
    }


def test_dedupe_refuses_to_pick_between_contradicting_rows(capsys) -> None:
    base = {
        "date": "2025-11-23",
        "status": "final",
        "home_score": 1,
        "away_score": 1,
        "conference_game": False,
    }
    a = {
        **base,
        "id": "sidearm:lincoln:1",
        "home": "lincoln",
        "away": "tiffin",
        "stage": {"phase": "postseason", "competition": "ncaa"},
        "shootout": {"winner": "lincoln", "home": 4, "away": 3},
    }
    b = {
        **base,
        "id": "sidearm:tiffin:2",
        "home": "lincoln",
        "away": "tiffin",
        "stage": {"phase": "postseason", "competition": "conference"},
        "shootout": {"winner": "tiffin", "home": 3, "away": 4},
    }
    (row,), _ = _dedupe_fixtures([a, b])
    assert row["stage"] == {"phase": "unknown"}
    assert "shootout" not in row
    out = capsys.readouterr().out
    assert "stage disagreement" in out and "shootout disagreement" in out


def test_a_postseason_side_with_no_stanza_is_named() -> None:
    stanzas = {programme_slug(s.name) for s in SCHOOLS}
    fixtures = [
        {
            "id": "sidearm:lincoln:5",
            "date": "2025-11-21",
            "home": "lincoln",
            "away": "wilimington",
            "stage": {"phase": "postseason", "competition": "ncaa"},
        },
        {
            "id": "sidearm:lincoln:6",
            "date": "2025-09-01",
            "home": "lincoln",
            "away": "some-club",
            "stage": {"phase": "regular"},
        },
    ]
    assert postseason_strangers(fixtures, stanzas) == [
        "postseason side with no stanza: 2025-11-21, wilimington (sidearm:lincoln:5)"
    ]


def test_the_rendered_rows_shootout_follows_the_side_onto_a_reversed_payload_twin() -> (
    None
):
    """kentucky-wesleyan 2026, game 11458: the payload reads the match away
    at Lake Erie, the rendered row reads it at home, and only the rendered
    row prints the shootout. The counts must follow Kentucky Wesleyan."""
    import json

    schools = [
        *SCHOOLS,
        _school("Kentucky Wesleyan", "KWC", "G-MAC"),
        _school("Lake Erie", "LEC", "G-MAC"),
    ]
    aliases = identity_aliases(schools, "men")
    scope = resolution_scope(schools, "men", set(), conference="G-MAC", season=2025)
    event = {
        "id": 11458,
        "date": "2025-11-05T19:00:00",
        "location_indicator": "A",
        "is_conference": True,
        "type": "past",
        "schedule": {"title": "2025 Men's Soccer Schedule"},
        "opponent": {"title": "Lake Erie"},
        "result": {"team_score": "1", "opponent_score": "1", "status": "T"},
    }
    component = (
        "<script>\nvar obj = "
        + json.dumps({"type": "events", "data": [event]})
        + ";\n</script>"
    )
    html = (
        "<html><head><title>2025 Men's Soccer Schedule</title></head><body>"
        + component
        + "<ul>"
        + _block(
            "Great Midwest Tournament",
            _row(
                "11458", "Nov 5 (Wed)", "Lake Erie", "T, 1-1 (KWC Advances 3-0 on PKs)"
            ),
        )
        + "</ul></body></html>"
    )
    (row,) = parse_schedule_page(
        html,
        page_url="https://example.test/sports/mens-soccer/schedule/2025",
        year=2025,
        owner_slug="kentucky-wesleyan",
        aliases=aliases,
        scope=scope,
    )
    assert (row["home"], row["away"]) == ("lake-erie", "kentucky-wesleyan")
    assert row["shootout"] == {"winner": "kentucky-wesleyan", "home": 0, "away": 3}
    assert row["stage"]["competition"] == "conference"


def test_an_opponent_annotation_names_the_competition_of_a_row_no_block_holds() -> None:
    """roberts-wesleyan 2025, game 5530: the one NCAA tie that page prints
    outside any block, its round in the opponent cell's annotation."""
    html = _page(
        _row("1", "Oct 25 (Sat)", "Quincy", "W, 2-0")
        + _row(
            "2",
            "Nov 21 (Fri)",
            "Maryville (NCAA Division II Tournament First Round at Franklin Pierce University)",
            "L, 2-6",
        )
        + _row("3", "Nov 1 (Sat)", "Missouri S&T (Senior Night)", "W, 1-0")
    )
    rows = _parse(html)
    assert rows["2"]["away"] == "maryville" or rows["2"]["home"] == "maryville"
    assert rows["2"]["stage"] == {
        "phase": "postseason",
        "competition": "ncaa",
        "source": "NCAA Division II Tournament First Round at Franklin Pierce University",
        "round_published": "NCAA Division II Tournament First Round at Franklin Pierce University",
    }
    assert rows["1"]["stage"] == {"phase": "regular"}
    assert rows["3"]["stage"] == {"phase": "regular"}
