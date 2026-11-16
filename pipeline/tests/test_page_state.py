"""Conditional fetch: an unchanged page skips the parse and the write.

The politeness contract under test: a steady-state daily collect should be
mostly cheap validation requests.  Tier one is HTTP — stored validators go
out as ``If-None-Match``/``If-Modified-Since`` and a 304 ends the question
with no body.  Tier two is the content signature for servers that answer 200
regardless: content unchanged under render noise still skips the parse and
the write.  Either way
the skip must be legible (outcome marked unchanged, coverage able to say
verified-unchanged) and must never outlive its inputs — a changed page, or a
changed parser/identity configuration, reads the bytes again.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import sidearm_live
from src.config import SchoolConfig
from src.page_state import BoxArchive, PageStateStore, box_kind, content_signature
from src.sidearm_live import (
    LAYER_ROSTER,
    LAYER_SCHEDULE,
    LayerOutcome,
    ProgrammeCollection,
    collect_programme,
    conference_header_signature,
    parse_fingerprint,
    write_raw_pages,
)

_LAST_MODIFIED = "Mon, 31 Aug 2026 12:38:14 GMT"
_ALIASES = {"southern nazarene": "southern-nazarene"}


def _school() -> SchoolConfig:
    return SchoolConfig(
        name="Harding",
        abbreviation="HU",
        conference="GAC",
        prefix="hu",
        base_url="https://static.example.test/{year}/{prefix}-{num:02d}.htm",
        gender="men",
        live_base_url="https://example.test/sports/mens-soccer",
    )


def _schedule_html(opponent: str = "Southern Nazarene") -> str:
    component = {
        "type": "events",
        "data": [
            {
                "id": 42,
                "date": "2026-09-17T19:00:00",
                "location_indicator": "A",
                "is_conference": True,
                "type": "upcoming",
                "schedule": {"title": "2026 Men's Soccer Schedule"},
                "opponent": {"title": opponent},
                "result": {"team_score": None, "opponent_score": None},
            }
        ],
    }
    return (
        "<html><head><title>2026 Men's Soccer Schedule - Example</title></head>"
        f"<body><script>\nvar obj = {json.dumps(component)};\n</script></body></html>"
    )


def _response(
    *,
    status: int = 200,
    url: str = "https://example.test/sports/mens-soccer/schedule/2026",
    text: str = "",
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status,
        url=url,
        text=text,
        headers=headers or {},
        raise_for_status=lambda: None,
    )


def _counting_parse(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Count real schedule parses without changing what they produce."""
    calls: list[object] = []
    original = sidearm_live.parse_schedule_page

    def wrapped(html: str, **kwargs: object):
        calls.append(html)
        return original(html, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sidearm_live, "parse_schedule_page", wrapped)
    return calls


def _first_collect(
    store: PageStateStore, tmp_path: Path, headers: dict[str, str] | None
) -> ProgrammeCollection:
    session = MagicMock()
    session.get.return_value = _response(text=_schedule_html(), headers=headers)
    result = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )
    write_raw_pages(tmp_path, result, 2026, "men")
    return result


def test_content_signature_survives_render_noise() -> None:
    # Measured 2026-08-31 on fhsuathletics.com: a re-render changes exactly
    # three shapes over identical content — component instance UUIDs, the
    # urlArgs ticks, and a randomized ad-blocker class prefix.  The signature
    # must see through all three, and still see a real change.
    def render(uuid: str, ticks: str, nonce: str) -> str:
        return (
            f"<script>window.urlArgs = '{ticks}';</script>"
            f"<navigation-component params=\"{{ id: '{uuid}' }}\">"
            f'<div class="{nonce}-modal__title">Ad Blocker Detected</div>'
            '<li class="sidearm-schedule-game" data-game-id="42">W, 2-1</li>'
        )

    first = render(
        "5ffe13e2-b5b8-4ed2-b544-9351196ce1a2", "639027634940434393", "bmtxykf1w"
    )
    second = render(
        "195840df-885b-4541-85e8-946386873c12", "639027643308813835", "bilooxr41"
    )
    assert content_signature(first) == content_signature(second)
    assert content_signature(first.replace("W, 2-1", "W, 3-1")) != content_signature(
        first
    )


def test_first_collect_seeds_validators_and_the_cached_parse(tmp_path: Path) -> None:
    store = PageStateStore(tmp_path, 2026, "men")
    result = _first_collect(
        store, tmp_path, {"ETag": '"abc"', "Last-Modified": _LAST_MODIFIED}
    )

    assert result.state(LAYER_SCHEDULE) == "complete"
    assert result.outcomes[LAYER_SCHEDULE].unchanged is False
    sidecar = json.loads(
        store.state_path("harding", LAYER_SCHEDULE).read_text(encoding="utf-8")
    )
    assert sidecar["etag"] == '"abc"'
    assert sidecar["last_modified"] == _LAST_MODIFIED
    assert sidecar["signature"] == content_signature(_schedule_html())
    assert len(sidecar["parsed"]["fixtures"]) == 1
    assert store.html_path("harding", LAYER_SCHEDULE).is_file()


def test_a_304_skips_the_parse_and_reuses_the_cached_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PageStateStore(tmp_path, 2026, "men")
    first = _first_collect(
        store, tmp_path, {"ETag": '"abc"', "Last-Modified": _LAST_MODIFIED}
    )

    parses = _counting_parse(monkeypatch)
    session = MagicMock()
    session.get.return_value = _response(status=304, text="")
    second = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )

    sent = session.get.call_args.kwargs["headers"]
    assert sent["If-None-Match"] == '"abc"'
    assert sent["If-Modified-Since"] == _LAST_MODIFIED
    assert parses == []
    assert second.fixtures == first.fixtures
    assert second.state(LAYER_SCHEDULE) == "complete"
    assert second.outcomes[LAYER_SCHEDULE].unchanged is True
    # The archived page came back off disk for downstream link extraction.
    assert second.schedule_html == _schedule_html()


def test_identical_bytes_without_validators_still_skip_the_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The server offered no ETag or Last-Modified, so the request cannot be
    # conditional — but the body it re-serves is byte-identical, and the
    # content signature catches that.
    store = PageStateStore(tmp_path, 2026, "men")
    first = _first_collect(store, tmp_path, headers=None)

    parses = _counting_parse(monkeypatch)
    session = MagicMock()
    session.get.return_value = _response(text=_schedule_html())
    second = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )

    assert session.get.call_args.kwargs["headers"] is None
    assert parses == []
    assert second.fixtures == first.fixtures
    assert second.outcomes[LAYER_SCHEDULE].unchanged is True


def test_a_changed_page_is_reparsed_and_its_sidecar_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PageStateStore(tmp_path, 2026, "men")
    _first_collect(store, tmp_path, {"Last-Modified": _LAST_MODIFIED})

    changed = _schedule_html(opponent="Oklahoma Baptist")
    parses = _counting_parse(monkeypatch)
    session = MagicMock()
    session.get.return_value = _response(text=changed)
    second = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )
    write_raw_pages(tmp_path, second, 2026, "men")

    assert len(parses) == 1
    assert second.outcomes[LAYER_SCHEDULE].unchanged is False
    assert second.fixtures[0]["home"] == "oklahoma-baptist"
    sidecar = json.loads(
        store.state_path("harding", LAYER_SCHEDULE).read_text(encoding="utf-8")
    )
    assert sidecar["signature"] == content_signature(changed)
    # The archive now holds the changed bytes.
    assert (
        store.html_path("harding", LAYER_SCHEDULE).read_text(encoding="utf-8")
        == changed
    )


def test_a_stale_fingerprint_reparses_the_archive_without_a_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The page is unchanged but the parse that read it is not (a parser fix,
    # a schools.toml edit).  The 304 still spares the transfer; the archived
    # bytes are simply read again and the sidecar catches up.
    store = PageStateStore(tmp_path, 2026, "men")
    _first_collect(store, tmp_path, {"ETag": '"abc"'})
    path = store.state_path("harding", LAYER_SCHEDULE)
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    sidecar["fingerprint"] = "stale"
    path.write_text(json.dumps(sidecar), encoding="utf-8")

    parses = _counting_parse(monkeypatch)
    session = MagicMock()
    session.get.return_value = _response(status=304, text="")
    second = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )

    assert len(parses) == 1
    assert parses[0] == _schedule_html()
    assert second.outcomes[LAYER_SCHEDULE].unchanged is True
    assert len(second.fixtures) == 1
    refreshed = json.loads(path.read_text(encoding="utf-8"))
    assert refreshed["fingerprint"] == parse_fingerprint(
        2026, _ALIASES, None, conference_header_signature()
    )
    assert len(refreshed["parsed"]["fixtures"]) == 1


def test_a_sidecar_without_its_archived_page_validates_nothing(
    tmp_path: Path,
) -> None:
    store = PageStateStore(tmp_path, 2026, "men")
    _first_collect(store, tmp_path, {"ETag": '"abc"'})
    store.html_path("harding", LAYER_SCHEDULE).unlink()

    fingerprint = parse_fingerprint(2026, _ALIASES, None, conference_header_signature())
    assert store.load("harding", LAYER_SCHEDULE, fingerprint) is None

    # And with nothing to validate against, the next collect is a full,
    # unconditional fetch that reseeds both files.
    session = MagicMock()
    session.get.return_value = _response(
        text=_schedule_html(), headers={"ETag": '"abc"'}
    )
    result = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )
    assert session.get.call_args.kwargs["headers"] is None
    assert result.outcomes[LAYER_SCHEDULE].unchanged is False
    assert len(result.fixtures) == 1


def test_a_refused_page_that_reaches_the_archive_invalidates_its_sidecar(
    tmp_path: Path,
) -> None:
    # A page that proves its season but publishes no schedule shape at all is
    # refused AFTER its bytes were kept for archiving, so the next
    # write_raw_pages overwrites the good bytes — a sidecar describing the
    # previous page would then lie about what sits beside it.
    store = PageStateStore(tmp_path, 2026, "men")
    _first_collect(store, tmp_path, {"ETag": '"abc"'})

    session = MagicMock()
    session.get.return_value = _response(
        text=(
            "<html><head><title>2026 Men's Soccer Schedule - Example</title>"
            "</head><body></body></html>"
        )
    )
    result = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )

    assert result.state(LAYER_SCHEDULE) == "unavailable"
    assert "no schedule payload" in (result.outcomes[LAYER_SCHEDULE].reason or "")
    assert not store.state_path("harding", LAYER_SCHEDULE).exists()


def test_a_refusal_before_the_archive_keeps_the_sidecar(tmp_path: Path) -> None:
    # A wrong-season redirect is refused inside the fetch, before any bytes
    # are kept — the archive still holds the last good page, so the sidecar
    # describing it stays valid and the next run can still revalidate.
    store = PageStateStore(tmp_path, 2026, "men")
    _first_collect(store, tmp_path, {"ETag": '"abc"'})

    session = MagicMock()
    session.get.return_value = _response(
        text="<title>2025 Men's Soccer Schedule - Example</title>"
    )
    result = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )

    assert result.state(LAYER_SCHEDULE) == "unavailable"
    assert result.schedule_html == ""
    assert store.state_path("harding", LAYER_SCHEDULE).exists()


def test_write_raw_pages_skips_layers_verified_unchanged(tmp_path: Path) -> None:
    result = ProgrammeCollection(
        slug="harding",
        name="Harding",
        fixtures=[],
        players=[],
        outcomes={
            LAYER_SCHEDULE: LayerOutcome(
                LAYER_SCHEDULE, "complete", count=1, unchanged=True
            ),
            LAYER_ROSTER: LayerOutcome(LAYER_ROSTER, "complete", count=1),
        },
        schedule_html="<html>unchanged schedule</html>",
        roster_html="<html>fresh roster</html>",
    )
    write_raw_pages(tmp_path, result, 2026, "men")
    directory = tmp_path / "data" / "raw_html" / "harding"
    assert not (directory / "2026-men-schedule.html").exists()
    assert (directory / "2026-men-roster.html").read_text(
        encoding="utf-8"
    ) == "<html>fresh roster</html>"


def test_a_304_reuses_the_cached_skips_with_the_cached_fixtures(
    tmp_path: Path,
) -> None:
    """A named skip is part of the parse, so it rides the sidecar and comes
    back with the reused fixtures rather than vanishing on an unchanged page."""
    store = PageStateStore(tmp_path, 2026, "men")
    hosted = _schedule_html().replace(
        '"title": "Southern Nazarene"', '"title": "Southern Nazarene vs Maryville"'
    )
    session = MagicMock()
    session.get.return_value = _response(text=hosted, headers={"ETag": '"h"'})
    first = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )
    write_raw_pages(tmp_path, first, 2026, "men")
    expected = (
        "hosted other-match skipped: 2026-09-17, Southern Nazarene v Maryville",
    )
    assert first.fixtures == []
    assert first.outcomes[LAYER_SCHEDULE].skips == expected
    sidecar = json.loads(
        store.state_path("harding", LAYER_SCHEDULE).read_text(encoding="utf-8")
    )
    assert sidecar["parsed"]["skips"] == list(expected)

    session.get.return_value = _response(status=304, text="")
    second = collect_programme(
        _school(),
        2026,
        _ALIASES,
        session=session,
        layers=(LAYER_SCHEDULE,),
        page_cache=store,
    )
    assert second.outcomes[LAYER_SCHEDULE].unchanged is True
    assert second.outcomes[LAYER_SCHEDULE].skips == expected


def test_box_kind_folds_every_character_outside_the_safe_set() -> None:
    """A box page is named by its fixture id, folded to ``[A-Za-z0-9._-]``.
    Presto ids carry only colons and alphanumerics (every stored matches
    file read on 2026-09-06 holds no id with a slash), so both platforms
    fold the same way; the general fold is pinned on a made-up id."""
    assert box_kind("sidearm:harding:14053") == "box-sidearm-harding-14053"
    assert (
        box_kind("presto:bridgeport:0x4hct72k8bvn6o4")
        == "box-presto-bridgeport-0x4hct72k8bvn6o4"
    )
    assert box_kind("presto:x/y z") == "box-presto-x-y-z"
    store = PageStateStore(Path("/home"), 2026, "men")
    assert store.html_path("harding", box_kind("sidearm:harding:14053")) == Path(
        "/home/data/raw_html/harding/2026-men-box-sidearm-harding-14053.html"
    )


def test_save_html_writes_the_page_atomically(tmp_path: Path) -> None:
    store = PageStateStore(tmp_path, 2026, "men")
    store.save_html("harding", "box-sidearm-harding-1", "<html>one</html>")
    store.save_html("harding", "box-sidearm-harding-1", "<html>two</html>")

    path = (
        tmp_path
        / "data"
        / "raw_html"
        / "harding"
        / "2026-men-box-sidearm-harding-1.html"
    )
    assert path.read_text(encoding="utf-8") == "<html>two</html>"
    # The temporary the rename came from never outlives the write.
    assert sorted(item.name for item in path.parent.iterdir()) == [path.name]


def test_box_archive_saves_the_page_and_a_sidecar_the_store_loads(
    tmp_path: Path,
) -> None:
    store = PageStateStore(tmp_path, 2026, "men")
    archive = BoxArchive(store, "harding", "sidearm:harding:1", "fp-1")
    record = {"source_url": "https://example.test/boxscore/1", "teams": []}
    archive.save(
        requested_url="https://example.test/boxscore/1",
        final_url="https://example.test/boxscore/1",
        html="<html>box</html>",
        parsed=record,
    )

    assert archive.html_path().read_text(encoding="utf-8") == "<html>box</html>"
    state = archive.load()
    assert state is not None and state.parsed == record
    assert state.signature == content_signature("<html>box</html>")
    # Another fingerprint keeps the bytes but not the parse.
    stale = BoxArchive(store, "harding", "sidearm:harding:1", "fp-2").load()
    assert stale is not None and stale.parsed is None
    # A sidecar-only rewrite leaves the archived bytes alone.
    archive.save(
        requested_url="https://example.test/boxscore/1",
        final_url="https://example.test/boxscore/1",
        html="<html>never written</html>",
        parsed={"teams": [1]},
        with_html=False,
    )
    assert archive.html_path().read_text(encoding="utf-8") == "<html>box</html>"
    assert archive.load().parsed == {"teams": [1]}  # type: ignore[union-attr]
