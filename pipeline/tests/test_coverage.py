"""Tests for the coverage manifest — the record of what a data home holds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import coverage


def test_absent_manifest_reads_as_empty_rather_than_raising(tmp_path: Path) -> None:
    assert coverage.read_coverage(tmp_path) == {
        "schema": coverage.COVERAGE_SCHEMA,
        "cells": {},
    }


def test_a_later_run_does_not_erase_an_earlier_run(tmp_path: Path) -> None:
    """The accretion guarantee.

    A data home starts empty and grows one ask at a time.  A run that collects
    one programme must not erase the twelve collected last week.
    """
    first = coverage.merge_cells(
        tmp_path,
        {
            coverage.cell_key(2026, "men", "harding", "roster"): {
                "state": coverage.STATE_COMPLETE,
                "count": 30,
            }
        },
        updated_at="2026-08-09T06:00:00+00:00",
    )
    coverage.write_coverage(tmp_path, first)

    second = coverage.merge_cells(
        tmp_path,
        {
            coverage.cell_key(2019, "men", "harding", "roster"): {
                "state": coverage.STATE_COMPLETE,
                "count": 26,
            }
        },
        updated_at="2026-08-09T07:00:00+00:00",
    )
    coverage.write_coverage(tmp_path, second)

    stored = coverage.read_coverage(tmp_path)
    assert set(stored["cells"]) == {
        "2026/men/harding/roster",
        "2019/men/harding/roster",
    }
    assert stored["updated_at"] == "2026-08-09T07:00:00+00:00"


def test_recollecting_the_same_cell_replaces_it(tmp_path: Path) -> None:
    key = coverage.cell_key(2026, "men", "harding", "roster")
    coverage.write_coverage(
        tmp_path,
        coverage.merge_cells(
            tmp_path,
            {key: {"state": coverage.STATE_EMPTY, "count": 0}},
            updated_at="t1",
        ),
    )
    coverage.write_coverage(
        tmp_path,
        coverage.merge_cells(
            tmp_path,
            {key: {"state": coverage.STATE_COMPLETE, "count": 30}},
            updated_at="t2",
        ),
    )
    stored = coverage.read_coverage(tmp_path)
    assert stored["cells"][key] == {"state": coverage.STATE_COMPLETE, "count": 30}


def test_corrupt_manifest_is_reported_not_silently_replaced(tmp_path: Path) -> None:
    path = coverage.coverage_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a JSON object"):
        coverage.read_coverage(tmp_path)


def test_summarize_counts_one_slice_by_state(tmp_path: Path) -> None:
    manifest = {
        "cells": {
            "2026/men/harding/roster": {"state": coverage.STATE_COMPLETE},
            "2026/men/newman/roster": {"state": coverage.STATE_EMPTY},
            "2026/men/northeastern-state/roster": {
                "state": coverage.STATE_NO_COLLECTOR
            },
            "2026/men/harding/schedule": {"state": coverage.STATE_COMPLETE},
            "2026/women/harding/roster": {"state": coverage.STATE_COMPLETE},
        }
    }
    assert coverage.summarize(manifest, 2026, "men", "roster") == {
        coverage.STATE_COMPLETE: 1,
        coverage.STATE_EMPTY: 1,
        coverage.STATE_NO_COLLECTOR: 1,
    }


def test_written_manifest_is_valid_json_with_stable_ordering(tmp_path: Path) -> None:
    manifest = coverage.merge_cells(
        tmp_path,
        {
            coverage.cell_key(2026, "men", "zeta", "roster"): {"state": "complete"},
            coverage.cell_key(2026, "men", "alpha", "roster"): {"state": "complete"},
        },
        updated_at="t",
    )
    path = coverage.write_coverage(tmp_path, manifest)
    text = path.read_text(encoding="utf-8")
    assert json.loads(text)["cells"]
    assert text.index('"2026/men/alpha/roster"') < text.index('"2026/men/zeta/roster"')
