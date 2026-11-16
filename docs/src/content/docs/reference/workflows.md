---
title: Workflows
description: "The five Touchline workflows as contracts: node chains, gates and their failure conditions, locking, the KEELSON_INPUTS_* env contract, model pinning, and exit semantics."
sidebar:
  order: 2
---

Five workflows ship in `workflows/`: `touchline-collect`, `touchline-backfill`, `touchline-report`, `touchline-player-profile`, and `data-integrity`. This page is their contract. The generic node model (bash, prompt, loop, and bun nodes; `until_bash`) is the harness's: see keelson's [workflow nodes reference](https://danielscholl.github.io/keelson/docs/reference/workflow-nodes/). The full assertion list per gate lives in [Gates and exit codes](../gates-and-exit-codes/).

## How inputs reach nodes

The env and substitution contract is the harness's, in the workflow nodes reference linked above. The detail worth naming here: hyphens in a node id become underscores in the variable name, so the `resolve-pipeline` node's output reaches downstream bash as `KEELSON_NODE_resolve_pipeline_OUTPUT`.

## Locking

| Workflow | `requiresProject` | `mutates_checkout` | `locking` | `webSearchMode` |
|---|---|---|---|---|
| `touchline-collect` | `false` | `true` | exclusive (default) | unset |
| `touchline-backfill` | `false` | `true` | exclusive (default) | unset |
| `touchline-report` | `false` | `true` | exclusive (default) | `live` |
| `touchline-player-profile` | `false` | `true` | `shared` | `live` |
| `data-integrity` | `true` | `true` | exclusive (default) | unset |

In Keelson, `requiresProject: true` means the working directory must be a git repository. A Touchline data home is an ordinary registered directory, so the four data-home workflows set it `false`; the selected project still supplies the working directory. `data-integrity` runs against the data repo, which is a git checkout, and requires one.

`mutates_checkout: true` takes the mutation lock on that directory: two collects into one data home would race on the same season file. `touchline-player-profile` adds `locking: shared` because it writes only per-player files (`data/players/...`, `data/research/players/...`), disjoint between runs: profile runs fan out in parallel against one data home while staying mutually exclusive with a mutating collect.

## touchline-collect

Collects a conference or one programme for one season into the data home. Inputs: `conference`, `gender`, `season` (required); `programmes` (optional, comma-separated slugs to narrow the run; empty means the whole conference), `layers` (defaults to `schedule,roster,stats,matches`) and `membership_extrapolated` (optional).

| Node | Kind | Contract |
|---|---|---|
| `preflight` | bash | Refuses (exit 1) a directory without a `touchline-data.yaml` marker, a marker not declaring `kind: touchline-data`, any empty required input, or a season that is not a four-digit year |
| `resolve-pipeline` | bash | Resolves the pipeline directory: `TOUCHLINE_PIPELINE_DIR`, else `packageDir` from `rib-touchline/config.json` under the Keelson home (`KEELSON_HOME`, defaulting to `~/.keelson`), else the installed package path; ALARM exit 1 when no candidate holds a `pyproject.toml` |
| `level-guard` | bash | `bun bin/resolve-membership.ts guard {cwd} {conference}`: REFUSED exit 1, naming the conference's NCAA level and the data home's, when they differ, when the conference has no profile, or when the marker states an invalid level; a marker with no `level` is read as `d2` with a `NOTE` saying so. Runs before anything is resolved or fetched |
| `resolve-programmes` | bash | Prints one line, `{extrapolated} {slug,slug,...}`. With a `programmes` input it passes that list through with the `membership_extrapolated` input as the flag. With none it runs the rib's `bin/resolve-membership.ts conference` against the packaged `data/reference/membership.json`, the same `resolveConference` the `touchline_collect` tool calls, carrying the last authored window forward past the authored range and flagging it; REFUSED exit 1 when no member resolves, ALARM exit 1 when the resolver is not beside the pipeline |
| `collect` | bash | Runs `collect-board` with `TOUCHLINE_DATA_DIR` set to the data home, forwarding the inputs and the resolved list, adding `--membership-extrapolated` when the resolved flag is `true`; ALARM exit 1 when the resolved line carries no list; otherwise propagates the collector's exit code |
| `report` | prompt | Short completion summary; every figure must appear in the upstream node text, and gaps are named, never softened |

Exit semantics: exit 0 from `collect` is a defined claim, the coverage manifest was written and describes reality, gaps included. A non-zero exit means no manifest was written, and nothing printed above it is a claim that data landed.

The resolver behind `resolve-programmes` is also a command line for anything outside the rib's TypeScript, such as the daily cadence script: `bun bin/resolve-membership.ts conference {conference} {gender} {season}` prints the flag and the member list, and `bun bin/resolve-membership.ts conferences {gender}` prints, sorted on one line, every advertised conference that authors at least one membership window for that gender. With `--level d1|d2|d3` that line keeps only the conferences whose `conference_profiles` entry names that NCAA level, and the command exits 1 when none do or when a conference carries no profile; without the flag the line is level-blind, as it always was. With `--season {YYYY}` it keeps only the conferences at least one programme resolves to that season, naming each one it leaves out on stderr (`skipped (no men 2026 members): WAC`). `home-level {dir}` prints a data home's level (`d1 declared`, or `d2 assumed` for a marker with none) and `guard {dir} {conference}...` is the level check `level-guard` runs. None names a conference; all read the packaged record.

A season past a conference's last authored window carries its last members forward, flagged, except a programme whose own windows already cover the season: it is wherever they put it (the same rule as `conference_in_effect` in `pipeline/src/membership.py`). An ended conference therefore resolves to nobody rather than to last year's members.

## touchline-backfill

Collects one conference over a season range into the data home, one collect node per season, under the same exclusive lock as `touchline-collect`. Inputs: `conference`, `gender`, `from_season`, `to_season` (required, inclusive, at most 8 seasons per run); `layers` (optional, defaults to all four); `refetch` (optional, `true` re-fetches every stored box score and page instead of reusing the ones whose fixture results are unchanged, for a parser change; every collect slot then passes `--refetch`).

| Node | Kind | Contract |
|---|---|---|
| `preflight` | bash | Marker and `kind` check; REFUSED while this data home's own cadence holds its PID lock (the default home's `~/.keelson/locks/touchline-collect-cadence.lock`, any other home's `touchline-collect-cadence.{dir name}.lock`; another home's cadence is no reason to refuse); required inputs; `gender` in `men` or `women`; both seasons four-digit years; REFUSED exit 1 when `from_season` is after `to_season` or the range is longer than the wired slots (`MAX_SEASONS=8`, split the range and run twice) |
| `resolve-pipeline` | bash | Same resolution chain as touchline-collect, plus an ALARM when the rib package beside the pipeline carries no `bin/backfill-slot.sh` |
| `level-guard` | bash | The same level check as touchline-collect's, before the first slot |
| `collect-1` to `collect-8` | bash | Each runs `bin/backfill-slot.sh` with `SLOT={n}`; the slot's season is `from_season + n - 1`. A slot past `to_season` prints `SKIPPED` and exits 0. Otherwise the slot resolves its own members for that season through `bin/resolve-membership.ts`, REFUSES when none resolve, and runs `collect-board` exactly as touchline-collect does, propagating its exit code. Slots chain in order with `trigger_rule: all_done`, so one failed season is reported and the later seasons still run |
| `report` | prompt | `trigger_rule: all_done`, `always_run: true`; one line per season, collected, failed with the printed reason, or did not run; a failed season is never folded into a total |

Why one node per season: a single node cannot hold a whole range inside the node budget (the LSC backfill measured about two thirds of one node's headroom per season), so each season carries its own 15 minute budget. Each season is written as its own season file, so a failed slot leaves the other seasons' files as their own collects left them.

## touchline-report

Builds the preseason scouting briefing for a collected season. Inputs: `season`, `gender`, `conference`, `focus` (all required). Each loop's text exit (`ALL RESEARCHED`, `ALL VERIFIED`, `ALL CARDS WRITTEN`) is a declaration; completion is decided by `until_bash`. All three loops run with `fresh_context: true` and `max_iterations: 24`, a load-time safety cap that a larger supported conference requires raising.

| Node | Kind | Depends on | Contract |
|---|---|---|---|
| `preflight` | bash | | Marker and `kind` check; required inputs; four-digit season; `gender` in `men` or `women`; the collected shard `data/fixtures/{season}-{gender}-{conference}.json` must exist, else REFUSED with "run touchline-collect first" |
| `conference-shard` | bash | `preflight` | Normalizes the conference input to its shard slug |
| `resolve-pipeline` | bash | `preflight` | Same resolution chain as touchline-collect; ALARM when nothing resolves |
| `digest` | bash | `resolve-pipeline` | Runs `build-digest`; the digest is rebuilt on every run and is the sole source of numbers downstream |
| `programme-count` | bash | `digest` | ALARM exit 1 when the digest is missing, unparseable, or lists zero programmes |
| `research` | loop | `digest`, `conference-shard`, `programme-count` | One programme per iteration, writing `data/research/{season}-{gender}/{conference}/research-{slug}.json` (`touchline.research/1`); `until_bash` passes only when every digest programme has a research file carrying a top-level `coach` object in that conference's pool, so a neighbouring conference's files can never end the sweep early |
| `validate-research` | bash gate | `research` | ALARM exit 1 when any digest programme lacks a research file, or its coach object lacks a name or a status in `new`, `returning`, `unknown` |
| `verify` | loop | `validate-research` | Adversarial pass, one programme per iteration: re-fetch every finding's URL trying to refute it, write `verified-{slug}.json` (`touchline.research-verified/1`); `until_bash` requires every per-programme file to exist and be newer than the digest |
| `merge-verified` | bash gate | `verify` | Validates each per-programme file with `jq -e` (schema tag, `findings` array, a `coaches` map holding exactly that programme's slug, `dropped`, `attested_uncaptured`, and `unswept` arrays), re-checks staleness, then merges deterministically with `jq -s` into `verified.json`, written via temp file and `mv -f` |
| `validate-verified` | bash gate | `merge-verified` | ALARM when `verified.json` is missing a required key, or its `coaches` map holds fewer entries than the research files carry coach objects (verify downgrades an unsupported coach to `unknown` but never drops it from the map) |
| `normalize` | bash | `validate-verified` | Runs `normalize-research`; `pipeline/scripts/normalize_research.py` rewrites each research file into the canonical line-per-fact layout only when `canonical()` round-trips to identical data, and exits 1 when any file had to be skipped |
| `narrative-core` | prompt | `normalize` | Writes `narrative-core.json` (`touchline.report-narrative-core/1`) from the digest and `verified.json` only |
| `narrative-cards` | loop | `normalize` | One opponent card per iteration (`touchline.report-narrative-card/1`); `until_bash` requires a `card-{slug}.json` newer than the digest for every non-focus programme |
| `assemble-narrative` | bash gate | `narrative-core`, `narrative-cards` | Validates the core and every card (schema tags, `programme` matching the slug, tier in `benchmark`, `swing`, `update`, a watchlist of at most 2 whose entries carry the slug and a legal label), then merges into `data/reports/narrative-{season}-{gender}-{focus}.json` under `touchline.report-narrative/4`, via temp file and `mv -f` |
| `validate-narrative` | bash gate | `assemble-narrative` | The last gate before render; assertions below |
| `render` | bash | `validate-narrative` | Runs `render-report` |
| `summary` | prompt | `render` | Completion summary; names what was dropped, attested-but-uncaptured, or unswept exactly as reported |

`validate-narrative` fails the run (ALARM, exit 1) when any of these does not hold: schema `touchline.report-narrative/4`; exactly 3 executive findings; 1 to 3 decisions; an offseason ledger of at most 3 items; the evidence and meaning fields present on every finding; no machinery words in any string (`digest`, `roster shape`, `roster_shape`, `verified pool`); word budgets measured with `wc -w` (bottom line at most 70 words, landscape 100, focus overview 110); each watchlist `why` at most 90 words; no dossier section; a watchlist holding at most 2 profiles per opponent, none for the focus side, only known programme slugs.

### Staleness is a timestamp

The digest is rebuilt at the start of every run, and everything derived from it must be newer than it. The `verify` and `narrative-cards` loops' `until_bash` checks test each per-programme file against the digest with the shell's `-nt` comparison, and `merge-verified` and `assemble-narrative` re-test the same condition before merging, alarming on "missing or stale". Last run's verification and cards cannot satisfy this run's gates.

### Model pinning

Model classes silently resolve to the smallest tier on this provider, so the workflow pins literal model ids. Loop nodes take the workflow-level model and effort (per-loop overrides are dropped), which is why the research tier lives at workflow level.

| Where | Model | Effort |
|---|---|---|
| Workflow level, inherited by the `research`, `verify`, and `narrative-cards` loops | `gpt-5.6-terra` | `medium` |
| `narrative-core` | `gpt-5.6-sol` | `xhigh` |
| `summary` | `gpt-5.6-luna` | default |

## touchline-player-profile

Builds or enriches one player's profile. Inputs: `player`, `programme`, `gender`, `conference` (all required).

| Node | Kind | Contract |
|---|---|---|
| `preflight` | bash | Marker check; required inputs; `gender` in `men` or `women` |
| `resolve-pipeline` | bash | Same resolution chain; ALARM when nothing resolves |
| `assemble` | bash | Runs `build-profile` to assemble the deterministic record; fails when the player has no trace in the collected season files, so a typo cannot masquerade as a person |
| `research` | prompt (`gpt-5.6-terra`, `medium`, fresh context) | Researches the one player under `prompts/player-profile.md` and `prompts/research-protocol.md`; writes `touchline.player-findings/1` at `data/research/players/{programme}-{player-key}.json` inside the data home |
| `verify` | prompt (`gpt-5.6-luna`, fresh context) | The adversarial refute pass: re-fetches every finding's URL and rewrites the same file in place, moving each dropped claim into a `dropped` array with a one-line reason |
| `merge` | bash | Slugifies the player key (lowercase, `iconv //TRANSLIT`, hyphenated); rescues a findings file mistakenly written relative to the rib repo; ALARM exit 1 when the file is missing or is not a valid `touchline.player-findings/1`; then runs `build-profile --findings` followed by `normalize-research` |
| `summary` | prompt (`gpt-5.6-luna`) | States where the profile lives and that re-runs enrich rather than replace |

Exit semantics: when `merge` alarms, the profile keeps its previous findings, because the upsert never ran. The merge is additive by contract: re-running the workflow enriches `data/players/`, never replaces it.

## data-integrity

Answers which numbers in the touchline data home are currently trustworthy. It is read-only end to end: nothing it runs writes to the home.

Three check nodes run independently, then a `report` node aggregates. All of them read the working directory, which is the data home:

| Node | Measures |
|---|---|
| `collect-gaps` | collect-board gap ledger files waiting under `data/errors`, each naming the layers a run could not prove |
| `goal-attribution` | per-programme scoreboard goals (fixtures layer, exhibitions and scoreless finals excluded and counted) against summed player goals (stats layer), every divergence named with both figures; programmes present in one layer but not the other |
| `membership-sync` | the data home's `data/reference/membership.json` against the rib's packaged source of record, canonicalized with `jq -S` so only data can differ; a divergence warns with the exact unified diff printed above the verdict line and the install command in the cause |
| `twin-check` | every match collected from both sides (same date, same two slugs, two season files) against itself: the unordered score and the status must agree; a disagreement warns with every record of the pair named above the verdict line. Which side each file calls home is not compared, since a neutral-site tournament legitimately differs there |
| `box-vs-fixture` | every collected box score against its fixture BY TEAM NAME: each published team name is resolved through the collector's identity rules and the score the box gives the fixture's home slug must equal `home_score` (likewise away); reversed and different scorelines are named, a stored `home_index` that disagrees with the names is named, and a box whose names resolve to neither slug is counted as unresolved, never passed. A pipeline script (`check-box-scores`), run by the node |
| `player-identity` | who each box-score line is: `player_ref` coverage per matches file by route (`page`, `twin`, `roster`, `key`), the owner side's `page` share, the lines that fell to `key` and why (`no_roster`, `roster_no_ids`, `not_on_roster`, `ambiguous`, `number_differs`, `no_number`, `unoriented`), and every line where the opponent's own box and the roster name different ids (one of the two is wrong). A file still under `touchline.matches/1` is measured by a fresh resolution and named as legacy, never counted as zero. A pipeline script (`check-player-identity`), run by the node |
| `report` | bun script; renders the per-check table and one final JSON verdict line |

The contract, uniform across the checks:

- **Fail closed.** Every captured variable is asserted non-empty; any empty one prints a `CHECK DID NOT RUN` headline naming the failed captures and stating they are failed measurements, not measurements of zero. A missing or unreadable directory is never a clean zero.
- **Monitors exit 0.** A check signals failure through the `alarm` verdict in its one-line JSON payload, never through its exit code; even a check that cannot run prints its `CHECK DID NOT RUN` alarm and exits 0.
- **Severity only rises.** Each verdict starts at `ok` and moves only upward, `ok` to `warn` to `alarm`, so a later assignment can never undo an earlier signal.
- **One verdict.** The `report` node (`runtime: bun`, `always_run: true`, `trigger_rule: all_done`) parses each check's last JSON line from `KEELSON_NODE_{id}_OUTPUT`, rendering an alarm row for a check whose output is empty or unparseable, and prints the worst verdict: any alarm makes the run ALARM, else any warn makes it WARN, else CLEAR.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): touchline-collect as a task.
- [Run a scouting report](../../guides/run-a-report/): touchline-report end to end.
- [Gates and exit codes](../gates-and-exit-codes/): the full assertion list per gate.

**Understand it**

- [The model declares, the validator decides](../../concepts/gates/): why a gate follows every generative node.
- [The determinism boundary](../../concepts/the-determinism-boundary/): which nodes may be generative at all.
