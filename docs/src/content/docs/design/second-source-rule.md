---
title: The second-source rule
description: "A data-integrity check counts only when it compares a fact against an independently collected copy of it, and only after it has been shown to go red on a planted error."
sidebar:
  order: 8
---

## The error that passed every check

On 2026-09-01 a forecasting session cross-checked every box score against
its fixture by team name and found 33 results stored reversed, twenty of
them Oklahoma Christian's. The schedule parser had read "L, 3-2" as the
owner scoring 3, because most sites print the owner's score first and
oceagles.com prints the winner's. Every check in the data-integrity
workflow was green the whole time.

They were green because they were self-consistent. The box-score orienter
set `home_index` by matching the box's scores to the fixture's, so a
reversed fixture produced a reversed `home_index`, and the two errors
cancelled on every surface that read them together. Goal attribution
summed a programme's goals across both slots of every scoreline, so a swap
changed nothing it could see. A check that compares a value with something
derived from that value measures the derivation, not the value.

## Decision

A data-integrity check counts only if it has a **second source**: a copy of
the same fact collected by a different parser from a different page, or
authored by a different hand. The two sides of the comparison must be able
to disagree; if one was computed from the other, the check is a tautology
and does not join the family.

And a check is served only after it has been **shown to go red** on a
planted error. Before it is wired into the report, run it against a data
home where the error it exists to catch has been introduced by hand, see it
name that row, then run it clean. A check that has never failed has never
been measured. Count the served checks after `keelson restart`; the number
in the report is the number that ran, and a remembered count is not a
measurement either.

## The family, and each check's second source

| check | the fact | its second source |
|---|---|---|
| `twin-check` | a match's scoreline and status | the opponent's own season file, collected from the opponent's site |
| `box-vs-fixture` | a match's scoreline and which side is home | the box score's published team names, resolved through the collector's identity rules; never the stored `home_index`, which was derived from the fixture |
| `goal-attribution` | a programme's goals | the stats page's per-player goals, a different page from the schedule |
| `exhibition-markers` | whether a match is a friendly | the text the page printed beside the venue, against the parsed flag |
| `membership-sync` | the membership record | the rib's packaged, reviewed copy against the data home's mirror |
| `collect-gaps` | what a collect could not prove | the gap ledger the collect wrote, against the layers on disk |

A match only one followed programme played has no twin, which is why
`box-vs-fixture` exists beside `twin-check`; a box score that names a team
no stanza alias resolves is counted as unresolved and named, never passed,
because an unresolved comparison is not an agreement.

## What this rules out

- A check whose two sides share a parser.
- A check that reads `home_index`, `conference_game_source`, or any other
  field the collector derived, as if it were evidence about the field it
  was derived from.
- A check wired into the report on the strength of a green run. Green
  proves nothing until red has been seen.

## Related

- [Contracts beat examples](../contracts-not-examples/): the quality bar is
  written as rules a script can check; this is the rule for the checks.
- [Gates](../../concepts/gates/): a check that cannot run alarms, and is
  never confusable with a pass.
- [Audit the data](../../guides/audit-the-data/): running the family.
