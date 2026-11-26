"""A misread non-conference side is re-pointed only when the other
programme's own page proves it: one candidate, same day, same score."""

from __future__ import annotations

import json
from pathlib import Path

from src.twins import SeasonIndex, repoint_by_twins, season_index


def _row(
    owner: str, n: int, date: str, home: str, away: str, hs=None, as_=None, **extra
):
    row = {
        "id": f"sidearm:{owner}:{n}",
        "date": date,
        "home": home,
        "away": away,
        "status": "final" if hs is not None else "scheduled",
        **extra,
    }
    if hs is not None:
        row["home_score"], row["away_score"] = hs, as_
    return row


def _doc(members: list[str], rows: list[dict]) -> dict:
    return {"programmes": [{"slug": s} for s in members], "fixtures": rows}


A10 = _doc(
    ["loyola-chicago", "dayton"],
    [
        _row("loyola-chicago", 1, "2026-08-20", "green-bay", "loyola-chicago", 0, 2),
        _row("loyola-chicago", 2, "2026-09-13", "uic", "loyola-chicago", 1, 0),
    ],
)
PATRIOT = _doc(
    ["loyola-maryland"],
    [_row("loyola-maryland", 1, "2026-08-28", "syracuse", "loyola-maryland", 2, 0)],
)
ACC = _doc(
    ["miami"],
    [_row("miami", 1, "2026-08-20", "little-rock", "miami", 0, 3)],
)
MAC = _doc(
    ["miami-ohio"],
    [_row("miami-ohio", 1, "2026-08-20", "miami-ohio", "morehead-state", 2, 1)],
)
UNCOLLECTED = {"programmes": [{"slug": "quiet"}], "fixtures": []}


def _index(*docs: dict) -> SeasonIndex:
    return SeasonIndex(docs)


def test_a_stranger_takes_the_programme_whose_page_lists_the_match() -> None:
    rows = [_row("green-bay", 1, "2026-08-20", "green-bay", "loyola", 0, 2)]
    changes = repoint_by_twins(rows, {"green-bay"}, _index(A10, PATRIOT))
    assert rows[0]["away"] == "loyola-chicago"
    assert [(c.was, c.now, c.proof) for c in changes] == [
        ("loyola", "loyola-chicago", "sidearm:loyola-chicago:1")
    ]
    assert "loyola-chicago's own page" in changes[0].line()


def test_a_wrong_programme_whose_page_has_no_such_match_is_re_pointed() -> None:
    rows = [_row("little-rock", 1, "2026-08-20", "little-rock", "miami-ohio", 0, 3)]
    repoint_by_twins(rows, {"little-rock"}, _index(ACC, MAC))
    assert rows[0]["away"] == "miami"


def test_a_side_its_own_page_confirms_stands() -> None:
    rows = [
        _row("morehead-state", 1, "2026-08-20", "miami-ohio", "morehead-state", 2, 1)
    ]
    assert repoint_by_twins(rows, {"morehead-state"}, _index(ACC, MAC)) == []
    assert rows[0]["home"] == "miami-ohio"


def test_nothing_moves_without_proof() -> None:
    cases = [
        # a different score
        _row("green-bay", 1, "2026-08-20", "green-bay", "loyola", 1, 2),
        # another day
        _row("green-bay", 2, "2026-08-21", "green-bay", "loyola", 0, 2),
        # not played yet
        _row("green-bay", 3, "2026-08-20", "green-bay", "loyola"),
        # an exhibition
        _row(
            "green-bay",
            4,
            "2026-08-20",
            "green-bay",
            "loyola",
            0,
            2,
            match_type="exhibition",
        ),
    ]
    for row in cases:
        rows = [row]
        assert repoint_by_twins(rows, {"green-bay"}, _index(A10)) == [], row
        assert row["away"] == "loyola"


def test_two_candidates_or_an_uncollected_programme_stay_as_read() -> None:
    twin = _doc(
        ["loyola-maryland"],
        [
            _row(
                "loyola-maryland", 9, "2026-08-20", "green-bay", "loyola-maryland", 0, 2
            )
        ],
    )
    rows = [_row("green-bay", 1, "2026-08-20", "green-bay", "loyola", 0, 2)]
    assert repoint_by_twins(rows, {"green-bay"}, _index(A10, twin)) == []
    rows = [_row("green-bay", 1, "2026-08-20", "green-bay", "quiet", 0, 2)]
    assert repoint_by_twins(rows, {"green-bay"}, _index(A10, UNCOLLECTED)) == []
    assert rows[0]["away"] == "quiet"


def test_conference_sides_and_rows_another_member_owns_are_untouched() -> None:
    rows = [
        _row("green-bay", 1, "2026-08-20", "green-bay", "milwaukee", 0, 2),
        _row("milwaukee", 1, "2026-08-20", "green-bay", "loyola", 0, 2),
    ]
    assert repoint_by_twins(rows, {"green-bay", "milwaukee"}, _index(A10)) == []


def test_the_owner_already_holding_the_match_is_not_duplicated() -> None:
    rows = [
        _row("green-bay", 1, "2026-08-20", "green-bay", "loyola", 0, 2),
        _row("green-bay", 2, "2026-08-20", "green-bay", "loyola-chicago", 0, 2),
    ]
    assert repoint_by_twins(rows, {"green-bay"}, _index(A10)) == []


def test_the_index_reads_the_sibling_files_only(tmp_path: Path) -> None:
    fixtures = tmp_path / "data" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "2026-men-a10.json").write_text(json.dumps(A10))
    (fixtures / "2026-men-horizon.json").write_text(
        json.dumps(
            _doc(
                ["green-bay"],
                [_row("green-bay", 1, "2026-08-20", "green-bay", "x", 0, 2)],
            )
        )
    )
    (fixtures / "2026-women-acc.json").write_text(json.dumps(ACC))
    (fixtures / "2025-men-a10.json").write_text("not json")
    index = season_index(fixtures, "2026-men-horizon")
    assert set(index.own) == {"loyola-chicago"}
    assert "green-bay" not in index.programmes


def test_a_shootout_winner_follows_the_re_pointed_side() -> None:
    twin = _doc(
        ["loyola-chicago"],
        [_row("loyola-chicago", 1, "2026-11-01", "green-bay", "loyola-chicago", 1, 1)],
    )
    row = _row("green-bay", 1, "2026-11-01", "green-bay", "loyola", 1, 1)
    row["shootout"] = {"winner": "loyola", "home": 3, "away": 4}
    repoint_by_twins([row], {"green-bay"}, _index(twin))
    assert row["away"] == "loyola-chicago"
    assert row["shootout"] == {"winner": "loyola-chicago", "home": 3, "away": 4}


def test_a_conference_opponent_misread_takes_the_member_whose_page_lists_it() -> None:
    # Two Concordias in one conference: "Concordia" on Benedictine's page
    # mints a stranger; Concordia Wisconsin's own row in the same collect
    # proves which one played.
    rows = [
        _row("benedictine", 1, "2026-09-16", "benedictine", "concordia", 2, 1),
        _row(
            "concordia-wisconsin",
            7,
            "2026-09-16",
            "benedictine",
            "concordia-wisconsin",
            2,
            1,
        ),
        _row("concordia-chicago", 3, "2026-09-16", "concordia-chicago", "aurora", 1, 0),
    ]
    members = {"benedictine", "concordia-wisconsin", "concordia-chicago"}
    changes = repoint_by_twins(rows, members, _index())
    assert rows[0]["away"] == "concordia-wisconsin"
    assert [(c.was, c.now, c.proof) for c in changes] == [
        ("concordia", "concordia-wisconsin", "sidearm:concordia-wisconsin:7")
    ]


def test_a_conference_twin_needs_the_same_score_and_one_candidate() -> None:
    rows = [
        _row("benedictine", 1, "2026-09-16", "benedictine", "concordia", 2, 1),
        _row(
            "concordia-wisconsin",
            7,
            "2026-09-16",
            "benedictine",
            "concordia-wisconsin",
            3,
            1,
        ),
    ]
    assert (
        repoint_by_twins(rows, {"benedictine", "concordia-wisconsin"}, _index()) == []
    )
    assert rows[0]["away"] == "concordia"
    rows = [
        _row("benedictine", 1, "2026-09-16", "benedictine", "concordia", 2, 1),
        _row(
            "concordia-wisconsin",
            7,
            "2026-09-16",
            "benedictine",
            "concordia-wisconsin",
            2,
            1,
        ),
        _row(
            "concordia-chicago",
            3,
            "2026-09-16",
            "benedictine",
            "concordia-chicago",
            2,
            1,
        ),
    ]
    members = {"benedictine", "concordia-wisconsin", "concordia-chicago"}
    assert repoint_by_twins(rows, members, _index()) == []
    assert rows[0]["away"] == "concordia"
