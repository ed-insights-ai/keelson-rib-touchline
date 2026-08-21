---
title: A briefing is a run, not a document
description: The decision that the deliverable is reproduced by rerunning the circuit, never edited, with staleness enforced by timestamps against a rebuilt digest.
sidebar:
  order: 7
---

## Decision

The scouting briefing is the output of a run, and only a run. When new
results land or research goes stale, nobody edits the delivered document: the
same circuit reruns and produces a new one. Everything the report reads is
rebuilt or re-verified inside the run itself, so a briefing's date is its
provenance, and currency is a property of when the circuit last ran.

## Mechanism

The digest is rebuilt every run. The `digest` node of
`workflows/touchline-report.yml` executes `build-digest` into
`data/scratch/`, which the workflow's own comments label regenerable, and it
is the sole source of numbers for every stage downstream.

Staleness is measured against that rebuilt digest by file timestamp. The
verify loop's `until_bash` requires each `verified-{slug}.json` to exist and
be newer than the digest (the shell `-nt` test); `merge-verified` reruns the
same test and alarms on missing or stale files; the opponent-card loop and
`assemble-narrative` hold `card-{slug}.json` and `narrative-core.json` to the
identical check. Since the digest's timestamp belongs to this run, any
artifact not rewritten since is stale by construction. The verify prompt
states the intent plainly: the digest is rebuilt for every report run, so the
timestamp check prevents stale verification from being reused.

The delivered pair is kept. `assemble-narrative` merges the core and cards
into `data/reports/narrative-{season}-{gender}-{focus}.json`, and
`pipeline/scripts/render_report.py` renders the PDF beside it, removing each
HTML intermediate once its PDF lands. The numbers can be recomputed on any
future day; the model-authored prose that actually shipped cannot, since a
rerun writes new prose under the same contract. So the narrative file stays
next to the PDF it produced, as the record of that run.

One decision, two lanes. The freshness lane is built: a box score published
hours after the final whistle enters the archive on the next collect, the
digest recomputes, and the same gates produce a current assessment. Because
every store derives from the archive, up to date means rerun, never rebuild.
The learning lane is enabled but honestly future work: archived seasons
accumulate into a training substrate for predictive models, none of which
ship in the prototype, and any model trained there would enter the briefing
as one more graded, sourced finding, never oracle text. The framing is
section 08 of the [system-design narrative](../system-narrative/).

## Rejected alternatives

**A report repository with cached verification.** Reusing last run's
verified findings under a fresh digest was rejected because a verification is
dated evidence about a page at a fetch time, not a durable fact. The `-nt`
gates exist to refuse exactly this reuse.

**Editing stale documents.** Patching August's PDF by hand when a roster
finally publishes was rejected because an edited deliverable has no
provenance: no gate saw the edit, no digest backs its numbers, and the
narrative validators never ran against it. The cost of a rerun was
engineered down so that this temptation loses.

## Failure semantics

Stale verification stops the narrative, not the operator. `merge-verified`
and `assemble-narrative` exit nonzero naming the stale file,
`validate-narrative` never runs, and no report renders. The remedy is always
the same verb, rerun: each loop iteration picks the first programme whose
file is missing or not newer than the digest, so a resumed run redoes exactly
the stale work and no more. Nothing in the failure path invites a hand edit.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): drive the full gated run this page decides the shape of.
- [Workflows](../../reference/workflows/): the report DAG, node by node.

**Understand it**

- [The determinism boundary](../../concepts/the-determinism-boundary/): why the digest is the sole source of numbers.
- [Gate after every generative step](../gate-after-every-generative-step/): the founding incident behind the mechanical checks.
