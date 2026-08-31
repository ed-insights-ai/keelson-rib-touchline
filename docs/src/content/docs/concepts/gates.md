---
title: The model declares, the validator decides
description: Mechanical completion checks, fail-closed monitors, monotone severity, and hard print budgets gate every generative step in Touchline.
sidebar:
  order: 9
---

Every generative step in Touchline is followed by a deterministic check, and the check has the last word. When a research iteration replies "ALL RESEARCHED", the workflow treats the reply as a declaration, not a result. A **gate** is the deterministic node that decides whether the declaration is true: it counts files, checks schemas, measures word counts, and fails the run when reality disagrees. A report never ships because a model said the work was done. It ships because the gates could not prove otherwise.

The incident that made this a founding law rather than a preference is recorded in [Gate after every generative step](../../design/gate-after-every-generative-step/). This page is about the machinery the law produced.

## Completion is counted, not claimed

A Keelson loop can end two ways: the model replies the loop's `until` phrase, or the loop's `until_bash` check passes. Touchline treats the phrase as a courtesy and the check as the contract. The research loop in `workflows/touchline-report.yml` nominally ends on "ALL RESEARCHED", but its `until_bash` recounts the evidence on every iteration: it reads the digest's programme count with `jq`, counts the `research-{slug}.json` files that carry a top-level `coach` object, and passes only when the second number covers the first. The prompt even instructs the model to run its own `jq` check over the same files before replying, and a comment beside the next node states the reason plainly: the text exit can fire on a model's say-so.

Then the workflow checks again anyway. The `validate-research` gate that follows the loop walks every programme in the digest and fails the run, exit 1, if any programme lacks a research file or a coach object with a legal status.

The verification and opponent-card loops add a second mechanical axis: staleness. Their `until_bash` checks require each per-programme file to be newer than the digest (the shell's `-nt` test), and the digest is rebuilt at the start of every run, so last week's `verified-{slug}.json` cannot satisfy this week's gate. Freshness is a file timestamp, not a promise.

## A check that did not run is never a zero

Gates guard production; monitors guard belief. The `data-integrity` workflow runs read-only checks against the data home's season layers, gap ledger, and membership reference, and every one of them is required to **fail closed**: a check that could not run must say so, loudly, instead of reporting a clean zero.

The failure mode this defends against is precise. A shell pipeline that discards stderr delivers every failure as an empty string, and in bash `[ "" -gt 0 ]` is a test error rather than false, so an unguarded escalation never fires and the verdict keeps its initialized `ok`. That is exactly how a check against a store that no longer existed once rendered as passing. The discipline in `workflows/data-integrity.yml`: after the measurements run, every captured variable is asserted non-empty, and if any is missing the check prints a `CHECK DID NOT RUN` headline naming the empty captures, stating that those are failed measurements, not measurements of zero. The failure headline is deliberately not the measurement headline with blanks in it; a reader must be able to tell "the measurement failed" from "the data is bad" at a glance.

The filesystem checks apply the convention with their own guards: the collect-gaps node alarms on a missing `data/errors` directory, because a missing directory is not an empty one, and an unreadable directory is not an empty one either; goal-attribution refuses to sweep a season file that `jq` cannot read, because a file that cannot be read is not a clean one.

## Severity only rises

Verdicts live on a three-step lattice: `ok` below `warn` below `alarm`, and movement along it is monotone. Each check in `workflows/data-integrity.yml` initializes its verdict at `ok` and only ever escalates it; none is followed by an assignment that could lower it. The rule was learned the hard way, in a since-retired check whose first fix set an alarm correctly and then reset it to warn with a later plain assignment, silently. A later line that can undo an earlier signal is the same defect as a check that never ran.

Aggregation follows the lattice. The integrity report node collects each check's one-line JSON verdict and prints the worst as the run's verdict: any alarm makes the run ALARM, otherwise any warn makes it WARN.

## Exit codes are the seam

The orchestration layer never parses prose to learn whether a step succeeded; it reads the exit code, and each workflow defines what its codes mean.

| Species | Behavior on failure | Where |
|---|---|---|
| Gate | Print an ALARM line, exit 1, halt the run | `validate-research`, `validate-verified`, `validate-narrative` in `workflows/touchline-report.yml` |
| Monitor | Exit 0 with an alarm verdict in its JSON payload, so every other check still runs | the checks in `workflows/data-integrity.yml`, aggregated by the report node |
| Collector | Exit 0 is a defined claim: the coverage manifest was written and describes reality, gaps included | the collect node in `workflows/touchline-collect.yml` |

A gate halting is the point: nothing downstream may run on unproven input. A monitor halting would be a bug: it would hide every other check's findings behind the first failure. The normalizer sits between the species: `pipeline/scripts/normalize_research.py` exits 1 when any research file had to be skipped, so a file that cannot round-trip to identical data stops the run before the narrative stage reads it. The full contract table lives in [Gates and exit codes](../../reference/gates-and-exit-codes/).

## The prose itself is gated

The last gate before render reads the assembled narrative the way a compiler reads source. `validate-narrative` in `workflows/touchline-report.yml` enforces structure first: exactly 3 executive findings, 1 to 3 decisions, an offseason ledger of at most 3 items, the evidence and meaning split present on every finding, no dossier section, and a watchlist holding at most 2 profiles per opponent, none of them for the focus side.

It also enforces two things a schema checker would not think to look for.

**Lexical guardrails.** The gate greps every string in the narrative for machinery words: "digest", "roster shape", "verified pool", and the raw `roster_shape` key name. One hit is an alarm. The report speaks to a coaching staff, and the style contract bans it from naming its own internals; "No roster shape is verified" must become "the 2026 roster has not been published". A model drifts toward its own vocabulary under pressure, so the ban is enforced with `grep`, not with a request.

**Hard word budgets.** `wc -w` measures the bottom line against 70 words, the landscape section against 100, and the focus overview against 110; each watchlist "why" is measured against 90. These are print boundaries, not taste: the renderer composes fixed pages, and prose past a budget spills onto a broken page that no deterministic layout step can repair. The gate's alarm message states it plainly: prose past budget breaks the print layout.

:::caution
A narrative that passes every gate is on-contract, not true. The gates prove shape, freshness, vocabulary, and budget; the truth standard lives upstream, in the adversarial verification pass and the evidence rules. See [Evidence, not recall](../evidence-not-recall/).
:::

Lab: [Break a gate](../../tutorials/break-a-gate/) makes this page physical: forge a gate's input on a scratch copy, watch the exact ALARM fire, and read the exit code the orchestrator saw.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): drive the workflow these gates guard, end to end.
- [Gates and exit codes](../../reference/gates-and-exit-codes/): the terse contract for every gate, check, and code.

**Understand it**

- [The determinism boundary](../the-determinism-boundary/): the line that decides which steps need a gate at all.
- [Gate after every generative step](../../design/gate-after-every-generative-step/): the founding incident and the decision record.
