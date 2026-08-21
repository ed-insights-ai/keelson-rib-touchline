---
title: Audit the data
description: Run the read-only integrity checks, from the fail-closed data-integrity workflow to the standalone conference, completeness, membership, and caption audits.
sidebar:
  order: 9
---

Every audit here is fail-closed: a check that cannot run alarms, loudly, and
is never confusable with a pass. None of them writes to the database.

## 1. Run the data-integrity workflow

Run it against the data home:

```bash
keelson workflow run data-integrity
```

`workflows/data-integrity.yml` rebuilds the parquet export offline from the
raw archive, then runs eleven deterministic read-only checks against it and
live Postgres. Each check emits a one-line JSON verdict (`check`, `verdict`,
`headline`, `cause`), and the report node renders them as a verdict table: a
rollup line (`CLEAR`, `WARN`, or `ALARM`, the worst of all checks, with
counts) and one row per check.

| Check | What it measures |
|---|---|
| freshness | game count, newest game date, seasons present |
| conference-flag | rows with a NULL `is_conference_game` or `away_conference` |
| conference-derivation | shells the conference audit and validates its verdict line |
| duplication | duplicate (date, home, away, gender) groups and score disagreements |
| season-label | seasons whose game dates or URL year contradict `season_year` |
| identity | scored games where the school matches neither team slot |
| discipline | red-card coverage across enabled programs |
| orphans | games missing team stats, player stats, or events; implausibly long seasons |
| parse-failures | unparsed box scores waiting in `data/errors` |
| archive | Postgres row count vs the per-school parquet exports; archive git drift |
| export-staleness | the merged parquet export vs Postgres; retired-ordinal rows |

## 2. Tell a failed check from a pass

The workflow's rule, stated at the top of the file: every check must alarm
when it cannot run. The checks discard query stderr, so a dead database, a
dropped table, or a timeout all arrive as an empty capture. Each check
asserts that every captured value is non-empty, and when any is missing it
emits an alarm whose headline says the check `DID NOT RUN` (a two-sided
check names the half that failed) and names the captures that came back
empty. A real pass always carries measured numbers. "The query failed" and
"the data is clean" are never the same line, so an `ok` verdict with blank
numbers is a bug in the check, not a pass. The same discipline covers the filesystem checks: a missing or
unreadable `data/errors` directory is `CHECK DID NOT RUN`, because a missing
directory is not an empty one.

## 3. Conference audit

```bash
uv run --project pipeline conference-audit
```

`pipeline/scripts/conference_audit.py` opens a read-only transaction
(`connection.set_session(readonly=True)`), recomputes every game's
conference status from canonical identities and membership, and compares
against the stored flags. `DATABASE_URL` or `--database-url` overrides the
default DSN. Verdicts escalate through a lattice, ok below warn below alarm,
and only ever rise (`_raise_verdict`): NULL stored flags warn, because
agreement cannot yet be verified; disagreements, unresolved identities, and
standing violations alarm. Standing violations carry named rules from
`pipeline/src/conference.py`: `women-vs-mens-affiliate`,
`men-vs-oklahoma-baptist`, `pre-2019-men-vs-affiliate`. The verdict rides
the final JSON line, not the exit code; a query failure prints a
`CHECK DID NOT RUN` payload and exits 1.

## 4. Database completeness

```bash
uv run --project pipeline audit
```

`pipeline/scripts/audit.py` prints a per-school table built with a LEFT
JOIN, so an enabled school with zero games still appears, marked `EMPTY`,
then totals and acceptance checks: a floor on total games, no empty schools, and
`home_conference` coverage. The verdict rides the printed PASS/FAIL lines.

## 5. Membership validation

```bash
TOUCHLINE_DATA_DIR={data-home} uv run --project pipeline check-membership
```

`pipeline/scripts/check_membership.py` validates the authored
`data/reference/membership.json`: the structural codes `independent` and
`non_member` must be declared, every window must carry a non-empty source
citation, per-programme coverage must have no gaps (the error tells you to
cover them explicitly with an independent or non_member window) and no
overlaps, and every configured programme must be covered. Exit 0 prints the
programme and window summary; exit 1 prints every violation.

## 6. Caption orientation

```bash
cd pipeline
TOUCHLINE_DATA_DIR={data-home} uv run python scripts/check_sidearm_captions.py
```

`pipeline/scripts/check_sidearm_captions.py` audits the population of a
known historical home/away swap in SideArm roster attribution: it re-parses
every cached SideArm page, matches parsed players to stored parquet rows by
a composite key with multiset semantics, and classifies each stored game by
goalie-caption prefix match into `aligned`, `swapped`, `ambiguous`,
`unmatched`, or `missing_pages`. It prints one JSON report and exits nonzero
unless every game aligned.

**What you just exercised:** [Gates](../../concepts/gates/),
[Absence is data](../../concepts/absence-is-data/),
[Identity](../../concepts/identity/), and
[Season is a dimension](../../concepts/season-and-membership/).

## Related

**Run it**

- [Rebuild from the archive](../rebuild-from-the-archive/): the repair path when a check finds derived stores drifting.
- [Workflows](../../reference/workflows/): the data-integrity workflow contract.

**Understand it**

- [Break a gate](../../tutorials/break-a-gate/): fail-closed refusal, exercised by hand.
- [Absence is data](../../concepts/absence-is-data/): why a missing measurement must never read as zero.
