---
title: Data on disk
description: The data home tier by tier, the season-file naming contract, and the two derived stores rebuilt from it.
sidebar:
  order: 3
---

A Touchline data home is an ordinary directory the consumer owns. The rib
resolves its paths through `src/datahome.ts`; the pipeline resolves every path
through the functions in `pipeline/src/paths.py`, which read
`TOUCHLINE_DATA_DIR` and fall back to the current working directory at call
time. Everything durable in the home derives from fetched pages, and the two
stores at the foot of this page (the parquet tree and the Postgres index) are
derived again from those files: both rebuildable, neither the system of
record.

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
| `data/raw_html/{programme}/{season}-{gender}-schedule.html` (also `-roster`, `-stats`) | `write_raw_pages` in `pipeline/src/sidearm_live.py` | The pages exactly as the live collector fetched them, so any parse can be redone offline. |
| `data/raw_html/{school}/{year}/game_{n}.html` | The legacy box-score archive | Read back by `pipeline/scripts/reparse.py` to rebuild the parquet tree without network access. |
| `data/source_urls.csv` | `source_urls_path` in `pipeline/src/paths.py` | The URL ledger `reparse` pairs with the legacy archive. |
| `data/errors/{year}/` | `pipeline/src/parser.py` | Per-game JSON error reports, kept rather than dropped. |
| `data/errors/collect-board-{season}-{gender}-{conference}.json` | `pipeline/scripts/collect_board.py` | A live run's named gaps, written alongside the coverage cells that record them. |

## Reference

| Path | Contents |
|---|---|
| `data/reference/canon.json` | The team-string identity artifact, built and checked against the database by `pipeline/scripts/build_canon.py` (`canon_path` in `pipeline/src/paths.py`). |
| `data/reference/membership.json` | Season-windowed conference membership, each window citing its source (`membership_path` in `pipeline/src/paths.py`). |

The membership file exists twice, with one authority: the copy shipped
inside the rib package (`membershipPath` in `src/membership.ts` resolves
against the package root) is the source of record — version-controlled and
reviewed — and the data home copy is a deployment artifact mirrored from
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

## The parquet tree

The first derived store. `pipeline/src/storage.py` writes it under
`data/structured/`:

| Path | Contents |
|---|---|
| `data/structured/{school}/{year}/` | `games.parquet`, `player_stats.parquet`, `events.parquet`, `team_stats.parquet` for one school season (`save_season`). |
| `data/structured/{school}/all/` | That school's seasons merged (`merge_all_seasons`). |
| `data/structured/all/` | Every configured school merged (`merge_all_schools`). |

`merge_all_seasons` ignores its deprecated `years` parameter and rescans
every numeric season directory on disk, so updating one season cannot
truncate the merged archive. `merge_all_schools` recovers school identity
from the key itself: `game_id` encodes `ordinal * 1_000_000 + year * 100 +
game_num` (`pipeline/src/config.py`, whose `load_schools` raises on duplicate
ordinals), so the merge filters on `game_id // 1_000_000`. Events carry a
content-addressed `event_id` (`_assign_event_ids`: SHA1 over lowercased
identity fields plus an occurrence counter) and merges drop duplicates on it.
`pipeline/scripts/reparse.py` rebuilds the whole tree offline from
`data/raw_html/` and `data/source_urls.csv`; `pipeline/scripts/export.py`
copies the four merged parquets from `data/structured/all/` to a flat
directory.

## The Postgres index

The second derived store, loaded from the merged parquets by
`pipeline/scripts/load_db.py`. The DSN is `DATABASE_URL`, else
`FALLBACK_DATABASE_URL` in `pipeline/src/paths.py`, whose comment states the
frame: the database is "rebuildable from the files under data_root(); it is
never the system of record."

| Table | Kind | Key |
|---|---|---|
| `schools` | Dimension | `SERIAL` id, unique `abbreviation`. |
| `games` | Fact | Natural primary key `game_id`. |
| `team_game_stats`, `player_game_stats`, `game_events` | Children | `SERIAL` surrogate id, foreign keys to `games` and `schools`. |
| `opponents` | Reference | Unique `name`; migration 006's comment: "Populated on scrape; conference/division filled over time." |

The migrations in `pipeline/migrations/` are idempotent
(`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`,
`ON CONFLICT ... DO NOTHING`) and transactional. NULL semantics are written
into the schema itself as `COMMENT` entries:

| Column | Semantics |
|---|---|
| `games.is_conference_game` | "True if game counts toward conference standings. From SideArm is_conference flag." Defaults to NULL, meaning unknown (migration 005). |
| `games.home_conference` | "Conference of the scraping school (always known from schools.conference)." |
| `games.away_conference` | "Conference of opponent. NULL = unknown. Filled as opponent registry grows." |
| `games.neutral_site` | "True only when source venue evidence identifies a neutral site." Defaults to false (migration 008). |
| `opponents.verified_at` | `TIMESTAMP DEFAULT NULL`, stamped as opponents are verified over time (migration 006). |
| `schools.gender`, `schools.enabled` | Mirror the `gender` and enablement flags of `config/schools.toml` (migration 007). |

The loader keeps reloads safe: `games` upserts with
`ON CONFLICT (game_id) DO UPDATE` and `COALESCE` on the three conference
columns, so a NULL re-load never erases a known value; the keyless child
tables reload by delete-then-insert scoped to the school and its game set.

## Related

**Run it**

- [Create a data home](../../guides/create-a-data-home/): scaffold the tree this page maps.
- [Rebuild from the archive](../../guides/rebuild-from-the-archive/): regenerate both derived stores from the evidence tier.
- [Pipeline CLI](../pipeline-cli/): the console scripts that write these paths.

**Understand it**

- [Archive first](../../concepts/archive-first/): why the raw pages are the system of record.
- [Absence is data](../../concepts/absence-is-data/): what the coverage manifest and missing manifests record.
- [Raw archive as system of record](../../design/raw-archive-as-system-of-record/): the decision that shaped every tier here.
