"""Migrate legacy season files to conference-sharded storage.

The reader intentionally has no legacy filename fallback. Run this once in a
consumer data home before upgrading the rib; repeating it is safe.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from src import paths
from src.sidearm_live import programme_slug

KINDS = ("fixtures", "rosters", "stats", "matches")
LEGACY_NAME = re.compile(r"^(\d{4})-(men|women)\.json$")
SHARDED_NAME = re.compile(r"^(\d{4})-(men|women)-([a-z0-9-]+)\.json$")


class MigrationError(RuntimeError):
    """The home cannot be migrated without guessing or overwriting data."""


@dataclass(frozen=True)
class Migration:
    source: Path
    destination: Path
    payload: dict[str, object]
    destination_exists: bool


def _read_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MigrationError(f"{path} must contain a JSON object")
    return payload


def _fixture_labels(root: Path) -> dict[tuple[int, str], set[str]]:
    labels: dict[tuple[int, str], set[str]] = {}
    directory = root / "data" / "fixtures"
    if not directory.is_dir():
        return labels
    for path in directory.iterdir():
        legacy = LEGACY_NAME.match(path.name)
        sharded = SHARDED_NAME.match(path.name)
        matched = legacy or sharded
        if matched is None:
            continue
        key = (int(matched.group(1)), matched.group(2))
        if legacy:
            payload = _read_object(path)
            label = str(payload.get("conference") or "").strip()
        else:
            try:
                payload = _read_object(path)
            except MigrationError:
                payload = {}
            label = str(payload.get("conference") or sharded.group(3)).strip()
        if label:
            labels.setdefault(key, set()).add(label)
    return labels


def _resolve_conference(
    *,
    path: Path,
    payload: dict[str, object],
    key: tuple[int, str],
    requested: str | None,
    labels_by_key: dict[tuple[int, str], set[str]],
) -> str:
    own = str(payload.get("conference") or "").strip()
    if own:
        if requested and programme_slug(own) != programme_slug(requested):
            raise MigrationError(
                f"{path} declares conference {own!r}, not requested {requested!r}"
            )
        return own
    if requested:
        return requested

    candidates = labels_by_key.get(key, set())
    if len(candidates) == 1:
        return next(iter(candidates))
    if len(candidates) > 1:
        raise MigrationError(
            f"{path} has no conference and {key[0]} {key[1]} has multiple shards; "
            "pass --conference explicitly"
        )

    all_labels = {label for labels in labels_by_key.values() for label in labels}
    if len(all_labels) == 1:
        return next(iter(all_labels))
    raise MigrationError(
        f"{path} has no conference to derive its shard; pass --conference explicitly"
    )


def _transform(
    path: Path,
    kind: str,
    season: int,
    gender: str,
    conference: str,
    payload: dict[str, object],
) -> dict[str, object]:
    migrated = deepcopy(payload)
    if "season" in migrated and migrated["season"] != season:
        raise MigrationError(
            f"{path} names season {migrated['season']!r}, but its filename names {season}"
        )
    if "gender" in migrated and migrated["gender"] != gender:
        raise MigrationError(
            f"{path} names gender {migrated['gender']!r}, but its filename names {gender}"
        )

    if kind == "fixtures":
        schema = migrated.get("schema")
        if schema not in {"touchline.fixtures/1", "touchline.fixtures/2"}:
            raise MigrationError(f"{path} has unsupported fixtures schema {schema!r}")
        programmes = migrated.get("programmes")
        if not isinstance(programmes, list):
            raise MigrationError(f"{path} has no programmes array")
        for programme in programmes:
            if not isinstance(programme, dict):
                raise MigrationError(f"{path} has a non-object programme entry")
            programme.setdefault("conference", conference)
        migrated["schema"] = "touchline.fixtures/2"
        migrated["conference"] = conference
    return migrated


def plan_migration(root: Path, *, conference: str | None = None) -> list[Migration]:
    """Preflight every legacy file before returning any filesystem mutations."""
    if conference is not None and not programme_slug(conference):
        raise MigrationError("conference must contain at least one letter or number")

    sources: list[tuple[str, Path, int, str, dict[str, object]]] = []
    for kind in KINDS:
        directory = root / "data" / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            matched = LEGACY_NAME.match(path.name)
            if matched is None:
                continue
            sources.append(
                (
                    kind,
                    path,
                    int(matched.group(1)),
                    matched.group(2),
                    _read_object(path),
                )
            )
    if not sources:
        return []

    labels_by_key = _fixture_labels(root)
    migrations: list[Migration] = []
    for kind, source, season, gender, payload in sources:
        label = _resolve_conference(
            path=source,
            payload=payload,
            key=(season, gender),
            requested=conference,
            labels_by_key=labels_by_key,
        )
        slug = programme_slug(label)
        if not slug:
            raise MigrationError(f"{source} has an invalid conference {label!r}")
        migrated = _transform(source, kind, season, gender, label, payload)
        destination = source.with_name(f"{season}-{gender}-{slug}.json")
        exists = destination.exists()
        if exists and _read_object(destination) != migrated:
            raise MigrationError(
                f"refusing to overwrite differing destination {destination}"
            )
        migrations.append(
            Migration(
                source=source,
                destination=destination,
                payload=migrated,
                destination_exists=exists,
            )
        )
    return migrations


def migrate_home(root: Path, *, conference: str | None = None) -> list[Path]:
    """Apply a fully preflighted migration and return the shard paths touched."""
    migrations = plan_migration(root, conference=conference)
    migrated: list[Path] = []
    for item in migrations:
        if not item.destination_exists:
            temporary = item.destination.with_name(
                f".{item.destination.name}.{os.getpid()}.tmp"
            )
            temporary.write_text(
                json.dumps(item.payload, indent=2) + "\n", encoding="utf-8"
            )
            temporary.replace(item.destination)
        item.source.unlink()
        migrated.append(item.destination)
    return migrated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy season JSON files to conference-sharded names."
    )
    parser.add_argument(
        "--conference",
        help=(
            "Conference label for layers that do not carry one. Optional when the "
            "home's fixture shards establish exactly one conference."
        ),
    )
    args = parser.parse_args()
    root = paths.data_root()
    try:
        migrated = migrate_home(root, conference=args.conference)
    except MigrationError as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 1
    if migrated:
        print(f"migrated {len(migrated)} season file(s)")
        for path in migrated:
            print(path)
    else:
        print("no legacy season files found; data home is already migrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
