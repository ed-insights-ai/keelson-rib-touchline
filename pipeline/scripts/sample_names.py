"""Invent the people in a sample data home.

The sample homes are public, so nobody in them keeps a real name. Every name
token of every person the season files name (players, keepers, scorers,
assisters, carded players and officials) is swapped for an invented token,
and the swap is applied everywhere that token appears: the name fields, the
play-by-play and goal descriptions, and the name slug in a roster or bio URL.

The swap works on tokens, not whole names, so every spelling a vendor prints
stays consistent: "Avery Brannock", "Brannock, Avery", "BRANNOCK,AVERY",
"A. Brannock" and roster/avery-brannock/9246 all become the same invented
person. An invented token keeps the real token's initial, its case pattern, an
accent where the real one had one and an apostrophe where the real one had
one, so initials, accent folding and case-insensitive joins work exactly as
they did. The map is injective and never produces a real token of the home,
so two people stay two people and no invented token reads as someone real
from the same home.

A person's page ids (the bio id in roster and bio URLs, `player_id`, and
page/twin/roster `player_ref.id`) and the town of a hometown are swapped too,
one-to-one, so no sample player leads back to a real one; `veil` does that.
Everything else (shirt numbers, positions, state or country of a hometown,
teams, scores, times) stays as collected. Particles and suffixes (de, van, Jr, III) and tokens of
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

from src.identity import _PLAIN_LETTERS, fold_name

PEOPLE_LAYERS = ("rosters", "stats", "matches")

# Kept as published: they name nobody on their own.
KEEP = frozenset(
    "de del della der den di da dos das du la le van von ten ter st y e "
    "jr sr ii iii iv v vi".split()
)

# Play-by-play vocabulary, in any case: the word, not a person ("yellow card",
# "Short pass from", "PENALTY KICK MISS"). One that is also somebody's name is
# still swapped where it sits in a name ("Short, Anna", "Anna Short").
WORDS = frozenset(
    """
    a about across after against all along an and area around as assist at
    attempt attempts awarded away back ball bar beam behind block blocked bottom
    box by card carries center chance chest chested clear clearance cleared
    close converted corner cross crossbar cut cuts day deep defender defensive
    deflected deflecting deflection direct down draw drawn drew end ended failed far
    feet field final finish first following foot footed for forward foul free
    from front gk goal goalie goalkeeper goals half hand head headed header high
    hit home in initial inside into kick kicked knee left line long low made
    middle miss missed near net no of off offside on one open or ot out outside
    over overtime own pass passed passes passing path penalty period play player
    post quick range rebound received recovered red right rush save saved scored
    scores second shootout short shot shots side sliding spot start steal sub
    substitution takeaway tapped team ten the third through throw to top two under
    unknown
    var volley wide win wing with woodwork yards yellow
    """.split()
)

# Name fields that name no person: the box score's team line.
SENTINELS = frozenset({"team"})

# Invented tokens never contain these: famous names and words nobody wants
# printed as a student's name.
BLOCKED = (
    "putin",
    "hitler",
    "stalin",
    "trump",
    "biden",
    "obama",
    "osama",
    "nazi",
    "satan",
    "anal",
    "anus",
    "rape",
    "nig",
    "fag",
    "slut",
    "whor",
    "porn",
    "cum",
    "cock",
    "dick",
    "puss",
    "tit",
    "sex",
    "kkk",
    "shit",
    "fuc",
    "kil",
    "dead",
    "dumb",
    "crap",
    "butt",
    "poo",
    "piss",
    "homo",
    "jew",
    "gay",
    "bitch",
    "bastard",
    "damn",
    "hell",
    "pedo",
    "isis",
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
    """The key a token is known by: the identity module's plain letters (so
    "Høihjelle" and "Hoihjelle" are one key), lower case, one apostrophe."""
    text = unicodedata.normalize("NFKD", token.replace("’", "'").lower())
    text = text.translate(_PLAIN_LETTERS)
    return "".join(c for c in text if not unicodedata.combining(c))


def _base(key: str) -> tuple[str, str]:
    """A possessive's surname and its suffix: "brannock's" -> ("brannock", "'s")."""
    if key.endswith("'s") and len(key) > 2:
        return key[:-2], "'s"
    return key, ""


def _plain(key: str) -> str:
    return key.replace("'", "")


def _kept(key: str) -> bool:
    return len(_plain(key)) <= 2 or key in KEEP


def _sentinel(value: str) -> bool:
    """A name field that names no person (a team save, an unnamed card)."""
    return fold(value.strip()) in SENTINELS


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

    def __init__(
        self,
        vocabulary: set[str],
        words: set[str] = frozenset(),
        people: set[str] = frozenset(),
    ):
        # Every full name the name fields hold, folded: "Drew Harding" in a
        # Harding match is still a person.
        self.people = {fold(n) for n in people}
        self.real = {_base(fold(t))[0] for t in vocabulary}
        # Team names, nicknames and abbreviations of the home: never a text-only
        # person, and never what an invented token is.
        self.words = set(words)
        avoid = {_plain(k) for k in self.real} | {fold(w) for w in words}
        used: set[str] = set()
        self.map: dict[str, str] = {}
        self.invented: set[str] = set()
        # fold_name(real) -> fold_name(invented), for key-sourced player ids.
        self.folded: dict[str, str] = {}
        self.conflicts: list[str] = []
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
                if (
                    cand not in used
                    and cand not in avoid
                    and not any(b in cand for b in BLOCKED)
                ):
                    break
            else:  # pragma: no cover - pools hold thousands per letter
                raise SystemExit(f"ran out of invented names for {letter!r}")
            used.add(cand)
            self.map[key] = cand
            self.map.setdefault(plain, cand)
        self.invented = set(self.map.values())

    def known(self, token: str) -> str | None:
        """The map key a token stands for, possessive or not; None if none."""
        key, _ = _base(fold(token))
        return key if key in self.map else None

    def token(self, real: str) -> str:
        key = fold(real)
        base, suffix = _base(key)
        new = self.map.get(base)
        if new is None:
            return real
        stem = real[: len(real) - len(suffix)] if suffix else real
        return _shape(new, stem) + (real[len(stem) :] if suffix else "")

    def name(self, text: str) -> str:
        if _sentinel(text):
            return text
        return TOKEN.sub(lambda m: self.token(m.group(0)), text)

    def text(self, text: str, protect: list[str]) -> str:
        """Free text: every person token swapped, the rest left as published."""
        out, last = [], 0
        for start, end, swap in _text_tokens(text, protect, self):
            out.append(text[last:start])
            tok = text[start:end]
            out.append(self.token(tok) if swap else tok)
            last = end
        out.append(text[last:])
        return "".join(out)

    def official(self, text: str) -> str:
        role, sep, who = text.partition(":")
        return role + sep + self.name(who) if sep else self.name(text)

    def url(self, url: str, new_name: str | None) -> str:
        m = ROSTER_SLUG.search(url)
        if m and new_name is not None:
            return url[: m.start(2)] + slugify(new_name) + url[m.end(2) :]
        # Any other shape (a PrestoSports bios/hare_alex_xyz page): swap every
        # name token in the path; veil() refuses the id it cannot swap.
        head, sep, path = url.partition("://")
        host, slash, rest = path.partition("/")
        if not slash:
            return url
        rest = re.sub(r"[A-Za-z]+", lambda t: self.token(t.group(0)), rest)
        return f"{head}{sep}{host}{slash}{rest}"


def slugify(name: str) -> str:
    plain = fold(name).replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def _spans(text: str, protect: list[str]) -> list[tuple[int, int]]:
    """Where the text names one of the match's teams. "Harding, Drew" is a
    person even in a Harding match, so a team spelling a comma follows is not
    one; neither is one a person token runs into ("Drew Harding")."""
    if not protect:
        return []
    pat = re.compile(
        "|".join(
            r"(?<!\w)" + re.escape(p) + r"(?![\w,])"
            for p in sorted(set(protect), key=len, reverse=True)
            if p
        )
    )
    return [(m.start(), m.end()) for m in pat.finditer(text)]


def _text_tokens(text: str, protect: list[str], names: NameMap):
    """(start, end, swap) for every token of a free text outside the match's
    team spellings. swap is True for a person token."""
    toks = [(m.start(), m.end(), m.group(0)) for m in TOKEN.finditer(text)]
    spans = _spans(text, protect)
    person = [names.known(t) is not None for _, _, t in toks]

    def inside(i: int) -> bool:
        s, e, _ = toks[i]
        for a, b in spans:
            if a <= s and e <= b:
                # A person token right before the team spelling makes it a
                # surname: "Shot by Drew Harding."
                j = next((k for k in range(len(toks)) if toks[k][0] == a), None)
                if j and person[j - 1] and text[toks[j - 1][1] : a] == " ":
                    prev = toks[j - 1][2]
                    if not _word(prev) or fold(f"{prev} {text[a:b]}") in names.people:
                        return False
                return True
        return False

    def neighbour_person(i: int) -> bool:
        for j in (i - 1, i + 1):
            if 0 <= j < len(toks) and person[j] and not _word(toks[j][2]):
                gap = text[min(toks[i][1], toks[j][1]) : max(toks[i][0], toks[j][0])]
                if gap.strip() in ("", ","):
                    return True
        return False

    for i, (s, e, tok) in enumerate(toks):
        if inside(i):
            continue
        if not person[i]:
            yield s, e, False
            continue
        if _wordlike(tok):
            # A play word (or a short ALL-CAPS abbreviation) that is also
            # somebody's name: the word, unless it sits
            # in a name ("Short, Anna", "Anna Short").
            followed_by_comma = text[e : e + 1] == ","
            yield s, e, followed_by_comma or neighbour_person(i)
            continue
        yield s, e, True


def _wordlike(tok: str) -> bool:
    """A play word, or a short ALL-CAPS abbreviation ("URI", "MCK", "OPSU")."""
    return _word(tok) or (tok.isupper() and 2 <= len(tok) <= 4)


def _word(tok: str) -> bool:
    """Play-by-play vocabulary, in any case but ALL CAPS of more than one letter
    is still a word ("GOAL", "Shot", "drew")."""
    return fold(tok) in WORDS


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
    return [n for n in names if n and not _sentinel(n)]


def _free_texts(doc: dict):
    for match in (doc.get("matches") or {}).values():
        protect = _protect_for(match)
        for s in match.get("scoring", []):
            if isinstance(s.get("description"), str):
                yield s["description"], protect
        for play in match.get("plays", []):
            if isinstance(play.get("text"), str):
                yield play["text"], protect


def team_words(docs: list[dict], extra: list[str] = ()) -> set[str]:
    """Every word of every team name, nickname and abbreviation the home holds."""
    out: set[str] = set()
    names = list(extra)
    for d in docs:
        for p in d.get("programmes") or []:
            if isinstance(p, dict):
                names += [p.get("name") or "", p.get("abbr") or ""]
        for match in (d.get("matches") or {}).values():
            for side in match.get("teams", []):
                names += [side.get("name") or "", side.get("abbr") or ""]
    for n in names:
        out.update(TOKEN.findall(n))
    return out


def vocabulary(docs: list[dict], words: set[str] = frozenset()) -> set[str]:
    """Every name token of every person: those the name fields hold, and those
    only a play or a description names ("Kesselring carries the ball"): a
    capitalised token that is not play vocabulary and not a team word."""
    vocab = {t for d in docs for n in _people(d) for t in TOKEN.findall(n)}
    known = {_base(fold(t))[0] for t in vocab}
    for d in docs:
        for text, protect in _free_texts(d):
            spans = _spans(text, protect)
            for m in TOKEN.finditer(text):
                tok = m.group(0)
                if any(a <= m.start() and m.end() <= b for a, b in spans):
                    continue
                key = _base(fold(tok))[0]
                if key in known or not tok[0].isupper() or _wordlike(tok):
                    continue
                if tok in words or _base(tok)[0] in words or _kept(key):
                    continue
                vocab.add(tok)
                known.add(key)
    return vocab


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
        was, now = fold_name(old), fold_name(new)
        seen = names.folded.setdefault(was, now)
        if seen != now:
            names.conflicts.append(
                f"{old!r} folds like a name already invented as {seen!r}, "
                f"but became {now!r}"
            )
        ref = row.get("player_ref")
        if isinstance(ref, dict) and ref.get("source") == "key":
            slug, sep, rest = str(ref.get("id", "")).partition(":")
            folded, sep2, number = rest.rpartition(":")
            if sep and sep2 and folded == was:
                ref["id"] = f"{slug}:{now}:{number}"
                ref["_rekeyed"] = True
    if isinstance(row.get(url_key), str):
        row[url_key] = names.url(row[url_key], new)


def rekey(doc: dict, names: NameMap) -> list[str]:
    """Re-fold the key-sourced player ids (programme:foldedname:number) a line's
    own name did not; return those no name in the home folds to."""
    missed: list[str] = []
    for match in (doc.get("matches") or {}).values():
        for side in match.get("teams", []):
            for k in ("players", "keepers"):
                for p in side.get(k, []):
                    ref = p.get("player_ref")
                    if not isinstance(ref, dict) or ref.get("source") != "key":
                        continue
                    if ref.pop("_rekeyed", False):
                        continue
                    slug, sep, rest = str(ref.get("id", "")).partition(":")
                    folded, sep2, number = rest.rpartition(":")
                    if not (sep and sep2):
                        missed.append(
                            f"key id {ref.get('id')!r} is not slug:name:number"
                        )
                    elif folded in names.folded:
                        ref["id"] = f"{slug}:{names.folded[folded]}:{number}"
                    else:
                        missed.append(f"key id {ref['id']!r} folds no name in the home")
    return missed


# -- what is left of the real names --------------------------------------------


def residue(doc: dict, names: NameMap) -> list[str]:
    """Every real token still where a person is named."""
    left: list[str] = []
    real = names.real - {k for k in names.real if _kept(k)}

    def look(text: str, where: str) -> None:
        for t in TOKEN.findall(text):
            key, _ = _base(fold(t))
            if key in real and _plain(key) not in names.invented:
                left.append(f"{where}: {t!r} in {text!r}")

    for name in _people(doc):
        look(name, "name")
    for url in _person_urls(doc):
        look(
            re.sub(r"[^A-Za-z]+", " ", url.partition("://")[2].partition("/")[2]), "url"
        )
    for text, protect in _free_texts(doc):
        for s, e, swap in _text_tokens(text, protect, names):
            tok = text[s:e]
            key = names.known(tok)
            if key is not None and swap and _plain(key) not in names.invented:
                left.append(f"text: {tok!r} in {text!r}")
            elif (
                key is None
                and tok[0].isupper()
                and not _wordlike(tok)
                and _plain(_base(fold(tok))[0]) not in names.invented
                and tok not in names.words
                and _base(tok)[0] not in names.words
                and not _kept(_base(fold(tok))[0])
            ):
                left.append(f"text: unknown {tok!r} in {text!r}")
    return left


def _person_urls(doc: dict) -> list[str]:
    urls = []
    for team in (doc.get("rosters") or {}).values():
        urls += [p.get("source_url") for p in team.get("players", [])]
    for team in (doc.get("teams") or {}).values():
        for k in ("players", "keepers"):
            urls += [p.get("bio_url") for p in team.get(k, [])]
    for match in (doc.get("matches") or {}).values():
        for side in match.get("teams", []):
            for k in ("players", "keepers"):
                urls += [p.get("bio_url") for p in side.get(k, [])]
    return [u for u in urls if isinstance(u, str)]


# -- page ids and hometowns ------------------------------------------------------
#
# A name alone is not the whole person: a school's bio page id (in a roster or
# bio URL, a stats `player_id`, a box-score `player_id` or a page/twin/roster
# `player_ref.id`) opens the real bio, and a hometown narrows a roster line to
# one real player. Both are swapped too, one-to-one, so every join on an id
# still holds. Shirt numbers stay.

_TOWN_HEADS = [
    "Ash",
    "Bram",
    "Cold",
    "Dun",
    "Elm",
    "Fen",
    "Glen",
    "Hollow",
    "Iron",
    "Juniper",
    "Kest",
    "Lark",
    "Marrow",
    "North",
    "Oak",
    "Pine",
    "Quarry",
    "Red",
    "Sable",
    "Thorn",
    "Upper",
    "Vale",
    "Wil",
    "Yarrow",
    "Alder",
    "Birch",
    "Cinder",
    "Drift",
    "Ember",
    "Flint",
    "Gull",
    "Heron",
    "Ivy",
    "Kettle",
    "Lantern",
    "Moss",
    "Nettle",
    "Otter",
    "Pebble",
    "Rook",
    "Slate",
    "Tallow",
    "Wren",
]
_TOWN_TAILS = [
    "ford",
    "ville",
    "ton",
    "dale",
    "field",
    "burg",
    "haven",
    "port",
    "wick",
    "mere",
    "stead",
    "brook",
    " Creek",
    " Falls",
    " Springs",
    " Hollow",
    " Bend",
    " Crossing",
    " Ridge",
    " Mills",
]


def _id_paths(doc: dict):
    """(row, key) for every person id a season file holds, and URL rows."""
    ids, urls = [], []
    for team in (doc.get("rosters") or {}).values():
        urls += [(p, "source_url") for p in team.get("players", [])]
    for team in (doc.get("teams") or {}).values():
        for k in ("players", "keepers"):
            for p in team.get(k, []):
                ids.append((p, "player_id"))
                urls.append((p, "bio_url"))
    for match in (doc.get("matches") or {}).values():
        for side in match.get("teams", []):
            for k in ("players", "keepers"):
                for p in side.get(k, []):
                    ids.append((p, "player_id"))
                    urls.append((p, "bio_url"))
                    ref = p.get("player_ref")
                    if isinstance(ref, dict) and ref.get("source") != "key":
                        ids.append((ref, "id"))
    ids = [(r, k) for r, k in ids if isinstance(r.get(k), str) and r[k]]
    urls = [(r, k) for r, k in urls if isinstance(r.get(k), str)]
    return ids, urls


def _hometowns(doc: dict):
    return [
        p
        for team in (doc.get("rosters") or {}).values()
        for p in team.get("players", [])
        if isinstance(p.get("hometown"), str) and "," in p["hometown"]
    ]


def _injective(real: list[str], make, size: int) -> dict[str, str]:
    """Map each real value to an invented one: hashed, probed, never real."""
    taken = set(real)
    out: dict[str, str] = {}
    for value in sorted(set(real)):
        i = int(hashlib.sha256(value.encode()).hexdigest(), 16)
        for step in range(size):
            cand = make((i + step) % size, value)
            if cand not in taken:
                break
        else:  # pragma: no cover
            raise SystemExit(f"ran out of invented values for {value!r}")
        taken.add(cand)
        out[value] = cand
    return out


def _new_id(n: int, real: str) -> str:
    if not real.isdigit():
        return f"x{n % 10**8:08d}"
    width = len(real)
    lo = 10 ** (width - 1) if width > 1 else 0
    return str(lo + n % (10**width - lo))


def _new_town(n: int, _real: str) -> str:
    head = _TOWN_HEADS[n % len(_TOWN_HEADS)]
    tail = _TOWN_TAILS[(n // len(_TOWN_HEADS)) % len(_TOWN_TAILS)]
    return head + tail


def veil(docs: list[dict]) -> list[str]:
    """Swap every person id and hometown town across a home's season files;
    return what is left of the real ones (empty when clean)."""
    rows = [_id_paths(d) for d in docs]
    real_ids = [r[k] for ids, _ in rows for r, k in ids]
    for _, urls in rows:
        for r, k in urls:
            m = ROSTER_SLUG.search(r[k])
            if m:
                real_ids.append(m.group(3).lstrip("/"))
    by_width = {}
    for v in real_ids:
        by_width.setdefault(len(v), []).append(v)
    id_map: dict[str, str] = {}
    for width, values in by_width.items():
        span = max(10**width - (10 ** (width - 1) if width > 1 else 0), 1)
        id_map |= _injective(values, _new_id, span)
    for ids, urls in rows:
        for r, k in ids:
            r[k] = id_map[r[k]]
        for r, k in urls:
            m = ROSTER_SLUG.search(r[k])
            if m:
                new = "/" + id_map[m.group(3).lstrip("/")]
                r[k] = r[k][: m.start(3)] + new + r[k][m.end(3) :]

    towns = [p for d in docs for p in _hometowns(d)]
    real_towns = [p["hometown"].split(",", 1)[0].strip() for p in towns]
    town_map = _injective(real_towns, _new_town, len(_TOWN_HEADS) * len(_TOWN_TAILS))
    for p, town in zip(towns, real_towns):
        rest = p["hometown"].split(",", 1)[1]
        p["hometown"] = f"{town_map[town]},{rest}"

    left: list[str] = []
    real_id_set, real_town_set = set(real_ids), set(real_towns)
    for d in docs:
        for url in _person_urls(d):
            if not ROSTER_SLUG.search(url) and re.search(r"/[^/]*\d[^/]*$", url):
                left.append(f"url {url!r} carries a page id this cut cannot swap")
        ids, urls = _id_paths(d)
        left += [f"id {r[k]!r} is real" for r, k in ids if r[k] in real_id_set]
        for r, k in urls:
            m = ROSTER_SLUG.search(r[k])
            if m and m.group(3).lstrip("/") in real_id_set:
                left.append(f"url {r[k]!r} keeps a real id")
        for p in _hometowns(d):
            if p["hometown"].split(",", 1)[0].strip() in real_town_set:
                left.append(f"hometown {p['hometown']!r} is real")
    return left


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


def _programme_names(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out = []
    for row in (
        json.loads(path.read_text(encoding="utf-8")).get("programmes", {}).values()
    ):
        for k in ("name", "nickname", "abbreviation"):
            if isinstance(row.get(k), str):
                out.append(row[k])
    return out


def invent(home: Path) -> dict:
    """Swap every real person in a home's season files; refuse on any residue."""
    files = _season_files(home / "data")
    originals = {p: p.read_text(encoding="utf-8") for p in files}
    docs = {p: json.loads(s) for p, s in originals.items()}
    words = team_words(
        list(docs.values())
        + [
            json.loads(p.read_text())
            for p in sorted((home / "data" / "fixtures").glob("*.json"))
        ],
        _programme_names(home / "data" / "reference" / "programmes.json"),
    )
    people = {n for d in docs.values() for n in _people(d)}
    names = NameMap(vocabulary(list(docs.values()), words), words, people)
    left: list[str] = []
    for doc in docs.values():
        apply(doc, names)
    for path, doc in docs.items():
        left += [f"{path.name} {r}" for r in rekey(doc, names)]
        left += [f"{path.name} {r}" for r in residue(doc, names)]
    left += names.conflicts
    left += veil(list(docs.values()))
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
