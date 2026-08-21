"""Deterministic scouting digest — every number a report may cite.

The digest is the numeric record a generated scouting report is allowed to
quote: season form, box-score patterns, roster turnover, career lines, and
head-to-head history, computed here from the data home's season files and
nowhere else.  A language model writes prose *around* these figures; it never
produces one.  One wrong number in front of a coach ends the conversation, so
the boundary is absolute: if a figure is not in the digest, the report cannot
say it.

Everything is parameterized by season, gender, conference, and a focus
programme. The conference selects the storage shard; the fixtures file remains
the authority for its display label.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from src.sidearm_live import programme_slug

DIGEST_SCHEMA = "touchline.digest/1"

#: Fifteen-minute scoring bands, plus everything past regulation.
MINUTE_BANDS = ("0-15", "15-30", "30-45", "45-60", "60-75", "75-90", "90+")

#: Career-line fields lifted from a season's published statistics row.
CAREER_FIELDS = (
    "gp",
    "gs",
    "minutes",
    "goals",
    "assists",
    "points",
    "shots",
    "sog",
    "yellow",
    "red",
)


def normalize_name(name: str) -> str:
    """Fold a published player name to a join key.

    Sites vary capitalization, spacing, and diacritics between the roster
    page and the statistics page for the same player; a "Last, First" form is
    folded to first-last order so both spellings meet.
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    if "," in text:
        last, _, first = text.partition(",")
        text = f"{first} {last}"
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _season_path(
    root: Path, kind: str, season: int, gender: str, conference: str
) -> Path:
    return (
        root
        / "data"
        / kind
        / f"{season}-{gender}-{programme_slug(conference)}.json"
    )


def load_season(
    root: Path, kind: str, season: int, gender: str, conference: str
) -> dict | None:
    """One season file as a dict, or None when the home does not hold it."""
    path = _season_path(root, kind, season, gender, conference)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def seasons_held(root: Path, gender: str, conference: str) -> list[int]:
    """Every season the home holds for one conference shard, ascending."""
    directory = root / "data" / "fixtures"
    shard = programme_slug(conference)
    pattern = re.compile(
        rf"^(\d{{4}})-{re.escape(gender)}-{re.escape(shard)}\.json$"
    )
    found = []
    if directory.is_dir():
        for entry in directory.iterdir():
            matched = pattern.match(entry.name)
            if matched:
                found.append(int(matched.group(1)))
    return sorted(found)


def _has_score(fixture: dict) -> bool:
    return isinstance(fixture.get("home_score"), int) and isinstance(
        fixture.get("away_score"), int
    )


def _finals(fixtures_payload: dict, slug: str) -> list[dict]:
    """Result-bearing finals only.

    A modern theme publishes completion without a score when no result was
    ever entered (measured on exhibitions).  Such a final carries nothing to
    aggregate — counting it would invent a 0-0 draw, a clean sheet, and a
    shutout at once — so every result computation starts from finals that
    actually have a score pair.
    """
    return [
        fixture
        for fixture in fixtures_payload.get("fixtures") or []
        if fixture.get("status") == "final"
        and _has_score(fixture)
        and slug in (fixture.get("home"), fixture.get("away"))
    ]


def _scored_conceded(fixture: dict, slug: str) -> tuple[int, int]:
    home_score = int(fixture.get("home_score") or 0)
    away_score = int(fixture.get("away_score") or 0)
    if fixture.get("home") == slug:
        return home_score, away_score
    return away_score, home_score


def season_form(fixtures_payload: dict, slug: str) -> dict:
    """Win/draw/loss form from the season's final fixtures.

    Fixtures cover the whole season, including games without a collected box
    score, so the record is computed here rather than from match details.
    """

    def tally(rows: list[dict]) -> dict:
        record = {"wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0}
        for fixture in rows:
            scored, conceded = _scored_conceded(fixture, slug)
            record["gf"] += scored
            record["ga"] += conceded
            if scored > conceded:
                record["wins"] += 1
            elif scored < conceded:
                record["losses"] += 1
            else:
                record["draws"] += 1
        return record

    finals = _finals(fixtures_payload, slug)
    overall = tally(finals)
    overall["played"] = len(finals)
    conference_rows = [f for f in finals if f.get("conference_game")]
    conference = tally(conference_rows)
    conference["played"] = len(conference_rows)
    return {
        "overall": overall,
        "conference": conference,
        "clean_sheets": sum(
            1 for f in finals if _scored_conceded(f, slug)[1] == 0
        ),
        "times_shut_out": sum(
            1 for f in finals if _scored_conceded(f, slug)[0] == 0
        ),
        "one_goal_games": sum(
            1
            for f in finals
            if abs(_scored_conceded(f, slug)[0] - _scored_conceded(f, slug)[1]) == 1
        ),
    }


def _minute_band(time_text: str) -> str | None:
    matched = re.match(r"^(\d+):(\d{2})$", time_text.strip())
    if not matched:
        return None
    minute = int(matched.group(1))
    if minute >= 90:
        return MINUTE_BANDS[6]
    return MINUTE_BANDS[minute // 15]


def _team_slugs(fixture: dict, match: dict) -> list[str]:
    """Map each ``teams`` index of a box score to its programme slug.

    ``home_index`` says which entry is the home side; the fixture row names
    the slugs.  Column position is never trusted for identity.
    """
    home_index = int(match.get("home_index") or 0)
    slugs = ["", ""]
    slugs[home_index] = str(fixture.get("home") or "")
    slugs[1 - home_index] = str(fixture.get("away") or "")
    return slugs


def match_patterns(fixtures_payload: dict, matches_payload: dict, slug: str) -> dict:
    """Scoring and pressure patterns across the season's collected box scores.

    Box-score coverage can trail the fixture list, so ``matches_counted`` and
    ``played_total`` travel with the numbers — a report must caveat patterns
    built on partial coverage.
    """
    matches = matches_payload.get("matches") or {}
    finals = _finals(fixtures_payload, slug)

    empty_bands = dict.fromkeys(MINUTE_BANDS, 0)
    patterns = {
        "matches_counted": 0,
        "played_total": len(finals),
        "goals_by_half": {
            "for": {"first": 0, "second": 0, "overtime": 0},
            "against": {"first": 0, "second": 0, "overtime": 0},
        },
        "goals_by_minute": {
            "for": dict(empty_bands),
            "against": dict(empty_bands),
        },
        "shots": {"for": 0, "sog_for": 0, "against": 0, "sog_against": 0},
        "corners": {"for": 0, "against": 0},
        "fouls": {"committed": 0, "drawn": 0},
        "saves": {"made": 0, "faced": 0},
    }

    for fixture in finals:
        match = matches.get(str(fixture.get("id")))
        if not isinstance(match, dict):
            continue
        slugs = _team_slugs(fixture, match)
        if slug not in slugs:
            continue
        patterns["matches_counted"] += 1
        own = slugs.index(slug)
        other = 1 - own

        teams = match.get("teams") or []
        for index, side in (("for", own), ("against", other)):
            if side >= len(teams):
                continue
            periods = [int(value or 0) for value in teams[side].get("periods") or []]
            halves = patterns["goals_by_half"][index]
            if len(periods) >= 1:
                halves["first"] += periods[0]
            if len(periods) >= 2:
                halves["second"] += periods[1]
            halves["overtime"] += sum(periods[2:])
        if len(teams) == 2:
            patterns["shots"]["for"] += int(teams[own].get("shots") or 0)
            patterns["shots"]["sog_for"] += int(teams[own].get("sog") or 0)
            patterns["shots"]["against"] += int(teams[other].get("shots") or 0)
            patterns["shots"]["sog_against"] += int(teams[other].get("sog") or 0)
            patterns["corners"]["for"] += int(teams[own].get("corners") or 0)
            patterns["corners"]["against"] += int(teams[other].get("corners") or 0)
            patterns["fouls"]["committed"] += int(teams[own].get("fouls") or 0)
            patterns["fouls"]["drawn"] += int(teams[other].get("fouls") or 0)
            patterns["saves"]["made"] += int(teams[own].get("saves") or 0)
            patterns["saves"]["faced"] += int(teams[other].get("saves") or 0)

        for goal in match.get("scoring") or []:
            band = _minute_band(str(goal.get("time") or ""))
            if band is None:
                continue
            team_index = goal.get("team")
            if team_index not in (0, 1):
                continue
            index = "for" if team_index == own else "against"
            patterns["goals_by_minute"][index][band] += 1

    return patterns


def discipline(stats_payload: dict, slug: str) -> dict:
    """Season card totals from the published statistics page.

    The statistics page aggregates the whole season, including games whose
    box scores were never collected — so cards come from here, not from
    counting card events across held matches.
    """
    team = (stats_payload.get("teams") or {}).get(slug) or {}
    players = team.get("players") or []
    return {
        "yellow": sum(int(player.get("yellow") or 0) for player in players),
        "red": sum(int(player.get("red") or 0) for player in players),
    }


def keepers(stats_payload: dict, slug: str) -> list[dict]:
    """Goalkeeper season lines, save percentage derived, most minutes first."""
    team = (stats_payload.get("teams") or {}).get(slug) or {}
    lines = []
    for keeper in team.get("keepers") or []:
        saves = int(keeper.get("saves") or 0)
        goals_against = int(keeper.get("goals_against") or 0)
        line = {
            key: keeper[key]
            for key in ("name", "minutes", "saves", "goals_against", "gp", "shutouts")
            if key in keeper
        }
        faced = saves + goals_against
        if faced:
            line["save_pct"] = round(saves / faced, 3)
        lines.append(line)
    return sorted(lines, key=lambda line: -int(line.get("minutes") or 0))


def _roster_names(rosters_payload: dict | None, slug: str) -> dict[str, str]:
    """Normalized name → published name for one programme's roster."""
    roster = ((rosters_payload or {}).get("rosters") or {}).get(slug) or {}
    names: dict[str, str] = {}
    for player in roster.get("players") or []:
        name = str(player.get("name") or "").strip()
        if name:
            names.setdefault(normalize_name(name), name)
    return names


#: Published position strings, folded to four groups a coach thinks in.
POSITION_BUCKETS = (
    ("GK", ("goalkeeper", "keeper", "gk")),
    ("D", ("defender", "defense", "defence", "back", "d")),
    ("M", ("midfielder", "midfield", "mf", "m")),
    ("F", ("forward", "striker", "attacker", "fw", "f")),
)

CLASS_BUCKETS = (
    ("Fr", ("fr", "freshman", "r-fr", "rs fr", "rfr", "redshirt freshman")),
    ("So", ("so", "sophomore", "r-so", "rs so")),
    ("Jr", ("jr", "junior", "r-jr", "rs jr")),
    ("Sr", ("sr", "senior", "r-sr", "rs sr", "gr", "graduate", "5th")),
)


def _position_bucket(raw: str | None) -> str:
    """First listed position wins; combos like 'Midfielder/Forward' fold to
    the first role."""
    first = str(raw or "").strip().lower().replace("/", " ").split()
    head = first[0].rstrip(".") if first else ""
    for bucket, words in POSITION_BUCKETS:
        if head in words:
            return bucket
    return "?"


#: US state names and AP/postal abbreviations, folded, for hometown reads.
_US_MARKERS = {
    marker.replace(".", "").casefold()
    for marker in (
        "Ala", "Alaska", "Ariz", "Ark", "Calif", "Colo", "Conn", "Del", "Fla",
        "Ga", "Hawaii", "Idaho", "Ill", "Ind", "Iowa", "Kan", "Ky", "La",
        "Maine", "Md", "Mass", "Mich", "Minn", "Miss", "Mo", "Mont", "Neb",
        "Nev", "NH", "NJ", "NM", "NY", "NC", "ND", "Ohio", "Okla", "Ore",
        "Pa", "RI", "SC", "SD", "Tenn", "Texas", "Utah", "Vt", "Va", "Wash",
        "WVa", "Wis", "Wyo", "DC",
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
        "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
        "MN", "MS", "MO", "MT", "NE", "NV", "OK", "OR", "PA", "TN", "TX",
        "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "Alabama", "Arizona", "Arkansas", "California", "Colorado",
        "Connecticut", "Delaware", "Florida", "Georgia", "Illinois",
        "Indiana", "Kansas", "Kentucky", "Louisiana", "Maryland",
        "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
        "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
        "New Mexico", "New York", "North Carolina", "North Dakota",
        "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
        "South Carolina", "South Dakota", "Tennessee", "Texas", "Vermont",
        "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
        "USA", "US",
    )
}


def _is_international(hometown: str | None) -> bool | None:
    """Read a published hometown as domestic or international.

    ``"Orleans, France"`` → True; ``"Searcy, Ark."`` → False; an empty or
    single-token hometown → None (unknown, counted separately — a missing
    hometown is not evidence of anything).
    """
    text = str(hometown or "").strip()
    if "," not in text:
        return None
    tail = text.rsplit(",", 1)[1].strip().replace(".", "")
    if not tail:
        return None
    return tail.casefold() not in _US_MARKERS


def _class_bucket(raw: str | None) -> str:
    text = str(raw or "").strip().lower().rstrip(".")
    for bucket, words in CLASS_BUCKETS:
        if text in words:
            return bucket
    return "?"


def roster_shape(
    prev_rosters: dict | None,
    current_rosters: dict | None,
    prev_stats: dict | None,
    slug: str,
) -> dict | None:
    """The squad's makeup by position group and class year.

    Answers the questions a coach grounds a preseason plan in: where is the
    roster experienced, where is it new, and how much of last season's
    playing time returns at each position. Positions come from the roster a
    player is listed on; last-season minutes join by normalized name.
    """
    current = ((current_rosters or {}).get("rosters") or {}).get(slug) or {}
    players = current.get("players") or []
    if not players:
        return None
    previous_names = set(_roster_names(prev_rosters, slug)) if prev_rosters else set()
    prev_players = (((prev_rosters or {}).get("rosters") or {}).get(slug) or {}).get(
        "players"
    ) or []
    prev_position = {
        normalize_name(str(p.get("name") or "")): _position_bucket(p.get("position"))
        for p in prev_players
    }
    minutes_by_name = {
        normalize_name(str(p.get("name") or "")): int(p.get("minutes") or 0)
        for p in (((prev_stats or {}).get("teams") or {}).get(slug) or {}).get("players")
        or []
    }

    by_position: dict[str, dict] = {}
    by_class: dict[str, int] = {}
    international = {"total": 0, "newcomers": 0, "unknown": 0}
    for player in players:
        key = normalize_name(str(player.get("name") or ""))
        pos = _position_bucket(player.get("position"))
        cls = _class_bucket(player.get("class_year"))
        row = by_position.setdefault(
            pos,
            {
                "returning": 0,
                "newcomers": 0,
                "newcomer_freshmen": 0,
                "returning_minutes": 0,
                "classes": {"returning": {}, "newcomers": {}},
            },
        )
        if previous_names and key in previous_names:
            status = "returning"
            row["returning"] += 1
            row["returning_minutes"] += minutes_by_name.get(key, 0)
        else:
            status = "newcomers"
            row["newcomers"] += 1
            if cls == "Fr":
                row["newcomer_freshmen"] += 1
        group = row["classes"][status]
        group[cls] = group.get(cls, 0) + 1
        by_class[cls] = by_class.get(cls, 0) + 1
        intl = _is_international(player.get("hometown"))
        if intl is True:
            international["total"] += 1
            row["international"] = row.get("international", 0) + 1
            intl_bucket = row.setdefault(
                "intl_classes", {"returning": {}, "newcomers": {}}
            )[status]
            intl_bucket[cls] = intl_bucket.get(cls, 0) + 1
            if status == "newcomers":
                international["newcomers"] += 1
        elif intl is None:
            international["unknown"] += 1

    if minutes_by_name and prev_position:
        prev_minutes: dict[str, int] = {}
        for key, minutes in minutes_by_name.items():
            bucket = prev_position.get(key, "?")
            prev_minutes[bucket] = prev_minutes.get(bucket, 0) + minutes
        for pos, row in by_position.items():
            held = prev_minutes.get(pos)
            row["minutes_share"] = (
                round(row["returning_minutes"] / held, 3) if held else None
            )

    return {
        "by_position": by_position,
        "by_class": by_class,
        "international": international,
        "turnover_known": bool(previous_names),
    }


def turnover(
    prev_rosters: dict | None,
    current_rosters: dict | None,
    prev_stats: dict | None,
    slug: str,
) -> dict | None:
    """Who returns, who left, and how much of last season walks back in.

    Joined on normalized names between the two published rosters; the shares
    weight last season's production (goals, assists, points, minutes) by
    whether its author is on the new roster.
    """
    previous = _roster_names(prev_rosters, slug)
    current = _roster_names(current_rosters, slug)
    if not previous or not current:
        return None

    returning_keys = sorted(set(previous) & set(current))
    departed_keys = sorted(set(previous) - set(current))
    newcomer_keys = sorted(set(current) - set(previous))

    result = {
        "returning": [previous[key] for key in returning_keys],
        "departed": [previous[key] for key in departed_keys],
        "newcomers": [current[key] for key in newcomer_keys],
        "counts": {
            "returning": len(returning_keys),
            "departed": len(departed_keys),
            "newcomers": len(newcomer_keys),
            "previous_roster": len(previous),
            "current_roster": len(current),
        },
    }

    team = ((prev_stats or {}).get("teams") or {}).get(slug) or {}
    players = team.get("players") or []
    if players:
        returning = set(returning_keys)
        shares = {}
        for field in ("goals", "assists", "points", "minutes"):
            total = sum(int(player.get(field) or 0) for player in players)
            kept = sum(
                int(player.get(field) or 0)
                for player in players
                if normalize_name(str(player.get("name") or "")) in returning
            )
            shares[field] = round(kept / total, 3) if total else None
        result["returning_share"] = shares
        departed = set(departed_keys)
        leaders = [
            player
            for player in players
            if normalize_name(str(player.get("name") or "")) in departed
        ]
        leaders.sort(
            key=lambda player: (
                -int(player.get("points") or 0),
                -int(player.get("minutes") or 0),
            )
        )
        result["departed_leaders"] = [
            {
                "name": player.get("name"),
                "goals": int(player.get("goals") or 0),
                "assists": int(player.get("assists") or 0),
                "points": int(player.get("points") or 0),
                "minutes": int(player.get("minutes") or 0),
            }
            for player in leaders[:3]
            if int(player.get("points") or 0) or int(player.get("minutes") or 0)
        ]
    return result


def _stat_row(stats_payload: dict | None, slug: str, key: str, player_id: str | None) -> dict | None:
    team = ((stats_payload or {}).get("teams") or {}).get(slug) or {}
    for player in team.get("players") or []:
        if player_id and str(player.get("player_id") or "") == player_id:
            return player
    for player in team.get("players") or []:
        if normalize_name(str(player.get("name") or "")) == key:
            return player
    return None


def top_returning(
    turnover_result: dict | None,
    stats_by_season: dict[int, dict | None],
    current_rosters: dict | None,
    slug: str,
    prev_season: int,
    limit: int = 5,
) -> list[dict]:
    """The returning players a coach will actually ask about.

    Ranked by last season's points then minutes; each carries a career line
    per held season, joined by the site's stable player id where published
    and by normalized name otherwise.
    """
    if not turnover_result:
        return []
    prev_stats = stats_by_season.get(prev_season)
    roster = ((current_rosters or {}).get("rosters") or {}).get(slug) or {}
    bios = {
        normalize_name(str(player.get("name") or "")): player
        for player in roster.get("players") or []
    }

    ranked = []
    for name in turnover_result["returning"]:
        key = normalize_name(name)
        last = _stat_row(prev_stats, slug, key, None)
        if last is None:
            continue
        ranked.append((key, name, last))
    ranked.sort(
        key=lambda item: (
            -int(item[2].get("points") or 0),
            -int(item[2].get("minutes") or 0),
        )
    )

    profiles = []
    for key, name, last in ranked[:limit]:
        player_id = str(last.get("player_id") or "") or None
        career = []
        for season in sorted(stats_by_season):
            row = _stat_row(stats_by_season[season], slug, key, player_id)
            if row is None:
                continue
            career.append(
                {
                    "season": season,
                    **{
                        field: int(row.get(field) or 0)
                        for field in CAREER_FIELDS
                        if field in row
                    },
                }
            )
        bio = bios.get(key) or {}
        profiles.append(
            {
                "name": name,
                **{
                    field: bio[field]
                    for field in ("position", "class_year", "number", "hometown")
                    if bio.get(field)
                },
                "career": career,
            }
        )
    return profiles


#: A player must have played this much before stopping to be worth flagging —
#: either sustained minutes or a real run of appearances; a few cameo minutes
#: disappearing is rotation noise, not an availability signal.
AVAILABILITY_MIN_APPS = 5
AVAILABILITY_MIN_MINUTES = 180
#: ...and this many held matches must remain after their last appearance.
AVAILABILITY_MIN_MISSED = 3


def availability_flags(
    fixtures_payload: dict,
    matches_payload: dict,
    slug: str,
    current_rosters: dict | None,
) -> list[dict]:
    """Players with large unexplained holes in their participation — INFERRED.

    Built from per-match minutes in held box scores.  Two shapes are flagged:
    ``stopped`` (a regular who vanishes and never returns — the season-ending
    shape) and ``gap`` (played, missed a run of matches, came back — the
    injury-and-recovery shape).  The record cannot distinguish injury from
    transfer, discipline, or redshirt, so the digest reports only the pattern
    (apps, starts, minutes, the dates around the hole) and never the cause.
    Consumers must label conclusions drawn from this as projected.
    """
    matches = matches_payload.get("matches") or {}
    timeline: list[tuple[str, dict]] = []
    for fixture in sorted(
        _finals(fixtures_payload, slug), key=lambda row: str(row.get("date"))
    ):
        match = matches.get(str(fixture.get("id")))
        if not isinstance(match, dict):
            continue
        slugs = _team_slugs(fixture, match)
        if slug not in slugs:
            continue
        team = (match.get("teams") or [])[slugs.index(slug)]
        timeline.append((str(fixture.get("date")), team))

    if len(timeline) <= AVAILABILITY_MIN_MISSED:
        return []

    players: dict[str, dict] = {}
    for index, (date, team) in enumerate(timeline):
        for row in team.get("players") or []:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            key = normalize_name(name)
            entry = players.setdefault(
                key,
                {"name": name, "appearances": [], "starts": 0, "minutes": 0},
            )
            entry["appearances"].append(index)
            entry["minutes"] += int(row.get("minutes") or 0)
            if row.get("started"):
                entry["starts"] += 1

    returning = set(_roster_names(current_rosters, slug)) if current_rosters else set()
    flags = []
    total = len(timeline)
    for key, entry in players.items():
        played = entry["appearances"]
        if (
            len(played) < AVAILABILITY_MIN_APPS
            and entry["minutes"] < AVAILABILITY_MIN_MINUTES
        ):
            continue

        # The tail: a player who never came back.
        tail_missed = total - 1 - played[-1]

        # Interior gaps: the largest run of team matches missed between two of
        # the player's own appearances — the "played, vanished, returned"
        # shape a season-interrupting injury leaves behind.
        gap_missed, gap_out, gap_back = 0, -1, -1
        for previous, current in zip(played, played[1:]):
            run = current - previous - 1
            if run > gap_missed:
                gap_missed, gap_out, gap_back = run, previous, current

        if tail_missed >= AVAILABILITY_MIN_MISSED and tail_missed >= gap_missed:
            kind, detail = "stopped", {
                "last_seen": timeline[played[-1]][0],
                "missed_after": tail_missed,
            }
        elif gap_missed >= AVAILABILITY_MIN_MISSED:
            kind, detail = "gap", {
                "out_after": timeline[gap_out][0],
                "back_on": timeline[gap_back][0],
                "missed": gap_missed,
            }
        else:
            continue

        flags.append(
            {
                "name": entry["name"],
                "appearances": len(played),
                "starts": entry["starts"],
                "minutes": entry["minutes"],
                "kind": kind,
                **detail,
                "of_matches": total,
                "on_current_roster": key in returning if current_rosters else None,
            }
        )
    flags.sort(key=lambda flag: (-flag["starts"], -flag["minutes"], flag["name"]))
    return flags


#: A season counts as "a lot of playing time" above this many minutes…
USAGE_DROP_FLOOR = 600
#: …and the next season is a collapse at or below this fraction of it.
USAGE_DROP_RATIO = 0.5


def usage_shifts(
    stats_by_season: dict[int, dict | None],
    slug: str,
    prev_season: int,
    current_rosters: dict | None,
) -> list[dict]:
    """Returning players whose minutes collapsed year over year — INFERRED.

    A player with heavy minutes two seasons ago and a fraction of them last
    season, still on the new roster, is a theory generator: injury year,
    position battle lost, academic redshirt — the record cannot say which.
    Only players on the current published roster are reported; departures
    are the turnover section's story.  Consumers must present conclusions
    from this as possible analysis, labeled projected.
    """
    before_stats = stats_by_season.get(prev_season - 1)
    after_stats = stats_by_season.get(prev_season)
    if before_stats is None or after_stats is None or current_rosters is None:
        return []
    on_roster = set(_roster_names(current_rosters, slug))
    if not on_roster:
        return []

    team_before = ((before_stats.get("teams") or {}).get(slug) or {}).get("players") or []
    shifts = []
    for row in team_before:
        minutes_before = int(row.get("minutes") or 0)
        if minutes_before < USAGE_DROP_FLOOR:
            continue
        name = str(row.get("name") or "").strip()
        key = normalize_name(name)
        if key not in on_roster:
            continue
        after_row = _stat_row(
            after_stats, slug, key, str(row.get("player_id") or "") or None
        )
        if after_row is None:
            # Not in last season's statistics at all — the strongest form of
            # the same signal for a player still on the roster.
            minutes_after = 0
        else:
            minutes_after = int(after_row.get("minutes") or 0)
        if minutes_after > minutes_before * USAGE_DROP_RATIO:
            continue
        shifts.append(
            {
                "name": name,
                "before": {"season": prev_season - 1, "minutes": minutes_before},
                "after": {"season": prev_season, "minutes": minutes_after},
                "drop_pct": round((1 - minutes_after / minutes_before) * 100),
            }
        )
    shifts.sort(key=lambda shift: -shift["drop_pct"])
    return shifts


def head_to_head(
    fixtures_by_season: dict[int, dict | None], focus: str, slug: str
) -> dict | None:
    """Every held meeting between the focus programme and one opponent.

    The record reads from the focus side: ``wins`` are focus wins.
    """
    meetings = []
    for season in sorted(fixtures_by_season):
        payload = fixtures_by_season[season]
        for fixture in (payload or {}).get("fixtures") or []:
            if fixture.get("status") != "final" or not _has_score(fixture):
                continue
            pair = {fixture.get("home"), fixture.get("away")}
            if pair != {focus, slug}:
                continue
            scored, conceded = _scored_conceded(fixture, focus)
            meetings.append(
                {
                    "season": season,
                    "date": fixture.get("date"),
                    "home": fixture.get("home"),
                    "away": fixture.get("away"),
                    "score": f"{fixture.get('home_score')}-{fixture.get('away_score')}",
                    "focus_result": "W" if scored > conceded else "L" if scored < conceded else "D",
                }
            )
    if not meetings:
        return None
    meetings.sort(key=lambda meeting: str(meeting["date"]))
    results = [meeting["focus_result"] for meeting in meetings]
    return {
        "wins": results.count("W"),
        "draws": results.count("D"),
        "losses": results.count("L"),
        "meetings": meetings,
        "last_meeting": meetings[-1],
    }


def upcoming_vs_focus(fixtures_payload: dict, focus: str, slug: str) -> list[dict]:
    """This season's still-unplayed meetings between the focus and one opponent."""
    rows = []
    for fixture in fixtures_payload.get("fixtures") or []:
        if fixture.get("status") == "final":
            continue
        if {fixture.get("home"), fixture.get("away")} != {focus, slug}:
            continue
        rows.append(
            {
                key: fixture[key]
                for key in ("date", "home", "away", "time", "venue", "status")
                if key in fixture
            }
        )
    return sorted(rows, key=lambda row: str(row.get("date")))


def build_digest(
    root: Path,
    *,
    season: int,
    gender: str,
    conference: str,
    focus: str,
    generated_at: str,
) -> dict:
    """Assemble one conference shard's digest around a focus programme.

    Raises ``ValueError`` when the home lacks the target season's fixtures or
    the focus is not one of its programmes — the caller should collect first,
    not guess.
    """
    current_fixtures = load_season(root, "fixtures", season, gender, conference)
    if current_fixtures is None:
        raise ValueError(
            f"no fixtures for {season} {gender} {conference} in this data home — "
            "collect that season first"
        )
    programmes = {
        str(entry.get("slug")): entry
        for entry in current_fixtures.get("programmes") or []
    }
    if focus not in programmes:
        known = ", ".join(sorted(programmes)) or "none"
        raise ValueError(
            f"focus '{focus}' is not among this season's programmes ({known})"
        )

    held = seasons_held(root, gender, conference)
    previous_candidates = [year for year in held if year < season]
    prev_season = max(previous_candidates) if previous_candidates else None

    fixtures_by_season = {
        year: load_season(root, "fixtures", year, gender, conference)
        for year in held
    }
    stats_by_season = {
        year: load_season(root, "stats", year, gender, conference) for year in held
    }
    current_rosters = load_season(root, "rosters", season, gender, conference)
    prev_rosters = (
        load_season(root, "rosters", prev_season, gender, conference)
        if prev_season is not None
        else None
    )
    prev_stats = stats_by_season.get(prev_season) if prev_season is not None else None
    prev_fixtures = (
        fixtures_by_season.get(prev_season) if prev_season is not None else None
    )
    prev_matches = (
        load_season(root, "matches", prev_season, gender, conference)
        if prev_season is not None
        else None
    )

    sections: dict[str, dict] = {}
    ordered = [focus, *sorted(slug for slug in programmes if slug != focus)]
    for slug in ordered:
        entry = programmes[slug]
        section: dict[str, object] = {
            "name": entry.get("name") or slug,
        }
        if entry.get("abbr"):
            section["abbr"] = entry["abbr"]

        if prev_season is not None and prev_fixtures is not None:
            last: dict[str, object] = {
                "season": prev_season,
                **season_form(prev_fixtures, slug),
            }
            if prev_matches is not None:
                last["patterns"] = match_patterns(prev_fixtures, prev_matches, slug)
                flags = availability_flags(
                    prev_fixtures, prev_matches, slug, current_rosters
                )
                if flags:
                    last["availability_flags"] = flags
            if prev_stats is not None:
                last["discipline"] = discipline(prev_stats, slug)
                last["keepers"] = keepers(prev_stats, slug)
            section["last_season"] = last

        if prev_season is not None:
            shifts = usage_shifts(stats_by_season, slug, prev_season, current_rosters)
            if shifts:
                section["usage_shifts"] = shifts

        shape = roster_shape(prev_rosters, current_rosters, prev_stats, slug)
        if shape is not None:
            section["roster_shape"] = shape

        churn = turnover(prev_rosters, current_rosters, prev_stats, slug)
        if churn is not None:
            churn["previous_season"] = prev_season
            churn["roster_season"] = season
            section["turnover"] = churn
            section["top_returning"] = top_returning(
                churn, stats_by_season, current_rosters, slug, prev_season or season
            )

        if slug != focus:
            versus = head_to_head(fixtures_by_season, focus, slug)
            if versus is not None:
                section["head_to_head"] = versus
            fixtures_ahead = upcoming_vs_focus(current_fixtures, focus, slug)
            if fixtures_ahead:
                section["fixtures_vs_focus"] = fixtures_ahead

        sections[slug] = section

    sources = {}
    for kind in ("fixtures", "rosters", "stats", "matches"):
        for year in held:
            payload = load_season(root, kind, year, gender, conference)
            if payload is not None and payload.get("collected_at"):
                sources[
                    f"{kind}/{year}-{gender}-{programme_slug(conference)}"
                ] = payload["collected_at"]

    return {
        "schema": DIGEST_SCHEMA,
        "season": season,
        "gender": gender,
        "conference": current_fixtures.get("conference"),
        "focus": focus,
        "generated_at": generated_at,
        "previous_season": prev_season,
        "seasons_held": held,
        "membership_extrapolated": bool(
            current_fixtures.get("membership_extrapolated")
        ),
        "programmes": sections,
        "sources": sources,
    }
