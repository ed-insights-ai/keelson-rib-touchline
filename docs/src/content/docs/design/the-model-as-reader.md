---
title: The model as reader, never a source
description: Every model contribution is prose over computed numbers or a finding bound to a fetched URL, and a refuted claim is downgraded on the record, never deleted.
sidebar:
  order: 3
---

## Decision

Ask a language model about a small-college soccer programme and it will
answer: training data has an opinion about everything, and the model cannot
feel the difference between recall and invention. So no contribution enters
Touchline on the model's authority. Everything a model writes takes one of
two admissible forms: prose over numbers the pipeline computed, or a finding
bound to a URL fetched during this run. The corollary is grade, never
delete: a claim that fails checking is downgraded on the record, with a
reason, and kept.

## Mechanism

The evidence side is `prompts/research-protocol.md`, a markdown contract
every research stage reads at runtime. It binds identity (a name match
alone is never a finding; every hit needs a corroborating attribute such as
school, hometown, club, or a photo caption naming the player), grades
sources (league and club official pages and local news are high; club
social posts and a player's own on-field posts are medium; crowd-sourced
databases are lead generation only, never confirmation), and refuses
undated evidence: an undated source cannot date a claim. Verdict and
confidence stay orthogonal axes. Fetching a player's own post yields
confirmed at medium: the fetch settles that the source says it, and the
tier never rises by being fetched.

The enforcement side is the `verify` loop in
`workflows/touchline-report.yml`, an adversarial pass that re-fetches every
finding's URL trying to refute the claim as written. What fails does not
vanish. A refuted finding leaves the printable pool and lands in the
`dropped` array with a named reason; a refuted coach claim keeps its
object, downgraded to status "unknown" with `since_season` nulled, and
stays in the coaches map. The `validate-verified` gate holds that as an
invariant: the merged `verified.json` must carry at least as many coach
entries as research files carried coach objects. Downstream, the narrative
writer is walled in. The `narrative-core` node's only source of numbers is
the digest and its only admissible news is `verified.json`. The rule
reaches the smallest contributions too: the run summary may not print a
figure absent from its upstream text, and the chat agent's system prompt in
`src/agent.ts` requires every reported figure to come from a tool result.

## Rejected alternatives

- **Model recall as a source.** A recalled claim carries no URL and no
  date, so the verify pass could never re-fetch it. Evidence the refuter
  cannot touch is not evidence, even when it happens to be true.
- **Deleting refuted findings.** The failed check is itself evidence: the
  `dropped` record names what failed and why, and the run summary reports
  it exactly as recorded, never softened. Deleting a refuted coach claim
  would also erase a programme from the coaches map, which
  `validate-verified` treats as a broken run.
- **A single quality scalar.** One score conflates "was this checked" with
  "who said it". The protocol's report-entry rule needs both axes: a
  confirmed claim at high confidence may appear in prose freely, while a
  confirmed-at-medium claim enters only with its source kind named in the
  sentence and never as the sole support for a decision or a major-news
  item. A scalar cannot carry that rule.

## Failure semantics

A claim without provenance does not exist. A claim believed true but not
capturable at a fetched URL goes to `attested_uncaptured`, a dead-letter
bucket that never reaches report prose in any form: not as fact, not as a
hedge, not as an uncertainty. It surfaces only in the run summary, for a
human to capture or discard. What the sweep could not reach at all is filed
in `unswept` with its reason, and `prompts/player-profile.md` keeps
confirmed, ruled out, and no indexed mention strictly apart
([Absence is data](../../concepts/absence-is-data/) owns the distinction).

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): the workflow that
  runs research, refutation, and narrative end to end.
- [Prompt contracts](../../reference/prompts-and-protocols/): the contract
  surface of every prompt file.

**Understand it**

- [Evidence, not recall](../../concepts/evidence-not-recall/): the full
  evidence standard, from finding to page.
- [Absence is data](../../concepts/absence-is-data/): why a recorded gap is
  a first-class result.
