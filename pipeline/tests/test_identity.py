"""``player_ref`` on every box-score line (bead tl-y8q).

The page publishes an id for the site owner's roster only, so the resolver
writes a second identity beside ``player_id`` on every line, by four routes
in a fixed order, none of them a spelling guess.  These tests pin the
order, the two roster rules, what falls to ``key`` and why, and that a
page id is never overwritten — the owner side's ``page`` share is the
parser's number, not the resolver's.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.identity import (
    MISS_AMBIGUOUS,
    MISS_NO_NUMBER,
    MISS_NO_ROSTER,
    MISS_ROSTER_NO_IDS,
    MISS_NOT_ON_ROSTER,
    MISS_NUMBER_DIFFERS,
    IdentityReport,
    SeasonSources,
    fold_name,
    fold_surname,
    resolve_matches,
    synthetic_key,
)

ALPHA_HOST = "https://alphaathletics.example"
BETA_HOST = "https://betasports.example"


def _roster(slug: str, host: str, players: list[tuple[str, str, str]]) -> dict:
    return {
        "programme": slug,
        "source_url": f"{host}/sports/mens-soccer/roster/2026",
        "players": [
            {
                "name": name,
                "number": number,
                "source_url": f"{host}/sports/mens-soccer/roster/{fold_name(name)}/{pid}",
            }
            for name, number, pid in players
        ],
    }


def _box(host: str, home_index: int, teams: list[dict]) -> dict:
    return {
        "source_url": f"{host}/sports/mens-soccer/stats/2026/x/boxscore/1",
        "home_index": home_index,
        "teams": teams,
    }


def _line(name: str, number: str | None = None, player_id: str | None = None) -> dict:
    line: dict[str, object] = {"name": name, "shots": 0}
    if number is not None:
        line["number"] = number
    if player_id is not None:
        line["player_id"] = player_id
    return line


def _sources() -> SeasonSources:
    sources = SeasonSources()
    sources.add_rosters(
        {
            "rosters": {
                "alpha": _roster(
                    "alpha",
                    ALPHA_HOST,
                    [
                        ("Iver Høihjelle", "3", "101"),
                        ("Benjamin Hoffmann", "9", "102"),
                        ("Santiago Dominguez Ochoa", "1", "103"),
                        ("Jose Silva", "7", "104"),
                        ("Jose Silva", "17", "105"),
                        ("Marcus Reed", "22", "106"),
                    ],
                ),
                "beta": _roster("beta", BETA_HOST, [("Tom Keeper", "1", "201")]),
            }
        }
    )
    return sources


def test_fold_agrees_on_accents_order_and_case_only() -> None:
    assert (
        fold_name("Høihjelle, Iver") == fold_name("Iver Hoihjelle") == "iverhoihjelle"
    )
    assert fold_name("Hoffman") != fold_name("Hoffmann")
    assert fold_surname("Le Baut, Mylan") == "lebaut"
    assert fold_surname("Mylan Le Baut") == "baut"
    assert synthetic_key("alpha", "Reed, Marcus", "022") == "alpha:marcusreed:22"


def test_the_page_id_is_the_first_route_and_is_never_overwritten() -> None:
    sources = _sources()
    fixture = {
        "id": "sidearm:beta:1",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    # Beta's own site served the box: beta's rows link, alpha's do not.
    match = _box(
        BETA_HOST,
        0,
        [
            {
                "name": "Beta",
                "players": [_line("Tom Keeper", "1", "999")],
                "keepers": [],
            },
            {"name": "Alpha", "players": [_line("Iver Hoihjelle", "3")], "keepers": []},
        ],
    )
    report = resolve_matches({"sidearm:beta:1": match}, [fixture], sources)
    beta_line = match["teams"][0]["players"][0]
    # The roster says 201; the page said 999; the page wins and is kept.
    assert beta_line["player_ref"] == {"id": "999", "source": "page"}
    assert beta_line["player_id"] == "999"
    assert report.counts[("owner", "page")] == 1
    assert match["teams"][1]["players"][0]["player_ref"] == {
        "id": "101",
        "source": "roster",
    }
    assert report.counts[("opponent", "roster")] == 1


def test_the_roster_rules_exact_name_then_number_and_surname_nothing_else() -> None:
    sources = _sources()
    fixture = {
        "id": "sidearm:beta:1",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    lines = [
        _line("Høihjelle, Iver", "3"),  # exact folded name
        _line("Ben Hoffmann", "9"),  # number + surname, first name differs
        _line("Benjamin Hoffman", "9"),  # a spelling away: no guess
        _line("Santiago Dominguez", "1"),  # roster's last word is Ochoa: no hit
        _line("Jose Silva", "7"),  # name ambiguous, number decides
        _line("Jose Silva"),  # name ambiguous, no number to decide
        _line("Mark Reed", "2"),  # surname there, number differs
        _line("Mark Reed"),  # surname there, no number printed
        _line("Nobody Here", "5"),  # not on the roster at all
    ]
    match = _box(
        BETA_HOST,
        0,
        [
            {"name": "Beta", "players": [], "keepers": []},
            {"name": "Alpha", "players": lines, "keepers": []},
        ],
    )
    report = resolve_matches({"sidearm:beta:1": match}, [fixture], sources)
    refs = [line["player_ref"] for line in lines]
    assert refs[0] == {"id": "101", "source": "roster"}
    assert refs[1] == {"id": "102", "source": "roster"}
    assert refs[2] == {"id": "alpha:benjaminhoffman:9", "source": "key"}
    # The rule is number AND surname, and the surname is the last word: a
    # double surname the box shortens is a miss the report names, not a
    # rule the resolver bends.
    assert refs[3] == {"id": "alpha:santiagodominguez:1", "source": "key"}
    assert refs[4] == {"id": "104", "source": "roster"}
    assert refs[5] == {"id": "alpha:josesilva:", "source": "key"}
    assert refs[6] == {"id": "alpha:markreed:2", "source": "key"}
    assert refs[7] == {"id": "alpha:markreed:", "source": "key"}
    assert refs[8] == {"id": "alpha:nobodyhere:5", "source": "key"}
    # The reasons name what a later rule would win, exactly.
    assert report.misses[MISS_AMBIGUOUS] == 1  # Jose Silva without a number
    assert report.misses[MISS_NO_NUMBER] == 1  # Mark Reed without a number
    assert report.misses[MISS_NUMBER_DIFFERS] == 1  # Mark Reed #2
    assert report.misses[MISS_NOT_ON_ROSTER] == 3  # Hoffman, Dominguez, Nobody
    assert report.counts[("opponent", "key")] == 6
    assert report.counts[("opponent", "roster")] == 3


def test_the_twin_box_beats_the_roster_and_a_disagreement_is_a_finding() -> None:
    sources = _sources()
    # Alpha's own box of the same match, served by alpha's site, links alpha's
    # roster — but with an id the roster does not carry for Reed.
    alpha_fixture = {
        "id": "sidearm:alpha:7",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    alpha_box = _box(
        ALPHA_HOST,
        0,
        [
            {"name": "Beta", "players": [_line("Tom Keeper", "1")], "keepers": []},
            {
                "name": "Alpha",
                "players": [
                    _line("Hoihjelle, Iver", "3", "101"),
                    _line("Reed, Marcus", "22", "777"),
                ],
                "keepers": [],
            },
        ],
    )
    sources.add_matches(
        {"matches": {"sidearm:alpha:7": alpha_box}}, {"fixtures": [alpha_fixture]}
    )
    fixture = {
        "id": "sidearm:beta:1",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    lines = [_line("Iver Hoihjelle", "3"), _line("Marcus Reed", "22")]
    match = _box(
        BETA_HOST,
        0,
        [
            {"name": "Beta", "players": [], "keepers": []},
            {"name": "Alpha", "players": lines, "keepers": []},
        ],
    )
    report = resolve_matches({"sidearm:beta:1": match}, [fixture], sources)
    assert lines[0]["player_ref"] == {"id": "101", "source": "twin"}
    assert lines[1]["player_ref"] == {"id": "777", "source": "twin"}
    assert report.counts[("opponent", "twin")] == 2
    assert len(report.disagreements) == 1
    assert "twin box says 777, roster says 106" in report.disagreements[0]


def test_a_box_served_by_a_third_host_is_no_twin() -> None:
    """A twin is the programme's OWN box: ids are per site, so a box some
    other site served says nothing about alpha's ids even if alpha's rows
    on it linked somewhere."""
    sources = _sources()
    other_fixture = {
        "id": "sidearm:alpha:7",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    other_box = _box(
        "https://thirdparty.example",
        0,
        [
            {"name": "Beta", "players": [], "keepers": []},
            {
                "name": "Alpha",
                "players": [_line("Marcus Reed", "22", "777")],
                "keepers": [],
            },
        ],
    )
    sources.add_matches(
        {"matches": {"sidearm:alpha:7": other_box}}, {"fixtures": [other_fixture]}
    )
    assert sources.twins == {}


def test_no_roster_and_no_orientation_fall_to_key_with_their_reasons() -> None:
    sources = _sources()
    fixture = {
        "id": "sidearm:beta:1",
        "date": "2026-09-01",
        "home": "beta",
        "away": "gamma",
    }
    stranger = _line("Some One", "4")
    match = _box(
        BETA_HOST,
        0,
        [
            {"name": "Beta", "players": [], "keepers": []},
            {"name": "Gamma", "players": [stranger], "keepers": []},
        ],
    )
    report = resolve_matches({"sidearm:beta:1": match}, [fixture], sources)
    assert stranger["player_ref"] == {"id": "gamma:someone:4", "source": "key"}
    assert report.misses[MISS_NO_ROSTER] == 1
    # A roster the site published without bio links (PrestoSports) is a
    # roster that can resolve nobody, and the reason says so.
    sources.add_rosters(
        {
            "rosters": {
                "gamma": {
                    "programme": "gamma",
                    "players": [{"name": "Some One", "number": "4"}],
                }
            }
        }
    )
    report = resolve_matches({"sidearm:beta:1": match}, [fixture], sources)
    assert stranger["player_ref"] == {"id": "gamma:someone:4", "source": "key"}
    assert report.misses[MISS_ROSTER_NO_IDS] == 1
    # An unoriented box names no side, so no slug: still a key, reason named.
    unoriented = {
        "source_url": f"{BETA_HOST}/x/boxscore/2",
        "teams": [
            {"name": "A", "players": [_line("Some One", "4")], "keepers": []},
            {"name": "B", "players": [], "keepers": []},
        ],
    }
    fixture2 = {
        "id": "sidearm:beta:2",
        "date": "2026-09-02",
        "home": "beta",
        "away": "alpha",
    }
    report = resolve_matches({"sidearm:beta:2": unoriented}, [fixture2], sources)
    assert unoriented["teams"][0]["players"][0]["player_ref"] == {
        "id": ":someone:4",
        "source": "key",
    }
    assert report.misses["unoriented"] == 1


def test_keepers_are_lines_too_and_a_stale_ref_is_recomputed() -> None:
    sources = _sources()
    fixture = {
        "id": "sidearm:beta:1",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    keeper = _line("Santiago Dominguez Ochoa", "1")
    keeper["player_ref"] = {"id": "stale", "source": "roster"}
    match = _box(
        BETA_HOST,
        0,
        [
            {"name": "Beta", "players": [], "keepers": []},
            {"name": "Alpha", "players": [], "keepers": [keeper]},
        ],
    )
    resolve_matches({"sidearm:beta:1": match}, [fixture], sources)
    assert keeper["player_ref"] == {"id": "103", "source": "roster"}


def test_the_owner_page_share_is_the_parsers_number_not_the_resolvers() -> None:
    """The guard the bead asked for: resolving adds identity to lines that
    had none and takes nothing from lines that had it, so the owner side's
    ``page`` share after the pass equals the share of owner lines the parser
    gave a ``player_id``."""
    sources = _sources()
    fixture = {
        "id": "sidearm:alpha:1",
        "date": "2026-09-01",
        "home": "alpha",
        "away": "beta",
    }
    owner_lines = [
        _line("Iver Hoihjelle", "3", "101"),
        _line("Benjamin Hoffmann", "9", "102"),
        _line("Marcus Reed", "22"),  # the page printed no link for him
    ]
    match = _box(
        ALPHA_HOST,
        0,
        [
            {"name": "Alpha", "players": owner_lines, "keepers": []},
            {"name": "Beta", "players": [_line("Tom Keeper", "1")], "keepers": []},
        ],
    )
    before = sum(1 for line in owner_lines if line.get("player_id")) / len(owner_lines)
    report = resolve_matches({"sidearm:alpha:1": match}, [fixture], sources)
    assert report.share("owner", "page") == before
    assert owner_lines[2]["player_ref"] == {"id": "106", "source": "roster"}
    assert report.summary().startswith(
        "identity: owner side 3 lines: page 2 · roster 1;"
    )


def test_load_disk_reads_the_seasons_sibling_shards(tmp_path: Path) -> None:
    root = tmp_path
    for kind in ("rosters", "matches", "fixtures"):
        (root / "data" / kind).mkdir(parents=True)
    (root / "data" / "rosters" / "2026-men-x.json").write_text(
        json.dumps(
            {
                "rosters": {
                    "alpha": _roster(
                        "alpha", ALPHA_HOST, [("Marcus Reed", "22", "106")]
                    )
                }
            }
        )
    )
    fixture = {
        "id": "sidearm:alpha:7",
        "date": "2026-09-01",
        "home": "beta",
        "away": "alpha",
    }
    (root / "data" / "fixtures" / "2026-men-x.json").write_text(
        json.dumps({"fixtures": [fixture]})
    )
    (root / "data" / "matches" / "2026-men-x.json").write_text(
        json.dumps(
            {
                "matches": {
                    "sidearm:alpha:7": _box(
                        ALPHA_HOST,
                        0,
                        [
                            {"name": "Beta", "players": [], "keepers": []},
                            {
                                "name": "Alpha",
                                "players": [_line("Reed, Marcus", "22", "106")],
                                "keepers": [],
                            },
                        ],
                    )
                }
            }
        )
    )
    # The other gender and season are not this season's sources.
    (root / "data" / "rosters" / "2025-men-x.json").write_text(
        json.dumps({"rosters": {"zeta": {}}})
    )
    sources = SeasonSources()
    sources.load_disk(root, 2026, "men", exclude_matches="y")
    assert set(sources.rosters) == {"alpha"}
    assert ("2026-09-01", "alpha") in sources.twins
    excluded = SeasonSources()
    excluded.load_disk(root, 2026, "men", exclude_matches="x")
    assert excluded.twins == {}
    assert isinstance(IdentityReport().summary(), str)
