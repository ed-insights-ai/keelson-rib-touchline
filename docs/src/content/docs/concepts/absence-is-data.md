---
title: Absence is data
description: The four coverage states, named missing manifests, null-not-zero score semantics, and the complete-coverage licence an absence claim must earn.
sidebar:
  order: 6
---

Most data systems record what they found. Touchline also records what it did
not find, and why. An empty place in a data home is never just blank: it is a
named state in the coverage manifest, a named entry in a file's missing
manifest, or a null the schemas refuse to collapse into zero. This is the
system's signature idea, and the reason for it is trust. A reader who asks
"why is this cell empty?" and gets four different true answers on four
different days stops believing all of them. So Touchline never lets one kind
of empty impersonate another.

## Four kinds of empty

The docstring of `pipeline/src/coverage.py` names the three conditions a bare
directory listing cannot tell apart: not collected yet (nobody has asked), not
published yet (the source has not released it), and no collector exists (this
can never be served). "Conflating those is the fastest way to make a data
product untrustworthy, so they are recorded separately and rendered
separately."

The collector's vocabulary is one step finer. Every collection layer of every
programme lands in one of four states, the vocabulary of `LayerOutcome` in
`pipeline/src/sidearm_live.py`:

| State | Meaning | What travels with it |
|---|---|---|
| `complete` | Served, proven, and holds rows | `count`, `source_url` |
| `empty` | Served and proven, and genuinely holds nothing | a reason such as "proved its season but listed no players" |
| `unavailable` | Could not be collected | the `reason` says why, with the attempted URL when one was tried |
| `no-collector` | This programme's platform has no collector | the reason names the missing recipe |

The load-bearing word is *proven*. A page only earns `empty` after it passes
season proof; a page that cannot be proven to represent the requested season
raises `LiveCollectionError` and lands as `unavailable` with the error as its
reason. So `empty` always means the source itself is silent, never that the
fetch fell over. A schedule with zero fixtures in February and a roster page
the site has not built yet are different facts, and the manifest keeps them
different.

There is a fifth reading that needs no state at all: a cell absent from the
manifest is a question nobody has asked yet.

## The coverage manifest

The record lives at `data/coverage.json` under the schema tag
`touchline.coverage/1`. Each cell is keyed
`{season}/{gender}/{programme}/{layer}` by `cell_key` in
`pipeline/src/coverage.py`, and the collect run's `record` helper in
`pipeline/scripts/collect_board.py` stamps every cell with its `state`,
`confirmed_at`, and `collector`, plus `reason`, `count`, and `source_url` when
they exist.

Two write rules protect the record. `merge_cells` folds a run's cells into
whatever the home already holds, merged and never overwritten: "a run that
collects one programme must not erase the record of the twelve collected last
week." And `write_coverage` goes through a temp file and an atomic rename, so
an interrupted run cannot leave half a manifest.

## Named, never dropped

The season files carry their own absence records. Every file contract in
`src/model.ts` includes a `missing` manifest: the fixtures file names the
programmes whose schedule could not be collected, the rosters and stats files
name those whose page yielded nothing, and the matches file upgrades the
manifest to a record mapping each fixture id to the collector's named reason
for the gap.

The board treats those names as content. `src/board.ts` renders collection
gaps in a notice, "named rather than dropped", and a re-collect retries them.
Opening the drawer on a played fixture with no box score shows the exact
reason from the matches file's `missing` record rather than a shrug. The
season rail draws a hollow tick behind today for a match past its date whose
site still publishes no result, so an uncollected result and an unpublished
one stay distinguishable at a glance. And a published schedule and roster with
zero played matches gets its own notice declaring pre-season a valid state:
some kinds of empty are simply correct.

## Null is not zero

Scores in the fixture contract are nullable, "never 0, which is a real
scoreline" (`src/model.ts`). The distinction is not pedantry: `isPlayed` is
true whenever a site marks a fixture final, and at least one modern theme
publishes completion without ever entering a score, so anything
score-dependent guards on the numbers, never on played-ness alone. The
digest's `_counts` predicate in `pipeline/src/digest.py` applies the same
guard when aggregating: counting a score-less final "would invent a 0-0 draw,
a clean sheet, and a shutout at once."

Season statistics get the parallel rule. Every stat field in `src/model.ts` is
optional because a site prints what its stat crew recorded, and an absent
number means "not published", never zero. The collector says the same thing
in its payloads: a stat cell it cannot read is omitted from the player's
entry rather than written as zero, and a card whose color the page never
encodes is stored as `unknown` rather than guessed. The meaning of an
absent field is part of the contract, written where the next reader will
find it.

## Honest denominators

An aggregate built over partial coverage must say so. `match_patterns` in
`pipeline/src/digest.py` sends `matches_counted` and `played_total` along with
every pattern block, because box-score coverage can trail the fixture list and
a report has to caveat patterns built on part of a season. The same file's
`discipline` function picks its source by coverage shape: card totals come
from the season statistics page, which aggregates the whole season, not from
counting card events across held box scores, which cover only the matches that
were collected.

## Absence claims need a licence

"First season on this roster" is an absence claim: it denies every earlier
appearance, and "3rd season" denies a fourth. A skipped or unreadable archive
season could hide the very appearance the claim rules out. So
`priorRosterCoverage` in `src/board.ts` computes whether roster coverage runs
unbroken from the programme's first collected roster to the season before the
one shown, and complete coverage is the licence to make own-roster tenure
claims at all. NEW chips are gated on the identical check, because with no
history at all "new" would describe our records, not the squad.

Positive sightings need no such licence. "Previously at another programme" is
supported by the sighting itself, since a coverage gap can only hide more
appearances, never fewer. Under incomplete coverage the drawer degrades to the
recorded facts, listing the seasons a player was seen with no count and no
first-season claim.

## Ruled out is not unfound

The research side draws the same line for the model doing offseason work. The
rules of evidence in `prompts/player-profile.md` keep three verdicts apart:
**confirmed** (verified at a fetched, identity-bound URL), **ruled out** (a
specific page was read and the name is not there, the strong form of absence),
and **no indexed mention** (the surface cannot be seen: private accounts,
JS-only rosters, blocked pages). The third is a finding about coverage, not
evidence of absence, and it is recorded in `unswept` with its reason, per the
sweep and stopping rules in `prompts/research-protocol.md`. The distinction
carries downstream: a participation gap backed by ruled-out checks is a
stronger signal than one sitting on unswept coverage, and the research file
must say which the reader has. Evidence of absence must be gathered, exactly
like evidence of presence.

Observe it (read-only, under ten minutes): against a completed archived
season in your data home, run `jq -r '[.cells[].state] | unique[]' data/coverage.json`
and confirm every state is one of the four above, then run
`jq '.missing' data/matches/{season}-{gender}-{conference}.json` and read the
collector's named reason for each box score it could not fetch.

Lab: [Stand up a season](../../tutorials/first-season-board/) is the gap
chase: stand up a season, find every absence the board names, and trace each
one to its coverage cell and missing manifest.
[Interrogate the digest](../../tutorials/interrogate-the-digest/) works the
same discipline on the numbers side.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): the run that writes the coverage cells and missing manifests this page reads.
- [Audit the data](../../guides/audit-the-data/): the checks that keep recorded absence honest over time.
- [File contracts](../../reference/file-contracts/): the missing manifests and nullable fields, field by field.

**Understand it**

- [Season is a dimension](../season-and-membership/): absence must be authored there too; a membership gap is covered explicitly or the record fails validation.
- [Evidence, not recall](../evidence-not-recall/): the evidence standard the three research verdicts live under.
