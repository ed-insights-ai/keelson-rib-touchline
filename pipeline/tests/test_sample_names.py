"""The sample homes' invented names (scripts/sample_names.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.sample_names import NameMap, fold, invent, residue, vocabulary

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _match_file() -> dict:
    return {
        "schema": "touchline.matches/2",
        "matches": {
            "sidearm:harding:1": {
                "teams": [
                    {
                        "name": "Harding",
                        "abbr": "HU",
                        "players": [
                            {"name": "Payton Roehrich", "player_ref": {"id": "9"}},
                            {"name": "Ana Muñoz", "player_ref": {"id": "8"}},
                            {"name": "Liam O'Brien", "player_ref": {"id": "7"}},
                            {"name": "Drew Harding", "player_ref": {"id": "6"}},
                        ],
                        "keepers": [],
                    },
                    {"name": "Rockhurst", "abbr": "RU", "players": [], "keepers": []},
                ],
                "scoring": [
                    {
                        "scorer": "Payton Roehrich",
                        "assist": "Ana Munoz",
                        "description": "GOAL by HU Roehrich, Payton Assist by MUNOZ,ANA.",
                    }
                ],
                "cards": [{"player": "Liam O'Brien"}],
                "plays": [
                    {"text": "Roehrich, Payton at goalie for Harding"},
                    {
                        "text": "Foul on P. Roehrich; yellow card. Shot by Harding, Drew."
                    },
                    {"text": "Shot by Harding, Drew, saved. Harding substitution."},
                    {"text": "Drew a foul: O'Brien, Liam drew one too."},
                ],
                "officials": ["Referee: Payton Smith"],
            }
        },
    }


def _roster_file() -> dict:
    return {
        "schema": "touchline.rosters/1",
        "rosters": {
            "harding": {
                "players": [
                    {
                        "name": "Payton Roehrich",
                        "number": "1",
                        "hometown": "Lavon, Texas",
                        "source_url": "https://x.example/sports/mens-soccer/roster/payton-roehrich/9246",
                    }
                ]
            }
        },
    }


def _swapped():
    docs = [_match_file(), _roster_file()]
    names = NameMap(vocabulary(docs))
    from scripts.sample_names import apply

    for d in docs:
        apply(d, names)
    return docs, names


def test_every_spelling_of_one_person_gets_the_same_invented_name() -> None:
    (matches, roster), names = _swapped()
    m = matches["matches"]["sidearm:harding:1"]
    first, last = m["teams"][0]["players"][0]["name"].split()
    assert (first, last) != ("Payton", "Roehrich")
    assert first[0] == "P" and last[0] == "R"
    assert m["scoring"][0]["scorer"] == f"{first} {last}"
    assert m["scoring"][0]["description"].startswith(f"GOAL by HU {last}, {first} ")
    assert m["plays"][0]["text"] == f"{last}, {first} at goalie for Harding"
    assert f"P. {last};" in m["plays"][1]["text"]
    assert roster["rosters"]["harding"]["players"][0]["name"] == f"{first} {last}"
    slug = f"{first}-{last}".lower()
    assert roster["rosters"]["harding"]["players"][0]["source_url"].endswith(
        f"/roster/{slug}/9246"
    )
    # A real name token never survives, in any case.
    assert "roehrich" not in json.dumps([matches, roster]).lower()


def test_case_accents_and_apostrophes_carry_over() -> None:
    (matches, _), _ = _swapped()
    m = matches["matches"]["sidearm:harding:1"]
    accented = m["teams"][0]["players"][1]["name"].split()[1]
    plain = m["scoring"][0]["assist"].split()[1]
    assert accented != plain and fold(accented) == fold(plain)
    assert "MUNOZ" not in m["scoring"][0]["description"]
    assert (
        f"{plain.upper()},{m['scoring'][0]['assist'].split()[0].upper()}."
        in (m["scoring"][0]["description"])
    )
    obrien = m["cards"][0]["player"].split()[1]
    assert obrien[1] == "'" and obrien[0] == "O"


def test_teams_play_words_and_unnamed_fields_stay_as_published() -> None:
    (matches, roster), names = _swapped()
    m = matches["matches"]["sidearm:harding:1"]
    # "Harding" is a team here and a player's surname: the team keeps its
    # name only where the text names the team.
    surname = m["teams"][0]["players"][3]["name"].split()[1]
    assert surname != "Harding"
    assert m["plays"][0]["text"].endswith("for Harding")
    assert "yellow card" in m["plays"][1]["text"]
    assert m["plays"][2]["text"].endswith("Harding substitution.")
    assert m["officials"][0].startswith("Referee: ")
    assert "Payton" not in m["officials"][0]
    assert roster["rosters"]["harding"]["players"][0]["hometown"] == "Lavon, Texas"
    assert m["teams"][0]["players"][0]["player_ref"] == {"id": "9"}
    assert f"Shot by {surname}, " in m["plays"][2]["text"]
    assert residue(matches, names) == []


def test_the_map_is_injective_and_never_real() -> None:
    vocab = {"Smith", "Smyth", "Smithe", "Jones", "Joans", "Li", "de", "Jr"}
    names = NameMap(vocab)
    out = [names.token(t) for t in sorted(vocab)]
    assert len(set(out)) == len(out)
    assert names.token("Li") == "Li" and names.token("de") == "de"
    assert not {fold(t) for t in out if t not in {"Li", "de", "Jr"}} & {
        fold(t) for t in vocab
    }
    assert NameMap(vocab).map == names.map  # deterministic


def test_invent_rewrites_a_home_and_refuses_nothing_on_clean_input(tmp_path) -> None:
    for layer, doc in (("matches", _match_file()), ("rosters", _roster_file())):
        (tmp_path / "data" / layer).mkdir(parents=True)
        (tmp_path / "data" / layer / "2026-men-gac.json").write_text(
            json.dumps(doc, indent=2) + "\n"
        )
    report = invent(tmp_path)
    assert report["tokens"] > 0
    text = (tmp_path / "data" / "matches" / "2026-men-gac.json").read_text()
    assert "Roehrich" not in text and "Payton" not in text


@pytest.mark.parametrize("home", sorted(p.name for p in SAMPLES.glob("*-soccer")))
def test_the_checked_in_samples_say_their_people_are_invented(home) -> None:
    manifest = json.loads((SAMPLES / home / "data" / "sample.json").read_text())
    assert manifest["people"].startswith("invented")


def test_key_sourced_player_ids_fold_the_invented_name() -> None:
    from scripts.sample_names import apply, rekey
    from src.identity import fold_name

    doc = _match_file()
    line = doc["matches"]["sidearm:harding:1"]["teams"][0]["players"][0]
    line["number"] = "07"
    line["player_ref"] = {"id": "harding:paytonroehrich:7", "source": "key"}
    names = NameMap(vocabulary([doc]))
    apply(doc, names)
    assert rekey(doc, names) == []
    assert line["player_ref"]["id"] == f"harding:{fold_name(line['name'])}:7"

    stray = _match_file()
    stray["matches"]["sidearm:harding:1"]["teams"][0]["players"][0]["player_ref"] = {
        "id": "harding:nobodyhere:3",
        "source": "key",
    }
    names = NameMap(vocabulary([stray]))
    apply(stray, names)
    assert rekey(stray, names) == [
        "key id 'harding:nobodyhere:3' folds no name in the home"
    ]
