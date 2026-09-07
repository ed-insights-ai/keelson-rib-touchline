---
title: The archive is the system of record
description: Raw pages land on disk before any parser reads them; the season files every consumer reads are rebuildable derivatives of that archive.
sidebar:
  order: 2
---

Touchline treats exactly one store as truth: the raw HTML of every page it
fetched, exactly as the site served it. Everything downstream, starting with
the season JSON files the board reads, is a **derivative**: computed from the
archive, rebuildable from the archive, and deletable without losing a single
fact. When a parser improves or a bug is found months later, the fix is to
replay the archive offline, not to crawl the web again and hope it still
says what it said.

## The page lands first

The collector writes the served page to disk before any derived file is
published from it.

The board collector archives per programme through `write_raw_pages`
(`pipeline/src/sidearm_live.py`), which writes
`data/raw_html/{slug}/{year}-{gender}-schedule.html` and the matching roster
and stats pages. Its docstring is the whole rule: archive whatever was
actually served, so any parse can be redone offline. The board entrypoint
(`pipeline/scripts/collect_board.py`) calls it immediately after each
programme's collection, before it assembles a single season file.
Box-score pages sit in the same cache beside the three layer pages, named by
fixture id (`data/raw_html/{slug}/{year}-{gender}-box-{fixture-id}.html`,
every character outside `[A-Za-z0-9._-]` folded to `-`, so
`sidearm:harding:14053` becomes `2026-men-box-sidearm-harding-14053.html`)
under the programme whose schedule page linked them, each with a sidecar
carrying the parser fingerprint; a parser change reparses a stored box from
disk instead of fetching it again. All of those pages live on disk as the
collector's fetch cache, no longer in the data home's git history, and the
daily cadence preserves them as weekly `tar.zst` sets per conference-season
under `~/keelson/archive/raw-html`
([Run the daily cadence](../../guides/daily-cadence/#weekly-raw-html-archive)).

This is what warehouse practice calls a **raw zone** (or bronze layer): an
immutable capture of the source, with every parsed product strictly
downstream of it. The reason is not tidiness. The web does not replay the
past. Sites redesign, past-season URLs redirect to the current season, and a
page you fetched in September may be unfetchable by March. The archive is the
one witness that cannot drift, and [Proof before parse](../proof-before-parse/)
is what guarantees each archived page is the page it claims to be.

## Everything else is a derivative

The stores downstream of the archive are each explicitly rebuildable:

- **Season JSON files**, the consumer deliverable: one schema-tagged file per
  season, gender, and conference (`touchline.fixtures/2`,
  `touchline.rosters/1`, `touchline.stats/1`, `touchline.matches/2`), written
  atomically by `_atomic_json` in `pipeline/scripts/collect_board.py`.
  The collector's conditional-fetch memory means a page verified unchanged is
  re-parsed from the archive rather than re-fetched, so a season already
  collected replays largely offline.
- **Derived indexes**, when one is ever wanted: a SQL index for ad-hoc
  querying can be built from the season files and dropped without losing a
  fact. None is maintained today; the retired Postgres index held exactly
  that standing.

:::note
Re-fetching is not rebuilding. A collect run always proves each page it
relies on, and only the pages whose stored validators no longer hold are
fetched again; everything else replays from the archive. `--refetch` exists
for the deliberate case of collecting as if the home had never seen the
pages.
:::

## Four tiers in the data home

Durable data lives in a **data home**: an ordinary directory marked by
`touchline-data.yaml` and scaffolded by `bootstrapDataHome`
(`src/datahome.ts`). The layout separates four tiers by what it costs to lose
them:

| Tier | Paths | What it holds |
| --- | --- | --- |
| Deliverables | `data/fixtures/`, `data/rosters/`, `data/stats/`, `data/matches/` | The product: schema-tagged season files, one per season, gender, and conference. |
| Evidence | `data/raw_html/`, `data/errors/` | The pages exactly as fetched, plus anything a run could not parse, kept rather than dropped. |
| Reference | `data/reference/` | Curated membership: `membership.json`, resolved by `membership_path` in `pipeline/src/paths.py`. Identity reference lives in code, in `pipeline/src/canon.py`. |
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

- [Rebuild from the archive](../../guides/rebuild-from-the-archive/): re-derive
  the season files against a real data home.
- [Create a data home](../../guides/create-a-data-home/): scaffold the four
  tiers this page describes.
- [Data on disk](../../reference/data-on-disk/): the exact layout contract,
  file by file.

**Understand it**

- [Proof before parse](../proof-before-parse/): why each archived page can be
  trusted to be what its filename says.
- [Raw archive as system of record](../../design/raw-archive-as-system-of-record/):
  the decision record, with the alternatives that were rejected.
