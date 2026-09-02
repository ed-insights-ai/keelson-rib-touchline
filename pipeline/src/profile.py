"""Player profiles — the accumulating per-player record.

A profile is one JSON file per (gender, programme, player) under
``data/players/``, built from two kinds of material:

* the **assembled record** — deterministic, recomputed on every build from the
  data home's season files: roster identity, career statistic lines, the
  per-match appearance timeline, and availability flags (participation holes).
  This part is never merged; it is replaced with fresh truth each build.
* **verified findings** — offseason research (summer leagues, honors, news)
  written by the player-profile workflow's research/verify nodes and merged
  in additively: a finding, once verified, stays; re-runs deduplicate on
  (url, text) rather than replace.

Built across seasons, the profile is the substrate for trajectory analysis —
spotting the players who shine over time — and every conclusion drawn from it
downstream must carry the evidence label its material warrants: career lines
are observed, availability holes are projected, research findings carry their
own confidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.digest import (
    _finals,
    _team_slugs,
    availability_flags,
    load_season,
    normalize_name,
    seasons_held,
)

PROFILE_SCHEMA = "touchline.player-profile/1"

#: Career-line fields lifted from a season statistics row.
_CAREER_FIELDS = (
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
_KEEPER_FIELDS = ("gp", "minutes", "saves", "goals_against", "shutouts")
_IDENTITY_FIELDS = (
    "position",
    "class_year",
    "number",
    "height",
    "weight",
    "hometown",
)


def player_key(name: str) -> str:
    """Filesystem slug for a player: ``José Núñez`` → ``jose-nunez``."""
    return re.sub(r"\s+", "-", normalize_name(name)) or "unknown"


def profile_path(root: Path, gender: str, programme: str, name: str) -> Path:
    return root / "data" / "players" / gender / programme / f"{player_key(name)}.json"


def _identity(
    root: Path, programme: str, gender: str, conference: str, key: str
) -> dict:
    """Roster bio from the most recent roster that lists the player."""
    for season in reversed(seasons_held(root, gender, conference)):
        rosters = load_season(root, "rosters", season, gender, conference)
        roster = ((rosters or {}).get("rosters") or {}).get(programme) or {}
        for player in roster.get("players") or []:
            if normalize_name(str(player.get("name") or "")) != key:
                continue
            return {
                "name": player.get("name"),
                "roster_season": season,
                **{
                    field: player[field]
                    for field in _IDENTITY_FIELDS
                    if player.get(field)
                },
            }
    return {}


def _career(
    root: Path, programme: str, gender: str, conference: str, key: str
) -> tuple[list, list]:
    """Statistic lines per season, split into field-player and keeper rows."""
    field_lines, keeper_lines = [], []
    for season in seasons_held(root, gender, conference):
        stats = load_season(root, "stats", season, gender, conference)
        team = ((stats or {}).get("teams") or {}).get(programme) or {}
        for row in team.get("players") or []:
            if normalize_name(str(row.get("name") or "")) == key:
                field_lines.append(
                    {
                        "season": season,
                        **{f: row[f] for f in _CAREER_FIELDS if f in row},
                    }
                )
                break
        for row in team.get("keepers") or []:
            if normalize_name(str(row.get("name") or "")) == key:
                line = {
                    "season": season,
                    **{f: row[f] for f in _KEEPER_FIELDS if f in row},
                }
                saves = int(row.get("saves") or 0)
                against = int(row.get("goals_against") or 0)
                if saves + against:
                    line["save_pct"] = round(saves / (saves + against), 3)
                keeper_lines.append(line)
                break
    return field_lines, keeper_lines


def _appearances(
    root: Path, programme: str, gender: str, conference: str, key: str
) -> list:
    """Per-match participation, season by season, from held box scores."""
    out = []
    for season in seasons_held(root, gender, conference):
        fixtures = load_season(root, "fixtures", season, gender, conference)
        matches_payload = load_season(root, "matches", season, gender, conference)
        if fixtures is None or matches_payload is None:
            continue
        matches = matches_payload.get("matches") or {}
        rows = []
        for fixture in sorted(
            _finals(fixtures, programme), key=lambda row: str(row.get("date"))
        ):
            match = matches.get(str(fixture.get("id")))
            if not isinstance(match, dict):
                continue
            slugs = _team_slugs(fixture, match)
            if programme not in slugs:
                continue
            own = slugs.index(programme)
            team = (match.get("teams") or [])[own]
            for player in team.get("players") or []:
                if normalize_name(str(player.get("name") or "")) != key:
                    continue
                rows.append(
                    {
                        "date": fixture.get("date"),
                        "opponent": slugs[1 - own],
                        "minutes": int(player.get("minutes") or 0),
                        "goals": int(player.get("goals") or 0),
                        "assists": int(player.get("assists") or 0),
                        "started": bool(player.get("started")),
                    }
                )
                break
        if rows:
            out.append({"season": season, "matches": rows})
    return out


def _availability(
    root: Path, programme: str, gender: str, conference: str, key: str
) -> list:
    """This player's participation-hole flags, one entry per flagged season."""
    flagged = []
    for season in seasons_held(root, gender, conference):
        fixtures = load_season(root, "fixtures", season, gender, conference)
        matches = load_season(root, "matches", season, gender, conference)
        if fixtures is None or matches is None:
            continue
        for flag in availability_flags(fixtures, matches, programme, None):
            if normalize_name(str(flag.get("name") or "")) == key:
                flag = dict(flag)
                flag["season"] = season
                flag.pop("on_current_roster", None)
                flagged.append(flag)
    return flagged


def assemble_record(
    root: Path,
    *,
    programme: str,
    gender: str,
    conference: str,
    player: str,
) -> dict:
    """The deterministic half of a profile, recomputed from the season files.

    Raises ``ValueError`` when the data home has no trace of the player at
    all — a profile of nothing would only invite a name-typo to masquerade
    as a person.
    """
    # The join key is the normalized name (spaces); player_key (hyphens) is
    # only ever a filename.
    key = normalize_name(player)
    identity = _identity(root, programme, gender, conference, key)
    career, keeper_career = _career(root, programme, gender, conference, key)
    appearances = _appearances(root, programme, gender, conference, key)
    if not identity and not career and not keeper_career and not appearances:
        raise ValueError(
            f"no trace of '{player}' for programme '{programme}' ({gender}) in this "
            "data home — check the spelling against the roster"
        )
    record = {
        "identity": identity or {"name": player},
        "career": career,
        "appearances": appearances,
        "availability_flags": _availability(root, programme, gender, conference, key),
        "seasons_searched": seasons_held(root, gender, conference),
    }
    if keeper_career:
        record["keeper_career"] = keeper_career
    return record


def _finding_key(finding: dict) -> tuple[str, str]:
    return (str(finding.get("url") or ""), str(finding.get("text") or ""))


def upsert_profile(
    root: Path,
    *,
    programme: str,
    gender: str,
    conference: str,
    player: str,
    generated_at: str,
    findings_file: Path | None = None,
) -> Path:
    """Build or refresh one profile: fresh record, additive findings."""
    path = profile_path(root, gender, programme, player)
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    record = assemble_record(
        root,
        programme=programme,
        gender=gender,
        conference=conference,
        player=player,
    )

    findings = list(existing.get("findings") or [])
    attested = list(existing.get("attested_uncaptured") or [])
    unswept = list(existing.get("unswept") or [])
    if findings_file is not None:
        incoming = json.loads(findings_file.read_text(encoding="utf-8"))
        seen = {_finding_key(finding) for finding in findings}
        for finding in incoming.get("findings") or []:
            if _finding_key(finding) not in seen:
                findings.append(finding)
                seen.add(_finding_key(finding))
        for item in incoming.get("attested_uncaptured") or []:
            if item not in attested:
                attested.append(item)
        for item in incoming.get("unswept") or []:
            if item not in unswept:
                unswept.append(item)

    profile = {
        "schema": PROFILE_SCHEMA,
        "player": record["identity"].get("name", player),
        "key": player_key(player),
        "programme": programme,
        "gender": gender,
        "first_built": existing.get("first_built") or generated_at,
        "updated_at": generated_at,
        **record,
        "findings": findings,
        "attested_uncaptured": attested,
        "unswept": unswept,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
