"""Resolve who each box-score line is: ``player_ref`` on every player-match line.

A SideArm box score links a bio (the ``player_id`` the parsers read off the
href) only for the site owner's roster; the opponent's rows print a bare
name, no link, no attribute (measured 2026-09-07 on the archived Fort Lewis
7089 box: FLC rows linked, FHS rows plain).  PrestoSports links no bios at
all.  So ``player_id`` — the id AS PUBLISHED ON THE PAGE — is absent on
roughly half of every season's lines, and an opponent's line cannot be
joined to the same player anywhere else (bead tl-y8q).

This module writes a second field beside it, ``player_ref``, on every line
of both sides: ``{"id": ..., "source": ...}``, where ``source`` names the
route the id came by, so a consumer can see how far to trust it:

``page``
    the page's own link; ``id`` is ``player_id``.
``twin``
    the opponent's own box score of the same match (a match between two
    collected programmes is published twice, once on each site, and each
    site links its own roster): the line in that box whose name matches
    this one, exactly or by shirt number and surname, carries the id.
``roster``
    the programme's season roster in ``data/rosters`` (its bio URL carries
    the id): exact folded full name, unique on the roster; else shirt
    number AND folded surname, unique.
``key``
    unresolved; ``id`` is the synthetic ``<slug>:<folded name>:<number>``,
    stable within a season so downstream can still link a programme's
    lines to each other.

The rules stop at the first hit, in that order, and none of them guesses a
spelling: no edit distance, no nickname table, no number-only match, no
first-name-only match ("Hoffman" is not "Hoffmann").  A twin and a roster
that both hit and disagree is a finding, not a choice — one of the two
sources is wrong, and the report names it.  The resolution is a pure
function of the season's files, so re-running the writer over unchanged
data writes the same refs.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

SOURCE_PAGE = "page"
SOURCE_TWIN = "twin"
SOURCE_ROSTER = "roster"
SOURCE_KEY = "key"
SOURCES = (SOURCE_PAGE, SOURCE_TWIN, SOURCE_ROSTER, SOURCE_KEY)

#: Why a line fell to ``key``, for the report: what a later rule would win.
MISS_NO_ROSTER = "no_roster"  # the programme has no roster this season
MISS_ROSTER_NO_IDS = "roster_no_ids"  # a roster whose site links no bios (Presto)
MISS_NOT_ON_ROSTER = "not_on_roster"  # neither name nor number+surname hit
MISS_AMBIGUOUS = "ambiguous"  # more than one roster player matched
MISS_NUMBER_DIFFERS = "number_differs"  # surname hit, shirt number did not
MISS_NO_NUMBER = "no_number"  # surname hit, the line prints no number
MISS_NO_NAME = "no_name"  # the line prints no name at all
MISS_UNORIENTED = "unoriented"  # the box names no side, so no slug


#: Letters NFKD leaves whole because they are letters of their own, not a
#: base plus a mark, and the ASCII a stat crew types for them.  A fixed
#: table, applied the same way to both sources; nothing is inferred.
_PLAIN_LETTERS = str.maketrans(
    {
        "ø": "o",
        "æ": "ae",
        "œ": "oe",
        "ß": "ss",
        "ð": "d",
        "þ": "th",
        "ł": "l",
        "đ": "d",
        "ı": "i",
    }
)


def _letters(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower()).translate(_PLAIN_LETTERS)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z]", "", text)


def fold_name(name: str) -> str:
    """A name reduced to what two sources can agree on: NFKD-decomposed,
    accents dropped, lower-cased, letters only, given names first.

    "Høihjelle, Iver" and "Iver Hoihjelle" both fold to ``iverhoihjelle``;
    nothing else is folded — "Hoffman" stays a different word from
    "Hoffmann", and a middle name the other source omits is a miss.
    """
    return _letters(_given_first(name))


def fold_surname(name: str) -> str:
    """The surname folded: the part before the comma in "Last, First", the
    last word otherwise.  A compound surname the other source hyphenates or
    joins folds the same ("Le Baut" and "LeBaut" both give ``lebaut`` only
    when written as one token; two tokens keep the last, by design — this
    is the tie-break under a matching shirt number, not a guess)."""
    head, comma, _ = name.partition(",")
    surname = head if comma else (name.split() or [""])[-1]
    return _letters(surname)


def _given_first(name: str) -> str:
    head, comma, tail = name.partition(",")
    if comma and tail.strip():
        return f"{tail.strip()} {head.strip()}"
    return name.strip()


def _number(value: object) -> str:
    """A shirt number as the sources print it, leading zeros dropped so
    "01" and "1" agree; empty when the line prints none."""
    text = str(value or "").strip()
    return text.lstrip("0") or ("0" if text else "")


def synthetic_key(slug: str, name: str, number: object) -> str:
    return f"{slug}:{fold_name(name)}:{_number(number)}"


@dataclass
class RosterIndex:
    """One programme's season roster, indexed for the two roster rules."""

    by_name: dict[str, list[str]] = field(default_factory=dict)
    by_number_surname: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    by_surname: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_players(cls, players: list[dict[str, object]]) -> RosterIndex:
        index = cls()
        for player in players:
            player_id = roster_player_id(player)
            name = str(player.get("name") or "")
            if not player_id or not name:
                continue
            index.by_name.setdefault(fold_name(name), []).append(player_id)
            surname = fold_surname(name)
            index.by_surname.setdefault(surname, []).append(player_id)
            number = _number(player.get("number"))
            if number:
                index.by_number_surname.setdefault((number, surname), []).append(
                    player_id
                )
        return index


def roster_player_id(player: dict[str, object]) -> str:
    """A roster line's id: ``player_id`` when the writer carried one, else
    the trailing number of its bio URL (``.../roster/<name>/<id>``)."""
    explicit = str(player.get("player_id") or "").strip()
    if explicit:
        return explicit
    match = re.search(r"/(\d+)/?$", str(player.get("source_url") or ""))
    return match.group(1) if match else ""


def _lookup(index: RosterIndex, name: str, number: object) -> tuple[str, str]:
    """``(id, "")`` on a hit, ``("", miss reason)`` otherwise."""
    if not name:
        return "", MISS_NO_NAME
    if not index.by_name:
        return "", MISS_ROSTER_NO_IDS
    by_name = sorted(set(index.by_name.get(fold_name(name), [])))
    if len(by_name) == 1:
        return by_name[0], ""
    surname = fold_surname(name)
    shirt = _number(number)
    by_number = (
        sorted(set(index.by_number_surname.get((shirt, surname), []))) if shirt else []
    )
    if len(by_number) == 1:
        return by_number[0], ""
    if len(by_name) > 1 or len(by_number) > 1:
        return "", MISS_AMBIGUOUS
    if index.by_surname.get(surname):
        return "", MISS_NO_NUMBER if not shirt else MISS_NUMBER_DIFFERS
    return "", MISS_NOT_ON_ROSTER


def _twin_index(lines: list[dict[str, object]]) -> RosterIndex:
    """The opponent's own box, read like a roster: every line that carries
    a page id is a player that site published."""
    return RosterIndex.from_players(
        [
            {
                "name": line.get("name"),
                "number": line.get("number"),
                "player_id": line.get("player_id"),
            }
            for line in lines
            if line.get("player_id")
        ]
    )


def team_slugs(fixture: dict[str, object], match: dict[str, object]) -> list[str]:
    """Each ``teams`` index's programme slug, by the stored ``home_index``;
    ``["", ""]`` when the box never proved its orientation."""
    home_index = match.get("home_index")
    if home_index not in (0, 1):
        return ["", ""]
    slugs = ["", ""]
    slugs[int(home_index)] = str(fixture.get("home") or "")
    slugs[1 - int(home_index)] = str(fixture.get("away") or "")
    return slugs


def _side_lines(team: dict[str, object]) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = []
    for key in ("players", "keepers"):
        value = team.get(key)
        if isinstance(value, list):
            lines.extend(line for line in value if isinstance(line, dict))
    return lines


@dataclass
class SeasonSources:
    """What one season's resolution reads: every collected roster and every
    collected box, by programme, across every conference file of the season.

    Built from the run's own payloads plus the sibling conference files on
    disk (``data/rosters/{season}-{gender}-*.json`` and
    ``data/matches/{season}-{gender}-*.json`` with their fixtures), so a
    cross-conference opponent resolves through its own conference's collect.
    """

    rosters: dict[str, RosterIndex] = field(default_factory=dict)
    #: Site host of each programme's roster page, the tell that a box was
    #: served by that programme's own site.
    hosts: dict[str, str] = field(default_factory=dict)
    #: ``(date, slug)`` -> that programme's lines in a box its own site served.
    twins: dict[tuple[str, str], list[dict[str, object]]] = field(default_factory=dict)

    def add_rosters(self, payload: dict[str, object]) -> None:
        rosters = payload.get("rosters")
        if not isinstance(rosters, dict):
            return
        for slug, roster in rosters.items():
            if not isinstance(roster, dict):
                continue
            players = roster.get("players")
            self.rosters[str(slug)] = RosterIndex.from_players(
                [p for p in players if isinstance(p, dict)]
                if isinstance(players, list)
                else []
            )
            host = urlparse(str(roster.get("source_url") or "")).netloc.lower()
            if host:
                self.hosts[str(slug)] = host

    def add_matches(
        self, matches_payload: dict[str, object], fixtures_payload: dict[str, object]
    ) -> None:
        """Every box a programme's own site served, keyed by date and slug.

        A box is that programme's own when its ``source_url`` host is the
        host of the programme's roster page this season; the lines on that
        programme's side then carry the site's ids.  (Rosters must be added
        first.)
        """
        fixtures = {
            str(f.get("id")): f
            for f in (fixtures_payload.get("fixtures") or [])
            if isinstance(f, dict)
        }
        matches = matches_payload.get("matches")
        if not isinstance(matches, dict):
            return
        for fixture_id, match in matches.items():
            fixture = fixtures.get(str(fixture_id))
            if fixture is None or not isinstance(match, dict):
                continue
            host = urlparse(str(match.get("source_url") or "")).netloc.lower()
            teams = match.get("teams")
            if not host or not isinstance(teams, list) or len(teams) != 2:
                continue
            slugs = team_slugs(fixture, match)
            date = str(fixture.get("date") or "")
            for index, slug in enumerate(slugs):
                if slug and self.hosts.get(slug) == host:
                    self.twins.setdefault((date, slug), []).extend(
                        _side_lines(teams[index])
                    )

    def load_disk(
        self,
        root: Path,
        season: int,
        gender: str,
        *,
        exclude_matches: str | None = None,
    ) -> None:
        """Every conference file of the season under ``root``: rosters
        first (they carry the hosts), then boxes with their fixtures.
        ``exclude_matches`` names the shard whose boxes the caller holds in
        memory, so a stale copy on disk is not read beside them."""
        pattern = f"{season}-{gender}-*.json"
        rosters_dir = root / "data" / "rosters"
        matches_dir = root / "data" / "matches"
        fixtures_dir = root / "data" / "fixtures"
        if rosters_dir.is_dir():
            for path in sorted(rosters_dir.glob(pattern)):
                payload = _read(path)
                if payload is not None:
                    self.add_rosters(payload)
        if matches_dir.is_dir():
            for path in sorted(matches_dir.glob(pattern)):
                if _shard_of(path) == exclude_matches:
                    continue
                matches = _read(path)
                fixtures = _read(fixtures_dir / path.name)
                if matches is not None and fixtures is not None:
                    self.add_matches(matches, fixtures)


def _shard_of(path: Path) -> str:
    """The conference shard of ``{season}-{gender}-{shard}.json``."""
    return path.stem.split("-", 2)[-1]


def _read(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass
class IdentityReport:
    """What one resolution pass did, for the collect summary and the check."""

    #: ``(side, source)`` -> lines, side ``owner`` (the box's own site) or
    #: ``opponent``.
    counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    #: Miss reason -> lines that fell to ``key`` for it.
    misses: Counter[str] = field(default_factory=Counter)
    #: A twin and a roster naming different ids for one line.
    disagreements: list[str] = field(default_factory=list)

    def lines(self, side: str) -> int:
        return sum(n for (s, _), n in self.counts.items() if s == side)

    def share(self, side: str, source: str) -> float:
        total = self.lines(side)
        return self.counts[(side, source)] / total if total else 0.0

    def summary(self) -> str:
        """One line in the collect summary's voice."""
        parts = []
        for side in ("owner", "opponent"):
            total = self.lines(side)
            cells = " · ".join(
                f"{source} {self.counts[(side, source)]}"
                for source in SOURCES
                if self.counts[(side, source)]
            )
            parts.append(f"{side} side {total} lines: {cells or 'none'}")
        text = "identity: " + "; ".join(parts)
        if self.misses:
            text += " (key by reason: " + ", ".join(
                f"{reason} {n}" for reason, n in sorted(self.misses.items())
            )
            text += ")"
        if self.disagreements:
            text += f"; {len(self.disagreements)} twin/roster disagreement(s)"
        return text


def resolve_line(
    line: dict[str, object],
    *,
    slug: str,
    date: str,
    sources: SeasonSources,
    report: IdentityReport,
    side: str,
    label: str,
) -> None:
    """Write ``player_ref`` on one line, by the rules in the module doc."""
    name = str(line.get("name") or "")
    number = line.get("number")
    page_id = str(line.get("player_id") or "").strip()
    if page_id:
        line["player_ref"] = {"id": page_id, "source": SOURCE_PAGE}
        report.counts[(side, SOURCE_PAGE)] += 1
        return
    if not slug:
        line["player_ref"] = {
            "id": synthetic_key("", name, number),
            "source": SOURCE_KEY,
        }
        report.counts[(side, SOURCE_KEY)] += 1
        report.misses[MISS_UNORIENTED] += 1
        return
    twin_lines = sources.twins.get((date, slug))
    twin_id = ""
    if twin_lines:
        twin_id, _ = _lookup(_twin_index(twin_lines), name, number)
    roster = sources.rosters.get(slug)
    roster_id, reason = ("", MISS_NO_ROSTER)
    if roster is not None:
        roster_id, reason = _lookup(roster, name, number)
    if twin_id:
        if roster_id and roster_id != twin_id:
            report.disagreements.append(
                f"{label} {slug} {name!r} #{_number(number) or '-'}: "
                f"twin box says {twin_id}, roster says {roster_id}"
            )
        line["player_ref"] = {"id": twin_id, "source": SOURCE_TWIN}
        report.counts[(side, SOURCE_TWIN)] += 1
        return
    if roster_id:
        line["player_ref"] = {"id": roster_id, "source": SOURCE_ROSTER}
        report.counts[(side, SOURCE_ROSTER)] += 1
        return
    line["player_ref"] = {
        "id": synthetic_key(slug, name, number),
        "source": SOURCE_KEY,
    }
    report.counts[(side, SOURCE_KEY)] += 1
    report.misses[reason] += 1


def resolve_matches(
    matches: dict[str, dict[str, object]],
    fixtures: list[dict[str, object]],
    sources: SeasonSources,
    *,
    report: IdentityReport | None = None,
) -> IdentityReport:
    """Write ``player_ref`` on every line of every match, in place.

    The owner side is the side whose programme's site served the box (by
    host, the same tell ``SeasonSources`` uses); when no side's host is
    known, the side carrying more page ids.  Any ``player_ref`` already on
    a line is recomputed: the field is a function of the season's files,
    never something a stored box carries forward.
    """
    report = report if report is not None else IdentityReport()
    by_id = {str(f.get("id")): f for f in fixtures if isinstance(f, dict)}
    for fixture_id, match in matches.items():
        fixture = by_id.get(str(fixture_id))
        teams = match.get("teams") if isinstance(match, dict) else None
        if fixture is None or not isinstance(teams, list) or len(teams) != 2:
            continue
        slugs = team_slugs(fixture, match)
        date = str(fixture.get("date") or "")
        host = urlparse(str(match.get("source_url") or "")).netloc.lower()
        owner = next(
            (
                i
                for i, slug in enumerate(slugs)
                if slug and sources.hosts.get(slug) == host
            ),
            None,
        )
        if owner is None:
            ids = [
                sum(1 for line in _side_lines(t) if line.get("player_id"))
                for t in teams
            ]
            owner = 0 if ids[0] >= ids[1] else 1
        for index, team in enumerate(teams):
            if not isinstance(team, dict):
                continue
            side = "owner" if index == owner else "opponent"
            for line in _side_lines(team):
                resolve_line(
                    line,
                    slug=slugs[index],
                    date=date,
                    sources=sources,
                    report=report,
                    side=side,
                    label=f"{fixture_id} {date}",
                )
    return report
