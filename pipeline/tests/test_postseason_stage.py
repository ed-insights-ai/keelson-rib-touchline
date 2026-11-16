"""Postseason stage, shootouts and the bare "NCAA" slot on a schedule page.

The markup is the measured SideArm shape (lincoln 2025, fort-hays-state 2025):
a ``div.sidearm-schedule-tournament`` holding a ``<p>`` header and a ``<ul>``
of ordinary game rows, the round in ``.sidearm-schedule-game-promotion-name``.
"""

from __future__ import annotations

from scripts.collect_board import _dedupe_fixtures, postseason_strangers
from src.config import SchoolConfig, programme_slug
from src.membership import load_membership
from src.sidearm_live import (
    ConferenceHeaders,
    conference_headers,
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
    # The slot is no one level's: Division I and III print it the same way.
    for slot in (
        "NCAA D1",
        "NCAA DI",
        "NCAA Division I",
        "NCAA Division 1",
        "NCAA D-I",
        "NCAA II",
        "NCAA DII",
        "NCAA D3",
        "NCAA DIII",
        "NCAA Division III",
        "TBD",
        "tba",
    ):
        assert round_placeholder(slot), slot
    # Still the whole string only: a name that merely starts that way is a side.
    for side in ("NCAA Division Institute", "NCAA DIV", "Indiana", "Iona", "D3 United"):
        assert not round_placeholder(side), side
    html = _page(_row("1", "Nov 13 (Thu)", "NCAA"))
    assert _parse(html) == {}


def test_the_division_one_championship_rounds_are_ncaa_postseason() -> None:
    """The Division I championship's semifinals and final are the College Cup.

    "NCAA College Cup" carried no round word the NCAA rule knew, so a block
    under it was no postseason and an opponent cell printing it would mint
    a programme named for it. The phrase is the NCAA's own, so it names the
    competition with or without "NCAA" beside it, and it is a round.
    """
    for header in (
        "NCAA College Cup",
        "NCAA Tournament First Round",
        "NCAA Second Round",
        "NCAA Third Round",
        "NCAA Quarterfinal",
        "NCAA College Cup Semifinal",
        "College Cup Final",
        "2025 NCAA Men's College Cup",
    ):
        assert tournament_stage(header) == {
            "phase": "postseason",
            "competition": "ncaa",
            "source": header,
        }, header
        assert round_placeholder(header), header
    # Another body's cup is still another body's postseason.
    assert tournament_stage("NCCAA College Cup") == {
        "phase": "unknown",
        "source": "NCCAA College Cup",
    }

    html = _page(
        _row("1", "Nov 30 (Sun)", "Tiffin", "W, 1-0")
        + _block(
            "NCAA College Cup",
            _row("2", "Dec 12 (Fri)", "Quincy", "W, 2-1", "College Cup Semifinal")
            + _row("3", "Dec 15 (Mon)", "Maryville", "L, 0-1", "NCAA College Cup")
            + _row("4", "Dec 15 (Mon)", "NCAA College Cup"),
        )
    )
    rows = _parse(html)
    assert rows["1"]["stage"] == {"phase": "regular"}
    assert rows["2"]["stage"] == {
        "phase": "postseason",
        "competition": "ncaa",
        "source": "NCAA College Cup",
        "round_published": "College Cup Semifinal",
    }
    assert rows["3"]["stage"]["round_published"] == "NCAA College Cup"  # type: ignore[index]
    # The unfilled slot is skipped, never minted as a programme.
    assert "4" not in rows


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


# ── a conference is recognised from the reference, not from this module ─────
#
# The long names a header prints without the word "conference" or a code
# ("Northeast 10 Championship", "Great Midwest Tournament") used to be a
# table in sidearm_live.py that knew Division II's conferences only. They are
# ``conference_profiles`` in the membership reference now, so the first
# Division I page read ("America East Tournament", Vermont 2024) is a data
# change. The Division I codes below are a TEST reference: none of them is
# declared in the shipped file.


def _reference(profiles: dict[str, dict[str, object]]) -> dict[str, object]:
    return {
        "conferences": [*profiles, "independent", "non_member"],
        "conference_profiles": profiles,
    }


def _d1(*names: str, code_is_word: bool = False) -> dict[str, object]:
    profile: dict[str, object] = {"level": "d1", "names": list(names)}
    if code_is_word:
        profile["code_is_word"] = True
    return profile


D1_REFERENCE = _reference(
    {
        "AE": _d1("America East Conference", "America East"),
        "BIGEAST": _d1("Big East Conference", "Big East"),
        "B1G": _d1("Big Ten Conference", "Big Ten"),
        "A10": _d1("Atlantic 10 Conference", "Atlantic 10", "A-10"),
        "SUNBELT": _d1("Sun Belt Conference", "Sun Belt"),
        "BIGSOUTH": _d1("Big South Conference", "Big South"),
        "BIGWEST": _d1("Big West Conference", "Big West"),
        "PAC12": _d1("Pac-12 Conference", "Pac-12"),
        "MW": _d1("Mountain West Conference", "Mountain West"),
        "MVC": _d1("Missouri Valley Conference", "Missouri Valley"),
        "MAAC": _d1("Metro Atlantic Athletic Conference"),
        "CAA": _d1("Coastal Athletic Association"),
        "ASUN": _d1("Atlantic Sun Conference", "ASUN Conference"),
        "AAC": _d1("American Athletic Conference", "American Conference", "American"),
        "PATRIOT": _d1("Patriot League", code_is_word=True),
        "SUMMIT": _d1("Summit League", code_is_word=True),
        "IVY": _d1("Ivy League", code_is_word=True),
        # One Division II neighbour, for the name inside a longer name.
        "GAC": {
            "level": "d2",
            "names": ["Great American Conference", "Great American"],
        },
    }
)
D1_HEADERS = ConferenceHeaders(D1_REFERENCE)

D1_POSTSEASON = {
    "America East Tournament": "AE",
    "Big East Championship": "BIGEAST",
    "Big Ten Tournament": "B1G",
    "Atlantic 10 Championship": "A10",
    "A-10 Championship": "A10",
    "Sun Belt Championship": "SUNBELT",
    "Big South Tournament": "BIGSOUTH",
    "Big West Championship": "BIGWEST",
    "Pac-12 Tournament": "PAC12",
    "Mountain West Championship": "MW",
    "Missouri Valley Conference Tournament": "MVC",
    "MAAC Championship": "MAAC",
    "CAA Championship": "CAA",
    "ASUN Championship": "ASUN",
    "American Championship": "AAC",
    "Patriot League Tournament": "PATRIOT",
    "Summit League Championship": "SUMMIT",
    "Ivy League Tournament": "IVY",
}


def test_division_one_headers_name_their_conference_from_the_reference() -> None:
    assert len(D1_POSTSEASON) == 18
    for header, conference in D1_POSTSEASON.items():
        assert tournament_stage(header, headers=D1_HEADERS) == {
            "phase": "postseason",
            "competition": "conference",
            "source": header,
        }, header
        assert D1_HEADERS.named(header) == [conference], header


def test_a_word_code_never_names_its_conference_alone() -> None:
    # PATRIOT, SUMMIT and IVY are ordinary words: read as bare tokens they
    # make conference postseason of an invitational, a city and a classic.
    strays = [
        "Patriot Invitational Tournament",
        "Summit City Tournament",
        "Ivy Classic Tournament",
    ]
    for header in strays:
        assert tournament_stage(header, headers=D1_HEADERS) is None, header
        assert D1_HEADERS.named(header) == [], header

    # Without the flag the same reference reads all three as postseason,
    # which is the defect the flag exists for.
    unflagged = ConferenceHeaders(
        _reference(
            {
                "PATRIOT": _d1("Patriot League"),
                "SUMMIT": _d1("Summit League"),
                "IVY": _d1("Ivy League"),
            }
        )
    )
    assert [
        tournament_stage(header, headers=unflagged)["competition"]  # type: ignore[index]
        for header in strays
    ] == ["conference"] * 3

    # What the flag costs: the bare word beside a championship word is no
    # longer read either, until the profile lists the word as a name.
    assert tournament_stage("Ivy Tournament", headers=D1_HEADERS) is None
    listed = ConferenceHeaders(
        _reference({"IVY": _d1("Ivy League", "Ivy", code_is_word=True)})
    )
    assert listed.named("Ivy Tournament") == ["IVY"]
    assert listed.named("2025 Ivy Women's Soccer Tournament") == ["IVY"]
    assert tournament_stage("Ivy Classic Tournament", headers=listed) is None


def test_a_one_word_name_must_qualify_the_championship_word() -> None:
    # "American" is a name the American Conference is printed under, and an
    # ordinary word: it names the conference only directly before the
    # championship word, through nothing but season, gender and sport.
    for header in (
        "American Championship",
        "2025 American Championship",
        "American Men's Soccer Championship",
        "The American Women’s Soccer Tournament",
        "American Conference Championship",
        "American Athletic Conference Tournament",
        "AAC Tournament",
    ):
        assert D1_HEADERS.named(header) == ["AAC"], header
    for header in (
        "American International Tournament",
        "American Invitational Tournament",
        "Pan-American Tournament",
        "Native American Heritage Night",
    ):
        assert tournament_stage(header, headers=D1_HEADERS) is None, header
    # A name inside another conference's longer name is the longer one's.
    for header in (
        "Great American Conference Tournament",
        "Great American Championship",
        "GAC Tournament",
    ):
        assert D1_HEADERS.named(header) == ["GAC"], header


def test_a_name_reads_through_spacing_hyphens_and_case() -> None:
    for header in (
        "PAC 12 TOURNAMENT",
        "pac-12 tournament",
        "A 10 Championship",
        "Atlantic-10 Championship",
        "big  ten   tournament",
    ):
        assert tournament_stage(header, headers=D1_HEADERS) is not None, header
    # Whole words only: a name is not read out of a longer word.
    for header in ("Big Eastern Tournament", "Sun Belted Championship"):
        assert tournament_stage(header, headers=D1_HEADERS) is None, header


def test_the_division_two_long_names_moved_into_the_reference_whole() -> None:
    # One header per alternative of the table that used to live in
    # sidearm_live.py, none carrying the word "conference" or a code, each
    # still read from the shipped reference, and by the conference it names.
    moved = {
        "Northeast 10 Championship": ["NE10"],
        "Northeast-10 Championship": ["NE10"],
        "Northeast10 Semifinal Tournament": ["NE10"],
        "Great Midwest Tournament": ["G-MAC"],
        "GULF SOUTH CHAMPIONSHIPS": ["GSC"],
        "Pacific West Tournament": ["PACWEST"],
        "Sunshine State Championship": ["SSC"],
        "Lone Star Tournament": ["LSC"],
        "Peach Belt Championship": ["PBC"],
        "South Atlantic Tournament": ["SAC"],
        "East Coast Championship": ["ECC"],
        "Mountain East Tournament": ["MEC"],
        "Rocky Mountain Championship": ["RMAC"],
        # Two conferences are printed under it, and it names both.
        "Great Lakes Tournament": ["GLIAC", "GLVC"],
        "Great Northwest Championship": ["GNAC"],
        "Great American Tournament": ["GAC"],
        "Central Atlantic Championship": ["CACC"],
        "California Collegiate Tournament": ["CCAA"],
        "Pennsylvania State Championship": ["PSAC"],
    }
    shipped = conference_headers()
    for header, conferences in moved.items():
        assert tournament_stage(header) == {
            "phase": "postseason",
            "competition": "conference",
            "source": header,
        }, header
        assert sorted(shipped.named(header)) == conferences, header
    # A header naming two conferences names both, in the order printed.
    assert shipped.named("GAC/MIAA Men's Soccer Championship") == ["GAC", "MIAA"]
    assert shipped.named("MIAA/GAC Men's Soccer Championship") == ["MIAA", "GAC"]
    # A name no profile carries is not read, whatever it sounds like.
    assert tournament_stage("Outer Hebrides Tournament") is None


def test_a_declared_code_without_a_profile_is_still_read_as_a_token() -> None:
    # An older mirrored reference carries no profiles: the code rule stands.
    bare = ConferenceHeaders({"conferences": ["GLVC", "independent", "non_member"]})
    assert bare.named("GLVC Championship") == ["GLVC"]
    assert tournament_stage("Great Lakes Tournament", headers=bare) is None
    assert ConferenceHeaders({}).named("GLVC Championship") == []


def test_the_header_reading_is_part_of_the_schedule_parse_identity() -> None:
    # The names used to be source, which the fingerprint hashes; as data
    # they enter it by value, so an edited name re-reads the archive.
    document = load_membership()
    assert ConferenceHeaders(document).signature == conference_headers().signature
    edited = {
        **document,
        "conference_profiles": {
            **document["conference_profiles"],
            "GAC": {"level": "d2", "names": ["Great American Conference"]},
        },
    }
    assert ConferenceHeaders(edited).signature != conference_headers().signature
