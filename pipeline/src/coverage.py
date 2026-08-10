"""The coverage manifest — what this data home holds, and what it does not.

A Touchline data home starts empty and grows one ask at a time.  Without a
record of what landed, every consumer has to guess from directory listings, and
the three states that matter most are indistinguishable from each other:

    not collected yet     ·  nobody has asked for this
    not published yet     ·  we asked, the source has not released it
    no collector exists   ·  we asked, and this can never be served

Conflating those is the fastest way to make a data product untrustworthy, so
they are recorded separately and rendered separately.

The manifest is merged, never overwritten: a run that collects one programme
must not erase the record of the twelve collected last week.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

COVERAGE_SCHEMA = "touchline.coverage/1"
COVERAGE_FILENAME = "coverage.json"

# Cell states, ordered worst to best for reporting.
STATE_NO_COLLECTOR = "no-collector"
STATE_UNAVAILABLE = "unavailable"
STATE_EMPTY = "empty"
STATE_COMPLETE = "complete"


def cell_key(season: int, gender: str, programme: str, layer: str) -> str:
    return f"{season}/{gender}/{programme}/{layer}"


def coverage_path(root: Path) -> Path:
    return root / "data" / COVERAGE_FILENAME


def read_coverage(root: Path) -> dict[str, Any]:
    """Load the manifest, tolerating absence and refusing silent corruption."""
    path = coverage_path(root)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schema": COVERAGE_SCHEMA, "cells": {}}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    cells = payload.get("cells")
    if not isinstance(cells, dict):
        payload["cells"] = {}
    payload.setdefault("schema", COVERAGE_SCHEMA)
    return payload


def merge_cells(
    root: Path,
    cells: dict[str, dict[str, Any]],
    *,
    updated_at: str,
) -> dict[str, Any]:
    """Fold this run's cells into whatever the data home already recorded."""
    manifest = read_coverage(root)
    existing = manifest.get("cells")
    if not isinstance(existing, dict):
        existing = {}
    existing.update(cells)
    manifest["cells"] = existing
    manifest["schema"] = COVERAGE_SCHEMA
    manifest["updated_at"] = updated_at
    return manifest


def write_coverage(root: Path, manifest: dict[str, Any]) -> Path:
    """Write atomically so an interrupted run cannot leave half a manifest."""
    path = coverage_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def summarize(
    manifest: dict[str, Any], season: int, gender: str, layer: str
) -> dict[str, int]:
    """Count cells by state for one (season, gender, layer) slice."""
    prefix = f"{season}/{gender}/"
    suffix = f"/{layer}"
    counts: dict[str, int] = {}
    cells = manifest.get("cells")
    if not isinstance(cells, dict):
        return counts
    for key, cell in cells.items():
        if not key.startswith(prefix) or not key.endswith(suffix):
            continue
        if not isinstance(cell, dict):
            continue
        state = str(cell.get("state") or STATE_UNAVAILABLE)
        counts[state] = counts.get(state, 0) + 1
    return counts
