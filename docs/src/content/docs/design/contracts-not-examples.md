---
title: Contracts beat examples
description: The exemplar leak, the cold-run test that measured the fix, and why the quality bar lives in written contracts and validators instead of sample reports.
sidebar:
  order: 4
---

## The exemplar leak

Early in the prototype, an exemplar report rode along with the generation
prompts as a quality reference: here is what good looks like. Its phrasing
leaked into every output. The fix was removal, not a better exemplar: the
sample was deleted entirely, and the quality bar moved into written
contracts and validators, which constrain without being copyable. Contracts
generalize; examples imprint.

## Decision

The report's quality bar is written as rules, never shown as samples. No
exemplar output travels with the prompts. `prompts/style-contract.md`
states how a report must read, `prompts/scouting-questionnaire.md` states
what it must answer, and the validators check what a script can check. A
model can obey a rule without copying it; it cannot study an example
without absorbing its phrasing.

## The evidence, dated August 2026

The acceptance test was to run the system where it was not tuned: same
prompts, same contract, same validators, same renderer, on three
programmes. Harding was the tuning subject, Fort Hays State the first cold
run, Newman the weakest published data. Measured in August 2026, the
cross-narrative 5-gram Jaccard overlap between any two of the three
briefings was 3.4 percent, and every shared 8-gram was a data artifact, a
source URL or a citation line, not template language. The contract
constrains form; it does not leak phrasing. Two gaps found in the
comparison runs became contract rules; the third run was clean.

## Mechanism

The bar lives in `prompts/style-contract.md`, in rules precise enough to
follow with nothing to copy:

- **The toolkit rule.** The page structure is a toolkit, not a template.
  Which decisions surface and which position groups get attention come
  from this team's numbers and verified findings at generation time; no
  report assumes a goalkeeper battle, a scoring gap, or any other
  storyline until the data shows it.
- **The anti-formula rules.** Consecutive items in one list must not share
  an opening verb or sentence shape. A concept named in a contract example
  ("performance after 60 minutes") applies only where this team's data
  flags it, because contract examples are illustrations, not required
  phrasing. Tier names never appear in prose. A watchlist draws from
  different evidence classes where the record offers them.
- **The generic-decision test.** A decision title that would sit unchanged
  in another team's report is under-specified; it is rebound to named
  players and this team's numbers until it could belong to no one else.
- **Cadence rules** that ban the tells of generated text: the
  claim-then-elaboration pivot as a default sentence shape, antithesis
  mirrored across consecutive sentences, aphoristic fragments as paragraph
  closers.

The workflow makes variance mechanical where it can: each `narrative-cards`
iteration in `workflows/touchline-report.yml` reads the `card-{slug}.json`
files already written and varies its opening and implication sentence shape
from the preceding cards. And what a script can check moved into a gate:
`validate-narrative` measures the contract's word budgets with `wc -w` and
greps the prose for the machinery words the contract bans.

## Rejected alternatives

- **Few-shot exemplar reports.** Tried; that is the leak. An exemplar can
  only show one team's answers, so its phrasing imprints on every subject.
- **Per-programme tuned prompts.** Tuning per subject would make every
  programme a special case and erase the one honest acceptance test, the
  cold run on a subject nothing was tuned for. One prompt set serving
  every programme is what makes the overlap figure above meaningful.

## Failure semantics

A gap found in a cold run becomes a contract rule or a gate check, never an
edit to the output. The briefing itself is not touched by hand: the fix
lands upstream, in `prompts/style-contract.md` or a validator in
`workflows/touchline-report.yml`, and the report is reproduced (see
[A briefing is a run, not a document](../a-briefing-is-a-run/)). A defect
fixed in the artifact dies with the artifact; a defect fixed in the
contract is fixed for every briefing after it.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): produce a briefing
  under the contract.
- [Prompt contracts](../../reference/prompts-and-protocols/): the contract
  surface, file by file.

**Understand it**

- [How a machine scouts a season](../system-narrative/): the full
  narrative, and the rest of the dated measurements.
- [Gate after every generative step](../gate-after-every-generative-step/):
  the sibling decision that gives the contracts their teeth.
