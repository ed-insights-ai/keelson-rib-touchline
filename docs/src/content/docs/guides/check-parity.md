---
title: Check two data homes for parity
description: "Compare two data homes record by record (fixtures, box scores, rosters, season statistics, coverage cells and references) and separate real disagreements from differences a later collection is expected to see. The cloud pipeline's cutover gate."
sidebar:
  order: 12
---

Until cutover, the cloud pipeline writes a `shadow` branch of each data home
while the Mac cadence keeps writing `main`. The new pipeline replaces the Mac
only once shadow matches main, and `check-parity` is what decides that.

```bash
cd pipeline
uv run check-parity ~/keelson/d2-soccer@main ~/keelson/d2-soccer@shadow \
  --record collect-record.json --report parity.md --json parity.json
```

Each side is a data-home directory, or a commit of a data-home clone written
`PATH@REF`. A ref is read with `git cat-file`, so nothing is checked out and
the working tree is never touched. The first side is the reference copy
(expected), the second is the one under test (actual).

## What counts as a match

Every season file is split into records, and each record is compared on its
own:

| Layer | Record | Key |
|---|---|---|
| fixtures | one fixture row | fixture `id` |
| matches | one box score, or its `missing` gap | match id |
| rosters | one programme's roster | programme slug |
| stats | one programme's season statistics | programme slug |
| coverage | one cell of `data/coverage.json` | cell key |
| reference | `membership.json` and `programmes.json`, each as one record | file |

Each season file's header (the programmes it names, its `missing` gaps, how
conference games were decided) is compared too, as one record per file.

A record is a **match** only when both sides are equal. The only fields left
out are the ones that say when a collect ran: `collected_at`, and a cell's
`confirmed_at` and `verified`.

A difference is **timing** only when a later collection could have seen
something the earlier one couldn't, and the later side moved forward, never
back:

- a fixture went from scheduled to live or final, was moved, or was first
  listed, and the game is dated no more than `--lag-days` (default 3) before
  the earlier collection;
- a box score was posted, or revised by the host, within that window;
- a team's season totals grew (no counting stat went down, no player
  vanished) and the team has a game between the two collections;
- a coverage cell's count or reason moved with such a game, and its state
  didn't get worse.

Everything else is a **disagreement**. That includes a final score that
differs, a box score or played fixture that vanished, totals that went down
or moved with no game in between, any roster difference (rosters don't move
with games), a gap on one side only, two collections made within a minute of
each other that differ at all, and a box score no fixture dates. Two sides
whose reference files differ ran different rib versions, and the check says
so.

When collections are days apart, schools' edits to roster and stats pages
show up as disagreements. That is deliberate: the check can't tell a school's
edit from a parsing difference without the raw page. The report says how far
apart the sides were collected. Re-collect both sides together to settle it.

## What it doesn't compare

The check never counts these as matches, and the report lists each one:

- **Not compared:** `data/errors/`, `data/reports/`, `data/research/`,
  `data/raw_html/`, a sample's `data/sample.json`, and symlinks.
- **Unproven:** a season file or coverage cell with the same collection stamp
  on both sides. A shadow branch starts as a copy of main, and the cloud
  collect doesn't commit a change that touches only `collected_at`, so an
  identical stamp proves nothing about the new pipeline. Pass the run's
  `collect-record.json` with `--record`: a unit it marks `changed` or
  `no-change`, with its own `collected_at`, is compared at that time. To
  compare two commits of the same home, or a sample against itself, pass
  `--compare-inherited` instead. Same-stamp records are then judged as
  collected at the same moment.
- **Excluded:** units a run record marks `skipped`, `failed` or `lost`.

`--require-complete` turns unproven and excluded into a failure. The cutover
gate sets it.

## Output and exit codes

- `--report FILE` is the Markdown report: the verdict and counts, a table of
  disagreements folded by the fields they touch, then every disagreement and
  timing difference grouped by programme and dated, each with its fields
  (expected and actual) and why it was classed that way. With neither
  `--report` nor `--json`, the report goes to stdout.
- `--json FILE` is the `touchline.parity/1` result: `verdict`, totals and
  per-layer counts, every finding, and the unproven, excluded and
  not-compared lists.
- `--summary FILE` appends the report, for example to `$GITHUB_STEP_SUMMARY`.
- The last line on stdout is always one JSON verdict line, as with
  `check-contracts`.

Exit 0 means parity. Exit 1 means at least one record disagrees, or
`--require-complete` wasn't met. Exit 2 means the check couldn't run: an
unreadable home, homes at different levels, an unknown schema, or a file
under `data/` it has no rule for. An exit 2 is an alarm and is never treated
as parity: teach the check the new file or schema first.
