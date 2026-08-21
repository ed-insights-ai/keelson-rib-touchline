---
title: Stand up a season
description: Init a data home, collect a real GAC conference season, read the coverage manifest it writes, and chase your first named gap from the board back to disk.
sidebar:
  order: 2
---

Every lab on this rail grades you against a real data home, and this lab
builds it. You will create the home, fill it with one GAC conference season,
and then do the thing that separates Touchline from a scraper with a
spreadsheet: read what did *not* land, and why, in the system's own words.

By the end you can:

- create a Touchline data home and prove its marker and scaffold on disk
- collect one conference season and read the per-layer summary it prints
- name the four coverage states defined in `pipeline/src/coverage.py` and
  list which ones your manifest holds
- demonstrate the exit-code contract: a run with named gaps still exits 0
- follow a gap from a board marking to its coverage cell and recorded reason

You need the rib installed ([Install](../../guides/install/)), plus `jq` and
`uv` for the disk checks. Pick a completed season for `{season}` (any year
back to 2016 serves results and box scores); the labs after this one need
played matches, so a finished season serves the whole rail. The current
season works too, and in August the board will honestly stamp it pre-season.

## 1. Try it: create the home

In the Touchline chat, call `touchline_init` with a folder name (the
composer command `/touchline {folder-name}` does the same through the same
code path, `initTouchlineHome` in `src/commands.ts`). The reply names the
created path; that path is `{data-home}` below. Re-running is safe: an
existing home is reported, never overwritten.

What makes this directory a data home is one marker file,
`touchline-data.yaml` with `kind: touchline-data` (`MARKER_FILE` and
`MARKER_KIND` in `src/datahome.ts`). Every write path checks it, so a
collection can never scribble into a folder that is not empty or ours.

**Check yourself**: the marker and the four layer directories exist; verify
with this command:

```sh
grep -c "kind: touchline-data" {data-home}/touchline-data.yaml
ls {data-home}/data
```

The grep prints `1`, and the listing shows `fixtures`, `rosters`, `stats`,
`matches`, `raw_html`, `errors`, and `reference`.

## 2. Try it: collect GAC men {season}

Still in chat: "Collect GAC men {season}". The `touchline_collect` tool
resolves the fleet from the membership record, plans the season, and runs
the pipeline collector ([Run a collection](../../guides/run-a-collection/)
walks the machinery). Read the reply top to bottom: the plan line, the
resolved programme list, then per-layer summaries and any `GAP:` lines.
Each GAP names what was refused (a programme, one of its layers, or a
single match) and the reason, and none of them failed the run.

**Check yourself**: the run's real deliverable is the coverage manifest;
verify with this command:

```sh
jq -r '.schema' {data-home}/data/coverage.json
```

Exactly one line: `touchline.coverage/1`.

## 3. Try it: enumerate your coverage states

Every cell in the manifest is keyed `{season}/{gender}/{programme}/{layer}`
and carries one of four states, defined as the `STATE_` constants in
`pipeline/src/coverage.py`: `no-collector`, `unavailable`, `empty`, and
`complete`. The docstring of that module names the distinction they exist to
protect: "not collected yet", "not published yet", and "no collector exists"
must never be conflated. [Absence is data](../../concepts/absence-is-data/)
is the essay; your manifest is the instance.

List the states your collection actually produced:

```sh
cd {data-home}
jq -r '[.cells[].state] | unique[]' data/coverage.json
```

**Check yourself**: every printed line is one of the four names above, and
`complete` is among them; verify against the constants with this command
(`{package-dir}` is the installed rib package root):

```sh
grep "^STATE_" {package-dir}/pipeline/src/coverage.py
```

## 4. Try it: the exit-code contract, on a practice home

Exit 0 does not mean "everything served". It means the manifest was written
and describes reality, gaps and all (the closing comment of `main` in
`pipeline/scripts/collect_board.py`). Prove it without touching your real
home or the network: point `TOUCHLINE_DATA_DIR` at a scratch practice
directory and ask for a programme that does not exist. An unknown slug is
refused before any fetch and recorded as `no-collector`.

```sh
mkdir -p {practice-dir}
TOUCHLINE_DATA_DIR={practice-dir} uv run --project {package-dir}/pipeline collect-board \
  --conference GAC --gender men --season {season} \
  --programmes not-a-school --layers schedule
echo $?
```

The run prints one `GAP:` line naming `not-a-school` and its reason, then
the shell prints `0`.

**Check yourself**: the gap landed in both places gaps live; verify with
this command:

```sh
jq -r '.cells["{season}/men/not-a-school/schedule"].state' {practice-dir}/data/coverage.json
jq -r '.errors[]' {practice-dir}/data/errors/collect-board-{season}-men-gac.json
```

The first prints `no-collector`; the second prints the same reason the GAP
line named.

## 5. Try it: chase a gap from the board to disk

Open the Touchline surface and pick your project; the board renders your
season ([Work the board](../../guides/work-the-board/) is the field guide).
Two markings claim absence, and each is chased differently.

**The gaps notice.** If any programme's layer is missing, the sheet shows a
"collection gaps" notice naming each programme and layer, and the tally
shows a Gaps count. Chase one: list every cell that is not complete, with
its reason, then find the same reason string in the errors file.

```sh
jq -r '.cells | to_entries[] | select(.value.state != "complete")
  | "\(.key)  \(.value.state)  \(.value.reason // "-")"' data/coverage.json
jq -r '.errors[]' data/errors/collect-board-{season}-men-gac.json
```

Now say what one GAP line means in a single sentence of your own: which
programme, which layer, and whether the source refused it (`unavailable`),
served nothing (`empty`), or has no recipe (`no-collector`).

**The rail's honesty check.** An unfilled tick behind today is a match past
its date whose site still publishes no result; the rail's footer counts it
as "past date, no result published". That is the site's silence, not a
collection gap: the owner's schedule cell reads `complete`, and the fixture
row itself carries the evidence.

```sh
jq -r --arg today "$(date +%F)" '.fixtures[]
  | select(.status == "scheduled" and .date < $today)
  | "\(.date)  \(.home) v \(.away)  \(.source_url)"' data/fixtures/{season}-men-gac.json
```

**Check yourself**: the count this prints equals the rail footer's count (a
completed archive season usually prints nothing, and the footer then falls
back to the plain week count); and every board gap you chased has a coverage cell whose
`reason` is non-empty, or an entry in a season file's `missing` manifest;
verify with this command:

```sh
jq -r '.missing // [] | .[]' data/fixtures/{season}-men-gac.json \
  data/rosters/{season}-men-gac.json data/stats/{season}-men-gac.json
jq -r '.missing // {} | to_entries[] | "\(.key)  \(.value)"' data/matches/{season}-men-gac.json
```

## Next stop

Your data home now holds season files, a manifest that tells the truth
about them, and, underneath it all, every served page archived verbatim in
`data/raw_html/`. The next lab opens those pages and parses one the hard
way: [Read a page the way the parser does](../read-a-raw-page/).

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): the same collection as
  an operator task, including the workflow for long archive runs.
- [Data on disk](../../reference/data-on-disk/): the contract of every file
  this lab created.

**Understand it**

- [Absence is data](../../concepts/absence-is-data/): why four states, and
  what each licenses a reader to conclude.
- [The syllabus](../syllabus/): where this lab sits on the rail, and the
  three lab modes it uses.
