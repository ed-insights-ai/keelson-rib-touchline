"""Record-by-record parity between two data homes.

The cutover gate for the cloud pipeline: the new pipeline writes a ``shadow``
branch of each data home while the Mac cadence keeps writing ``main``, and the
new pipeline may replace the Mac only once shadow matches main. This module
decides what "matches" means.

Two homes are read (a directory, or a git ref read without a checkout) and
every season file is broken into records:

==========  ==============================================  ==============
layer       record                                          key
==========  ==============================================  ==============
fixtures    one fixture row                                 fixture ``id``
matches     one box score (or its ``missing`` entry)        match id
rosters     one programme's roster                          programme slug
stats       one programme's season statistics               programme slug
coverage    one coverage cell                               cell key
reference   ``membership.json`` / ``programmes.json``       top-level key
==========  ==============================================  ==============

plus each season file's own header facts (the ``programmes`` it names, its
``missing`` gaps, how conference games were decided).

Every record lands in exactly one class:

``match``
    Equal on both sides, ignoring only the fields that record *when* a
    collect ran (``collected_at``, a cell's ``confirmed_at`` and its
    ``verified`` reuse flag).
``timing``
    Different, and the difference is the kind a later collection is expected
    to see: the game is dated within ``lag_days`` before the earlier side's
    collection (or later), and the later side moved forward, never back.
    A fixture that went from scheduled to final, a box score posted after the
    earlier collect, season totals that grew with a game played in between.
``disagreement``
    Everything else. A final score that differs, a box score that vanished,
    totals that went down, a roster that differs (rosters do not move with
    games, so no game can explain them), a gap one side has and the other
    does not, two sides collected at the same moment that differ at all.

Strictness is the point: a record is a match only when it is equal, and a
difference is ``timing`` only when the dates prove the later side could have
seen something the earlier side could not. When a difference cannot be dated
(a box score with no fixture on either side), it is a disagreement.

Some things are never compared, and the result says so rather than counting
them as matches:

* files outside the six layers (``data/errors``, ``data/reports``,
  ``data/research``, raw pages, a sample's manifest, symlinks), listed with
  counts;
* files whose collection stamp is identical on both sides and that no run
  record vouches for (``unproven``): a shadow branch starts as a copy of main,
  so an identical file with main's stamp proves nothing about the new
  pipeline;
* units a run record marks ``skipped``, ``failed`` or ``lost``
  (``excluded``).

Anything the module cannot read or does not recognise (an unknown schema, a
file it has no rule for, two homes at different levels) is an ``error``: the
check could not run, which is never mistaken for parity.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.paths import UNDECLARED_HOME_LEVEL, marker_level

SCHEMA = "touchline.parity/1"

MATCH = "match"
TIMING = "timing"
DISAGREEMENT = "disagreement"

# The schemas this module knows how to break into records. A season file on
# either side carrying anything else is an error, not a skipped file: the
# check must learn a new schema before it can vouch for it.
SEASON_SCHEMAS = {
    "fixtures": ("touchline.fixtures/2",),
    "rosters": ("touchline.rosters/1",),
    "stats": ("touchline.stats/1",),
    # /1 lacks player_ref on box-score lines; readers admit both until the
    # backfill rewrites every season (contracts/CHANGELOG.md, 2026-09-07).
    "matches": ("touchline.matches/1", "touchline.matches/2"),
}
COVERAGE_SCHEMA = "touchline.coverage/1"
REFERENCE_FILES = ("membership.json", "programmes.json")
# The field and value that version each reference file.
REFERENCE_VERSIONS: dict[str, tuple[str, Any]] = {
    "membership.json": ("version", 1),
    "programmes.json": ("schema", "touchline.programmes/2"),
}

# Paths under data/ that are deliberately not compared. They are run
# artefacts (errors), derived documents (reports), working notes (research),
# the raw page archive, or a sample's own manifest.
NOT_COMPARED_DIRS = {
    "errors": "collector error reports: run artefacts, not data",
    "reports": "derived reports, not collected data",
    "research": "research notes, not collected data",
    "raw_html": "raw page archive: compared through what was parsed from it",
}
NOT_COMPARED_FILES = {
    "sample.json": "sample-home manifest, written by the cut, not the collector",
}

SEASON_FILE = re.compile(
    r"^(?P<season>\d{4})-(?P<gender>men|women)-(?P<conf>[a-z0-9-]+)\.json$"
)

# Fields that record when a collect ran, not what it found.
VOLATILE_CELL_FIELDS = ("confirmed_at", "verified")

# Coverage layers and the season-file layer each describes.
CELL_LAYER = {
    "schedule": "fixtures",
    "roster": "rosters",
    "stats": "stats",
    "matches": "matches",
}

# Two collections closer than this are the same moment: nothing can be timing.
SIMULTANEOUS = dt.timedelta(minutes=1)

DEFAULT_LAG_DAYS = 3

# Stat fields that are ratios or averages: free to move either way.
RATIO_STATS = {"shot_pct", "sog_pct", "save_pct", "gaa"}

FIELD_DIFF_CAP = 12


# ---------------------------------------------------------------------------
# Reading a home


class ParityError(Exception):
    """The check could not run: unreadable input, or input it cannot judge."""


@dataclass(frozen=True)
class Entry:
    path: str  # relative to the home root, posix
    digest: str  # git blob sha1 of the content ("" for a symlink)
    symlink: bool = False


class Tree:
    """One side of the comparison."""

    label: str

    def entries(self) -> dict[str, Entry]:
        raise NotImplementedError

    def read(self, path: str) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        return None


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(
        b"blob %d\0" % len(data) + data, usedforsecurity=False
    ).hexdigest()


def _comparable(rel: str) -> bool:
    """Could this path hold records (or the level marker)?"""
    if rel == "touchline-data.yaml":
        return True
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != "data":
        return False
    return not (len(parts) > 2 and parts[1] in NOT_COMPARED_DIRS)


class DirTree(Tree):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.label = str(root)

    def entries(self) -> dict[str, Entry]:
        out: dict[str, Entry] = {}
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root).as_posix()
            if rel.startswith(".git/") or rel == ".git":
                continue
            if p.is_symlink():
                out[rel] = Entry(rel, "", symlink=True)
            elif p.is_file():
                # Files never compared (raw pages, errors, reports) are
                # listed for the count but never read.
                digest = _blob_sha(self.read(rel)) if _comparable(rel) else ""
                out[rel] = Entry(rel, digest)
        return out

    def read(self, path: str) -> bytes:
        # No cache: a compared file is read twice (hash, then parse), which
        # keeps memory bounded by the largest file, not the whole home.
        try:
            return (self.root / path).read_bytes()
        except OSError as exc:
            raise ParityError(f"{self.label}: cannot read {path}: {exc}") from exc


class GitTree(Tree):
    """A commit of a data-home clone, read with ``git cat-file``, no checkout."""

    def __init__(self, repo: Path, ref: str) -> None:
        self.repo = repo
        self.ref = ref
        self.label = f"{repo}@{ref}"
        try:
            self.commit = self._git(
                "rev-parse", "--verify", f"{ref}^{{commit}}"
            ).strip()
        except subprocess.CalledProcessError as exc:
            raise ParityError(
                f"{self.label}: not a commit ({exc.stderr.strip()})"
            ) from exc
        self._proc: subprocess.Popen[bytes] | None = None
        self._entries: dict[str, Entry] | None = None

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def entries(self) -> dict[str, Entry]:
        if self._entries is None:
            listing = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo),
                    "ls-tree",
                    "-r",
                    "-z",
                    "--full-tree",
                    self.commit,
                ],
                check=True,
                capture_output=True,
            ).stdout
            out: dict[str, Entry] = {}
            for raw in listing.split(b"\0"):
                if not raw:
                    continue
                meta, _, path_b = raw.partition(b"\t")
                mode, kind, sha = meta.decode().split()
                path = path_b.decode()
                if kind != "blob":
                    continue
                out[path] = Entry(path, sha, symlink=mode == "120000")
            self._entries = out
        return self._entries

    def read(self, path: str) -> bytes:
        entry = self.entries().get(path)
        if entry is None:
            raise FileNotFoundError(path)
        if self._proc is None:
            self._proc = subprocess.Popen(
                ["git", "-C", str(self.repo), "cat-file", "--batch"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(entry.digest.encode() + b"\n")
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            raise ParityError(f"{self.label}: cannot read {path}")
        size = int(header[2])
        data = self._proc.stdout.read(size)
        self._proc.stdout.read(1)  # trailing newline
        return data

    def close(self) -> None:
        if self._proc is not None:
            assert self._proc.stdin
            self._proc.stdin.close()
            self._proc.wait()
            self._proc = None


def open_tree(spec: str) -> Tree:
    """``PATH`` (a directory) or ``PATH@REF`` (a commit of a git clone)."""
    path = Path(spec).expanduser()
    if path.is_dir():
        if not (path / "touchline-data.yaml").is_file():
            raise ParityError(f"{spec}: not a data home (no touchline-data.yaml)")
        return DirTree(path.resolve())
    repo, sep, ref = spec.rpartition("@")
    if sep and repo and ref and Path(repo).expanduser().is_dir():
        tree = GitTree(Path(repo).expanduser().resolve(), ref)
        if "touchline-data.yaml" not in tree.entries():
            raise ParityError(
                f"{spec}: not a data home (no touchline-data.yaml at {ref})"
            )
        return tree
    raise ParityError(f"{spec}: neither a directory nor PATH@REF")


def _level(tree: Tree) -> str:
    """The home's level by the pipeline's own marker rule (src/paths.py):
    a marker with no ``level`` line is the d2 every pre-level home is."""
    text = tree.read("touchline-data.yaml").decode("utf-8", "replace")
    kind = re.search(r"^\s*kind:\s*(\S+)\s*$", text, re.MULTILINE)
    if kind is None or kind.group(1) != "touchline-data":
        raise ParityError(
            f"{tree.label}: touchline-data.yaml is not a Touchline marker"
        )
    try:
        level = marker_level(text)
    except ValueError as exc:
        raise ParityError(f"{tree.label}: touchline-data.yaml {exc}") from exc
    return level or UNDECLARED_HOME_LEVEL


# ---------------------------------------------------------------------------
# Run records (collect-record.json from the cloud collect)


@dataclass(frozen=True)
class Unit:
    season: int
    gender: str
    conference: str  # lower case, as in file names
    result: str
    collected_at: dt.datetime | None
    reason: str | None
    division: str = ""


EXCLUDING_RESULTS = {"skipped", "failed", "lost"}
VOUCHING_RESULTS = {"changed", "no-change"}


def load_records(paths: Iterable[Path]) -> dict[tuple[int, str, str], Unit]:
    """Units keyed ``(season, gender, conference)``, merged by ``_merge_unit``."""
    units: dict[tuple[int, str, str], Unit] = {}
    for path in paths:
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            raise ParityError(f"run record {path}: {exc}") from exc
        if not isinstance(doc, dict):
            raise ParityError(f"run record {path}: not a JSON object")
        if doc.get("schema") != "touchline.collect-record/1":
            raise ParityError(
                f"run record {path}: schema {doc.get('schema')!r} is not touchline.collect-record/1"
            )
        division = doc.get("division")
        if not isinstance(division, str) or not division:
            raise ParityError(f"run record {path}: no division")
        season = doc.get("season")
        units_in = doc.get("units")
        if units_in is None:
            units_in = []
        if not isinstance(units_in, list):
            raise ParityError(f"run record {path}: units is not a list")
        for unit in units_in:
            try:
                key = (
                    int(unit.get("season", season)),
                    str(unit["gender"]),
                    str(unit["conference"]).lower(),
                )
                result = str(unit["result"])
                if result not in EXCLUDING_RESULTS | VOUCHING_RESULTS:
                    raise ValueError(f"unknown result {result!r}")
                stamp = unit.get("collected_at")
                new = Unit(
                    *key,
                    result=result,
                    collected_at=_ts(stamp) if stamp else None,
                    reason=unit.get("reason"),
                    division=division,
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ParityError(
                    f"run record {path}: bad unit {unit!r}: {exc}"
                ) from exc
            units[key] = _merge_unit(units.get(key), new)
    return units


def _merge_unit(old: Unit | None, new: Unit) -> Unit:
    """Two records naming one unit (the hosted and presto jobs, or two runs):
    a collect that landed beats one that did not, then the later one wins."""
    if old is None:
        return new
    old_ok, new_ok = old.result in VOUCHING_RESULTS, new.result in VOUCHING_RESULTS
    if old_ok != new_ok:
        return old if old_ok else new
    if old.collected_at and new.collected_at and old.collected_at > new.collected_at:
        return old
    return new


# ---------------------------------------------------------------------------
# Findings


@dataclass
class Finding:
    layer: str
    file: str
    key: str
    kind: str  # added | removed | changed
    cls: str  # timing | disagreement
    reason: str
    programmes: list[str] = field(default_factory=list)
    date: str | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    fields_truncated: int = 0

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "class": self.cls,
            "layer": self.layer,
            "file": self.file,
            "key": self.key,
            "change": self.kind,
            "reason": self.reason,
            "programmes": self.programmes,
        }
        if self.date:
            out["date"] = self.date
        if self.fields:
            out["fields"] = self.fields
        if self.fields_truncated:
            out["fields_truncated"] = self.fields_truncated
        return out


@dataclass
class Result:
    expected: str
    actual: str
    lag_days: int
    require_complete: bool
    level: str | None = None
    counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(
            lambda: {MATCH: 0, TIMING: 0, DISAGREEMENT: 0}
        )
    )
    findings: list[Finding] = field(default_factory=list)
    identical_files: int = 0
    compared_files: int = 0
    unproven: list[dict[str, str]] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    not_compared: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, layer: str, cls: str, n: int = 1) -> None:
        self.counts[layer][cls] += n

    def find(self, f: Finding) -> None:
        self.findings.append(f)
        self.add(f.layer, f.cls)

    @property
    def disagreements(self) -> list[Finding]:
        return [f for f in self.findings if f.cls == DISAGREEMENT]

    @property
    def timing(self) -> list[Finding]:
        return [f for f in self.findings if f.cls == TIMING]

    @property
    def complete(self) -> bool:
        return not self.unproven and not self.excluded

    @property
    def verdict(self) -> str:
        if self.errors:
            return "error"
        if self.disagreements:
            return "fail"
        if self.require_complete and not self.complete:
            return "fail"
        return "pass"

    def to_json(self) -> dict[str, Any]:
        layers = {k: dict(v) for k, v in sorted(self.counts.items())}
        totals = {MATCH: 0, TIMING: 0, DISAGREEMENT: 0}
        for v in layers.values():
            for k in totals:
                totals[k] += v[k]
        return {
            "schema": SCHEMA,
            "verdict": self.verdict,
            "expected": self.expected,
            "actual": self.actual,
            "level": self.level,
            "lag_days": self.lag_days,
            "require_complete": self.require_complete,
            "complete": self.complete,
            "totals": totals,
            "layers": layers,
            "units_excluded": sum(
                1 for u in self.excluded if u["path"].startswith("unit ")
            ),
            "coverage_cells": {
                "unproven": sum(1 for u in self.unproven if "#" in u["path"]),
                "excluded": sum(1 for u in self.excluded if "#" in u["path"]),
            },
            "files": {
                "compared": self.compared_files,
                "identical": self.identical_files,
                "unproven": sum(1 for u in self.unproven if "#" not in u["path"]),
                "excluded": sum(
                    1
                    for u in self.excluded
                    if "#" not in u["path"] and not u["path"].startswith("unit ")
                ),
                "not_compared": sum(int(n["count"]) for n in self.not_compared),
            },
            "errors": self.errors,
            "notes": self.notes,
            "findings": [f.to_json() for f in self.findings],
            "unproven": self.unproven,
            "excluded": self.excluded,
            "not_compared": self.not_compared,
        }


# ---------------------------------------------------------------------------
# Helpers


def _ts(value: Any) -> dt.datetime:
    stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.UTC)
    return stamp


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def deep_diff(a: Any, b: Any, path: str = "") -> Iterator[tuple[str, Any, Any]]:
    """Leaf-level differences between two JSON values."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            sub = f"{path}.{k}" if path else str(k)
            if k not in a:
                yield sub, None, b[k]
            elif k not in b:
                yield sub, a[k], None
            else:
                yield from deep_diff(a[k], b[k], sub)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from deep_diff(x, y, f"{path}[{i}]")
    elif type(a) is not type(b) or a != b:
        # bool is an int subclass; 1 and True are different facts here.
        yield path, a, b


def same(a: Any, b: Any) -> bool:
    """Equal as JSON facts: ``==`` with types held, so ``true`` is not ``1``
    and ``1`` is not ``1.0``."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(v, b[k]) for k, v in a.items())
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _lost(early: Any, late: Any, path: str = "") -> str | None:
    """The first place the later value holds less than the earlier one did:
    a key whose value vanished or became null, or a list that got shorter."""
    if isinstance(early, dict):
        if not isinstance(late, dict):
            return path or "<root>"
        for k, v in early.items():
            sub = f"{path}.{k}" if path else str(k)
            if v is not None and late.get(k) is None:
                return sub
            hit = _lost(v, late.get(k), sub)
            if hit:
                return hit
        return None
    if isinstance(early, list):
        if not isinstance(late, list) or len(late) < len(early):
            return path or "<root>"
        for i, (x, y) in enumerate(zip(early, late, strict=False)):
            hit = _lost(x, y, f"{path}[{i}]")
            if hit:
                return hit
    return None


def _short(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True)
        if len(text) > 160:
            kind = "object" if isinstance(value, dict) else f"list of {len(value)}"
            return f"<{kind}, {len(text)} chars>"
    if isinstance(value, str) and len(value) > 160:
        return value[:157] + "..."
    return value


def _fields(a: Any, b: Any) -> tuple[list[dict[str, Any]], int]:
    diffs = list(deep_diff(a, b))
    shown = [
        {"path": p, "expected": _short(x), "actual": _short(y)}
        for p, x, y in diffs[:FIELD_DIFF_CAP]
    ]
    return shown, max(0, len(diffs) - FIELD_DIFF_CAP)


def _check_other_version(path: str, doc: Any, label: str) -> None:
    """Coverage and reference files: refuse a version this check cannot read."""
    if not isinstance(doc, dict):
        raise ParityError(f"{path} ({label}): not a JSON object")
    name = path.rsplit("/", 1)[1]
    field_name, want = (
        ("schema", COVERAGE_SCHEMA)
        if name == "coverage.json"
        else REFERENCE_VERSIONS[name]
    )
    if doc.get(field_name) != want:
        raise ParityError(
            f"{path} ({label}): {field_name} {doc.get(field_name)!r}, this check reads {want!r}"
        )


def _dig(doc: Any, dotted: str) -> Any:
    for part in dotted.split(".", 1) if "." in dotted else [dotted]:
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def _strip_player_ref(value: Any) -> Any:
    """A matches/2 document as /1 would carry it (and without its schema tag)."""
    if isinstance(value, dict):
        return {
            k: _strip_player_ref(v)
            for k, v in value.items()
            if k not in ("player_ref", "schema")
        }
    if isinstance(value, list):
        return [_strip_player_ref(v) for v in value]
    return value


def _keyed(rows: list[dict[str, Any]], *keys: str) -> dict[str, dict[str, Any]]:
    """Index rows by the first present key field; repeats get ``#2``, ``#3``."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        base = None
        for k in keys:
            if row.get(k) not in (None, ""):
                base = f"{k}={row[k]}"
                break
        if base is None:
            base = f"name={row.get('name')}|number={row.get('number')}"
        key, n = base, 1
        while key in out:
            n += 1
            key = f"{base}#{n}"
        out[key] = row
    return out


# ---------------------------------------------------------------------------
# The comparison


@dataclass
class Side:
    tree: Tree
    entries: dict[str, Entry]
    docs: dict[str, Any] = field(default_factory=dict)

    def load(self, path: str) -> Any:
        if path not in self.docs:
            try:
                self.docs[path] = json.loads(self.tree.read(path))
            except (OSError, ValueError) as exc:
                raise ParityError(
                    f"{self.tree.label}: cannot read {path}: {exc}"
                ) from exc
        return self.docs[path]


@dataclass
class Window:
    """When each side collected a record, and what that lets timing explain."""

    expected_at: dt.datetime | None
    actual_at: dt.datetime | None
    lag: dt.timedelta

    @property
    def simultaneous(self) -> bool:
        if self.expected_at is None or self.actual_at is None:
            return True  # undatable: nothing can be timing
        return abs(self.expected_at - self.actual_at) < SIMULTANEOUS

    @property
    def earlier(self) -> dt.datetime:
        assert self.expected_at and self.actual_at
        return min(self.expected_at, self.actual_at)

    @property
    def later(self) -> dt.datetime:
        assert self.expected_at and self.actual_at
        return max(self.expected_at, self.actual_at)

    @property
    def actual_is_later(self) -> bool:
        assert self.expected_at and self.actual_at
        return self.actual_at > self.expected_at

    def open_for(self, day: dt.date | None) -> bool:
        """A game on ``day`` could still change between the two collections."""
        if self.simultaneous or day is None:
            return False
        return day >= (self.earlier - self.lag).date()

    def played_between(self, day: dt.date | None) -> bool:
        """A game on ``day`` could have been played between the collections."""
        if not self.open_for(day):
            return False
        assert day is not None
        return day <= (self.later + dt.timedelta(days=1)).date()

    def describe(self) -> str:
        if self.expected_at is None or self.actual_at is None:
            return "no collection time on one side"
        hours = abs(self.actual_at - self.expected_at).total_seconds() / 3600
        side = "actual" if self.actual_at > self.expected_at else "expected"
        return f"{side} collected {hours:.1f}h later"


STATUS_RANK = {"scheduled": 0, "postponed": 0, "cancelled": 0, "live": 1, "final": 2}


class Comparison:
    def __init__(
        self,
        expected: Tree,
        actual: Tree,
        *,
        lag_days: int = DEFAULT_LAG_DAYS,
        records: dict[tuple[int, str, str], Unit] | None = None,
        require_complete: bool = False,
        compare_inherited: bool = False,
    ) -> None:
        self.compare_inherited = compare_inherited
        self.e = Side(expected, expected.entries())
        self.a = Side(actual, actual.entries())
        self.lag = dt.timedelta(days=lag_days)
        self.units = records or {}
        self.result = Result(expected.label, actual.label, lag_days, require_complete)
        # (season, gender, slug) -> game dates, from both sides' fixtures
        self.game_days: dict[tuple[int, str, str], set[dt.date]] = defaultdict(set)
        # (season, gender, match id) -> (date, programmes)
        self.fixture_index: dict[
            tuple[int, str, str], tuple[dt.date | None, list[str]]
        ] = {}
        # (season, gender, match id) -> every date either side gives it
        self.fixture_dates: dict[tuple[int, str, str], set[dt.date]] = defaultdict(set)
        # (season, gender, slug) -> conference (file stem), for coverage cells
        self.member_of: dict[tuple[int, str, str], str] = {}

    # -- entry point --------------------------------------------------------

    def run(self) -> Result:
        r = self.result
        try:
            le, la = _level(self.e.tree), _level(self.a.tree)
            if le != la:
                r.errors.append(
                    f"homes are at different levels: expected {le!r}, actual {la!r}"
                )
                return r
            r.level = le
            foreign = sorted({u.division for u in self.units.values()} - {le})
            if foreign:
                r.errors.append(
                    f"run records name division {', '.join(foreign)}, but the homes are {le!r}"
                )
                return r
            season_files, other = self._classify_paths()
            # Every unit a run says it did not land is excluded, whether or
            # not it left a file behind: a failed first collect leaves none.
            for (season, gender, conf), unit in sorted(self.units.items()):
                if unit.result in EXCLUDING_RESULTS:
                    r.excluded.append(
                        {
                            "path": f"unit {season}-{gender}-{conf}",
                            "reason": f"run record says {unit.result}"
                            + (f": {unit.reason}" if unit.reason else ""),
                        }
                    )
            self._index_fixtures(season_files)
            for path in season_files:
                self._season_file(path)
                self._release(path)
            for path in other:
                self._other_file(path)
                self._release(path)
        except ParityError as exc:
            r.errors.append(str(exc))
        except (ValueError, TypeError, AttributeError, KeyError, OSError) as exc:
            # Malformed input (a bad timestamp, a list where an object
            # belongs, an unreadable file): the check could not run.
            r.errors.append(f"malformed input: {type(exc).__name__}: {exc}")
        r.findings.sort(
            key=lambda f: (f.cls != DISAGREEMENT, f.file, f.date or "", f.key)
        )
        return r

    def _release(self, path: str) -> None:
        """Drop a compared file's parsed documents; only fixtures' are needed
        again, and the fixture index already holds what they are needed for."""
        self.e.docs.pop(path, None)
        self.a.docs.pop(path, None)

    # -- paths --------------------------------------------------------------

    def _classify_paths(self) -> tuple[list[str], list[str]]:
        r = self.result
        season: list[str] = []
        other: list[str] = []
        skipped: dict[tuple[str, str], int] = defaultdict(int)
        for path in sorted(set(self.e.entries) | set(self.a.entries)):
            if not path.startswith("data/"):
                continue
            parts = path.split("/")
            ent = self.e.entries.get(path) or self.a.entries.get(path)
            assert ent is not None
            if ent.symlink or (
                self.e.entries.get(path, ent).symlink
                or self.a.entries.get(path, ent).symlink
            ):
                r.not_compared.append(
                    {
                        "path": path,
                        "count": 1,
                        "reason": "symlink: not data, and not portable",
                    }
                )
                continue
            top = parts[1]
            if len(parts) > 2 and top in NOT_COMPARED_DIRS:
                skipped[(f"data/{top}/", NOT_COMPARED_DIRS[top])] += 1
            elif len(parts) == 2 and top in NOT_COMPARED_FILES:
                skipped[(path, NOT_COMPARED_FILES[top])] += 1
            elif len(parts) == 3 and top in SEASON_SCHEMAS:
                if not SEASON_FILE.match(parts[2]):
                    r.errors.append(
                        f"{path}: a {top} file not named <season>-<gender>-<conf>.json"
                    )
                else:
                    season.append(path)
            elif path == "data/coverage.json" or (
                len(parts) == 3 and top == "reference" and parts[2] in REFERENCE_FILES
            ):
                other.append(path)
            else:
                r.errors.append(f"{path}: no parity rule for this file")
        for (where, why), n in sorted(skipped.items()):
            r.not_compared.append({"path": where, "count": n, "reason": why})
        # Fixtures first, so matches and stats can look up their games.
        season.sort(key=lambda p: (list(SEASON_SCHEMAS).index(p.split("/")[1]), p))
        return season, other

    # -- fixture index ------------------------------------------------------

    def _index_fixtures(self, season_files: list[str]) -> None:
        for path in season_files:
            if not path.startswith("data/fixtures/"):
                continue
            m = SEASON_FILE.match(path.rsplit("/", 1)[1])
            assert m
            season, gender, conf = int(m["season"]), m["gender"], m["conf"]
            for side in (self.e, self.a):
                if path not in side.entries:
                    continue
                doc = side.load(path)
                for prog in doc.get("programmes") or []:
                    if isinstance(prog, dict) and prog.get("slug"):
                        self.member_of.setdefault((season, gender, prog["slug"]), conf)
                for fx in doc.get("fixtures") or []:
                    day = _date(fx.get("date"))
                    progs = [s for s in (fx.get("home"), fx.get("away")) if s]
                    key = (season, gender, str(fx.get("id")))
                    if day:
                        self.fixture_dates[key].add(day)
                    if (
                        key not in self.fixture_index
                        or self.fixture_index[key][0] is None
                    ):
                        self.fixture_index[key] = (day, progs)
                    # Only a game with evidence of play can explain totals
                    # or coverage that moved.
                    if day and fx.get("status") in ("live", "final"):
                        for slug in progs:
                            self.game_days[(season, gender, slug)].add(day)

    # -- season files -------------------------------------------------------

    def _unit(self, season: int, gender: str, conf: str) -> Unit | None:
        return self.units.get((season, gender, conf))

    def _season_file(self, path: str) -> None:
        r = self.result
        layer = path.split("/")[1]
        m = SEASON_FILE.match(path.rsplit("/", 1)[1])
        assert m
        season, gender, conf = int(m["season"]), m["gender"], m["conf"]
        unit = self._unit(season, gender, conf)
        if unit and unit.result in EXCLUDING_RESULTS:
            r.excluded.append(
                {
                    "path": path,
                    "reason": f"run record says {unit.result}"
                    + (f": {unit.reason}" if unit.reason else ""),
                }
            )
            return
        in_e, in_a = path in self.e.entries, path in self.a.entries
        want = SEASON_SCHEMAS[layer]
        if not (in_e and in_a):
            only_doc = (self.a if in_a else self.e).load(path)
            if not isinstance(only_doc, dict) or only_doc.get("schema") not in want:
                got = only_doc.get("schema") if isinstance(only_doc, dict) else None
                r.errors.append(
                    f"{path}: schema {got!r}, this check reads {', '.join(want)}"
                )
                return
            r.find(
                Finding(
                    layer,
                    path,
                    "<file>",
                    "added" if in_a else "removed",
                    DISAGREEMENT,
                    f"whole file only on the {'actual' if in_a else 'expected'} side",
                )
            )
            return
        de, da = self.e.load(path), self.a.load(path)
        for label, doc in (("expected", de), ("actual", da)):
            if not isinstance(doc, dict):
                r.errors.append(f"{path} ({label}): not a JSON object")
                return
        for label, doc in (("expected", de), ("actual", da)):
            if doc.get("schema") not in want:
                r.errors.append(
                    f"{path} ({label}): schema {doc.get('schema')!r}, this check reads {', '.join(want)}"
                )
                return
            if doc.get("season") != season or doc.get("gender") != gender:
                r.errors.append(
                    f"{path} ({label}): header season/gender disagree with the file name"
                )
                return
        if de.get("schema") != da.get("schema"):
            r.find(
                Finding(
                    layer,
                    path,
                    "<schema>",
                    "changed",
                    DISAGREEMENT,
                    f"schema versions differ, expected {de.get('schema')} and actual {da.get('schema')}; "
                    "records are compared without player_ref, which only /2 carries",
                )
            )
            de, da = _strip_player_ref(de), _strip_player_ref(da)
        te, ta = de.get("collected_at"), da.get("collected_at")
        vouched = (
            unit is not None
            and unit.result in VOUCHING_RESULTS
            and unit.collected_at is not None
        )
        same_bytes = self.e.entries[path].digest == self.a.entries[path].digest
        # A file whose facts differ is always compared: under one stamp, as a
        # simultaneous collection, so any difference disagrees. Formatting
        # alone (same facts, other bytes) stays unproven.
        if (
            te == ta
            and not vouched
            and not self.compare_inherited
            and (same_bytes or same(de, da))
        ):
            r.unproven.append(
                {
                    "path": path,
                    "reason": "same collected_at on both sides and no run record vouches for the actual side: "
                    "this file was not independently collected",
                }
            )
            return
        r.compared_files += 1
        if same_bytes:
            r.identical_files += 1
        window = Window(
            _ts(te) if te else None,
            unit.collected_at if vouched and unit else (_ts(ta) if ta else None),
            self.lag,
        )
        ctx = (season, gender)
        getattr(self, f"_layer_{layer}")(path, ctx, de, da, window)

    def _header(
        self, layer: str, path: str, de: dict, da: dict, skip: set[str]
    ) -> None:
        """File-level facts outside the record lists, compared exactly."""
        a_rest = {k: v for k, v in de.items() if k not in skip}
        b_rest = {k: v for k, v in da.items() if k not in skip}
        if same(a_rest, b_rest):
            self.result.add(layer, MATCH)
            return
        fields, more = _fields(a_rest, b_rest)
        self.result.find(
            Finding(
                layer,
                path,
                "<header>",
                "changed",
                DISAGREEMENT,
                "file header differs (programmes named, gaps, how conference games were decided)",
                fields=fields,
                fields_truncated=more,
            )
        )

    # fixtures

    def _layer_fixtures(
        self, path: str, ctx: tuple[int, str], de: dict, da: dict, w: Window
    ) -> None:
        self._header("fixtures", path, de, da, {"collected_at", "fixtures"})
        ea = _keyed(de.get("fixtures") or [], "id")
        aa = _keyed(da.get("fixtures") or [], "id")
        for key in sorted(set(ea) | set(aa)):
            x, y = ea.get(key), aa.get(key)
            if same(x, y):
                self.result.add("fixtures", MATCH)
                continue
            row = y if x is None else x
            assert row is not None
            day = min(
                d
                for d in (
                    _date((x or {}).get("date")),
                    _date((y or {}).get("date")),
                    dt.date.max,
                )
                if d
            )
            day = None if day == dt.date.max else day
            progs = [s for s in (row.get("home"), row.get("away")) if s]
            cls, reason = self._fixture_class(x, y, day, w)
            kind = "added" if x is None else "removed" if y is None else "changed"
            fields, more = _fields(x, y) if x is not None and y is not None else ([], 0)
            self.result.find(
                Finding(
                    "fixtures",
                    path,
                    key.removeprefix("id="),
                    kind,
                    cls,
                    reason,
                    progs,
                    str(day) if day else None,
                    fields,
                    more,
                )
            )

    def _fixture_class(
        self, x: dict | None, y: dict | None, day: dt.date | None, w: Window
    ) -> tuple[str, str]:
        when = w.describe()
        if w.simultaneous:
            return (
                DISAGREEMENT,
                f"differs between collections made at the same time ({when})",
            )
        if not w.open_for(day):
            return (
                DISAGREEMENT,
                f"game dated {day}, more than {w.lag.days} days before the earlier collection ({when})",
            )
        early, late = (x, y) if w.actual_is_later else (y, x)
        if late is None:
            assert early is not None
            if early.get("status") in ("live", "final"):
                return (
                    DISAGREEMENT,
                    f"a played game vanished from the later collection ({when})",
                )
            return (
                TIMING,
                f"an unplayed fixture was dropped from the schedule before the later collection ({when})",
            )
        played = late.get("status") in ("live", "final")
        late_day = _date(late.get("date"))
        if played and not w.played_between(late_day):
            return (
                DISAGREEMENT,
                f"the later side has a result for a game dated {late_day}, outside the window between the collections ({when})",
            )
        if early is None:
            return TIMING, f"fixture first listed after the earlier collection ({when})"
        for score in ("home_score", "away_score"):
            if score in early and score not in late:
                return (
                    DISAGREEMENT,
                    f"the later collection lost the {score} the earlier one had ({when})",
                )
        for ident in ("home", "away"):
            if not same(early.get(ident), late.get(ident)):
                return (
                    DISAGREEMENT,
                    f"the two sides name different teams for one fixture id ({when})",
                )
        re_, rl = (
            STATUS_RANK.get(str(early.get("status")), -1),
            STATUS_RANK.get(str(late.get("status")), -1),
        )
        if re_ < 0 or rl < 0:
            return (
                DISAGREEMENT,
                f"unknown fixture status {early.get('status')!r}/{late.get('status')!r}",
            )
        if rl < re_:
            return (
                DISAGREEMENT,
                f"status went backwards, {early.get('status')} then {late.get('status')} ({when})",
            )
        if early.get("status") == late.get("status") == "final":
            return (
                TIMING,
                f"a recent result was revised by the host after the earlier collection ({when})",
            )
        return (
            TIMING,
            f"game moved on between collections, {early.get('status')} then {late.get('status')} ({when})",
        )

    # matches

    def _layer_matches(
        self, path: str, ctx: tuple[int, str], de: dict, da: dict, w: Window
    ) -> None:
        self._header("matches", path, de, da, {"collected_at", "matches", "missing"})
        me, ma = de.get("matches") or {}, da.get("matches") or {}
        gone_e, gone_a = de.get("missing") or {}, da.get("missing") or {}
        for key in sorted(set(me) | set(ma) | set(gone_e) | set(gone_a)):
            x, y = me.get(key), ma.get(key)
            if x is not None and same(x, y):
                self.result.add("matches", MATCH)
                continue
            if x is None and y is None:
                # A gap on both sides, or on one side with no box score on
                # the other.
                if key in gone_e and key in gone_a:
                    if same(gone_e[key], gone_a[key]):
                        self.result.add("matches", MATCH)
                    else:
                        self.result.find(
                            Finding(
                                "matches",
                                path,
                                key,
                                "changed",
                                DISAGREEMENT,
                                "both sides name this gap, for different reasons",
                                self._programmes(ctx, key),
                                self._day_str(ctx, key),
                                *_fields(gone_e[key], gone_a[key]),
                            )
                        )
                elif (key in gone_e) == (key in gone_a):
                    self.result.add("matches", MATCH)
                else:
                    side = "expected" if key in gone_e else "actual"
                    self.result.find(
                        Finding(
                            "matches",
                            path,
                            key,
                            "changed",
                            DISAGREEMENT,
                            f"gap named only on the {side} side: {(gone_e.get(key) or gone_a.get(key))}",
                            self._programmes(ctx, key),
                            self._day_str(ctx, key),
                        )
                    )
                continue
            days = sorted(self.fixture_dates.get((*ctx, key), ()))
            kind = "added" if x is None else "removed" if y is None else "changed"
            cls, reason = self._match_class(x, y, days, w)
            if (
                x is not None
                and y is not None
                and all("player_ref" in p for p, _, _ in deep_diff(x, y))
            ):
                reason += (
                    "; only player_ref differs (who a line is, resolved from the season's rosters"
                    " and the opponent's box score), so look at the rosters first"
                )
            fields, more = _fields(x, y) if x is not None and y is not None else ([], 0)
            self.result.find(
                Finding(
                    "matches",
                    path,
                    key,
                    kind,
                    cls,
                    reason,
                    self._programmes(ctx, key),
                    self._day_str(ctx, key),
                    fields,
                    more,
                )
            )

    def _programmes(self, ctx: tuple[int, str], key: str) -> list[str]:
        progs = self.fixture_index.get((*ctx, key), (None, []))[1]
        if progs:
            return progs
        parts = key.split(":")
        return [parts[1]] if len(parts) == 3 else []

    def _day_str(self, ctx: tuple[int, str], key: str) -> str | None:
        day = self.fixture_index.get((*ctx, key), (None, []))[0]
        return str(day) if day else None

    def _match_class(
        self, x: dict | None, y: dict | None, days: list[dt.date], w: Window
    ) -> tuple[str, str]:
        """Every date either side gives the game must fall in the played
        window: a fixture moved between collections cannot lend its old date
        to a box score."""
        when = w.describe()
        if not days:
            return (
                DISAGREEMENT,
                "no fixture on either side dates this box score, so no timing can explain it",
            )
        if w.simultaneous:
            return (
                DISAGREEMENT,
                f"differs between collections made at the same time ({when})",
            )
        for day in days:
            if not w.open_for(day):
                return (
                    DISAGREEMENT,
                    f"game dated {day}, more than {w.lag.days} days before the earlier collection ({when})",
                )
            if not w.played_between(day):
                return (
                    DISAGREEMENT,
                    f"box score for a game dated {day}, after both collections ({when})",
                )
        early, late = (x, y) if w.actual_is_later else (y, x)
        if late is None:
            return (
                DISAGREEMENT,
                f"a box score vanished from the later collection ({when})",
            )
        if early is None:
            return TIMING, f"box score posted after the earlier collection ({when})"
        lost = _lost(early, late)
        if lost:
            return (
                DISAGREEMENT,
                f"the later box score lost {lost}, which the earlier one had ({when})",
            )
        return (
            TIMING,
            f"box score revised by the host within {w.lag.days} days of the game ({when})",
        )

    # rosters

    def _layer_rosters(
        self, path: str, ctx: tuple[int, str], de: dict, da: dict, w: Window
    ) -> None:
        self._header("rosters", path, de, da, {"collected_at", "rosters"})
        re_, ra = de.get("rosters") or {}, da.get("rosters") or {}
        for slug in sorted(set(re_) | set(ra)):
            x, y = re_.get(slug), ra.get(slug)
            if same(x, y):
                self.result.add("rosters", MATCH)
                continue
            kind = "added" if x is None else "removed" if y is None else "changed"
            fields: list[dict[str, Any]] = []
            more = 0
            if x is not None and y is not None:
                fields, more = _fields(self._roster_view(x), self._roster_view(y))
            reason = (
                "rosters do not change with games, so no timing explains a roster difference"
                + (
                    ""
                    if w.simultaneous
                    else f"; {w.describe()}, and schools do edit roster pages: re-collect both sides together to settle it"
                )
            )
            self.result.find(
                Finding(
                    "rosters",
                    path,
                    slug,
                    kind,
                    DISAGREEMENT,
                    reason,
                    [slug],
                    None,
                    fields,
                    more,
                )
            )

    @staticmethod
    def _roster_view(team: dict) -> dict:
        out = {k: v for k, v in team.items() if k != "players"}
        out["players"] = _keyed(team.get("players") or [], "source_url")
        return out

    # stats

    def _layer_stats(
        self, path: str, ctx: tuple[int, str], de: dict, da: dict, w: Window
    ) -> None:
        self._header("stats", path, de, da, {"collected_at", "teams"})
        te, ta = de.get("teams") or {}, da.get("teams") or {}
        for slug in sorted(set(te) | set(ta)):
            x, y = te.get(slug), ta.get(slug)
            if same(x, y):
                self.result.add("stats", MATCH)
                continue
            kind = "added" if x is None else "removed" if y is None else "changed"
            vx = self._stats_view(x) if x is not None else None
            vy = self._stats_view(y) if y is not None else None
            fields, more = (
                _fields(vx, vy) if vx is not None and vy is not None else ([], 0)
            )
            games = sorted(
                d for d in self.game_days.get((*ctx, slug), ()) if w.played_between(d)
            )
            cls, reason = self._stats_class(vx, vy, games, w)
            self.result.find(
                Finding(
                    "stats",
                    path,
                    slug,
                    kind,
                    cls,
                    reason,
                    [slug],
                    str(games[-1]) if games else None,
                    fields,
                    more,
                )
            )

    @staticmethod
    def _stats_view(team: dict) -> dict:
        out = {k: v for k, v in team.items() if k not in ("players", "keepers")}
        out["players"] = _keyed(team.get("players") or [], "player_id", "bio_url")
        out["keepers"] = _keyed(team.get("keepers") or [], "player_id", "bio_url")
        return out

    def _stats_class(
        self, x: dict | None, y: dict | None, games: list[dt.date], w: Window
    ) -> tuple[str, str]:
        when = w.describe()
        if w.simultaneous:
            return (
                DISAGREEMENT,
                f"differs between collections made at the same time ({when})",
            )
        if not games:
            return (
                DISAGREEMENT,
                f"season totals differ but the team played no game between the collections ({when})",
            )
        early, late = (x, y) if w.actual_is_later else (y, x)
        if late is None:
            return (
                DISAGREEMENT,
                f"team statistics vanished from the later collection ({when})",
            )
        if early is None:
            return (
                TIMING,
                f"team statistics first published after the earlier collection, game on {games[-1]} ({when})",
            )
        for k in set(early) | set(late):
            if k in ("players", "keepers"):
                continue
            if not same(early.get(k), late.get(k)):
                return DISAGREEMENT, f"team field {k!r} differs ({when})"
        for group in ("players", "keepers"):
            pe, pl = early.get(group) or {}, late.get(group) or {}
            for pk, row in pe.items():
                if pk not in pl:
                    return (
                        DISAGREEMENT,
                        f"{group[:-1]} {pk} vanished from the later collection ({when})",
                    )
                bad = self._regressed(row, pl[pk])
                if bad:
                    return DISAGREEMENT, f"{group[:-1]} {pk}: {bad} ({when})"
        return (
            TIMING,
            f"season totals grew with games played between the collections ({', '.join(map(str, games))}; {when})",
        )

    @staticmethod
    def _regressed(early: dict, late: dict) -> str | None:
        for k in set(early) | set(late):
            a, b = early.get(k), late.get(k)
            if same(a, b):
                continue
            a_num = isinstance(a, (int, float)) and not isinstance(a, bool)
            b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
            if a_num and b_num and k in RATIO_STATS:
                continue
            if isinstance(a, int) and isinstance(b, int) and a_num and b_num:
                if b < a:
                    return f"{k} went down, {a} then {b}"
                continue
            if (
                a is None
                and k not in RATIO_STATS
                and isinstance(b, int)
                and b_num
                and b >= 0
            ):
                continue  # a count first printed once the player recorded one
            return f"{k} changed, {_short(a)!r} then {_short(b)!r}"
        return None

    # -- coverage and references ------------------------------------------

    def _other_file(self, path: str) -> None:
        r = self.result
        in_e, in_a = path in self.e.entries, path in self.a.entries
        layer = "coverage" if path.endswith("coverage.json") else "reference"
        if not (in_e and in_a):
            _check_other_version(
                path, (self.a if in_a else self.e).load(path), "only side"
            )
            r.find(
                Finding(
                    layer,
                    path,
                    "<file>",
                    "added" if in_a else "removed",
                    DISAGREEMENT,
                    "whole file on one side only",
                )
            )
            return
        r.compared_files += 1
        if self.e.entries[path].digest == self.a.entries[path].digest:
            r.identical_files += 1
        de, da = self.e.load(path), self.a.load(path)
        if layer == "coverage":
            self._coverage(path, de, da)
        else:
            self._reference(path, de, da)

    def _reference(self, path: str, de: Any, da: Any) -> None:
        """Both homes mirror the rib's packaged copy, so these are compared as
        one record per file: any difference means the two sides ran
        different rib versions, and one finding says so with the entries
        that differ, rather than one finding per entry."""
        name = path.rsplit("/", 1)[1]
        field_name, want = REFERENCE_VERSIONS[name]
        for label, doc in (("expected", de), ("actual", da)):
            if not isinstance(doc, dict):
                raise ParityError(f"{path} ({label}): not a JSON object")
            if doc.get(field_name) != want:
                raise ParityError(
                    f"{path} ({label}): {field_name} {doc.get(field_name)!r}, this check reads {want!r}"
                )
        if same(de, da):
            self.result.add("reference", MATCH)
            return
        changed: list[str] = []
        for key in sorted(set(de) | set(da)):
            x, y = de.get(key), da.get(key)
            if isinstance(x, dict) and isinstance(y, dict) and len(x) > 20:
                changed.extend(
                    f"{key}.{k}"
                    for k in sorted(set(x) | set(y))
                    if not same(x.get(k), y.get(k))
                )
            elif not same(x, y):
                changed.append(key)
        fields = [
            {"path": k, "expected": _short(_dig(de, k)), "actual": _short(_dig(da, k))}
            for k in changed[:FIELD_DIFF_CAP]
        ]
        self.result.find(
            Finding(
                "reference",
                path,
                path.rsplit("/", 1)[1],
                "changed",
                DISAGREEMENT,
                f"{len(changed)} entries differ: the sides mirror different rib versions of this reference; "
                "run both from the same rib commit",
                fields=fields,
                fields_truncated=max(0, len(changed) - FIELD_DIFF_CAP),
            )
        )

    def _coverage(self, path: str, de: dict, da: dict) -> None:
        r = self.result
        for label, doc in (("expected", de), ("actual", da)):
            if doc.get("schema") != COVERAGE_SCHEMA:
                raise ParityError(
                    f"{path} ({label}): schema {doc.get('schema')!r}, this check reads {COVERAGE_SCHEMA}"
                )
        ce, ca = de.get("cells") or {}, da.get("cells") or {}
        if not isinstance(ce, dict) or not isinstance(ca, dict):
            raise ParityError(f"{path}: cells is not an object")
        for key in sorted(set(ce) | set(ca)):
            x, y = ce.get(key), ca.get(key)
            for label, c in (("expected", x), ("actual", y)):
                if c is not None and not isinstance(c, dict):
                    raise ParityError(
                        f"{path} ({label}): cell {key!r} is not an object"
                    )
            cell = x or y
            if not isinstance(cell, dict):
                raise ParityError(f"{path}: cell {key!r} is empty on both sides")
            parts = key.split("/")
            season, gender, slug = (
                int(cell.get("season") or parts[0]),
                str(cell.get("gender") or parts[1]),
                str(cell.get("programme") or parts[2]),
            )
            conf = self.member_of.get((season, gender, slug))
            unit = self._unit(season, gender, conf) if conf else None
            if unit and unit.result in EXCLUDING_RESULTS:
                r.excluded.append(
                    {
                        "path": f"{path}#{key}",
                        "reason": f"run record says {unit.result}",
                    }
                )
                continue
            xs = (
                {k: v for k, v in (x or {}).items() if k not in VOLATILE_CELL_FIELDS}
                if x
                else None
            )
            ys = (
                {k: v for k, v in (y or {}).items() if k not in VOLATILE_CELL_FIELDS}
                if y
                else None
            )
            vouched = (
                unit is not None
                and unit.result in VOUCHING_RESULTS
                and unit.collected_at is not None
            )
            same_stamp = x and y and x.get("confirmed_at") == y.get("confirmed_at")
            if same_stamp and not vouched and not self.compare_inherited:
                if not same(xs, ys):
                    r.find(
                        Finding(
                            "coverage",
                            path,
                            key,
                            "changed",
                            DISAGREEMENT,
                            "cells differ yet carry the same confirmation time",
                            [slug],
                            None,
                            *_fields(xs, ys),
                        )
                    )
                else:
                    r.unproven.append(
                        {
                            "path": f"{path}#{key}",
                            "reason": "same confirmed_at on both sides and no run record vouches for it",
                        }
                    )
                continue
            if same(xs, ys):
                r.add("coverage", MATCH)
                continue
            w = Window(
                _ts(x["confirmed_at"]) if x and x.get("confirmed_at") else None,
                unit.collected_at
                if vouched and unit
                else (_ts(y["confirmed_at"]) if y and y.get("confirmed_at") else None),
                self.lag,
            )
            kind = "added" if x is None else "removed" if y is None else "changed"
            cls, reason = self._cell_class(xs, ys, (season, gender, slug), w)
            fields, more = (
                _fields(xs, ys) if xs is not None and ys is not None else ([], 0)
            )
            r.find(
                Finding(
                    "coverage", path, key, kind, cls, reason, [slug], None, fields, more
                )
            )

    def _cell_class(
        self, x: dict | None, y: dict | None, prog: tuple[int, str, str], w: Window
    ) -> tuple[str, str]:
        when = w.describe()
        if x is None or y is None:
            return (
                DISAGREEMENT,
                f"cell recorded on the {'actual' if x is None else 'expected'} side only",
            )
        if w.simultaneous:
            return (
                DISAGREEMENT,
                f"differs between collections made at the same time ({when})",
            )
        if x.get("layer") == "roster":
            return DISAGREEMENT, "roster cells do not move with games"
        early, late = (x, y) if w.actual_is_later else (y, x)
        if early.get("state") == "complete" and late.get("state") != "complete":
            return (
                DISAGREEMENT,
                f"later collection lost what the earlier one had: {late.get('state')}, {late.get('reason')!r} ({when})",
            )
        # The only state changes a game can explain: a gap or an empty
        # layer that filled in. Anything else loses or reshapes coverage.
        if early.get("state") != late.get("state") and not (
            early.get("state") in ("empty", "unavailable")
            and late.get("state") == "complete"
        ):
            return (
                DISAGREEMENT,
                f"state differs, {early.get('state')} then {late.get('state')} ({when})",
            )
        games = [d for d in self.game_days.get(prog, ()) if w.played_between(d)]
        if not games:
            return (
                DISAGREEMENT,
                f"cell differs but the team played no game between the collections ({when})",
            )
        for k in set(early) | set(late):
            if k not in ("count", "reason", "state", "skips"):
                if not same(early.get(k), late.get(k)):
                    return DISAGREEMENT, f"cell field {k!r} differs ({when})"

        def is_count(v: Any) -> bool:
            return isinstance(v, int) and not isinstance(v, bool)

        if is_count(early.get("count")) and not is_count(late.get("count")):
            return (
                DISAGREEMENT,
                f"the later cell lost its count, {early['count']} then {late.get('count')!r} ({when})",
            )
        if (
            is_count(early.get("count"))
            and is_count(late.get("count"))
            and late["count"] < early["count"]
        ):
            if x.get("layer") != "schedule":
                return (
                    DISAGREEMENT,
                    f"count went down, {early['count']} then {late['count']} ({when})",
                )
        return TIMING, f"cell moved with games played between the collections ({when})"


def compare(
    expected: Tree,
    actual: Tree,
    *,
    lag_days: int = DEFAULT_LAG_DAYS,
    records: dict[tuple[int, str, str], Unit] | None = None,
    require_complete: bool = False,
    compare_inherited: bool = False,
) -> Result:
    return Comparison(
        expected,
        actual,
        lag_days=lag_days,
        records=records,
        require_complete=require_complete,
        compare_inherited=compare_inherited,
    ).run()


# ---------------------------------------------------------------------------
# The report a person reads


def render_markdown(result: Result, limit: int = 200) -> str:
    j = result.to_json()
    lines: list[str] = []
    verdict = {
        "pass": "PASS",
        "fail": "FAIL",
        "error": "ERROR (the check could not run)",
    }[j["verdict"]]
    lines.append(f"# Data-home parity: {verdict}")
    lines.append("")
    lines.append(f"- Expected: `{result.expected}`")
    lines.append(f"- Actual: `{result.actual}`")
    lines.append(
        f"- Records: {j['totals'][MATCH]} match, {j['totals'][TIMING]} differ by timing, "
        f"**{j['totals'][DISAGREEMENT]} disagree**"
    )
    f = j["files"]
    lines.append(
        f"- Files: {f['compared']} compared ({f['identical']} byte-identical), {f['unproven']} unproven, "
        f"{f['excluded']} excluded by run records, {f['not_compared']} not compared; coverage cells: {j['coverage_cells']['unproven']} unproven, {j['coverage_cells']['excluded']} excluded"
    )
    lines.append(
        f"- Timing window: a game dated up to {result.lag_days} days before the earlier collection may still differ"
    )
    if result.require_complete:
        lines.append(
            f"- Complete coverage required: {'yes, and met' if result.complete else 'yes, and NOT met'}"
        )
    lines.append("")
    if result.errors:
        lines.append("## Could not compare")
        lines.append("")
        lines.extend(f"- {e}" for e in result.errors)
        lines.append("")
    lines.append("## By layer")
    lines.append("")
    lines.append("| Layer | Match | Timing | Disagree |")
    lines.append("|---|---:|---:|---:|")
    for layer, c in j["layers"].items():
        lines.append(f"| {layer} | {c[MATCH]} | {c[TIMING]} | {c[DISAGREEMENT]} |")
    lines.append("")

    def block(title: str, items: list[Finding]) -> None:
        if not items:
            return
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        by_prog: dict[str, list[Finding]] = defaultdict(list)
        for it in items:
            by_prog[", ".join(it.programmes) or "(no programme)"].append(it)
        shown = 0
        for prog in sorted(by_prog):
            if shown >= limit:
                break
            lines.append(f"### {prog}")
            lines.append("")
            for it in sorted(
                by_prog[prog], key=lambda x: (x.date or "", x.layer, x.key)
            ):
                if shown >= limit:
                    break
                shown += 1
                date = f"{it.date} " if it.date else ""
                lines.append(
                    f"- {date}**{it.layer}** `{it.key}` ({it.kind}) in `{it.file}`: {it.reason}"
                )
                for fd in it.fields:
                    lines.append(
                        f"  - `{fd['path']}`: expected `{json.dumps(fd['expected'])}`, actual `{json.dumps(fd['actual'])}`"
                    )
                if it.fields_truncated:
                    lines.append(f"  - ...and {it.fields_truncated} more fields")
            lines.append("")
        if len(items) > shown:
            lines.append(
                f"...and {len(items) - shown} more; the JSON result lists every one."
            )
            lines.append("")

    if result.disagreements:
        lines.append("## What disagrees, by pattern")
        lines.append("")
        lines.append(
            "Each disagreement reduced to its layer, its change and the fields it touches (indexes and player keys folded)."
        )
        lines.append("")
        lines.append("| Records | Layer | Change | Fields |")
        lines.append("|---:|---|---|---|")
        for (layer, kind, pattern), n in _patterns(result.disagreements)[:25]:
            lines.append(f"| {n} | {layer} | {kind} | {pattern} |")
        lines.append("")
    block("Disagreements", result.disagreements)
    block("Timing differences", result.timing)
    if result.unproven:
        lines.append(f"## Unproven ({len(result.unproven)})")
        lines.append("")
        lines.append(
            "Same collection stamp on both sides, and no run record vouches for the actual side, so these "
            "are copies, not evidence. Pass the run's collect-record.json to count them."
        )
        lines.append("")
        lines.extend(_grouped(result.unproven, limit))
        lines.append("")
    if result.excluded:
        lines.append(f"## Excluded by run records ({len(result.excluded)})")
        lines.append("")
        lines.extend(_grouped(result.excluded, limit))
        lines.append("")
    if result.not_compared:
        lines.append("## Not compared")
        lines.append("")
        for n in result.not_compared:
            lines.append(
                f"- `{n['path']}` ({n['count']} file{'s' if n['count'] != 1 else ''}): {n['reason']}"
            )
        lines.append("")
    if result.notes:
        lines.append("## Notes")
        lines.append("")
        lines.extend(f"- {n}" for n in result.notes)
        lines.append("")
    return "\n".join(lines)


def _grouped(items: list[dict[str, str]], limit: int) -> list[str]:
    """One line per file; coverage cells (``path#cell``) counted per file."""
    by_file: dict[tuple[str, str], int] = defaultdict(int)
    for it in items:
        by_file[(it["path"].split("#", 1)[0], it["reason"])] += 1
    out = []
    for (path, reason), n in sorted(by_file.items())[:limit]:
        cells = f" ({n} cells)" if path.endswith("coverage.json") else ""
        out.append(f"- `{path}`{cells}: {reason}")
    if len(by_file) > limit:
        out.append(f"- ...and {len(by_file) - limit} more")
    return out


_INDEX = re.compile(r"\[\d+\]")
_ROW_KEY = re.compile(r"\.(?:player_id|bio_url|source_url|name)=[^.]*")


def _fold(path: str) -> str:
    return _ROW_KEY.sub(".<row>", _INDEX.sub("[]", path))


def _patterns(items: list[Finding]) -> list[tuple[tuple[str, str, str], int]]:
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for it in items:
        if it.fields:
            folded = sorted({_fold(f["path"]) for f in it.fields})
            pattern = ", ".join(f"`{p}`" for p in folded[:4]) + (
                " ..." if len(folded) > 4 or it.fields_truncated else ""
            )
        else:
            pattern = f"`{it.key}`" if it.key.startswith("<") else "(whole record)"
        counts[(it.layer, it.kind, pattern)] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
