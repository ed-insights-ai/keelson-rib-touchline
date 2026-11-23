---
title: Collect in GitHub Actions
description: "The daily collect without Keelson or a model: the Collect workflow, its hosted and PrestoSports jobs, the shadow branch, the raw-HTML cache in S3, the run record, the dry run, and what has to be set up before it runs for real."
sidebar:
  order: 12
---

The `Collect` workflow (`.github/workflows/collect.yml`) runs the same
collector as the [daily cadence](../daily-cadence/), `collect-board`, straight
from a GitHub Actions job. There is no Keelson server and no model call: a
small driver, `uv run collect-direct` (`pipeline/scripts/collect_direct.py`),
does what the cadence's `collect` mode does around each `collect-board` call.

Until cutover it writes only to the **`shadow`** branch of each data home and
to the data bucket. The Mac's cadence stays production through the season,
and the parity check compares `shadow` with `main`.

## What one run does

1. **Plan.** For every level in the one levels list (`src/levels.ts`, the same
   list as `divisions` in `infra/main/variables.tf`; a test holds them
   together) and each gender, the conferences with a member this season
   resolve from membership (`bin/resolve-membership.ts`, as the cadence does),
   and each conference's programmes with them. A level with no conference yet
   (d3 today) gets no job. Each season unit is routed:
   - **presto** when any of its programmes collects through PrestoSports,
     which answers GitHub-hosted runners with HTTP 405 (the cloud trial,
     PR #155);
   - **hosted** otherwise (Sidearm, WMT, and Harding's StatCrew school, whose
     live pages are Sidearm).

   The split is by unit, never by programme, because `collect-board` writes a
   unit's season files whole. In 2026 that is 80 hosted and 14 presto units.
2. **Collect the hosted units** on `ubuntu-latest`, one job per division.
3. **Collect the presto units** on the self-hosted runner labelled `presto`,
   after the hosted units of that division have landed.
4. **Land** each changed unit on `shadow` as one commit, and archive the raw
   pages to S3.

## The change rules

They are the cadence's, line for line, so the two pipelines agree on what a
change is:

| Result | When | Lands? |
| --- | --- | --- |
| `changed` | a new board file, or a board diff beyond the `collected_at` stamp | yes, one commit `collect(shadow): {CONF} {gender} {season}` |
| `no-change` | the only diff is `collected_at` | no; the stamp is kept in the run record |
| `lost` | a programme HEAD held is now a named gap (`missing`) | no, unless `accept_loss` names the conference |
| `failed` | `collect-board` exited non-zero or passed its 40-minute unit budget | no |
| `skipped` | a presto unit with no presto runner set up | no |

A run with a `failed` or `lost` unit lands every other unit and then ends red,
as the cadence exits 1.

## Work homes and landing

Each job collects into a **work home**: a slim copy of the data home's
`shadow` (the marker, `data/reference/`, `data/coverage.json` and every season
file of the season being collected, since `collect-board` reads sibling
conferences' rosters and boxes for identities) with its own throwaway git
repository. Each changed unit is one commit there.

`collect-direct land` replays those commits onto the `shadow` checkout. Board
and errors files are copied; `coverage.json` takes only the cells that commit
changed, so the hosted and presto jobs never overwrite each other's cells. If
the push is refused because `shadow` moved, it refetches and replays again.

`shadow` is its own lineage: created from `main` on the first run, then
written only by this workflow, so it is what the new pipeline would hold on
its own.

## The raw-HTML cache

The pages `collect-board` fetches, and their `.state.json` sidecars, live in
the data bucket in the same layout as a data home's `data/raw_html/`:

```
s3://touchline-data-{account}/raw/{division}/raw_html/{slug}/{season}-{gender}-{kind}.html (and .state.json)
```

Before collecting, a job restores the season's pages for its units'
programmes (`.github/scripts/raw-sync.sh down`); afterwards it archives what
the work home holds (`up`). Downloads keep the bucket's timestamps, so the
upload sends only new or changed pages. Nothing is ever deleted, and the
Actions cache is never used. The first runs start with an empty cache, which
only means every page is parsed as new; to bring the Mac's cache across, sync
`~/keelson/d2-soccer/data/raw_html/` to `raw/d2/raw_html/` (and d1 the same)
with Daniel's AWS CLI.

## The run record

Every job uploads `collect-record-{division}-{job}` (90 days), a
`touchline.collect-record/1` JSON document:

```json
{
  "schema": "touchline.collect-record/1",
  "division": "d2", "season": 2026, "job": "hosted",
  "run_id": "…", "rib_sha": "…", "started_at": "…", "finished_at": "…",
  "work_base": "…", "target_base": "…", "target_head": "…",
  "target_branch": "shadow", "main_sha": "…", "landed": ["collect(shadow): GAC men 2026"], "pushed": true,
  "units": [
    {"conference": "GAC", "gender": "men", "job": "hosted", "result": "no-change",
     "programmes": 7, "collected_at": "2026-11-24T14:21:07+00:00", "reason": null, "lost": [], "seconds": 41.2}
  ]
}
```

`collected_at` is the new pipeline's own collection time, set for `changed`
and `no-change` units. The parity check (`uv run check-parity`) reads it to
tell a unit this pipeline reproduced from one it merely inherited from `main`.

## The dry run

A pull request that touches the workflow or the driver, or a manual run with
`mode: dry-run`, collects the sample homes' conferences (GAC and A10, from
`samples/*/data/sample.json`) live into copies of `samples/d1-soccer` and
`samples/d2-soccer`. It uses no secrets, no bucket and no push. It passes when
every unit collected without a failure or a loss and `check-contracts` passes
on both copies, and it runs `check-parity` against the samples when that tool
is in the checkout. The copies and records are uploaded as `collect-dry-run`.

## Running it by hand

**Actions → Collect → Run workflow** takes `mode`, `divisions`,
`conferences`, `genders`, `accept_loss` (conferences whose loss is real) and
`refetch`. Manual runs work whatever `TOUCHLINE_COLLECT_UNTIL` says.

## Setting it up

Real runs need, on the rib's `production` environment:

| Setting | Kind | Who | Note |
| --- | --- | --- | --- |
| `AWS_ACCOUNT_ID` | variable | Daniel (infra/RUNBOOK.md) | the OIDC role `touchline-publish` trusts only `production` on `main` |
| `TOUCHLINE_APP_ID`, `TOUCHLINE_APP_PRIVATE_KEY` | variable, secret | Daniel ([GitHub App](https://github.com/ed-insights-ai/keelson-rib-touchline/blob/main/infra/GITHUB_APP.md)) | the App must be installed on `d1-soccer` and `d2-soccer`; it creates and pushes `shadow` |

and two repository variables that switch the schedule on:

| Variable | Effect |
| --- | --- |
| `TOUCHLINE_COLLECT_UNTIL` | `YYYY-MM-DD`. The schedule (14:17 UTC daily) collects through this date. Unset, scheduled runs do nothing. `2026-12-15` ends with the season. |
| `TOUCHLINE_PRESTO_RUNNER` | `true` once a self-hosted runner labelled `presto` is registered. Otherwise the presto units are recorded `skipped` and everything else still lands. |

### The PrestoSports runner

An always-on machine at home (or the Mac), registered to this private repo
only, never to a public one:

1. **Settings → Actions → Runners → New self-hosted runner** on
   `keelson-rib-touchline`; follow the commands it shows, and at
   `config.sh` add `--labels presto`.
2. Install it as a service (`./svc.sh install && ./svc.sh start`) so it comes
   back after a restart.
3. It needs `git`, `tar` and network access to the schools' sites; the job
   installs `uv` itself. It needs no AWS or GitHub App credentials: the presto
   job receives only its work home, and a hosted job lands the result.
4. Set `TOUCHLINE_PRESTO_RUNNER` to `true`.

If the machine is off, the presto job waits in the queue; the hosted units
have already landed, and the next day's run replaces the waiting job rather
than stacking a backlog. Those 14 units are then a day stale.

## Minutes

The hosted jobs run in parallel per division. A daily run is roughly the
cadence's collect time per division plus about two minutes of setup; the dry
run on a pull request is a few minutes. The presto job runs on the home
machine and costs no Actions minutes.
