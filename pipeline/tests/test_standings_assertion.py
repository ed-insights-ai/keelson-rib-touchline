"""Standings pages whose heading names no gender or season, and divisions in a table.

``check-membership --standings`` reads the season and gender off the page's
heading ("2022 Men's Soccer Standings") and refuses a page served for
another. The Division I women's pages of 2026-11-20 defeat that reading: the
Big 12 prints "2026 Soccer Standings" (its sport path is ``soc``), the OVC's
2022 page "2022 Soccer Standings", the UAC "2026 Soccer (W) Standings", and
the NEC "2026 NEC Women's Soccer Standings". The check used to verify neither
and say nothing. Now it reads what a heading does say, refuses a page whose
heading leaves the season or gender unsaid unless the operator asserts it
(``--assert-season``, ``--assert-gender``), records every assertion in the
verdict, and still refuses a page that contradicts what was asked.

The UAC prints its Blue and Red divisions as header rows inside one table;
they are read as each following team's division and held against the
windows' ``division``.

Every page is a capture from the women's onboarding
(``d1-soccer/docs/onboarding-2026-11-20-women/batches/standings``), trimmed
to its title, standings headings and table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import membership
from src.config import SchoolConfig, programme_slug

FIXTURES = Path(__file__).parent / "fixtures"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


BIG12 = _page("sidearm_big12_women_standings_2026.html")
UAC = _page("sidearm_uac_women_standings_2026.html")
NEC = _page("sidearm_nec_women_standings_2026.html")
OVC_2022 = _page("sidearm_ovc_women_standings_2022.html")

UAC_DIVISIONS = {
    "EKU": "Blue Division",
    "North Alabama": "Blue Division",
    "Austin Peay": "Blue Division",
    "West Georgia": "Blue Division",
    "Abilene Christian": "Red Division",
    "Tarleton State": "Red Division",
    "Central Arkansas": "Red Division",
    "Little Rock": "Red Division",
}


def _school(name: str, conference: str) -> SchoolConfig:
    return SchoolConfig(
        name=name,
        abbreviation="",
        conference=conference,
        prefix="",
        base_url="",
        gender="women",
    )


def _case(
    conference: str,
    season: int,
    names: list[str],
    divisions: dict[str, str] | None = None,
) -> tuple[dict, list[SchoolConfig]]:
    """A document and stanzas authored from the names a page lists."""

    def window(name: str) -> dict:
        authored = {
            "conference": conference,
            "from_season": season,
            "to_season": season,
            "source": "test fixture",
        }
        if divisions is not None:
            authored["division"] = divisions[name]
        return authored

    document = {
        "version": 1,
        "seasons": {"from": season, "to": season},
        "conferences": [conference, "independent", "non_member"],
        "conference_profiles": {
            conference: {"level": "d1", "names": [f"{conference} Test Conference"]}
        },
        "memberships": {
            programme_slug(name): {"women": [window(name)]} for name in names
        },
    }
    return document, [_school(name, conference) for name in names]


def _names(html: str) -> list[str]:
    return [name.rstrip(" *") for name in membership.parse_standings_page(html).names]


# ── what a heading says ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("html", "season", "gender", "count"),
    [
        (BIG12, 2026, None, 16),
        (OVC_2022, 2022, None, 9),
        (UAC, 2026, "women", 8),
        (NEC, 2026, "women", 11),
    ],
    ids=["big12-2026", "ovc-2022", "uac-2026", "nec-2026"],
)
def test_a_heading_is_read_for_whatever_it_says(html, season, gender, count):
    page = membership.parse_standings_page(html)
    assert (page.season, page.gender, len(page.names)) == (season, gender, count)


def test_a_heading_with_no_season_still_names_its_gender():
    html = NEC.replace(
        "2026 NEC Women's Soccer Standings", "NEC Women's Soccer Standings"
    )
    page = membership.parse_standings_page(html)
    assert (page.season, page.gender) == (None, "women")


# ── divisions printed inside one table ─────────────────────────────────────


def test_division_header_rows_are_divisions_not_teams():
    page = membership.parse_standings_page(UAC)
    assert [name.rstrip(" *") for name in page.names] == list(UAC_DIVISIONS)
    assert {
        name.rstrip(" *"): division for name, division in page.divisions.items()
    } == UAC_DIVISIONS
    # A table with no division rows carries none.
    assert membership.parse_standings_page(BIG12).divisions == {}


def test_the_page_divisions_are_held_against_the_windows():
    names = _names(UAC)
    document, schools = _case("UAC", 2026, names, UAC_DIVISIONS)
    verdict = membership.verify_standings(
        UAC, "UAC", "women", 2026, document=document, schools=schools
    )
    assert verdict.agrees
    assert verdict.division_mismatches == {}

    moved = {**UAC_DIVISIONS, "Little Rock": "Blue Division"}
    document, schools = _case("UAC", 2026, names, moved)
    verdict = membership.verify_standings(
        UAC, "UAC", "women", 2026, document=document, schools=schools
    )
    assert not verdict.agrees
    assert verdict.division_mismatches == {
        "little-rock": ("Red Division", "Blue Division")
    }

    # Windows that carry no division beside a page that prints them.
    document, schools = _case("UAC", 2026, names)
    verdict = membership.verify_standings(
        UAC, "UAC", "women", 2026, document=document, schools=schools
    )
    assert not verdict.agrees
    assert verdict.division_mismatches["eku"] == ("Blue Division", None)


# ── an explicit, recorded assertion for what the heading leaves unsaid ─────


def test_a_page_whose_heading_leaves_the_gender_unsaid_is_refused_unasserted():
    document, schools = _case("BIG12", 2026, _names(BIG12))
    with pytest.raises(ValueError, match="names no gender.*--assert-gender"):
        membership.verify_standings(
            BIG12, "BIG12", "women", 2026, document=document, schools=schools
        )
    verdict = membership.verify_standings(
        BIG12,
        "BIG12",
        "women",
        2026,
        document=document,
        schools=schools,
        assert_gender=True,
    )
    assert verdict.agrees
    assert verdict.asserted == ("gender",)


def test_a_page_whose_heading_leaves_the_season_unsaid_is_refused_unasserted():
    html = NEC.replace(
        "2026 NEC Women's Soccer Standings", "NEC Women's Soccer Standings"
    )
    document, schools = _case("NEC", 2026, _names(NEC))
    with pytest.raises(ValueError, match="names no season.*--assert-season"):
        membership.verify_standings(
            html, "NEC", "women", 2026, document=document, schools=schools
        )
    verdict = membership.verify_standings(
        html,
        "NEC",
        "women",
        2026,
        document=document,
        schools=schools,
        assert_season=True,
    )
    assert verdict.asserted == ("season",)
    # A heading that says both needs no assertion and records none.
    verdict = membership.verify_standings(
        NEC, "NEC", "women", 2026, document=document, schools=schools
    )
    assert verdict.asserted == ()


def test_an_assertion_never_overrides_what_the_page_does_say():
    document, schools = _case("BIG12", 2025, _names(BIG12))
    with pytest.raises(ValueError, match="2026 season, not 2025"):
        membership.verify_standings(
            BIG12,
            "BIG12",
            "women",
            2025,
            document=document,
            schools=schools,
            assert_season=True,
            assert_gender=True,
        )
    document, schools = _case("UAC", 2026, _names(UAC), UAC_DIVISIONS)
    with pytest.raises(ValueError, match="women's soccer, not men's"):
        membership.verify_standings(
            UAC,
            "UAC",
            "men",
            2026,
            document=document,
            schools=schools,
            assert_gender=True,
        )


def test_the_cli_records_the_assertion(monkeypatch, capsys, tmp_path):
    from scripts.check_membership import main

    document, schools = _case("OVC", 2022, _names(OVC_2022))
    monkeypatch.setattr(membership, "load_membership", lambda *a, **k: document)
    monkeypatch.setattr(membership, "validate", lambda *a, **k: [])
    monkeypatch.setattr(membership, "load_schools", lambda *a, **k: schools)
    page = tmp_path / "ovc-2022.html"
    page.write_text(OVC_2022, encoding="utf-8")
    argv = ["--standings", str(page), "--conference", "OVC", "--season", "2022"]

    assert main([*argv, "--gender", "women"]) == 1
    assert "names no gender" in capsys.readouterr().err

    assert main([*argv, "--gender", "women", "--assert-gender"]) == 0
    out = capsys.readouterr().out
    assert "gender asserted, not read: women" in out
    assert "agreement" in out
