---
title: Rebuild from the archive
description: Re-derive lost or stale season files from the raw page archive, migrating legacy season files to conference shards first.
sidebar:
  order: 8
---

The raw page archive is the evidence tier, and the season JSON files are
derivatives of it, so a corrupt, stale, or deleted season file is an
inconvenience, not a loss. The recovery move is always the same: run the
collect again for that season. The collector proves each page before
believing it, replays pages the archive already holds when their stored
validators still stand, and re-fetches only what it must, so a rebuild is
mostly an offline replay with a thin network edge.

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

## 2. Re-collect the season

```bash
TOUCHLINE_DATA_DIR={data-home} uv run --project pipeline collect-board \
  --season {season} --gender {gender} --conference {conference} \
  --programmes {slug},{slug}
```

The run rewrites the season's fixtures, rosters, stats, and matches files
wholesale, widened to whatever scope the home already covers, so one
command refreshes the whole season unit. Three mechanisms keep the rebuild
cheap and honest:

- **Unchanged pages replay from the archive.** The conditional-fetch memory
  (`pipeline/src/page_state.py`) answers a cheap validation request per
  page, and a page verified unchanged is re-parsed from the archived copy
  `write_raw_pages` kept, not re-fetched. A parser fix invalidates the
  cached parse through its fingerprint without costing a fetch.
- **Settled box scores are reused.** A stored box score for a final whose
  scoreline has not moved is data that cannot have changed since the
  whistle; the run keeps it rather than re-fetching it.
- **`--refetch` is the clean slate.** It collects as if the home had never
  seen the pages: every validator ignored, every box score re-fetched. Use
  it when the stored state itself is what you distrust.

Any layer that cannot be proven lands as a named gap in `data/coverage.json`
and the run's gap ledger, never as silently missing data.

## 3. Verify the rebuild

Run the checks in [Audit the data](../audit-the-data/):
`workflows/data-integrity.yml` sweeps the rebuilt season layers cell by
cell, and its goal-attribution check names any programme whose fixtures and
stats layers disagree, which after a rebuild usually means one layer's
publication lagged the other; re-collect once the site catches up.

**What you just exercised:** [Archive first](../../concepts/archive-first/),
[Proof before parse](../../concepts/proof-before-parse/), and
[Raw archive as system of record](../../design/raw-archive-as-system-of-record/).

## Related

**Run it**

- [Audit the data](../audit-the-data/): the read-only checks that grade the rebuild.
- [Run a collection](../run-a-collection/): the same command in its everyday shape.

**Understand it**

- [Read a raw page](../../tutorials/read-a-raw-page/): the archived HTML the replay consumes, opened by hand.
- [Archive first](../../concepts/archive-first/): why the page is written verbatim before anything parses it.
