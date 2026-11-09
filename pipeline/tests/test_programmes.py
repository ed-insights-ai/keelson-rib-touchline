"""The programmes reference: built from the stanzas, never guessed, always current."""

import json
from dataclasses import replace
from pathlib import Path

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
    cousubs = gz.TRIMMED_COUSUBS_FIXTURE.read_text(encoding="utf-8")
    assert _offline().trimmed_cousubs_text(built.used_places) == cousubs, (
        "the trimmed county-subdivisions fixture is stale: run `uv run build-programmes`"
    )


def test_every_row_from_before_batch1_is_unchanged() -> None:
    # The coordinator's invariant: the 74 rows that existed before this
    # branch keep their city, GEOID and point, field by field.
    before = json.loads(
        (
            Path(__file__).parent / "fixtures" / "programmes_before_batch1.json"
        ).read_text(encoding="utf-8")
    )["rows"]
    assert len(before) == 74
    rows = json.loads(paths.packaged_programmes_path().read_text(encoding="utf-8"))[
        "programmes"
    ]
    for slug, expected in before.items():
        row = rows[slug]
        actual = {
            "city": row["city"],
            "geoid": row["provenance"]["point"]["geoid"],
            "lat": row["point"]["lat"],
            "lon": row["point"]["lon"],
        }
        assert actual == expected, slug


def test_a_town_the_places_file_lacks_cites_the_county_subdivisions_file() -> None:
    built = programmes.build(
        [_school(name="Franklin Pierce", city="Rindge, N.H.")], _offline()
    )
    row = built.document["programmes"]["franklin-pierce"]
    point = row["provenance"]["point"]
    assert row["city"] == "Rindge, N.H."
    assert row["point"] == {"lat": 42.7567, "lon": -72.0132}
    assert point["source"] == gz.COUSUBS_SOURCE
    assert point["url"] == gz.COUSUBS_URL
    assert point["accessed"] == gz.COUSUBS_FILE_DATE
    assert (point["geoid"], point["name"]) == ("3300564580", "Rindge town")
    assert point["note"] == programmes.COUSUB_NOTE
    # The document-level block still describes the places file.
    assert built.document["gazetteer"]["source"] == gz.GAZETTEER_SOURCE


def test_the_four_batch1_towns_land_as_the_site_prints_them() -> None:
    rows = json.loads(paths.packaged_programmes_path().read_text(encoding="utf-8"))[
        "programmes"
    ]
    expected = {
        "franklin-pierce": ("Rindge, N.H.", "3300564580"),
        "saint-michael-s": ("Colchester, Vt.", "5000714875"),
        "bloomfield": ("Bloomfield, N.J.", "3401306260"),
        "daemen": ("Amherst, N.Y.", "3602902000"),
    }
    for slug, (city, geoid) in expected.items():
        point = rows[slug]["provenance"]["point"]
        assert rows[slug]["city"] == city, slug
        assert point["geoid"] == geoid, slug
        assert point["source"] == gz.COUSUBS_SOURCE, slug
        assert point["note"] == programmes.COUSUB_NOTE, slug


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
        point = row["provenance"]["point"]
        # Every point is the Gazetteer's, named by GEOID, except a stanza's
        # own point for a town the Gazetteer covers nowhere, which says so.
        assert point.get("geoid") or point.get("note") == programmes.POINT_NOTE, slug


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


def test_a_pin_named_for_another_place_needs_the_stanza_to_say_why() -> None:
    # University Center, Mich. is a mailing-address community inside Kochville
    # township with no Gazetteer row of its own. The pin is refused until the
    # stanza says so, and then the city stays the town the school prints.
    stanza = _school(
        name="Saginaw Valley State",
        city="University Center, Mich.",
        gazetteer_geoid="2614543800",
    )
    with pytest.raises(programmes.ProgrammeError) as caught:
        programmes.build([stanza], _offline())
    assert "gazetteer_note" in str(caught.value)
    assert "Kochville township" in str(caught.value)

    why = "University Center is an unincorporated community inside Kochville township"
    built = programmes.build([replace(stanza, gazetteer_note=why)], _offline())
    row = built.document["programmes"]["saginaw-valley-state"]
    point = row["provenance"]["point"]
    assert row["city"] == "University Center, Mich."
    assert (point["geoid"], point["name"]) == ("2614543800", "Kochville township")
    assert row["point"] == {"lat": 43.5056, "lon": -83.9852}
    assert why in point["note"] and programmes.COUSUB_NOTE in point["note"]


def test_a_pinned_place_carries_a_note_in_its_provenance() -> None:
    built = programmes.build(
        [_school(name="Saint Leo", city="Saint Leo, Fla.", gazetteer_geoid="1262775")],
        _offline(),
    )
    point = built.document["programmes"]["saint-leo"]["provenance"]["point"]
    assert point["geoid"] == "1262775" and "St. Leo town" in point["note"]
    assert point["accessed"] == gz.GAZETTEER_FILE_DATE


def test_a_point_on_a_gazetteer_resolvable_city_is_refused() -> None:
    # Searcy, Ark. is a Gazetteer place; a stanza point there would override
    # a real place in silence, so the build refuses it naming the place.
    stanza = _school(point=(35.0, -91.0), point_source="a test pin")
    with pytest.raises(programmes.ProgrammeError) as caught:
        programmes.build([stanza], _offline())
    message = str(caught.value)
    assert "harding: point refused" in message
    assert "0563020 Searcy city" in message
    assert "gazetteer_geoid" in message


def test_a_point_carries_a_town_the_gazetteer_covers_nowhere() -> None:
    # Burnaby, B.C. parses to no US state and the Gazetteer has no row for
    # it, so the stanza's own point lands with its source and no GEOID; the
    # city stays as the stanza prints it.
    stanza = _school(
        name="Simon Fraser",
        city="Burnaby, B.C.",
        point=(49.242778, -122.972778),
        point_source="Natural Resources Canada, CGNDB entry JAEBN for Burnaby",
    )
    built = programmes.build([stanza], _offline())
    row = built.document["programmes"]["simon-fraser"]
    assert row["city"] == "Burnaby, B.C."
    assert row["point"] == {"lat": 49.242778, "lon": -122.972778}
    point = row["provenance"]["point"]
    assert point == {
        "source": "Natural Resources Canada, CGNDB entry JAEBN for Burnaby",
        "accessed": "2026-09-02",
        "note": programmes.POINT_NOTE,
    }
    assert built.used_places == {}


def test_the_shipped_simon_fraser_row_carries_the_stanza_point() -> None:
    rows = json.loads(paths.packaged_programmes_path().read_text(encoding="utf-8"))[
        "programmes"
    ]
    row = rows["simon-fraser"]
    assert row["city"] == "Burnaby, B.C."
    assert row["point"] == {"lat": 49.242778, "lon": -122.972778}
    assert row["provenance"]["point"]["note"] == programmes.POINT_NOTE
    assert "geoid" not in row["provenance"]["point"]


def test_a_reasoned_override_corrects_a_resolved_towns_point() -> None:
    # tui-vu9: the Gazetteer's internal point for San Francisco lies 46 km out
    # in the Pacific (the boundary takes in the Farallons). With a reason the
    # stanza's point stands; the town, its GEOID and the replaced point stay
    # in the provenance.
    stanza = _school(
        name="San Francisco State",
        city="San Francisco, Calif.",
        point=(37.7775, -122.41639),
        point_source="a test source",
        point_reason="the boundary takes in the Farallon Islands",
    )
    row = programmes.build([stanza], _offline()).document["programmes"][
        "san-francisco-state"
    ]
    assert row["city"] == "San Francisco, Calif."
    assert row["point"] == {"lat": 37.7775, "lon": -122.41639}
    point = row["provenance"]["point"]
    assert point["source"] == "a test source"
    assert (point["geoid"], point["name"], point["state"]) == (
        "0667000",
        "San Francisco city",
        "CA",
    )
    assert "(37.7272, -123.0322)" in point["note"]
    assert point["note"].endswith("because the boundary takes in the Farallon Islands")


def test_an_override_may_correct_a_point_never_relocate_a_programme() -> None:
    # Oakland is 15 km away and would pass; Sacramento is 120 km away.
    far = _school(
        name="San Francisco State",
        city="San Francisco, Calif.",
        point=(38.5816, -121.4944),
        point_source="a test source",
        point_reason="a reason",
    )
    with pytest.raises(programmes.ProgrammeError) as caught:
        programmes.build([far], _offline())
    assert "san-francisco-state: point override refused" in str(caught.value)


def test_a_reason_on_a_town_the_gazetteer_lacks_is_refused() -> None:
    stanza = _school(
        name="Simon Fraser",
        city="Burnaby, B.C.",
        point=(49.242778, -122.972778),
        point_source="a test source",
        point_reason="nothing to override",
    )
    with pytest.raises(programmes.ProgrammeError) as caught:
        programmes.build([stanza], _offline())
    assert "simon-fraser: point_reason refused" in str(caught.value)


def test_the_shipped_san_francisco_state_row_is_on_the_peninsula() -> None:
    rows = json.loads(paths.packaged_programmes_path().read_text(encoding="utf-8"))[
        "programmes"
    ]
    lat = rows["san-francisco-state"]["point"]["lat"]
    lon = rows["san-francisco-state"]["point"]["lon"]
    assert 37.70 < lat < 37.82 and -122.52 < lon < -122.35
    assert rows["san-francisco-state"]["provenance"]["point"]["geoid"] == "0667000"
