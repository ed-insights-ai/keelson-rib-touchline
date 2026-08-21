---
title: Install and activate
description: Install the Touchline rib into a Keelson harness, read the status ladder, and verify the first tool call answers.
sidebar:
  order: 1
---

Touchline is a Keelson rib, so installing it is the harness's generic rib
lifecycle: [Managing ribs](https://danielscholl.github.io/keelson/docs/guides/managing-ribs/)
covers sources, version pinning, activation filters, and removal. This page
documents only what Touchline adds: one runtime prerequisite, a status ladder
that names the first missing rung, and the first verification call.

## Prerequisites

- **A running Keelson harness.** Generic; see the
  [Keelson docs](https://danielscholl.github.io/keelson/).
- **uv.** Touchline's collection pipeline is Python, executed through
  `uv run`. The status probe checks for it before any collection can start.
- **Chrome or Chromium, optional.** Only PDF printing of the scouting report
  uses a browser (`pipeline/scripts/render_report.py`, `_chrome()`). Without
  one, the report is delivered as HTML and the PDF step is skipped. Set
  `TOUCHLINE_CHROME` to name a specific binary. The status ladder does not
  check for it.

## Step 1: install and restart

```sh
keelson rib add https://github.com/ed-insights-ai/keelson-rib-touchline
```

The Python pipeline ships inside the package, so there is nothing separate to
clone. Rib discovery happens once, at boot: restart the harness before
expecting the surface or the tools.

## Step 2: read the status ladder

```sh
keelson rib show touchline
```

The status this prints is `touchlineAuthStatus` in `src/activation.ts`. It
never throws, and it reports the first missing prerequisite rather than a
boolean, so every answer tells you the next action. The rungs, in order:

| Rung | What is checked | When it fails |
|---|---|---|
| Activation config | `~/.keelson/rib-touchline/config.json` reads and writes cleanly (written atomically by `ensureActivationConfig`) | The message names the invalid file. |
| Pipeline present | `pipeline/pyproject.toml` exists inside the installed package | "Reinstall the rib." |
| uv | `uv --version` answers | "Install uv before collecting." |
| Data home selected | `TOUCHLINE_DATA_DIR`, else the `dataDir` remembered in the config | Asks you to select an empty Keelson project to initialize. |
| Data home state | `dataHomeState` classifies the directory as `ready` | An `empty` home says it is ready to initialize; anything else gets the sentence from `explainRefusal`. |

The healthy answer names the data home and whether it came from the
environment (`env`) or the remembered config (`config`):

```
Ready — Touchline data home at {data-home} (config).
```

On a fresh install, stopping at the data-home rung is the expected state:
[Create a data home](../create-a-data-home/) is the next page.

## Step 3: verify from chat

Ask the status tool, in chat or over MCP:

```
touchline_status { project: "{project}" }
```

Every Touchline tool handler is wrapped by `guarded()` in `src/tools.ts`, so
a failure comes back as an honest error result, never an escaped exception.
Against a data home holding collected seasons, the healthy shape is one line
per season file:

```
{project} — {n} season file(s) at {data-home}
  {season} {gender} ({conference}): {programmes} programmes, {fixtures} fixtures, {played} played, {players} roster players
```

Two other healthy answers exist before the first collection: an empty folder
reports that it is ready to become a data home, and a marked home with no
seasons yet answers with its marker version and points you at
`touchline_collect`. A `foreign`, `occupied`, or `missing` directory returns
the same refusal sentence the ladder would give, as an error result. Named
collection gaps ride the season line as `GAPS: ...`; they are data, not
failure.

**What you just exercised:**
[The system in one view](../../concepts/five-layers/),
[Absence is data](../../concepts/absence-is-data/),
[Season is a dimension](../../concepts/season-and-membership/).

## Related

**Run it**

- [Create a data home](../create-a-data-home/): the data-home rung, done properly.
- [Run a collection](../run-a-collection/): the first real work the install enables.
- [Rib surface](../../reference/rib-surface/): the exact schema of every tool the install registered.

**Understand it**

- [The system narrative](../../design/system-narrative/): what the whole rib is for, before you run any of it.
