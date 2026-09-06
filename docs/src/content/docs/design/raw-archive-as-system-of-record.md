---
title: The raw archive as system of record
description: The decision to hold raw served HTML as the only system of record, treat every other store as derived, and replay parser fixes offline, with the alternatives that were rejected.
sidebar:
  order: 5
---

**Status: historical decision record, 2026-09-06.** The Postgres/parquet
lineage was retired (bead tl-hzp); the system of record is the JSON data home
written by `pipeline/scripts/collect_board.py`, with raw HTML kept as a fetch
cache (bead tl-ttj). That evidence now lives on disk under `data/raw_html`,
outside the data home's git history, and in the weekly `tar.zst` sets the
cadence writes under `~/keelson/archive/raw-html`
([Run the daily cadence](../../guides/daily-cadence/#weekly-raw-html-archive)).

## Decision

Touchline holds exactly one store as truth: its archive of raw HTML, each
page kept verbatim as the site served it. The season JSON files, the
parquet shards, and the Postgres database are derived stores: recomputable,
deletable, and never the place a fact lives. A parser fix is a replay of the
archive, never a second crawl. This page is the decision record;
[Archive first](../../concepts/archive-first/) is the concept page that walks
the mechanism in full.

## Mechanism

Archival comes before parsing. On the historical lineage,
`GameFetcher.fetch` (`pipeline/src/fetcher.py`) writes the response text under
`data/raw_html/{school}/{year}/` before returning it to the parser, and reads
cache-first, so a warm rerun parses disk rather than network. On the live
lineage, `collect_programme` (`pipeline/src/sidearm_live.py`) captures the
served page before its parser runs, and `pipeline/scripts/collect_board.py`
calls `write_raw_pages` right after each programme's collection, before any
season file is assembled. The docstring of `write_raw_pages` is the whole
rule: archive whatever was actually served, so any parse can be redone
offline.

Every derived store says it is derived. `pipeline/CLAUDE.md` declares the
parquets ignored build output, rebuilt offline with `uv run reparse`, and
`pipeline/src/paths.py` annotates the database DSN as a derived index that is
never the system of record. The corollary is sharp: `uv run scrape` is not an
offline command even with a warm cache, because discovery always hits the
network. Backfills go through `reparse`, never `scrape`.

The rebuild is all-or-nothing. `pipeline/scripts/reparse.py` reparses every
archived game page under `data/raw_html/` against the `data/source_urls.csv`
provenance manifest, builds the parquet tree in a staging directory,
validates every expected output with `_validate_staged_output`, and swaps it
into place with backup and rollback in `_publish_staged_output`.

## Rejected alternatives

**The database as system of record.** The web does not replay the past:
sites redesign, and past-season URLs redirect to the current season (see
[Proof before parse](../../concepts/proof-before-parse/)). A record that
cannot be re-derived from kept evidence is only as good as its last
migration, and every parser fix becomes a destructive one. As a derived
index, Postgres can be dropped and reloaded without ceremony.

**Parse at fetch, retain no raw.** Parser bugs surface long after the fetch.
The gh-21 orientation bug
([Reading hostile HTML](../../concepts/reading-hostile-html/) tells it) was
audited after the fact by `pipeline/scripts/check_sidearm_captions.py`, which
re-parses every cached SideArm page against the stored rows; without the
archive, the affected population would have been unknowable, let alone
repairable.

**Store only structured output.** A parsed value embodies one day's
understanding of a hostile layout. Keeping the value and dropping the page
freezes that understanding: the value can never be re-questioned when the
parser improves.

## Failure semantics

A parse failure is debuggable forever. The failing page is already archived,
and `log_parse_error` (`pipeline/src/parser.py`) writes a forensics artifact
under `data/errors/{year}/` carrying the traceback plus every table's shape,
columns, and first row, so the failure reproduces offline without a refetch.
The live collector records named gaps to `data/errors/` as
`collect-board-{season}-{gender}-{conference}.json` instead of failing the
run. And a failed reparse publishes nothing: validation runs against the
staged tree, and the swap restores the prior tree on error, so a reader sees
the old complete tree or the new one, never a half-written mixture.

## Related

**Run it**

- [Rebuild from the archive](../../guides/rebuild-from-the-archive/): run the staged offline reparse against a real data home.
- [Data on disk](../../reference/data-on-disk/): the exact layout contract for the archive and its derivatives.

**Understand it**

- [Archive first](../../concepts/archive-first/): the concept page, with the four data-home tiers and the delete-safety story.
- [Proof before parse](../../concepts/proof-before-parse/): why each archived page can be trusted to be the page its name claims.
