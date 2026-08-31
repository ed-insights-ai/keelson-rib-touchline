---
title: Data on disk
description: The data home tier by tier, the season-file naming contract, and the evidence that backs every deliverable.
sidebar:
  order: 3
---

A Touchline data home is an ordinary directory the consumer owns. The rib
resolves its paths through `src/datahome.ts`; the pipeline resolves every path
through the functions in `pipeline/src/paths.py`, which read
`TOUCHLINE_DATA_DIR` and fall back to the current working directory at call
time. Everything durable in the home derives from fetched pages: the raw
archive is the evidence, and the JSON files beside it are the system of
record that every consumer reads.

## The marker

A directory is a data home when it carries `touchline-data.yaml` at its root
(`MARKER_FILE` in `src/datahome.ts`). The file's `kind` must be
`touchline-data` (`MARKER_KIND`); its `version` defaults to 1.
`dataHomeState` in `src/datahome.ts` classifies any directory:

| State | Meaning |
|---|---|
| `ready` | The marker is present and valid; workflows may run here. |
| `empty` | Nothing but VCS and OS bookkeeping; bootstrap may scaffold. |
| `occupied` | Holds other work; bootstrap refuses unless `force` is set. |
| `foreign` | A `touchline-data.yaml` exists but is not Touchline's; refuse to touch. |
| `missing` | The directory does not exist or cannot be read. |

`bootstrapDataHome` is idempotent: `mkdir -p` for every subdirectory plus a
`writeIfAbsent` for the marker and README, so a re-run fills gaps and
overwrites nothing. Its doc comment fixes the `force` contract: it exists for
the deliberate adoption of a populated directory and must never be set from
an inferred intent.

## Deliverables

| Path | Contents | Schema tag |
|---|---|---|
| `data/fixtures/` | Published schedules | `touchline.fixtures/2` |
| `data/rosters/` | Published rosters | `touchline.rosters/1` |
| `data/stats/` | Published player season statistics | `touchline.stats/1` |
| `data/matches/` | Published per-match box scores | `touchline.matches/1` |

Each directory holds one JSON file per season shard, named
`{season}-{gender}-{conference}.json` by `seasonFileName` in
`src/datahome.ts`, where `{conference}` is the lower-case slug from
`conferenceSlug`. The filename is the index: the inverse regex
`SEASON_FILE_NAME` parses season, gender, and conference back out of it, and
`listSeasons` enumerates seasons by unioning the filenames in the fixtures
and rosters directories, tagging each with `hasFixtures` and `hasRosters`
because a past season commonly has a roster but no schedule.

Readers return a typed `LoadResult` (`absent`, `unreadable`, or `invalid`,
with the path and detail) rather than rendering an empty board. The one
exception is `loadRosterHistory`, which skips unreadable archive seasons:
tenure lines are enrichment and degrade rather than fail the current board.
Field semantics live in [File contracts](../file-contracts/).

## Evidence

| Path | Written by | Contents |
|---|---|---|
| `data/raw_html/{programme}/{season}-{gender}-schedule.html` (also `-roster`, `-stats`) | `write_raw_pages` in `pipeline/src/sidearm_live.py` | The pages exactly as the collector fetched them, so any parse can be redone offline. |
| `data/errors/collect-board-{season}-{gender}-{conference}.json` | `pipeline/scripts/collect_board.py` | A run's named gaps, written alongside the coverage cells that record them. |

## Reference

| Path | Contents |
|---|---|
| `data/reference/membership.json` | Season-windowed conference membership, each window citing its source (`membership_path` in `pipeline/src/paths.py`). |

Identity reference is code, not a data-home file: the institution registry,
alias index, and adjudication ledger live in `pipeline/src/canon.py`, where
the test suite holds every ruling to its evidence contract.

The membership file exists twice, with one authority: the copy shipped
inside the rib package (`membershipPath` in `src/membership.ts` resolves
against the package root) is the source of record, version-controlled and
reviewed, and the data home copy is a deployment artifact mirrored from
it. Pipeline loaders prefer the packaged copy and fall back to the mirror
(`load_membership` in `pipeline/src/membership.py`), collect refreshes the
mirror at the start of every run (`sync_membership_reference` in
`pipeline/scripts/collect_board.py`), and the data-integrity workflow's
`membership-sync` check reports any divergence with the exact diff. Edits
belong in the packaged copy only.

## Working and delivered

Bootstrap creates the deliverable, evidence, and reference directories; each
path below is created on demand by its writer.

| Path | Writer | Contents |
|---|---|---|
| `data/coverage.json` | `pipeline/scripts/collect_board.py` via `pipeline/src/coverage.py` | The `touchline.coverage/1` manifest, merged and never overwritten. |
| `data/scratch/` | `pipeline/scripts/build_digest.py` and the `touchline-report` workflow | `digest-{season}-{gender}-{focus}.json` and the `report-{season}-{gender}-{focus}/` narrative-core and card files; regenerable intermediates. |
| `data/research/{season}-{gender}/` | `touchline-report` research, verify, and merge nodes | `research-{slug}.json`, `verified-{slug}.json`, and the merged `verified.json`. |
| `data/research/players/` | The `touchline-player-profile` research node | `{programme}-{player}.json` findings files. |
| `data/reports/` | `touchline-report` and `pipeline/scripts/render_report.py` | `narrative-{season}-{gender}-{focus}.json`, plus `preseason-{season}-{gender}-{focus}.html` and `.pdf` and their `-appendix` pair. |
| `data/players/{gender}/{programme}/` | `upsert_profile` in `pipeline/src/profile.py` | One accumulating profile per player, filed by `player_key`. |

## Derived stores

There are none to maintain. The JSON data home is the system of record: the
season files are what every consumer reads, and the raw page archive is the
evidence they were parsed from. If a SQL index ever earns its keep for ad-hoc
querying, it can be built from these files and dropped without losing a
fact; that is the standing the retired Postgres index held, and any
successor would hold the same one. Nothing in the rib or the pipeline reads
a database.

## Related

**Run it**

- [Create a data home](../../guides/create-a-data-home/): scaffold the tree this page maps.
- [Rebuild from the archive](../../guides/rebuild-from-the-archive/): re-derive the season files from the evidence tier.
- [Pipeline CLI](../pipeline-cli/): the console scripts that write these paths.

**Understand it**

- [Archive first](../../concepts/archive-first/): why the raw pages are the system of record.
- [Absence is data](../../concepts/absence-is-data/): what the coverage manifest and missing manifests record.
- [Raw archive as system of record](../../design/raw-archive-as-system-of-record/): the decision that shaped every tier here.
