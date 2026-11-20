---
title: Run the daily cadence
description: "The unattended loop that keeps a data home tracking the published record and the site tracking the data home: modes, the shim install, the change-detection rule, the rollback scope, the log and the run record."
sidebar:
  order: 11
---

The daily cadence is one POSIX shell script, `bin/touchline-collect-cadence.sh`,
shipped in the rib package and run by launchd every morning through a thin
shim. It collects every conference at its data home's NCAA level that has a
member this season, decides per conference whether the board really changed,
journals only when one did, publishes whenever any conference was collected
(so the site is dated by the run's look), and pushes the data home's record.
Nothing in it names a conference: the set resolves at run time from
`bin/resolve-membership.ts conferences {gender} --level {level} --season {season}`,
so onboarding a conference never edits it
([Onboard a conference](../onboard-a-conference/), step 7). One cadence runs
per data home, and a data home holds one NCAA level
([A second data home](#a-second-data-home)).

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
| publish | `just publish` in the site checkout, once, when any conference was collected (changed or not), with `TOUCHLINE_RECOLLECTED` naming each unchanged one and its collect stamp. The recipe's own build, link check, gh-pages push and deployed-host assertion are the gate | logged as `PUBLISH FAILED`, exit 1; the data home commits are intact |
| push data | pushes every data home commit ahead of upstream | a warning and exit 1; the commits stay local |
| archive | on the archive day only (Sunday by default), tars the raw HTML fetch cache as one `tar.zst` per season, gender and conference plus one for anything unclaimed, then prunes old sets ([Weekly raw HTML archive](#weekly-raw-html-archive)) | a warning and exit 1; the dated directory is left without its `.done` marker and the next run removes it |

Membership resolution failing for a conference (`resolve-failed`) skips its
collect and counts as a failure the same way.

### The level and the conference set

The data home's `touchline-data.yaml` names the one NCAA level it collects
(`level: d1`, `d2` or `d3`). A marker with no `level` is read as `d2`, and
the log says so on every run (`NOTE: ... declares no level, so it is read as
d2`): every home made before levels existed is Division II, because until the
Division I men's conferences were onboarded the membership record held
nothing else. A `level` that is not one of the three stops the run.

Unpinned, the set is every conference at that level with at least one member
this season. A conference authored at the level but with no member this
season is named in the log and left out, neither collected nor failed: the
WAC's men end in 2025, every 2025 member is authored elsewhere for 2026, so a
Division I run logs
`skipped (no men 2026 members): WAC (at the home's level but with no member this season; not collected).`
and collects the other 23.

A pinned set (`TOUCHLINE_CONFERENCES`, or the config's `conferences.{gender}`)
wins, but every pinned conference must be at the home's level. One that is
not is refused by name, with both levels, before anything is collected, and
the run exits 1:
`REFUSED: ACC is a d1 conference and the data home ... collects d2 ...`.

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
| `collect-journal` | a home other than the site's only: collect and detect, then journal the changed conferences and the national journal into touchline-ui's `journal/<level>/`, commit them on its `main` and push. No publish, no data push, no archive | the Division I home's morning job, scheduled ahead of the site's run so that run's publish carries its journals |
| `archive` | the archive leg alone, under the same PID lock, whatever the day: no collect, no journal, no publish, no data push | take a tarball set by hand, or catch up a missed Sunday |
| `version` | prints the packaged script path, the package dir, the package version and its `git describe`, then exits 0 | proves the shim resolves the installed package without taking the lock or collecting |
| `plan` | resolves what a collect would collect today, the home's level, the conference set (one run per gender, as below) and every conference's programmes, prints it and exits. No lock, no log file, no run record, no keelson call, no git | check a config or membership change before the morning run |
| `paths` | prints every path this home's cadence derives (`data_home`, `home_key`, `default_home`, `project`, `lock_dir`, `log_file`, `runs_file`, `archive_root`, `rib_config`) and exits. Touches nothing | see where a second home's lock, log and archive live |

Environment overrides: `TOUCHLINE_CONFERENCES` (space-separated keys, pins the
set), `TOUCHLINE_SEASON`, `TOUCHLINE_GENDER` (default `men`),
`TOUCHLINE_DATA_HOME` (default `~/keelson/d2-soccer`; picks the home, and with
it every derived path below), `TOUCHLINE_UI_DIR`
(default `~/edinsights-ai/project/touchline-ui`),
`TOUCHLINE_CADENCE_LOG_FILE`, `TOUCHLINE_CADENCE_RUNS_FILE` (the run record path),
`TOUCHLINE_CADENCE_LOCK_DIR` (the PID lock directory, read by the backfill
preflight too), `TOUCHLINE_PROJECT` (the keelson project the collects run
in), `TOUCHLINE_CONFIG_PATH` (the rib config), `TOUCHLINE_ARCHIVE_DAY` and
`TOUCHLINE_ARCHIVE_DIR` (the archive leg's day and root, below) and
`TOUCHLINE_CADENCE_PATH` (replaces the script's absolute `PATH`; the test
harness uses it to put its fakes first).

## A second data home

A data home collects one NCAA level, so Division I is a second home
(`~/keelson/d1-soccer`, marker `level: d1`) beside the Division II one, with
its own cadence. Every path the cadence writes outside the data home derives
from the home. The default home, `~/keelson/d2-soccer`, matched by path, keeps
every name it had before there was a second; any other home keys its names by
its directory name:

| | default home (`~/keelson/d2-soccer`) | any other home, e.g. `~/keelson/d1-soccer` |
|---|---|---|
| PID lock | `~/.keelson/locks/touchline-collect-cadence.lock` | `~/.keelson/locks/touchline-collect-cadence.d1-soccer.lock` |
| log | `~/.keelson/logs/touchline-collect-cadence.log` | `~/.keelson/logs/touchline-collect-cadence.d1-soccer.log` |
| run record | `~/.keelson/logs/touchline-cadence-runs.jsonl` | `~/.keelson/logs/touchline-cadence-runs.d1-soccer.jsonl` |
| archive root | `~/keelson/archive/raw-html` | `~/keelson/archive/d1-soccer/raw-html` |
| keelson project | `d2-soccer` | `d1-soccer` |
| modes | all but `collect-journal` | `collect`, `collect-journal`, `archive`, `plan`, `paths` |

So two homes' cadences run side by side, neither waiting on the other's lock,
and two homes archiving on the same Sunday never write one directory.
`sh {script} paths` with `TOUCHLINE_DATA_HOME` set prints the column for any
home. The backfill workflow's preflight derives the same lock from its own
working directory, so a backfill refuses only while its own home's cadence
runs.

### Per-home config

The config's top-level `genders` and `conferences` belong to the default home
(and touchline-ui's justfile reads the same `genders`). Any other home reads
only its own section under `homes`, keyed by its directory name, and never
falls back to the top level, so a Division I home never inherits the
Division II site's women's pin:

```json
{
  "genders": ["men", "women"],
  "conferences": { "women": ["GAC", "…"] },
  "homes": {
    "d1-soccer": { "genders": ["men"] }
  }
}
```

The default home may also carry a `homes.d2-soccer` section; when it does,
that section wins over the top level. A home with no section follows one
gender (`men`, or `TOUCHLINE_GENDER`) and resolves its set from membership.
A single-gender run reads its home's pin for that gender unless
`TOUCHLINE_CONFERENCES` is set at all.

### Journals for a second home: `collect-journal`

The publish leg belongs to the site, and the site (`touchline-ui`) builds
every division in one publish: Division II at its base path and Division I
under `/d1`, each from its own data home and its own journal folder
(`journal/` and `journal/d1/`). A cadence for any other home is refused the
full loop, before it takes its lock, with one `FATAL` naming the home, so two
runs never race over one gh-pages.

What a second home does run is `collect-journal`: the same collect and detect
as `collect`, then, for the conferences whose board really moved, the journal
legs the full loop runs (one pooled conference call, then the national one,
each capped), pointed at the home's level (`TOUCHLINE_NCAA_DIVISION=<level>`,
with the site home's `TOUCHLINE_DATA_DIR` and `TOUCHLINE_JOURNAL_DIR` dropped,
as touchline-ui's `just journal-d1` does). The validated files land in
`journal/<level>/` and are committed on touchline-ui's `main` as
`chore(journal): cadence regeneration <date> <level> [<keys>]`, then pushed;
a checkout on any other branch is logged and left uncommitted, as in the loop.
A quiet morning spends no model call. It never publishes and never pushes the
data home; the site's own run, later the same morning, publishes what it
wrote. The site home is refused `collect-journal`: it journals inside its
loop.

Schedule it ahead of the site's 06:30 run. A Division I collect of 23
conferences takes about ten minutes and its journal about as long again, so a
05:30 start lands both before the site publishes; a run that overruns is
caught by the next morning's publish, and the site labels a journal older than
its board ("JOURNAL WRITTEN FOR AN EARLIER COLLECT") until then.

### Running a second home's cadence

A second launchd job, beside the first, with the home in its environment:

```xml
<key>Label</key><string>ai.edinsights.touchline-collect-d1</string>
<key>ProgramArguments</key>
<array>
  <string>/usr/bin/caffeinate</string><string>-i</string><string>-s</string>
  <string>/bin/sh</string>
  <string>/Users/{you}/.keelson/scripts/touchline-collect-cadence.sh</string>
  <string>collect-journal</string>
</array>
<key>EnvironmentVariables</key>
<dict><key>TOUCHLINE_DATA_HOME</key><string>/Users/{you}/keelson/d1-soccer</string></dict>
<key>StandardOutPath</key><string>/Users/{you}/.keelson/logs/touchline-collect-cadence.d1-soccer.log</string>
<key>StandardErrorPath</key><string>/Users/{you}/.keelson/logs/touchline-collect-cadence.d1-soccer.log</string>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>5</integer><key>Minute</key><integer>30</integer></dict>
```

The shim is the same file: it resolves the package once and passes
`TOUCHLINE_DATA_HOME` through, and its own `FATAL` goes to the same per-home
log. The home must be a git repository (change detection needs one) and a
registered keelson project named for its directory (`TOUCHLINE_PROJECT`
overrides). Check it first with `TOUCHLINE_DATA_HOME=~/keelson/d1-soccer sh
~/.keelson/scripts/touchline-collect-cadence.sh plan`.

## Divisions: men's and women's in one morning

The rib config (`~/.keelson/rib-touchline/config.json`) may name the
divisions the data home follows, and pin a division's conference set:

```json
{
  "packageDir": "…",
  "dataDir": "…",
  "genders": ["men", "women"],
  "conferences": { "women": ["GAC"] }
}
```

With more than one gender named and no `TOUCHLINE_GENDER` set (launchd sets
none), `loop` and `collect` run the script once per gender, in the listed
order, and exit with the worst status. Each run is an ordinary single-gender
run: it takes the lock, sweeps, collects, rolls back, journals, commits,
publishes and writes its own run record (`gender` tells them apart).

- `conferences.{gender}` pins that gender's set; a gender without one
  resolves its set from membership, as before. The women's division follows
  only what the site publishes for women, so it is pinned: membership also
  carries women's MIAA windows the collector has no stanzas for.
  `TOUCHLINE_CONFERENCES` still pins every gender at once.
- `TOUCHLINE_GENDERS` (`men,women`) overrides the config's list and is
  exported to every run, because `just publish` in touchline-ui builds one
  site per listed gender (the women's at `/women/`, behind the Men / Women
  switch). A publish from either run therefore carries both sites.
- Only the first run may archive: the archive leg tars every gender's cells
  in one pass, so later runs get `TOUCHLINE_ARCHIVE_DAY=0`.

A run with `TOUCHLINE_GENDER` set, or a config naming one gender or none, is
the single run it always was.

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
back, so a quiet day leaves no commit and spends no model call. The stamp
that churn carried is not thrown away with it: the run hands it to the
journal legs and the publish as `TOUCHLINE_RECOLLECTED`
(`{conference}={collected_at} ...`), and the site dates that conference by it
(its freshness line and its "today"). A day where every conference came back
unchanged still republishes the site for the same reason; a day where none
collected publishes nothing. A re-run of an already-collected day converges
to "nothing to journal".

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
`~/.keelson/locks/touchline-collect-cadence.lock` (the default home's; another
home's carries its key, [A second data home](#a-second-data-home)). It makes a second cadence
start a logged no-op (`cadence already running (pid {n}) - exiting without
work.`, exit 0); a lock whose PID is gone is taken over, and `version` mode
never takes it. The backfill workflow's preflight reads the same lock, the
one for the home it runs in, and refuses with `REFUSED: the touchline cadence
for this data home is running (pid {n}, lock {path}); retry after it
finishes.` while that PID is live; another home's cadence running is no
reason to refuse.

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

`~/.keelson/logs/touchline-collect-cadence.log` (another home's log carries
its key, [A second data home](#a-second-data-home)), appended by every run. Lines
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
and records the build stamp, an unchanged conference's collect stamp reaches
the journal legs and the publish while its board keeps the committed one, a
quiet run republishes without a journal or a commit while a run that
collected nothing publishes nothing, a second concurrent start is a no-op, a run
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
