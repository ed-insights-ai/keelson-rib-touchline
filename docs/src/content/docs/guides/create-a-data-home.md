---
title: Create a data home
description: Initialize the marked directory Touchline collects into, point tools at it, and remove it without losing data by accident.
sidebar:
  order: 2
---

Everything Touchline collects lives in a **data home**: an ordinary directory
carrying the marker file `touchline-data.yaml` with `kind: touchline-data`
(`MARKER_FILE` and `MARKER_KIND` in `src/datahome.ts`). The rib package holds
code; the data home holds your data; the marker is the boundary between "the
user pointed us at their data" and "the user pointed us at their home
directory". Git is neither required nor initialized.

## The five states

`dataHomeState` in `src/datahome.ts` classifies any directory:

| State | Meaning |
|---|---|
| `ready` | The marker is present. Touchline reads and collects here. |
| `empty` | Nothing but VCS and OS bookkeeping (`.git`, `.DS_Store`, `.gitignore`, `.gitkeep`, `README.md`). Initialization may proceed. |
| `occupied` | The directory holds other work. The refusal lists up to eight entries so you can see whose. |
| `foreign` | A `touchline-data.yaml` exists but its `kind` is not `touchline-data`. Touchline refuses to scaffold over it. |
| `missing` | The directory does not exist or cannot be read. |

Every write path enforces the **empty-or-ours rule**: `bootstrapDataHome`
accepts only `empty` and `ready`, and `touchline_collect` in `src/tools.ts`
re-checks the state before touching disk, so a collection can never scribble a
data tree into a project you merely had selected. `bootstrapDataHome` takes a
`force` flag for deliberately adopting an `occupied` directory; its doc
comment requires an explicit human instruction, and no chat tool passes it.

## Step 1: create one

Two entry points share one code path, `initTouchlineHome` in
`src/commands.ts`, so the two cannot drift:

- In the composer: `/touchline {folder-name}`. With no argument the command
  just opens the Touchline agent.
- In chat or over MCP: `touchline_init { name: "{folder-name}" }`.

The folder name is lowercase: letters, numbers, dashes, and underscores, up
to 64 characters. The folder is created under the Keelson workspace
(`KEELSON_WORKSPACE`, else `~/keelson`), initialized, registered as a Keelson
project of the same name, and remembered as the rib's data directory in
`~/.keelson/rib-touchline/config.json`. Success begins:

```
Initialized {data-home} as a Touchline data home.
Registered it as the Keelson project '{name}'.
```

Re-running is safe: bootstrap is idempotent (`writeIfAbsent` in
`src/datahome.ts` never overwrites), and an already-initialized home is
reported, not rebuilt. A name conflict (the same name at a different path, or
the path already registered under another name) refuses with nothing changed.

## What bootstrap scaffolds

| Path | What lives here |
|---|---|
| `data/fixtures/`, `data/rosters/`, `data/stats/`, `data/matches/` | The four deliverable layers, one JSON file per season, gender, and conference (`seasonFileName` in `src/datahome.ts`). |
| `data/raw_html/` | Every page exactly as fetched, so any parse can be redone offline. |
| `data/errors/` | Anything a run could not parse, kept rather than dropped. |
| `data/reference/` | Reference data beside the deliverables: the `membership.json` mirror (`pipeline/src/paths.py`). |

Plus the marker itself and a README describing the layout.

## Step 2: point tools at it

`TOUCHLINE_DATA_DIR` is the seam between code and this directory, on both
sides of the rib. The TypeScript side resolves it in
`resolveActivationDataDir` (`src/activation.ts`): the environment variable
always beats the remembered `dataDir`, which keeps one-off CLI runs and
recovery work explicit and reversible. The Python side resolves every disk
path through functions in `pipeline/src/paths.py`, reading
`TOUCHLINE_DATA_DIR` at call time. So any pipeline command can be aimed at
any data home:

```sh
TOUCHLINE_DATA_DIR=/path/to/{data-home} uv run --project pipeline migrate-shard --conference GAC
```

## Step 3: remove one, in two steps

`touchline_remove` in `src/tools.ts` defaults to the reversible action: it
unregisters the Keelson project and leaves every collected file on disk, so
you can re-register it any time. Deleting data is a separate act, gated
twice:

1. Call the tool with `delete_data` but without `confirm`. Nothing is
   deleted; the reply inventories what would be lost: per season, the fixture
   and roster-player counts, plus the count of archived source pages.
2. Relay that to whoever is deciding, then call again with `confirm` exactly
   equal to the project name. Anything else refuses.

Three refusals cannot be confirmed away; `planTouchlineRemoval` in
`src/commands.ts` blocks them outright:

- **The workspace root or your home directory.** Touchline will not delete
  either.
- **A git repository.** That is tracked work, not a disposable data home.
  Unregister it and delete the folder yourself if you really mean to.
- **A folder carrying no Touchline marker.** Touchline only deletes folders
  it created: the same rule that governs collection governs deletion.

A blocked plan answers `REFUSED:` with the reason, and a confirmed call
against it fails with the same sentence.

**What you just exercised:**
[The archive is the system of record](../../concepts/archive-first/),
[The system in one view](../../concepts/five-layers/),
[Season is a dimension](../../concepts/season-and-membership/).

## Related

**Run it**

- [Run a collection](../run-a-collection/): fill the home you just created.
- [Data on disk](../../reference/data-on-disk/): the full directory and file contract.

**Understand it**

- [Raw archive as system of record](../../design/raw-archive-as-system-of-record/): why the evidence tier exists at all.
- [Conference is configuration](../../design/conference-as-configuration/): why the shard name carries a conference.
