"""Season-aware conference-membership reference data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from src import paths
from src.config import SchoolConfig, load_schools, programme_slug

#: The top-level key naming, per conference code, where a conference with no
#: per-season records pages keeps its member lists instead.
STANDINGS_ARCHIVES = "standings_archives"

#: The top-level key carrying, per conference code, what the conference is:
#: its NCAA level and the names it is printed under.
CONFERENCE_PROFILES = "conference_profiles"

#: The NCAA levels a conference can play at. The word is "level" on purpose:
#: "division" already means a conference's own East/West split on a
#: membership window (and a gender in the cadence script).
LEVELS = ("d1", "d2", "d3")

#: The two codes ``conferences`` carries that are not conferences: a window
#: needs something to name for a season outside every conference.
STRUCTURAL_CODES = frozenset({"independent", "non_member"})

_PROFILE_FIELDS = frozenset({"level", "names", "code_is_word"})


@dataclass(frozen=True)
class ConferenceProfile:
    """One conference as a record, not a bare code.

    ``level`` is the NCAA level it plays at. ``names`` are the long names it
    is printed under in schedule headers ("Great American Conference",
    "Great American"), which is how a header that carries neither the word
    "conference" nor the code is still read as that conference's postseason
    (``sidearm_live.tournament_stage``). ``code_is_word`` says the code is
    an ordinary English word (a code such as PATRIOT or SUMMIT), so the code
    alone never names the conference in a header; only its ``names`` do.
    """

    code: str
    level: str
    names: tuple[str, ...]
    code_is_word: bool = False


def load_membership(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the authored membership document.

    With no explicit ``path``, the rib's packaged copy is preferred — it is
    the source of record — and the data home's mirrored copy is only the
    fallback for an install that ships no packaged data tree. Collect keeps
    the mirror fresh (scripts/collect_board.py) and the data-integrity
    workflow's membership-sync check reports any divergence, so the two
    surfaces can never quietly resolve different member lists.
    """
    if path is not None:
        membership_path = Path(path)
        if not membership_path.exists():
            raise FileNotFoundError(f"Membership file not found: {membership_path}")
    else:
        packaged = paths.packaged_membership_path()
        membership_path = packaged if packaged.exists() else paths.membership_path()
        if not membership_path.exists():
            raise FileNotFoundError(
                "Membership file not found: no packaged copy at "
                f"{packaged} and no data home copy at {membership_path}"
            )

    with membership_path.open(encoding="utf-8") as membership_file:
        document = json.load(membership_file)

    if not isinstance(document, dict):
        raise ValueError("membership.json root must be a JSON object")
    return document


def conference_profiles(
    document: dict[str, Any] | None = None,
) -> dict[str, ConferenceProfile]:
    """Every well-formed conference profile in the document, by code.

    A reader, not a judge: a malformed entry is left out here and named by
    ``validate``, so a collect never dies over a profile check-membership
    would have refused before the file shipped.
    """
    membership_document = document if document is not None else load_membership()
    raw = membership_document.get(CONFERENCE_PROFILES)
    if not isinstance(raw, dict):
        return {}

    profiles: dict[str, ConferenceProfile] = {}
    for code, entry in raw.items():
        if not isinstance(code, str) or not isinstance(entry, dict):
            continue
        level = entry.get("level")
        names = entry.get("names")
        if level not in LEVELS or not isinstance(names, list):
            continue
        printed = tuple(
            " ".join(name.split())
            for name in names
            if isinstance(name, str) and name.strip()
        )
        if not printed:
            continue
        profiles[code] = ConferenceProfile(
            code=code,
            level=level,
            names=printed,
            code_is_word=entry.get("code_is_word") is True,
        )
    return profiles


def conference_level(
    conference: str,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """The NCAA level a conference plays at, or None for a code with no profile."""
    profile = conference_profiles(document).get(conference)
    return None if profile is None else profile.level


def conferences_at_level(
    level: str,
    *,
    document: dict[str, Any] | None = None,
) -> list[str]:
    """Every conference code whose profile names ``level``, sorted."""
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; known: {', '.join(LEVELS)}")
    return sorted(
        code
        for code, profile in conference_profiles(document).items()
        if profile.level == level
    )


def collecting_level(
    conference: str,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """The NCAA level a collect of ``conference`` resolves opponent text at.

    The conference's profile level, its code compared without case the way
    ``conference_in_effect`` compares it. None for a code with no profile (a
    structural code, or a reference older than profiles): such a collect has
    no level to scope to and resolves against every stanza of the gender, as
    every collect did before levels existed.
    """
    profiles = conference_profiles(document)
    wanted = conference.strip().casefold()
    for code, profile in profiles.items():
        if code.casefold() == wanted:
            return profile.level
    return None


def _levelled_windows(
    windows: object, profiles: dict[str, ConferenceProfile]
) -> list[tuple[int, int, str]]:
    """(from, to, level) for each well-formed window naming a profiled conference."""
    if not isinstance(windows, list):
        return []
    levelled: list[tuple[int, int, str]] = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        from_season, to_season = window.get("from_season"), window.get("to_season")
        profile = profiles.get(window.get("conference"))  # type: ignore[arg-type]
        if _is_year(from_season) and _is_year(to_season) and profile is not None:
            levelled.append((from_season, to_season, profile.level))
    return levelled


def _level_in_season(
    levelled: list[tuple[int, int, str]],
    season_year: int,
    stanza_level: str | None,
) -> str | None:
    """The rule ``programme_level`` documents, over pre-read windows."""
    if not levelled:
        return stanza_level
    for from_season, to_season, level in levelled:
        if from_season <= season_year <= to_season:
            return level
    before = [
        (to_season, level)
        for _, to_season, level in levelled
        if to_season < season_year
    ]
    if before:
        return max(before)[1]
    return min((from_season, level) for from_season, _, level in levelled)[1]


def programme_level(
    slug: str,
    gender: str,
    season_year: int,
    *,
    stanza_conference: str = "",
    document: dict[str, Any] | None = None,
) -> str | None:
    """The NCAA level a programme is resolved at in one season.

    The level of the conference its window for the season names: Mercyhurst
    men, PSAC (d2) 2022-2023 and a Division I conference from 2024, is at d2
    for 2023 and d1 for 2024. Opponent text is resolved only against the
    stanzas at the collecting conference's level that season
    (``stanzas_at_level``), so this is what decides which table a stanza
    sits in.

    A season no level-bearing window covers (before the programme's first
    window, after its last, or covered only by a structural ``independent``
    or ``non_member`` window, which names no conference and so no level)
    takes the level of the latest level-bearing window that ended before
    it, else of the earliest one after it: a leaver keeps the level it left
    from until a window says otherwise, and an arrival the level it arrived
    at. That is the rule that keeps every Division II table exactly what it
    was before levels existed. Every stanza sat in one table per gender then,
    in every season; Mercyhurst, whose PSAC windows end in 2023, is still at
    d2 for 2024-2026 until its Division I window is authored, and Oklahoma
    Baptist, GAC through 2019 and ``non_member`` after, is still at d2. Being
    in a level's table is not membership of a conference:
    ``conference_in_effect`` answers that, and still puts such a programme
    in none.

    A programme with no level-bearing window at all takes its stanza
    conference's level, the default ``has_windows`` gives a programme the
    reference has not reached. None when that has no profile either:
    ``stanzas_at_level`` then keeps the stanza in every level's table, as
    before levels, and ``validate`` refuses such a stanza in a shipped config.
    """
    membership_document = document if document is not None else load_membership()
    profiles = conference_profiles(membership_document)
    memberships = membership_document.get("memberships")
    genders = memberships.get(slug) if isinstance(memberships, dict) else None
    windows = genders.get(gender) if isinstance(genders, dict) else None
    stanza = profiles.get(stanza_conference)
    return _level_in_season(
        _levelled_windows(windows, profiles),
        season_year,
        None if stanza is None else stanza.level,
    )


def stanzas_at_level(
    schools: list[SchoolConfig],
    gender: str,
    level: str | None,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> list[SchoolConfig]:
    """The stanzas of one gender that opponent text may resolve to, in file order.

    One NCAA level in one season (``programme_level``). The order is the
    file's, so a map built from the result keeps last-stanza-wins exactly
    where it held before; leaving a level's stanzas out of another level's
    table therefore cannot change a key that level's stanzas alone claim.
    A stanza with no level is kept at every level. With no ``level`` (a
    collect of a conference with no profile) every stanza of the gender is
    kept: there is nothing to scope to.
    """
    of_gender = [school for school in schools if school.gender == gender]
    if level is None:
        return of_gender
    membership_document = document if document is not None else load_membership()
    profiles = conference_profiles(membership_document)
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        memberships = {}
    kept: list[SchoolConfig] = []
    for school in of_gender:
        genders = memberships.get(programme_slug(school.name))
        windows = genders.get(gender) if isinstance(genders, dict) else None
        stanza = profiles.get(school.conference)
        held = _level_in_season(
            _levelled_windows(windows, profiles),
            season_year,
            None if stanza is None else stanza.level,
        )
        if held is None or held == level:
            kept.append(school)
    return kept


def resolution_stanzas(
    schools: list[SchoolConfig],
    gender: str,
    conference: str,
    season_year: int,
    *,
    document: dict[str, Any] | None,
) -> list[SchoolConfig]:
    """The stanzas a collect of one conference-season resolves opponent text to.

    ``stanzas_at_level`` at the conference's level (``collecting_level``).
    The one place a collect's identity scope is decided: the identity map,
    the resolution scope's member claims, member-only aliases and distance
    tiebreak, and so ``ncaa_side``, are all built from this list, and the
    schedule parse fingerprint hashes what they are built into. Text naming
    a school at another level resolves to nothing here and mints its slug
    from the text, as text naming an unknown school does. With no document
    (an install without the membership reference) every stanza of the
    gender is kept, as before.
    """
    if document is None:
        return [school for school in schools if school.gender == gender]
    return stanzas_at_level(
        schools,
        gender,
        collecting_level(conference, document=document),
        season_year,
        document=document,
    )


def shard_stanzas(
    schools: list[SchoolConfig],
    stem: str,
    *,
    document: dict[str, Any] | None,
) -> list[SchoolConfig]:
    """The stanzas a season file's collect resolved against, from its file name.

    ``stem`` is a season file's name without ``.json``,
    ``{season}-{gender}-{conference slug}`` ("2024-men-g-mac"); the slug is
    matched back to a declared code. A read-only check that re-resolves
    stored text the way the collect did (check_box_scores.py,
    sweep_opponent_slugs.py) reads it in this table. A stem it cannot read,
    or a document it does not have, gives every stanza of the stem's gender:
    the table before levels.
    """
    season, _, rest = stem.partition("-")
    gender, _, shard = rest.partition("-")
    of_gender = [school for school in schools if school.gender == gender]
    if document is None or not season.isdigit() or not shard:
        return of_gender
    codes = document.get("conferences")
    for code in codes if isinstance(codes, list) else []:
        if isinstance(code, str) and programme_slug(code) == shard:
            return resolution_stanzas(
                schools, gender, code, int(season), document=document
            )
    return of_gender


def level_scopes(
    schools: list[SchoolConfig],
    *,
    document: dict[str, Any],
) -> list[tuple[str, str, int, list[SchoolConfig]]]:
    """Every (gender, level, season, stanzas) table a collect can resolve against.

    The seasons are the document's span (``seasons``), or every season a
    window names when it has none; a season outside them reads the same
    windows as the span's nearest end, so the span answers for it. One
    table per level some stanza holds that season; a stanza with no level
    sits in each. When no stanza of a gender has a level that season, the
    one table is labelled ``"unlevelled"``. check-membership refuses an
    identity key two stanzas of one table claim.
    """
    raw = document.get("seasons")
    if (
        isinstance(raw, dict)
        and _is_year(raw.get("from"))
        and _is_year(raw.get("to"))
        and raw["from"] <= raw["to"]
    ):
        seasons = list(range(raw["from"], raw["to"] + 1))
    else:
        memberships = document.get("memberships")
        years = {
            year
            for genders in (
                memberships.values() if isinstance(memberships, dict) else []
            )
            if isinstance(genders, dict)
            for windows in genders.values()
            if isinstance(windows, list)
            for window in windows
            if isinstance(window, dict)
            and _is_year(window.get("from_season"))
            and _is_year(window.get("to_season"))
            for year in range(window["from_season"], window["to_season"] + 1)
        }
        seasons = sorted(years) or [0]
    tables: list[tuple[str, str, int, list[SchoolConfig]]] = []
    genders: list[str] = []
    for school in schools:
        if school.gender not in genders:
            genders.append(school.gender)
    for gender in genders:
        for season in seasons:
            held = {
                programme_level(
                    programme_slug(school.name),
                    gender,
                    season,
                    stanza_conference=school.conference,
                    document=document,
                )
                for school in schools
                if school.gender == gender
            }
            levels = [level for level in LEVELS if level in held]
            if not levels:
                tables.append(
                    (
                        gender,
                        "unlevelled",
                        season,
                        stanzas_at_level(
                            schools, gender, None, season, document=document
                        ),
                    )
                )
                continue
            for level in levels:
                tables.append(
                    (
                        gender,
                        level,
                        season,
                        stanzas_at_level(
                            schools, gender, level, season, document=document
                        ),
                    )
                )
    return tables


def conference_for(
    slug: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """Return the programme's conference for one season, if declared."""
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return None

    genders = memberships.get(slug)
    if not isinstance(genders, dict):
        return None
    return _window_conference(genders.get(gender), season_year)


def has_windows(
    slug: str,
    gender: str,
    *,
    document: dict[str, Any] | None = None,
) -> bool:
    """Whether the document authors any membership window for the programme.

    The line between the two ways a programme's conference is known. One
    with authored windows is governed by them alone: a season none of them
    covers is a season it is in no conference, never a season to guess from
    its stanza. One with none is a programme the reference has not reached,
    and its stanza's ``conference`` is all there is.
    """
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return False
    genders = memberships.get(slug)
    if not isinstance(genders, dict):
        return False
    windows = genders.get(gender)
    return isinstance(windows, list) and any(
        isinstance(window, dict)
        and _is_year(window.get("from_season"))
        and _is_year(window.get("to_season"))
        and isinstance(window.get("conference"), str)
        for window in windows
    )


def authored_through(
    conference: str,
    gender: str,
    *,
    document: dict[str, Any] | None = None,
) -> int:
    """The last season any window authors for one conference and gender.

    The conference's own horizon, 0 when no window names it. Scoped to the
    conference, never the file, for the reason ``resolveConference`` in
    src/membership.ts gives: one conference authored through 2025 beside
    another through 2026 must not read its horizon off its neighbour. The
    code is compared without case, as that resolver compares it.
    """
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return 0
    wanted = conference.strip().casefold()
    through = 0
    for genders in memberships.values():
        if not isinstance(genders, dict):
            continue
        windows = genders.get(gender)
        if not isinstance(windows, list):
            continue
        for window in windows:
            if not isinstance(window, dict):
                continue
            named = window.get("conference")
            to_season = window.get("to_season")
            if (
                isinstance(named, str)
                and named.casefold() == wanted
                and _is_year(to_season)
                and to_season > through
            ):
                through = to_season
    return through


def effective_season(
    conference: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> int:
    """The season whose windows answer for ``season_year`` in a conference.

    The season itself, unless it lies past the conference's last authored
    season: then that last season, carried forward. This is the one place a
    season no window covers is still answered, and it is the answer
    ``resolveConference`` gives (the collect it resolves is stamped
    ``membership_extrapolated``): the GAC authored through 2025 keeps its
    2025 members for a 2026 collect. It is a statement about the
    conference's horizon, not about any programme, so a programme that left
    inside the horizon (Mercyhurst, PSAC through 2023 while the PSAC is
    authored through 2026) is not carried anywhere.
    """
    through = authored_through(conference, gender, document=document)
    return through if 0 < through < season_year else season_year


def conference_in_effect(
    slug: str,
    gender: str,
    season_year: int,
    conference: str,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """A programme's conference for one season, as a collect of ``conference`` reads it.

    The programme's own window covering the season always answers. With none,
    the only answer left is the carry-forward: the season lies past
    ``conference``'s authored horizon and the programme's window for that
    conference's last authored season names that same conference, so the
    programme is still read as its member (``effective_season``). Anything
    else is None, a season the programme is in no conference: it is never
    filled in from a stanza, and never from another conference's horizon.

    So a programme whose own windows already say where it went is not
    carried anywhere (Trevecca, GSC from 2024, is no G-MAC member in 2024
    whatever the G-MAC's horizon is), and one carried forward is carried
    only into the conference being read.

    Nor is a programme whose windows moved it on after the horizon, even
    once that later window has ended: LOWER authored through 2025, a
    programme LOWER's 2022-2025 and UPPER's for 2026 has left LOWER, so a
    2027 LOWER collect does not restore it. A later window is what was
    authored after the horizon season; only a programme with none is still
    where the horizon left it.
    """
    membership_document = document if document is not None else load_membership()
    declared = conference_for(slug, gender, season_year, document=membership_document)
    if declared is not None:
        return declared
    effective = effective_season(
        conference, gender, season_year, document=membership_document
    )
    if effective == season_year:
        return None
    carried = conference_for(slug, gender, effective, document=membership_document)
    if carried is None or carried.casefold() != conference.strip().casefold():
        return None
    if _authored_after(slug, gender, effective, document=membership_document):
        return None
    return carried


def _authored_after(
    slug: str, gender: str, season_year: int, *, document: dict[str, Any]
) -> bool:
    """Whether any of the programme's windows starts after ``season_year``."""
    memberships = document.get("memberships")
    genders = memberships.get(slug) if isinstance(memberships, dict) else None
    windows = genders.get(gender) if isinstance(genders, dict) else None
    return isinstance(windows, list) and any(
        isinstance(window, dict)
        and _is_year(window.get("from_season"))
        and window["from_season"] > season_year
        for window in windows
    )


def members_in_effect(
    conference: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> set[str]:
    """Every slug ``conference_in_effect`` places in the conference that season.

    ``members_of`` with the conference's horizon honoured: identical to it
    for every season the conference authors, and its last authored season's
    members, less any whose own window has since moved them, for a season
    past that.
    """
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return set()
    return {
        slug
        for slug in memberships
        if isinstance(slug, str)
        and conference_in_effect(
            slug, gender, season_year, conference, document=membership_document
        )
        == conference
    }


def division_for(
    slug: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """Return the division the programme's window names for one season.

    A division is the conference's own grouping of its members, spelled the
    way the conference prints it ("East", "Northwest", "Southwest" for
    Conference Carolinas from 2023). It is optional on a window and absent
    for every conference that publishes one table; a programme that moves
    between divisions has one window per division, the Trevecca shape with
    the conference unchanged. ``None`` when no window covers the season or
    the covering window carries no division.
    """
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return None

    genders = memberships.get(slug)
    if not isinstance(genders, dict):
        return None
    window = _window_for(genders.get(gender), season_year)
    if window is None:
        return None
    return _window_division(window)


def members_of(
    conference: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> set[str]:
    """Return every slug whose window for one season names the conference.

    The inverse of ``conference_for``, and the reason the windows exist: a
    programme can change conference inside the authored span (Trevecca played
    G-MAC men's soccer in 2022 and 2023 and GSC from 2024), so "who was in this
    conference" has a different answer per season. A schools.toml stanza
    carries one conference, the current one; only the windows can answer for
    an earlier season.
    """
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return set()

    members: set[str] = set()
    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not isinstance(genders, dict):
            continue
        if _window_conference(genders.get(gender), season_year) == conference:
            members.add(slug)
    return members


def divisions_of(
    conference: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return each member's division for one conference-season, by slug.

    The divisional companion of ``members_of``: only members whose window
    carries a division appear, so the map is empty for a conference that
    publishes one table and, once ``validate`` has passed, either empty or
    complete for any conference-season (the all-or-none rule).
    """
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return {}

    divisions: dict[str, str] = {}
    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not isinstance(genders, dict):
            continue
        window = _window_for(genders.get(gender), season_year)
        if window is None or window.get("conference") != conference:
            continue
        division = _window_division(window)
        if division is not None:
            divisions[slug] = division
    return divisions


def _window_for(windows: object, season_year: int) -> dict[str, Any] | None:
    """Walk one programme's windows for the one covering a season."""
    if not isinstance(windows, list):
        return None

    for window in windows:
        if not isinstance(window, dict):
            continue
        from_season = window.get("from_season")
        to_season = window.get("to_season")
        if (
            _is_year(from_season)
            and _is_year(to_season)
            and from_season <= season_year <= to_season
            and isinstance(window.get("conference"), str)
        ):
            return window
    return None


def _window_conference(windows: object, season_year: int) -> str | None:
    """Walk one programme's windows for the conference covering a season."""
    window = _window_for(windows, season_year)
    return None if window is None else window["conference"]


def _window_division(window: dict[str, Any]) -> str | None:
    division = window.get("division")
    return division if isinstance(division, str) and division.strip() else None


def is_conference_member(
    slug: str,
    gender: str,
    season_year: int,
    conference: str,
    *,
    document: dict[str, Any] | None = None,
) -> bool:
    """Return whether a programme belongs to a conference for one season."""
    return (
        conference_for(
            slug,
            gender,
            season_year,
            document=document,
        )
        == conference
    )


def covered_programmes(document: dict[str, Any]) -> set[tuple[str, str]]:
    """Return every slug and gender pair represented by the document."""
    memberships = document.get("memberships")
    if not isinstance(memberships, dict):
        return set()

    covered: set[tuple[str, str]] = set()
    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not isinstance(genders, dict):
            continue
        for gender in genders:
            if isinstance(gender, str):
                covered.add((slug, gender))
    return covered


def _is_year(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _season_span(
    document: dict[str, Any],
    errors: list[str],
) -> tuple[int, int] | None:
    seasons = document.get("seasons")
    if not isinstance(seasons, dict):
        errors.append("seasons must be an object with integer 'from' and 'to'")
        return None

    from_season = seasons.get("from")
    to_season = seasons.get("to")
    if not _is_year(from_season) or not _is_year(to_season):
        errors.append("seasons 'from' and 'to' must be integers")
        return None
    if from_season > to_season:
        errors.append(
            f"seasons 'from' must not exceed 'to' ({from_season} > {to_season})"
        )
        return None
    return from_season, to_season


def _declared_conferences(
    document: dict[str, Any],
    errors: list[str],
) -> set[str] | None:
    conferences = document.get("conferences")
    if not isinstance(conferences, list) or not all(
        isinstance(conference, str) for conference in conferences
    ):
        errors.append("conferences must be a list of strings")
        return None

    declared = set(conferences)
    if len(conferences) != len(declared):
        errors.append("conferences must not contain duplicate codes")

    missing_structural = sorted(STRUCTURAL_CODES - declared)
    if missing_structural:
        errors.append(
            f"conferences must declare structural codes: {missing_structural}"
        )
    return declared


def _validate_conference_profiles(
    document: dict[str, Any],
    errors: list[str],
    *,
    declared: set[str] | None,
) -> None:
    """Hold ``conference_profiles`` to the declared conference list.

    Every conference the file declares carries a profile, and a profile
    names a declared conference: the two lists are one set, so a conference
    cannot ship without its level and printed names, and a profile cannot
    quietly teach the schedule parser a name for a conference the rib does
    not collect. The structural codes are not conferences and carry none.
    """
    profiles = document.get(CONFERENCE_PROFILES)
    if not isinstance(profiles, dict):
        errors.append(
            f"{CONFERENCE_PROFILES} must be a JSON object keyed by conference code"
        )
        return

    if declared is not None:
        for conference in sorted(declared - STRUCTURAL_CODES - set(profiles)):
            errors.append(
                f"conference {conference!r} has no {CONFERENCE_PROFILES} entry; "
                "every declared conference carries its level and printed names"
            )

    for conference, profile in profiles.items():
        label = f"{CONFERENCE_PROFILES}[{conference!r}]"
        if not isinstance(conference, str) or not conference:
            errors.append(f"{CONFERENCE_PROFILES} has invalid conference key")
            continue
        if conference in STRUCTURAL_CODES:
            errors.append(f"{label} is a structural code, not a conference")
            continue
        if declared is not None and conference not in declared:
            errors.append(f"{label} names an undeclared conference code")
        if not isinstance(profile, dict):
            errors.append(f"{label} must be a JSON object")
            continue

        unknown = sorted(set(profile) - _PROFILE_FIELDS)
        if unknown:
            errors.append(f"{label} has unknown fields: {unknown}")

        level = profile.get("level")
        if level not in LEVELS:
            errors.append(f"{label} level must be one of {list(LEVELS)}, not {level!r}")

        names = profile.get("names")
        if not isinstance(names, list) or not names:
            errors.append(f"{label} names must be a non-empty list of strings")
        else:
            folded: set[str] = set()
            for name in names:
                if not isinstance(name, str) or not re.search(r"\w", name):
                    errors.append(
                        f"{label} names must be non-empty strings, not {name!r}"
                    )
                    continue
                key = " ".join(name.split()).casefold()
                if key in folded:
                    errors.append(f"{label} names repeat {name!r}")
                folded.add(key)

        if "code_is_word" in profile and not isinstance(profile["code_is_word"], bool):
            errors.append(f"{label} code_is_word must be true or false")


def _validate_standings_archives(
    document: dict[str, Any],
    errors: list[str],
    *,
    span: tuple[int, int] | None,
) -> None:
    """Check the optional per-conference standings-archive map.

    The map is evidence, not membership: it says where a conference-season's
    member list was read when the conference publishes no records page. Its
    key need not be a declared conference yet, because the archive is
    authored ahead of the windows it will support (the batch 4 SAC prep
    landed the ids before the windows); ``check-membership --standings``
    resolves the code at verification time and refuses one it cannot find.
    """
    archives = document.get(STANDINGS_ARCHIVES)
    if archives is None:
        return
    if not isinstance(archives, dict):
        errors.append(f"{STANDINGS_ARCHIVES} must be a JSON object keyed by code")
        return

    for conference, archive in archives.items():
        label = f"{STANDINGS_ARCHIVES}[{conference!r}]"
        if not isinstance(conference, str) or not conference:
            errors.append(f"{STANDINGS_ARCHIVES} has invalid conference key")
            continue
        if not isinstance(archive, dict):
            errors.append(f"{label} must be a JSON object")
            continue

        template = archive.get("url_template")
        if not isinstance(template, str) or "{id}" not in template:
            errors.append(f"{label} url_template must be a URL carrying '{{id}}'")

        seasons = archive.get("seasons")
        if not isinstance(seasons, dict) or not seasons:
            errors.append(f"{label} seasons must be a non-empty object")
            continue
        for season, page_id in seasons.items():
            if not isinstance(season, str) or not re.fullmatch(r"\d{4}", season):
                errors.append(f"{label} season key {season!r} must be a 4-digit year")
                continue
            if not isinstance(page_id, str) or not page_id.strip():
                errors.append(f"{label} season {season} id must be a non-empty string")
            if span is not None and not (span[0] <= int(season) <= span[1]):
                errors.append(
                    f"{label} season {season} falls outside {span[0]}-{span[1]}"
                )


def _validate_windows(
    programme: str,
    windows: list[object],
    errors: list[str],
    *,
    span: tuple[int, int] | None,
    declared: set[str] | None,
) -> None:
    if not windows:
        errors.append(f"{programme} must declare at least one membership window")
        return

    valid_ranges: list[tuple[int, int]] = []
    for index, window in enumerate(windows):
        label = f"{programme} window {index}"
        if not isinstance(window, dict):
            errors.append(f"{label} must be a JSON object")
            continue

        conference = window.get("conference")
        if declared is not None and conference not in declared:
            errors.append(f"{label} has unknown conference code {conference!r}")

        source = window.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"{label} must have a non-empty source citation")

        if "division" in window:
            division = window.get("division")
            if not isinstance(division, str) or not division.strip():
                errors.append(
                    f"{label} division must be a non-empty string, "
                    "spelled as the conference prints it"
                )

        from_season = window.get("from_season")
        to_season = window.get("to_season")
        if not _is_year(from_season):
            errors.append(f"{label} from_season must be an integer")
        if not _is_year(to_season):
            errors.append(f"{label} to_season must be an integer")
        if not _is_year(from_season) or not _is_year(to_season):
            continue
        if from_season > to_season:
            errors.append(
                f"{label} has from_season greater than to_season "
                f"({from_season} > {to_season})"
            )
            continue

        valid_ranges.append((from_season, to_season))
        if span is not None and (from_season < span[0] or to_season > span[1]):
            errors.append(
                f"{label} falls outside {span[0]}-{span[1]}: {from_season}-{to_season}"
            )

    if valid_ranges:
        authored_from = min(from_season for from_season, _ in valid_ranges)
        authored_to = max(to_season for _, to_season in valid_ranges)
        authored_counts = {year: 0 for year in range(authored_from, authored_to + 1)}
        for from_season, to_season in valid_ranges:
            for year in range(from_season, to_season + 1):
                authored_counts[year] += 1

        gaps = [year for year, count in authored_counts.items() if count == 0]
        if gaps:
            errors.append(
                f"{programme} has membership gaps at seasons {gaps}; "
                "cover them explicitly with an independent or non_member window"
            )

    if span is not None:
        season_counts = {year: 0 for year in range(span[0], span[1] + 1)}
        for from_season, to_season in valid_ranges:
            for year in range(
                max(from_season, span[0]),
                min(to_season, span[1]) + 1,
            ):
                season_counts[year] += 1

        overlaps = [year for year, count in season_counts.items() if count > 1]
        if overlaps:
            errors.append(f"{programme} has overlapping windows at seasons {overlaps}")


def _validate_divisions(
    document: dict[str, Any],
    errors: list[str],
    *,
    span: tuple[int, int] | None,
) -> None:
    """Hold every conference-season to the all-or-none division rule.

    A conference that prints divisions prints them for every member, so
    within one (conference, gender, season) either every resolving window
    carries a ``division`` or none does. A mix means an authoring slip (one
    window split for the move, its neighbours not yet labelled), and it is
    refused here naming the conference-season and the odd members, because
    the site groups a standings table by division only when the season's
    membership is wholly divisional.
    """
    if span is None:
        return
    memberships = document.get("memberships")
    if not isinstance(memberships, dict):
        return

    seasons: dict[tuple[str, str, int], dict[str, str | None]] = {}
    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not isinstance(genders, dict):
            continue
        for gender, windows in genders.items():
            if not isinstance(gender, str):
                continue
            for year in range(span[0], span[1] + 1):
                window = _window_for(windows, year)
                if window is None:
                    continue
                members = seasons.setdefault((window["conference"], gender, year), {})
                members[slug] = _window_division(window)

    for (conference, gender, year), members in sorted(seasons.items()):
        labelled = sorted(slug for slug, division in members.items() if division)
        unlabelled = sorted(slug for slug, division in members.items() if not division)
        if not labelled or not unlabelled:
            continue
        odd, wording = (
            (unlabelled, "without a division")
            if len(unlabelled) <= len(labelled)
            else (labelled, "carrying a division alone")
        )
        errors.append(
            f"{conference} {gender} {year} mixes divisions: every member's "
            "window must carry a division or none may; "
            f"{wording}: {odd}"
        )


def validate(
    document: dict[str, Any],
    *,
    schools: list[SchoolConfig] | None = None,
) -> list[str]:
    """Return every membership contract violation in a document."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["membership document root must be a JSON object"]

    if document.get("version") != 1:
        errors.append("version must be 1")

    span = _season_span(document, errors)
    declared = _declared_conferences(document, errors)
    _validate_conference_profiles(document, errors, declared=declared)
    _validate_standings_archives(document, errors, span=span)

    if schools is None:
        schools = load_schools()
    from src.sidearm_live import (
        level_identity_ambiguities,
        level_identity_collisions,
        member_alias_collisions,
    )

    # Identity is one table per gender, NCAA level and season, last stanza
    # wins, so a spelling two stanzas of one table claim is refused here
    # rather than resolved silently at collect time. Two stanzas never at
    # one level in one season share no table, and a key both claim is no
    # collision; the scope says which table the pair met in.
    for gender, scope, key, claimants in level_identity_collisions(
        schools, document=document
    ):
        named = " and ".join(f"{slug} ({label})" for slug, label in claimants)
        errors.append(
            f"identity collision ({gender}, {scope}): {key!r} is claimed by "
            f"{named}; drop the alias or set abbreviation_resolves = false on "
            "the stanzas that share the initialism"
        )
    # A folded key an institution word splits ("boston": Boston College and
    # Boston University) resolves to neither programme, so a stanza claiming
    # it bare would claim nothing; the bare spelling names both schools.
    for gender, scope, key, bare, worded in level_identity_ambiguities(
        schools, document=document
    ):
        claimed = " and ".join(f"{slug} ({label})" for slug, label in bare)
        split = " and ".join(f"{slug} ({label})" for slug, label in worded)
        errors.append(
            f"ambiguous identity ({gender}, {scope}): {key!r} is claimed bare "
            f"by {claimed}, but only an institution word tells apart the "
            f"programmes it folds to ({split}), so it resolves to none of "
            "them; drop the spelling or keep its institution word"
        )
    # A stanza with no level would sit in every level's table, the
    # cross-level capture the scope exists to prevent. A stanza conference
    # that is declared already answers through its own profile check, so
    # only a programme whose windows are all structural and whose stanza
    # names no declared conference is named here.
    for school in schools:
        slug = programme_slug(school.name)
        if declared is not None and school.conference in declared - STRUCTURAL_CODES:
            continue
        if (
            programme_level(
                slug,
                school.gender,
                span[0] if span is not None else 0,
                stanza_conference=school.conference,
                document=document,
            )
            is None
        ):
            errors.append(
                f"{slug}:{school.gender} has no NCAA level: no window names a "
                "conference with a profile and its stanza conference "
                f"{school.conference!r} has none, so it would resolve opponent "
                "text at every level"
            )
    # A member alias resolves only inside its conference's scope, so the one
    # spelling it may not share is a fellow member's.
    for gender, conference, key, claimants in member_alias_collisions(schools):
        named = " and ".join(f"{slug} ({label})" for slug, label in claimants)
        errors.append(
            f"member alias collision ({gender}, {conference}): {key!r} is "
            f"claimed by {named}; a member alias may not be a spelling another "
            "member of the same conference claims"
        )

    configured_programmes = {
        (programme_slug(school.name), school.gender) for school in schools
    }
    configured_slugs = {programme_slug(school.name) for school in schools}
    memberships = document.get("memberships")
    if not isinstance(memberships, dict):
        errors.append("memberships must be a JSON object")
        errors.append(f"missing configured programmes: {sorted(configured_programmes)}")
        return errors

    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not slug:
            errors.append(f"invalid institution slug key: {slug!r}")
            continue
        if slug not in configured_slugs:
            errors.append(f"unknown institution slug: {slug!r}")
        if not isinstance(genders, dict):
            errors.append(f"{slug} memberships must be a JSON object")
            continue

        for gender, windows in genders.items():
            programme = f"{slug}:{gender}"
            if not isinstance(gender, str) or not gender:
                errors.append(f"{slug} has invalid gender key: {gender!r}")
                continue
            if not isinstance(windows, list):
                errors.append(f"{programme} windows must be a JSON array")
                continue
            _validate_windows(
                programme,
                windows,
                errors,
                span=span,
                declared=declared,
            )

    _validate_divisions(document, errors, span=span)

    covered = covered_programmes(document)
    missing = sorted(configured_programmes - covered)
    if missing:
        errors.append(f"missing configured programmes: {missing}")

    return errors


# ── standings-archive evidence ───────────────────────────────────────────────
#
# check-membership never fetches: the windows are authored, each ``source``
# sentence names the page that proves it, and the script validates the file
# against schools.toml. For a conference whose site publishes per-season
# records pages (``stats.aspx?path=msoc&year=Y&conf=true``) that sentence is
# the whole method. The SAC publishes none (every year answers "no
# statistics available"); its member list per season lives in a standings
# archive addressed by an opaque id, and the id-to-season map is data below,
# so the same ``source`` sentence can name the page and the same offline
# check can read a captured copy of it back.


def standings_archive_url(
    conference: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """The archived standings page for one conference-season, if declared."""
    membership_document = document if document is not None else load_membership()
    archives = membership_document.get(STANDINGS_ARCHIVES)
    if not isinstance(archives, dict):
        return None
    archive = archives.get(conference)
    if not isinstance(archive, dict):
        return None
    template = archive.get("url_template")
    seasons = archive.get("seasons")
    if not isinstance(template, str) or not isinstance(seasons, dict):
        return None
    page_id = seasons.get(str(season_year))
    if not isinstance(page_id, str):
        return None
    return template.replace("{id}", page_id)


@dataclass(frozen=True)
class StandingsPage:
    """What a SideArm ``standings.aspx`` page says about itself."""

    season: int | None
    gender: str | None
    names: list[str]


_STANDINGS_HEADING = re.compile(
    r"(?P<season>\d{4})\s+(?P<gender>Men|Women)'s\s+Soccer\s+Standings"
)


def parse_standings_page(html: str) -> StandingsPage:
    """Read the team names off a SideArm ``standings.aspx`` page.

    The skin prints each row's school twice, in a wide cell and a narrow one
    (and the live 2026 skin prints the narrow one first), so the name is the
    first cell's link text, or the cell's own text on a skin that prints
    plain names. The season and gender come from the table's caption or the
    page heading ("2022 Men's Soccer Standings"); a page served for another
    season is refused by the caller rather than counted.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.sidearm-standings-table") or soup.select_one(
        "table.standings"
    )
    names: list[str] = []
    if table is not None:
        for row in table.select("tbody tr"):
            cell = row.find("td")
            if cell is None:
                continue
            link = cell.find("a")
            text = (link or cell).get_text(" ", strip=True)
            if text:
                names.append(text)

    heading_texts = []
    if table is not None and table.caption is not None:
        heading_texts.append(table.caption.get_text(" ", strip=True))
    heading_texts.extend(
        element.get_text(" ", strip=True) for element in soup.find_all(["h1", "h2"])
    )
    if soup.title is not None:
        heading_texts.append(soup.title.get_text(" ", strip=True))
    season: int | None = None
    gender: str | None = None
    for text in heading_texts:
        match = _STANDINGS_HEADING.search(text)
        if match:
            season = int(match.group("season"))
            gender = match.group("gender").lower()
            break
    return StandingsPage(season=season, gender=gender, names=names)


@dataclass(frozen=True)
class StandingsVerdict:
    """A captured standings page held against the authored windows."""

    url: str | None
    page: StandingsPage
    slugs: dict[str, str]
    expected: set[str]

    @property
    def read(self) -> set[str]:
        return set(self.slugs.values())

    @property
    def missing(self) -> set[str]:
        """Authored members the page does not list."""
        return self.expected - self.read

    @property
    def strangers(self) -> set[str]:
        """Names the page lists that no window claims for the conference."""
        return self.read - self.expected

    @property
    def agrees(self) -> bool:
        return not self.missing and not self.strangers


def verify_standings(
    html: str,
    conference: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
    schools: list[SchoolConfig] | None = None,
) -> StandingsVerdict:
    """Compare a standings page's team names with the resolved members.

    Names are minted the way opponent text is at collect time: inside the
    conference-season's resolution scope (so a member's ``member_aliases``
    claim its own spelling, "Lincoln University (Pa.)" on a CACC table or
    "Wayne State College" on an NSIC one), then through the gender's identity
    map (every spelling a stanza claims), falling back to ``programme_slug``
    for a school no stanza knows yet, so the verdict for a conference not yet
    in schools.toml still reads as the slugs its stanzas will mint.

    Raises ``ValueError`` when the page names another season or gender than
    the one asked about, so a wrong archive id cannot pass as agreement.
    """
    from src.sidearm_live import identity_aliases, opponent_slug, resolution_scope

    membership_document = document if document is not None else load_membership()
    page = parse_standings_page(html)
    if page.season is not None and page.season != season_year:
        raise ValueError(
            f"standings page is the {page.season} season, not {season_year}"
        )
    if page.gender is not None and page.gender != gender:
        raise ValueError(f"standings page is {page.gender}'s soccer, not {gender}'s")
    if not page.names:
        raise ValueError("standings page carries no team rows")

    # The table a collect of this conference-season resolves against: the
    # stanzas at the conference's NCAA level that season.
    stanzas = resolution_stanzas(
        schools if schools is not None else load_schools(),
        gender,
        conference,
        season_year,
        document=membership_document,
    )
    aliases = identity_aliases(stanzas, gender)
    expected = members_of(conference, gender, season_year, document=membership_document)
    scope = resolution_scope(
        stanzas,
        gender,
        set(expected),
        conference=conference,
        season=season_year,
        level=collecting_level(conference, document=membership_document),
    )
    slugs = {name: opponent_slug(name, aliases, scope=scope) for name in page.names}
    return StandingsVerdict(
        url=standings_archive_url(
            conference, season_year, document=membership_document
        ),
        page=page,
        slugs=slugs,
        expected=expected,
    )
