---
title: The syllabus
description: "The curriculum map for the lab rail: what each lab certifies, the three lab modes, and three ordered reading paths through the site."
sidebar:
  order: 1
---

The tutorials tier is a data-science curriculum run against a real data
home, and this page is its syllabus. It maps each skill to the concept
that explains it, the lab that teaches it, and the operator surface that
uses it for real; it names the three modes a lab may run in; and it lays
out three ordered paths through the site, one per kind of reader.

By the end you can:

- name, for any skill in the competency map, the concept that explains
  it, the lab that certifies it, and the operator surface that uses it
- state which of the three modes a lab runs in before starting it, and
  what that mode protects
- pick the reading path that fits you and name its first stop

## The system grades the student

One conceit governs every lab, stated here once: **the system grades the
student**. Every checkpoint ends "verify with this command", and no lab
carries a prose answer key. The graders are the rib's own validators, so
passing a checkpoint and having correct data are the same event:

- **`collect-board`** (`pipeline/scripts/collect_board.py`) proves every
  page before parsing it and writes the coverage manifest; a collection
  is right when its cells say so, gaps named.
- **The canon test suite** (`pipeline/tests/test_canon.py`) holds every
  identity ruling to its evidence contract and the alias index to
  disjointness.
- **`check-membership`** (`pipeline/scripts/check_membership.py`)
  validates the authored membership artifact and reports its coverage.
- **`build-digest`** (`pipeline/scripts/build_digest.py`) is
  deterministic, so a number you recompute by hand either matches the
  digest or exposes a mistake, yours or the machine's.
- **The `verify` refute pass** in `workflows/touchline-report.yml`
  re-fetches every finding's URL and keeps only what survives.
- **The `validate-narrative` gate** in the same workflow fails the run
  when a narrative leaves its contract.

A checkpoint that cannot be verified mechanically is not on the rail.

## The competency map

Each row is one skill, read left to right: the theory, the lab that
makes it physical, and the surface where an operator exercises it daily.

| Skill | Concept spine | Lab | Operator surface |
| --- | --- | --- | --- |
| Scraping and acquisition | [Proof before parse](../../concepts/proof-before-parse/), [Archive first](../../concepts/archive-first/) | [Stand up a season](../first-season-board/), [Read a raw page](../read-a-raw-page/) | [Run a collection](../../guides/run-a-collection/), [Onboard a school](../../guides/onboard-a-school/) |
| Cleaning and parsing | [Reading hostile HTML](../../concepts/reading-hostile-html/) | [Read a raw page](../read-a-raw-page/) | [Audit the data](../../guides/audit-the-data/) |
| Entity resolution | [Identity](../../concepts/identity/) | [Trace an identity](../trace-an-identity/) | [Audit the data](../../guides/audit-the-data/) |
| Data modeling and time | [Season is a dimension](../../concepts/season-and-membership/), [Absence is data](../../concepts/absence-is-data/) | [Trace an identity](../trace-an-identity/), [Stand up a season](../first-season-board/) | [File contracts](../../reference/file-contracts/), [Data on disk](../../reference/data-on-disk/) |
| Deterministic analysis | [The determinism boundary](../../concepts/the-determinism-boundary/) | [Interrogate the digest](../interrogate-the-digest/) | [Run a scouting report](../../guides/run-a-report/) |
| Gated LLM composition | [Evidence, not recall](../../concepts/evidence-not-recall/), [Gates](../../concepts/gates/) | [Break a gate](../break-a-gate/), [Research with receipts](../research-with-receipts/), [Capstone](../capstone-scout-a-season/) | [Run a scouting report](../../guides/run-a-report/), [Build a player profile](../../guides/build-a-player-profile/) |

## The three lab modes

Every exercise runs in one of three modes, and the destructive ones
always say "on a scratch copy".

1. **A practice home.** Point `TOUCHLINE_DATA_DIR` at a fresh directory
   and the whole exercise is disposable. Scaffolding is safe by
   construction: `bootstrapDataHome` in `src/datahome.ts` refuses any
   directory that is neither empty nor already marked as a Touchline
   home, so a mistyped path cannot scatter a data tree into your work.
2. **Read-only against the real home.** Inspection labs read the archive
   and the season files and recompute results by hand; nothing is
   written, so the living season is never at risk.
3. **Scratch writes only.** Labs that must write touch only regenerable
   tiers: `data/scratch/` and the derived files a re-collect rebuilds.

The taxonomy is not invented for teaching; it mirrors the data home's
own tiers. The archive under `data/raw_html/` is the evidence and no lab
writes it. Scratch and the derived files are rebuildable, which is
exactly why scratch labs may write them. And a
practice home is cheap because the empty-or-ours rule makes creating one
a one-step, reversible act.

## Three reading paths

**The operator path.** Run the system before studying it: the guides
tier in order.

1. [Install](../../guides/install/)
2. [Create a data home](../../guides/create-a-data-home/)
3. [Run a collection](../../guides/run-a-collection/)
4. [Work the board](../../guides/work-the-board/)
5. [Run a scouting report](../../guides/run-a-report/)
6. [Build a player profile](../../guides/build-a-player-profile/)
7. [Onboard a school](../../guides/onboard-a-school/)
8. [Rebuild from the archive](../../guides/rebuild-from-the-archive/)
9. [Audit the data](../../guides/audit-the-data/)

**The data-science curriculum.** The lab rail in order, with each
flagship concept read just before the lab that makes it physical.

1. [Stand up a season](../first-season-board/): collect the season the
   rest of the rail grades you against.
2. [Read a page the way the parser does](../read-a-raw-page/)
3. [Identity](../../concepts/identity/), before its lab
4. [Trace an identity](../trace-an-identity/)
5. [The determinism boundary](../../concepts/the-determinism-boundary/)
6. [Absence is data](../../concepts/absence-is-data/), before the
   digest's gap work
7. [Interrogate the digest](../interrogate-the-digest/)
8. [Gates](../../concepts/gates/)
9. [Break a gate](../break-a-gate/)
10. [Evidence, not recall](../../concepts/evidence-not-recall/)
11. [Research with receipts](../research-with-receipts/)
12. [Capstone: scout a season](../capstone-scout-a-season/)

**AI-system literacy.** For the reader who cares less about soccer data
than about how a gated LLM system is built and broken.

1. [Five layers](../../concepts/five-layers/)
2. [The determinism boundary](../../concepts/the-determinism-boundary/)
3. [Evidence, not recall](../../concepts/evidence-not-recall/)
4. [Gates](../../concepts/gates/)
5. [Prompt contracts](../../reference/prompts-and-protocols/)
6. [Break a gate](../break-a-gate/)
7. [Research with receipts](../research-with-receipts/)
8. [Capstone: scout a season](../capstone-scout-a-season/)

## Prerequisite

Every lab past the first assumes a data home holding at least one
collected conference season. If you have none, either follow
[Install](../../guides/install/) and
[Run a collection](../../guides/run-a-collection/) first, or start the
rail at its first stop, which builds one from nothing.

One stop asks for more: [Break a gate](../break-a-gate/) needs a data
home holding a delivered report. Produce one with
[Run a scouting report](../../guides/run-a-report/) before that stop.

First stop: [Stand up a season](../first-season-board/).

## Related

**Run it**

- [Guides](../../guides/): the operator path's pages, task-first and
  without the teaching.
- [Pipeline CLI](../../reference/pipeline-cli/): the graders named
  above, as a terse command contract.

**Understand it**

- [Five layers](../../concepts/five-layers/): the system shape the
  competency map is a projection of.
- [Concepts](../../concepts/): the full essay tier the rail interleaves.
