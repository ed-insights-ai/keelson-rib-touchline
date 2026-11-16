"""Collect published schedule, roster, statistics, and box-score pages into the board contract.

Layers are collected independently.  A site can serve a past season's schedule
from its DOM archive while its embedded payload still names the current season,
serve a roster for a year whose schedule it refuses, or the reverse — each
layer is proven and lands (or is refused with a named reason) on its own, so
one layer's failure never discards another's data.

Every run writes `data/coverage.json`, and the exit code reports only whether
that manifest was written.  Named gaps are data, not failures: a run that
collects twelve of thirteen programmes has produced twelve useful cells and one
cell carrying a reason, and discarding that would be worse than keeping it.

Fetches fan out scatter-gather across a worker pool, capped PER HOST rather
than globally: each programme's site is one host, a ``HostGate`` guarantees
no host ever sees two concurrent requests (with the historical polite
spacing preserved), and parallelism lives entirely across programmes.
``--serial`` collapses the pool to one worker for debugging; the outputs are
byte-identical either way, because every order-dependent assembly step — the
fixture dedupe, the season payloads, the coverage cells — runs serialized in
the main thread over the gathered results in request order.

Two things keep a bad minute from costing the whole run.  Each fetch task (a
programme's pages; one box score) runs behind its own budget, so a hung site
is recorded as that programme's gap while the rest of the run completes.
And progress is checkpointed as it confirms — coverage cells are merged to
disk per programme, box scores every few fetches — so a run killed at the
node budget keeps what it confirmed instead of writing nothing.  The season
files themselves are still assembled and written wholesale at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from src import coverage, paths
from src.fetch_pool import (
    GatedSession,
    HostGate,
    PacingPolicy,
    host_of,
    is_challenge_reason,
)
from src.config import DEFAULT_CONFIG, SchoolConfig, load_schools
from src.identity import IdentityReport, SeasonSources, resolve_matches
from src.membership import (
    MixedLevels,
    collect_level,
    collecting_level,
    conference_for,
    conference_in_effect,
    division_for,
    has_windows,
    load_membership,
    resolution_stanzas,
    stanzas_at_level,
)
from src.page_state import BoxArchive, PageStateStore
from src.programmes import load_programmes, programme_points
from src.recipes import PRESTO, SIDEARM, WMT, NoCollector, Recipe, live_recipe
from src.sidearm_live import (
    DEFAULT_LAYERS,
    LAYER_MATCHES,
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LAYER_STATS,
    STATE_COMPLETE,
    STATE_EMPTY,
    STATE_NO_COLLECTOR,
    STATE_UNAVAILABLE,
    LiveCollectionError,
    ProgrammeCollection,
    PublishedPage,
    ResolutionScope,
    boxscore_links,
    build_session,
    collect_match,
    collect_programme,
    conference_members,
    identity_aliases,
    parse_fingerprint,
    programme_slug,
    resolution_scope,
    write_raw_pages,
)

FIXTURES_SCHEMA = "touchline.fixtures/2"
ROSTERS_SCHEMA = "touchline.rosters/1"
STATS_SCHEMA = "touchline.stats/1"
MATCHES_SCHEMA = "touchline.matches/2"

# What a coverage cell names as its collector, per platform recipe.  A
# programme with no recipe at all (a platform the table does not know, or a
# slug no stanza configures) is filed under the default platform's name,
# as every cell was before a second platform existed.
COLLECTORS: Mapping[str, str] = {
    SIDEARM.platform: "sidearm-live",
    PRESTO.platform: "presto-live",
    WMT.platform: "wmt-live",
}
COLLECTOR = COLLECTORS[SIDEARM.platform]


def collector_name(school: SchoolConfig | None) -> str:
    """The coverage collector value for one programme's cells."""
    if school is None:
        return COLLECTOR
    return COLLECTORS.get(school.live_collector(), COLLECTOR)


# Sized off programme count, never above this: eight workers empty a
# conference-season in minutes while each individual host still sees at most
# one politely spaced request at a time.
DEFAULT_WORKERS = 8
# Seconds one isolated fetch task may run before it is recorded as a gap so
# the rest of the run completes.  A programme task is at most three page
# fetches, each already bounded by per-request timeouts and retries; five
# minutes is generous headroom, not a target.
DEFAULT_TASK_BUDGET = 300.0
# Box scores are the run's long network tail and have no sidecar cache, so
# the matches payload is checkpointed to disk every this-many new fetches —
# a killed run keeps them, and the next run's incremental harvest skips them.
MATCH_CHECKPOINT_EVERY = 10


def _scatter(
    executor: ThreadPoolExecutor,
    tasks: dict[str, Callable[[], object]],
    budget: float | None,
    on_settled: Callable[[str, object], None] | None = None,
) -> dict[str, object]:
    """Run isolated tasks, each behind its own budget measured from its start.

    Returns every key mapped to its result, to the exception it raised, or to
    a ``TimeoutError`` when it outlived its budget.  A timed-out task's thread
    cannot be killed — it is abandoned to finish in the background (every
    network read inside it is separately bounded by the request timeout)
    while the run completes without it, and its late result is discarded.  A
    queued task spends no budget until a worker actually starts it, so a
    small pool cannot time out work it never began.

    ``on_settled`` runs in the calling thread as each task settles, which is
    what lets progress be checkpointed in completion order while all
    order-dependent assembly stays with the caller, in request order.
    """
    starts: dict[str, float] = {}

    def tracked(key: str, call: Callable[[], object]) -> Callable[[], object]:
        def run() -> object:
            starts[key] = time.monotonic()
            return call()

        return run

    pending: dict[Future[object], str] = {
        executor.submit(tracked(key, call)): key for key, call in tasks.items()
    }
    settled: dict[str, object] = {}

    def settle(key: str, value: object) -> None:
        settled[key] = value
        if on_settled is not None:
            on_settled(key, value)

    while pending:
        done, _ = wait(set(pending), timeout=0.1, return_when=FIRST_COMPLETED)
        for future in done:
            key = pending.pop(future)
            try:
                settle(key, future.result())
            except Exception as exc:  # isolation is the point: a task's
                settle(key, exc)  # failure is its own named gap, never fatal
        if budget is None or budget <= 0:
            continue
        now = time.monotonic()
        for future, key in list(pending.items()):
            begun = starts.get(key)
            if begun is None or now - begun <= budget:
                continue
            if future.done():
                continue  # finished in the gap since wait(); next pass settles it
            pending.pop(future)
            future.cancel()
            settle(
                key,
                TimeoutError(f"did not finish within its {budget:.0f}s budget"),
            )
    return settled


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sync_reference(
    label: str, packaged: Path, target: Path, required_key: str
) -> str | None:
    """Mirror one packaged reference file into the data home.

    The packaged copy (version-controlled and reviewed) is the source of
    record; the data home's copy is a deployment artifact that exists so the
    data repo stays self-describing. Collect is the data home's one writer,
    so the mirror happens here: when the copies differ byte-for-byte, the
    packaged bytes replace the data home copy atomically. Nothing semantic
    is decided here.

    Returns a one-line description of what happened for the run log, or
    ``None`` when the mirror was already fresh. A sync that cannot happen is
    reported, never raised: the run's exit code stays about the coverage
    manifest, and the data-integrity workflow's sync checks are the loud
    guard for a mirror that stays stale.
    """
    try:
        text = packaged.read_text(encoding="utf-8")
    except OSError as error:
        return (
            f"{label} reference NOT synced: cannot read the packaged "
            f"source of record at {packaged} ({error}); the data home copy "
            "was left untouched"
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        return (
            f"{label} reference NOT synced: the packaged source of record "
            f"at {packaged} is not parseable JSON ({error}); the data home "
            "copy was left untouched"
        )
    if not isinstance(parsed, dict) or required_key not in parsed:
        return (
            f"{label} reference NOT synced: the packaged source of record "
            f"at {packaged} carries no {required_key} map; the data home "
            "copy was left untouched"
        )
    try:
        if target.read_text(encoding="utf-8") == text:
            return None
        state = "diverged from"
    except FileNotFoundError:
        state = "absent, mirrored from"
    except OSError as error:
        return (
            f"{label} reference NOT synced: cannot read {target} "
            f"({error}); fix the data home copy by hand"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return (
        f"{label} reference synced: the data home copy at {target} was "
        f"{state} the packaged source of record at {packaged}"
    )


def sync_membership_reference() -> str | None:
    """Mirror the rib's packaged membership.json into the data home."""
    return _sync_reference(
        "membership",
        paths.packaged_membership_path(),
        paths.membership_path(),
        "memberships",
    )


def _membership_document() -> dict[str, object] | None:
    """The membership document for one run, or None on an install without it.

    Loaded once rather than per programme.  A missing or unreadable file keeps
    the run alive on the stanza defaults instead of failing a collect over
    reference data it never needed before.
    """
    try:
        return load_membership()
    except (OSError, ValueError):
        return None


def _programme_points() -> dict[str, tuple[float, float]]:
    """Every programme's point for one run, or none on an install without them.

    Loaded once rather than per programme, like the membership document. A
    missing or unreadable programmes.json leaves the distance tiebreak
    unarmed, so every ambiguous name falls to the gender-wide rule.
    """
    try:
        return programme_points(load_programmes())
    except (OSError, ValueError):
        return {}


class UncoveredSeason(ValueError):
    """A programme with authored windows was asked for a season none covers."""

    def __init__(self, message: str, programmes: list[str]) -> None:
        super().__init__(message)
        self.programmes = programmes


def _authored_windows(slug: str, gender: str, document: dict[str, object]) -> str:
    """A programme's windows as the refusal prints them: "PSAC 2022-2023"."""
    genders = (document.get("memberships") or {}).get(slug) or {}  # type: ignore[union-attr]
    return ", ".join(
        f"{window['conference']} {window['from_season']}-{window['to_season']}"
        for window in genders.get(gender) or []
        if isinstance(window, dict)
    )


def uncovered_programmes(
    wanted: list[str],
    gender: str,
    season: int,
    conference: str,
    document: dict[str, object] | None,
) -> list[str]:
    """The asked-for programmes whose windows cover no season this collect reads.

    A programme with authored windows is governed by them alone, so one of
    these cannot be collected as a member of anything for the season: its
    stanza would file it under the conference it has left (Mercyhurst as a
    PSAC member in 2024).  A programme with no window at all is not among
    them (its stanza is all there is), and neither is a member carried
    forward past the conference's own authored horizon
    (``conference_in_effect``), which is what an extrapolated collect is.
    """
    if document is None:
        return []
    return [
        slug
        for slug in wanted
        if has_windows(slug, gender, document=document)
        and conference_in_effect(slug, gender, season, conference, document=document)
        is None
    ]


def refuse_uncovered(
    wanted: list[str],
    gender: str,
    season: int,
    conference: str,
    document: dict[str, object] | None,
) -> None:
    """Refuse a collect that would file a programme under a guessed conference."""
    uncovered = uncovered_programmes(wanted, gender, season, conference, document)
    if not uncovered or document is None:
        return
    named = "; ".join(
        f"{slug} (windows: {_authored_windows(slug, gender, document)})"
        for slug in uncovered
    )
    raise UncoveredSeason(
        f"refused: no {gender} membership window covers {season} for {named}. "
        "A programme with authored windows is in no conference for a season "
        f"none of them covers, so it cannot be collected as a {conference} "
        f"member for {season}. Author the window that was true in "
        "data/reference/membership.json (an independent or non_member window "
        "if that is what was true), or leave the programme out of the collect.",
        uncovered,
    )


def collect_identity(
    schools: list[SchoolConfig],
    gender: str,
    conference: str,
    season: int,
    *,
    document: dict[str, object] | None,
    points: dict[str, tuple[float, float]] | None = None,
    programmes: Iterable[str] = (),
) -> tuple[dict[str, str], set[str], ResolutionScope]:
    """What one conference-season collect resolves opponent text with.

    The identity map, the conference's member set and the resolution scope,
    in that order, the three inputs every schedule parse of the collect
    reads and its fingerprint hashes.

    Identity is scoped twice. By gender: an opponent string carries no
    gender, so an unscoped map resolves a men's fixture to a women's-only
    programme. And by NCAA level: the map and the scope are built from the
    stanzas at the collected conference's level for the season
    (``membership.resolution_stanzas``), so a Division II page's "Penn State
    Abington" stays itself instead of folding onto Division I "Penn State",
    and a Division I page's "California" is Cal, not California (Pa.). Text
    naming a school at another level mints its slug from the text. A
    structural code (independent, non_member) has no profile, so its level
    is the level of the ``programmes`` collected (``membership.collect_level``),
    and programmes at two levels in one collect raise ``MixedLevels``.

    Identity and membership are different questions and use different sets.
    The map spans every stanza at the level, so an out-of-conference
    opponent still gets a canonical slug; membership is one conference, so
    a cross-conference fixture is not derived into a conference game.
    Membership is per season: the window covering this season decides, the
    stanza's conference is only the default for a programme with no window.
    It is computed over every stanza, not the level's: a conference's
    members are at its level by the same windows, so the scoped list would
    give the same set, and this keeps the member test independent of the
    identity scope.

    Opponent text is written for the collecting conference's readers, so a
    printed name a member claims resolves to the member before any other
    programme (tl-b3v). One scope per collect, applied to every row of
    every page in it; with ``points`` an ambiguous name no member claims
    breaks by distance to the collecting school (tl-4sg.9.1).
    """
    level = collect_level(
        schools,
        gender,
        conference,
        season,
        programmes=programmes,
        document=document,
    )
    in_scope = stanzas_at_level(schools, gender, level, season, document=document)
    aliases = identity_aliases(in_scope, gender)
    members = conference_members(
        schools, gender, conference, season=season, document=document
    )
    scope = resolution_scope(
        in_scope,
        gender,
        members,
        conference=conference,
        season=season,
        points=points,
        level=level,
    )
    return aliases, members, scope


def programme_conference(
    slug: str,
    school: SchoolConfig,
    gender: str,
    season: int,
    document: dict[str, object] | None,
    *,
    conference: str | None = None,
) -> str:
    """The conference a configured programme played in for one season.

    Membership is per season.  The stanza carries one ``conference``, the
    current one; a programme that changed conference inside the window has a
    second window on the same slug, and the fixtures file for an earlier
    season must name the conference it played in then, not the one it plays
    in now.  The stanza is only the default for a programme the reference
    authors no window for (or with no membership document at all).

    A programme with authored windows is answered by them alone.  With the
    collect's ``conference``, a member carried forward past that conference's
    authored horizon is still its member (``conference_in_effect``), the same
    carry forward that resolved the collect's members; any other season no
    window covers raises ``UncoveredSeason`` rather than name the stanza's
    conference, which ``collect`` has already refused before any fetch.
    """
    if document is None or not has_windows(slug, gender, document=document):
        return school.conference
    declared = (
        conference_for(slug, gender, season, document=document)
        if conference is None
        else conference_in_effect(slug, gender, season, conference, document=document)
    )
    if declared is None:
        raise UncoveredSeason(
            f"{slug} has no {gender} membership window covering {season} "
            f"(windows: {_authored_windows(slug, gender, document)})",
            [slug],
        )
    return declared


def programme_division(
    slug: str,
    gender: str,
    season: int,
    document: dict[str, object] | None,
) -> str | None:
    """The division the programme's window names for one season, if any.

    Divisions are the conference's own grouping of its members (Conference
    Carolinas prints East, Northwest and Southwest from 2023), optional on a
    window and never on a stanza, so the fixtures file carries one beside
    ``conference`` only when the window covering the season names it. The
    site groups a standings table by division when every programme of the
    conference-season carries one; ``check-membership`` refuses a mix.
    """
    if document is None:
        return None
    return division_for(slug, gender, season, document=document)


def sync_programmes_reference() -> str | None:
    """Mirror the rib's built programmes.json into the data home (tl-891)."""
    return _sync_reference(
        "programmes",
        paths.packaged_programmes_path(),
        paths.programmes_path(),
        "programmes",
    )


def _merge_conference_claim(
    winner: dict[str, object], loser: dict[str, object]
) -> None:
    """Resolve one conference flag from a game's two published rows.

    A publisher's own marking (no ``conference_game_source``) outranks a flag
    we derived from membership; between two claims of the same rank a positive
    marking wins, because themes that mark conference games at all only mark
    the positives.
    """

    def claim(row: dict[str, object]) -> tuple[int, bool]:
        published = "conference_game_source" not in row
        return (1 if published else 0, bool(row.get("conference_game")))

    winning_rank, winning_flag = claim(winner)
    losing_rank, losing_flag = claim(loser)
    if losing_rank > winning_rank or (
        losing_rank == winning_rank and losing_flag and not winning_flag
    ):
        winner["conference_game"] = losing_flag
        source = loser.get("conference_game_source")
        winner.pop("conference_game_source", None)
        if source is not None:
            winner["conference_game_source"] = source


def _dedupe_fixtures(
    fixtures: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    by_match: dict[tuple[str, str, str], dict[str, object]] = {}
    duplicates = 0
    for fixture in fixtures:
        home = str(fixture["home"])
        away = str(fixture["away"])
        pair = sorted((home, away))
        key = (str(fixture["date"]), pair[0], pair[1])
        existing = by_match.get(key)
        if existing is None:
            by_match[key] = dict(fixture)
            continue
        duplicates += 1
        # Prefer the source that has reached the later lifecycle stage, then
        # retain whichever published more detail — but never lose detail the
        # other side published: each site is authoritative for its own extras
        # (kickoff time, facility, an exhibition marking), and the conference
        # claim resolves by rank.
        rank = {"scheduled": 0, "postponed": 1, "cancelled": 1, "live": 2, "final": 3}
        existing_score = rank.get(str(existing["status"]), 0) * 10 + len(existing)
        candidate_score = rank.get(str(fixture["status"]), 0) * 10 + len(fixture)
        winner, loser = (
            (dict(fixture), existing)
            if candidate_score > existing_score
            else (existing, dict(fixture))
        )
        for field in ("time", "venue", "match_type", "neutral"):
            if field not in winner and field in loser:
                winner[field] = loser[field]
        # A forfeit is one side's published word too, and it names a side,
        # so it crosses a reversed home/away pair by flipping (bead tl-wyv).
        if "forfeit" not in winner and "forfeit" in loser:
            side = str(loser["forfeit"])
            if loser["home"] != winner["home"]:
                side = "away" if side == "home" else "home"
            winner["forfeit"] = side
        # Two finals can tie on lifecycle rank when one side published a
        # score and the other published only completion; the detail count
        # must never decide a published score pair away.  Finals only — a
        # live row's score is in progress, not a result.  And oriented by
        # team id, because the match key groups reversed home/away rows.
        if (
            str(winner["status"]) == "final"
            and str(loser["status"]) == "final"
            and "home_score" not in winner
            and "home_score" in loser
            and "away_score" in loser
        ):
            if loser["home"] == winner["home"]:
                winner["home_score"] = loser["home_score"]
                winner["away_score"] = loser["away_score"]
            else:
                winner["home_score"] = loser["away_score"]
                winner["away_score"] = loser["home_score"]
        _merge_conference_claim(winner, loser)
        _merge_postseason_facts(winner, loser)
        by_match[key] = winner
    values = sorted(
        by_match.values(), key=lambda value: (str(value["date"]), str(value["id"]))
    )
    return values, duplicates


def _shootout_by_slug(fixture: dict[str, object]) -> tuple[str, int, int] | None:
    """A row's shootout as (winner, winner's count, loser's count), orientation-free."""
    shootout = fixture.get("shootout")
    if not isinstance(shootout, dict):
        return None
    winner = str(shootout["winner"])
    home, away = int(shootout["home"]), int(shootout["away"])  # type: ignore[arg-type]
    if winner == fixture["home"]:
        return winner, home, away
    return winner, away, home


def _merge_postseason_facts(
    winner: dict[str, object], loser: dict[str, object]
) -> None:
    """Carry the stage and shootout across one match's two rows.

    A fact only one row published is kept: each page is authoritative for
    what it printed, and 8 of the 39 2025 NCAA ties appear on one school's
    schedule only. Two rows that contradict each other are not settled
    here. A different phase or competition leaves the kept row ``unknown``,
    and a different shootout leaves it with none, each printed, so no single
    copy speaks for a match its two publishers disagree on.
    """
    mine, theirs = winner.get("stage"), loser.get("stage")
    if isinstance(theirs, dict):
        if not isinstance(mine, dict):
            winner["stage"] = dict(theirs)
        elif (mine.get("phase"), mine.get("competition")) != (
            theirs.get("phase"),
            theirs.get("competition"),
        ):
            print(
                f"stage disagreement on {winner['id']} / {loser['id']}: "
                f"{mine} v {theirs}; stored unknown",
                flush=True,
            )
            winner["stage"] = {"phase": "unknown"}
        else:
            for field in ("round_published", "source"):
                if field not in mine and field in theirs:
                    mine[field] = theirs[field]
    level = "home_score" in winner and winner.get("home_score") == winner.get(
        "away_score"
    )
    if not level:
        return
    if "result_published" not in winner and "result_published" in loser:
        winner["result_published"] = loser["result_published"]
    own, other = _shootout_by_slug(winner), _shootout_by_slug(loser)
    if other is None:
        return
    if own is None:
        decided, high, low = other
        winner_is_home = decided == winner["home"]
        winner["shootout"] = {
            "winner": decided,
            "home": high if winner_is_home else low,
            "away": low if winner_is_home else high,
        }
    elif own != other:
        print(
            f"shootout disagreement on {winner['id']} / {loser['id']}: "
            f"{own} v {other}; stored none",
            flush=True,
        )
        winner.pop("shootout", None)


def postseason_strangers(
    fixtures: list[dict[str, object]], stanza_slugs: set[str]
) -> list[str]:
    """One line per postseason row naming a side no schools.toml stanza mints.

    A bracket is drawn from these rows, so a side printed under a spelling
    no stanza claims ("Wilimington (DE) University" before its alias) splits
    one programme into two and breaks the bracket's path. The collect names
    them rather than refusing: the fix is an alias, made by hand.
    """
    lines: list[str] = []
    for fixture in fixtures:
        stage = fixture.get("stage")
        if not isinstance(stage, dict) or stage.get("phase") != "postseason":
            continue
        for side in ("home", "away"):
            slug = str(fixture[side])
            if slug not in stanza_slugs:
                lines.append(
                    f"postseason side with no stanza: {fixture['date']}, "
                    f"{slug} ({fixture['id']})"
                )
    return lines


def _borrow_twin_exhibitions(
    fixtures: list[dict[str, object]],
    *,
    season: int,
    gender: str,
    conference: str,
    fixtures_dir: Path,
) -> int:
    """Stamp ``match_type = "exhibition"`` on a freshly parsed row whose twin,
    in another conference's season file, carries that mark (bead tl-1go).

    A friendly is a property of the match, not of the page that printed it,
    and ``_dedupe_fixtures`` already carries the mark across the two rows of
    one file.  Across files nothing did: Lander's page marks its preseason
    games exhibition, Southern Wesleyan's and Newberry's pages do not, and the
    three rows sit in three conference files.  This step reads the OTHER
    conferences' season files for the same season and gender (the siblings
    ``{season}-{gender}-*.json`` of this collect's own file, which is never
    read), keys them by (date, sorted slug pair) exactly as the dedupe does,
    and borrows the one mark.  Nothing else crosses: not neutral, forfeit,
    time, venue or scores, and ``conference_game`` is not touched.

    Two rules bound it.  Own text always wins: a row that already carries any
    ``match_type`` is never touched, whatever the twin says.  And it applies
    to the freshly parsed rows only, never to a previously stored row's
    stamped value: a mark borrowed yesterday drops on its own if the other
    side withdraws it, because tomorrow's parse starts from the page again
    and this step starts from the sibling files again.  It is a pure function
    of (this collect's rows, the sibling files on disk), so ``_assemble``'s
    byte-identical guarantee holds.  A missing or unreadable sibling is
    skipped, never fatal.  One line per borrow goes to the collect log so the
    cadence log explains why a file changed when its own source did not.
    Mutates the rows in place and returns the number borrowed.
    """
    own = f"{season}-{gender}-{programme_slug(conference)}.json"
    twins: dict[tuple[str, str, str], str] = {}
    try:
        siblings = sorted(fixtures_dir.glob(f"{season}-{gender}-*.json"))
    except OSError:
        siblings = []
    for sibling in siblings:
        if sibling.name == own:
            continue
        try:
            payload = json.loads(sibling.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        rows = payload.get("fixtures")
        if not isinstance(rows, list):
            continue
        source = payload.get("conference")
        if not isinstance(source, str) or not source:
            source = sibling.stem.removeprefix(f"{season}-{gender}-")
        for row in rows:
            if not isinstance(row, dict) or row.get("match_type") != "exhibition":
                continue
            try:
                pair = sorted((str(row["home"]), str(row["away"])))
                key = (str(row["date"]), pair[0], pair[1])
            except KeyError:
                continue
            twins.setdefault(key, source)
    if not twins:
        return 0
    borrowed = 0
    for fixture in fixtures:
        if "match_type" in fixture:
            continue
        pair = sorted((str(fixture["home"]), str(fixture["away"])))
        source = twins.get((str(fixture["date"]), pair[0], pair[1]))
        if source is None:
            continue
        fixture["match_type"] = "exhibition"
        borrowed += 1
        print(
            f"exhibition borrowed: {fixture['date']}, "
            f"{fixture['home']} v {fixture['away']}, from {source}",
            flush=True,
        )
    return borrowed


def _stored_match_current(
    stored: dict[str, object], fixture: dict[str, object]
) -> bool:
    """Whether a stored box score still stands for this fixture, so its
    re-fetch can be skipped.

    The ruled vocabulary decides every branch.  "Played" means final WITH a
    published score, and only a played fixture whose stored detail carries the
    same score pair is skippable.  A silent final — final with no published
    score — is never skipped on stored data alone: tomorrow's collect retries
    silence, and a skip here would blind the pipeline to a late-published
    score.  A fixture whose result moved (a correction) no longer matches its
    stored detail and is re-fetched.  The score comparison respects the stored
    orientation when the match was oriented; an unoriented detail (a draw)
    compares the pair regardless of order.
    """
    home_score = fixture.get("home_score")
    away_score = fixture.get("away_score")
    if not isinstance(home_score, int) or not isinstance(away_score, int):
        return False
    teams = stored.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        return False
    scores = [team.get("score") if isinstance(team, dict) else None for team in teams]
    if not all(isinstance(score, int) for score in scores):
        return False
    home_index = stored.get("home_index")
    if home_index in (0, 1):
        return (
            scores[home_index] == home_score and scores[1 - home_index] == away_score  # type: ignore[index]
        )
    return sorted(scores) == sorted([home_score, away_score])  # type: ignore[type-var]


def _stored_box(
    fixture: dict[str, object],
    stored: dict[str, object],
    owners: list[tuple[str, Recipe]],
    store: PageStateStore,
    season: int,
) -> tuple[dict[str, object] | None, str, float]:
    """The record a stored box score stands on this run, which of the three
    reuse branches it took, and the wall time a reparse cost.

    ``current``: the archived page's sidecar carries the current parse
    fingerprint, so the stored record is reused as it stands, no fetch and
    no parse (today's path).  ``reparsed``: the page is archived but its
    sidecar is missing or names another fingerprint (the parser changed),
    so the bytes are read from disk through the recipe's own proof and
    parser, the sidecar is rewritten, and the fresh parse is the record.
    ``unarchived``: no archived page (a box collected before box pages
    joined the cache), so the stored record is reused; nothing fetches on
    its own, a ``--refetch`` archives it.  A reparse the current parser
    refuses returns no record (``refused``) and the site is asked, as for a
    fixture whose result moved.

    ``owners`` are the programmes whose schedule page could have linked the
    box, in the order the fetch tries them; the first with an archived page
    answers.  Pure over the disk state, run serially in fixture order.
    """
    fixture_id = str(fixture["id"])
    for owner, recipe in owners:
        archive = BoxArchive(
            store, owner, fixture_id, parse_fingerprint(season, *recipe.parse_identity)
        )
        state = archive.load()
        if state is not None and state.parsed is not None:
            return stored, "current", 0.0
        html_path = archive.html_path()
        if not html_path.is_file():
            continue
        started = time.perf_counter()
        source = str(stored.get("source_url") or "")
        try:
            page = PublishedPage(
                state.requested_url if state else source,
                state.final_url if state else source,
                html_path.read_text(encoding="utf-8"),
            )
            detail = recipe.parse_match(page, season, fixture)
        except (LiveCollectionError, OSError) as exc:
            print(
                f"match {fixture_id}: the archived box-score page no longer "
                f"parses ({exc}); fetching it",
                flush=True,
            )
            return None, "refused", time.perf_counter() - started
        archive.save(
            requested_url=page.requested_url,
            final_url=page.final_url,
            html=page.html,
            parsed=detail,
            signature=state.signature if state else None,
            with_html=False,
        )
        return detail, "reparsed", time.perf_counter() - started
    return stored, "unarchived", 0.0


def collect(
    *,
    season: int,
    gender: str,
    conference: str,
    wanted: list[str],
    layers: tuple[str, ...],
    config_path: Path,
    membership_extrapolated: bool,
    stored_matches: dict[str, dict[str, object]] | None = None,
    refetch: bool = False,
    workers: int | None = None,
    task_budget: float | None = DEFAULT_TASK_BUDGET,
    matches_checkpoint: Callable[[dict[str, object]], None] | None = None,
    gate: HostGate | None = None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, object]],
    list[str],
    int,
]:
    # load_schools has refused any two enabled stanzas of one gender that mint
    # the same slug, so the dicts below cannot drop a programme by keeping the
    # later stanza; a same-named institution reaches here under its own slug.
    schools = load_schools(config_path)
    # `enabled = false` records a programme whose site we have no working recipe
    # for.  Attempting it anyway spends a request to produce a failure we already
    # predicted, and — before the exit contract was fixed — sank the whole run.
    candidates = {
        programme_slug(school.name): school
        for school in schools
        if school.gender == gender and school.enabled
    }
    disabled = {
        programme_slug(school.name): school
        for school in schools
        if school.gender == gender and not school.enabled
    }
    membership_document = _membership_document()
    # Before any fetch: a programme whose authored windows cover no season
    # this collect reads would be filed under its stanza's conference, the
    # one it has left.  The run stops naming it instead.
    refuse_uncovered(wanted, gender, season, conference, membership_document)
    aliases, members, scope = collect_identity(
        schools,
        gender,
        conference,
        season,
        document=membership_document,
        points=_programme_points(),
        programmes=wanted,
    )
    results = []
    errors: list[str] = []
    cells: dict[str, dict[str, object]] = {}
    root = paths.data_root()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # The conditional-fetch memory: with it, an unchanged page answers a cheap
    # validation request instead of a re-parse.  --refetch collects as if the
    # data home had never seen these pages.
    page_cache = None if refetch else PageStateStore(root, season, gender)

    if workers is None:
        workers = max(1, min(DEFAULT_WORKERS, len(wanted)))

    # One gate for the whole run: the per-host cap of one in-flight request,
    # with polite spacing and per-host pacing, holds across both phases and
    # every worker — so two programmes on one host share one pace.  A
    # PrestoSports host starts paced (the platform is known to challenge a
    # burst); the WMT statistics host is paced by the recipe before its
    # first request there (one host shared by every WMT programme); any
    # host is paced from its first observed HTTP 202.
    # Sessions are per thread — requests makes no thread-safety promise.
    if gate is None:
        gate = HostGate(policy=PacingPolicy.from_env())
    for school in candidates.values():
        if live_recipe(school.live_collector()) is PRESTO:
            gate.presume_paced(host_of(school.base_url))
    thread_state = threading.local()

    def thread_session():
        session = getattr(thread_state, "session", None)
        if session is None:
            session = build_session(GatedSession(gate))
            thread_state.session = session
        return session

    def record_into(
        target: dict[str, dict[str, object]],
        programme: str,
        layer: str,
        state: str,
        **extra: object,
    ) -> None:
        target[coverage.cell_key(season, gender, programme, layer)] = {
            "season": season,
            "gender": gender,
            "programme": programme,
            "layer": layer,
            "state": state,
            "confirmed_at": now,
            "collector": collector_name(
                candidates.get(programme) or disabled.get(programme)
            ),
            **{key: value for key, value in extra.items() if value is not None},
        }

    def record(programme: str, layer: str, state: str, **extra: object) -> None:
        record_into(cells, programme, layer, state, **extra)

    def checkpoint_cells(batch: dict[str, dict[str, object]]) -> None:
        """Merge confirmed cells to disk NOW, so a run killed at the node
        budget keeps them.  Never fatal — the final merge in main() is the
        authoritative write and reports its own failure."""
        if not batch:
            return
        try:
            coverage.write_coverage(
                root, coverage.merge_cells(root, batch, updated_at=now)
            )
        except (OSError, ValueError):
            pass

    executor = ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="touchline-fetch"
    )
    try:
        collections: dict[str, object] = {}
        programme_cells: dict[str, dict[str, dict[str, object]]] = {}
        programme_errors: dict[str, list[str]] = {}

        def programme_task(school) -> object:
            return collect_programme(
                school,
                season,
                aliases,
                session=thread_session(),
                layers=layers,
                members=members,
                page_cache=page_cache,
                scope=scope,
            )

        def settle_programme(slug: str, value: object) -> None:
            """As each programme finishes (in completion order, main thread):
            archive its pages and checkpoint its cells.  Everything whose
            order matters is assembled later, in request order."""
            batch: dict[str, dict[str, object]] = {}
            gaps: list[str] = []
            if isinstance(value, ProgrammeCollection):
                collections[slug] = value
                write_raw_pages(root, value, season, gender)
                for layer in layers:
                    outcome = value.outcomes.get(layer)
                    if outcome is None:
                        continue
                    record_into(
                        batch,
                        slug,
                        layer,
                        outcome.state,
                        count=outcome.count,
                        reason=outcome.reason,
                        source_url=outcome.source_url,
                        # A run that legitimately did nothing must be legible
                        # as verified-unchanged, not mistakable for a gap.
                        verified="unchanged" if outcome.unchanged else None,
                        # Rows read but deliberately not minted (a hosted
                        # other-match), named so the manifest says why the
                        # page's count and the fixture count differ.
                        skips=list(outcome.skips) or None,
                    )
                    if outcome.reason:
                        gaps.append(f"{slug} {layer}: {outcome.reason}")
            else:
                # A hung or crashed collector is ITS programme's named gap;
                # the rest of the run completes around it.
                reason = (
                    f"[{season}] programme collection {value}"
                    if isinstance(value, TimeoutError)
                    else f"[{season}] programme collector failed: {value}"
                )
                for layer in layers:
                    record_into(batch, slug, layer, STATE_UNAVAILABLE, reason=reason)
                gaps.append(f"{slug}: {reason}")
            programme_cells[slug] = batch
            programme_errors[slug] = gaps
            checkpoint_cells(batch)

        _scatter(
            executor,
            {
                slug: partial(programme_task, candidates[slug])
                for slug in wanted
                if slug in candidates
            },
            task_budget,
            on_settled=settle_programme,
        )

        # One more chance for what a challenge refused: after the hosts'
        # cool-down, each challenged programme is collected again exactly
        # once, and its retry is kept only when it closed gaps.
        challenged = [
            slug
            for slug in wanted
            if slug in candidates
            and any(is_challenge_reason(gap) for gap in programme_errors.get(slug, []))
        ]
        if challenged:
            before = {
                slug: (
                    collections.get(slug),
                    programme_cells[slug],
                    programme_errors[slug],
                )
                for slug in challenged
            }
            print(
                f"pacing: {len(challenged)} programme(s) refused by a challenge; "
                f"retrying once after the cool-down: {', '.join(challenged)}",
                flush=True,
            )
            gate.wait_out_cooldowns()

            def settle_retry(slug: str, value: object) -> None:
                settle_programme(slug, value)
                previous, cells_then, gaps_then = before[slug]
                if len(programme_errors[slug]) > len(gaps_then):
                    if previous is None:
                        collections.pop(slug, None)
                    else:
                        collections[slug] = previous
                    programme_cells[slug] = cells_then
                    programme_errors[slug] = gaps_then
                    checkpoint_cells(cells_then)

            _scatter(
                executor,
                {
                    slug: partial(programme_task, candidates[slug])
                    for slug in challenged
                },
                task_budget,
                on_settled=settle_retry,
            )

        for slug in wanted:
            school = candidates.get(slug)
            if school is None:
                blocked = disabled.get(slug)
                reason = (
                    f"{slug}: {blocked.notes or 'programme is disabled in schools.toml'}"
                    if blocked is not None
                    else f"{slug}: no configured {gender} programme recipe"
                )
                errors.append(reason)
                for layer in layers:
                    record(slug, layer, coverage.STATE_NO_COLLECTOR, reason=reason)
                continue
            value = collections.get(slug)
            if isinstance(value, ProgrammeCollection):
                results.append(value)
            cells.update(programme_cells.get(slug, {}))
            errors.extend(programme_errors.get(slug, []))

        # Where the scope re-pointed a printed name away from the gender-wide
        # reading, the run log says so once per distinct text.
        for line in scope.notes():
            print(line, flush=True)

        return _assemble(
            season=season,
            gender=gender,
            conference=conference,
            wanted=wanted,
            layers=layers,
            membership_extrapolated=membership_extrapolated,
            membership_document=membership_document,
            candidates=candidates,
            results=results,
            errors=errors,
            cells=cells,
            now=now,
            data_root=root,
            stored_matches=stored_matches,
            refetch=refetch,
            executor=executor,
            task_budget=task_budget,
            gate=gate,
            thread_session=thread_session,
            record_into=record_into,
            checkpoint_cells=checkpoint_cells,
            matches_checkpoint=matches_checkpoint,
        )
    finally:
        # Never wait on an abandoned straggler: its work is already recorded
        # as a gap, and each of its network reads is separately bounded.
        executor.shutdown(wait=False, cancel_futures=True)


def _recipe_for(school: SchoolConfig) -> Recipe | None:
    """The platform recipe for one school's pages.

    The SideArm recipe is rebuilt around this module's own ``boxscore_links``
    and ``collect_match`` names: they are the seams a dry run or a test
    replaces for one box-score fetch, so the recipe must read them at call
    time rather than carry the functions it was built with.
    """
    recipe = live_recipe(school.live_collector())
    if recipe is SIDEARM:
        return replace(
            recipe, boxscore_links=boxscore_links, collect_match=collect_match
        )
    return recipe


def _assemble(
    *,
    season: int,
    gender: str,
    conference: str,
    wanted: list[str],
    layers: tuple[str, ...],
    membership_extrapolated: bool,
    membership_document: dict[str, object] | None,
    candidates: dict[str, object],
    results: list,
    errors: list[str],
    cells: dict[str, dict[str, object]],
    now: str,
    data_root: Path,
    stored_matches: dict[str, dict[str, object]] | None,
    refetch: bool,
    executor: ThreadPoolExecutor,
    task_budget: float | None,
    gate: HostGate,
    thread_session: Callable[[], object],
    record_into: Callable[..., None],
    checkpoint_cells: Callable[[dict[str, dict[str, object]]], None],
    matches_checkpoint: Callable[[dict[str, object]], None] | None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, object]],
    list[str],
    int,
]:
    """Serialized assembly: every payload is built in the main thread, in
    request order, so the outputs are byte-identical however the parallel
    fetches interleaved."""

    all_fixtures = [fixture for result in results for fixture in result.fixtures]
    fixtures, duplicates = _dedupe_fixtures(all_fixtures)
    # A friendly one side marked and the other did not, across two conference
    # files: borrow the mark from the twin row before the season file is
    # written (bead tl-1go).  Read-only over the sibling files, own text wins.
    borrowed = _borrow_twin_exhibitions(
        fixtures,
        season=season,
        gender=gender,
        conference=conference,
        fixtures_dir=data_root / "data" / "fixtures",
    )
    if borrowed:
        print(
            f"borrowed {borrowed} exhibition mark(s) from the other conferences' "
            f"season files for the same match",
            flush=True,
        )

    def _served(layer: str) -> list[str]:
        return [
            result.slug
            for result in results
            if result.state(layer) in {STATE_COMPLETE, STATE_EMPTY}
        ]

    schedule_served = set(_served(LAYER_SCHEDULE))
    roster_served = set(_served(LAYER_ROSTER))

    fixture_payload: dict[str, object] = {
        "schema": FIXTURES_SCHEMA,
        "season": season,
        "gender": gender,
        "conference": conference,
        "collected_at": now,
        "membership_extrapolated": membership_extrapolated,
        "conference_game_source": "published:schedule-page",
        "programmes": [
            {
                "slug": slug,
                "name": candidates[slug].display()
                if slug in candidates
                else slug.replace("-", " ").title(),
                # Membership is per season: the window wins, the stanza is
                # the default; a stranger is filed under the collected one.
                "conference": programme_conference(
                    slug,
                    candidates[slug],
                    gender,
                    season,
                    membership_document,
                    conference=conference,
                )
                if slug in candidates
                else conference,
                **(
                    {"abbr": candidates[slug].abbreviation}
                    if slug in candidates and candidates[slug].abbreviation
                    else {}
                ),
                **(
                    {"division": division}
                    if (
                        division := programme_division(
                            slug, gender, season, membership_document
                        )
                    )
                    else {}
                ),
            }
            for slug in wanted
        ],
        "fixtures": fixtures,
    }
    schedule_missing = [slug for slug in wanted if slug not in schedule_served]
    if schedule_missing and LAYER_SCHEDULE in layers:
        fixture_payload["missing"] = schedule_missing

    rosters = {
        result.slug: {
            "programme": result.slug,
            "source_url": result.roster_url,
            "players": result.players,
        }
        for result in results
        if result.state(LAYER_ROSTER) in {STATE_COMPLETE, STATE_EMPTY}
    }
    roster_payload: dict[str, object] = {
        "schema": ROSTERS_SCHEMA,
        "season": season,
        "gender": gender,
        "collected_at": now,
        "rosters": rosters,
    }
    roster_missing = sorted(
        {slug for slug in wanted if slug not in roster_served}
        | {
            result.slug
            for result in results
            if not result.players and result.slug in roster_served
        }
    )
    if roster_missing and LAYER_ROSTER in layers:
        roster_payload["missing"] = roster_missing

    stats_served = set(_served(LAYER_STATS))
    stats_teams = {
        result.slug: {
            "programme": result.slug,
            "source_url": result.stats_url,
            "players": result.stat_players or [],
            "keepers": result.stat_keepers or [],
        }
        for result in results
        if result.state(LAYER_STATS) in {STATE_COMPLETE, STATE_EMPTY}
    }
    stats_payload: dict[str, object] = {
        "schema": STATS_SCHEMA,
        "season": season,
        "gender": gender,
        "collected_at": now,
        "teams": stats_teams,
    }
    stats_missing = sorted(
        {slug for slug in wanted if slug not in stats_served}
        | {
            result.slug
            for result in results
            if result.slug in stats_served
            and not (result.stat_players or result.stat_keepers)
        }
    )
    if stats_missing and LAYER_STATS in layers:
        stats_payload["missing"] = stats_missing

    matches: dict[str, object] = {}
    matches_missing: dict[str, str] = {}
    # Who each box-score line is (bead tl-y8q): the page publishes an id for
    # the owner's roster only, so every line gets a ``player_ref`` resolved
    # from the season's own files — this run's rosters, the sibling
    # conferences' rosters and boxes on disk, and the boxes this run holds.
    # A function of those files, recomputed on every write.
    identity_sources = SeasonSources()
    identity_sources.load_disk(
        data_root, season, gender, exclude_matches=programme_slug(conference)
    )
    identity_sources.add_rosters(roster_payload)

    def resolve_identities(held: dict[str, dict[str, object]]) -> IdentityReport:
        identity_sources.add_matches({"matches": held}, {"fixtures": fixtures})
        return resolve_matches(held, fixtures, identity_sources)

    if LAYER_MATCHES in layers:
        # One box score per deduplicated fixture: a conference game sits on two
        # schedules, and each publishes its own link to the same match under its
        # own game id.  Every published (owner, id) pair is a candidate, so a
        # missing or refusing link on the surviving row's site can still be
        # collected through the other programme's link.
        # Each link is fetched by its own site's recipe, whichever programme's
        # row survived the fold.  A platform with no box-score collector yet
        # contributes no links and its programme's matches cell says so; its
        # fixtures are still detailed through the other side's link.
        links_by_owner: dict[str, tuple[Recipe, dict[str, str]]] = {}
        without_collector: dict[str, str] = {}
        for result in results:
            if not result.schedule_html:
                continue
            school = candidates.get(result.slug)
            recipe = _recipe_for(school) if isinstance(school, SchoolConfig) else None
            if recipe is None:
                continue
            try:
                links = recipe.boxscore_links(
                    result.schedule_html, result.schedule_url or ""
                )
            except NoCollector as exc:
                without_collector[result.slug] = exc.reason(school)
                continue
            links_by_owner[result.slug] = (recipe, links)
        # Each candidate carries the programme whose schedule page published
        # the link: the box page is archived under that programme.
        candidates_by_match: dict[
            tuple[str, str, str], list[tuple[str, Recipe, str]]
        ] = {}
        for fixture in all_fixtures:
            pair = sorted((str(fixture["home"]), str(fixture["away"])))
            key = (str(fixture["date"]), pair[0], pair[1])
            owner, _, game_id = str(fixture["id"]).rpartition(":")
            owner = owner.split(":")[-1]
            published = links_by_owner.get(owner)
            url = published[1].get(game_id) if published else None
            if published and url:
                candidates_by_match.setdefault(key, []).append(
                    (url, published[0], owner)
                )

        # Incremental harvest: a box score already stored for a final whose
        # result has not moved is data that cannot have changed since the
        # whistle, so re-fetching it is pure load on the publisher's site.
        # The skip never applies to a silent final (its box score may publish
        # late) or to a fixture whose result moved (a correction) — and the
        # fixture's own result is current every run, because the schedule
        # pages above are re-collected (or verified unchanged) first.
        # Box pages join the fetch cache beside the layer pages (bead tl-ir6):
        # a stored box whose page is archived reparses from disk when the
        # parser's fingerprint moves, and --refetch rewrites the archive.
        box_store = PageStateStore(data_root, season, gender)

        def box_owners(
            fixture: dict[str, object], key: tuple[str, str, str]
        ) -> list[tuple[str, Recipe]]:
            """The programmes whose schedule page could have linked this
            box, in the order the fetch tries them: the links published this
            run, then either side of the fixture."""
            owners: dict[str, Recipe] = {}
            for _url, recipe, owner in candidates_by_match.get(key, []):
                owners.setdefault(owner, recipe)
            for side in (str(fixture["home"]), str(fixture["away"])):
                school = candidates.get(side)
                recipe = (
                    _recipe_for(school) if isinstance(school, SchoolConfig) else None
                )
                if recipe is not None:
                    owners.setdefault(side, recipe)
            return list(owners.items())

        available = {} if refetch else dict(stored_matches or {})
        reused: dict[str, dict[str, object]] = {}
        planned: dict[str, tuple[list[tuple[str, Recipe, str]], dict[str, object]]] = {}
        reparsed = 0
        reparse_seconds = 0.0
        unarchived = 0
        for fixture in fixtures:
            if str(fixture.get("status")) != "final":
                continue
            fixture_id = str(fixture["id"])
            pair = sorted((str(fixture["home"]), str(fixture["away"])))
            key = (str(fixture["date"]), pair[0], pair[1])
            stored = available.get(fixture_id)
            if stored is not None and _stored_match_current(stored, fixture):
                held, branch, seconds = _stored_box(
                    fixture, stored, box_owners(fixture, key), box_store, season
                )
                if held is not None:
                    reused[fixture_id] = held
                    if branch == "reparsed":
                        reparsed += 1
                        reparse_seconds += seconds
                    elif branch == "unarchived":
                        unarchived += 1
                    continue
            urls = candidates_by_match.get(key, [])
            if urls:
                planned[fixture_id] = (urls, fixture)

        def match_task(
            urls: list[tuple[str, Recipe, str]], fixture: dict[str, object]
        ) -> object:
            failures: list[str] = []
            fixture_id = str(fixture["id"])
            for url, recipe, owner in urls:
                archive = BoxArchive(
                    box_store,
                    owner,
                    fixture_id,
                    parse_fingerprint(season, *recipe.parse_identity),
                )
                try:
                    return recipe.collect_match(
                        thread_session(), url, season, fixture, archive=archive
                    )
                except LiveCollectionError as exc:
                    failures.append(str(exc))
            raise LiveCollectionError("; ".join(failures))

        fetched: dict[str, dict[str, object]] = {}
        settled_count = 0

        def assembled_payload() -> dict[str, object]:
            """A valid matches payload from what is confirmed so far, in
            fixture order — the same wholesale shape the final write uses,
            every line carrying its ``player_ref``."""
            held: dict[str, dict[str, object]] = {}
            for value in fixtures:
                identity = str(value["id"])
                detail = reused.get(identity) or fetched.get(identity)
                if detail is not None:
                    held[identity] = detail
            resolve_identities(held)
            return {
                "schema": MATCHES_SCHEMA,
                "season": season,
                "gender": gender,
                "collected_at": now,
                "matches": held,
            }

        def settle_match(fixture_id: str, value: object) -> None:
            nonlocal settled_count
            if not isinstance(value, dict):
                return
            fetched[fixture_id] = value
            settled_count += 1
            if (
                matches_checkpoint is not None
                and settled_count % MATCH_CHECKPOINT_EVERY == 0
            ):
                matches_checkpoint(assembled_payload())

        settled = _scatter(
            executor,
            {
                fixture_id: partial(match_task, urls, fixture)
                for fixture_id, (urls, fixture) in planned.items()
            },
            task_budget,
            on_settled=settle_match,
        )

        # Box scores a challenge refused get one retry after the cool-down.
        challenged = [
            fixture_id
            for fixture_id in planned
            if isinstance(settled.get(fixture_id), LiveCollectionError)
            and is_challenge_reason(settled[fixture_id])
        ]
        if challenged:
            print(
                f"pacing: {len(challenged)} box score(s) refused by a challenge; "
                f"retrying once after the cool-down",
                flush=True,
            )
            gate.wait_out_cooldowns()
            settled.update(
                _scatter(
                    executor,
                    {
                        fixture_id: partial(match_task, *planned[fixture_id])
                        for fixture_id in challenged
                    },
                    task_budget,
                    on_settled=settle_match,
                )
            )

        for fixture in fixtures:
            if str(fixture.get("status")) != "final":
                continue
            fixture_id = str(fixture["id"])
            if fixture_id in reused:
                matches[fixture_id] = reused[fixture_id]
                continue
            if fixture_id not in planned:
                matches_missing[fixture_id] = (
                    "no box-score link on any collected schedule page"
                )
                errors.append(
                    f"match {fixture_id}: no box-score link on any collected schedule page"
                )
                continue
            value = settled.get(fixture_id)
            if isinstance(value, dict):
                matches[fixture_id] = value
                continue
            if isinstance(value, LiveCollectionError):
                reason = str(value)
            elif isinstance(value, TimeoutError):
                reason = f"box-score fetch {value}"
            else:
                reason = f"box-score collector failed: {value}"
            matches_missing[fixture_id] = reason
            errors.append(f"match {fixture_id}: {reason}")

        if reused:
            print(
                f"matches: kept {len(reused)} stored box score(s) whose results "
                f"are unchanged — not re-fetched"
            )
        # The price of a module-wide fingerprint change, per conference: any
        # edit to sidearm_live.py reparses every archived box of the season.
        if reparsed:
            print(
                f"boxes reparsed from the archive after a parser change: "
                f"{reparsed} in {reparse_seconds:.1f}s",
                flush=True,
            )
        if unarchived:
            print(
                f"stored boxes with no archived page: {unarchived} "
                f"(refetch archives them)",
                flush=True,
            )

        match_cells: dict[str, dict[str, object]] = {}

        def record(programme: str, layer: str, state: str, **extra: object) -> None:
            record_into(match_cells, programme, layer, state, **extra)

        for result in results:
            if result.state(LAYER_SCHEDULE) == STATE_NO_COLLECTOR:
                record(
                    result.slug,
                    LAYER_MATCHES,
                    coverage.STATE_NO_COLLECTOR,
                    reason=result.outcomes[LAYER_SCHEDULE].reason,
                )
                continue
            if result.slug in without_collector:
                record(
                    result.slug,
                    LAYER_MATCHES,
                    coverage.STATE_NO_COLLECTOR,
                    reason=without_collector[result.slug],
                )
                continue
            if result.state(LAYER_SCHEDULE) not in {STATE_COMPLETE, STATE_EMPTY}:
                record(
                    result.slug,
                    LAYER_MATCHES,
                    STATE_UNAVAILABLE,
                    reason=f"[{season}] no proven schedule to take box-score links from",
                )
                continue
            involved = [
                fixture
                for fixture in fixtures
                if str(fixture.get("status")) == "final"
                and result.slug in (str(fixture["home"]), str(fixture["away"]))
            ]
            collected = [
                fixture for fixture in involved if str(fixture["id"]) in matches
            ]
            if not involved:
                record(
                    result.slug,
                    LAYER_MATCHES,
                    STATE_EMPTY,
                    count=0,
                    reason=f"[{season}] no played fixtures to detail",
                )
            elif len(collected) == len(involved):
                record(result.slug, LAYER_MATCHES, STATE_COMPLETE, count=len(collected))
            else:
                gaps = [
                    str(fixture["id"])
                    for fixture in involved
                    if str(fixture["id"]) not in matches
                ]
                record(
                    result.slug,
                    LAYER_MATCHES,
                    STATE_COMPLETE if collected else STATE_UNAVAILABLE,
                    count=len(collected),
                    reason=(
                        f"[{season}] box scores missing for "
                        f"{len(gaps)} of {len(involved)} played fixtures: "
                        + ", ".join(gaps)
                    ),
                )

        cells.update(match_cells)
        checkpoint_cells(match_cells)

    if LAYER_MATCHES in layers:
        identity_report = resolve_identities(matches)
        print(identity_report.summary())
        for finding in identity_report.disagreements:
            print(f"  DISAGREE: {finding}")

    matches_payload: dict[str, object] = {
        "schema": MATCHES_SCHEMA,
        "season": season,
        "gender": gender,
        "collected_at": now,
        "matches": matches,
    }
    if matches_missing:
        matches_payload["missing"] = matches_missing

    return (
        fixture_payload,
        roster_payload,
        stats_payload,
        matches_payload,
        cells,
        errors,
        duplicates,
    )


def named_skips(cells: dict[str, dict[str, object]]) -> list[str]:
    """Every skip the run's cells recorded, in the gap line's voice.

    A skip is the gap convention's sibling: a row the collector read and
    deliberately did not mint (a match the programme hosted but did not
    play), named in the cell as ``skips`` and printed under the summary so
    the run log says why the page's row count and the fixture count differ.
    Unlike a gap it does not change the cell's state.
    """
    lines: list[str] = []
    for cell in cells.values():
        if not isinstance(cell, dict):
            continue
        for skip in cell.get("skips") or []:  # type: ignore[union-attr]
            lines.append(f"{cell.get('programme')} {cell.get('layer')}: {skip}")
    return lines


def widen_to_existing_scope(
    wanted: list[str], *season_paths: Path
) -> tuple[list[str], list[str]]:
    """A season file's scope only ever widens.

    The season files are written wholesale by each run, so a narrower ask
    against a data home that already covers a wider field would rewrite the
    file and silently discard every other programme's data.  Instead the run
    absorbs the existing scope: asking for one programme after a conference
    collection refreshes the whole unit.  Returns the widened list and the
    slugs that were added to it.
    """
    existing: set[str] = set()
    for path in season_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for entry in payload.get("programmes") or []:
            if isinstance(entry, dict) and entry.get("slug"):
                existing.add(str(entry["slug"]))
        for field in ("rosters", "teams"):
            keyed = payload.get(field)
            if isinstance(keyed, dict):
                existing.update(str(slug) for slug in keyed)
        for slug in payload.get("missing") or []:
            existing.add(str(slug))
    added = sorted(existing - set(wanted))
    return wanted + added, added


def level_refusal(conference: str) -> str | None:
    """Why a collect of ``conference`` into this data root must not run.

    A data home collects one NCAA level (its marker's ``level``, d2 when it
    states none). The rib and the workflows refuse a conference of another
    level before they get here; this is the same rule held once more at the
    last step before any fetch or write, so no path round them lands Division
    I data in a Division II home. A root with no marker, and a conference
    with no profile (a structural code), carry no level to compare and pass,
    as every collect did before levels. A broken marker refuses.
    """
    try:
        home = paths.home_level()
    except paths.MarkerError as exc:
        return f"REFUSED: {exc}. Nothing was fetched or written."
    if home is None:
        return None
    if not home.declared:
        print(
            f"NOTE: {paths.marker_path()} declares no level, so it is read as "
            f"{home.level}: every data home made before levels existed is "
            f'Division II. Add the line "level: {home.level}" to the marker '
            "to declare it."
        )
    wanted = collecting_level(conference)
    if wanted is None or wanted == home.level:
        return None
    how = (
        "declared in its marker"
        if home.declared
        else "assumed: its marker declares no level"
    )
    return (
        f"REFUSED: {conference.upper()} is a {wanted} conference and the data "
        f"home {paths.data_root()} collects {home.level} ({how}). A home holds "
        f"one NCAA level; collect {conference.upper()} into a {wanted} home "
        "instead. Nothing was fetched or written."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect published schedule and roster pages into board JSON."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--gender", choices=["men", "women"], required=True)
    parser.add_argument("--conference", required=True)
    parser.add_argument("--programmes", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--membership-extrapolated", action="store_true")
    parser.add_argument(
        "--layers",
        default=",".join(DEFAULT_LAYERS),
        help="Comma-separated layers to collect: schedule, roster, stats, matches.",
    )
    parser.add_argument(
        "--refetch",
        action="store_true",
        help=(
            "Collect as if the data home had never seen these pages: ignore "
            "stored validators and stored box scores, re-fetching and "
            "re-parsing everything."
        ),
    )
    concurrency = parser.add_mutually_exclusive_group()
    concurrency.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "Fetch tasks in flight at once. Parallelism is across hosts, "
            "never against one — a per-host cap of one politely spaced "
            "request is enforced regardless of this value, and a host that "
            "challenges (HTTP 202) is paced, backed off and cooled down "
            "(TOUCHLINE_HOST_SPACING, TOUCHLINE_PACED_SPACING, "
            "TOUCHLINE_CHALLENGE_BACKOFF, TOUCHLINE_HOST_COOLDOWN, "
            "TOUCHLINE_PACED_HOSTS). Default: "
            f"min({DEFAULT_WORKERS}, programme count)."
        ),
    )
    concurrency.add_argument(
        "--serial",
        action="store_true",
        help=(
            "Collect one fetch at a time (equivalent to --workers 1), for "
            "debugging. Outputs are byte-identical to a parallel run."
        ),
    )
    parser.add_argument(
        "--programme-timeout",
        type=float,
        default=DEFAULT_TASK_BUDGET,
        help=(
            "Seconds each isolated fetch task (one programme's pages, or one "
            "box score) may run before it is recorded as a named gap so the "
            "rest of the run completes. <= 0 disables the budget. Default: "
            f"{DEFAULT_TASK_BUDGET:.0f}."
        ),
    )
    args = parser.parse_args()

    if args.workers is not None and args.workers < 1:
        print("--workers must be at least 1", file=sys.stderr)
        return 2

    wanted = [value.strip() for value in args.programmes.split(",") if value.strip()]
    if not wanted:
        print("--programmes resolved to an empty list", file=sys.stderr)
        return 2

    conference_slug = programme_slug(args.conference)
    if not conference_slug:
        print(
            "--conference must contain at least one letter or number", file=sys.stderr
        )
        return 2

    data_root = paths.data_root()
    refusal = level_refusal(args.conference)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    for sync_note in (sync_membership_reference(), sync_programmes_reference()):
        if sync_note:
            print(sync_note)
    season_key = f"{args.season}-{args.gender}-{conference_slug}"
    fixture_path = data_root / "data" / "fixtures" / f"{season_key}.json"
    roster_path = data_root / "data" / "rosters" / f"{season_key}.json"
    stats_path = data_root / "data" / "stats" / f"{season_key}.json"
    matches_path = data_root / "data" / "matches" / f"{season_key}.json"
    wanted, widened = widen_to_existing_scope(
        wanted, fixture_path, roster_path, stats_path
    )
    if widened:
        print(
            f"scope widened to the season unit: this data home's {args.season} {args.gender} "
            f"collection already covers {', '.join(widened)}; a run refreshes the whole "
            "unit rather than narrowing the file."
        )

    layers = tuple(value.strip() for value in args.layers.split(",") if value.strip())
    unknown = [layer for layer in layers if layer not in DEFAULT_LAYERS]
    if unknown:
        print(
            f"unknown layer(s): {', '.join(unknown)}. Known: {', '.join(DEFAULT_LAYERS)}",
            file=sys.stderr,
        )
        return 2
    if not layers:
        print("--layers resolved to an empty list", file=sys.stderr)
        return 2
    if LAYER_MATCHES in layers and LAYER_SCHEDULE not in layers:
        print(
            "matches are collected through the schedule's own box-score links, "
            "so the schedule layer is included as well."
        )
        layers = (LAYER_SCHEDULE, *layers)

    # The epic's ratified incremental behaviour: fetch only finals lacking
    # their stored match data.  The previous run's matches file is the cache
    # the payload is assembled from — the file is still written wholesale, it
    # is just assembled from cache plus new fetches.
    stored_matches: dict[str, dict[str, object]] = {}
    if LAYER_MATCHES in layers and not args.refetch:
        try:
            existing = json.loads(matches_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict) and isinstance(existing.get("matches"), dict):
            stored_matches = {
                str(fixture_id): detail
                for fixture_id, detail in existing["matches"].items()
                if isinstance(detail, dict)
            }

    try:
        fixtures, rosters, stats, matches, cells, errors, duplicates = collect(
            season=args.season,
            gender=args.gender,
            conference=args.conference,
            wanted=wanted,
            layers=layers,
            config_path=Path(args.config),
            membership_extrapolated=args.membership_extrapolated,
            stored_matches=stored_matches,
            refetch=args.refetch,
            workers=1 if args.serial else args.workers,
            task_budget=args.programme_timeout,
            # Box scores checkpoint to their season file as they confirm: a run
            # killed at the node budget keeps them, and the next run's
            # incremental harvest starts from them instead of from zero.
            matches_checkpoint=(
                (lambda payload: _atomic_json(matches_path, payload))
                if LAYER_MATCHES in layers
                else None
            ),
        )
    except MixedLevels as refusal:
        # Refused before any fetch (collect_identity runs before the first
        # request); the season files stand as they were.
        print(str(refusal), file=sys.stderr)
        return 2
    except UncoveredSeason as refusal:
        # Nothing was fetched and nothing was written: the season files stand
        # as they were.  Named on stderr, exit 2 like any ask the collector
        # cannot honour.
        print(str(refusal), file=sys.stderr)
        absorbed = [slug for slug in refusal.programmes if slug in widened]
        if absorbed:
            print(
                f"{', '.join(absorbed)} came from this data home's existing "
                f"{season_key} files, which a run always refreshes whole; they "
                "were collected under the old stanza default.",
                file=sys.stderr,
            )
        return 2
    written: list[Path] = []
    if LAYER_SCHEDULE in layers:
        _atomic_json(fixture_path, fixtures)
        written.append(fixture_path)
    if LAYER_ROSTER in layers:
        _atomic_json(roster_path, rosters)
        written.append(roster_path)
    if LAYER_STATS in layers:
        _atomic_json(stats_path, stats)
        written.append(stats_path)
    if LAYER_MATCHES in layers:
        _atomic_json(matches_path, matches)
        written.append(matches_path)

    # The manifest is the run's real deliverable: it is what lets the next ask
    # be about what is missing rather than about everything.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        manifest = coverage.merge_cells(data_root, cells, updated_at=now)
        manifest_path = coverage.write_coverage(data_root, manifest)
    except (OSError, ValueError) as exc:
        print(f"FAILED to write the coverage manifest: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {', '.join(str(path) for path in written)} and {manifest_path}")

    unchanged = sum(
        1
        for cell in cells.values()
        if isinstance(cell, dict) and cell.get("verified") == "unchanged"
    )
    if unchanged:
        print(
            f"{unchanged} page(s) verified unchanged — reused without "
            f"re-parsing or rewriting"
        )

    if LAYER_SCHEDULE in layers:
        played = sum(
            1 for fixture in fixtures["fixtures"] if fixture["status"] == "final"
        )
        upcoming = sum(
            1 for fixture in fixtures["fixtures"] if fixture["status"] == "scheduled"
        )
        served = len(wanted) - len(fixtures.get("missing", []))
        print(
            f"schedule: {served}/{len(wanted)} programmes, "
            f"{len(fixtures['fixtures'])} fixtures ({played} played, {upcoming} upcoming)"
        )
        print("conference flags PUBLISHED by each programme's official schedule page")
    if LAYER_ROSTER in layers:
        players = sum(len(roster["players"]) for roster in rosters["rosters"].values())
        served = len(wanted) - len(rosters.get("missing", []))
        print(f"roster: {served}/{len(wanted)} programmes, {players} players")
    if LAYER_STATS in layers:
        lines = sum(
            len(team["players"]) + len(team["keepers"])
            for team in stats["teams"].values()
        )
        served = len(wanted) - len(stats.get("missing", []))
        print(f"stats: {served}/{len(wanted)} programmes, {lines} player season lines")
    if LAYER_MATCHES in layers:
        played = sum(
            1 for fixture in fixtures["fixtures"] if fixture["status"] == "final"
        )
        print(
            f"matches: {len(matches['matches'])} of {played} played fixtures "
            f"carry a collected box score"
        )

    if duplicates:
        print(
            f"collapsed {duplicates} duplicate fixture row(s) published by both programmes"
        )

    if LAYER_SCHEDULE in layers:
        # A stanza at another NCAA level is no stanza here: its text minted
        # a slug, it did not resolve, so a bracket side spelled that way is
        # a stranger to this collect's table like any other.
        stanza_slugs = {
            programme_slug(school.name)
            for school in resolution_stanzas(
                load_schools(args.config),
                args.gender,
                args.conference,
                args.season,
                programmes=wanted,
                document=_membership_document(),
            )
        }
        strangers = postseason_strangers(fixtures["fixtures"], stanza_slugs)
        if strangers:
            print(
                f"\n{len(strangers)} postseason side(s) with no schools.toml "
                f"stanza — add the printed spelling as an alias:"
            )
            for line in strangers:
                print(f"  POSTSEASON: {line}")

    skips = named_skips(cells)
    if skips:
        print(
            f"\n{len(skips)} named skip(s) — rows a page published that are not "
            f"that programme's fixtures, read and left unminted:"
        )
        for skip in skips:
            print(f"  SKIP: {skip}")

    if errors:
        error_path = data_root / "data" / "errors" / f"collect-board-{season_key}.json"
        _atomic_json(
            error_path,
            {
                "season": args.season,
                "gender": args.gender,
                "conference": args.conference,
                "errors": errors,
            },
        )
        print(
            f"\n{len(errors)} named gap(s) — recorded in the manifest, not discarded:"
        )
        for error in errors:
            print(f"  GAP: {error}")

    # Exit 0 means the manifest was written and describes reality, gaps and all.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
