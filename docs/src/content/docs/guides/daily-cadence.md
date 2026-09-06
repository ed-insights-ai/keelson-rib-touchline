---
title: Run the daily cadence
description: "The unattended loop that keeps a data home tracking the published record and the site tracking the data home: modes, the shim install, the change-detection rule, the rollback scope, the log and the run record."
sidebar:
  order: 11
---

The daily cadence is one POSIX shell script, `bin/touchline-collect-cadence.sh`,
shipped in the rib package and run by launchd every morning through a thin
shim. It collects every conference the membership record authors for the
season, decides per conference whether the board really changed, journals and
publishes only when one did, and pushes the data home's record. Nothing in it
names a conference: the set resolves at run time from
`bin/resolve-membership.ts conferences {gender}`, so onboarding a conference
never edits it ([Onboard a conference](../onboard-a-conference/), step 7).

Every run writes two things a reader can rely on: the cadence log, one line
per step, and a run record, one JSON line per completed run. Both live under
`~/.keelson/logs/`.

## The loop

One run is five legs, in order. A leg that fails is logged and the later legs
still run, except where the table says otherwise.

| leg | what it does | on failure |
|---|---|---|
| collect | one `keelson workflow run touchline-collect` per conference, sequentially, with programmes resolved from membership for the season | the conference is marked `failed`, its partial writes are rolled back, the next conference runs, the run exits 1 at the end |
| detect | reads the data home's git state per conference: real change is committed, stamp-only churn is rolled back | never fails on its own |
| journal | `bun run journal run --conference {keys} --write` in the site checkout, one pooled call for every changed conference, then `--national` once when any conference journal regenerated. Each is a live model call | the site keeps its previous journal for that conference; the loop continues |
| commit journals | stages exactly the regenerated journal and validation files, commits on the site's `main`, pushes | a checkout not on `main` is logged and left uncommitted; a push failure is a warning, never a stop |
| publish | `just publish` in the site checkout, once, only when a conference changed. The recipe's own build, link check, gh-pages push and deployed-host assertion are the gate | logged as `PUBLISH FAILED`, exit 1; the data home commits are intact |
| push data | pushes every data home commit ahead of upstream | a warning and exit 1; the commits stay local |

Membership resolution failing for a conference (`resolve-failed`) skips its
collect and counts as a failure the same way.

### The season

The college-soccer season is the calendar year of its fall semester. From June
onward the cadence collects the current year; January to May still means last
fall's season, so a spring wake-up refreshes the archive instead of asking the
sites for a season that does not exist yet. `TOUCHLINE_SEASON` pins it.

## Modes

The first argument selects the mode; no argument is the full loop.

| mode | runs | use |
|---|---|---|
| `loop` (default) | all five legs | what launchd runs at 06:30 |
| `collect` | collect and detect only: no journal, no commit, no publish, no data push | the site's justfile delegates its collect step here (`TOUCHLINE_COLLECT_CMD="sh {shim} collect"`) so `just` does not run the journal twice |
| `version` | prints the packaged script path, the package dir, the package version and its `git describe`, then exits 0 | proves the shim resolves the installed package without taking the lock or collecting |

Environment overrides: `TOUCHLINE_CONFERENCES` (space-separated keys, pins the
set), `TOUCHLINE_SEASON`, `TOUCHLINE_GENDER` (default `men`),
`TOUCHLINE_DATA_HOME` (default `~/keelson/d2-soccer`), `TOUCHLINE_UI_DIR`
(default `~/edinsights-ai/project/touchline-ui`),
`TOUCHLINE_CADENCE_RUNS_FILE` (the run record path) and
`TOUCHLINE_CADENCE_PATH` (replaces the script's absolute `PATH`; the test
harness uses it to put its fakes first).

## The shim install

The launchd plist (`~/Library/LaunchAgents/ai.edinsights.touchline-collect.plist`)
runs `/bin/sh ~/.keelson/scripts/touchline-collect-cadence.sh` and redirects
its output to the cadence log. That path holds the shim,
`bin/touchline-collect-cadence.shim.sh`, not the cadence itself. The shim
resolves the installed rib package the way the script's own
`rib_package_dir` does, `packageDir` from `~/.keelson/rib-touchline/config.json`
and otherwise `~/.keelson/node_modules/@keelson/rib-touchline`, and execs
`{package}/bin/touchline-collect-cadence.sh` with the same arguments. Upgrading
the rib upgrades the cadence; launchd and the shim never change.

Install or replace it by hand, keeping the previous file:

```bash
PKG=$(jq -r .packageDir ~/.keelson/rib-touchline/config.json)
cp ~/.keelson/scripts/touchline-collect-cadence.sh \
   ~/.keelson/scripts/touchline-collect-cadence.sh.bak-$(date +%Y%m%d)
cp "$PKG/bin/touchline-collect-cadence.shim.sh" \
   ~/.keelson/scripts/touchline-collect-cadence.sh
sh ~/.keelson/scripts/touchline-collect-cadence.sh version
```

The last line is the proof: it prints
`touchline-collect-cadence: script={package}/bin/touchline-collect-cadence.sh package={package} version={version} git={describe}`
and exits 0 without collecting. A shim whose package carries no cadence script
writes one `FATAL: cadence shim: packaged script not found at ...` line to the
cadence log, prints it to stderr, and exits 1.

## Change detection

Every collect rewrites the top-level `collected_at` stamp in each of the four
board files (`data/fixtures`, `data/rosters`, `data/stats`, `data/matches`,
each `{season}-{gender}-{conference}.json`), so "any diff" would journal daily
forever. A conference counts as changed when, for its four board files, either
a file is new to git or `git diff HEAD -U0` carries a changed line that is not
the `"collected_at"` line. Coverage manifests, raw page archives and error
files churn on every fetch: they ride along in a real change's commit and never
count as one.

A real change is committed in the data home as
`chore(data): cadence collect {conference} {gender} {season}`. Churn is rolled
back, so a quiet day leaves no commit and spends nothing. A re-run of an
already-collected day converges to "nothing to do".

Before the first collect, any uncommitted state already in the data home (an
interrupted earlier run) is swept into one commit, and a conference whose
board files carry real change in that sweep is marked changed, so the
per-conference detection that follows stays exact.

## Rollback scope

Rollback is data-home-wide today: `git reset --hard` followed by
`git clean -fd data`. It runs after a failed collect and after stamp-only
churn, and it is safe only because collects are serial inside one run and the
cadence is the only writer while it holds its lock. A concurrent backfill or a
maintenance write landing during a run would be swept by the pre-run commit or
discarded by the next rollback. Bead `tl-5go` tracks scoping the rollback to
the collected conference's board files plus its coverage, raw_html and error
entries, and taking the keelson workspace lease on the data home so the two
writers exclude each other.

## The lock

A PID lock at `~/.keelson/locks/touchline-collect-cadence.lock` makes a second
start a logged no-op (`cadence already running (pid {n}) - exiting without
work.`, exit 0). A lock whose PID is gone is taken over. `version` mode never
takes the lock.

## Where the log lives

`~/.keelson/logs/touchline-collect-cadence.log`, appended by every run. Lines
are timestamped; the output of each collect, journal and publish call is
indented beneath its leg. Under launchd the same file receives stdout and
stderr, and the script writes each line exactly once (it echoes to stdout only
when stdout is a terminal). The last line of every completed run is the
summary:

```
run summary: mode=loop season=2026 collect=[GAC=changed LSC=no-change]
  changed=[gac] failed=[none] journal_model_calls=2 journal_commit=95ff38f
  publish=succeeded exit=0 data_head=ce924f2 build=2026-09-06T14:16:59Z
```

(one line in the log). The fields keep their positions; `data_head` and
`build` are appended at the end. `journal_model_calls` counts live model calls
made this run: the pooled conference call counts one per changed conference,
the national call one more.

## The run record

The same run as data: one JSON line appended to
`~/.keelson/logs/touchline-cadence-runs.jsonl` immediately before the summary
line, for every run that reaches the end (a preflight `FATAL` and a lock no-op
write none).

| field | value |
|---|---|
| `started_at`, `finished_at` | UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `mode` | `loop` or `collect` |
| `season` | number |
| `gender` | `men` or `women` |
| `conferences` | the keys this run iterated, in order |
| `collect` | map, conference key to `changed`, `no-change`, `failed` or `resolve-failed` |
| `changed` | lowercase keys whose board really changed (the sweep's leftovers included) |
| `failed` | keys that failed or did not resolve |
| `journal_model_calls` | number, as in the summary line |
| `journal_commit` | the site's short SHA, `none`, `no-op` (files matched HEAD), `FAILED`, or `skipped (branch {name})` |
| `journaled` | keys whose journal regenerated and validated, `national` last when it did |
| `data_head` | the data home's short HEAD after the push leg (the pre-run value in `collect` mode) |
| `data_push` | `ok`, `failed`, or `skipped` (collect mode, no upstream, or nothing ahead) |
| `build_stamp` | the `touchline-build` meta content read from the site's `dist/index.html` after a successful publish, else `null` |
| `publish` | `succeeded`, `FAILED (exit {n})`, or `skipped (no change)` |
| `exit` | the run's exit code |

Read it with jq:

```bash
tail -1 ~/.keelson/logs/touchline-cadence-runs.jsonl | jq .
jq -r 'select(.exit != 0) | "\(.started_at) \(.failed) \(.publish)"' \
  ~/.keelson/logs/touchline-cadence-runs.jsonl
```

## Tests

`test/cadence.test.ts` runs the script and the shim under `/bin/sh` against a
throwaway world: a temp `HOME` with the rib config, a temp package dir, a temp
git data home with an upstream, a temp site checkout with an upstream, and
fake `keelson`, `bun` and `just` first on the script's `PATH` (git and jq are
real). The scenarios are the ones above: a changed collect commits, churn
rolls back, a failed collect rolls back and the run continues with exit 1,
`collect` mode stops before the journal, a `loop` run journals the conference
and the national leg, commits on the site's `main`, publishes and records the
build stamp, a second concurrent start is a no-op, and `version` resolves
through the shim. `bun test` runs them with the rest of the rib suite;
`bun run check:sh` runs shellcheck over `bin/*.sh`.
