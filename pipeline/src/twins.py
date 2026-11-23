"""Re-point a misread non-conference opponent to the programme whose own page
proves it.

A match between two collected programmes is published twice, once on each
school's schedule, and each page names its own school exactly. Opponent text
is the weak half: "Loyola" on Green Bay's page is Loyola Chicago, on
Syracuse's it is Loyola Maryland, and "Miami" on Little Rock's page is the
ACC's Miami while the name rules read the MAC's. The name rules decline to
guess (``sidearm_live._resolved_slug``), so such a side mints a stranger or
lands on the wrong programme, and the two sightings of one match never meet:
every reader that folds the whole division counts the match twice.

This pass settles a side by the other page instead of by spelling. For each
final, scored, non-exhibition fixture a member of the file owns against a
non-member, it looks in the season's OTHER fixture files of the same data
home (the same level and gender):

* the side stands when its programme's own page lists the owner that day,
  or when that programme's page was not collected (nothing to judge by);
* otherwise, when exactly one other collected programme's own page lists a
  final against the owner on that date with the same score from the owner's
  side, the side is that programme.

Anything short of that is left exactly as the name rules read it: no twin,
two candidates, a score that differs, a match not yet played. The result is
a pure function of the files, and every re-pointing is returned for the run
log, naming the printed slug, the programme and the proving fixture.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Repoint:
    fixture_id: str
    owner: str
    date: str
    side: str  # "home" or "away"
    was: str
    now: str
    proof: str  # the twin's fixture id

    def line(self) -> str:
        return (
            f"twin: {self.fixture_id} {self.date} {self.side} {self.was!r} -> "
            f"{self.now} ({self.now}'s own page, {self.proof}, lists {self.owner} "
            "that day with the same score)"
        )


def _owner(fixture: Mapping[str, object]) -> str | None:
    parts = str(fixture.get("id", "")).split(":")
    return parts[1] if len(parts) >= 3 and parts[1] else None


def _played(fixture: Mapping[str, object]) -> bool:
    return (
        fixture.get("status") == "final"
        and fixture.get("match_type") != "exhibition"
        and isinstance(fixture.get("home_score"), int)
        and isinstance(fixture.get("away_score"), int)
    )


def _score_for(fixture: Mapping[str, object], team: str) -> tuple[int, int]:
    home, away = int(fixture["home_score"]), int(fixture["away_score"])  # type: ignore[arg-type]
    return (home, away) if fixture.get("home") == team else (away, home)


def _members(document: Mapping[str, object]) -> set[str]:
    out: set[str] = set()
    for programme in document.get("programmes") or ():
        if isinstance(programme, Mapping) and programme.get("slug"):
            out.add(str(programme["slug"]))
        elif isinstance(programme, str):
            out.add(programme)
    return out


class SeasonIndex:
    """The other files of one season and gender, by programme."""

    def __init__(self, others: Iterable[Mapping[str, object]]) -> None:
        # programme -> the fixtures its own page published (id owner == slug)
        self.own: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        # every programme some other file lists as a member
        self.programmes: set[str] = set()
        for document in others:
            members = _members(document)
            self.programmes |= members
            for fixture in document.get("fixtures") or ():
                if not isinstance(fixture, Mapping):
                    continue
                owner = _owner(fixture)
                if owner in members:
                    self.own[owner].append(fixture)

    def lists(self, programme: str, team: str, date: str) -> list[Mapping[str, object]]:
        return [
            fixture
            for fixture in self.own.get(programme, ())
            if fixture.get("date") == date
            and {fixture.get("home"), fixture.get("away")} == {programme, team}
        ]


def repoint_by_twins(
    fixtures: Sequence[dict[str, object]],
    members: set[str],
    index: SeasonIndex,
) -> list[Repoint]:
    """Re-point, in place, each side the other programme's page proves."""
    changes: list[Repoint] = []
    for fixture in fixtures:
        owner = _owner(fixture)
        if owner not in members or not _played(fixture):
            continue
        if fixture.get("home") == owner:
            side = "away"
        elif fixture.get("away") == owner:
            side = "home"
        else:
            continue
        printed = str(fixture.get(side) or "")
        if not printed or printed in members:
            continue
        if printed in index.own:
            if index.lists(printed, owner, str(fixture["date"])):
                continue
        elif printed in index.programmes:
            # A programme of another file whose page was not collected: there
            # is no page to hold the side against.
            continue
        date = str(fixture["date"])
        score = _score_for(fixture, owner)
        candidates: list[tuple[str, Mapping[str, object]]] = []
        for programme in index.own:
            if programme in (owner, printed) or programme in members:
                continue
            for twin in index.lists(programme, owner, date):
                if _played(twin) and _score_for(twin, owner) == score:
                    candidates.append((programme, twin))
                    break
        if len(candidates) != 1:
            continue
        chosen, twin = candidates[0]
        if any(
            other is not fixture
            and _owner(other) == owner
            and other.get("date") == date
            and chosen in (other.get("home"), other.get("away"))
            for other in fixtures
        ):
            continue
        fixture[side] = chosen
        changes.append(
            Repoint(
                fixture_id=str(fixture.get("id")),
                owner=owner,
                date=date,
                side=side,
                was=printed,
                now=chosen,
                proof=str(twin.get("id")),
            )
        )
    return changes


def season_index(fixtures_dir: Path, season_key: str) -> SeasonIndex:
    """The index of ``fixtures_dir``'s other files of ``season_key``'s season
    and gender (``<season>-<gender>-<conference>``)."""
    season, gender, _ = season_key.split("-", 2)
    others: list[Mapping[str, object]] = []
    for path in sorted(fixtures_dir.glob(f"{season}-{gender}-*.json")):
        if path.stem == season_key:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(document, Mapping):
            others.append(document)
    return SeasonIndex(others)
