---
title: Season is a dimension
description: Conference membership as dated, cited windows; extrapolation carried as a labeled flag; and why a January match belongs to last fall's season.
sidebar:
  order: 10
---

In Touchline, season is an axis of every fact, and conference is a value that varies along it. A school does not have a conference the way it has a name. A programme holds **membership windows**: dated intervals of `{conference, from_season, to_season, source}`, authored by hand and validated by contract. The law behind the modeling is short: conference is configuration, never identity. `pipeline/CLAUDE.md` states it as a component rule, and the header of `src/membership.ts` draws the consequence: conference membership is data, not code, and nothing in the rib may hardcode a member list.

## Windows, citations, and authored absence

The artifact is `data/reference/membership.json`. The pipeline reads it through `pipeline/src/membership.py`, whose `conference_for` is an interval lookup: give it a slug, a gender, and a season year, and it returns the conference whose window covers that year, or nothing. The rib reads the same authored windows through `src/membership.ts`. Neither side owns the answer; both defer to the document.

The document earns that trust by surviving `validate` in `pipeline/src/membership.py`, run by the `pipeline/scripts/check_membership.py` CLI:

- every window carries a non-empty `source` citation, because membership is a claim about the world, and claims cite;
- the declared conference list must include the structural codes `independent` and `non_member`;
- a programme's authored seasons may have no gaps; the validator's own error says to "cover them explicitly with an independent or non_member window";
- windows may not overlap, and every configured programme must be covered.

The gap rule is [Absence is data](../absence-is-data/) applied to time. A season nobody wrote down is not "unknown, assume the current conference"; it is a validation failure until someone authors what was true, even when what was true is independence.

## Every conference has a horizon

Membership is authored through some last season, and that horizon belongs to each conference separately. `resolveConference` in `src/membership.ts` computes `authoredThrough` scoped to the conference and gender being asked about. The comment beside it preserves the bug this prevents: a global maximum would read one conference's authoring horizon off another's, so adding a second conference authored one season further would make the first resolve to nothing for that season. Adding a conference must never break the conference already there.

Ask for a season past the horizon and the resolver does not return an empty list, because an empty list reads as "this conference does not exist", and the season that has not started yet is the first thing a new user asks for. Instead it carries each programme's last window forward and sets `extrapolated: true`, with `authoredThrough` naming the season the answer actually rests on. In the resolver's own words, a carried-forward roster is a well-founded guess, not a cited fact, and the caller must surface it.

## Extrapolation travels as a label

The flag is never laundered into fact at any hop. Trace it end to end:

1. The `touchline_collect` tool in `src/tools.ts` prints the note ("the membership record is authored through" a named season) and passes `--membership-extrapolated` to the collector. The `touchline-collect` workflow carries the same fact as its `membership_extrapolated` input.
2. `pipeline/scripts/collect_board.py` stamps `membership_extrapolated` into the `touchline.fixtures/2` payload it writes.
3. `build_digest` in `pipeline/src/digest.py` copies the flag from the season's fixtures into the `touchline.digest/1` output.
4. `pipeline/src/report.py` renders a cover caveat when the digest carries it: membership for this season is carried forward from the last authored year and not yet confirmed.
5. The season board in `src/board.ts` shows the matching notice, "Membership carried forward", whenever the fixtures file's `membership_extrapolated` is set; the field is declared in `fixturesFileSchema` in `src/model.ts`.

Five surfaces, one flag name, and no hop where uncertainty quietly becomes certainty. This is Touchline's general posture toward the unconfirmed: not suppressed, not hedged into vagueness, but labeled and carried.

## A season is not a calendar year

A fall season can finish in the following spring, so "the 2020 season" and "calendar year 2020" are different claims. The schedule pages the collector reads render dates with no year at all, and `_dom_date` in `pipeline/src/sidearm_live.py` resolves them with a domain rule: months from January through June belong to the calendar year after the season's. Its docstring names the case that proves the rule: the COVID 2020 season was played into spring 2021, and those spring matches are correctly season 2020.

The integrity checks hold the same law from the other side. The `season-label` check in `workflows/data-integrity.yml` flags any programme-season whose game dates fall outside the season year and the year after it, and the duplication check uses the same two-year predicate when counting phantom rows, with a comment warning not to "simplify" it back to exact-year equality: that simplification condemns every legitimate spring match of a COVID-season programme.

## Season files shard by conference

On disk, a season's fixtures, rosters, stats, and matches live in conference-sharded files: `data/fixtures/{season}-{gender}-{conference}.json` and its siblings. Season and conference are both dimensions, so both are in the filename key.

Homes created before sharding hold legacy unsharded filenames, and `pipeline/scripts/migrate_shard.py` moves them over with the refuse-to-guess manners the rest of the pipeline uses. `plan_migration` preflights every file before anything mutates. The conference comes from the payload itself, from the `--conference` flag, or from the home's fixture shards only when exactly one candidate exists; anything ambiguous raises `MigrationError` and tells you to pass the flag. Fixtures are upgraded from `touchline.fixtures/1` to `touchline.fixtures/2`, stamping the conference into the payload and into each programme entry. Re-running is safe: an identical destination is skipped, a differing one is refused. And the season readers have no legacy-filename fallback, on purpose; a fallback would let an unmigrated home half-work forever.

The season axis reaches the resolution code too. `conference_for` in `pipeline/src/membership.py` answers for a slug, a gender, and a season year, so the same programme resolves to different conferences in different seasons, exactly as the windows author it. The collector's own conference-game flag is a coarser instrument, derived from one configured conference, and a publisher's own marking outranks it whenever the two meet; [the gates page](../gates/) covers how the standing checks report and fail closed.

Lab: [Trace an identity](../../tutorials/trace-an-identity/) makes this page physical: follow one programme from raw team string to canonical slug, then into its membership windows, and watch the season change the answer.

## Related

**Run it**

- [Audit the data](../../guides/audit-the-data/): run the membership check and the conference audit against a real data home.
- [Run a collection](../../guides/run-a-collection/): where an extrapolated member list first surfaces in a run's output.

**Understand it**

- [Identity](../identity/): who a team string names; this page is about when.
- [Conference is configuration](../../design/conference-as-configuration/): the decision record behind the law.
- [Absence is data](../absence-is-data/): the structural codes are that idea, applied to time.
