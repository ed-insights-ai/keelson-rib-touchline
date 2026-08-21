---
title: Evidence, not recall
description: The research protocol that makes the model a reader of fetched pages, never a source, with graded findings, identity binding, an adversarial verify pass, and bounded search.
sidebar:
  order: 8
---

Ask a language model about a small-college soccer programme and it will
answer. Training data has an opinion about everything, and the model
cannot feel the difference between recall and invention. So Touchline's
research stages hold one rule above every other:
**the model is a reader, never a source**. A fact enters the system only if
it was fetched at a URL during this run, bound to the right person, graded
by the kind of page that carried it, and then survived a second pass built
to refute it. The rules live in
`prompts/research-protocol.md`, a markdown contract every research stage
reads at runtime (report research and player profiles alike); the
gates in `workflows/touchline-report.yml` enforce what a prompt alone
cannot.

## A finding is a receipt

The unit of research output is the **finding**: one claim plus its source,
URL, date, and confidence grade. The report workflow's research
loop writes one file per programme at
`data/research/{season}-{gender}/research-{slug}.json` under the
`touchline.research/1` schema, and every entry in its `findings` array
carries `player`, `type`, `text`, `source`, `url`, `date`, and
`confidence`. A claim believed but not capturable at a URL is never
written as a finding; it goes to the dead-letter bucket below.
"Nothing found" for a player is a normal result, recorded plainly.

The protocol's one-finding-one-page rule shapes what a finding may say:
never write a claim whose truth needs two pages to check, because the
verify pass fetches each finding's single URL and drops anything that page
alone cannot support. Compound claims split. A coaching change becomes one
finding per page: the current staff directory names the new coach, the
appointment bio dates it, the prior year's directory names the
predecessor. When a single page states the whole fact, prefer that page.

## The right person

**Identity binding** is the false-positive rule: "discoverable but wrong"
is the pipeline's highest risk. A name
match alone is never a finding. Every hit must bind to the player through
at least one corroborating attribute: school, hometown, club, age or class
year, jersey number, or a photo caption or tag naming them. A face that
looks right is not evidence. Recency weights the anchor too: an identity
match on a current page is strong, while a hometown on a five-year-old
roster cannot by itself confirm a current-season claim. A hit that cannot
be bound is dropped or filed as attested-but-uncaptured, never stretched.

## Verdict and confidence are different axes

The protocol grades sources in `Source confidence and dating`. High means
league or club official pages, federation records, and local news. Medium
means club social posts capturable at a stable URL, and a player's own
public posts scoped to on-field activity and publicly announced athletic
status (health information never comes from personal accounts). Transfermarkt, Soccerway, and other
crowd-sourced databases are lead generation only, never confirmation, and
a null result in their thin lower-tier coverage means little.

The grade is one axis; the **verdict** (was the claim verified at a
fetched page) is the other, and the two never collapse. Fetching a
player's own transfer post raises the claim to confirmed at medium
confidence: the fetch settles that the source says it, but the tier still
says what kind of source it is, and it never rises by being fetched. A
successful fetch is evidence of publication, not of authority.

Time is graded the same way: **an undated source cannot date a claim**. A
social post or squad listing with no timestamp cannot establish a
current-season fact.

The grade decides what print may lean on. Under the protocol's report
entry rule, a confirmed claim at high confidence may appear in report prose
freely; a confirmed-at-medium claim enters only with its source kind named
in the sentence, and never stands as the sole support for a decision or a
major-news item. When official pages disagree, precedence resolves it (most
recent programme-published page, then conference pages, then older official
pages, then press) and the disagreement is recorded as a finding note: a
coach reading two class years deserves to know the record splits.

## A second pass tries to kill every claim

Research that grades itself is not enough, so the report workflow runs an
**adversarial verify pass**: the `verify` loop in
`workflows/touchline-report.yml`, one programme per iteration with a fresh
context, picking its target from the digest, then reading only that
programme's research file and the live web. Its
prompt re-fetches each finding's URL and checks the page supports the
claim as written: "You are trying to REFUTE each claim." What survives is
kept unchanged; a finding whose page cannot be fetched or does not support
the text lands in a `dropped` array with its reason, recorded, never
softened.

The head coach gets the downgrade-never-delete treatment. Coach status is a
mandatory, structured answer for every programme, recorded either way. When
the verify pass cannot support a coach claim it downgrades the status to
"unknown" and nulls the tenure, but the coach entry stays in the `coaches`
map. The `validate-verified` gate enforces the invariant: the merged
`verified.json` must carry at least as many coach entries as research
files carried coach objects. Verification can weaken a claim; it can never
silently erase a programme.

Verification also cannot go stale. A per-programme `verified-{slug}.json`
counts as done only while it is newer than the digest, and the digest is
rebuilt on every report run, so stale verification is never reused against
fresh numbers.

:::note
Neither loop trusts the model's say-so alone. An `until_bash` probe ends
each loop mechanically: coach objects counted on disk for research, fresh
per-programme files for verify. "ALL RESEARCHED" can still end the loop
early, so the `validate-research` gate recounts and fails the run instead.
The pattern is the subject of [Gates](../gates/).
:::

## Where the unusable goes

Two buckets keep unusable material out of prose but visible to humans.

`attested_uncaptured` is the dead-letter bucket: claims believed true but
not capturable at a fetched URL. It is a dead end for report content.
Claims there never reach the report in any form, not as fact, not as a
hedge, not as an uncertainty, and downstream stages must not treat the
bucket as soft evidence. They surface only in the run summary, for a human
to capture or discard.

`unswept` records the corners the sweep could not reach, with reasons: a
club that publishes no roster, a 403-blocked page, a social surface search
cannot see. `prompts/player-profile.md` sharpens the point with three
verdicts, never blurred: **confirmed** (fetched and
identity-bound), **ruled out** (the page was read and the name is absent,
the strong form of absence), and **no indexed mention** (the surface cannot
be seen at all, a finding about coverage, not evidence of absence). Why
gaps are first-class results is the subject of
[Absence is data](../absence-is-data/).

## Effort is budgeted

Search is bounded by explicit stopping rules, not the model's patience.
The club-first sweep stops for an anchor geography after five consecutive
clubs with no roster match; any query line stops when two consecutive
variants add nothing new. What was not swept is recorded in `unswept`
rather than searched indefinitely. The protocol's platform techniques
(direct post URLs, a Threads plain fetch, reading a roster-less club's
opponents) carry expected failure modes, and a failed technique files an
`unswept` entry, not an error.

## Only receipts reach the page

Downstream, the narrative writer is walled in by what survived. The
`narrative-core` node's inputs are the digest (its only source of numbers)
and `verified.json` (its only admissible news and offseason findings), and
its prompt closes the loop in the protocol's own terms: if it is not
discoverable, it is not in the report, and an undated source cannot date a
claim. The design record behind this standard is
[The model as reader](../../design/the-model-as-reader/).

Observe it: in a completed archived season's data home, open
`data/research/{season}-{gender}/verified.json` and read the `dropped`
array: each entry names a claim the refute pass killed, and why.

Lab: [Research with receipts](../../tutorials/research-with-receipts/)
runs a sweep against the real data home and audits its receipts.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): the workflow that runs this
  protocol end to end.
- [Prompt contracts](../../reference/prompts-and-protocols/): the
  contract surface of every prompt file.

**Understand it**

- [Absence is data](../absence-is-data/): the three verdicts, and why a
  recorded gap is a result.
- [Gates](../gates/): the validators that stop a run when research comes
  back out of contract.
- [The model as reader](../../design/the-model-as-reader/): the decision
  record behind this evidence standard.
