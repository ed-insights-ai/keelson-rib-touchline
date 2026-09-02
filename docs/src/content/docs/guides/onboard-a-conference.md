---
title: Onboard a conference
description: "Add a whole conference the way the LSC, GSC and GLVC were added: cited membership windows, probed school recipes, one collect per conference-season, and the verification that proves the neighbours are untouched."
sidebar:
  order: 10
---

A conference is configuration, not code
([Conference is configuration](../../design/conference-as-configuration/)).
Adding one is therefore a data change in the rib, a restart, a run of
collects, and a verification pass. This guide is the sequence as it actually
ran for the Lone Star (2026-08-12), Gulf South (2026-08-20) and Great Lakes
Valley (2026-09-01) conferences, corrected where reality disagreed with the
plan. Every step names the workflow, tool or `bd` command that performs it;
nothing here is hand-collected.

Per-school mechanics (the probe, the drafted stanza, the fields) live in
[Onboard a school](../onboard-a-school/) and are not repeated.

## 0. Record the decision before touching anything

Decide the depth (which seasons) and write it down where the next session
will find it:

```bash
bd remember --key <conf>-onboarding-decisions-<date> "..."
```

Depth is the first realignment tool you have. The LSC and GLVC are authored
2022-2026: five seasons, skipping the COVID-distorted 2020/21 seasons, and
starting after the moves that would otherwise split a school into two
windows. The GSC went back to 2016 because its churn fell inside the window
and the windows record it. Whichever you pick, the epic bead carries the
sequence and each step below is a child bead you `bd update --claim`.

## 1. Enumerate membership from the conference's own records

The source of truth is the conference site's per-season page, one fetch per
season: for SideArm conference sites the shape is
`https://{conference-host}/stats.aspx?path=msoc&year={season}&conf=true`,
with the live season's roster on `standings.aspx?path=msoc` when the
statistics page is still empty. Write down every school named, per season.
That list is the count the rib must reproduce later, so keep it.

Then run the **realignment-trap checklist**. Verify each item against a
records page; never assume it from memory:

- **Left for another division** (Bellarmine, Lindenwood, Southern Indiana
  in the GLVC; UT Tyler arriving from Division III in the LSC). Fetch the
  season before your window opens and confirm they are listed there and
  absent from the first window season.
- **Arrived mid-window** (Upper Iowa 2023 and Lincoln 2024 in the GLVC;
  Saint Edward's, Sul Ross and UT Dallas in the LSC; Montevallo, Spring
  Hill, AUM and Trevecca in the GSC). The window starts at the first season
  the records list them, and the source sentence names the season they are
  absent from.
- **Left mid-window** (Shorter and West Florida in the GSC; ENMU and UTPB in
  the LSC). The window ends at the last season listed, and the source names
  the first absent season.
- **Never sponsored the sport, or discontinued it** (ENMU dropped men's
  soccer December 2024). A school on the conference's member list that never
  appears in the sport's records gets no window at all.
- **Renamed** (Mississippi College became Mississippi Christian 2026-06-01).
  `name` keeps minting the old slug; `display_name` carries the new name.
- **Non-participation is not a membership break.** Spring Hill and West
  Florida are absent from the GSC's 2020 statistics because the conference
  postponed the season; their windows stay continuous and the collect names
  the gap. Only a records page that lists the school in the seasons either
  side and not in the middle is a real lapse, and none has been seen yet.

## 2. Probe every site and record the verdicts

From the rib checkout, one command, every URL:

```bash
uv run --project pipeline probe --conference GLVC --seasons 2022-2026 \
  --url https://{host-1}/sports/mens-soccer --name "{school-1}" \
  --url https://{host-2}/sports/mens-soccer --name "{school-2}" ...
```

`--name` is the slug-minting name, one per `--url` in order, chosen so
`programme_slug(name)` equals the membership key (check the GAC archive for
slugs opponent text already minted). The probe reads the rest off the site:
`abbreviation` from the site's own short form ("UIS", "UMSL"), `mascot`
from the schedule page's description ("Prairie Stars", "Tritons"), and
`aliases` from the published long name and the opponent spellings that
contain every word of the name. Each stanza arrives in the house layout,
ready to paste.

Expect a guessed hostname or two to fail name resolution (two of fifteen did
for the GLVC); correct them and re-probe rather than trusting a guess. A
site that answers 403 to every request (Lee, GSC) gets a stanza whose
comment says so and whose platform is inferred from the URL shape. Record
the verdict for every site in the conference block's header comment: the
probe date, the platform, which layers were present, and which seasons were
served.

## 3. Author the data, verify it reproduces the count, open a PR

Two files change and nothing else should:

1. `data/reference/membership.json`: the conference joins `conferences`;
   one window per programme, `source` written as URL + accessed date + the
   sentence that proves the window (see the GSC entries for the shape).
2. `pipeline/config/schools.toml`: one stanza per programme, pasted from
   the probe and checked against the site: `name` as passed to `--name`,
   `aliases` covering the opponent spellings the member schools actually
   publish, `years` equal to the window, `data_status = "unverified"`.

`test/board.test.ts` asserts the shape of `knownConferences()` against the
shipped membership file (its `conferences` minus `independent` and
`non_member`, sorted), so a conference added to the data joins the
collectable set without a test edit. If a third file must change, that is a
finding for the touchpoint ledger, not a quiet fix.

Verify before the PR:

```bash
bun test && bun run typecheck && bun run check
uv run --project pipeline pytest -q
uv run --project pipeline check-membership
```

and reproduce the per-season count from step 1 through the rib's resolver:

```ts
import { resolveConference } from "./src/membership";
for (const y of [2022, 2023, 2024, 2025, 2026])
  console.log(y, (await resolveConference("GLVC", "men", y)).slugs.length);
```

Every season must equal the published count exactly. A mismatch is a wrong
window, fixed in the data with a citation, never papered over at collect
time. Branch, PR, do not merge from the authoring session.

## 4. Merge, then restart Keelson

A linked rib serves the membership file and workflow catalogue it registered
at startup. After the merge:

```bash
keelson restart
```

`keelson rib reload` is not enough; it re-collects workflow contributions
only. Confirm the served rib sees the conference before collecting: the
first `touchline_collect` call prints the resolved member list, and the
count must match step 1 for that season.

## 5. Collect, one conference-season per call

Use the `touchline_collect` MCP tool, sequentially, one season each:

```
touchline_collect(target="GLVC", gender="men", season=2022, project="d2-soccer")
```

The tool resolves the programme list through the served rib and runs the
collect. `workflow_run("touchline-collect")` with only conference, gender
and season does the same: its `resolve-programmes` node reads the members
from the packaged membership record (the preflight refusal measured on
2026-09-01, run 6708b27d, is gone). For the whole range in one durable run,
`workflow_run("touchline-backfill")` with `from_season` and `to_season`
runs one collect node per season. The first collect into a data home whose
mirror is behind prints `membership reference synced`; that is the mirror
healing, and expected.

Each call reports schedule, roster, stats and matches counts, the duplicate
rows collapsed, and every named gap.

Expect an **alias round** after the first collect. A member's peers spell it
their own way ("Lincoln University of Missouri" for the stanza's "Lincoln"),
and a spelling no alias covers is collected as a stranger beside the member,
so one match appears twice. Scan the new fixture files for non-member slugs
that look like members, read the spelling off a peer's schedule page, add
it to the stanza's `aliases`, and re-collect the affected seasons. A
parenthetical is dropped before matching, so an alias like "Lincoln (Mo.)"
resolves nothing on its own; the alias must be the words that survive
normalisation. Copy the gaps verbatim into the collect
bead's notes as you go; they are also in
`data/errors/collect-board-{season}-{gender}-{conference}.json`. A season
takes about four minutes.

## 6. Verify the whole, then commit the data home

Run all four, in any order:

1. **`workflow_run("data-integrity", project="d2-soccer")`**, and count the
   checks. The workflow file has six (`collect-gaps`, `goal-attribution`,
   `exhibition-markers`, `membership-sync`, `twin-check`, `box-vs-fixture`);
   if the served run shows fewer,
   Keelson is serving a stale catalogue and needs a restart. `membership-sync`
   must be `ok` and say byte-identical.
2. **`touchline_status(project="d2-soccer")`** lists every season of the new
   conference with programme, fixture and roster counts matching step 5.
3. **Scope of the diff** in the data home: `git status --short` shows only
   `*-{conference}.json` under fixtures, rosters, stats, matches and errors,
   `data/coverage.json`, `data/reference/membership.json`, and new
   `data/raw_html/{programme}/` directories. No file of a neighbouring
   conference is modified.
4. **Finished seasons carrying `status: scheduled` rows** are usually
   unpublished-result exhibitions against non-Division II sides, a
   cancelled fixture, or a tournament placeholder opponent. Note them; they
   are not collect gaps.

Then commit and push the data home. It is the durable record and consumer
data, not rib code; its message records the per-season counts and the gap
total (see `chore(data): collect GLVC men 2022-2026` for the shape).

## 7. The site side

The public site is told separately, by the coordinator session that owns
touchline-ui: `src/site.config.ts` gains the conference in `conferences` and
`conferenceNames`, one journal generation for the conference and one
national regeneration are run (model spend, authorised per conference in the
epic). The cadence script's conference set resolves from the membership
record (`bin/resolve-membership.ts conferences`), so it needs no edit. The
site side is not derived from membership today; see the ledger below.

## 8. The touchpoint ledger

What the GLVC, the fourth conference, actually required, measured on
2026-09-01. Restarts, mirror heals, defaults and surprises included.

**Rib (tl-08b.1)**

| touchpoint | change |
|---|---|
| `data/reference/membership.json` | `GLVC` added to `conferences`; 15 windows |
| `pipeline/config/schools.toml` | 15 stanzas, hand-authored (probe drafts mint unusable names: "Gameday", "U", "St. Louis") |
| `test/board.test.ts` | literal `knownConferences` list grows by one |
| production code | none |

**Operations (tl-08b.2)**

| touchpoint | what happened |
|---|---|
| `keelson restart` | required after merge; `rib reload` does not pick up membership |
| data-home membership mirror | self-healed on the first collect ("membership reference synced … was diverged") |
| `workflow_run("touchline-collect")` | refused without caller-resolved `programmes` at the time; the workflow now resolves its own (proposal 1 below) |
| data-integrity check count | 4, matching the workflow file; a remembered "12" was stale |
| `~/.keelson/scripts/touchline-collect-cadence.sh` line 74 | `TOUCHLINE_CONFERENCES` default string had to be extended by hand; the default now resolves from data (proposal 2 below) |
| finished-season `scheduled` rows | unpublished exhibitions, one cancellation, one tournament placeholder; noted, not gaps |

**Site (coordinator, then the site beads under tui-4me)**

| touchpoint | change |
|---|---|
| `touchline-ui/src/site.config.ts` | 2 lines: `conferences` +1, `conferenceNames` +1 |
| journal | one GLVC model call |
| national page | one regeneration |
| `programmes.json`, `programme-coordinates.json` | 30 hand-kept reference rows: nickname, town as published, Gazetteer GEOID and centroid |
| division fold | a neutral-site rule, the first time two followed conferences shared a tournament match with no agreed home side |
| roster vocabulary | six published misspellings aliased, two abbreviations added, two non-positions named, one initials rule |
| copy test | one pairwise threshold, the chart caption marked mechanical |

**The alias round (tl-v7p)**

| touchpoint | what happened |
|---|---|
| `schools.toml` lincoln stanza | one alias, "Lincoln University of Missouri", after six 2026 fixtures collected twice |
| GLVC 2024-2026 | re-collected after merge and restart so the twins fold |
| other conferences' files | keep `missouri-s-and-t`, `uindy`, `of-missouri-saint-louis` until their own re-collect; the stanzas now resolve all three |
| tournament pages | `seed-` and `no-NN-` prefixes reach slugs; collector bug filed (tl-4sg.22) |

**What collapses, with a cost each** (filed as beads under tl-4sg):

1. **The collect workflow resolves its own programmes.** Make `programmes`
   optional and resolve from the packaged membership when empty, so
   `workflow_run` with conference/gender/season works and the tool and the
   workflow share one contract. Cost: medium (one bash node calling the
   pipeline's membership resolver, one test).
2. **Cadence reads its conference set from data.** Replace the default
   string with the conferences that have enabled schools in
   `schools.toml`, so an authored conference joins the daily collect the
   day it merges. Cost: small (a resolver call in the script, one
   `TOUCHLINE_CONFERENCES` override kept for scoping).
3. **The board fixture asserts shape, not a literal.** Assert that
   `knownConferences()` equals the membership file's conferences minus
   `independent` and `non_member`, sorted. Cost: extra small; the trade is
   losing the tripwire that names the shipped list, so keep one snapshot
   test if that tripwire is wanted. Done (tl-4sg.19): the test now reads
   the shipped file and no snapshot was kept.
4. **Probe emits a usable stanza.** Let the probe take `--name` and mint
   `abbreviation`, `mascot` and `aliases` from the site's own title and
   schedule opponent text, so the stanza is pasted, not rewritten. Cost:
   medium. Done (tl-4sg.20): step 2 above is the new shape.
5. **The first collect scans itself for the alias round.** After a collect,
   list non-member slugs whose tokens are a superset of a member's name and
   print them as candidate aliases, so the round above is one report, not a
   test failure on the site three steps later. Cost: small.
6. **A backfill workflow fans a conference out over seasons.** One
   `touchline-backfill` run takes conference, gender and a season range and
   executes one collect node per season under the existing mutation lock,
   turning five tool calls into one durable run. Cost: medium; a single
   node cannot hold five seasons inside the node budget, so it must be one
   node per season.

Not filed here, the site side's own collapse: `site.config.ts` deriving its
conference list and names from the membership file it already ships beside.

**What you just exercised:**
[Conference is configuration](../../design/conference-as-configuration/),
[Season is a dimension](../../concepts/season-and-membership/),
[Absence is data](../../concepts/absence-is-data/).

## Related

- [Onboard a school](../onboard-a-school/): the per-site probe and stanza.
- [Run a collection](../run-a-collection/): one conference-season and its manifest.
- [Audit the data](../audit-the-data/): the data-integrity workflow in detail.
