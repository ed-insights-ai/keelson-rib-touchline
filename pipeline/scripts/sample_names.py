"""Invent the people in a sample data home.

The sample homes are public, so nobody in them keeps a real name. Every name
token of every person the season files name (players, keepers, scorers,
assisters, carded players and officials) is swapped for an invented token,
and the swap is applied everywhere that token appears: the name fields, the
play-by-play and goal descriptions, and the name slug in a roster or bio URL.

The swap works on tokens, not whole names, so every spelling a vendor prints
stays consistent: "Payton Roehrich", "Roehrich, Payton", "ROEHRICH,PAYTON",
"P. Roehrich" and roster/payton-roehrich/9246 all become the same invented
person. An invented token keeps the real token's initial, its case pattern, an
accent where the real one had one and an apostrophe where the real one had
one, so initials, accent folding and case-insensitive joins work exactly as
they did. The map is injective and never produces a real token of the home,
so two people stay two people and no invented token reads as someone real
from the same home.

Everything else (numbers, ids, positions, hometowns, teams, scores, times)
stays as collected. Particles and suffixes (de, van, Jr, III) and tokens of
one or two letters (JJ, Li) are kept: on their own they name nobody.

`invent(home)` rewrites the season files of a home in place and returns a
report; `residue(home, vocabulary)` lists every real token still present,
and the cut refuses a sample that has any.

Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from src.identity import fold_name

PEOPLE_LAYERS = ("rosters", "stats", "matches")

# Kept as published: they name nobody on their own.
KEEP = frozenset(
    "de del della der den di da dos das du la le van von ten ter st y e "
    "jr sr ii iii iv v vi".split()
)

# Play-by-play vocabulary. A lowercase occurrence of one of these in free text
# is the word, not a person ("yellow card", "cross", "drew a foul").
PLAY_WORDS = frozenset(
    """
    against and area assist at back ball bar beam block blocked bottom box by
    card center chase clear corner cross day deflected deflection drew end far
    field foot for foul free from front goal goalie half hand head header high
    in keeper kick left line long miss missed near of off offside on out over
    pass penalty period post quick rebound red right rush save saved short shot
    start sub substitution ten the to top under volley wide win woodwork yellow
    """.split()
)

TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
ROSTER_SLUG = re.compile(r"(/roster/)([^/?#]+)(/\d+)")

_VOWELS = "aeiou"
_ACCENT = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú"}
_MIDS = ["b", "d", "l", "m", "n", "r", "s", "t", "v", "z", "nd", "rl", "st", "lv"]
_ENDS = [
    "a",
    "e",
    "o",
    "an",
    "en",
    "el",
    "er",
    "is",
    "in",
    "on",
    "ar",
    "ell",
    "ard",
    "ick",
    "ley",
    "ton",
    "sen",
    "ska",
    "ner",
    "by",
    "dale",
    "ford",
    "ane",
    "ina",
    "ia",
    "ett",
    "ory",
    "ix",
]


def fold(token: str) -> str:
    """The key a token is known by: accents off, lower case, one apostrophe."""
    plain = unicodedata.normalize("NFKD", token.replace("’", "'"))
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _plain(key: str) -> str:
    return key.replace("'", "")


def _kept(key: str) -> bool:
    return len(_plain(key)) <= 2 or key in KEEP


def _pool(letter: str) -> list[str]:
    """Every invented token starting with `letter`, in a fixed order."""
    if letter in _VOWELS + "y":
        onsets = [letter + c for c in ("l", "r", "v", "s", "d", "b")]
        heads = [o + v for o in onsets for v in _VOWELS]
    else:
        onsets = ["qu"] if letter == "q" else [letter]
        if letter in "bcdfgkpt":
            onsets += [letter + "r", letter + "l"]
        elif letter in "sv":
            onsets += [letter + "t" if letter == "s" else "vr"]
        heads = [o + v for o in onsets for v in _VOWELS]
    return [h + m + e for h in heads for m in _MIDS for e in _ENDS]


def _shape(invented: str, real: str) -> str:
    """Give an invented (lowercase, plain) token the real token's look."""
    out = invented
    if any(ord(c) > 127 for c in real):
        for i, c in enumerate(out):
            if i and c in _ACCENT:
                out = out[:i] + _ACCENT[c] + out[i + 1 :]
                break
    if "'" in real or "’" in real:
        mark = "’" if "’" in real else "'"
        out = out[0] + mark + out[1:]
    letters = [c for c in real if c.isalpha()]
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return out.upper()
    if all(c.islower() for c in letters):
        return out
    out = out[0].upper() + out[1:]
    inner = [i for i, c in enumerate(real) if i and c.isupper()]
    if inner:
        # McIntosh, DeLuca: keep a second capital so spellings that differ
        # only there stay different.
        at = min(inner[0], len(out) - 1)
        if out[at] in "'’":
            at = min(at + 1, len(out) - 1)
        out = out[:at] + out[at].upper() + out[at + 1 :]
    return out


class NameMap:
    """An injective map from real name tokens to invented ones."""

    def __init__(self, vocabulary: set[str]):
        self.real = {fold(t) for t in vocabulary}
        avoid = {_plain(k) for k in self.real}
        used: set[str] = set()
        self.map: dict[str, str] = {}
        # fold_name(real) -> fold_name(invented), for key-sourced player ids.
        self.folded: dict[str, str] = {}
        for key in sorted(self.real):
            if _kept(key):
                continue
            plain = _plain(key)
            if plain in self.map:  # o'brien and obrien are one person
                self.map[key] = self.map[plain]
                continue
            letter = next((c for c in plain if "a" <= c <= "z"), "x")
            pool = _pool(letter)
            i = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(pool)
            for step in range(len(pool)):
                cand = pool[(i + step) % len(pool)]
                if cand not in used and cand not in avoid:
                    break
            else:  # pragma: no cover - pools hold thousands per letter
                raise SystemExit(f"ran out of invented names for {letter!r}")
            used.add(cand)
            self.map[key] = cand
            self.map.setdefault(plain, cand)

    def token(self, real: str, free_text: bool = False) -> str:
        key = fold(real)
        new = self.map.get(key)
        if new is None:
            return real
        if free_text and real.islower() and key in PLAY_WORDS:
            return real
        return _shape(new, real)

    def name(self, text: str) -> str:
        return TOKEN.sub(lambda m: self.token(m.group(0)), text)

    def text(self, text: str, protect: list[str]) -> str:
        """Free text: team names and abbreviations are left as published, except
        where a comma follows, which is a surname ("Harding, Drew")."""
        return _protected(
            text,
            protect,
            lambda s: TOKEN.sub(lambda m: self.token(m.group(0), free_text=True), s),
        )

    def official(self, text: str) -> str:
        role, sep, who = text.partition(":")
        return role + sep + self.name(who) if sep else self.name(text)

    def url(self, url: str, new_name: str | None) -> str:
        m = ROSTER_SLUG.search(url)
        if m and new_name is not None:
            return url[: m.start(2)] + slugify(new_name) + url[m.end(2) :]
        if m:
            slug = "-".join(self.token(p) for p in m.group(2).split("-"))
            return url[: m.start(2)] + slug + url[m.end(2) :]
        return url


def slugify(name: str) -> str:
    plain = fold(name).replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def _protected(text: str, protect: list[str], fn) -> str:
    if not protect:
        return fn(text)
    pat = re.compile(
        "|".join(
            # "Harding, Drew" is a person even in a Harding match.
            r"(?<!\w)" + re.escape(p) + r"(?![\w,])"
            for p in sorted(set(protect), key=len, reverse=True)
            if p
        )
    )
    out, last = [], 0
    for m in pat.finditer(text):
        out.append(fn(text[last : m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(fn(text[last:]))
    return "".join(out)


# -- what a season file names ------------------------------------------------


def _people(doc: dict) -> list[str]:
    """Every person-name string a season file holds in a name field."""
    names: list[str] = []
    for team in (doc.get("rosters") or {}).values():
        names += [p.get("name") or "" for p in team.get("players", [])]
    for team in (doc.get("teams") or {}).values():
        for k in ("players", "keepers"):
            names += [p.get("name") or "" for p in team.get(k, [])]
    for match in (doc.get("matches") or {}).values():
        for side in match.get("teams", []):
            for k in ("players", "keepers"):
                names += [p.get("name") or "" for p in side.get(k, [])]
        for s in match.get("scoring", []):
            names += [s.get("scorer") or "", s.get("assist") or ""]
        names += [c.get("player") or "" for c in match.get("cards", [])]
        names += [o.partition(":")[2] or o for o in match.get("officials") or []]
    return names


def vocabulary(docs: list[dict]) -> set[str]:
    return {t for d in docs for n in _people(d) for t in TOKEN.findall(n)}


def _protect_for(match: dict) -> list[str]:
    out = []
    for side in match.get("teams", []):
        out += [side.get("name") or "", side.get("abbr") or ""]
    return [p for p in out if p]


def apply(doc: dict, names: NameMap) -> None:
    """Swap every person in one season file, in place."""
    for team in (doc.get("rosters") or {}).values():
        for p in team.get("players", []):
            _person(p, names, "source_url")
    for team in (doc.get("teams") or {}).values():
        for k in ("players", "keepers"):
            for p in team.get(k, []):
                _person(p, names, "bio_url")
    for match in (doc.get("matches") or {}).values():
        protect = _protect_for(match)
        for side in match.get("teams", []):
            for k in ("players", "keepers"):
                for p in side.get(k, []):
                    _person(p, names, "bio_url")
        for s in match.get("scoring", []):
            for k in ("scorer", "assist"):
                if isinstance(s.get(k), str):
                    s[k] = names.name(s[k])
            if isinstance(s.get("description"), str):
                s["description"] = names.text(s["description"], protect)
        for c in match.get("cards", []):
            if isinstance(c.get("player"), str):
                c["player"] = names.name(c["player"])
        for play in match.get("plays", []):
            if isinstance(play.get("text"), str):
                play["text"] = names.text(play["text"], protect)
        if match.get("officials"):
            match["officials"] = [
                names.official(o) if isinstance(o, str) else o
                for o in match["officials"]
            ]


def _person(row: dict, names: NameMap, url_key: str) -> None:
    new = None
    if isinstance(row.get("name"), str):
        old = row["name"]
        new = row["name"] = names.name(old)
        if fold_name(old) != fold_name(new):
            names.folded.setdefault(fold_name(old), fold_name(new))
    if isinstance(row.get(url_key), str):
        row[url_key] = names.url(row[url_key], new)


def rekey(doc: dict, names: NameMap) -> list[str]:
    """Re-fold key-sourced player ids (programme:foldedname:number) from the
    invented names; return the ids whose name no line of the home carried."""
    missed: list[str] = []
    for match in (doc.get("matches") or {}).values():
        for side in match.get("teams", []):
            for k in ("players", "keepers"):
                for p in side.get(k, []):
                    ref = p.get("player_ref")
                    if not isinstance(ref, dict) or ref.get("source") != "key":
                        continue
                    slug, sep, rest = str(ref.get("id", "")).partition(":")
                    folded, sep2, number = rest.rpartition(":")
                    if not (sep and sep2):
                        missed.append(
                            f"key id {ref.get('id')!r} is not slug:name:number"
                        )
                    elif folded in names.folded:
                        ref["id"] = f"{slug}:{names.folded[folded]}:{number}"
                    elif folded not in names.folded.values():
                        missed.append(f"key id {ref['id']!r} folds no name in the home")
    return missed


# -- what is left of the real names --------------------------------------------


def residue(doc: dict, names: NameMap) -> list[str]:
    """Every real (mapped) token still in a person-bearing field."""
    left: list[str] = []

    def scan(text: str, where: str, free: bool, protect: list[str] = ()) -> None:
        def look(s: str) -> str:
            for t in TOKEN.findall(s):
                key = fold(t)
                if key in names.map and not (
                    free and t.islower() and key in PLAY_WORDS
                ):
                    left.append(f"{where}: {t!r} in {text!r}")
            return s

        _protected(text, list(protect), look) if free else look(text)

    for name in _people(doc):
        scan(name, "name", False)
    for team in (doc.get("rosters") or {}).values():
        for p in team.get("players", []):
            scan(_slug(p.get("source_url")), "url", False)
    for team in (doc.get("teams") or {}).values():
        for k in ("players", "keepers"):
            for p in team.get(k, []):
                scan(_slug(p.get("bio_url")), "url", False)
    for match in (doc.get("matches") or {}).values():
        protect = _protect_for(match)
        for side in match.get("teams", []):
            for k in ("players", "keepers"):
                for p in side.get(k, []):
                    scan(_slug(p.get("bio_url")), "url", False)
        for s in match.get("scoring", []):
            scan(s.get("description") or "", "description", True, protect)
        for play in match.get("plays", []):
            scan(play.get("text") or "", "play", True, protect)
    return left


def _slug(url) -> str:
    m = ROSTER_SLUG.search(url or "")
    return m.group(2).replace("-", " ") if m else ""


# -- a home --------------------------------------------------------------------


def _season_files(data: Path) -> list[Path]:
    return sorted(p for layer in PEOPLE_LAYERS for p in (data / layer).glob("*.json"))


def _dump_like(path: Path, value, original: str) -> None:
    """Write `value` in the layout the collector wrote `original` in."""
    for ascii_only in (True, False):
        if (
            json.dumps(json.loads(original), indent=2, ensure_ascii=ascii_only) + "\n"
            == original
        ):
            break
    else:
        ascii_only = True
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=ascii_only) + "\n", encoding="utf-8"
    )


def invent(home: Path) -> dict:
    """Swap every real person in a home's season files; refuse on any residue."""
    files = _season_files(home / "data")
    originals = {p: p.read_text(encoding="utf-8") for p in files}
    docs = {p: json.loads(s) for p, s in originals.items()}
    names = NameMap(vocabulary(list(docs.values())))
    left: list[str] = []
    for doc in docs.values():
        apply(doc, names)
    for path, doc in docs.items():
        left += [f"{path.name} {r}" for r in rekey(doc, names)]
        left += [f"{path.name} {r}" for r in residue(doc, names)]
    if left:
        shown = "\n  ".join(left[:20])
        raise SystemExit(
            f"{len(left)} real name tokens survived the swap in {home}:\n  {shown}"
        )
    for path, doc in docs.items():
        _dump_like(path, doc, originals[path])
    return {
        "tokens": len(names.real),
        "invented": len({v for v in names.map.values()}),
        "files": [p.relative_to(home).as_posix() for p in files],
    }
