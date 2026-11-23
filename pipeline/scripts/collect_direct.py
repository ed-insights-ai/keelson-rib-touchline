"""Collect a division's season straight through ``collect-board``: no Keelson
server, no model call.  The GitHub Actions collect workflow
(``.github/workflows/collect.yml``) is its one caller today; at cutover it
replaces the Mac's ``bin/touchline-collect-cadence.sh collect``.

It keeps the cadence's rules exactly, because the parity check compares the
two pipelines' output:

* one season unit (season, gender, conference) per ``collect-board`` call,
  every programme membership resolves for it (``bin/resolve-membership.ts``,
  the same resolver the cadence uses);
* a unit whose only diff is the ``collected_at`` stamp is rolled back, not
  committed (``no-change``);
* a unit that would drop a programme HEAD held (it became a named gap) is
  rolled back and counted ``lost``, unless the run accepts the loss;
* a unit whose collect exits non-zero is rolled back and counted ``failed``;
  the other units still run.

The work happens in a *work home*: a slim copy of the target data home (the
marker, the reference mirrors, the coverage manifest and every season file of
the season being collected, which ``collect-board`` reads for sibling
identities), with its own throwaway git repository whose first commit is the
target's state.  Each changed unit is one commit there.  ``land`` replays
those commits onto the target checkout (the data home's ``shadow`` branch in
the pilot), overlaying only the coverage cells each commit changed, so two
jobs collecting different units of one division land cleanly in either
order, and ``land --push`` retries on a moved branch by replaying again.

Platforms.  PrestoSports refuses GitHub-hosted runners, so a unit with any
PrestoSports member is a ``presto`` unit, collected on the self-hosted runner
with that label; every other unit is ``hosted``.  The split is by unit, never
by programme, because ``collect-board`` writes a unit's season files whole.

Subcommands (``uv run collect-direct <cmd> --help``):

  plan      resolve the units to collect, per division, into plan JSON
  slim      make a work home from a data home
  slugs     print the programmes of a plan's units (for the raw-HTML sync)
  collect   collect a plan's units into a work home, writing the run record
  land      replay a work home's unit commits onto a data-home checkout

Exit codes: 0 done (gaps and rolled-back units are recorded, not failures),
1 a unit failed or was lost (``collect``) or the push never landed
(``land``), 2 the command could not run at all.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import paths
from src.config import DEFAULT_CONFIG, load_schools
from src.recipes import PRESTO
from src.sidearm_live import programme_slug

PLAN_SCHEMA = "touchline.collect-plan/1"
RECORD_SCHEMA = "touchline.collect-record/1"

#: The four board layers, as directories under data/.
BOARD_DIRS = ("fixtures", "rosters", "stats", "matches")
#: Every season-keyed directory a work home carries (errors included, so a
#: unit's errors file travels with it).
SEASON_DIRS = (*BOARD_DIRS, "errors")
COVERAGE = "data/coverage.json"

JOB_HOSTED = "hosted"
JOB_PRESTO = "presto"
JOBS = (JOB_HOSTED, JOB_PRESTO)

RESULT_CHANGED = "changed"
RESULT_NO_CHANGE = "no-change"
RESULT_LOST = "lost"
RESULT_FAILED = "failed"
RESULT_SKIPPED = "skipped"

#: Seconds one unit's collect-board may run before it is killed and the unit
#: counted failed.  collect-board bounds every programme and box score on its
#: own (five minutes each); this only stops a wedged process from eating the
#: job's whole budget.
DEFAULT_UNIT_TIMEOUT = 2400.0

GIT_AUTHOR = ("touchline-collect", "touchline-collect@users.noreply.github.com")


class DirectError(RuntimeError):
    """The command cannot run: named on stderr, exit 2."""


# ── small helpers ────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_season(today: datetime | None = None) -> int:
    """The college-soccer season is the calendar year of its fall semester:
    June onward is this year's, January to May still last fall's (the
    cadence's rule)."""
    today = today or datetime.now(timezone.utc)
    return today.year if today.month >= 6 else today.year - 1


def _git(home: Path, *args: str, check: bool = True, **kw: Any) -> str:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", GIT_AUTHOR[0])
    env.setdefault("GIT_AUTHOR_EMAIL", GIT_AUTHOR[1])
    env.setdefault("GIT_COMMITTER_NAME", GIT_AUTHOR[0])
    env.setdefault("GIT_COMMITTER_EMAIL", GIT_AUTHOR[1])
    done = subprocess.run(
        ["git", "-C", str(home), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        **kw,
    )
    if check and done.returncode != 0:
        raise DirectError(
            f"git {' '.join(args)} in {home} exited {done.returncode}: "
            f"{(done.stderr or done.stdout).strip()}"
        )
    return done.stdout


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _group(title: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::group::{title}", flush=True)
    else:
        print(f"── {title}", flush=True)


def _endgroup() -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::endgroup::", flush=True)


# ── plan ─────────────────────────────────────────────────────────────────────


@dataclass
class Unit:
    conference: str
    gender: str
    programmes: list[str]
    extrapolated: bool
    job: str

    @property
    def key(self) -> str:
        return programme_slug(self.conference)


@dataclass
class DivisionPlan:
    units: list[Unit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _resolver(rib: Path) -> list[str]:
    script = rib / "bin" / "resolve-membership.ts"
    if not script.is_file():
        raise DirectError(f"membership resolver not found at {script}")
    bun = shutil.which("bun")
    if bun is None:
        raise DirectError("bun is not on PATH; the membership resolver needs it")
    return [bun, str(script)]


def _resolve(rib: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_resolver(rib), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=rib,
    )


def resolve_levels(rib: Path) -> list[str]:
    done = _resolve(rib, "levels")
    if done.returncode != 0 or not done.stdout.split():
        raise DirectError(f"cannot read the levels list: {done.stderr.strip()}")
    return done.stdout.split()


def resolve_conferences(
    rib: Path, gender: str, level: str, season: int
) -> tuple[list[str], str]:
    """The conferences at ``level`` with a ``gender`` member in ``season``,
    and the resolver's note (an ended conference, or why none resolve)."""
    done = _resolve(
        rib, "conferences", gender, "--level", level, "--season", str(season)
    )
    note = done.stderr.strip()
    if done.returncode != 0:
        return [], note or f"no {level} {gender} conferences resolve"
    return done.stdout.split(), note


def resolve_programmes(
    rib: Path, conference: str, gender: str, season: int
) -> tuple[bool, list[str]]:
    done = _resolve(rib, "conference", conference, gender, str(season))
    line = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""
    flag, _, slugs = line.partition(" ")
    if done.returncode != 0 or flag not in ("true", "false") or not slugs:
        raise DirectError(
            f"membership resolution failed for {conference} {gender} {season}: "
            f"{done.stderr.strip() or line or 'no output'}"
        )
    return flag == "true", [s for s in slugs.split(",") if s]


def platforms(config: Path) -> dict[tuple[str, str], str]:
    """(slug, gender) -> live platform, from the enabled stanzas."""
    table: dict[tuple[str, str], str] = {}
    for school in load_schools(config):
        table[(programme_slug(school.name), school.gender)] = school.live_collector()
    return table


def route(
    programmes: Iterable[str], gender: str, table: dict[tuple[str, str], str]
) -> str:
    """``presto`` when any member collects through PrestoSports, which
    refuses GitHub-hosted runners; ``hosted`` otherwise."""
    for slug in programmes:
        if table.get((slug, gender)) == PRESTO.platform:
            return JOB_PRESTO
    return JOB_HOSTED


def build_plan(
    *,
    rib: Path,
    config: Path,
    season: int,
    genders: Sequence[str],
    divisions: Sequence[str] | None,
    conferences: Sequence[str] | None,
) -> dict[str, Any]:
    levels = resolve_levels(rib)
    wanted = list(divisions) if divisions else levels
    unknown = [d for d in wanted if d not in levels]
    if unknown:
        raise DirectError(
            f"unknown division(s) {', '.join(unknown)}; the list is {' '.join(levels)}"
        )
    pinned = {c.strip().upper() for c in conferences or [] if c.strip()}
    table = platforms(config)
    plan: dict[str, DivisionPlan] = {}
    seen_pins: set[str] = set()
    for level in wanted:
        division = plan.setdefault(level, DivisionPlan())
        for gender in genders:
            confs, note = resolve_conferences(rib, gender, level, season)
            if note:
                division.notes.append(f"{gender}: {note.split(' (known conferences')[0]}")
            for conference in confs:
                if pinned and conference.upper() not in pinned:
                    continue
                seen_pins.add(conference.upper())
                extrapolated, slugs = resolve_programmes(
                    rib, conference, gender, season
                )
                division.units.append(
                    Unit(
                        conference,
                        gender,
                        slugs,
                        extrapolated,
                        route(slugs, gender, table),
                    )
                )
    missing = sorted(pinned - seen_pins)
    if missing:
        raise DirectError(
            f"pinned conference(s) {', '.join(missing)} have no {'/'.join(genders)} "
            f"members in {season} at {'/'.join(wanted)}"
        )
    return {
        "schema": PLAN_SCHEMA,
        "season": season,
        "genders": list(genders),
        "divisions": {
            level: {
                "units": [asdict(u) for u in div.units],
                "jobs": sorted({u.job for u in div.units}),
                "notes": div.notes,
            }
            for level, div in plan.items()
        },
    }


def plan_units(
    plan: dict[str, Any], division: str, job: str | None = None
) -> list[Unit]:
    entry = (plan.get("divisions") or {}).get(division)
    if entry is None:
        raise DirectError(f"the plan has no division {division}")
    units = [Unit(**u) for u in entry.get("units") or []]
    return [u for u in units if job in (None, "all") or u.job == job]


# ── work home ────────────────────────────────────────────────────────────────


def make_work_home(source: Path, dest: Path, season: int) -> str:
    """Copy what a collect of ``season`` reads and writes from the data home
    at ``source`` into ``dest``, and commit it as the baseline.  Returns the
    baseline commit."""
    marker = source / paths.MARKER_FILE
    text = marker.read_text(encoding="utf-8") if marker.is_file() else ""
    if "kind: touchline-data" not in text:
        raise DirectError(
            f"{source} is not a Touchline data home (no {paths.MARKER_FILE} of kind touchline-data)"
        )
    if dest.exists() and any(dest.iterdir()):
        raise DirectError(f"{dest} exists and is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(marker, dest / paths.MARKER_FILE)
    if (source / ".gitignore").is_file():
        shutil.copy2(source / ".gitignore", dest / ".gitignore")
    copies: list[Path] = [Path(COVERAGE)]
    reference = source / "data" / "reference"
    if reference.is_dir():
        copies += [p.relative_to(source) for p in sorted(reference.glob("*.json"))]
    for directory in SEASON_DIRS:
        folder = source / "data" / directory
        if not folder.is_dir():
            continue
        pattern = (
            f"collect-board-{season}-*.json"
            if directory == "errors"
            else f"{season}-*.json"
        )
        copies += [p.relative_to(source) for p in sorted(folder.glob(pattern))]
    for relative in copies:
        origin = source / relative
        if origin.is_file():
            (dest / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, dest / relative)
    _git(dest, "init", "-q", "-b", "work")
    exclude = dest / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    # The fetch cache is never tracked, here or in a data home.
    exclude.write_text("data/raw_html/\n", encoding="utf-8")
    _git(dest, "add", "-A")
    _git(
        dest,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        f"baseline: {source.name} season {season}",
    )
    return _git(dest, "rev-parse", "HEAD").strip()


def unit_paths(season: int, gender: str, key: str) -> list[str]:
    stem = f"{season}-{gender}-{key}"
    return [f"data/{d}/{stem}.json" for d in BOARD_DIRS]


def has_signal(home: Path, season: int, gender: str, key: str) -> bool:
    """A real change: a new board file, or a board diff with any line beyond
    the ``collected_at`` stamp (the cadence's has_signal, line for line)."""
    board = unit_paths(season, gender, key)
    status = _git(home, "status", "--porcelain", "--", *board)
    if any(line.startswith("??") for line in status.splitlines()):
        return True
    diff = _git(home, "diff", "HEAD", "-U0", "--", *board)
    for line in diff.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        if '"collected_at"' in line:
            continue
        return True
    return False


def lost_programmes(home: Path, season: int, gender: str, key: str) -> list[str]:
    """``layer:slug`` for each programme the collected file lists under
    ``missing`` that HEAD neither listed there nor lacked data for (the
    cadence's lost_programmes)."""
    lost: list[str] = []
    for layer in ("fixtures", "rosters", "stats"):
        relative = f"data/{layer}/{season}-{gender}-{key}.json"
        current = _read_json(home / relative)
        if not isinstance(current, dict):
            continue
        shown = subprocess.run(
            ["git", "-C", str(home), "show", f"HEAD:{relative}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if shown.returncode != 0:
            continue
        try:
            head = json.loads(shown.stdout)
        except json.JSONDecodeError:
            continue
        if not isinstance(head, dict):
            continue
        head_missing = {s for s in head.get("missing") or [] if isinstance(s, str)}
        for slug in current.get("missing") or []:
            if not isinstance(slug, str) or slug in head_missing:
                continue
            if layer == "rosters":
                held = isinstance(head.get("rosters"), dict) and slug in head["rosters"]
            elif layer == "stats":
                held = isinstance(head.get("teams"), dict) and slug in head["teams"]
            else:
                held = any(
                    isinstance(p, dict) and p.get("slug") == slug
                    for p in head.get("programmes") or []
                )
            if held:
                lost.append(f"{layer}:{slug}")
    return lost


def restore_unit(home: Path, season: int, gender: str, key: str) -> None:
    """Undo a unit's writes: its board and errors files and the coverage
    manifest go back to HEAD, new ones are removed.  The raw pages stay:
    they are the fetch cache, never tracked."""
    targets = [
        *unit_paths(season, gender, key),
        f"data/errors/collect-board-{season}-{gender}-{key}.json",
        COVERAGE,
    ]
    status = _git(home, "status", "--porcelain", "-uall", "--", *targets)
    for line in status.splitlines():
        path = line[3:]
        if line.startswith("??"):
            _git(home, "clean", "-qfd", "--", path)
        else:
            _git(home, "checkout", "-q", "HEAD", "--", path)


def commit_all(home: Path, message: str) -> bool:
    _git(home, "add", "-A")
    if not _git(home, "diff", "--cached", "--name-only").strip():
        return False
    _git(home, "commit", "-q", "-m", message)
    return True


# ── collect ──────────────────────────────────────────────────────────────────


@dataclass
class UnitResult:
    conference: str
    gender: str
    job: str
    result: str
    programmes: int
    collected_at: str | None = None
    reason: str | None = None
    lost: list[str] = field(default_factory=list)
    seconds: float = 0.0


def run_collect_board(
    home: Path, unit: Unit, season: int, timeout: float, extra: Sequence[str]
) -> tuple[int, str]:
    pipeline = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "scripts.collect_board",
        "--season",
        str(season),
        "--gender",
        unit.gender,
        "--conference",
        unit.conference,
        "--programmes",
        ",".join(unit.programmes),
        *extra,
    ]
    if unit.extrapolated:
        command.append("--membership-extrapolated")
    env = dict(os.environ, TOUCHLINE_DATA_DIR=str(home))
    try:
        done = subprocess.run(
            command,
            cwd=pipeline,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return (
            124,
            out
            + f"\ncollect-board passed its {timeout:.0f}s unit budget and was stopped",
        )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def collect_unit(
    home: Path,
    unit: Unit,
    season: int,
    *,
    accept_loss: bool,
    timeout: float,
    extra: Sequence[str] = (),
    runner=run_collect_board,
) -> UnitResult:
    key = unit.key
    started = time.monotonic()
    code, output = runner(home, unit, season, timeout, extra)
    print(output.rstrip(), flush=True)
    result = UnitResult(
        unit.conference, unit.gender, unit.job, "", len(unit.programmes)
    )
    if code != 0:
        restore_unit(home, season, unit.gender, key)
        result.result = RESULT_FAILED
        last = [line for line in output.strip().splitlines() if line.strip()]
        result.reason = f"collect-board exited {code}" + (
            f": {last[-1][:300]}" if last else ""
        )
    else:
        stamp = _read_json(
            home / "data" / "fixtures" / f"{season}-{unit.gender}-{key}.json"
        )
        collected_at = stamp.get("collected_at") if isinstance(stamp, dict) else None
        lost = lost_programmes(home, season, unit.gender, key)
        if lost and not accept_loss:
            restore_unit(home, season, unit.gender, key)
            result.result = RESULT_LOST
            result.lost = lost
            result.reason = (
                "collect drops data HEAD held; rolled back so the board keeps "
                "the complete record (accept_loss lands a loss that is real)"
            )
        elif has_signal(home, season, unit.gender, key):
            commit_all(
                home, f"collect(shadow): {unit.conference} {unit.gender} {season}"
            )
            result.result = RESULT_CHANGED
            result.collected_at = collected_at
            result.lost = lost
            if lost:
                result.reason = "loss accepted by accept_loss"
        else:
            restore_unit(home, season, unit.gender, key)
            result.result = RESULT_NO_CHANGE
            result.collected_at = collected_at
    result.seconds = round(time.monotonic() - started, 1)
    return result


def skipped_results(units: Iterable[Unit], reason: str) -> list[UnitResult]:
    return [
        UnitResult(
            u.conference,
            u.gender,
            u.job,
            RESULT_SKIPPED,
            len(u.programmes),
            reason=reason,
        )
        for u in units
    ]


def write_summary(
    path: str | None, division: str, job: str, results: list[UnitResult]
) -> None:
    if not path:
        return
    lines = [
        f"### Collect {division} ({job})",
        "",
        "| Unit | Job | Result | Programmes | Seconds | Note |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for r in results:
        note = (r.reason or "") + (f" ({', '.join(r.lost)})" if r.lost else "")
        lines.append(
            f"| {r.conference} {r.gender} | {r.job} | {r.result} | {r.programmes} "
            f"| {r.seconds:.0f} | {note.replace('|', '/')} |"
        )
    counts: dict[str, int] = {}
    for r in results:
        counts[r.result] = counts.get(r.result, 0) + 1
    lines += [
        "",
        ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "no units",
        "",
    ]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


# ── land ─────────────────────────────────────────────────────────────────────


def _show(home: Path, rev: str, path: str) -> bytes | None:
    done = subprocess.run(
        ["git", "-C", str(home), "show", f"{rev}:{path}"],
        check=False,
        capture_output=True,
    )
    return done.stdout if done.returncode == 0 else None


def _cells(blob: bytes | None) -> dict[str, Any]:
    if blob is None:
        return {}
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    cells = payload.get("cells") if isinstance(payload, dict) else None
    return cells if isinstance(cells, dict) else {}


def overlay_coverage(target: Path, before: bytes | None, after: bytes | None) -> None:
    """Apply the cells one work commit changed to the target's manifest, so
    cells another job landed meanwhile survive."""
    old, new = _cells(before), _cells(after)
    changed = {k: v for k, v in new.items() if old.get(k) != v}
    removed = [k for k in old if k not in new]
    if not changed and not removed:
        return
    path = target / COVERAGE
    manifest = _read_json(path)
    if not isinstance(manifest, dict):
        manifest = {}
    cells = manifest.get("cells") if isinstance(manifest.get("cells"), dict) else {}
    cells.update(changed)
    for k in removed:
        cells.pop(k, None)
    manifest["cells"] = cells
    try:
        after_doc = json.loads(after) if after is not None else {}
    except json.JSONDecodeError:
        after_doc = {}
    for field_name in ("schema", "updated_at"):
        if isinstance(after_doc, dict) and field_name in after_doc:
            manifest[field_name] = after_doc[field_name]
    # The collector writes the manifest sorted and indented; keep that shape.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def work_commits(work: Path) -> list[str]:
    """The unit commits in a work home, oldest first (the baseline excluded)."""
    root = _git(work, "rev-list", "--max-parents=0", "HEAD").split()[0]
    return _git(work, "rev-list", "--reverse", f"{root}..HEAD").split()


def replay(work: Path, target: Path) -> list[str]:
    """Replay each work commit onto the target checkout as one commit.
    Returns the subjects of the commits made (a commit that changes nothing
    on the target makes none)."""
    made: list[str] = []
    for commit in work_commits(work):
        subject = _git(work, "log", "-1", "--format=%s", commit).strip()
        changes = _git(
            work, "diff", "--name-status", "--no-renames", f"{commit}^", commit
        )
        for line in changes.splitlines():
            status, _, path = line.partition("\t")
            if path == COVERAGE:
                overlay_coverage(
                    target, _show(work, f"{commit}^", path), _show(work, commit, path)
                )
            elif status.startswith("D"):
                (target / path).unlink(missing_ok=True)
            else:
                blob = _show(work, commit, path)
                if blob is None:
                    raise DirectError(f"cannot read {path} at {commit} in {work}")
                (target / path).parent.mkdir(parents=True, exist_ok=True)
                (target / path).write_bytes(blob)
        if commit_all(target, subject):
            made.append(subject)
    return made


def land(
    work: Path,
    target: Path,
    *,
    push: bool,
    remote: str,
    branch: str,
    retries: int,
) -> tuple[list[str], str]:
    made = replay(work, target)
    if not push or not made:
        return made, _git(target, "rev-parse", "HEAD").strip()
    for attempt in range(retries + 1):
        pushed = subprocess.run(
            ["git", "-C", str(target), "push", remote, f"HEAD:refs/heads/{branch}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if pushed.returncode == 0:
            return made, _git(target, "rev-parse", "HEAD").strip()
        print(
            f"push refused (attempt {attempt + 1}): {pushed.stderr.strip()}", flush=True
        )
        if attempt == retries:
            break
        time.sleep(2 * (attempt + 1))
        # The branch moved under us (another job landed): start again from it.
        _git(target, "fetch", "-q", "--depth", "1", remote, branch)
        _git(target, "reset", "-q", "--hard", "FETCH_HEAD")
        made = replay(work, target)
        if not made:
            return made, _git(target, "rev-parse", "HEAD").strip()
    raise DirectError(f"could not push {branch} after {retries + 1} attempts")


# ── command line ─────────────────────────────────────────────────────────────


def _csv(text: str | None) -> list[str]:
    return [v.strip() for v in (text or "").replace(" ", ",").split(",") if v.strip()]


def cmd_plan(args: argparse.Namespace) -> int:
    season = args.season or default_season()
    genders = _csv(args.genders) or ["men", "women"]
    for gender in genders:
        if gender not in ("men", "women"):
            raise DirectError(f"unknown gender {gender}")
    plan = build_plan(
        rib=paths.package_root(),
        config=Path(args.config),
        season=season,
        genders=genders,
        divisions=_csv(args.divisions) or None,
        conferences=_csv(args.conferences) or None,
    )
    _write_json(Path(args.out), plan)
    for level, entry in plan["divisions"].items():
        units = entry["units"]
        by_job = {job: sum(1 for u in units if u["job"] == job) for job in JOBS}
        print(
            f"{level}: {len(units)} unit(s) "
            + ", ".join(f"{job} {n}" for job, n in by_job.items())
            + "".join(f"\n  note: {n}" for n in entry["notes"])
        )
    return 0


def cmd_slim(args: argparse.Namespace) -> int:
    head = make_work_home(Path(args.source), Path(args.dest), args.season)
    print(
        f"work home {args.dest} from {args.source} season {args.season} at {head[:12]}"
    )
    return 0


def cmd_slugs(args: argparse.Namespace) -> int:
    plan = _read_json(Path(args.plan))
    if not isinstance(plan, dict):
        raise DirectError(f"cannot read plan {args.plan}")
    slugs = sorted(
        {s for u in plan_units(plan, args.division, args.job) for s in u.programmes}
    )
    print("\n".join(slugs))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    plan = _read_json(Path(args.plan))
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise DirectError(f"{args.plan} is not a {PLAN_SCHEMA} plan")
    season = int(plan["season"])
    home = Path(args.home).resolve()
    units = plan_units(plan, args.division, args.job)
    skip = plan_units(plan, args.division, JOB_PRESTO) if args.skip_presto else []
    accept = {c.upper() for c in _csv(args.accept_loss)}
    extra = ["--refetch"] if args.refetch else []
    started = _now()
    base = _git(home, "rev-parse", "HEAD").strip()
    results: list[UnitResult] = []
    for unit in units:
        _group(
            f"{unit.conference} {unit.gender} {season} ({unit.job}, {len(unit.programmes)} programmes)"
        )
        try:
            outcome = collect_unit(
                home,
                unit,
                season,
                accept_loss=unit.conference.upper() in accept,
                timeout=args.unit_timeout,
                extra=extra,
            )
        finally:
            _endgroup()
        print(
            f"{unit.conference} {unit.gender}: {outcome.result}"
            + (f" ({outcome.reason})" if outcome.reason else ""),
            flush=True,
        )
        results.append(outcome)
    results += skipped_results(skip, args.skip_presto or "")
    record = {
        "schema": RECORD_SCHEMA,
        "division": args.division,
        "season": season,
        "job": args.job,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "rib_sha": os.environ.get("GITHUB_SHA"),
        "started_at": started,
        "finished_at": _now(),
        "work_base": base,
        "units": [asdict(r) for r in results],
    }
    _write_json(Path(args.record), record)
    write_summary(
        os.environ.get("GITHUB_STEP_SUMMARY"), args.division, args.job, results
    )
    bad = [r for r in results if r.result in (RESULT_FAILED, RESULT_LOST)]
    return 1 if bad else 0


def cmd_land(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    base = _git(target, "rev-parse", "HEAD").strip()
    made, head = land(
        Path(args.work).resolve(),
        target,
        push=args.push,
        remote=args.remote,
        branch=args.branch,
        retries=args.retries,
    )
    for subject in made:
        print(f"landed: {subject}")
    if not made:
        print("nothing to land: no unit changed")
    if args.record:
        record_path = Path(args.record)
        record = _read_json(record_path)
        if isinstance(record, dict):
            record["target_base"] = base
            record["target_head"] = head
            record["target_branch"] = args.branch
            record["landed"] = made
            record["pushed"] = bool(args.push and made)
            if args.main_sha:
                record["main_sha"] = args.main_sha
            _write_json(record_path, record)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="collect-direct", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="resolve the units to collect into plan JSON")
    p.add_argument("--out", required=True)
    p.add_argument(
        "--season", type=int, default=None, help="default: the current season"
    )
    p.add_argument("--genders", default="men,women")
    p.add_argument(
        "--divisions", default="", help="default: every level in the one list"
    )
    p.add_argument("--conferences", default="", help="pin to these conferences")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("slim", help="make a work home from a data home")
    p.add_argument("--source", required=True)
    p.add_argument("--dest", required=True)
    p.add_argument("--season", type=int, required=True)
    p.set_defaults(func=cmd_slim)

    p = sub.add_parser("slugs", help="print the programmes of a plan's units")
    p.add_argument("--plan", required=True)
    p.add_argument("--division", required=True)
    p.add_argument("--job", choices=[*JOBS, "all"], default="all")
    p.set_defaults(func=cmd_slugs)

    p = sub.add_parser("collect", help="collect a plan's units into a work home")
    p.add_argument("--plan", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--division", required=True)
    p.add_argument("--job", choices=[*JOBS, "all"], required=True)
    p.add_argument("--record", required=True)
    p.add_argument("--accept-loss", default="", help="conferences whose loss lands")
    p.add_argument("--refetch", action="store_true")
    p.add_argument(
        "--skip-presto",
        default="",
        metavar="REASON",
        help="record the plan's presto units as skipped, with this reason",
    )
    p.add_argument("--unit-timeout", type=float, default=DEFAULT_UNIT_TIMEOUT)
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("land", help="replay a work home's unit commits onto a checkout")
    p.add_argument("--work", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--record", default="")
    p.add_argument("--push", action="store_true")
    p.add_argument("--remote", default="origin")
    p.add_argument("--branch", default="shadow")
    p.add_argument("--main-sha", default="")
    p.add_argument("--retries", type=int, default=4)
    p.set_defaults(func=cmd_land)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except DirectError as exc:
        print(f"collect-direct: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
