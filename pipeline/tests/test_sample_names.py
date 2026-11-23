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
                            {"name": "Avery Brannock", "player_ref": {"id": "9"}},
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
                        "scorer": "Avery Brannock",
                        "assist": "Ana Munoz",
                        "description": "GOAL by HU Brannock, Avery Assist by MUNOZ,ANA.",
                    }
                ],
                "cards": [{"player": "Liam O'Brien"}],
                "plays": [
                    {"text": "Brannock, Avery at goalie for Harding"},
                    {
                        "text": "Foul on A. Brannock; yellow card. Shot by Harding, Drew."
                    },
                    {"text": "Shot by Harding, Drew, saved. Harding substitution."},
                    {"text": "Drew a foul: O'Brien, Liam drew one too."},
                ],
                "officials": ["Referee: Avery Smith"],
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
                        "name": "Avery Brannock",
                        "number": "1",
                        "hometown": "Lavon, Texas",
                        "source_url": "https://x.example/sports/mens-soccer/roster/avery-brannock/9246",
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
    assert (first, last) != ("Avery", "Brannock")
    assert first[0] == "A" and last[0] == "B"
    assert m["scoring"][0]["scorer"] == f"{first} {last}"
    assert m["scoring"][0]["description"].startswith(f"GOAL by HU {last}, {first} ")
    assert m["plays"][0]["text"] == f"{last}, {first} at goalie for Harding"
    assert f"A. {last};" in m["plays"][1]["text"]
    assert roster["rosters"]["harding"]["players"][0]["name"] == f"{first} {last}"
    slug = f"{first}-{last}".lower()
    assert roster["rosters"]["harding"]["players"][0]["source_url"].endswith(
        f"/roster/{slug}/9246"
    )
    # A real name token never survives, in any case.
    assert "brannock" not in json.dumps([matches, roster]).lower()


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
    assert "Avery" not in m["officials"][0]
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
    assert "Brannock" not in text and "Avery" not in text


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
    line["player_ref"] = {"id": "harding:averybrannock:7", "source": "key"}
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


def test_page_ids_and_hometown_towns_are_swapped_consistently() -> None:
    from scripts.sample_names import veil

    roster = _roster_file()
    stats = {
        "teams": {
            "harding": {
                "players": [
                    {
                        "name": "X",
                        "player_id": "9246",
                        "bio_url": "https://x.example/sports/mens-soccer/roster/x/9246",
                    }
                ]
            }
        }
    }
    matches = _match_file()
    line = matches["matches"]["sidearm:harding:1"]["teams"][0]["players"][0]
    line["player_id"] = "9246"
    line["player_ref"] = {"id": "9246", "source": "page"}
    key = matches["matches"]["sidearm:harding:1"]["teams"][0]["players"][1]
    key["player_ref"] = {"id": "harding:anamunoz:8", "source": "key"}
    assert veil([roster, stats, matches]) == []

    new = stats["teams"]["harding"]["players"][0]["player_id"]
    assert new != "9246" and len(new) == 4
    assert line["player_id"] == line["player_ref"]["id"] == new
    assert stats["teams"]["harding"]["players"][0]["bio_url"].endswith(f"/x/{new}")
    assert roster["rosters"]["harding"]["players"][0]["source_url"].endswith(f"/{new}")
    assert key["player_ref"]["id"] == "harding:anamunoz:8"
    town, rest = roster["rosters"]["harding"]["players"][0]["hometown"].split(",", 1)
    assert town != "Lavon" and rest == " Texas"


def _one(plays: list[str], players: list[str], **match) -> tuple[dict, NameMap]:
    from scripts.sample_names import apply, team_words

    doc = {
        "matches": {
            "m": {
                "teams": [
                    {
                        "name": "Harding",
                        "abbr": "HU",
                        "players": [
                            {"name": n, "player_ref": {"id": str(i)}}
                            for i, n in enumerate(players)
                        ],
                    },
                    {"name": "Rhode Island", "abbr": "URI", "players": []},
                ],
                "plays": [{"text": t} for t in plays],
                **match,
            }
        }
    }
    words = team_words([doc])
    from scripts.sample_names import _people

    names = NameMap(vocabulary([doc], words), words, set(_people(doc)))
    apply(doc, names)
    return doc["matches"]["m"], names


def test_a_team_spelling_inside_a_given_name_first_name_is_swapped() -> None:
    m, names = _one(
        ["Shot by Drew Harding.", "Offside against Harding."], ["Drew Harding"]
    )
    new = m["teams"][0]["players"][0]["name"]
    assert m["plays"][0]["text"] == f"Shot by {new}."
    assert m["plays"][1]["text"] == "Offside against Harding."
    assert residue({"matches": {"m": m}}, names) == []


def test_possessives_text_only_people_and_play_words() -> None:
    m, names = _one(
        [
            "Brannock's shot is blocked.",
            "Kesselring carries the ball before passing to Brannock.",
            "Short pass from Brannock, off the hand of URI defender.",
            "Shot by HU Short, Anna.",
        ],
        ["Avery Brannock", "Anna Short"],
    )
    surname = m["teams"][0]["players"][0]["name"].split()[1]
    texts = [p["text"] for p in m["plays"]]
    assert texts[0] == f"{surname}'s shot is blocked."
    assert "Kesselring" not in texts[1] and texts[1].endswith(f"passing to {surname}.")
    assert texts[2].startswith("Short pass from ") and "URI defender" in texts[2]
    assert "Short" not in texts[3]
    assert residue({"matches": {"m": m}}, names) == []


def test_the_team_line_stays_a_team_line() -> None:
    m, _ = _one(
        ["Yellow card on HU TEAM."],
        ["Avery Brannock"],
        cards=[{"player": "TEAM"}],
        scoring=[{"scorer": "Team", "description": "Team save."}],
    )
    assert m["cards"][0]["player"] == "TEAM"
    assert m["scoring"][0]["scorer"] == "Team"
    assert m["plays"][0]["text"] == "Yellow card on HU TEAM."


def test_a_name_of_kept_tokens_still_rekeys(tmp_path) -> None:
    doc = _match_file()
    line = doc["matches"]["sidearm:harding:1"]["teams"][0]["players"][0]
    line["name"], line["number"] = "Ji Li", "7"
    line["player_ref"] = {"id": "harding:jili:7", "source": "key"}
    (tmp_path / "data" / "matches").mkdir(parents=True)
    (tmp_path / "data" / "matches" / "2026-men-gac.json").write_text(json.dumps(doc))
    invent(tmp_path)
    out = json.loads((tmp_path / "data" / "matches" / "2026-men-gac.json").read_text())
    ref = out["matches"]["sidearm:harding:1"]["teams"][0]["players"][0]["player_ref"]
    assert ref == {"id": "harding:jili:7", "source": "key"}


def test_folding_spellings_stay_one_person() -> None:
    names = NameMap({"Høihjelle", "Hoihjelle"})
    a, b = names.token("Høihjelle"), names.token("Hoihjelle")
    assert fold(a) == fold(b)


def test_a_page_id_the_cut_cannot_swap_is_refused(tmp_path) -> None:
    roster = {
        "rosters": {
            "tampa": {
                "players": [
                    {
                        "name": "Arlo Vale",
                        "hometown": "Tampa, Fla.",
                        "source_url": "https://x.example/sports/msoc/2026-27/bios/vale_arlo_2fev",
                    }
                ]
            }
        }
    }
    (tmp_path / "data" / "rosters").mkdir(parents=True)
    (tmp_path / "data" / "rosters" / "2026-men-gac.json").write_text(json.dumps(roster))
    with pytest.raises(SystemExit, match="cannot swap"):
        invent(tmp_path)
