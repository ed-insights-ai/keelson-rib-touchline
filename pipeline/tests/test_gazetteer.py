"""The town resolver: exactly one place, or a failure that names why."""

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


def _gaz() -> gz.Gazetteer:
    return gz.Gazetteer(
        gz.read_places("\n".join([HEADER, *ROWS]) + "\n"),
        header=HEADER,
        fetch_full=False,
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


def test_trimmed_text_round_trips_the_rows_used() -> None:
    g = _gaz()
    g.resolve(gz.parse_town("Searcy, Ark."))
    text = g.trimmed_text(g.used)
    assert text.splitlines()[0] == HEADER
    assert len(text.splitlines()) == 2
    assert gz.read_places(text)[0].geoid == "0563020"
