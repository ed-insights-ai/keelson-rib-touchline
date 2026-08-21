---
title: Surface, tools, and keys
description: "The board surface registration, the five chat tools and their input fields, the /touchline command, the board action payloads, and the rib:touchline:board snapshot key."
sidebar:
  order: 1
---

The rib registers one surface, one view, one agent, one command, and five chat tools, all from `src/index.ts`. This page is the contract for that surface area. The generic model (what a rib, a surface, and a snapshot key are) belongs to the harness: see keelson's [snapshots and surfaces](https://danielscholl.github.io/keelson/docs/concepts/snapshots-and-surfaces/) and the [rib contract](https://danielscholl.github.io/keelson/docs/reference/rib-contract/).

## Surface and view

| Registration | Value |
|---|---|
| Rib id | `touchline` |
| Surface | `TOUCHLINE_SURFACE_ID` (`touchline`), `projectScoped: true`, one header panel and no rows |
| View | `BOARD_KEY` with `canvasKind: "html"`: a self-contained markup string rendered in a sandboxed iframe |
| Agent | slug `touchline`; the chat seed is built live from the current scope by `buildSeed` (project, home state, collected seasons, known conferences and programmes) |
| Command | `/touchline`, argument hint `folder-name (optional)` |

The board is the only panel and it holds no forms: every write path (init, collect, focus, remove) lives in the chat tools behind the surface's agent. `registerTools` registers the composer with the snapshot manager under `BOARD_KEY`; a composer that throws renders a failure sheet rather than leaving the previous frame, and one delayed re-seed (`SEED_RETRY_MS`) repaints past the boot race where projects have not loaded yet. The viewed season's collection timestamp rides the panel byline (`stampPanel`), invalidating the manifest only when it changed. `onRunEvent` nudges a recompose when a `touchline-collect` run reports `succeeded`; delivery is not guaranteed, so it is a nudge, never the only path.

## The five chat tools

Defined in `src/tools.ts`, returned by `registerTools` in the order below. Every handler is wrapped by `guarded()`, so a thrown error becomes an error tool result rather than an escaped exception. Where a tool takes an optional `project`, an explicit name wins and the board's current scope is the fallback; ambiguity is reported, never guessed (`pickProject`).

| Tool | Input fields | State-changing | Requires confirmation |
|---|---|---|---|
| `touchline_init` | `name` (required) | yes | no |
| `touchline_status` | `project` | no | no |
| `touchline_collect` | `gender` (required, `men` or `women`); `target`; `conference` (legacy alias, prefer `target`); `season` (integer, defaults to `TOUCHLINE_V1_SEASON` in `src/season.ts`); `project` | yes | no |
| `touchline_focus` | `project`; `season`; `gender`; `conference`; `team` | yes | no |
| `touchline_remove` | `project` (required); `delete_data`; `confirm` | yes | yes |

Per-tool contract:

- **`touchline_init`** creates `{name}` under the Keelson workspace (`KEELSON_WORKSPACE`, else `~/keelson`), initializes it as a data home, and registers it as a Keelson project. Git is neither required nor initialized. Safe to re-run: an existing home is reported, never overwritten.
- **`touchline_status`** is read-only: home state, per-season fixture, played, and roster counts, plus every named gap from the season files' `missing` arrays. Played is counted through the shared `isPlayed` in `src/model.ts`, so a final without a published score still counts as played.
- **`touchline_collect`** resolves the target from membership data (`resolveTargets` in `src/membership.ts`, never a hardcoded list), plans the season's layers (`planForSeason` in `src/season.ts`; a season nothing can serve is refused with `unsupportedSeasonMessage`), then enforces the empty-or-ours rule: the directory must be `empty` or already `ready` per `dataHomeState` in `src/datahome.ts`, and anything else is refused by name. The collect subprocess budget scales with the fleet the run can become (`collectTimeoutMs` over `collectFleetSize`). Exit 0 from the collector means the coverage manifest was written and describes reality, gaps included; on success the board is repointed at what just landed.
- **`touchline_focus`** repoints the board at a season shard or one team. When a named `season` or `gender` matches more than one conference shard, `conference` must disambiguate; with neither named, the first collected season is shown. A `team` not in the selected season's programmes is refused with the list of programmes that are.
- **`touchline_remove`** is two-step. Called with `delete_data` but without `confirm` exactly equal to the project name, it changes nothing and reports what would be lost: seasons with fixture and roster counts, plus archived source pages. Deleting requires calling again with both. Three refusals cannot be confirmed away (`planTouchlineRemoval` in `src/commands.ts`): a folder carrying no Touchline marker, a git repository, and the workspace root or a home directory. Without `delete_data` the project is only unregistered and every file stays on disk.

## The /touchline command

`src/commands.ts` defines the one slash command. `/touchline` with no argument opens the Touchline agent. `/touchline {folder-name}` validates the name (lowercase, up to 64 letters, digits, dashes, or underscores, starting with a letter or digit), then calls `initTouchlineHome`, the same function `touchline_init` calls, so the two entry points cannot drift. The tool exists because a slash command is a composer affordance: the chat CLI and MCP cannot invoke one.

## Board actions

`onAction` in `src/index.ts` handles the board's actions. Every payload is zod-validated, and a malformed one returns an error naming the expected shape. All board actions are reads of the collected data: they repoint the board and repaint. Every write path into a data home lives in the chat tools.

| Action | Payload | Effect |
|---|---|---|
| `select-project` | `{ scopeId?: string }` | Point the board at a project. Also records the chosen data home in the activation config (`ensureActivationConfig` in `src/activation.ts`), the one side effect beyond selection state |
| `select-season` | `{ season: number, gender: string, conference?: string }` | Step to a season shard already on disk; ambiguous shards must name a conference; a team lens survives the step when the target season has that team |
| `select-lens` | `{ team?: string \| null }` | Switch between the whole-conference board and one team's lens |
| `select-player` | `{ player?: string \| null }` | Open or close the player drawer on the team page |
| `open-fixture` | `{ fixture?: string \| null }` | Open or close the match drawer (the fixture's box score) |
| `player-profile` | any | Not implemented; returns an error saying so |

## The agent seed

`touchlineSystemPrompt` in `src/agent.ts` is a write-once, user-readable chat seed whose honesty rules mirror what the rest of the rib enforces in code: never invent a programme or a number, name every gap, a folder must be empty or already a Touchline home, pre-season is a valid result, and gaps are results, not failures.

## Snapshot keys

`src/keys.ts` is the single source for the rib's static keys: `TOUCHLINE_SURFACE_ID` (`touchline`) and `BOARD_KEY` (`rib:touchline:board`). Keys must live under `rib:touchline:*`; an out-of-namespace key is an activation failure that takes the whole server boot down, not a warning. The key model itself is the harness's; see keelson's [snapshots reference](https://danielscholl.github.io/keelson/docs/reference/snapshots/).

## Related

**Run it**

- [Create a data home](../../guides/create-a-data-home/): the `/touchline` and `touchline_init` path as a task.
- [Work the board](../../guides/work-the-board/): the board actions from the operator's chair.

**Understand it**

- [Season is a dimension](../../concepts/season-and-membership/): how `touchline_collect` resolves a conference to that season's members.
- [Absence is data](../../concepts/absence-is-data/): why gaps travel through tool results as data, never as failure.
