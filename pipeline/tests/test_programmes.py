"""The programmes reference: built from the stanzas, never guessed, always current."""

import json
from dataclasses import replace

import pytest

from src import gazetteer as gz
from src import paths, programmes
from src.config import SchoolConfig, load_schools
from src.sidearm_live import programme_slug


def _school(**overrides) -> SchoolConfig:
    base = SchoolConfig(
        name="Harding",
        abbreviation="HU",
        conference="GAC",
        prefix="",
        base_url="https://hardingsports.com/sports/mens-soccer",
        years=[2025, 2026],
        enabled=True,
        mascot="Bisons",
        city="Searcy, Ark.",
        identity_accessed="2026-09-02",
    )
    return replace(base, **overrides)


def _offline() -> gz.Gazetteer:
    return gz.Gazetteer.load(fetch_full=False)


def test_the_packaged_file_equals_a_fresh_offline_build() -> None:
    built = programmes.build(load_schools(), _offline())
    packaged = paths.packaged_programmes_path().read_text(encoding="utf-8")
    assert programmes.render(built.document) == packaged, (
        "data/reference/programmes.json is stale — run `uv run build-programmes`"
    )
    fixture = gz.TRIMMED_FIXTURE.read_text(encoding="utf-8")
    assert _offline().trimmed_text(built.used_places) == fixture, (
        "the trimmed Gazetteer fixture is stale — run `uv run build-programmes`"
    )


def test_every_enabled_stanza_has_a_row_with_every_fact() -> None:
    document = json.loads(paths.packaged_programmes_path().read_text(encoding="utf-8"))
    rows = document["programmes"]
    expected = {programme_slug(s.name) for s in load_schools() if s.enabled}
    assert set(rows) == expected
    for slug, row in rows.items():
        for key in ("name", "nickname", "abbreviation", "city"):
            assert row[key], f"{slug} lacks {key}"
        assert isinstance(row["point"]["lat"], float) and isinstance(
            row["point"]["lon"], float
        ), slug
        for fact in ("nickname", "abbreviation", "city", "point"):
            assert row["provenance"][fact]["accessed"], (
                f"{slug} {fact} has no accessed date"
            )
        assert row["provenance"]["point"]["geoid"], slug


def test_a_stanza_without_a_town_stops_the_build_naming_the_slug() -> None:
    with pytest.raises(programmes.ProgrammeError) as caught:
        programmes.build([_school(city="")], _offline())
    assert "harding: stanza has no city" in str(caught.value)


def test_an_unresolvable_town_stops_the_build_naming_the_slug() -> None:
    with pytest.raises(programmes.ProgrammeError) as caught:
        programmes.build([_school(city="Nowhere, Ark.")], _offline())
    assert "harding: Nowhere, Ark.: no 2023 Gazetteer place" in str(caught.value)


def test_a_town_string_that_is_not_a_town_stops_the_build() -> None:
    with pytest.raises(programmes.ProgrammeError) as caught:
        programmes.build([_school(city="TBA")], _offline())
    assert "harding: city 'TBA' is not 'Town, State'" in str(caught.value)


def test_a_disabled_stanza_gets_no_row_and_a_shared_slug_one_row() -> None:
    men = _school()
    women = _school(gender="women", mascot="Lady Bisons")
    off = _school(name="Nowhere", enabled=False, city="")
    built = programmes.build([men, women, off], _offline())
    rows = built.document["programmes"]
    assert list(rows) == ["harding"]
    assert rows["harding"]["nickname"] == "Bisons"


def test_the_city_is_normalised_to_ap_style_and_cites_its_page() -> None:
    built = programmes.build([_school(city="Searcy, AR")], _offline())
    row = built.document["programmes"]["harding"]
    assert row["city"] == "Searcy, Ark."
    city = row["provenance"]["city"]
    assert city["source"] == programmes.CITY_SOURCE_SCHEDULE
    assert city["url"] == "https://hardingsports.com/sports/mens-soccer/schedule/2026"
    assert city["accessed"] == "2026-09-02"


def test_a_pinned_place_carries_a_note_in_its_provenance() -> None:
    built = programmes.build(
        [_school(name="Saint Leo", city="Saint Leo, Fla.", gazetteer_geoid="1262775")],
        _offline(),
    )
    point = built.document["programmes"]["saint-leo"]["provenance"]["point"]
    assert point["geoid"] == "1262775" and "St. Leo town" in point["note"]
    assert point["accessed"] == gz.GAZETTEER_FILE_DATE
