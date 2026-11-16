---
title: "Identity: resolving who is who"
description: "How a raw team string becomes a canonical slug: a rank-stripping grammar, exact alias matching, committed adjudications, and a resolver that refuses to guess."
sidebar:
  order: 5
---

The same programme reaches the pipeline under many spellings. Southwestern
Oklahoma State arrives as "SWOSU", "Southwestern Okla.", "SW Oklahoma State",
and, on a ranked week, "#9 SWOSU". Every downstream join keys on identity:
membership windows, conference flags, the digest's tables. So Touchline
resolves every team string to one canonical **institution slug**, without
similarity scoring: identity here is a grammar, an exact-match index, and a
ledger of committed human rulings. No fuzzy comparison exists anywhere in
the system. This page follows the rib's
**entity resolution** story from raw string to slug.

## A rank is not a name

The live collector mints slugs from published opponent strings, and a poll
rank moves week to week. Leave it in the name and every rank change mints a
fresh identity: the archive once held `no-4-csu-pueblo` beside
`no-15-csu-pueblo` for one school. The fix is `_RANK_PREFIX` in
`pipeline/src/sidearm_live.py`, a grammar built from the forms sites actually
publish: a poll rank with or without a marker ("#9", "No. 23", a bare "9"),
"RV" for receiving votes (a rank carrying no digits, which every numeric
pattern missed), a seed bracketed either way ("(3)", "[7]"), a seed spelled
as a word ("3-seed", "5th-Seed"), any of these slash-joined ("RV/#11"), and
any of these stacked in front of another.

Two limits keep the grammar from eating real names: a rank value stops at
two digits, and every token must be followed by whitespace. That is why
"5th-Seed Oklahoma Christian" loses the seed and keeps the school.
All-caps abbreviations such as "UT Tyler", the thing that actually leads an
opponent string most often, carry no rank value at all and never match.
`pipeline/src/canon.py` compiles the same grammar under its own
`_RANK_PREFIX`, with a comment binding the historical normalizer to stay in
step with the live collector's rank handling.

## Two normalizers, two universes

Normalization is a **canonicalization grammar**: an ordered set of rewrites
that erase presentation noise without erasing identity. The rib carries two,
because their failure costs differ.

`normalize` in `pipeline/src/canon.py` serves the historical archive. It
collapses whitespace, strips the rank prefix, strips trailing source codes
and trailing "Univ"/"University" fragments, expands "Okla." to Oklahoma and
"St." to State, then casefolds. It can afford the unconditional "St."
expansion because its output is only ever an exact-lookup key into a closed
alias index: a mangled string that matches nothing simply falls through to
`non_member`, and no identity is created.

`_identity_key` in `pipeline/src/sidearm_live.py` serves the live path, where
an unmatched key becomes the slug itself. There a bad rewrite becomes a
permanent identity, so "St." is handled by position: trailing, it abbreviates
State ("Northeastern St."); before another word, it abbreviates Saint
("St. Edward's"). The docstring records why: expanding it to State
unconditionally corrupted every Saint school in the archive. Parentheticals
are dropped entirely, because sites use them for both a region and a
match-type annotation, and neither belongs in an identity.

In record-linkage terms the normalized string is a **blocking** key. Two
records can only ever meet through exact equality on it. There is no
pairwise similarity pass anywhere in the resolution path.

## The alias index fails the build, not the join

`ALIASES` in `pipeline/src/canon.py` maps each slug to a frozenset of
normalized spellings, and `_build_alias_index` inverts it at import time,
raising `ValueError` the moment any normalized alias maps to two slugs. That
is an **import-time invariant**: an ambiguous alias is a build failure with a
named collision, never a runtime coin flip decided by iteration order.

The test suite extends the invariant to the ledger.
`pipeline/tests/test_canon.py` requires every adjudication to carry an
evidence note, holds a battery of observed source spellings (every published
rank form included) to their expected normalized keys and slugs, and asserts
the alias sets stay disjoint after normalization. A ruling without evidence,
or an alias that drifts onto two identities, fails the test run rather than
the join.

## Aliases are scoped by gender

Opponent strings carry no gender, so `identity_aliases` in
`pipeline/src/sidearm_live.py` builds the alias map for one gender's
collection at a time, from each configured school's name, abbreviation, and
per-stanza aliases. The docstring records the incident this guards against:
with an unscoped map, "Southwestern" on a men's schedule resolved to
Southwestern Oklahoma State, a school that fields no men's soccer, and a
platform audit found the same class of error in the historical derivation
when it ran gender-blind. Scoping the map is cheaper than detecting the
corruption afterwards.

## Aliases are scoped by NCAA level

A collect also resolves only against the stanzas of one NCAA level: the
level (`conference_profiles[code].level` in `membership.json`) of the
conference it collects, for the season it collects. Division I and
Division II share names and name tokens, and one table across both hands
one level's text to the other's programmes. Measured 2026-11-15 by loading
214 Division I men's programmes beside the Division II stanzas and replaying
all 2,313 archived Division II schedule pages: one unscoped table re-pointed
155 fixture-sides on 136 pages ("Penn State Abington" folded onto Penn State
by the token-subset fallback, "North Carolina Wesleyan" onto North
Carolina, "Queens" onto Queens of Charlotte), and the reverse holds on a
Division I page ("California" read as California (Pa.), "Notre Dame" as
Notre Dame College). Scoped, the same replay differs on 0 pages.

`membership.resolution_stanzas` is the one place the scope is decided, and
`collect_identity` in `scripts/collect_board.py` builds the identity map
and the `ResolutionScope` (member claims, member-only aliases, the distance
tiebreak, and so `ncaa_side`) from it. A programme's level in a season is
the level of the conference its window for the season names
(`membership.programme_level`): a reclassifier with a Division II window
through 2023 and a Division I window from 2024 sits in the Division II
table for 2023 and the Division I table for 2024. A season no level-bearing
window covers (before the first window, after the last, or a structural
`independent`/`non_member` window) takes the level of the latest such
window before it, else the earliest after it, which is what keeps every
Division II table exactly what it was before levels existed. Text naming a
school at another level is not resolved across levels: it mints its slug
from the text, as text naming an unknown school does. The schedule parse
fingerprint hashes the scoped map, and tournament headers are read against
the collecting level's conferences only, so adding another level's
stanzas or conferences re-reads none of this level's archive.

`check-membership` refuses an identity key two stanzas of one gender claim
only when they share a table: one level in one season. "Charleston" may be
the West Virginia school's name in Division II and the College of
Charleston's alias in Division I; "Boston" claimed by both Boston College
and Boston University (the fold drops "college" and "university") is
refused, naming the scope ("identity collision (men, d1, seasons
2016-2026)"). Programme slugs stay unique across every level: two enabled
stanzas of one gender may never mint the same slug.

## The collecting conference's members come first

A collect also resolves inside the conference-season it is reading for:
when a printed name folds to more than one programme, a member of the
collecting conference in that season is preferred over every other
programme, and a name no member claims resolves exactly as before. The
member set is the membership resolver's (`conference_members`, read from the
windows in `membership.json`), never a conference literal, and one
`ResolutionScope` built from it in `collect_board.py` applies to every row
of every page in the collect, conference and non-conference alike. The case
that forced it (tl-b3v): PacWest peers print "Dominican" for Dominican of
California and "Concordia" for Concordia Irvine, and the gender-wide map
read the first as the CACC's Dominican, whose whole name it is, so each
match landed in the PacWest file twice under two slugs. Such a short name
is a stanza's `member_aliases` entry, a spelling that enters no gender-wide
map and resolves only while the programme is a member of the collecting
conference; `check-membership` refuses one that a fellow member also claims,
and `display_name` still plays no part. Each printed text the scope
re-points is named once in the run log ("resolution: 'Dominican' read as
dominican-of-california, a PACWEST 2025 member, not dominican").

When a printed name is ambiguous, folding to one programme's name or aliases
and to another's `member_aliases`, and no member of the collecting conference
claims it (a CCAA page printing "Dominican" for a non-conference game against
Dominican of California), the claimant whose `programmes.json` point is
nearest the collecting school's wins, by great-circle distance; if the
collecting school or any claimant has no point, the gender-wide rule answers
as before, and a name with a single claimant is never touched. Each such
re-point is logged once per printed text with both candidates and their
distances ("resolution: 'Dominican' on cal-state-east-bay's page read as
dominican-of-california (53 km) over dominican (4,107 km)").

## Adjudication: the human in the loop

Some strings no grammar can decide. "OU" could be Oklahoma, Ouachita, or
neither. For these the `ADJUDICATIONS` ledger in `pipeline/src/canon.py`
holds committed human rulings, each keyed on the raw string exactly as
published and each carrying an evidence note. The strongest notes cite a
`game_id` or the source context in which every occurrence appears; the
plainest record the identification that settles the string. "OU" is
adjudicated to Ozarks of Arkansas, not Oklahoma, on the evidence of a named
game. "Southwestern" resolves to SWOSU because every source row carrying it
occurs in SWOSU context on swosuathletics.com. This is **human-in-the-loop**
resolution done as data engineering: the ambiguity is ruled on once, the
ruling cites its evidence and is committed where review and the test suite
can hold it, and nothing is patched silently in the parse path.

`resolve` applies the layers in a fixed order: the ledger first, on the raw
string; the alias index second, on the normalized string; and a default of
`non_member` last. An adjudication therefore always outranks the grammar.

Observe it: from `pipeline/`, run
`uv run python -c "from src.canon import resolve; print(resolve('OU'))"`
and read a committed ruling, with the `game_id` from the archived 2021
season that settled it.

## A closed world with three answers

`resolve` returns an exhaustive classification, typed in
`pipeline/src/canon.py` as the `Classification` literal: `institution_slug`
(a tracked GAC institution), `non_member` (a real school outside scope), or
`artifact` (a source-system token that names no institution at all, such as a
season-tagged code or a truncated context label). Every measured string gets
exactly one of the three: there is no "unknown" bucket to quietly absorb
mistakes.

## The refusal to guess

`opponent_slug` in `pipeline/src/sidearm_live.py` is where **abstention**
becomes mechanism. After the exact key lookup fails, the fallback is
deliberately conservative: a configured school matches only when every token
of one of its multi-token aliases appears in the published string, and only
when it is the unique school to do so. A one-token alias never matches on its
own, because a bare prefix is not an identity: "Southwestern" sits inside
"southwestern oklahoma state", and a substring test would collapse the two.

When nothing matches, the normalized key becomes the slug. That alone folds
"Delta St." onto "Delta State" without any lookup table. But "DBU" stays
apart from "Dallas Baptist" on purpose: no algorithm should guess that
expansion, and guessing is exactly what produced the Southwestern defect
above. An unresolved string remains visibly itself rather than silently
joining the wrong entity; in the historical universe the ledger then rules
on it.

## No fuzzy matching anywhere

There is no similarity scoring in the resolution path, and no longer any
fuzzy comparison anywhere in the system. (The retired box-score lineage
carried one bounded exception, a city-typo check used only to decide
neutral-site venues, and it retired with that lineage.) Two strings meet
only through exact equality on a normalized key, through an alias set, or
through a committed ruling. Institutions are never fuzzy-matched: a string
that resolves to nothing stays visibly itself instead of being scored onto
its nearest neighbour.

Lab: [Trace an identity](../../tutorials/trace-an-identity/) follows a raw
string through every layer on the real data home.

## Related

**Run it**

- [Onboard a school](../../guides/onboard-a-school/): where a new school's
  aliases enter the configuration.
- [Audit the data](../../guides/audit-the-data/): run the standing checks
  that grade what the identities feed, layer against layer.

**Understand it**

- [Reading hostile HTML](../reading-hostile-html/): where the raw team
  strings come from, and why they arrive malformed.
- [Season is a dimension](../season-and-membership/): what a resolved slug is
  joined against once identity is settled.
