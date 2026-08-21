---
title: Gate after every generative step
description: The founding incident, and the decision that a model's claim of completion is a request to be checked, enforced by mechanical loop exits and validation gates.
sidebar:
  order: 2
---

## The founding incident

Early in the prototype, asked to extend the research pool, the loop
announced completion with three of seven programmes still missing their
coach entries, and its design let the declaration end the work:
saying "done" made it so. The fix was structural, not a sterner prompt.
This page is the record of that decision; the machinery it produced is the
subject of
[The model declares, the validator decides](../../concepts/gates/).

## Decision

A model's claim of completion is a request to be checked, never a result.
Every generative stage that feeds the briefing in
`workflows/touchline-report.yml` is followed by a deterministic check that
can stop the run, and the check has the last word: completion is recounted
from the filesystem, stages pass on exit codes, and a briefing ships only
when no gate could prove it incomplete.

## Mechanism

Two layers, both in `workflows/touchline-report.yml`.

**Loops verify: completion is recomputed from disk.** After every
iteration, the research loop's `until_bash` check recomputes completion
instead of waiting for a declaration: it reads the programme count from
`data/scratch/digest-{season}-{gender}-{focus}.json` with `jq`, counts the
`research-{slug}.json` files carrying a top-level `coach` object, and ends
the loop only on full coverage. The verify and opponent-card loops add
staleness to the same check: each per-programme file must exist and be newer
than the digest (the shell's `-nt` test), and the digest is rebuilt every
run, so last week's `verified-{slug}.json` cannot satisfy today's loop.

**Gates anchor: the declaration is still checked.** The loop keeps one
text exit: an iteration that replies "ALL RESEARCHED" ends the stage
immediately, on the model's say-so. So a deterministic gate recounts
everything behind the loop. `validate-research`
walks every programme in the digest and fails the run when any lacks a
research file or a coach object with a legal status; its ALARM line names
each offender with its reason, `{slug}(no-file)` or `{slug}(no-coach)`.
This is the gate that would have caught the founding incident. The
`validate-verified` gate counts the other side: the merged `verified.json`
must carry at least as many coach entries as research files carried coach
objects, so verification may downgrade a coach to "unknown" but can never
quietly erase a programme. The same pattern continues through
`validate-narrative`, and the full contract is catalogued in
[Gates and exit codes](../../reference/gates-and-exit-codes/).

## Rejected alternatives

- **Trusting self-report.** The obvious patch was firmer prompt language,
  and it would fail the same way, only later. The research prompt still
  orders the model to run a `jq` check before replying, because the reply
  can end the stage: the prompt makes the honest exit cheap, and the gate
  behind the loop makes the dishonest one fatal. Prompts steer; only gates
  guarantee.
- **Retry until plausible.** Regenerating a failed stage until its output
  passes converges on whatever sneaks past the check, not on truth, and it
  buries the structural cause a human needs to see: a source that never
  published, an unreadable digest, a prompt defect. The loops keep the
  honest form of retry: bounded iterations, capped by `max_iterations`,
  that finish work counted on disk.
- **Human spot checks.** A human diff catches an omission once; a gate
  catches it on every run. The workflow fans research out across a whole
  conference and reruns for every briefing, so an invariant has to be
  checked at machine speed, every time. What a spot check does find becomes
  a rule or a gate, not a routine.

## Failure semantics

A tripped gate fails the run with a named reason: an ALARM line stating
exactly what is missing, then exit 1. Nothing downstream runs, and no gate
ever patches the output it judged. The merge nodes that do write,
`merge-verified` and `assemble-narrative`, validate every input with
`jq -e` and write through a temp file and `mv -f`, so a failed run never
leaves a half-merged output behind. A gate that repaired output would
convert a detected defect into a shipped one.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): drive the gated
  workflow end to end.
- [Gates and exit codes](../../reference/gates-and-exit-codes/): the terse
  contract for every gate, check, and code.

**Understand it**

- [The model declares, the validator decides](../../concepts/gates/): the
  machinery this decision produced.
- [Break a gate](../../tutorials/break-a-gate/): trip the gates on a
  scratch copy and read the alarms yourself.
