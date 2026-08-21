---
title: Conference is configuration
description: The decision to model conference membership as dated, cited windows in an authored artifact, with no member list hardcoded in pipeline logic.
sidebar:
  order: 6
---

## Decision

Conference membership is authored data, never code. The artifact is
`data/reference/membership.json`: for each programme and gender, a list of
windows `{conference, from_season, to_season, source}`, each citing its
source. The pipeline reads the data home's copy through
`pipeline/src/membership.py`; the rib reads the copy of the same authored
document shipped inside its package through `src/membership.ts` (see
[Data on disk](../../reference/data-on-disk/)). Neither side owns the answer;
both defer to the authored windows, and no member list appears in logic.
Because the lookup is season-scoped, a school's 2019
results belong to whatever conference its 2019 window names, regardless of
where the school plays today. This page is the decision record;
[Season is a dimension](../../concepts/season-and-membership/) is the concept
page.

## Mechanism

`conference_for` in `pipeline/src/membership.py` is an interval lookup: slug,
gender, and season year in, the covering window's conference out. The
document earns trust by surviving `validate` in the same file, run by the
`pipeline/scripts/check_membership.py` CLI: every window must carry a
non-empty `source` citation, the declared conference list must include the
structural codes `independent` and `non_member`, a programme's authored
seasons may have no gaps and no overlaps, and every configured programme must
be covered. Absence is authored, not inferred.

The season files carry the decision in their names:
`pipeline/scripts/collect_board.py` writes one shard per
`{season}-{gender}-{conference}`, so a file never mixes conferences and the
conference travels with the data.

Where a value is derived rather than published, it says so.
`parse_schedule_page` (`pipeline/src/sidearm_live.py`) takes a theme's own
conference marker as published truth; on themes that mark nothing, it derives
the flag from the configured member set and stamps
`conference_game_source: "derived:membership"` so no derived value can
masquerade as a publisher's claim. The member set is one conference's
membership (`conference_members`), never the whole alias map, because
identity spans every configured school while membership names one
conference: deriving from the alias map would mark a cross-conference
fixture as a conference game the moment a second conference is configured.

One exception is documented. `pipeline/src/conference.py` names GAC facts in
code: `AFFILIATES_SINCE_2019` lists the men's affiliate programmes whose
membership begins in 2019, and the module docstring cites the design
documents it comes from. The reason is independence: this module backs
`audit_rows`, the cross-check that re-derives `is_conference_game` and
compares it against what is stored, and an audit that read its boundary from
the inputs it audits would inherit their mistakes. The exception is scoped to
the audit; the collection path stays configuration-driven.

## Rejected alternatives

**Hardcoded member lists in logic.** The header of `src/membership.ts`
states the rule: conferences change, and the product is meant to expand
beyond the one it started with. A hardcoded list makes every realignment a
code change and quietly rewrites past seasons.

**Inferring membership from observed schedules.** A schedule proves who
played, not who counted for the table. One authored window's citation
preserves the trap: a conference's own statistics pages omitted a school
still inside the Division II provisional period, so reading published pages
as membership would have authored that school's first season wrong.
Inference also cannot cite a source, and the validator requires every window
to.

## Failure semantics

An uncovered season gap fails validation rather than extrapolating:
`check_membership` exits nonzero, and the error names the gap seasons and
instructs the author to cover them explicitly with an `independent` or
`non_member` window. Beyond the authored horizon, `resolveConference`
(`src/membership.ts`) carries the last window forward but marks the result
`extrapolated`, a labeled guess that travels all the way to the report cover;
the concept page traces that flag hop by hop.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): collect a conference-sharded season unit.
- [Audit the data](../../guides/audit-the-data/): run the independent conference derivation against the stored flags.

**Understand it**

- [Season is a dimension](../../concepts/season-and-membership/): the concept page, including the end-to-end extrapolation trace.
- [Absence is data](../../concepts/absence-is-data/): the posture the gap rule applies to time.
