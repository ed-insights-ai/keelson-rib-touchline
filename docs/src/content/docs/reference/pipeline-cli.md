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
from the data home or export the variable. Database scripts read
`DATABASE_URL`, else the local `touchline` database. Exit codes appear only
where they are nontrivial; the full contract table is
[Gates and exit codes](../gates-and-exit-codes/).

## Collection (online)

### scrape

Historical box-score lineage: discover, fetch, parse, and save each school
season to parquet. Never offline, even with a warm cache: discovery always
hits the network.

- **Inputs**: `--year`, `--school {abbrev}`, `--config` (default the packaged `config/schools.toml`), `--no-cache`, `-v`.
- **Outputs**: raw HTML cached at `data/raw_html/{school}/{year}/game_{NN}.html`; parquet under `data/structured/`; parse forensics under `data/errors/`.
- **Exit**: 0 every discovered game completed; 1 partial or rejected; 2 unknown school.

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
drafts a disabled `schools.toml` stanza for human review. Writes no local
data.

- **Inputs**: `--url` (repeatable), `--conference`, `--seasons` (a year or inclusive range, default the current year back through 2016), `--json`.
- **Outputs**: a report per URL on stdout, including the draft stanza.
- **Exit**: 0 every URL probed; 1 any URL invalid or unfetchable.

## Archive and rebuild (offline)

### reparse

Rebuild the entire `data/structured/` parquet tree from the committed raw
archive and the `data/source_urls.csv` manifest, offline. Output is staged,
validated, then atomically published with backup and rollback. This is the
backfill path; `scrape` never is.

- **Inputs**: `--raw-html-dir`, `--source-urls`, `--config`, `--output-root`, `-v`.
- **Outputs**: the rebuilt `data/structured/` tree.
- **Exit**: no coded contract; any reconciliation or validation failure raises.

### migrate-shard

Rename legacy unsharded season files to conference-sharded names across
fixtures, rosters, stats, and matches, upgrading fixtures from
`touchline.fixtures/1` to `touchline.fixtures/2`. Plans everything before
mutating anything; re-running is safe.

- **Inputs**: `--conference` (optional when the home's fixture shards establish exactly one).
- **Outputs**: renamed `{season}-{gender}-{conference}.json` shards.
- **Exit**: 0 migrated or nothing legacy; 1 refused rather than guess.

## Database (derived index)

### load-db

Load the parquet tree into PostgreSQL and backfill `home_conference`. The
database is a rebuildable index, never the system of record.

- **Inputs**: `--school`, `--dry-run`, `--scrape-first`, `--database-url`.
- **Outputs**: populated `schools`, `games`, `team_game_stats`, `player_game_stats`, and `game_events` tables; a load summary.
- **Network**: offline, unless `--scrape-first` runs the scraper.
- **Exit**: 0 loaded; 1 nothing under `data/structured/`.

### export

Copy the merged parquet files from `data/structured/all/` to a flat output
directory.

- **Inputs**: `--output` (default `data/`).
- **Exit**: 0 files copied; 1 no merged archive or nothing exported.

### audit

Completeness audit of the database: per-school game counts through a LEFT
JOIN so empty schools still appear, totals, conference coverage, and
acceptance checks.

- **Inputs**: `--database-url`.
- **Exit**: always 0 when it runs; acceptance failures print FAIL without changing the code.

### pipeline-run

Chain `scrape`, `load-db`, `export`, and `audit` as one run. Online, because
of the scrape step.

- **Inputs**: `--all-enabled` or `--school`, `--year`, `--skip-scrape`, `--skip-load`, `--no-cache`, `--database-url`, `--config`, `-v`.
- **Exit**: propagates a failing step's code; tolerates only the `export` step's refusal on an empty archive.

## Identity and membership

### build-canon

Measure the distinct team-string universe across every source column named in
its `SOURCE_COLUMNS` and build (or, with `--check`, validate without rewriting) the
committed identity artifact.

- **Inputs**: `--check`; `DATABASE_URL`.
- **Outputs**: `data/reference/canon.json`, deterministically serialized.
- **Network**: offline (database only).
- **Exit**: 0 valid; 1 any build, read, or validation failure.

### check-membership

Validate the authored conference-membership reference artifact against the
contract in `pipeline/src/membership.py`: dated windows, mandatory sources,
no gaps, no overlaps, every configured programme covered.

- **Inputs**: none; reads `data/reference/membership.json`.
- **Exit**: 0 valid; 1 one line per violation.

### conference-audit

Recompute `is_conference_game` from identities and membership, read-only, and
compare against the stored flags. Prints a one-line JSON verdict on the
`ok`, `warn`, `alarm` lattice.

- **Inputs**: `--database-url`.
- **Network**: offline (database only, in a read-only session).
- **Exit**: 0 the audit ran, whatever the verdict; 1 the check did not run.

## Analysis and reports (offline)

### build-digest

Compute the deterministic scouting digest for one conference season shard:
the only source of figures a generated report may cite.

- **Inputs**: `--season`, `--gender`, `--conference`, `--focus`.
- **Outputs**: `data/scratch/digest-{season}-{gender}-{focus}.json` (`touchline.digest/1`), written atomically.
- **Exit**: 0 written; 2 fixtures missing or focus slug unknown, collect first.

### export-board

Project the merged parquet archive into a fixtures season file
(`touchline.fixtures/2`) for the board. Every fixture is already played: the
archive holds only games with a box score.

- **Inputs**: `--season`, `--gender`, `--conference`, `--programmes`, `--config`.
- **Outputs**: `data/fixtures/{season}-{gender}-{conference}.json`; unmatched opponent names reported, never dropped.
- **Exit**: 0 fixtures written; 1 no merged archive or zero fixtures; 2 usage.

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
- [Rebuild from the archive](../../guides/rebuild-from-the-archive/): `reparse` in anger.
- [Gates and exit codes](../gates-and-exit-codes/): the full exit and gate contract.

**Understand it**

- [Archive first](../../concepts/archive-first/): why `reparse` exists and `scrape` is never the backfill.
- [The determinism boundary](../../concepts/the-determinism-boundary/): why the digest is the only source of numbers.
- [Absence is data](../../concepts/absence-is-data/): what a collect run's exit 0 does and does not claim.
