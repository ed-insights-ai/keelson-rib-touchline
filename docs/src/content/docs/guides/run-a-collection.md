---
title: Run a collection
description: Collect one conference-season into a Touchline data home, read the run's GAP lines, and check the coverage manifest it writes.
sidebar:
  order: 3
---

A collection fills one conference-season unit: the season files
`data/fixtures/{season}-{gender}-{conference}.json` and their roster, stats,
and matches siblings, the raw pages behind them, and the coverage manifest
recording what landed. One conference-season per run. You need a
[data home](../create-a-data-home/) first; the examples use the GAC, the
first deployment.

## 1. See what already exists

Ask read-only first. The `touchline_status` tool reports each collected
season's fixture and roster counts and any named gaps, or tells you the
folder is empty and ready to become a data home.

## 2. Collect from chat

`touchline_collect` is the front door. In the Touchline chat, name a target,
a gender, and a season: "Collect GAC men {season}". The tool
(`src/tools.ts`) then:

1. Plans the season (`planForSeason` in `src/season.ts`): a season the sites
   have not published yet, or one that predates the readable season pages,
   is refused at plan time; anything plausible attempts all four layers.
2. Resolves the target against the authored membership record
   (`resolveTargets` in `src/membership.ts`), never a hardcoded list. Past
   the last authored season the member list is carried forward and the run
   is flagged as extrapolated.
3. Refuses any directory that is neither empty nor already a Touchline home,
   then bootstraps the data home.
4. Runs the pipeline collector with the project root as the data directory:

```sh
TOUCHLINE_DATA_DIR={data-home} uv run --project {package-dir}/pipeline collect-board \
  --conference GAC --gender men --season {season} \
  --programmes {slug},{slug} \
  --layers schedule,roster,stats,matches
```

Pass `refetch: true` to append `--refetch`, which re-fetches every stored box score and page instead of reusing the ones whose fixture results are unchanged (for a parser change); `touchline-backfill` takes the same `refetch` input.

The subprocess budget scales with the fleet the run can become
(`collectTimeoutMs` in `src/season.ts`), because a one-programme ask can
widen (the scope widening below).

## 3. Or run the workflow

An archive season is a long call, and chat clients have deadlines. For an
archive season, start the `touchline-collect` workflow with `workflow_run`
instead and it runs durably. Its nodes (`workflows/touchline-collect.yml`):
`preflight` refuses any working directory without a `touchline-data.yaml`
marker declaring `kind: touchline-data`; `resolve-pipeline` locates the
installed pipeline; `resolve-programmes` reads the conference's members for
the season from the packaged membership record, the same resolver the tool
uses; `collect` runs the identical CLI; `report` writes a prose summary that
is forbidden to invent a number. Inputs: `conference`, `gender`, `season`,
plus optional `programmes` (slugs to narrow the run), `layers` and
`membership_extrapolated`.

For a multi-season backfill, start `touchline-backfill` with `conference`,
`gender`, `from_season` and `to_season` (at most 8 seasons per run). It runs
one collect node per season, in order, under one lock, and reports every
season's outcome in one summary; a failed season is named and the later
seasons still run. See [Workflows](../../reference/workflows/).

## 4. Read the output

Watch for four kinds of line:

- **Scope widening.** Season files are written wholesale, so a narrow rerun
  could silently discard other programmes' data. Instead,
  `widen_to_existing_scope` in `pipeline/scripts/collect_board.py` absorbs
  the file's existing scope: asking for one programme after a conference
  collection refreshes the whole unit, and the run prints "scope widened to
  the season unit" naming the absorbed slugs.
- **Per-layer summaries**: programmes served per layer, fixtures split into
  played and upcoming, roster players, player season lines, how many played
  fixtures carry a collected box score, and any collapsed duplicate rows
  (a conference game is published by both schedules).
- **Borrowed exhibition marks.** A friendly is a property of the match, not
  of the page that printed it. When one side's schedule marks a fixture
  exhibition and the twin row sits unmarked in another conference's season
  file for the same season and gender, the collect stamps `match_type`
  `exhibition` on its own freshly parsed row and prints `exhibition
  borrowed: {date}, {home} v {away}, from {conference}` once per row, so the
  cadence log explains a file that changed when its own source did not. The
  other file is only read, never written; a row that already carries any
  `match_type` is never touched; nothing else crosses (not scores, time,
  venue or the conference flag). Because every run starts from the page and
  the sibling files again, a borrowed mark drops on its own if the other
  side withdraws it, and every conference converges within one cadence.
- **GAP lines.** Every named gap prints as a `GAP:` line naming the
  programme and layer (or the match) and the reason. Gaps are data, not
  failure: they land in the coverage manifest and in
  `data/errors/collect-board-{season}-{gender}-{conference}.json`.

## 5. What success and failure mean

Exit 0 means exactly one thing: the coverage manifest was written and
describes reality, gaps and all. A run that serves every programme but one
is a success carrying one named gap. Exit 1 means the manifest write itself
failed; exit 2 is a usage error (an empty programme list, an unknown layer).
The chat tool and the workflow's `collect` node treat any non-zero exit as a
failed run that claims nothing.

Every served page is archived verbatim to `data/raw_html/`
(`write_raw_pages` in `pipeline/src/sidearm_live.py`), so any parse can be
redone offline.

## 6. Check the coverage manifest

`data/coverage.json` (schema `touchline.coverage/1`) holds one cell per
`{season}/{gender}/{programme}/{layer}` in one of four states:
`no-collector`, `unavailable`, `empty`, `complete`. The manifest is merged,
never overwritten (`merge_cells` in `pipeline/src/coverage.py`): this run's
cells join last week's.

```sh
jq -r '.cells | to_entries[]
  | select(.key | startswith("{season}/{gender}/"))
  | "\(.key)  \(.value.state)"' data/coverage.json
```

An `unavailable` cell carries the reason the source refused; `empty` means
the source served a page with nothing in it, which is a different fact.

**What you just exercised:**
[Absence is data](../../concepts/absence-is-data/) (named gaps and coverage
cells), [Archive first](../../concepts/archive-first/) (every served page
archived verbatim for offline re-parse), [Season is a dimension](../../concepts/season-and-membership/)
(the resolved fleet and the extrapolation flag), and
[Five layers](../../concepts/five-layers/) (where collection sits in the
system).

## Related

**Run it**

- [Work the board](../work-the-board/): see the collection you just made, gaps and all.
- [Data on disk](../../reference/data-on-disk/): the exact contracts of the files the run wrote.

**Understand it**

- [Absence is data](../../concepts/absence-is-data/): why exit 0 tolerates gaps and the manifest records them.
- [Stand up a season](../../tutorials/first-season-board/): the lab that starts from this run.
