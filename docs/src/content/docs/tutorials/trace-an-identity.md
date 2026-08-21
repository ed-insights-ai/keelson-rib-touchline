---
title: Trace an identity
description: "Hand-normalize real opponent strings, read adjudications with their game_id evidence, make an ambiguous alias refuse the build, and write one ruling that build-canon --check grades."
sidebar:
  order: 4
---

Every join downstream of the parser keys on identity: membership windows,
conference flags, every table in the digest. The last stop left you inside
a parsed page ([Read a page the way the parser does](../read-a-raw-page/));
this one follows the team strings it produced all the way down to canonical
slugs. [Identity](../../concepts/identity/) owns the why; this lab makes it
physical. You do the normalizer's job on paper, read the rulings humans
committed, break the alias index, and write one adjudication the system
itself grades.

By the end you can:

- normalize a raw opponent string on paper with the rewrite order of
  `normalize` in `pipeline/src/canon.py`, and predict its slug
- read an adjudication from the ledger and name the evidence that settled it
- tell a source artifact from an institution when the string tempts you the
  other way
- make `build-canon --check` pass with a ruling of your own and fail the
  moment its evidence note is stripped
- author a membership window that survives gap validation in
  `check-membership`

## What you need

- The Touchline package checkout and `uv`. Exercises 1 through 3 and 5 need
  nothing else.
- A data home holding the historical archive, loaded into Postgres, with
  its committed `data/reference/canon.json`. Each has its own source: the
  archive comes from `uv run scrape` or the project's existing data repo
  (the `scrape` entry in the
  [Pipeline CLI](../../reference/pipeline-cli/#scrape) is the contract),
  Postgres from the `load-db` step in
  [Rebuild from the archive](../../guides/rebuild-from-the-archive/), and
  the canon artifact from `build-canon`
  (`pipeline/scripts/build_canon.py`).
- `jq`, plus `psql` for one evidence lookup.

Work from the pipeline project unless a step says otherwise:

```sh
cd {package-dir}/pipeline
```

## 1. Try it: normalize three strings on paper

`normalize` in `pipeline/src/canon.py` is an ordered list of rewrites:
collapse whitespace, strip the rank-prefix grammar (`_RANK_PREFIX` covers
"#9", "No. 23", "RV", "(3)", "[7]", "3-seed", slash-joined and stacked
forms; the comment above it warns that leaving one in "mints an identity
that drifts with the poll"), strip a trailing source code ("NU", "OK",
"OKLA."), strip a trailing "Un"/"Univ"/"University" fragment, expand
an "Okla." token to Oklahoma and a "St." token to State (each with or
without its dot), then casefold. Apply the rewrites by hand to three
spellings the archive really serves, writing down each normalized key and
the slug you expect the alias index to return:

- `Newman  NU`
- `(3) Fort Hays St.`
- `Northwestern Okla St`

Check yourself: your three keys and slugs match the resolver's; verify with
this command:

```sh
uv run python -c "from src.canon import normalize, resolve
for s in ('Newman  NU', '(3) Fort Hays St.', 'Northwestern Okla St'):
    print(repr(normalize(s)), '->', resolve(s)['institution_slug'])"
```

## 2. Try it: read two rulings and their evidence

Some strings no grammar can decide, and for those the `ADJUDICATIONS`
ledger in `pipeline/src/canon.py` holds committed human rulings. `resolve`
consults it first, on the raw string exactly as published, before the alias
index ever sees the normalized key. Read the ruling for "OU" out of the
built artifact:

```sh
jq '.opponents["OU"]' {data-home}/data/reference/canon.json
```

The classification is `non_member`, and the note cites the proof: Ozarks of
Arkansas, not Oklahoma and not Ouachita, on the evidence of `game_id`
8202103. Now read "Southwestern", a ruling whose evidence is context rather
than a single game: every source row carrying it occurs in SWOSU context on
swosuathletics.com. Note what the grammar alone would have done: its
normalized key sits in no alias set, so without the ruling a conference
member's own matches would have filed under `non_member`.

Check yourself: both rulings are flagged adjudicated and carry a non-empty
evidence note; verify with this command:

```sh
jq -r '.opponents["OU", "Southwestern"]
  | [.classification, (.adjudicated | tostring), .note] | @tsv' \
  {data-home}/data/reference/canon.json
```

## 3. Try it: the decoy

The ledger's third answer is `artifact`: a token the source system minted
that names no institution at all. The model entry is "NWOSU18", ruled
artifact with the note "Season-tagged context-only team code; evidence:
game_id 8201807". The string exists only as a label in that game's context
rows; no school publishes under it.

Now the decoy. Resolve `UAPBWS17` in your head first. It reads like a real
school (Arkansas-Pine Bluff, women's soccer, 2017), which makes
`non_member` the tempting call. Then check the ledger: the committed ruling
is `artifact`, on the same grounds as the model, a season-tagged
context-only team code with its own cited game. The contract backs the
distinction mechanically: `validate_document` in
`pipeline/scripts/build_canon.py` requires every artifact note to name a
`game_id`, and refuses any artifact that carries a slug.

Check yourself: your classification agrees with the committed one; verify
with this command:

```sh
uv run python -c "from src.canon import resolve; print(resolve('UAPBWS17'))"
```

## 4. Try it: grade the committed artifact

`build-canon --check` re-measures the team-string universe from the five
source columns in Postgres, then validates the committed artifact against
it without rewriting anything: bidirectional key parity (nothing measured
missing, nothing stale retained), the note contracts from exercise 3, no
normalized key crossing identities, agreement with the code's ledger, and
two regression sentinels.

```sh
TOUCHLINE_DATA_DIR={data-home} uv run build-canon --check
echo "exit $?"
```

```
covered {n}/{n}, adjudicated {n}, institutions {n}, non-members {n}, artifacts {n}
exit 0
```

Check yourself: exit 0, with the same count on both sides of the covered
slash; verify with the command above.

## 5. Try it: make ambiguity refuse the import

The alias index is inverted from `ALIASES` at import time, and
`_build_alias_index` raises the moment one normalized alias maps to two
slugs. Prove it on a scratch copy:

```sh
cp src/canon.py {scratch}/canon-collision.py
```

Open `{scratch}/canon-collision.py` and add `"Harding"` to the `newman`
set in `_RAW_ALIASES`, then execute the copy:

```sh
uv run python {scratch}/canon-collision.py; echo "exit $?"
```

```
ValueError: normalized alias 'harding' maps to 'harding' and 'newman'
exit 1
```

In the real module that line runs at import, so every pipeline command that
touches identity is dead until the collision is resolved. Ambiguity is a
build failure with a named collision, never a runtime coin flip.

Check yourself: the copy exits nonzero naming both slugs; verify with the
run command above.

## 6. Try it: write a ruling the system will grade

The house format is the ledger's: a classification, an institution slug or
`null`, and a note that cites evidence, either a `game_id` or the source
context of every row. Stage a ruling of your own on a scratch copy of the
artifact:

```sh
mkdir -p {scratch}/identity/data/reference
C={scratch}/identity/data/reference/canon.json
cp {data-home}/data/reference/canon.json "$C"
jq -r '.opponents | to_entries[] | select(.value.adjudicated | not)
  | select(.value.classification == "non_member") | .key' "$C" | head
```

Pick one raw string from that list, then find its evidence in the archive:

```sh
psql "postgresql://lume@localhost:5432/touchline" -tc \
  "SELECT game_id FROM games
     WHERE home_team = '{raw-string}' OR away_team = '{raw-string}'
   UNION SELECT game_id FROM game_events WHERE team = '{raw-string}'
   LIMIT 3"
```

Write the ruling in the house format and run the grader:

```sh
jq '.opponents["{raw-string}"] += {adjudicated: true,
  note: "{who-this-is}; evidence: game_id {game-id}."}' "$C" \
  > "$C.tmp" && mv "$C.tmp" "$C"
TOUCHLINE_DATA_DIR={scratch}/identity uv run build-canon --check; echo "exit $?"
```

Exit 0: your ruling is in contract. Now strip the evidence and watch the
contract notice:

```sh
jq '.opponents["{raw-string}"].note = null' "$C" > "$C.tmp" && mv "$C.tmp" "$C"
TOUCHLINE_DATA_DIR={scratch}/identity uv run build-canon --check; echo "exit $?"
```

```
build-canon failed: '{raw-string}' is adjudicated without an evidence note
exit 1
```

A permanent ruling lands in `ADJUDICATIONS` in `pipeline/src/canon.py` and
is rebuilt into the artifact; the scratch staging you just did exercises
the same contract `--check` holds a committed one to.

Check yourself: exit 0 with your note in place, exit 1 naming your string
with the note nulled; verify with the two check runs above.

## 7. Try it: author a membership window

Identity says who. Membership says which conference held them, season by
season, as dated windows of `{conference, from_season, to_season, source}`
validated by `validate` in `pipeline/src/membership.py`
([Season is a dimension](../../concepts/season-and-membership/) is the
essay). Copy the artifact into your scratch home and baseline it:

```sh
cp {data-home}/data/reference/membership.json {scratch}/identity/data/reference/
TOUCHLINE_DATA_DIR={scratch}/identity uv run check-membership; echo "exit $?"
```

Now open the scratch copy, pick one programme window spanning several
seasons, and split it in two, leaving exactly one season uncovered between
the halves. Re-run the check:

```
check-membership failed: {slug}:{gender} has membership gaps at seasons [{year}]; cover them explicitly with an independent or non_member window
exit 1
```

The validator will not infer what filled the hole. Author it: add a window
for the missing season with `"conference": "independent"` and a non-empty
`source` line, and the check passes again. Then watch the season change
the answer:

```sh
TOUCHLINE_DATA_DIR={scratch}/identity uv run python -c "from src.membership import conference_for
print(conference_for('{slug}', '{gender}', {gap-season}))
print(conference_for('{slug}', '{gender}', {season-before-gap}))"
```

Check yourself: the gap year prints `independent`, the year before prints
`GAC`, and the check exits 0; verify with the two commands above.

## Next stop

Identity settled, the numbers can start: every digest table you are about
to recompute joins on the slugs you just traced. Read
[The determinism boundary](../../concepts/the-determinism-boundary/) and
[Absence is data](../../concepts/absence-is-data/) on the way. Next stop:
[Interrogate the digest](../interrogate-the-digest/).

## Related

**Run it**

- [Audit the data](../../guides/audit-the-data/): the standing checks that
  hold the canon and membership artifacts.
- [Onboard a school](../../guides/onboard-a-school/): where a new
  programme's aliases and membership windows enter the configuration.

**Understand it**

- [Identity](../../concepts/identity/): the full resolution story, and the
  one fuzzy match the system permits.
- [Season is a dimension](../../concepts/season-and-membership/): why
  membership is dated, cited windows rather than a school attribute.
