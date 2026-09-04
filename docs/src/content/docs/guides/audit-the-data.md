---
title: Audit the data
description: Run the read-only integrity checks, from the fail-closed data-integrity workflow to the standalone membership validation.
sidebar:
  order: 9
---

Every audit here is fail-closed: a check that cannot run alarms, loudly, and
is never confusable with a pass. None of them writes to the data home.

## 1. Run the data-integrity workflow

Run it against the data home:

```bash
keelson workflow run data-integrity
```

`workflows/data-integrity.yml` runs seven deterministic read-only checks
against the season JSON layers (`data/fixtures`, `data/stats`,
`data/matches`), the collect gap ledger (`data/errors`), and the membership
reference. Every check compares against a second, independently collected
copy of the fact ([The second-source rule](../../design/second-source-rule/)).
Each check emits a one-line JSON verdict (`check`, `verdict`,
`headline`, `cause`), and the report node renders them as a verdict table: a
rollup line (`CLEAR`, `WARN`, or `ALARM`, the worst of all checks, with
counts) and one row per check.

| Check | What it measures |
|---|---|
| collect-gaps | collect-board gap ledger files waiting in `data/errors`, each naming the layers a run could not prove and why |
| goal-attribution | per-programme scoreboard goals (fixtures layer, exhibitions and scoreless finals excluded and counted) vs summed player goals (stats layer), every divergence named with both figures |
| exhibition-markers | fixtures whose stored venue or opponent text says friendly or exhibition while `match_type` is unset, each named |
| membership-sync | the data home's mirrored `data/reference/membership.json` vs the rib's packaged source of record, canonicalized; a divergence warns with the exact diff |
| programmes-sync | the data home's mirrored `data/reference/programmes.json` (`touchline.programmes/2`: nickname, town, point, provenance per programme) vs the rib's built source of record, canonicalized; a divergence warns with the exact diff |
| twin-check | every match collected from both sides (two season files, same date and slugs): unordered score and status must agree; the home side is not compared, since a neutral site differs there honestly |
| box-vs-fixture | every box score against its fixture by team name, the names resolved through the collector's identity rules; reversed or different scorelines named, a disagreeing stored `home_index` named, unresolved names counted and never passed |

The twin-check leans on one collector rule: a fixture is `final` only when it
carries both scores. A schedule row whose completed class or "Final" span
comes with no parsed score (a preseason exhibition whose result was never
entered, a page fetched before the score was posted, a letter the printed
numbers contradict) is stored `scheduled` with no score, and the collect log
names it by fixture id (`page reads final with no score`). A status word
anywhere on the row wins over both signals: rescheduled, postponed, "PPD",
"Post.", a make-up date or "suspended" store `postponed`, and "cancelled"
stores `cancelled`, except that a word printed outside the result cell on a
row that also prints a score ("Rescheduled from 9/23" beside "L, 2-3") is a
note on a played make-up date and the score wins. Two collectors of one
match therefore agree on played-versus-unplayed, which is what the fold on
the site requires (beads tl-d69, tl-md2).

A forfeit is the one final without a measured scoreline. A row whose result
cell or promotion says forfeit ("Win by forfeit", "Loss by forfeit",
"forfeited") is stored `final` with `forfeit` naming the awarded side,
`home` or `away`, read from the letter: W on a programme's own page awards
that programme's slot, L the opponent's. The scores are the printed ones
when the host prints them (Upper Iowa 2024, "W, 2-2" beside "Win by
forfeit", is stored 2-2 with `forfeit: "home"`), else 1-0 to the awarded
side; a row without the word never carries `forfeit`, and a level score
beside a W or L with neither a shootout nor a forfeit word is still refused
(bead tl-wyv).

## 2. Tell a failed check from a pass

The workflow's rule, stated at the top of the file: every check must alarm
when it cannot run. Each check asserts that every captured value is
non-empty, and when any is missing it emits an alarm whose headline says the
check `DID NOT RUN` and names the captures that came back empty. A real pass
always carries measured numbers. "The measurement failed" and "the data is
clean" are never the same line, so an `ok` verdict with blank numbers is a
bug in the check, not a pass. The same discipline covers the filesystem: a
missing or unreadable `data/errors` directory is `CHECK DID NOT RUN`,
because a missing directory is not an empty one, and a season file `jq`
cannot read fails the sweep rather than reading as clean.

## 3. Membership validation

```bash
uv run --project pipeline check-membership
```

`pipeline/scripts/check_membership.py` validates the authored
`data/reference/membership.json` (the rib's packaged source of record,
which the loader prefers); the data home's mirrored copy is only the
fallback for an install shipping no packaged data tree, and the
data-integrity workflow's `membership-sync` check reports any drift
between the two. The validation: the structural codes `independent` and
`non_member` must be declared, every window must carry a non-empty source
citation, per-programme coverage must have no gaps (the error tells you to
cover them explicitly with an independent or non_member window) and no
overlaps, and every configured programme must be covered. Exit 0 prints the
programme and window summary; exit 1 prints every violation.

**What you just exercised:** [Gates](../../concepts/gates/),
[Absence is data](../../concepts/absence-is-data/), and
[Season is a dimension](../../concepts/season-and-membership/).

## Related

**Run it**

- [Run a collection](../run-a-collection/): the repair path when a check names a lagging layer, re-collect it.
- [Workflows](../../reference/workflows/): the data-integrity workflow contract.

**Understand it**

- [Break a gate](../../tutorials/break-a-gate/): fail-closed refusal, exercised by hand.
- [Absence is data](../../concepts/absence-is-data/): why a missing measurement must never read as zero.
