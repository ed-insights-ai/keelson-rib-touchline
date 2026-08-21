---
title: Rebuild from the archive
description: Rebuild parquet and Postgres offline from the raw HTML archive, migrating legacy season files to conference shards first.
sidebar:
  order: 8
---

The raw HTML archive is the system of record. The parquet tree under
`data/structured/` and the Postgres database are rebuildable derivatives, so
a corrupt, stale, or deleted derived store is an inconvenience, not a loss:
rebuild it offline from `data/raw_html/` and the URL manifest. What is never
a rebuild path is scraping: `uv run scrape` is not offline even with a warm
cache, because discovery always hits the network (`pipeline/CLAUDE.md`). Use
`scrape` only for pages you never archived; use `reparse` for everything the
archive already holds.

## 1. Migrate legacy season files, once

Skip this step if the home is already conference-sharded. A home created
before sharding holds legacy unsharded season filenames, shaped
`{season}-{gender}.json`; the reader deliberately has no legacy fallback, so
migrate before using it:

```bash
TOUCHLINE_DATA_DIR={data-home} uv run --project pipeline migrate-shard --conference GAC
```

`pipeline/scripts/migrate_shard.py` splits plan from apply: `plan_migration`
preflights every file across all four layers (fixtures, rosters, stats,
matches) before anything is touched. Conference resolution refuses to guess:
a payload's own `conference` field wins, and must agree with `--conference`
when both are present; otherwise the flag; otherwise the home's fixture
shards, but only when they establish exactly one candidate. Anything
ambiguous raises `MigrationError` and tells you to pass `--conference`
explicitly. Fixture files are upgraded from `touchline.fixtures/1` to
`touchline.fixtures/2`, stamping the conference into the payload and into
each programme entry.

Re-running is safe: a destination identical to what the migration would write
is skipped, and a differing destination is refused rather than overwritten.
Success prints each shard written and exits 0; a refusal prints
`migration refused:` with the reason and exits 1, having changed nothing.

## 2. Reparse the archive

```bash
TOUCHLINE_DATA_DIR={data-home} uv run --project pipeline reparse
```

`pipeline/scripts/reparse.py` reads every archived page under
`data/raw_html/{school}/{year}/` plus the manifest `data/source_urls.csv` and
rebuilds the whole `data/structured/` parquet tree without touching the
network. The manifest is strict: exactly the header `game_id,source_url`, no
blanks, no duplicates. Reconciliation is bidirectional: every archived page
must have a manifest row, and every manifest row must be consumed by a page.

Output is built in a staging directory, validated (`_validate_staged_output`
requires every expected parquet to exist and be non-empty), stamped with a
`.reparse-complete` marker, then swapped into place by rename, with a backup
that is restored if the swap fails (`_publish_staged_output`). Success prints
`Reparsed {n} cached games into ...`. Any page that fails to parse fails the
whole run, naming the game_id and path, and the previous `data/structured/`
tree is left untouched: a partial rebuild is never published.

## 3. Reload the database

```bash
TOUCHLINE_DATA_DIR={data-home} uv run --project pipeline load-db
```

`pipeline/scripts/load_db.py` loads the parquet tree into Postgres
(`DATABASE_URL`, defaulting to the local touchline database). The load is
idempotent: games upsert on `game_id`, and the child tables (team stats,
player stats, events) are deleted and reinserted per game, so re-running
converges to the same rows. `--dry-run` prints what would load without
writing; `--school {abbrev}` restricts the load to one school. The database
is a derived index, never the record: dropping and reloading it is always
safe.

## 4. Verify the rebuild

Run the checks in [Audit the data](../audit-the-data/). The archive check in
`workflows/data-integrity.yml` compares Postgres row counts against freshly
reparsed parquet exports, so a clean rebuild reads as agreement and any gap
is a real divergence.

**What you just exercised:** [Archive first](../../concepts/archive-first/),
[The determinism boundary](../../concepts/the-determinism-boundary/), and
[Raw archive as system of record](../../design/raw-archive-as-system-of-record/).

## Related

**Run it**

- [Audit the data](../audit-the-data/): the read-only checks that grade the rebuild.
- [Run a collection](../run-a-collection/): the online path, for data the archive does not hold.

**Understand it**

- [Read a raw page](../../tutorials/read-a-raw-page/): the archived HTML the reparse consumes, opened by hand.
- [Archive first](../../concepts/archive-first/): why the page is written verbatim before anything parses it.
