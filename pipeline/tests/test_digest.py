"""The digest computes every number a scouting report may cite — so each
aggregate here is pinned to a tiny synthetic season where the right answer
is checkable by hand."""

from __future__ import annotations

import json
from pathlib import Path

import src.digest as digest_module
from src.digest import (
    build_digest,
    discipline,
    head_to_head,
    keepers,
    load_season,
    match_patterns,
    normalize_name,
    roster_shape,
    season_form,
    seasons_held,
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
        "schema": "touchline.fixtures/2",
        "season": season,
        "gender": "men",
        "conference": "TESTCONF",
        "collected_at": f"{season}-08-01T00:00:00+00:00",
        "membership_extrapolated": False,
        "programmes": [
            {
                "slug": "alpha",
                "name": "Alpha University",
                "conference": "TESTCONF",
                "abbr": "AU",
            },
            {
                "slug": "beta",
                "name": "Beta State",
                "conference": "TESTCONF",
                "abbr": "BS",
            },
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
            {
                "id": "x",
                "date": "2025-09-22",
                "home": "alpha",
                "away": "beta",
                "status": "scheduled",
            },
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
    payload = fixtures_payload(
        2025, [fixture, final("2025-09-08", "alpha", "beta", 1, 0, fixture_id="m2")]
    )
    matches = {
        "schema": "touchline.matches/1",
        "matches": {
            "m1": {
                # teams[0] is alpha (away), teams[1] is beta (home).
                "home_index": 1,
                "teams": [
                    {
                        "name": "Alpha",
                        "score": 2,
                        "periods": [1, 0, 1],
                        "shots": 10,
                        "sog": 6,
                        "saves": 3,
                        "corners": 5,
                        "fouls": 9,
                    },
                    {
                        "name": "Beta",
                        "score": 1,
                        "periods": [0, 1, 0],
                        "shots": 14,
                        "sog": 4,
                        "saves": 4,
                        "corners": 2,
                        "fouls": 12,
                    },
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
    assert patterns["goals_by_half"]["against"] == {
        "first": 0,
        "second": 1,
        "overtime": 0,
    }
    assert patterns["goals_by_minute"]["for"]["0-15"] == 1
    assert patterns["goals_by_minute"]["for"]["90+"] == 1
    assert patterns["goals_by_minute"]["against"]["30-45"] == 1
    assert patterns["shots"] == {
        "for": 10,
        "sog_for": 6,
        "against": 14,
        "sog_against": 4,
    }
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
                    {
                        "name": "Sub Keeper",
                        "minutes": 90,
                        "saves": 4,
                        "goals_against": 4,
                    },
                    {
                        "name": "Main Keeper",
                        "minutes": 900,
                        "saves": 45,
                        "goals_against": 9,
                    },
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
                    {
                        "name": "Jose Nunez",
                        "goals": 6,
                        "assists": 2,
                        "points": 14,
                        "minutes": 1200,
                    },
                    {
                        "name": "Jordan Smith",
                        "goals": 0,
                        "assists": 1,
                        "points": 1,
                        "minutes": 300,
                    },
                    {
                        "name": "Old Star",
                        "goals": 4,
                        "assists": 5,
                        "points": 13,
                        "minutes": 1500,
                    },
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
                    [
                        {
                            "name": "Star Player",
                            "player_id": "77",
                            "gp": 15,
                            "goals": 5,
                            "points": 12,
                            "minutes": 1300,
                        }
                    ]
                )
            }
        },
        2025: {
            "teams": {
                "alpha": stats_team(
                    [
                        # The site renamed him but kept the id — the join must hold.
                        {
                            "name": "Star Player Jr.",
                            "player_id": "77",
                            "gp": 16,
                            "goals": 8,
                            "points": 19,
                            "minutes": 1400,
                        },
                        {
                            "name": "Role Player",
                            "gp": 16,
                            "goals": 1,
                            "points": 3,
                            "minutes": 900,
                        },
                    ]
                )
            }
        },
    }
    current = {
        "rosters": {
            "alpha": {
                "players": [
                    {
                        "name": "Star Player Jr.",
                        "position": "Forward",
                        "class_year": "Senior",
                        "number": "9",
                    },
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
    assert [profile["name"] for profile in profiles] == [
        "Star Player Jr.",
        "Role Player",
    ]
    star = profiles[0]
    assert star["position"] == "Forward"
    assert star["class_year"] == "Senior"
    assert [line["season"] for line in star["career"]] == [2024, 2025]
    assert star["career"][0]["goals"] == 5
    assert star["career"][1]["points"] == 19
    role = profiles[1]
    assert [line["season"] for line in role["career"]] == [2025]


# ── availability_flags ───────────────────────────────────────────────────────


def _season_of_matches(dates_and_squads):
    """Build fixtures+matches payloads where alpha plays on each date with the
    given player rows (each row: (name, minutes))."""
    fixtures = []
    matches = {}
    for index, (date, squad) in enumerate(dates_and_squads):
        fixture_id = f"m{index}"
        fixtures.append(final(date, "alpha", "beta", 1, 0, fixture_id=fixture_id))
        matches[fixture_id] = {
            "home_index": 0,
            "teams": [
                {
                    "name": "Alpha",
                    "players": [
                        {"name": name, "minutes": minutes} for name, minutes in squad
                    ],
                },
                {"name": "Beta", "players": []},
            ],
        }
    return fixtures_payload(2025, fixtures), {
        "schema": "touchline.matches/1",
        "matches": matches,
    }


def test_availability_flags_a_regular_who_stops_appearing():
    from src.digest import availability_flags

    ever_present = ("Ever Present", 90)
    squads = [
        ("2025-09-01", [ever_present, ("Hurt Star", 90)]),
        ("2025-09-08", [ever_present, ("Hurt Star", 88)]),
        ("2025-09-15", [ever_present, ("Hurt Star", 90)]),
        ("2025-09-22", [ever_present, ("Late Sub", 12)]),
        ("2025-09-29", [ever_present, ("Late Sub", 8)]),
        ("2025-10-06", [ever_present, ("Late Sub", 15)]),
        ("2025-10-13", [ever_present]),
    ]
    fixtures, matches = _season_of_matches(squads)
    current = {"rosters": {"alpha": roster(["Ever Present", "Hurt Star"])}}
    flags = availability_flags(fixtures, matches, "alpha", current)
    assert [flag["name"] for flag in flags] == ["Hurt Star"]
    flag = flags[0]
    assert flag["appearances"] == 3
    assert flag["minutes"] == 268
    assert flag["last_seen"] == "2025-09-15"
    assert flag["missed_after"] == 4
    assert flag["of_matches"] == 7
    # The scouting gold: he is back on the new roster.
    assert flag["on_current_roster"] is True
    # Late Sub stopped too (missed 1) and Ever Present never stopped — neither flagged.


def test_availability_ignores_fringe_players_and_short_seasons():
    from src.digest import availability_flags

    squads = [
        ("2025-09-01", [("Cameo", 6), ("Regular", 90)]),
        ("2025-09-08", [("Cameo", 4), ("Regular", 90)]),
        ("2025-09-15", [("Cameo", 5), ("Regular", 90)]),
        ("2025-09-22", [("Regular", 90)]),
        ("2025-09-29", [("Regular", 90)]),
        ("2025-10-06", [("Regular", 90)]),
        ("2025-10-13", [("Regular", 90)]),
    ]
    fixtures, matches = _season_of_matches(squads)
    # Cameo stopped appearing, but 3 apps for 15 minutes is rotation noise,
    # not an availability signal.
    assert availability_flags(fixtures, matches, "alpha", None) == []

    # A held season of three matches is too short to infer anything.
    short_fixtures, short_matches = _season_of_matches(squads[:3])
    assert availability_flags(short_fixtures, short_matches, "alpha", None) == []


# ── usage_shifts ─────────────────────────────────────────────────────────────


def test_usage_shift_flags_a_minutes_collapse_for_a_rostered_player():
    from src.digest import usage_shifts

    stats_by_season = {
        2024: {
            "teams": {
                "alpha": stats_team(
                    [
                        {"name": "Was A Starter", "minutes": 1200},
                        {"name": "Still Going", "minutes": 1400},
                        {"name": "Left Anyway", "minutes": 900},
                    ]
                )
            }
        },
        2025: {
            "teams": {
                "alpha": stats_team(
                    [
                        {"name": "Was A Starter", "minutes": 150},
                        {"name": "Still Going", "minutes": 1350},
                    ]
                )
            }
        },
    }
    current = {
        "rosters": {"alpha": roster(["Was A Starter", "Still Going", "Ghosted"])}
    }
    shifts = usage_shifts(stats_by_season, "alpha", 2025, current)
    # Still Going held steady; Left Anyway is off the roster (turnover's story).
    assert [shift["name"] for shift in shifts] == ["Was A Starter"]
    shift = shifts[0]
    assert shift["before"] == {"season": 2024, "minutes": 1200}
    assert shift["after"] == {"season": 2025, "minutes": 150}
    assert shift["drop_pct"] == 88


def test_usage_shift_treats_vanishing_from_stats_as_a_full_collapse():
    from src.digest import usage_shifts

    stats_by_season = {
        2024: {"teams": {"alpha": stats_team([{"name": "Gone Dark", "minutes": 800}])}},
        2025: {"teams": {"alpha": stats_team([])}},
    }
    current = {"rosters": {"alpha": roster(["Gone Dark"])}}
    shifts = usage_shifts(stats_by_season, "alpha", 2025, current)
    assert shifts[0]["after"]["minutes"] == 0
    assert shifts[0]["drop_pct"] == 100
    # Without both seasons of statistics there is nothing to infer from.
    assert usage_shifts({2025: stats_by_season[2025]}, "alpha", 2025, current) == []


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
    path = root / "data" / kind / f"{season}-men-testconf.json"
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
                final(
                    "2025-09-01",
                    "alpha",
                    "beta",
                    2,
                    1,
                    conference_game=True,
                    fixture_id="m1",
                ),
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
                        {
                            "name": "Alpha",
                            "score": 2,
                            "periods": [2, 0],
                            "shots": 9,
                            "sog": 5,
                            "saves": 2,
                            "corners": 4,
                            "fouls": 7,
                        },
                        {
                            "name": "Beta",
                            "score": 1,
                            "periods": [0, 1],
                            "shots": 8,
                            "sog": 3,
                            "saves": 3,
                            "corners": 3,
                            "fouls": 10,
                        },
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
        {
            "collected_at": "2025-08-15T00:00:00+00:00",
            "rosters": {"alpha": roster(["Star", "Leaver"]), "beta": roster(["B One"])},
        },
    )
    write_season(
        root,
        "rosters",
        2026,
        {
            "collected_at": "2026-08-01T00:00:00+00:00",
            "rosters": {
                "alpha": roster(["Star", "Arrival"]),
                "beta": roster(["B One"]),
            },
        },
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
                        {
                            "name": "Star",
                            "player_id": "1",
                            "gp": 2,
                            "goals": 2,
                            "assists": 0,
                            "points": 4,
                            "minutes": 180,
                            "yellow": 1,
                            "red": 0,
                        },
                        {
                            "name": "Leaver",
                            "gp": 2,
                            "goals": 0,
                            "assists": 1,
                            "points": 1,
                            "minutes": 120,
                            "yellow": 0,
                            "red": 1,
                        },
                    ],
                    [{"name": "Wall", "minutes": 180, "saves": 7, "goals_against": 3}],
                ),
                "beta": stats_team(
                    [
                        {
                            "name": "B One",
                            "goals": 1,
                            "points": 2,
                            "minutes": 170,
                            "yellow": 2,
                            "red": 0,
                        }
                    ]
                ),
            },
        },
    )


def test_build_digest_assembles_the_unit(tmp_path):
    seed_home(tmp_path)
    digest = build_digest(
        tmp_path,
        season=2026,
        gender="men",
        conference="TESTCONF",
        focus="alpha",
        generated_at="2026-08-10T00:00:00+00:00",
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
    assert digest["sources"]["stats/2025-men-testconf"] == "2025-11-20T00:00:00+00:00"


def test_season_readers_resolve_only_the_requested_conference_shard(tmp_path):
    seed_home(tmp_path)
    assert seasons_held(tmp_path, "men", "TESTCONF") == [2025, 2026]
    assert seasons_held(tmp_path, "men", "OTHER") == []
    assert load_season(tmp_path, "fixtures", 2026, "men", "TESTCONF") is not None
    assert load_season(tmp_path, "fixtures", 2026, "men", "OTHER") is None


def test_build_digest_refuses_a_home_without_the_season(tmp_path):
    seed_home(tmp_path)
    try:
        build_digest(
            tmp_path,
            season=2030,
            gender="men",
            conference="TESTCONF",
            focus="alpha",
            generated_at="now",
        )
    except ValueError as exc:
        assert "collect that season first" in str(exc)
    else:
        raise AssertionError("expected ValueError for a missing season")


def test_build_digest_refuses_an_unknown_focus(tmp_path):
    seed_home(tmp_path)
    try:
        build_digest(
            tmp_path,
            season=2026,
            gender="men",
            conference="TESTCONF",
            focus="gamma",
            generated_at="now",
        )
    except ValueError as exc:
        assert "gamma" in str(exc)
        assert "alpha" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown focus")


# ── roster_shape ─────────────────────────────────────────────────────────────


def _shape_roster(players: list[dict]) -> dict:
    return {"rosters": {"alpha": {"programme": "alpha", "players": players}}}


def test_roster_shape_groups_position_and_class():
    prev = _shape_roster(
        [
            {"name": "Alan Keep", "position": "Goalkeeper", "class_year": "Jr."},
            {"name": "Bob Back", "position": "Defender", "class_year": "Sr."},
            {"name": "Carl Mid", "position": "Midfielder/Forward", "class_year": "So."},
        ]
    )
    current = _shape_roster(
        [
            {"name": "Alan Keep", "position": "Goalkeeper", "class_year": "Sr."},
            {"name": "New Wall", "position": "Defender", "class_year": "Fr."},
            {"name": "Carl Mid", "position": "Midfielder/Forward", "class_year": "Jr."},
            {"name": "Extra Fwd", "position": "Forward", "class_year": "Fr."},
        ]
    )
    stats = {
        "teams": {
            "alpha": {
                "players": [
                    {"name": "Alan Keep", "minutes": 900},
                    {"name": "Bob Back", "minutes": 1000},
                    {"name": "Carl Mid", "minutes": 500},
                ]
            }
        }
    }
    shape = roster_shape(prev, current, stats, "alpha")
    assert shape["turnover_known"] is True
    gk = shape["by_position"]["GK"]
    assert gk["returning"] == 1 and gk["returning_minutes"] == 900
    assert gk["minutes_share"] == 1.0
    d = shape["by_position"]["D"]
    assert d["newcomers"] == 1 and d["newcomer_freshmen"] == 1
    assert d["returning"] == 0 and d["minutes_share"] == 0.0
    assert shape["by_class"] == {"Sr": 1, "Fr": 2, "Jr": 1}


def test_roster_shape_without_previous_roster_counts_everyone_new():
    current = _shape_roster(
        [{"name": "Solo Player", "position": "F", "class_year": "Freshman"}]
    )
    shape = roster_shape(None, current, None, "alpha")
    assert shape["turnover_known"] is False
    assert shape["by_position"]["F"]["newcomers"] == 1


def test_international_hometown_read():
    assert digest_module._is_international("Orleans, France") is True
    assert digest_module._is_international("Searcy, Ark.") is False
    assert digest_module._is_international("Dallas, TX") is False
    assert digest_module._is_international("London, England") is True
    assert digest_module._is_international("") is None
    assert digest_module._is_international("Unknown") is None


def test_roster_shape_counts_internationals():
    current = _shape_roster(
        [
            {
                "name": "Local Kid",
                "position": "F",
                "class_year": "Fr.",
                "hometown": "Searcy, Ark.",
            },
            {
                "name": "Euro Vet",
                "position": "D",
                "class_year": "Sr.",
                "hometown": "Lyon, France",
            },
            {"name": "No Home", "position": "M", "class_year": "So."},
        ]
    )
    shape = digest_module.roster_shape(None, current, None, "alpha")
    assert shape["international"] == {"total": 1, "newcomers": 1, "unknown": 1}
    assert shape["by_position"]["D"]["international"] == 1


def scoreless_final(date: str, home: str, away: str) -> dict:
    """A modern theme's played-without-score shape: completion published,
    no result ever entered (measured on exhibitions, 2026-08-21)."""
    return {
        "id": f"sidearm:{home}:{date}",
        "date": date,
        "home": home,
        "away": away,
        "status": "final",
        "conference_game": False,
        "match_type": "exhibition",
    }


def test_a_scoreless_final_carries_no_result_to_aggregate():
    # Counting it would invent a 0-0 draw, a clean sheet, and a shutout
    # in one stroke.
    payload = fixtures_payload(
        2026,
        [
            final("2026-09-01", "alpha", "beta", 2, 1, conference_game=True),
            scoreless_final("2026-08-13", "alpha", "outsider"),
        ],
    )
    form = season_form(payload, "alpha")
    assert form["overall"]["played"] == 1
    assert form["overall"]["draws"] == 0
    assert form["clean_sheets"] == 0
    assert form["times_shut_out"] == 0


def test_head_to_head_skips_a_final_without_a_score():
    by_season = {
        2025: fixtures_payload(2025, [final("2025-10-01", "alpha", "beta", 3, 1)]),
        2026: fixtures_payload(2026, [scoreless_final("2026-08-13", "alpha", "beta")]),
    }
    versus = head_to_head(by_season, "alpha", "beta")
    assert (versus["wins"], versus["draws"], versus["losses"]) == (1, 0, 0)
    assert versus["last_meeting"]["season"] == 2025


def test_a_scored_exhibition_never_alters_the_record():
    # Some sites do publish a score for an exhibition; the teams still do
    # not count it, and their own published record stays 0-0 — so must ours.
    payload = fixtures_payload(
        2026,
        [
            final("2026-09-01", "alpha", "beta", 2, 1, conference_game=True),
            {
                **final("2026-08-13", "alpha", "outsider", 4, 0),
                "match_type": "exhibition",
            },
        ],
    )
    form = season_form(payload, "alpha")
    assert form["overall"] == {
        "wins": 1,
        "draws": 0,
        "losses": 0,
        "gf": 2,
        "ga": 1,
        "played": 1,
    }
    assert form["clean_sheets"] == 0


def test_head_to_head_skips_an_exhibition_meeting():
    by_season = {
        2025: fixtures_payload(2025, [final("2025-10-01", "alpha", "beta", 3, 1)]),
        2026: fixtures_payload(
            2026,
            [
                {
                    **final("2026-08-13", "beta", "alpha", 2, 0),
                    "match_type": "exhibition",
                }
            ],
        ),
    }
    versus = head_to_head(by_season, "alpha", "beta")
    assert (versus["wins"], versus["draws"], versus["losses"]) == (1, 0, 0)
    assert versus["last_meeting"]["season"] == 2025
