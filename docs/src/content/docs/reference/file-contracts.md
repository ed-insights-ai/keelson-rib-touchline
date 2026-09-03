---
title: File contracts
description: Every versioned schema tag in one place, with the field semantics that carry each file's honesty rules.
sidebar:
  order: 4
---

Every durable JSON file Touchline writes opens with a `schema` string naming
its contract and version. Readers refuse an unknown tag rather than guess:
the four season-file schemas in `src/model.ts` pin the tag with a
`z.literal`, and every object schema is `.strict()`, so an unknown field
fails validation the same way a missing one does.

| Tag | File | Writer | Reader or gate |
|---|---|---|---|
| `touchline.fixtures/2` | `data/fixtures/{season}-{gender}-{conference}.json` | `pipeline/scripts/collect_board.py` | `fixturesFileSchema` in `src/model.ts` |
| `touchline.rosters/1` | `data/rosters/{season}-{gender}-{conference}.json` | `pipeline/scripts/collect_board.py` | `rostersFileSchema` in `src/model.ts` |
| `touchline.stats/1` | `data/stats/{season}-{gender}-{conference}.json` | `pipeline/scripts/collect_board.py` | `statsFileSchema` in `src/model.ts` |
| `touchline.matches/1` | `data/matches/{season}-{gender}-{conference}.json` | `pipeline/scripts/collect_board.py` | `matchesFileSchema` in `src/model.ts` |
| `touchline.digest/1` | `data/scratch/digest-{season}-{gender}-{focus}.json` | `build_digest` in `pipeline/src/digest.py` | `pipeline/src/report.py` and the `touchline-report` gates |
| `touchline.research/1` | `data/research/{season}-{gender}/{conference}/research-{slug}.json` | `touchline-report` research nodes | The `validate-research` gate |
| `touchline.research-verified/1` | `data/research/{season}-{gender}/{conference}/verified-{slug}.json`, merged into `verified.json` | `touchline-report` verify and merge nodes | The `validate-verified` gate |
| `touchline.player-findings/1` | `data/research/players/{programme}-{player}.json` | `touchline-player-profile` research node | The workflow's upsert step refuses any other tag |
| `touchline.report-narrative/4` | `data/reports/narrative-{season}-{gender}-{focus}.json` | `touchline-report` narrative nodes | The `validate-narrative` gate; contract text at the head of `pipeline/src/report.py` |
| `touchline.player-profile/1` | `data/players/{gender}/{programme}/{player}.json` | `upsert_profile` in `pipeline/src/profile.py` | Re-runs read it back and merge findings additively |
| `touchline.coverage/1` | `data/coverage.json` | `pipeline/src/coverage.py`, stamped by `pipeline/scripts/collect_board.py` | `read_coverage` tolerates absence, refuses corruption |

A version bumps when meaning changes. Fixtures are on `/2`;
`pipeline/scripts/migrate_shard.py` accepts a legacy `touchline.fixtures/1`
shard and rewrites what it migrates to `touchline.fixtures/2`.

## Season files

The four board contracts share a header: `schema`, `season`, `gender`, and
`collected_at` (UTC, seconds). Only the fixtures file carries `conference`
and a `programmes` array; for the other three the conference lives in the
filename shard.

### touchline.fixtures/2

| Field | Semantics |
|---|---|
| `home_score`, `away_score` | Nullable integers: null until played, never 0, which is a real scoreline. `isPlayed` in `src/model.ts` is `status === "final"`, and a played game may still carry no score, so anything score-dependent guards on the numbers, never on played-ness alone. |
| `match_type` | The single value `exhibition`, present only when the site itself printed the marking. Absence means a countable game. |
| `conference_game` | Whether the result counts in the conference table. |
| `conference_game_source` (fixture) | Present only when the flag was not published by a schedule page (for example `derived:membership`). Absence means the publisher's own marking. |
| `conference_game_source` (file) | How the run determined flags; `pipeline/scripts/collect_board.py` writes `published:schedule-page`. |
| `membership_extrapolated` | True when membership had to be carried past its authored windows. `resolveConference` in `src/membership.ts` flags the carried-forward result as a well-founded guess, not a cited fact. |
| `date`, `time` | ISO date local to the venue; no timezone is invented. Kickoff is `HH:MM`, absent when the source published no time. |
| `missing` | Programmes whose schedule could not be collected. Never omitted silently. |

### touchline.rosters/1

| Field | Semantics |
|---|---|
| `rosters` | A record keyed by programme slug; each roster names its `source_url`. |
| `number` | Jersey number as printed, a string, because "00" and "0" differ. |
| `weight` | As printed, for example "165 lbs"; only some themes publish it. |
| `missing` | Every programme with no collected players, whether the layer failed or the proven page listed nobody. Named, never dropped. |

### touchline.stats/1

| Field | Semantics |
|---|---|
| Every stat field | Optional: a site prints what its stat crew recorded, and an absent number is "not published", never zero. |
| `points` | 2 × goals + assists, the NCAA points convention. |
| `keepers` | The goalkeeping story is a separate line; keepers also appear in the outfield table when they took a shot. |
| `player_id` | SideArm's own player id, the join key to the roster's bio URL. |
| `missing` | Programmes whose statistics page yielded nothing. Named, never dropped. |

### touchline.matches/1

| Field | Semantics |
|---|---|
| `matches` | A record keyed by fixture id, the same ids the season's fixtures file carries. |
| `teams` | Each side exactly as the box score served it. Names and abbreviations are consistent within a page, not across pages, so `scoring`, `cards`, and `plays` reference sides by index into this array. |
| `home_index` | Which served side is the fixture's home team. Absent when the page gave no way to prove it. |
| `plays` | The text is the record, free prose typed by the home stat crew; `type` exists only where the collector recognized the phrasing, so an untyped play is still a play. The `period` is the page's own section token ("1", "2", "SO"). |
| `missing` | A record of fixture id to the collector's named reason, for played fixtures whose box score could not be collected. |

## touchline.digest/1

The digest is the only source of figures a generated report may cite;
`build_digest` in `pipeline/src/digest.py` computes it from the season files
and nowhere else.

| Field | Semantics |
|---|---|
| `season`, `gender`, `conference`, `focus` | The shard and the focus programme. `conference` is the fixtures file's own display label. |
| `previous_season`, `seasons_held` | The prior season on disk (or null) and every season the shard holds, ascending. |
| `membership_extrapolated` | Carried through from the season's fixtures file. |
| `programmes` | One section per programme, focus first: last-season form and patterns, availability flags, discipline, keepers, usage shifts, roster shape, turnover, top returning players, and (for opponents) head-to-head history and fixtures against the focus. |
| `sources` | The `collected_at` stamp of every season file the digest read. |

## touchline.research/1 and touchline.research-verified/1

Research files are written by agents under fetch-to-verify rules; the shapes
are contracted in `workflows/touchline-report.yml` and normalized by
`pipeline/scripts/normalize_research.py`.

| Field | Semantics |
|---|---|
| `coach` | The standing answer for a programme: `name`, `status` (`new`, `returning`, `unknown`), `since_season`, `text`, `source`, `url`, `date`, `confidence`. |
| `findings` | Each carries `player`, `type` (`summer-league`, `honor`, `news`, `coach`, `signing`), `text`, `source`, `url`, `date`, and `confidence` (`high` or `medium`). A finding exists only if it can be verified at a URL. |
| `attested_uncaptured` | Claims believed but not capturable at a URL. They never sit in `findings`. |
| `unswept` | Clubs or leagues whose roster could not be read, with the reason. |
| `clubs_checked` | The sweep record. |

The verified file keeps six required keys: the `schema` tag, surviving
`findings` unchanged, a `coaches` map with exactly one entry per programme
file, `dropped` (each with `programme`, `text`, `reason`),
`attested_uncaptured`, and `unswept`. A coach
whose page does not support the claim is downgraded to `unknown`, never
dropped from the map; `merge-verified` folds the per-programme files into
`verified.json`.

## touchline.player-findings/1

The `touchline-player-profile` workflow's research output, one file per
player at `data/research/players/{programme}-{player}.json`, where
`{player}` is the `player_key` slug: `player`,
`programme`, `findings` (types `summer-league`, `honor`, `news`, `signing`,
`transfer-trail`), `attested_uncaptured`, `unswept`, and `searched`. The
workflow's upsert step rejects a file whose `schema` is not
`touchline.player-findings/1`, and the profile keeps its previous findings.

## touchline.report-narrative/4

The prose half of a report, validated by the `validate-narrative` gate and
rendered by `pipeline/src/report.py`, whose module docstring is the contract
text. The narrative never carries a number the digest does not; missing
sections render as explicit placeholders so the deterministic skeleton
always ships.

| Field | Semantics |
|---|---|
| `headline`, `exec` | `exec` holds `bottom_line`, exactly three `findings` (each with `evidence`, `meaning`, `implication`, a label, a confidence), at most three `decisions`, and `priorities`. |
| `landscape`, `focus` | One page of prose beside the table and chart; the focus team's `overview`, `roster`, `news`, and `offseason` ledger. |
| `programmes` | Per-opponent card material: `threat`, `vulnerability`, `roster_note`, `implication`, optional `coach`, `news`, and a `tier` (`benchmark`, `swing`, `update`). |
| `watchlist` | Up to two players per opponent, each with a `label`, a `why`, and a `verify` line. No focus-team entries. |
| Labels | `observed`, `projected`, `signal`, `judgment`; confidence is `high`, `medium`, or `low`. `signal` marks an observed pattern whose cause is unverified. |

## touchline.player-profile/1

One file per player under `data/players/{gender}/{programme}/`, in two
halves with different update rules (`upsert_profile` in
`pipeline/src/profile.py`).

| Field | Semantics |
|---|---|
| `player`, `key`, `programme`, `gender` | Identity; `key` is the `player_key` filename slug. |
| `first_built`, `updated_at` | The first build stamp survives re-runs; `updated_at` moves. |
| `identity`, `career`, `keeper_career`, `appearances`, `availability_flags`, `seasons_searched` | The assembled record, deterministic and replaced with fresh truth on every build. `keeper_career` appears only when the player has keeper lines. |
| `findings`, `attested_uncaptured`, `unswept` | Merged additively from findings files; re-runs deduplicate findings on (`url`, `text`) rather than replace. |

`assemble_record` raises when the data home has no trace of the player at
all, so a name typo cannot masquerade as a person.

## touchline.coverage/1

The manifest at `data/coverage.json`, merged and never overwritten, written
atomically (`pipeline/src/coverage.py`).

| Field | Semantics |
|---|---|
| `cells` | Keyed `{season}/{gender}/{programme}/{layer}` by `cell_key`. |
| Cell `state` | One of `complete`, `empty`, `unavailable`, `no-collector`. [Absence is data](../../concepts/absence-is-data/) owns what each state means. |
| Cell stamps | `season`, `gender`, `programme`, `layer`, `confirmed_at`, `collector`, plus `reason`, `count`, and `source_url` when they exist. |
| Cell `verified` | The single value `unchanged`, present only when the conditional fetch reused a page the server said had not changed. A marker, not a state: `state` is still the layer's outcome. |
| `updated_at` | Set on every merge. |

## Contract fixtures

The tags above are read by strict schemas outside this repository, and a
strict reader refuses a whole file for one unknown field. The `contracts/`
directory at the package root publishes one sample per schema that crosses
that boundary (`coverage-1.json`, `fixtures-2.json`, `rosters-1.json`,
`stats-1.json`, `matches-1.json`, and the untagged `membership.json`), each
cut from real collector output and trimmed to the fewest rows that still
exercise every field, every optional, and every enumerated value the writer
can emit.

Two tests hold the writers to them. `pipeline/tests/test_contracts.py` runs
a full collect and reduces every payload to shape facts (field path, JSON
kind, and the value where the field is enumerated); a fact the fixture lacks
fails the suite, so a writer that starts emitting a new value breaks here,
in CI, rather than on the published build. `test/contracts.test.ts` proves
each fixture parses under the rib's own strict zod schemas (`src/model.ts`,
`src/coverage.ts`, `src/membership.ts`). A contract change therefore lands
in one commit as the writer, its fixture, and a line in
`contracts/CHANGELOG.md`. Setting `TOUCHLINE_CONTRACT_DATA_DIR` to a data
home root runs the same check over every season file and the manifest it
holds.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): the run that writes the four season files and the coverage manifest.
- [Data on disk](../data-on-disk/): where every file on this page lives.
- [Gates and exit codes](../gates-and-exit-codes/): the gates that enforce these tags mid-workflow.

**Understand it**

- [Absence is data](../../concepts/absence-is-data/): the null-not-zero and missing-manifest rules these fields encode.
- [The determinism boundary](../../concepts/the-determinism-boundary/): why the digest is the only number source a report may quote.
- [Contracts beat examples](../../design/contracts-not-examples/): why prompts read these contracts instead of sample files.
