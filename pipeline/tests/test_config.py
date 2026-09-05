"""load_schools refuses two enabled stanzas of one gender that mint one slug.

The slug ``name`` mints keys candidates, coverage cells, membership windows
and the programmes reference, all dicts that keep the later stanza and drop
the earlier one silently. The check is the ordinal check's sibling (bead
tl-4sg.9, same-named institutions).
"""

from __future__ import annotations

import pytest

from src.config import load_schools, programme_slug


def _entry(
    name: str,
    abbr: str,
    *,
    gender: str = "men",
    enabled: bool = True,
    display_name: str = "",
    conference: str = "TEST",
) -> str:
    lines = [
        "[[schools]]",
        f'name = "{name}"',
        f'abbreviation = "{abbr}"',
        f'conference = "{conference}"',
        f'gender = "{gender}"',
        f"enabled = {str(enabled).lower()}",
        f'base_url = "https://{programme_slug(name)}.example/sports/soccer"',
    ]
    if display_name:
        lines.append(f'display_name = "{display_name}"')
    return "\n".join(lines)


def _write(tmp_path, *entries: str):
    config = tmp_path / "schools.toml"
    config.write_text("\n\n".join(entries) + "\n")
    return config


def test_two_enabled_stanzas_minting_one_slug_refuse_the_load(tmp_path):
    """The error names both stanzas, their conferences and the way out."""
    config = _write(
        tmp_path,
        _entry("Lincoln", "LU", conference="GLVC"),
        _entry("Lincoln", "LUP", conference="OTHER"),
    )

    with pytest.raises(ValueError) as caught:
        load_schools(config)

    message = str(caught.value)
    assert "Duplicate programme slug 'lincoln' (men)" in message
    assert "'Lincoln' (LU, GLVC)" in message
    assert "'Lincoln' (LUP, OTHER)" in message
    assert "display_name" in message


def test_a_qualified_name_disambiguates_and_loads(tmp_path):
    """The path the error names: qualify ``name`` and keep the published
    spelling in ``display_name``, which is reader-facing and never an
    identity claim (tl-4an.31), so it may fold to the incumbent's key; both
    stanzas load under their own slug."""
    config = _write(
        tmp_path,
        _entry("Lincoln", "LU", conference="GLVC"),
        _entry(
            "Lincoln Pennsylvania",
            "LUP",
            conference="OTHER",
            display_name="Lincoln (Pa.)",
        ),
    )

    schools = load_schools(config)

    assert [programme_slug(s.name) for s in schools] == [
        "lincoln",
        "lincoln-pennsylvania",
    ]
    assert [s.display() for s in schools] == ["Lincoln", "Lincoln (Pa.)"]


def test_a_disabled_twin_does_not_participate(tmp_path):
    """A disabled stanza reaches no per-programme map, so it may share a slug."""
    config = _write(
        tmp_path,
        _entry("Lincoln", "LU"),
        _entry("Lincoln", "LUX", enabled=False),
        _entry("Lincoln", "LUY", enabled=False),
    )

    schools = load_schools(config)

    assert [s.enabled for s in schools] == [True, False, False]


def test_a_womens_stanza_shares_the_mens_slug_on_purpose(tmp_path):
    """Identity is (gender, slug): one school's two programmes share a slug."""
    config = _write(
        tmp_path,
        _entry("Harding", "HU", gender="men"),
        _entry("Harding", "HUW", gender="women"),
    )

    schools = load_schools(config)

    assert {programme_slug(s.name) for s in schools} == {"harding"}


def test_the_shipped_config_mints_one_slug_per_enabled_programme():
    """Every enabled stanza across every conference has its own (gender, slug)."""
    schools = load_schools()
    keys = [(s.gender, programme_slug(s.name)) for s in schools if s.enabled]
    assert len(keys) == len(set(keys))


def _point_entry(extra: str) -> str:
    return _entry("Simon Fraser", "SFU") + "\n" + extra


def test_a_point_loads_as_a_lat_lon_pair_with_its_source(tmp_path):
    config = _write(
        tmp_path,
        _point_entry(
            "point = { lat = 49.242778, lon = -122.972778 }\n"
            'point_source = "Natural Resources Canada, CGNDB entry JAEBN"'
        ),
    )
    (school,) = load_schools(config)
    assert school.point == (49.242778, -122.972778)
    assert school.point_source == "Natural Resources Canada, CGNDB entry JAEBN"


def test_a_point_without_a_source_is_refused(tmp_path):
    config = _write(tmp_path, _point_entry("point = { lat = 49.24, lon = -122.97 }"))
    with pytest.raises(ValueError, match="point_source"):
        load_schools(config)


@pytest.mark.parametrize(
    "point",
    [
        "point = { lat = 49.24 }",
        'point = { lat = "49.24", lon = -122.97 }',
        "point = 3",
    ],
)
def test_a_malformed_point_is_refused(tmp_path, point):
    config = _write(tmp_path, _point_entry(point + '\npoint_source = "x"'))
    with pytest.raises(ValueError, match="point must be a table"):
        load_schools(config)


def test_a_point_outside_decimal_degrees_is_refused(tmp_path):
    config = _write(
        tmp_path,
        _point_entry('point = { lat = 149.24, lon = -122.97 }\npoint_source = "x"'),
    )
    with pytest.raises(ValueError, match="outside the range"):
        load_schools(config)


def test_a_point_beside_a_geoid_pin_is_refused(tmp_path):
    config = _write(
        tmp_path,
        _point_entry(
            'point = { lat = 49.24, lon = -122.97 }\npoint_source = "x"\n'
            'gazetteer_geoid = "0563020"'
        ),
    )
    with pytest.raises(ValueError, match="alternatives"):
        load_schools(config)
