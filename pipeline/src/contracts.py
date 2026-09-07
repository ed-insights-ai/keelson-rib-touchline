"""Contract fixtures: the shapes this rib promises to write.

Every durable file the rib publishes is read by a strict schema somewhere
else (touchline-ui refuses an unknown field or value outright).  Until now
nothing stood between the writer here and that reader: the conditional
fetch started stamping ``verified: "unchanged"`` on coverage cells and the
site's build refused the whole manifest.

``contracts/`` at the package root holds one fixture per schema, a small
real document exercising every field and every enumerated value the writer
can emit.  The site reads the same files in its schema tests.  On this side
the rule is enforced by *shape facts*: a document is reduced to the set of
(path, kind) leaves it contains, with enumerated fields contributing their
values too, and writer output must not produce a fact its fixture lacks.
A writer change that adds a field or a value without touching the fixture
fails here, in CI, rather than on the published build.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import paths

CONTRACTS_DIRNAME = "contracts"

#: A record's keys are data (a slug, a fixture id, a cell key), so the walk
#: replaces them with this token; a list's items get the array token.
KEY = "*"
ITEM = "[]"

FactPath = tuple[str, ...]
Fact = tuple[FactPath, str]


@dataclass(frozen=True)
class Contract:
    """One published schema: where its fixture lives and how to read it."""

    name: str
    filename: str
    schema: str | None
    #: Paths whose dict keys are data rather than field names.
    records: frozenset[FactPath] = frozenset()
    #: Paths whose string values form a closed set the reader enumerates.
    enums: frozenset[FactPath] = frozenset()

    def path(self) -> Path:
        return contracts_dir() / self.filename

    def fixture(self) -> Any:
        return json.loads(self.path().read_text(encoding="utf-8"))


def contracts_dir() -> Path:
    return paths.package_root() / CONTRACTS_DIRNAME


COVERAGE = Contract(
    name="coverage",
    filename="coverage-1.json",
    schema="touchline.coverage/1",
    records=frozenset({("cells",)}),
    enums=frozenset(
        {
            ("cells", KEY, "layer"),
            ("cells", KEY, "state"),
            ("cells", KEY, "verified"),
            ("cells", KEY, "collector"),
        }
    ),
)

FIXTURES = Contract(
    name="fixtures",
    filename="fixtures-2.json",
    schema="touchline.fixtures/2",
    enums=frozenset(
        {
            ("gender",),
            ("conference_game_source",),
            ("fixtures", ITEM, "status"),
            ("fixtures", ITEM, "match_type"),
            ("fixtures", ITEM, "forfeit"),
            ("fixtures", ITEM, "conference_game_source"),
        }
    ),
)

ROSTERS = Contract(
    name="rosters",
    filename="rosters-1.json",
    schema="touchline.rosters/1",
    records=frozenset({("rosters",)}),
    enums=frozenset({("gender",)}),
)

STATS = Contract(
    name="stats",
    filename="stats-1.json",
    schema="touchline.stats/1",
    records=frozenset({("teams",)}),
    enums=frozenset({("gender",)}),
)

MATCHES = Contract(
    name="matches",
    filename="matches-2.json",
    schema="touchline.matches/2",
    records=frozenset({("matches",), ("missing",)}),
    enums=frozenset(
        {
            ("gender",),
            ("matches", KEY, "cards", ITEM, "type"),
            ("matches", KEY, "plays", ITEM, "type"),
            ("matches", KEY, "plays", ITEM, "period"),
            ("matches", KEY, "teams", ITEM, "players", ITEM, "player_ref", "source"),
            ("matches", KEY, "teams", ITEM, "keepers", ITEM, "player_ref", "source"),
        }
    ),
)

MEMBERSHIP = Contract(
    name="membership",
    filename="membership.json",
    schema=None,
    records=frozenset(
        {
            ("memberships",),
            ("memberships", KEY),
            ("standings_archives",),
            ("standings_archives", KEY, "seasons"),
        }
    ),
    enums=frozenset(),
)

PROGRAMMES = Contract(
    name="programmes",
    filename="programmes-2.json",
    schema="touchline.programmes/2",
    records=frozenset({("programmes",)}),
    enums=frozenset(),
)

CONTRACTS: tuple[Contract, ...] = (
    COVERAGE,
    FIXTURES,
    ROSTERS,
    STATS,
    MATCHES,
    MEMBERSHIP,
    PROGRAMMES,
)


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def facts(document: Any, contract: Contract) -> set[Fact]:
    """Reduce a document to the set of shape facts it exhibits."""
    found: set[Fact] = set()

    def walk(value: Any, path: FactPath) -> None:
        kind = _kind(value)
        found.add((path, kind))
        if kind == "object":
            if path in contract.records:
                for child in value.values():
                    walk(child, (*path, KEY))
            else:
                for key, child in value.items():
                    walk(child, (*path, key))
        elif kind == "array":
            for child in value:
                walk(child, (*path, ITEM))
        elif kind == "string" and path in contract.enums:
            found.add((path, f"value:{value}"))

    walk(document, ())
    return found


def drift(document: Any, contract: Contract) -> set[Fact]:
    """Facts the document exhibits that its contract fixture does not.

    Empty means the document is within the contract.  Anything else is a
    field, a type, or an enumerated value the fixture has never promised,
    and the fixture (and the site's schema) must move before the writer.
    """
    return facts(document, contract) - facts(contract.fixture(), contract)


def values(document: Any, contract: Contract, path: FactPath) -> set[str]:
    """Every value an enumerated field takes in a document."""
    prefix = "value:"
    return {
        kind[len(prefix) :]
        for fact_path, kind in facts(document, contract)
        if fact_path == path and kind.startswith(prefix)
    }


def describe(found: set[Fact]) -> str:
    """Render drift for an assertion message, one fact per line."""
    return "\n".join(
        f"  {'/'.join(path) or '<root>'}: {kind}" for path, kind in sorted(found)
    )
