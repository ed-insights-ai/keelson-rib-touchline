# Architecture — `@keelson/rib-touchline`

> This file is a short pointer. The authoritative architecture lives in the
> documentation site under `docs/`, which tracks the shipped rib. The repo is
> private and GitHub Pages is not enabled today, so build it locally:
> `cd docs && bun install && bun run build` (or `bun run dev` to browse).

Touchline scouts college soccer seasons for Keelson: it collects what athletics
sites already publish (schedules, rosters, player statistics, box scores, 2016
to the present), archives every page verbatim, reconciles the parses into
canonical records, computes a deterministic digest, and lets a gated language
model write evidence-cited scouting reports over it. Keelson owns the workflow
engine and the board surface; this rib adds the season intelligence.

## Where the architecture is documented

| Tier | What it covers |
|---|---|
| Concepts | The theory: the five layers, archive-first storage, proof before parse, identity resolution, absence as data, the determinism boundary, evidence-not-recall, gates, and season/membership time modeling. |
| Design | Decision records (gate after every generative step, the model as reader, contracts not examples, the raw archive as system of record, conference as configuration, a briefing is a run) and the hosted system-design narrative PDF. |
| Reference | The exact contract: the rib surface and tools, the four workflows, data on disk, the versioned file contracts, gates and exit codes, the pipeline CLI, the prompt contracts, and the glossary. |
| Guides | Operator recipes: install, create a data home, run a collection, work the board, run a report, build a player profile, onboard a school, rebuild from the archive, audit the data. |
| Tutorials | The lab rail: a data-science curriculum run against a real data home, capstoned by a full gated report run. |

## Lineage

The Python collection pipeline under `pipeline/` was extracted from the
`ed-insights-ai/ed-insights-platform` repository (`packages/pipeline`), where
its development history remains. Attribution lives in [NOTICE](../NOTICE). The
original product contract is the Touchline rib specification in that
repository's `docs/specs/`.
