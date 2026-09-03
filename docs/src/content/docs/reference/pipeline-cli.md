---
title: Pipeline CLI
description: One terse entry per console script in pipeline/pyproject.toml, with inputs, outputs, network behavior, and exit codes.
sidebar:
  order: 6
---

Every console script declared in `pipeline/pyproject.toml` under
`[project.scripts]`, one entry each. Run them with
`uv run --project {pipeline-dir} {script}` (or `uv run {script}` from the
pipeline directory). All data paths resolve through `pipeline/src/paths.py`:
`TOUCHLINE_DATA_DIR` when set, else the current working directory, so run
from the data home or export the variable. Exit codes appear only
where they are nontrivial; the full contract table is
[Gates and exit codes](../gates-and-exit-codes/).

## Collection (online)

### collect-board

Live SideArm collection of the four layers (`schedule`, `roster`, `stats`,
`matches`) for one conference season, each layer proven and landed
independently. Named gaps are data, not failures.

- **Inputs**: `--season`, `--gender`, `--conference`, `--programmes` (comma-separated slugs), `--layers` (default all four), `--config`, `--membership-extrapolated`.
- **Outputs**: `data/fixtures/{season}-{gender}-{conference}.json` and its `rosters`, `stats`, and `matches` siblings; the merged `data/coverage.json`; `data/errors/collect-board-{season}-{gender}-{conference}.json` when gaps were named.
- **Exit**: 0 the coverage manifest was written, gaps and all; 1 the manifest write failed; 2 usage.

### probe

Read-only onboarding probe: fingerprints a site's platform with positive
evidence, reports which layers it publishes and which seasons it serves, and
drafts a disabled `schools.toml` stanza in the house layout for human
review, with `abbreviation`, `mascot` and `aliases` read off the site.
Writes no local data.

- **Inputs**: `--url` (repeatable), `--name` (the slug-minting name, one per `--url` in order, or none), `--conference`, `--seasons` (a year or inclusive range, default the current year back through 2016), `--json`.
- **Outputs**: a report per URL on stdout, including the draft stanza.
- **Exit**: 0 every URL probed; 1 any URL invalid or unfetchable; 2 `--name` given for some URLs but not all.

## Data home maintenance (offline)

### migrate-shard

Rename legacy unsharded season files to conference-sharded names across
fixtures, rosters, stats, and matches, upgrading fixtures from
`touchline.fixtures/1` to `touchline.fixtures/2`. Plans everything before
mutating anything; re-running is safe.

- **Inputs**: `--conference` (optional when the home's fixture shards establish exactly one).
- **Outputs**: renamed `{season}-{gender}-{conference}.json` shards.
- **Exit**: 0 migrated or nothing legacy; 1 refused rather than guess.

## No database commands

There are none, on purpose. The JSON data home is the system of record:
the season files under `data/fixtures`, `data/rosters`, `data/stats`, and
`data/matches`, backed by the raw page archive. A derived SQL index can be
rebuilt from those files if one is ever needed; the pipeline neither
maintains nor reads one.

## Identity and membership

### check-membership

Validate the authored conference-membership reference artifact against the
contract in `pipeline/src/membership.py`: dated windows, mandatory sources,
no gaps, no overlaps, every configured programme covered.

- **Inputs**: none; reads `data/reference/membership.json`.
- **Exit**: 0 valid; 1 one line per violation.

### sweep-opponent-slugs

Read-only sweep of every fixture file in the data home for one fixture filed
under two opponent slugs: two rows on one date sharing a slug on one side
with two different slugs on the other (`ut-dallas` beside
`of-texas-at-dallas`). Each pair is re-folded through the collector's
current identity rules and labelled `FOLD` (a fold rule joins them, named),
`ALIAS` (a stanza alias joins them) or `APART` (still two identities, or a
host meeting two visitors in one day). Every conference file is swept;
nothing names a conference.

- **Inputs**: `TOUCHLINE_DATA_DIR`; reads `data/fixtures/*.json` only.
- **Output**: one line per pair, then one JSON verdict line (`ok` with no
  pairs, `warn` otherwise).
- **Exit**: always 0.

## Analysis and reports (offline)

### build-digest

Compute the deterministic scouting digest for one conference season shard:
the only source of figures a generated report may cite.

- **Inputs**: `--season`, `--gender`, `--conference`, `--focus`.
- **Outputs**: `data/scratch/digest-{season}-{gender}-{focus}.json` (`touchline.digest/1`), written atomically.
- **Exit**: 0 written; 2 fixtures missing or focus slug unknown, collect first.

### render-report

Merge the digest with a narrative file into the print-first briefing and its
appendix, then print both to PDF through headless Chrome. Missing narrative
sections render as explicit placeholders.

- **Inputs**: `--season`, `--gender`, `--focus`, `--narrative` (default `data/reports/narrative-{season}-{gender}-{focus}.json` when present); `TOUCHLINE_CHROME` overrides the browser binary.
- **Outputs**: `data/reports/preseason-{season}-{gender}-{focus}.pdf` and its `-appendix` sibling; the HTML intermediates survive only when no PDF could be made.
- **Exit**: 0 rendered (HTML only when Chrome is absent); 2 no digest; 3 PDF print failed.

### build-profile

Assemble or refresh one player profile: the deterministic record is
recomputed and replaced, and with `--findings` a verified research file is
merged additively, deduplicated on URL plus text.

- **Inputs**: `--programme`, `--gender`, `--conference`, `--player` (name as published), `--findings`.
- **Outputs**: `data/players/{gender}/{programme}/{slug}.json` (`touchline.player-profile/1`).
- **Exit**: 0 written; 2 findings file missing, or the player has no trace in the season files.

### normalize-research

Rewrite every research JSON under `data/research/` into the canonical
line-per-fact shape. Idempotent and content-preserving: a file whose
canonical form fails the round trip is skipped, loudly.

- **Inputs**: none.
- **Exit**: 0 all canonical; 1 any file skipped.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): the collect commands in their working order.
- [Run a scouting report](../../guides/run-a-report/): the digest, render, and gate chain as a task.
- [Rebuild from the archive](../../guides/rebuild-from-the-archive/): re-deriving season files from the archive.
- [Gates and exit codes](../gates-and-exit-codes/): the full exit and gate contract.

**Understand it**

- [Archive first](../../concepts/archive-first/): why every page is archived before anything parses it.
- [The determinism boundary](../../concepts/the-determinism-boundary/): why the digest is the only source of numbers.
- [Absence is data](../../concepts/absence-is-data/): what a collect run's exit 0 does and does not claim.
