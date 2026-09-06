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

One run is these legs, in order. A leg that fails is logged and the later
legs still run, except where the table says otherwise.

| leg | what it does | on failure |
|---|---|---|
| collect | one `keelson workflow run touchline-collect` per conference, sequentially, with programmes resolved from membership for the season | the conference is marked `failed`, its own paths are rolled back, the next conference runs, the run exits 1 at the end. A collect refused by keelson's mutation lock is marked `locked` instead: nothing is rolled back and the conferences after it are skipped |
| detect | reads the data home's git state per conference: real change is committed, stamp-only churn is rolled back | never fails on its own |
| journal | `bun run journal run --conference {keys} --write` in the site checkout, one pooled call for every changed conference, then `--national` once when any conference journal regenerated. Each is a live model call | the site keeps its previous journal for that conference; the loop continues |
| commit journals | stages exactly the regenerated journal and validation files, commits on the site's `main`, pushes | a checkout not on `main` is logged and left uncommitted; a push failure is a warning, never a stop |
| publish | `just publish` in the site checkout, once, only when a conference changed. The recipe's own build, link check, gh-pages push and deployed-host assertion are the gate | logged as `PUBLISH FAILED`, exit 1; the data home commits are intact |
| push data | pushes every data home commit ahead of upstream | a warning and exit 1; the commits stay local |
| archive | on the archive day only (Sunday by default), tars the raw HTML fetch cache as one `tar.zst` per season, gender and conference plus one for anything unclaimed, then prunes old sets ([Weekly raw HTML archive](#weekly-raw-html-archive)) | a warning and exit 1; the dated directory is left without its `.done` marker and the next run removes it |

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
| `loop` (default) | all the legs | what launchd runs at 06:30 |
| `collect` | collect and detect only: no journal, no commit, no publish, no data push, no archive | the site's justfile delegates its collect step here (`TOUCHLINE_COLLECT_CMD="sh {shim} collect"`) so `just` does not run the journal twice |
| `archive` | the archive leg alone, under the same PID lock, whatever the day: no collect, no journal, no publish, no data push | take a tarball set by hand, or catch up a missed Sunday |
| `version` | prints the packaged script path, the package dir, the package version and its `git describe`, then exits 0 | proves the shim resolves the installed package without taking the lock or collecting |

Environment overrides: `TOUCHLINE_CONFERENCES` (space-separated keys, pins the
set), `TOUCHLINE_SEASON`, `TOUCHLINE_GENDER` (default `men`),
`TOUCHLINE_DATA_HOME` (default `~/keelson/d2-soccer`), `TOUCHLINE_UI_DIR`
(default `~/edinsights-ai/project/touchline-ui`),
`TOUCHLINE_CADENCE_RUNS_FILE` (the run record path),
`TOUCHLINE_CADENCE_LOCK_DIR` (the PID lock directory, read by the backfill
preflight too), `TOUCHLINE_ARCHIVE_DAY` and `TOUCHLINE_ARCHIVE_DIR` (the
archive leg's day and root, below) and `TOUCHLINE_CADENCE_PATH` (replaces the
script's absolute `PATH`; the test harness uses it to put its fakes first).

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
the `"collected_at"` line. Coverage manifests and error files churn on every
fetch: they ride along in a real change's commit and never count as one. Raw
pages churn the same way but are not tracked at all: `data/raw_html` is
gitignored in the data home, lives on disk as the collector's fetch cache, and
is preserved by the weekly archive below rather than by git history.

A real change is committed in the data home as
`chore(data): cadence collect {conference} {gender} {season}`. Churn is rolled
back, so a quiet day leaves no commit and spends nothing. A re-run of an
already-collected day converges to "nothing to do".

Before the first collect, any uncommitted state already in the data home (an
interrupted earlier run) is swept into one commit, and a conference whose
board files carry real change in that sweep is marked changed, so the
per-conference detection that follows stays exact. The sweep names what it
commits: one `sweep {CONF}: {n} path(s): ...` line per conference (board and
errors files by their `{season}-{gender}-{conference}` suffix, raw page
archives by programme slug, with membership resolved once per conference for
the whole run), one `sweep shared:` line for `data/coverage.json`, one
`sweep unattributed:` line for anything else, and the commit reads
`chore(data): sweep uncommitted changes found before cadence run [{CONFs}]`.

## Two locks and a scoped rollback

Two writers can reach one data home: the cadence and a `touchline-backfill`
run. Two locks keep them apart, neither of them new.

The first is keelson's. `touchline-collect` and `touchline-backfill` both
declare `mutates_checkout: true`, so the server holds one exclusive mutation
lock per project and runs them one after another. A collect started while a
backfill holds the lock fails at start with
`project {id} is locked by {owner} for "touchline-backfill"`. The cadence
honours that lock twice over. Before its sweep it asks
`keelson workflow status --json` whether a `touchline-collect` or
`touchline-backfill` run is running or paused on the data home (matched on the
run's `workingDir`, since the envelope carries the project's id, not its
name). If one is, it logs
`data home busy: {workflow} run {id} started {at}, owner {origin}` and exits 0
with nothing swept and nothing collected; the run record carries `busy` and
the summary line ends `busy={workflow} {id}`, so a busy start never reads as
a quiet day. A status call that fails is logged and the run goes on, because
the server refuses the collect itself. A collect refused mid-run makes its
conference `locked`: the error is logged verbatim, nothing is rolled back,
the conferences after it are skipped by name, the journal and publish legs
still run for whatever changed before it, and the run exits 1. There is no
retry inside the run; the next fire is the retry. (Keelson's
`workspace_lease` is a worktree lease, not a mutex, and plays no part.)

The second is the cadence's own PID lock at
`~/.keelson/locks/touchline-collect-cadence.lock`. It makes a second cadence
start a logged no-op (`cadence already running (pid {n}) - exiting without
work.`, exit 0); a lock whose PID is gone is taken over, and `version` mode
never takes it. The backfill workflow's preflight reads the same lock and
refuses with `REFUSED: the touchline cadence is running (pid {n}); retry
after it finishes.` while that PID is live.

A rollback, after stamp-only churn or a failed collect, touches only the
collected conference's paths:

- `data/fixtures/{season}-{gender}-{conference}.json` and the same file under
  `data/rosters`, `data/stats` and `data/matches`
- `data/errors/collect-board-{season}-{gender}-{conference}.json`
- `data/raw_html/{slug}/{season}-{gender}-*` for each of its resolved
  programme slugs
- `data/coverage.json`

Tracked paths go back to `HEAD`, untracked ones are cleaned, and a path that
does not exist is skipped. Coverage is one manifest shared by every
conference, so restoring it is all-or-nothing; inside a run every successful
collect commits before the next one starts, so no other conference's coverage
is lost. Nothing outside those paths is ever reset.

## Weekly raw HTML archive

The raw pages under `data/raw_html` are the evidence behind every number and
cannot be fetched again once a publisher redesigns, but they are also the
data home's largest and churniest class, so they left its git index (bead
tl-ttj: gitignored, the history kept as it was). What preserves them now is
this leg.

**When.** In `loop` mode, on the archive day: the run's `date +%u` equals
`TOUCHLINE_ARCHIVE_DAY`, default `7` (Sunday). `0` disables the leg, `always`
forces it on every run. `archive` mode runs the leg on any day. The leg runs
after the data home push and before the run record, so the record carries its
result.

**Where.** `{TOUCHLINE_ARCHIVE_DIR}/{YYYY-MM-DD}/`, the root defaulting to
`~/keelson/archive/raw-html`, one dated directory per run. Inside it, one
`{season}-{gender}-{conference}.tar.zst` per conference-season the data home
has collected, holding `data/raw_html/{slug}/{season}-{gender}-*` for that
cell's programmes (the `.state.json` sidecars included), paths relative to the
data home. Membership is read from the data home, never resolved live:
`data/coverage.json` says which `(season, gender, programme)` cells were
collected (`.cells[] | .season, .gender, .programme`), and the fixtures board
of that season and gender says which conference collected the programme
(`data/fixtures/{season}-{gender}-{conference}.json`: `.conference`,
`.programmes[].slug`), since a coverage cell carries no conference field. A
cell with no pages on disk is logged and skipped. Nothing on disk is left
out: every file under `data/raw_html` that no cell claimed (a slug no cell
names, a page older than its coverage, a disabled or dead-host stanza's
pages) goes into `unassigned.tar.zst`. Each tarball is written to
`{name}.tar.zst.tmp` and moved into place, and a `.done` marker is written
last, after every tarball of the run landed.

**Retention.** After the run's tarballs, the dated directories under the root
are listed newest first by name. Any directory without a `.done` marker is
removed (an interrupted or failed run), then every complete directory beyond
the newest four, today's counted. A failed leg writes no `.done`, so the next
pass removes its directory.

**Log lines.** `archive: writing {dir} from {data home}/data/raw_html`, then
`archive {season} {gender} {CONF}: {n} file(s), {size}` per tarball,
`archive unassigned: {n} file(s) across {k} slug(s) ({first few slugs}), {size}`
or `archive unassigned: none`, `archive total: {n} tarball(s), {size}, {dir}`,
`archive retention: removed {dir} (...)` per removal and
`archive retention: kept {k} of {n}`. A skipped leg logs
`archive: skipped (not archive day; today is {u}, archive day {d})` or
`archive: skipped (disabled; archive day 0, today is {u})`. A failure logs
`WARNING: archive FAILED ({reason})`, sets the exit code to 1 and never stops
the run. The summary line ends `archive={result}` and the run record carries
the same string in `archive`: `ok {dir} {total size}`, `skipped (...)` or
`FAILED ({reason})`.

`zstd` must be on the script's `PATH` in `loop` and `archive` modes
(preflight dies naming it, like `git` and `jq`); `collect` mode does not need
it. Restore a page set with
`zstd -dc {dir}/{season}-{gender}-{conf}.tar.zst | tar -C ~/keelson/d2-soccer -xf -`.

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
  locked=[none] busy=none archive=skipped (not archive day; today is 4, archive day 7)
```

(one line in the log). The fields keep their positions; `data_head`, `build`,
`locked`, `busy` and `archive` are appended at the end. `journal_model_calls` counts live
model calls made this run: the pooled conference call counts one per changed
conference, the national call one more. A busy start reads
`collect=[none] ... busy=touchline-backfill {run id}`.

## The run record

The same run as data: one JSON line appended to
`~/.keelson/logs/touchline-cadence-runs.jsonl` immediately before the summary
line, for every run that reaches the end (a preflight `FATAL` and a lock no-op
write none).

| field | value |
|---|---|
| `started_at`, `finished_at` | UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `mode` | `loop`, `collect` or `archive` |
| `season` | number |
| `gender` | `men` or `women` |
| `conferences` | the keys this run iterated, in order |
| `collect` | map, conference key to `changed`, `no-change`, `failed`, `locked` or `resolve-failed`; empty on a busy start |
| `changed` | lowercase keys whose board really changed (the sweep's leftovers included) |
| `failed` | keys that failed or did not resolve |
| `locked` | keys whose collect was refused by keelson's mutation lock |
| `busy` | `{workflow} {run id}` when the start found another run on the data home and did nothing, else `null` |
| `journal_model_calls` | number, as in the summary line |
| `journal_commit` | the site's short SHA, `none`, `no-op` (files matched HEAD), `FAILED`, or `skipped (branch {name})` |
| `journaled` | keys whose journal regenerated and validated, `national` last when it did |
| `data_head` | the data home's short HEAD after the push leg (the pre-run value in `collect` mode) |
| `data_push` | `ok`, `failed`, or `skipped` (collect mode, no upstream, or nothing ahead) |
| `build_stamp` | the `touchline-build` meta content read from the site's `dist/index.html` after a successful publish, else `null` |
| `publish` | `succeeded`, `FAILED (exit {n})`, or `skipped (no change)` |
| `exit` | the run's exit code |
| `archive` | `ok {dir} {total size}`, `skipped (...)` (not the archive day, disabled, `collect` mode, or not reached on a busy start), or `FAILED ({reason})` |

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
fake `keelson`, `bun` and `just` first on the script's `PATH` (git, jq, tar
and zstd are real). The scenarios are the ones above: a changed collect
commits, churn rolls back, a failed collect rolls back and the run continues
with exit 1, `collect` mode stops before the journal, a `loop` run journals
the conference and the national leg, commits on the site's `main`, publishes
and records the build stamp, a second concurrent start is a no-op, a run
already on the data home makes the start a busy exit, a locked collect is
reported and nothing rolled back, a failed collect's rollback leaves a
sibling's mid-collect write alone, the sweep names its paths per conference,
and `version` resolves through the shim. The archive leg has its own set: a
`loop` run on the archive day writes one tarball per conference-season with
exactly that cell's pages, retention keeps the newest four complete sets and
drops an incomplete one, a disabled or wrong day skips with the reason, an
unclaimed page lands in `unassigned.tar.zst`, `archive` mode runs only that
leg under the lock, and a `PATH` without zstd fails `loop` preflight but not
`collect`. The zstd-dependent scenarios skip by name on a machine without it. The backfill preflight's lock refusal is covered in
`test/workflows.test.ts`. `bun test` runs them with the rest of the rib
suite; `bun run check:sh` runs shellcheck over `bin/*.sh`.
