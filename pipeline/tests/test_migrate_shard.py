"""One-shot migration from legacy season keys to conference shards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate_shard import MigrationError, migrate_home


def _write(root: Path, kind: str, name: str, payload: dict) -> Path:
    path = root / "data" / kind / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _seed_legacy_home(root: Path) -> None:
    _write(
        root,
        "fixtures",
        "2026-men.json",
        {
            "schema": "touchline.fixtures/1",
            "season": 2026,
            "gender": "men",
            "conference": "GAC",
            "collected_at": "2026-08-12T12:00:00Z",
            "programmes": [{"slug": "harding", "name": "Harding"}],
            "fixtures": [],
        },
    )
    for kind, field in (
        ("rosters", "rosters"),
        ("stats", "teams"),
        ("matches", "matches"),
    ):
        _write(
            root,
            kind,
            "2026-men.json",
            {
                "schema": f"touchline.{kind}/1",
                "season": 2026,
                "gender": "men",
                "collected_at": "2026-08-12T12:00:00Z",
                field: {},
            },
        )
    _write(
        root,
        "rosters",
        "2019-men.json",
        {
            "schema": "touchline.rosters/1",
            "season": 2019,
            "gender": "men",
            "collected_at": "2026-08-12T12:00:00Z",
            "rosters": {},
        },
    )


def test_migrates_every_layer_and_is_idempotent(tmp_path: Path) -> None:
    _seed_legacy_home(tmp_path)

    migrated = migrate_home(tmp_path)
    assert len(migrated) == 5
    for kind in ("fixtures", "rosters", "stats", "matches"):
        assert not (tmp_path / "data" / kind / "2026-men.json").exists()
        assert (tmp_path / "data" / kind / "2026-men-gac.json").is_file()
    assert (tmp_path / "data" / "rosters" / "2019-men-gac.json").is_file()

    fixtures_path = tmp_path / "data" / "fixtures" / "2026-men-gac.json"
    fixtures = json.loads(fixtures_path.read_text())
    assert fixtures["schema"] == "touchline.fixtures/2"
    assert fixtures["conference"] == "GAC"
    assert fixtures["programmes"] == [
        {"slug": "harding", "name": "Harding", "conference": "GAC"}
    ]
    roster = json.loads(
        (tmp_path / "data" / "rosters" / "2026-men-gac.json").read_text()
    )
    assert roster["schema"] == "touchline.rosters/1"

    before = {
        path: path.read_bytes()
        for path in sorted((tmp_path / "data").glob("*/*.json"))
    }
    assert migrate_home(tmp_path) == []
    assert {
        path: path.read_bytes()
        for path in sorted((tmp_path / "data").glob("*/*.json"))
    } == before


def test_refuses_a_differing_destination_without_mutating_any_source(
    tmp_path: Path,
) -> None:
    _seed_legacy_home(tmp_path)
    destination = _write(
        tmp_path,
        "fixtures",
        "2026-men-gac.json",
        {"schema": "touchline.fixtures/2", "different": True},
    )

    with pytest.raises(MigrationError, match="refusing to overwrite"):
        migrate_home(tmp_path)

    assert destination.exists()
    assert (tmp_path / "data" / "fixtures" / "2026-men.json").exists()
    assert (tmp_path / "data" / "rosters" / "2026-men.json").exists()


def test_explicit_conference_migrates_a_home_without_fixtures(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "rosters",
        "2019-men.json",
        {
            "schema": "touchline.rosters/1",
            "season": 2019,
            "gender": "men",
            "rosters": {},
        },
    )

    assert migrate_home(tmp_path, conference="Lone Star Conference") == [
        tmp_path / "data" / "rosters" / "2019-men-lone-star-conference.json"
    ]
