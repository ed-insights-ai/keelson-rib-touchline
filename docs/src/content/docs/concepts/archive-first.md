---
title: The archive is the system of record
description: Raw pages land on disk before any parser reads them; the season files, parquet shards, and Postgres are rebuildable derivatives of that archive.
sidebar:
  order: 2
---

Touchline treats exactly one store as truth: the raw HTML of every page it
fetched, exactly as the site served it. Everything downstream, the
season JSON files the board reads, the parquet shards, the Postgres database,
is a **derivative**: computed from the archive, rebuildable from the archive,
and deletable without losing a single fact. When a parser improves or a bug
is found months later, the fix is to replay the archive offline, not to crawl
the web again and hope it still says what it said.

## The page lands first

Both collection lineages write the served page to disk before any derived
file is published from it.

The historical box-score scraper fetches through `GameFetcher`
(`pipeline/src/fetcher.py`), which writes the response text to
`data/raw_html/{school}/{year}/game_{nn}.html` before returning the HTML to
its caller. The parser only ever sees bytes that are already archived. The
cache is also read-first: a page already on disk is returned from disk, so a
re-run parses the archive rather than the network.

The live board collector archives per programme through `write_raw_pages`
(`pipeline/src/sidearm_live.py`), which writes
`data/raw_html/{slug}/{year}-{gender}-schedule.html` and the matching roster
and stats pages. Its docstring is the whole rule: archive whatever was
actually served, so any parse can be redone offline. The board entrypoint
(`pipeline/scripts/collect_board.py`) calls it immediately after each
programme's collection, before it assembles a single season file.

This is what warehouse practice calls a **raw zone** (or bronze layer): an
immutable capture of the source, with every parsed product strictly
downstream of it. The reason is not tidiness. The web does not replay the
past. Sites redesign, past-season URLs redirect to the current season, and a
page you fetched in September may be unfetchable by March. The archive is the
one witness that cannot drift, and [Proof before parse](../proof-before-parse/)
is what guarantees each archived page is the page it claims to be.

## Everything else is a derivative

Three stores sit downstream of the archive, each explicitly labeled
rebuildable:

- **Season JSON files**, the consumer deliverable: one schema-tagged file per
  season, gender, and conference (`touchline.fixtures/2`,
  `touchline.rosters/1`, `touchline.stats/1`, `touchline.matches/1`), written
  atomically by `_atomic_json` in `pipeline/scripts/collect_board.py`.
- **Parquet shards** under `data/structured/`: ignored build output, per
  `pipeline/CLAUDE.md`, rebuilt offline with `uv run reparse`.
- **Postgres**: `pipeline/src/paths.py` annotates the fallback DSN as a
  derived index, "rebuildable from the files under data_root(); it is never
  the system of record". `pipeline/scripts/load_db.py` loads it from the
  parquet shards, idempotently.

:::note
Re-fetching is not rebuilding. `uv run scrape` is never an offline command,
even with a warm cache, because discovery always hits the network
(`pipeline/CLAUDE.md`). Any backfill goes through `reparse`, never `scrape`.
:::

## Reparse: recompute the tree, then swap it in

`uv run reparse` (`pipeline/scripts/reparse.py`) rebuilds the entire
`data/structured/` parquet tree from two data-home inputs: the committed
archive under `data/raw_html/` and the provenance manifest
`data/source_urls.csv`. (School configuration is code-like config that ships
with the package, per `pipeline/src/paths.py`.) It never touches the network.

The rebuild is strict about provenance before it parses anything.
`_load_source_urls` refuses a manifest with the wrong columns, a blank URL,
or a duplicate `game_id`. Every archived page must map to a manifest entry,
every manifest entry must have an archived page, and `_build_game_id` refuses
a school with no assigned ordinal rather than let it collide in the shared id
namespace. A rebuild that cannot say where each page came from does not run.

The output is then published atomically, in three moves:

1. **Staging.** Every season is parsed and saved into a hidden staging
   directory created beside `data/structured/`, where `save_season`,
   `merge_all_seasons`, and `merge_all_schools` (`pipeline/src/storage.py`)
   build the full tree. `merge_all_seasons` deliberately ignores its
   deprecated `years` parameter and scans every season directory on disk, so
   updating one season cannot truncate the merged archive.
2. **Validation.** `_validate_staged_output` requires every expected parquet
   file, per season, per school, and merged, to exist and be non-empty, and a
   `.reparse-complete` marker records the game count.
3. **Publish.** `_publish_staged_output` renames the live tree aside, renames
   the staged tree into place, and restores the old tree if the swap fails.
   A reader sees the old complete tree or the new complete tree, never a
   half-written one.

## Four tiers in the data home

Durable data lives in a **data home**: an ordinary directory marked by
`touchline-data.yaml` and scaffolded by `bootstrapDataHome`
(`src/datahome.ts`). The layout separates four tiers by what it costs to lose
them:

| Tier | Paths | What it holds |
| --- | --- | --- |
| Deliverables | `data/fixtures/`, `data/rosters/`, `data/stats/`, `data/matches/` | The product: schema-tagged season files, one per season, gender, and conference. |
| Evidence | `data/raw_html/`, `data/errors/` | The pages exactly as fetched, plus anything a run could not parse, kept rather than dropped. |
| Reference | `data/reference/` | Curated identity and membership: `canon.json` and `membership.json`, resolved by `canon_path` and `membership_path` in `pipeline/src/paths.py`. |
| Scratch | `data/scratch/` | Regenerable intermediates, such as the report digest `pipeline/scripts/build_digest.py` writes; created on first write rather than by the bootstrap. |

The tiers order the delete-safety story. Scratch is always safe to delete.
Deliverables and every derived index can be recomputed. Evidence cannot: it
is the record, and losing it is the only loss the system cannot repair.

## Code here, data there

`pipeline/src/paths.py` is the single seam between pipeline code and disk.
Every path is a function, not a constant, resolving `TOUCHLINE_DATA_DIR` and
falling back to the current working directory at call time; workflow runs
execute with their cwd set to the data repo. Durable data never lives inside
the package, and the TypeScript side holds the same line: `dataHome`
(`src/datahome.ts`) roots every reader and writer at the marked directory.
The consequence is clean separation of lifecycles. The rib can be upgraded or
reinstalled without touching a season file, and the whole data home moves by
changing one environment variable.

Lab: [Read a raw page](../../tutorials/read-a-raw-page/) makes this physical:
you open an archived page from a completed season and rerun a parse against
it offline.

## Related

**Run it**

- [Rebuild from the archive](../../guides/rebuild-from-the-archive/): run the
  staged reparse against a real data home.
- [Create a data home](../../guides/create-a-data-home/): scaffold the four
  tiers this page describes.
- [Data on disk](../../reference/data-on-disk/): the exact layout contract,
  file by file.

**Understand it**

- [Proof before parse](../proof-before-parse/): why each archived page can be
  trusted to be what its filename says.
- [Raw archive as system of record](../../design/raw-archive-as-system-of-record/):
  the decision record, with the alternatives that were rejected.
