"""The town resolver: exactly one place, or a failure that names why.

Places first; the county-subdivisions file only when places has no match.
"""

import pytest

from src import gazetteer as gz

HEADER = "USPS\tGEOID\tANSICODE\tNAME\tLSAD\tFUNCSTAT\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG"
ROWS = [
    "AR\t0563020\t00069956\tSearcy city\t25\tA\t1\t0\t1\t0\t35.2411\t-91.7352",
    "FL\t1243975\t02404437\tMelbourne city\t25\tA\t1\t0\t1\t0\t28.1090\t-80.6449",
    "FL\t1244075\t02404443\tMelbourne Village town\t43\tA\t1\t0\t1\t0\t28.0912\t-80.6620",
    "IL\t1772000\t02399411\tSpringfield city\t25\tA\t1\t0\t1\t0\t39.7911\t-89.6446",
    "IL\t1772001\t02399412\tSpringfield village\t47\tA\t1\t0\t1\t0\t39.0\t-89.0",
    "FL\t1262775\t02403581\tSt. Leo town\t43\tA\t1\t0\t1\t0\t28.3361\t-82.2582",
    "MO\t2938000\t00735212\tKansas City city\t25\tA\t1\t0\t1\t0\t39.1235\t-94.5539",
    "TN\t4752006\t02405092\tNashville-Davidson metropolitan government (balance)\t21\tA\t1\t0\t1\t0\t36.1718\t-86.7850",
    "TX\t4855000\t02411470\tOdessa city\t25\tA\t1\t0\t1\t0\t31.8805\t-102.3453",
    "TX\t4855012\t02411471\tOdessa CDP\t57\tS\t1\t0\t1\t0\t31.0\t-102.0",
]


# County subdivisions: no LSAD column, lines padded with spaces (as the
# Census file is). Searcy and Springfield have places rows above; the
# subdivisions of the same name must never be reached for them.
COUSUB_ROWS = [
    "AR\t0514599999\t00000001\tSearcy township\tA\t1\t0\t1\t0\t35.0\t-91.0   ",
    "IL\t1716799999\t00000002\tSpringfield township\tA\t1\t0\t1\t0\t39.0\t-89.0   ",
    "NH\t3300564580\t00873707\tRindge town\tA\t96104786\t6962970\t37.106\t2.688\t42.756663\t-72.013247   ",
    "NJ\t3401306260\t01729714\tBloomfield township\tA\t13822567\t63224\t5.337\t0.024\t40.809141\t-74.187142   ",
]
TOWNS_THE_PLACES_FILE_LACKS = [
    ("Rindge, N.H.", "3300564580", "Rindge town", 42.7567, -72.0132),
    ("Colchester, Vt.", "5000714875", "Colchester town", 44.5541, -73.2255),
    ("Bloomfield, N.J.", "3401306260", "Bloomfield township", 40.8091, -74.1871),
    ("Amherst, N.Y.", "3602902000", "Amherst town", 43.0116, -78.7571),
]


def _gaz() -> gz.Gazetteer:
    return gz.Gazetteer(
        gz.read_places("\n".join([HEADER, *ROWS]) + "\n"),
        header=HEADER,
        fetch_full=False,
        cousubs=gz.read_cousubs(
            "\n".join([gz.COUSUBS_HEADER + "   ", *COUSUB_ROWS]) + "\n"
        ),
    )


@pytest.mark.parametrize(
    ("text", "name", "usps", "ap"),
    [
        ("Searcy, Ark.", "Searcy", "AR", "Searcy, Ark."),
        ("Rome, GA", "Rome", "GA", "Rome, Ga."),
        ("Alva, Oklahoma", "Alva", "OK", "Alva, Okla."),
        ("Ada, OK / Tiger Soccer Field", "Ada", "OK", "Ada, Okla."),
        ("Dallas, Texas", "Dallas", "TX", "Dallas, Texas"),
    ],
)
def test_parse_town_reads_ap_usps_and_spelled_states(text, name, usps, ap) -> None:
    town = gz.parse_town(text)
    assert town is not None
    assert (town.name, town.usps, town.ap) == (name, usps, ap)


@pytest.mark.parametrize("text", ["Searcy", "Searcy, Arkansaw", "", "TBA"])
def test_parse_town_refuses_what_is_not_a_town_and_state(text) -> None:
    assert gz.parse_town(text) is None


def test_one_incorporated_place_resolves() -> None:
    place = _gaz().resolve(gz.parse_town("Searcy, Ark."))
    assert (place.geoid, place.lat, place.lon) == ("0563020", 35.2411, -91.7352)


def test_a_place_named_city_keeps_its_name() -> None:
    assert _gaz().resolve(gz.parse_town("Kansas City, Mo.")).geoid == "2938000"


def test_incorporated_outranks_a_cdp_of_the_same_name() -> None:
    assert _gaz().resolve(gz.parse_town("Odessa, Texas")).geoid == "4855000"


def test_two_incorporated_places_fail_naming_both() -> None:
    with pytest.raises(gz.GazetteerError) as caught:
        _gaz().resolve(gz.parse_town("Springfield, Ill."))
    assert "1772000 Springfield city" in str(caught.value)
    assert "1772001 Springfield village" in str(caught.value)
    assert "gazetteer_geoid" in str(caught.value)


def test_a_place_whose_name_extends_the_town_is_not_a_match() -> None:
    # "Melbourne Village town" is not Melbourne; only "Melbourne city" is.
    assert _gaz().resolve(gz.parse_town("Melbourne, Fla.")).geoid == "1243975"


def test_a_pin_settles_the_ambiguity() -> None:
    assert (
        _gaz().resolve(gz.parse_town("Springfield, Ill."), pin="1772001").geoid
        == "1772001"
    )


def test_a_pin_reaches_a_consolidated_or_abbreviated_place() -> None:
    g = _gaz()
    assert (
        g.resolve(gz.parse_town("Nashville, Tenn."), pin="4752006").geoid == "4752006"
    )
    assert g.resolve(gz.parse_town("Saint Leo, Fla."), pin="1262775").geoid == "1262775"


def test_a_pin_that_names_another_place_fails() -> None:
    with pytest.raises(gz.GazetteerError) as caught:
        _gaz().resolve(gz.parse_town("Searcy, Ark."), pin="4855000")
    assert "not the town in the city string" in str(caught.value)


def test_an_unknown_town_fails_without_fetching_when_offline() -> None:
    with pytest.raises(gz.GazetteerError) as caught:
        _gaz().resolve(gz.parse_town("Nowhere, Ark."))
    assert "no 2023 Gazetteer place in AR" in str(caught.value)
    assert "places file or the county subdivisions file" in str(caught.value)


@pytest.mark.parametrize(
    ("city", "geoid", "name", "lat", "lon"), TOWNS_THE_PLACES_FILE_LACKS
)
def test_a_town_the_places_file_lacks_resolves_through_county_subdivisions(
    city, geoid, name, lat, lon
) -> None:
    # Driven by the committed trimmed fixtures, offline: the four batch-1 towns.
    town = gz.parse_town(city)
    place = gz.Gazetteer.load(fetch_full=False).resolve(town)
    assert (place.geoid, place.name, place.cousub, town.ap) == (geoid, name, True, city)
    assert (place.lat, place.lon) == (lat, lon)
    assert place.incorporated


def test_a_town_the_places_file_has_never_consults_county_subdivisions(
    monkeypatch,
) -> None:
    g = _gaz()

    def never(_town):
        raise AssertionError("the county subdivisions file was consulted")

    monkeypatch.setattr(g, "_cousub_candidates", never)
    monkeypatch.setattr(g, "_widen_cousubs", lambda: never(None))
    place = g.resolve(gz.parse_town("Searcy, Ark."))
    assert (place.geoid, place.cousub) == ("0563020", False)
    # Two places candidates stay an ambiguity naming them, not a fallback.
    with pytest.raises(gz.GazetteerError) as caught:
        g.resolve(gz.parse_town("Springfield, Ill."))
    assert "1772000 Springfield city" in str(caught.value)
    assert "township" not in str(caught.value)


def test_a_ten_digit_pin_resolves_through_county_subdivisions() -> None:
    place = _gaz().resolve(gz.parse_town("Rindge, N.H."), pin="3300564580")
    assert (place.geoid, place.name, place.cousub) == (
        "3300564580",
        "Rindge town",
        True,
    )


def test_a_county_subdivision_descriptor_comes_off_the_name() -> None:
    assert gz._stem("Bloomfield township") == "bloomfield"
    assert gz._stem("Autaugaville CCD") == "autaugaville"
    assert gz._stem("Rindge town") == "rindge"


def test_trimmed_text_round_trips_the_rows_used() -> None:
    g = _gaz()
    g.resolve(gz.parse_town("Searcy, Ark."))
    text = g.trimmed_text(g.used)
    assert text.splitlines()[0] == HEADER
    assert len(text.splitlines()) == 2
    assert gz.read_places(text)[0].geoid == "0563020"


def test_trimmed_cousubs_text_holds_only_the_subdivisions_used_unpadded() -> None:
    g = _gaz()
    g.resolve(gz.parse_town("Searcy, Ark."))
    g.resolve(gz.parse_town("Rindge, N.H."))
    text = g.trimmed_cousubs_text(g.used)
    assert text.splitlines() == [
        gz.COUSUBS_HEADER,
        "NH\t3300564580\t00873707\tRindge town\tA\t96104786\t6962970\t37.106\t2.688\t42.756663\t-72.013247",
    ]
    assert len(g.trimmed_text(g.used).splitlines()) == 2
