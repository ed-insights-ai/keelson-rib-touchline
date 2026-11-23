"""Check that the site and the desk show the same numbers.

    python3 -I snapshot/agree.py <desk.json> <figures.json>...

<figures.json> is touchline-ui's `bun scripts/figures.ts` for one build: the
figures the site's pages print for each program it lists (its record and its
player lines). <desk.json> is snapshot/desk-figures.mjs over the `all` index
this run published.

Program figures are the gate: every program the site lists must be in the desk
with the same won, drawn, lost, goals for, goals against and games. Both count
the same games from the same season files, so any difference is a bug in one
of them, and the run exits 1.

Player lines are reported, not gated: the site prints each school's season
stats sheet, while the desk sums its own box-score lines, so the two can differ
where a school's sheet and its box scores disagree.

Writes a Markdown summary to stdout.
"""

from __future__ import annotations

import json
import sys

TEAM_FIELDS = [
    ("won", "won"),
    ("drawn", "drawn"),
    ("lost", "lost"),
    ("goalsFor", "goals_for"),
    ("goalsAgainst", "goals_against"),
    ("played", "played"),
]
PLAYER_FIELDS = [
    ("gp", "gp"),
    ("gs", "gs"),
    ("goals", "goals"),
    ("assists", "assists"),
    ("shots", "shots"),
]
KEEPER_FIELDS = [("gp", "k_gp"), ("saves", "k_saves"), ("goals_against", "k_ga")]

LIMIT = 40  # differences listed before the rest are counted


def load_desk(path: str) -> tuple[dict, dict]:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if doc.get("schema") != "touchline.desk-figures/1":
        raise SystemExit(
            f"not a touchline.desk-figures/1 document: {doc.get('schema')!r}"
        )
    teams: dict = {}
    players: dict = {}
    for r in doc["rows"]:
        key = (r["division"], r["gender"], int(r["season"]), r["team"])
        if r["kind"] == "team":
            teams[key] = r
        else:
            players.setdefault(key, {}).setdefault(r["name"], []).append(r)
    return teams, players


def num(v):
    return None if v is None else int(v)


def compare(teams: dict, players: dict, figures: list[dict]):
    """(program differences, player-line differences, one summary row per build)."""
    team_diffs: list[str] = []
    player_diffs: list[str] = []
    rows: list[str] = []
    for f in figures:
        if f.get("schema") != "touchline.figures/1":
            raise SystemExit(f"not a touchline.figures/1 document: {f.get('schema')!r}")
        d, g, s = f["division"], f["gender"], int(f["season"])
        n_teams = n_lines = n_line_diffs = 0
        for conf in f["conferences"].values():
            for slug, p in conf["programmes"].items():
                key = (d, g, s, slug)
                where = f"{d} {g} {s} {p['name']} ({slug})"
                n_teams += 1
                # A program with no counted results has no row in the desk: zero.
                desk = teams.get(key) or {b: 0 for _, b in TEAM_FIELDS}
                site = p["record"]
                for a, b in TEAM_FIELDS:
                    if num(site[a]) != num(desk[b]):
                        team_diffs.append(
                            f"{where} {a}: site {site[a]}, desk {desk[b]}"
                        )
                roster = players.get(key, {})
                for line in p.get("players", []):
                    if line.get("gp") is None and not line.get("keeper"):
                        continue  # on the roster with no stats line: the page prints no figures
                    n_lines += 1
                    who = f"{where} {line['name']}"
                    found = roster.get(line["name"], [])
                    if len(found) != 1:
                        player_diffs.append(
                            f"{who}: the desk has {len(found)} lines under that name"
                        )
                        n_line_diffs += 1
                        continue
                    row = found[0]
                    before = len(player_diffs)
                    for a, b in PLAYER_FIELDS:
                        if line.get(a) is not None and num(line[a]) != num(row[b]):
                            player_diffs.append(
                                f"{who} {a}: site {line[a]}, desk {row[b]}"
                            )
                    keeper = line.get("keeper")
                    if keeper:
                        for a, b in KEEPER_FIELDS:
                            if keeper.get(a) is not None and num(keeper[a]) != num(
                                row[b]
                            ):
                                player_diffs.append(
                                    f"{who} keeper {a}: site {keeper[a]}, desk {row[b]}"
                                )
                    n_line_diffs += len(player_diffs) > before
        if n_teams == 0:
            # figures.ts skips a conference it cannot load; a build with none
            # compared nothing, which must not read as agreement.
            team_diffs.append(f"{d} {g} {s}: the site's figures list no programs")
        rows.append(f"| {d} | {g} | {s} | {n_teams} | {n_lines} | {n_line_diffs} |")
    return team_diffs, player_diffs, rows


def listed(diffs: list[str]) -> list[str]:
    out = [f"- {x}" for x in diffs[:LIMIT]]
    if len(diffs) > LIMIT:
        out.append(f"- ... and {len(diffs) - LIMIT} more")
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    teams, players = load_desk(argv[1])
    figures = []
    for path in argv[2:]:
        with open(path, encoding="utf-8") as fh:
            figures.append(json.load(fh))
    if not figures:
        raise SystemExit("no site figures given")
    team_diffs, player_diffs, rows = compare(teams, players, figures)
    out = [
        "| division | gender | season | programs | player lines | lines that differ |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]
    if team_diffs:
        out += [
            f"**{len(team_diffs)} program figure(s) differ between the site and the desk:**",
            "",
        ]
        out += listed(team_diffs) + [""]
    else:
        out += ["Every program's record, goals and games agree.", ""]
    if player_diffs:
        out += [
            f"<details><summary>{len(player_diffs)} player-line difference(s), reported only "
            "(the site prints schools' stats sheets, the desk sums box scores)</summary>",
            "",
            *listed(player_diffs),
            "",
            "</details>",
        ]
    print("\n".join(out))
    return 1 if team_diffs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
