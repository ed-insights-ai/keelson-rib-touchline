"""The cloud trial reduces coverage cells to failure classes, never data."""

from scripts.cloud_trial import (
    CellOutcome,
    GroupRun,
    _probe_class,
    classify_reason,
    is_block,
    render,
    verdict,
)


def test_classify_reason_names_blocks_and_flaky_minutes_apart():
    assert classify_reason("complete", "") == "ok"
    assert classify_reason("empty", "") == "ok"
    assert classify_reason("no-collector", "anything") == "no-collector"
    assert (
        classify_reason("unavailable", "x: 403 Client Error: Forbidden") == "http-403"
    )
    assert (
        classify_reason("unavailable", "served a challenge, not the page")
        == "challenge"
    )
    assert (
        classify_reason("unavailable", "host h is cooling down after HTTP 202")
        == "challenge"
    )
    assert (
        classify_reason("unavailable", "Read timed out. (read timeout=30)") == "timeout"
    )
    assert classify_reason("unavailable", "Max retries exceeded") == "connect"
    assert classify_reason("unavailable", "page did not prove its season") == "unproven"
    assert (
        classify_reason(
            "unavailable", "[2026] no proven schedule to take box-score links from"
        )
        == "follows-schedule"
    )


def test_probe_values_map_to_the_same_classes():
    assert _probe_class("present") == "ok"
    assert _probe_class("absent") == "ok"
    assert _probe_class("error (HTTP 403)") == "http-403"
    assert _probe_class("error (timeout)") == "timeout"
    assert _probe_class("error (connection failed)") == "connect"
    assert _probe_class("error (season not proven)") == "unproven"


def test_blocks_are_refusals_not_outages():
    assert is_block("http-403") and is_block("challenge") and is_block("http-202")
    assert is_block("http-405")
    assert not is_block("http-404") and not is_block("timeout") and not is_block("ok")


def _cell(platform, cls):
    return CellOutcome(platform, "G", "p", "schedule", "x", cls, "h")


def test_verdict_and_report_carry_only_states():
    cells = [
        _cell("sidearm", "ok"),
        _cell("prestosports", "ok"),
        _cell("prestosports", "challenge"),
        _cell("wmt", "http-403"),
        _cell("statcrew", "timeout"),
    ]
    runs = [GroupRun("sidearm", "G", 0, 1.0)]
    assert verdict(cells, runs, "sidearm") == "PASS"
    assert verdict(cells, runs, "prestosports") == "PARTLY BLOCKED"
    assert verdict(cells, runs, "wmt") == "BLOCKED"
    assert verdict(cells, runs, "statcrew") == "DEGRADED"
    assert verdict(cells, runs, "d3-probe") == "not tested"
    text, result = render(2026, runs, cells, 3.0)
    assert result["platforms"]["prestosports"] == {
        "verdict": "PARTLY BLOCKED",
        "ok": 1,
        "failed": {"challenge": 1},
    }
    assert "| wmt | BLOCKED |" in text


def test_probe_refuses_a_served_non_page_as_a_challenge():
    assert _probe_class("error (HTTP 200)") == "challenge"
    assert _probe_class("error (HTTP 202)") == "challenge"


def test_an_interrupted_group_never_passes():
    cells = [_cell("wmt", "ok")]
    assert verdict(cells, [GroupRun("wmt", "G", 124, 1.0)], "wmt") == "DEGRADED"
    assert verdict(cells, [GroupRun("wmt", "G", 0, 1.0)], "wmt") == "PASS"


def test_failed_box_scores_count_by_class_and_host_without_fixture_ids(tmp_path):
    import json

    from scripts.cloud_trial import _box_score_failures

    matches = tmp_path / "data" / "matches"
    matches.mkdir(parents=True)
    (matches / "2026-men-sac.json").write_text(
        json.dumps(
            {
                "matches": {},
                "missing": {
                    "fx-1": "[2026] fx-1: failed to fetch box score "
                    "https://a.example/b: 403 Client Error: Forbidden",
                    "fx-2": "[2026] fx-2: served a challenge, not the page",
                },
            }
        )
    )
    outcomes = _box_score_failures(tmp_path, "prestosports", "SAC men")
    assert sorted(o.cls for o in outcomes) == ["challenge", "http-403"]
    assert {o.host for o in outcomes} == {"a.example", ""}
    assert all("fx-" not in o.programme for o in outcomes)
    runs = [GroupRun("prestosports", "SAC men", 0, 1.0)]
    cells = [_cell("prestosports", "ok"), *outcomes]
    assert verdict(cells, runs, "prestosports") == "PARTLY BLOCKED"


def test_unsupported_coverage_blocks_pass_but_downstream_skips_do_not():
    runs = [GroupRun("wmt", "G", 0, 1.0)]
    assert (
        verdict([_cell("wmt", "ok"), _cell("wmt", "no-collector")], runs, "wmt")
        == "DEGRADED"
    )
    assert (
        verdict([_cell("wmt", "ok"), _cell("wmt", "follows-schedule")], runs, "wmt")
        == "PASS"
    )
    text, _ = render(
        2026, runs, [_cell("wmt", "ok"), _cell("wmt", "no-collector")], 1.0
    )
    assert "no-collector" in text


def test_unpublished_box_scores_are_not_failed_fetches(tmp_path):
    import json

    from scripts.cloud_trial import _box_score_failures

    matches = tmp_path / "data" / "matches"
    matches.mkdir(parents=True)
    (matches / "2026-men-sac.json").write_text(
        json.dumps(
            {"missing": {"fx-1": "no box-score link on any collected schedule page"}}
        )
    )
    assert _box_score_failures(tmp_path, "sidearm", "G") == []
