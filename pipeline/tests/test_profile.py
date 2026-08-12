"""Profiles: deterministic record recomputed each build, findings additive."""

from __future__ import annotations

import json

from src.profile import assemble_record, player_key, profile_path, upsert_profile
from tests.test_digest import seed_home


def test_player_key_folds_like_the_name_join():
    assert player_key("José Núñez") == "jose-nunez"
    assert player_key("Smith, Jordan") == "jordan-smith"


def test_assemble_record_gathers_identity_career_and_appearances(tmp_path):
    seed_home(tmp_path)
    record = assemble_record(
        tmp_path,
        programme="alpha",
        gender="men",
        conference="TESTCONF",
        player="Star",
    )
    # Identity from the most recent roster listing him (2026).
    assert record["identity"]["name"] == "Star"
    assert record["identity"]["roster_season"] == 2026
    # One career line, from the 2025 statistics page.
    assert [line["season"] for line in record["career"]] == [2025]
    assert record["career"][0]["goals"] == 2
    # No per-match row for him in the seeded box score — appearances empty,
    # but the record still stands on identity + career.
    assert record["appearances"] == []
    assert record["seasons_searched"] == [2025, 2026]


def test_assemble_record_matches_multi_word_names(tmp_path):
    """Regression: the join key is the normalized name, not the file slug —
    a hyphenated key silently missed every multi-word player."""
    seed_home(tmp_path)
    path = tmp_path / "data" / "rosters" / "2026-men-testconf.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rosters"]["alpha"]["players"].append({"name": "Two Words"})
    path.write_text(json.dumps(payload), encoding="utf-8")
    record = assemble_record(
        tmp_path,
        programme="alpha",
        gender="men",
        conference="TESTCONF",
        player="Two Words",
    )
    assert record["identity"]["roster_season"] == 2026


def test_assemble_record_refuses_a_ghost(tmp_path):
    seed_home(tmp_path)
    try:
        assemble_record(
            tmp_path,
            programme="alpha",
            gender="men",
            conference="TESTCONF",
            player="Nobody Real",
        )
    except ValueError as exc:
        assert "no trace" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown player")


def test_upsert_merges_findings_additively_and_refreshes_record(tmp_path):
    seed_home(tmp_path)
    first = {
        "schema": "touchline.player-findings/1",
        "findings": [
            {"type": "summer-league", "text": "On Club X squad", "url": "https://x", "confidence": "high"}
        ],
        "attested_uncaptured": ["all-team honor, no link yet"],
        "unswept": ["Club Y (roster 403)"],
    }
    findings_path = tmp_path / "f1.json"
    findings_path.write_text(json.dumps(first), encoding="utf-8")
    path = upsert_profile(
        tmp_path,
        programme="alpha",
        gender="men",
        conference="TESTCONF",
        player="Star",
        generated_at="2026-08-10T00:00:00+00:00",
        findings_file=findings_path,
    )
    assert path == profile_path(tmp_path, "men", "alpha", "Star")

    # Second run: same finding again (dedupe) plus a new one; record refreshed.
    second = {
        "schema": "touchline.player-findings/1",
        "findings": [
            {"type": "summer-league", "text": "On Club X squad", "url": "https://x", "confidence": "high"},
            {"type": "honor", "text": "Team of the Season", "url": "https://y", "confidence": "medium"},
        ],
    }
    findings_path.write_text(json.dumps(second), encoding="utf-8")
    upsert_profile(
        tmp_path,
        programme="alpha",
        gender="men",
        conference="TESTCONF",
        player="Star",
        generated_at="2026-08-11T00:00:00+00:00",
        findings_file=findings_path,
    )
    profile = json.loads(path.read_text(encoding="utf-8"))
    assert profile["schema"] == "touchline.player-profile/1"
    assert [f["text"] for f in profile["findings"]] == [
        "On Club X squad",
        "Team of the Season",
    ]
    assert profile["attested_uncaptured"] == ["all-team honor, no link yet"]
    assert profile["first_built"] == "2026-08-10T00:00:00+00:00"
    assert profile["updated_at"] == "2026-08-11T00:00:00+00:00"


def test_upsert_without_findings_is_a_pure_record_refresh(tmp_path):
    seed_home(tmp_path)
    path = upsert_profile(
        tmp_path,
        programme="alpha",
        gender="men",
        conference="TESTCONF",
        player="Star",
        generated_at="2026-08-10T00:00:00+00:00",
    )
    profile = json.loads(path.read_text(encoding="utf-8"))
    assert profile["findings"] == []
    assert profile["career"][0]["season"] == 2025
