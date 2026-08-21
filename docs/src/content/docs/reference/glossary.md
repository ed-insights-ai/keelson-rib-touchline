---
title: Glossary
description: Every house term in one line each, pointing to the page that owns its definition.
sidebar:
  order: 8
---

One line per term. The linked page owns the definition; this page only
points.

- **adjudication**: a recorded human ruling on an ambiguous team string, held in the `ADJUDICATIONS` ledger in `pipeline/src/canon.py`; see [Identity](../../concepts/identity/).
- **artifact**: the classification for a team string that names no institution at all (a malformed or context-only label), one of the three answers `resolve` in `pipeline/src/canon.py` may give; see [Identity](../../concepts/identity/).
- **attested_uncaptured**: the dead-letter bucket for claims believed true but not capturable at a fetched URL, which never reach report prose; see [Evidence, not recall](../../concepts/evidence-not-recall/).
- **bench lens**: the reading rule that weights every held pattern by verified coach tenure; see [Prompt contracts](../prompts-and-protocols/).
- **coverage cell**: one entry in `data/coverage.json`, keyed `{season}/{gender}/{programme}/{layer}`, recording a collection outcome state and why; see [Absence is data](../../concepts/absence-is-data/).
- **data home**: the marker-file-owned directory that holds a deployment's archive, season files, research, and reports; see [Create a data home](../../guides/create-a-data-home/).
- **digest**: the deterministic per-report computation that is the only numeric source the narrative may quote; see [The determinism boundary](../../concepts/the-determinism-boundary/).
- **drawer**: the board's detail view behind a row: a schedule row opens the match drawer, a roster row the player drawer; see [Work the board](../../guides/work-the-board/).
- **empty-or-ours rule**: the write-path guard that touches only a directory that is empty or already a marked data home; see [Create a data home](../../guides/create-a-data-home/).
- **evidence label**: the tag every important claim renders under: observed, projected, signal, or judgment; see [The determinism boundary](../../concepts/the-determinism-boundary/).
- **experience ladder**: the canonical scouting heuristic for reading a newcomer's verified pedigree by competition tier; see [Prompt contracts](../prompts-and-protocols/).
- **finding**: the unit of research output, one claim plus its source, URL, date, and confidence grade; see [Evidence, not recall](../../concepts/evidence-not-recall/).
- **fixture**: one scheduled match in a season's `touchline.fixtures/2` file, with nullable scores and a lifecycle status; see [File contracts](../file-contracts/).
- **focus programme**: the programme a report run is prepared for, named by the `focus` input; see [Run a scouting report](../../guides/run-a-report/).
- **gate**: a mechanical check that can stop a run, standing after every generative step; see [The model declares, the validator decides](../../concepts/gates/).
- **identity binding**: the false-positive rule that a name match becomes a finding only through a corroborating attribute; see [Evidence, not recall](../../concepts/evidence-not-recall/).
- **insight filter**: the scored rubric that decides whether an insight enters the main report, a card line, or nothing; see [Prompt contracts](../prompts-and-protocols/).
- **layer**: one of the five stages of the system map (collect, curate, analyze, interpret, render), and in a coverage cell key, one collected surface of a programme; see [The system in one view](../../concepts/five-layers/).
- **major news**: the class of verified items (coach change, intra-conference transfer, decorated arrival) that travels to every report and bypasses the insight filter; see [Prompt contracts](../prompts-and-protocols/).
- **membership window**: a cited `from_season`-to-`to_season` interval binding a programme to a conference; see [Season is a dimension](../../concepts/season-and-membership/).
- **missing manifest**: the `missing` field every season file carries, naming what could not be collected instead of dropping it silently; see [Absence is data](../../concepts/absence-is-data/).
- **one finding, one page**: the decomposition rule that every finding's truth must be checkable at its single URL; see [Evidence, not recall](../../concepts/evidence-not-recall/).
- **ordinal**: a school's globally unique integer namespacing the legacy `game_id` arithmetic; see [Onboard a school](../../guides/onboard-a-school/).
- **payload trap**: the embedded page JSON that confidently names the wrong season, which proof-before-parse exists to catch; see [Proof before parse](../../concepts/proof-before-parse/).
- **programme**: one school's team in one gender, the unit that season files, coverage cells, and research files are keyed by; see [Season is a dimension](../../concepts/season-and-membership/).
- **rib**: a package that plugs a domain like Touchline into the Keelson harness; see [the overview](../../).
- **ruled out vs no indexed mention**: the two absences the research keeps apart: a page read without the name, versus a surface search cannot see; see [Absence is data](../../concepts/absence-is-data/).
- **season proof**: the check that a fetched page demonstrably serves the requested season before anything parses it; see [Proof before parse](../../concepts/proof-before-parse/).
- **season rail**: the board's one-tick-per-fixture timeline of a season, whose marks keep played, postponed, and past-date-unpublished fixtures distinct; see [Work the board](../../guides/work-the-board/).
- **shard**: a season file scoped to one conference, one gender, and one season; see [Season is a dimension](../../concepts/season-and-membership/).
- **stopping rules**: the explicit budgets that end a research sweep and route the remainder to `unswept`; see [Prompt contracts](../prompts-and-protocols/).
- **tier**: an opponent card's layout classification, benchmark, swing, or update, never spoken in prose; see [Prompt contracts](../prompts-and-protocols/).
- **unswept**: the record of what a research sweep could not reach, with reasons; see [Evidence, not recall](../../concepts/evidence-not-recall/).
- **verdict**: whether a claim was verified at a fetched page, an axis orthogonal to source confidence; see [Evidence, not recall](../../concepts/evidence-not-recall/).
- **watchlist**: the per-opponent player profiles admitted by the insight filter, up to two each; see [Prompt contracts](../prompts-and-protocols/).

## Related

**Run it**

- [Surface, tools, and keys](../rib-surface/): the tools and board the operator-facing terms name.
- [Data on disk](../data-on-disk/): where the files behind these terms live.

**Understand it**

- [The system in one view](../../concepts/five-layers/): the map these terms hang off.
- [The syllabus](../../tutorials/syllabus/): the learning rail that makes them physical.
