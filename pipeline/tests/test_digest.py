"""The digest computes every number a scouting report may cite — so each
aggregate here is pinned to a tiny synthetic season where the right answer
is checkable by hand."""

from __future__ import annotations

import json
from pathlib import Path

from src.digest import (
    build_digest,
    discipline,
    head_to_head,
    keepers,
    match_patterns,
    normalize_name,
    season_form,
    top_returning,
    turnover,
    upcoming_vs_focus,
)

# ── Synthetic season builders ────────────────────────────────────────────────
# Two conference programmes (alpha, beta) and one non-member opponent, with
# every published quirk the aggregates must survive: a flipped home_index, a
# "Last, First" name spelling, and box scores missing for one played fixture.


def fixtures_payload(season: int, fixtures: list[dict]) -> dict:
    return {
        "schema": "touchline.fixtures/1",
        "season": season,
        "gender": "men",
        "conference": "TESTCONF",
        "collected_at": f"{season}-08-01T00:00:00+00:00",
        "membership_extrapolated": False,
        "programmes": [
            {"slug": "alpha", "name": "Alpha University", "abbr": "AU"},
            {"slug": "beta", "name": "Beta State", "abbr": "BS"},
        ],
        "fixtures": fixtures,
    }


def final(
    date: str,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    *,
    conference_game: bool = False,
    fixture_id: str | None = None,
) -> dict:
    return {
        "id": fixture_id or f"sidearm:{home}:{date}",
        "date": date,
        "home": home,
        "away": away,
        "status": "final",
        "conference_game": conference_game,
        "home_score": home_score,
        "away_score": away_score,
    }


def roster(players: list[str]) -> dict:
    return {"programme": "alpha", "players": [{"name": name} for name in players]}


def stats_team(players: list[dict], keepers_rows: list[dict] | None = None) -> dict:
    return {"programme": "alpha", "players": players, "keepers": keepers_rows or []}


# ── season_form ──────────────────────────────────────────────────────────────


def test_form_reads_both_home_and_away_finals():
    payload = fixtures_payload(
        2025,
        [
            final("2025-09-01", "alpha", "beta", 2, 1, conference_game=True),
            final("2025-09-08", "beta", "alpha", 3, 3, conference_game=True),
            final("2025-09-15", "outsider", "alpha", 2, 0),
            {"id": "x", "date": "2025-09-22", "home": "alpha", "away": "beta", "status": "scheduled"},
        ],
    )
    form = season_form(payload, "alpha")
    assert form["overall"] == {
        "wins": 1,
        "draws": 1,
        "losses": 1,
        "gf": 5,
        "ga": 6,
        "played": 3,
    }
    assert form["conference"] == {
        "wins": 1,
        "draws": 1,
        "losses": 0,
        "gf": 5,
        "ga": 4,
        "played": 2,
    }
    assert form["clean_sheets"] == 0
    assert form["times_shut_out"] == 1
    assert form["one_goal_games"] == 1


# ── match_patterns ───────────────────────────────────────────────────────────


def test_patterns_attribute_by_home_index_not_column_order():
    """Alpha is the AWAY side of a box score whose teams list the home side
    second — attribution must go through home_index, never position."""
    fixture = final("2025-09-01", "beta", "alpha", 1, 2, fixture_id="m1")
    payload = fixtures_payload(2025, [fixture, final("2025-09-08", "alpha", "beta", 1, 0, fixture_id="m2")])
    matches = {
        "schema": "touchline.matches/1",
        "matches": {
            "m1": {
                # teams[0] is alpha (away), teams[1] is beta (home).
                "home_index": 1,
                "teams": [
                    {"name": "Alpha", "score": 2, "periods": [1, 0, 1], "shots": 10, "sog": 6, "saves": 3, "corners": 5, "fouls": 9},
                    {"name": "Beta", "score": 1, "periods": [0, 1, 0], "shots": 14, "sog": 4, "saves": 4, "corners": 2, "fouls": 12},
                ],
                "scoring": [
                    {"time": "12:30", "team": 0},
                    {"time": "44:59", "team": 1},
                    {"time": "97:10", "team": 0},
                ],
            }
            # m2 was played but its box score was never collected.
        },
    }
    patterns = match_patterns(payload, matches, "alpha")
    assert patterns["matches_counted"] == 1
    assert patterns["played_total"] == 2
    assert patterns["goals_by_half"]["for"] == {"first": 1, "second": 0, "overtime": 1}
    assert patterns["goals_by_half"]["against"] == {"first": 0, "second": 1, "overtime": 0}
    assert patterns["goals_by_minute"]["for"]["0-15"] == 1
    assert patterns["goals_by_minute"]["for"]["90+"] == 1
    assert patterns["goals_by_minute"]["against"]["30-45"] == 1
    assert patterns["shots"] == {"for": 10, "sog_for": 6, "against": 14, "sog_against": 4}
    assert patterns["corners"] == {"for": 5, "against": 2}
    assert patterns["fouls"] == {"committed": 9, "drawn": 12}
    assert patterns["saves"] == {"made": 3, "faced": 4}


# ── discipline / keepers ─────────────────────────────────────────────────────


def test_discipline_and_keepers_come_from_the_stats_page():
    stats = {
        "teams": {
            "alpha": stats_team(
                [
                    {"name": "A One", "yellow": 3, "red": 1},
                    {"name": "A Two", "yellow": 2, "red": 0},
                ],
                [
                    {"name": "Sub Keeper", "minutes": 90, "saves": 4, "goals_against": 4},
                    {"name": "Main Keeper", "minutes": 900, "saves": 45, "goals_against": 9},
                ],
            )
        }
    }
    assert discipline(stats, "alpha") == {"yellow": 5, "red": 1}
    lines = keepers(stats, "alpha")
    assert [line["name"] for line in lines] == ["Main Keeper", "Sub Keeper"]
    assert lines[0]["save_pct"] == 0.833
    assert lines[1]["save_pct"] == 0.5


# ── turnover ─────────────────────────────────────────────────────────────────


def test_turnover_joins_rosters_by_normalized_name():
    prev = {"rosters": {"alpha": roster(["José Núñez", "Smith, Jordan", "Old Star"])}}
    curr = {"rosters": {"alpha": roster(["Jose Nunez", "Jordan Smith", "New Kid"])}}
    prev_stats = {
        "teams": {
            "alpha": stats_team(
                [
                    {"name": "Jose Nunez", "goals": 6, "assists": 2, "points": 14, "minutes": 1200},
                    {"name": "Jordan Smith", "goals": 0, "assists": 1, "points": 1, "minutes": 300},
                    {"name": "Old Star", "goals": 4, "assists": 5, "points": 13, "minutes": 1500},
                ]
            )
        }
    }
    churn = turnover(prev, curr, prev_stats, "alpha")
    assert churn["counts"] == {
        "returning": 2,
        "departed": 1,
        "newcomers": 1,
        "previous_roster": 3,
        "current_roster": 3,
    }
    assert churn["departed"] == ["Old Star"]
    assert churn["newcomers"] == ["New Kid"]
    # Returning production: 6/10 goals, 15/28 points, 1500/3000 minutes.
    assert churn["returning_share"]["goals"] == 0.6
    assert churn["returning_share"]["points"] == round(15 / 28, 3)
    assert churn["returning_share"]["minutes"] == 0.5
    assert churn["departed_leaders"][0]["name"] == "Old Star"


def test_turnover_needs_both_rosters():
    prev = {"rosters": {"alpha": roster(["Someone"])}}
    assert turnover(prev, None, None, "alpha") is None
    assert turnover(prev, {"rosters": {}}, None, "alpha") is None


def test_normalize_name_folds_diacritics_and_comma_order():
    assert normalize_name("José Núñez") == normalize_name("jose nunez")
    assert normalize_name("Smith, Jordan") == normalize_name("Jordan Smith")


# ── top_returning ────────────────────────────────────────────────────────────


def test_top_returning_ranks_by_points_and_builds_career_lines():
    churn = {"returning": ["Star Player", "Role Player"]}
    stats_by_season = {
        2024: {
            "teams": {
                "alpha": stats_team(
                    [{"name": "Star Player", "player_id": "77", "gp": 15, "goals": 5, "points": 12, "minutes": 1300}]
                )
            }
        },
        2025: {
            "teams": {
                "alpha": stats_team(
                    [
                        # The site renamed him but kept the id — the join must hold.
                        {"name": "Star Player Jr.", "player_id": "77", "gp": 16, "goals": 8, "points": 19, "minutes": 1400},
                        {"name": "Role Player", "gp": 16, "goals": 1, "points": 3, "minutes": 900},
                    ]
                )
            }
        },
    }
    current = {
        "rosters": {
            "alpha": {
                "players": [
                    {"name": "Star Player Jr.", "position": "Forward", "class_year": "Senior", "number": "9"},
                    {"name": "Role Player", "position": "Defender"},
                ]
            }
        }
    }
    # "Star Player" appears in 2025 stats as "Star Player Jr." — findable by id
    # once the 2025 row is located by name?  The prev-season row is looked up
    # by the returning name's key, so rank via the row that matches.
    churn = {"returning": ["Star Player Jr.", "Role Player"]}
    profiles = top_returning(churn, stats_by_season, current, "alpha", 2025, limit=5)
    assert [profile["name"] for profile in profiles] == ["Star Player Jr.", "Role Player"]
    star = profiles[0]
    assert star["position"] == "Forward"
    assert star["class_year"] == "Senior"
    assert [line["season"] for line in star["career"]] == [2024, 2025]
    assert star["career"][0]["goals"] == 5
    assert star["career"][1]["points"] == 19
    role = profiles[1]
    assert [line["season"] for line in role["career"]] == [2025]


# ── head_to_head / upcoming ──────────────────────────────────────────────────


def test_head_to_head_reads_from_the_focus_side():
    by_season = {
        2024: fixtures_payload(2024, [final("2024-10-01", "beta", "alpha", 2, 0)]),
        2025: fixtures_payload(
            2025,
            [
                final("2025-10-01", "alpha", "beta", 3, 1),
                final("2025-09-01", "alpha", "outsider", 1, 0),
            ],
        ),
    }
    versus = head_to_head(by_season, "alpha", "beta")
    assert (versus["wins"], versus["draws"], versus["losses"]) == (1, 0, 1)
    assert versus["last_meeting"]["season"] == 2025
    assert versus["last_meeting"]["focus_result"] == "W"
    assert versus["meetings"][0]["score"] == "2-0"
    assert head_to_head(by_season, "alpha", "nobody") is None


def test_upcoming_vs_focus_lists_only_unplayed_meetings():
    payload = fixtures_payload(
        2026,
        [
            final("2026-09-01", "alpha", "beta", 1, 0),
            {
                "id": "y",
                "date": "2026-10-10",
                "home": "beta",
                "away": "alpha",
                "status": "scheduled",
                "time": "19:00",
                "venue": "Beta Field",
            },
        ],
    )
    ahead = upcoming_vs_focus(payload, "alpha", "beta")
    assert len(ahead) == 1
    assert ahead[0]["venue"] == "Beta Field"


# ── build_digest end to end ──────────────────────────────────────────────────


def write_season(root: Path, kind: str, season: int, payload: dict) -> None:
    path = root / "data" / kind / f"{season}-men.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed_home(root: Path) -> None:
    write_season(
        root,
        "fixtures",
        2025,
        fixtures_payload(
            2025,
            [
                final("2025-09-01", "alpha", "beta", 2, 1, conference_game=True, fixture_id="m1"),
                final("2025-09-15", "outsider", "alpha", 2, 0),
            ],
        ),
    )
    write_season(
        root,
        "fixtures",
        2026,
        fixtures_payload(
            2026,
            [
                {
                    "id": "f1",
                    "date": "2026-10-10",
                    "home": "beta",
                    "away": "alpha",
                    "status": "scheduled",
                    "conference_game": True,
                }
            ],
        ),
    )
    write_season(
        root,
        "matches",
        2025,
        {
            "schema": "touchline.matches/1",
            "collected_at": "2025-11-20T00:00:00+00:00",
            "matches": {
                "m1": {
                    "home_index": 0,
                    "teams": [
                        {"name": "Alpha", "score": 2, "periods": [2, 0], "shots": 9, "sog": 5, "saves": 2, "corners": 4, "fouls": 7},
                        {"name": "Beta", "score": 1, "periods": [0, 1], "shots": 8, "sog": 3, "saves": 3, "corners": 3, "fouls": 10},
                    ],
                    "scoring": [
                        {"time": "10:00", "team": 0},
                        {"time": "30:00", "team": 0},
                        {"time": "80:00", "team": 1},
                    ],
                }
            },
        },
    )
    write_season(
        root,
        "rosters",
        2025,
        {"collected_at": "2025-08-15T00:00:00+00:00", "rosters": {"alpha": roster(["Star", "Leaver"]), "beta": roster(["B One"])}},
    )
    write_season(
        root,
        "rosters",
        2026,
        {"collected_at": "2026-08-01T00:00:00+00:00", "rosters": {"alpha": roster(["Star", "Arrival"]), "beta": roster(["B One"])}},
    )
    write_season(
        root,
        "stats",
        2025,
        {
            "collected_at": "2025-11-20T00:00:00+00:00",
            "teams": {
                "alpha": stats_team(
                    [
                        {"name": "Star", "player_id": "1", "gp": 2, "goals": 2, "assists": 0, "points": 4, "minutes": 180, "yellow": 1, "red": 0},
                        {"name": "Leaver", "gp": 2, "goals": 0, "assists": 1, "points": 1, "minutes": 120, "yellow": 0, "red": 1},
                    ],
                    [{"name": "Wall", "minutes": 180, "saves": 7, "goals_against": 3}],
                ),
                "beta": stats_team([{"name": "B One", "goals": 1, "points": 2, "minutes": 170, "yellow": 2, "red": 0}]),
            },
        },
    )


def test_build_digest_assembles_the_unit(tmp_path):
    seed_home(tmp_path)
    digest = build_digest(
        tmp_path, season=2026, gender="men", focus="alpha", generated_at="2026-08-10T00:00:00+00:00"
    )
    assert digest["schema"] == "touchline.digest/1"
    assert digest["conference"] == "TESTCONF"
    assert digest["previous_season"] == 2025
    assert digest["seasons_held"] == [2025, 2026]
    # Focus first, then opponents alphabetically.
    assert list(digest["programmes"]) == ["alpha", "beta"]

    alpha = digest["programmes"]["alpha"]
    assert alpha["last_season"]["overall"]["played"] == 2
    assert alpha["last_season"]["patterns"]["matches_counted"] == 1
    assert alpha["last_season"]["discipline"] == {"yellow": 1, "red": 1}
    assert alpha["last_season"]["keepers"][0]["name"] == "Wall"
    assert alpha["turnover"]["departed"] == ["Leaver"]
    assert alpha["turnover"]["newcomers"] == ["Arrival"]
    assert alpha["top_returning"][0]["name"] == "Star"
    assert "head_to_head" not in alpha

    beta = digest["programmes"]["beta"]
    # The record reads from the focus side: alpha won the only meeting.
    assert beta["head_to_head"]["wins"] == 1
    assert beta["head_to_head"]["losses"] == 0
    assert beta["fixtures_vs_focus"][0]["date"] == "2026-10-10"
    assert "sources" in digest
    assert digest["sources"]["stats/2025-men"] == "2025-11-20T00:00:00+00:00"


def test_build_digest_refuses_a_home_without_the_season(tmp_path):
    seed_home(tmp_path)
    try:
        build_digest(tmp_path, season=2030, gender="men", focus="alpha", generated_at="now")
    except ValueError as exc:
        assert "collect that season first" in str(exc)
    else:
        raise AssertionError("expected ValueError for a missing season")


def test_build_digest_refuses_an_unknown_focus(tmp_path):
    seed_home(tmp_path)
    try:
        build_digest(tmp_path, season=2026, gender="men", focus="gamma", generated_at="now")
    except ValueError as exc:
        assert "gamma" in str(exc)
        assert "alpha" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown focus")
