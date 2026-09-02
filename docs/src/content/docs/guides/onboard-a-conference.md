---
title: Onboard a conference
description: "Add a whole conference the way the LSC, GSC, GLVC, RMAC and SSC were added: cited membership windows, probed school recipes, one collect per conference-season, and the verification that proves the neighbours are untouched."
sidebar:
  order: 10
---

A conference is configuration, not code
([Conference is configuration](../../design/conference-as-configuration/)).
Adding one is therefore a data change in the rib, a restart, a run of
collects, and a verification pass. This guide is the sequence as it actually
ran for the Lone Star (2026-08-12), Gulf South (2026-08-20), Great Lakes
Valley (2026-09-01), Rocky Mountain (2026-09-02) and Sunshine State
(2026-09-02) conferences, corrected where reality disagreed with the plan.
The last two were the first adds run entirely from this page, and their
ledgers in section 8 record where the page was wrong. Every step names the
workflow, tool or `bd` command that performs it; nothing here is
hand-collected.

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

Take the athletics hosts from the conference site's members page
(`https://{conference-host}/members` on SideArm conference sites links
every athletics site directly) rather than guessing them from the school's
name. A guessed host that does not resolve costs a re-probe; a guessed host
that resolves to the wrong site costs more (`gohardrockers.com` was the
guess for South Dakota Mines, `gorockers.com` is the host; bead tl-clk.8).
The live standings page prints school names as plain text, not links, so
the per-school statistics links come from a finished season's page.

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
contain every word of the name. Each stanza arrives in the house layout.

The draft is a starting point, not yet a paste (measured on the RMAC and
SSC probes, bead tl-clk.7). Expect to correct, per stanza: an
`abbreviation` minted as initials (AS, CM, FL, R, W, T) where the site's
own short form is wanted; `enabled = false` where the house stanzas carry
`true`; a missing `mascot` when the site's title carries it in a place the
probe does not read (CSU Pueblo, MSU Denver, five of the eleven SSC sites);
an alias that is the page title with the mascot still in it; and aliases
printed between conference and gender rather than last. Peer spellings
("CSU-Pueblo", "Colorado Mines", "Westminster University") come from a scan
of the other members' schedule pages, which the probe does not do; add
them by hand now or in the alias round after the first collect.

Expect a guessed hostname or two to fail name resolution (two of fifteen did
for the GLVC); correct them and re-probe rather than trusting a guess. A
site that refuses the probe (Lee, GSC, answers 403 to every request; Tampa,
SSC, did on 2026-09-02) comes back with what HTTP said on every line: the
platform line reads `unknown` with the status and the URL, every layer reads
`error (HTTP 403)`, the candidate seasons are listed as not seen with their
status, and a stanza is still drafted (bead tl-v1q.6). Re-probe on another
day before naming the platform by hand: Tampa answered 200 to the pipeline's
own session on the next run, and the probe read PrestoSports off its markup.
A PrestoSports site is probed at its sport landing page
(`https://{host}/sports/msoc`), its seasons are academic-year paths
(`/sports/msoc/2025-26/schedule` is the 2025 season), and its stanza sets
`scraper` and `live_scraper` to `"prestosports"`, which collects the
schedule and roster layers today; stats and box scores file `no-collector`
until PR 3 of bead tl-v1q.5, so such a programme's box scores land only
from the members' pages until then. Record the verdict for every site in
the conference block's header comment: the probe date, the platform, which
layers were present, and which seasons were served.

## 3. Author the data, verify it reproduces the count, open a PR

Four files change and nothing else should (measured on the RMAC and SSC
adds, 2026-09-02, beads tl-clk.5 and tl-891):

1. `data/reference/membership.json`: the conference joins `conferences`;
   one window per programme, `source` written as URL + accessed date + the
   sentence that proves the window (see the GSC entries for the shape).
2. `pipeline/config/schools.toml`: one stanza per programme, pasted from
   the probe and checked against the site: `name` as passed to `--name`,
   `aliases` covering the opponent spellings the member schools actually
   publish, `years` equal to the window, `data_status = "unverified"`, and
   `city` as the schedule page prints the home town (the probe drafts it;
   `enabled = true` once pasted).
3. `data/reference/programmes.json`: not edited but rebuilt. Run
   `uv run --project pipeline build-programmes`; it resolves every stanza's
   `city` to one 2023 Gazetteer place and writes the row with its
   provenance. A town that resolves to none or to two places stops the
   build naming the slug and the candidates: fix the spelling, or pin the
   place with `gazetteer_geoid = "<GEOID>"` on the stanza. The offline
   Gazetteer fixture under `pipeline/data/gazetteer/` is rewritten by the
   same run.
4. `contracts/membership.json` + `contracts/CHANGELOG.md`: the membership
   fixture's conference list must equal the packaged file's, so the
   conference joins it with one window.

`test/board.test.ts` asserts the shape of `knownConferences()` against the
shipped membership file (its `conferences` minus `independent` and
`non_member`, sorted), so a conference added to the data joins the
collectable set without a test edit. If a fifth file must change, that is a
finding for the touchpoint ledger, not a quiet fix. One such finding is
already known: a test that names a real, not-yet-declared conference as its
example of an unknown code fails on the day that conference ships
(`test_membership.py` did this with RMAC; it now uses a code no conference
will carry, bead tl-clk.6). Never name the next conference in a test.

Verify before the PR:

```bash
bun test && bun run typecheck && bun run check
uv run --project pipeline pytest -q
uv run --project pipeline check-membership
uv run --project pipeline build-programmes --check
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

Read a backfill's terminal status with care. Its `report` node is a model
call, so a backend error there marks the run `failed` after every collect
slot succeeded and wrote its files (RMAC run 6ee3e4c8; bead tl-clk.9).
Check the per-slot status and the season files, not the run's last word.

Each call reports schedule, roster, stats and matches counts, the duplicate
rows collapsed, and every named gap. The fixture total it prints counts
played and upcoming rows only; cancelled and postponed rows are in the
files but not in the summary, so a shortfall against the total (16 rows in
SSC 2024, a hurricane week) is those statuses, not a gap (bead tl-v1q.7).

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

Three refinements to the alias round, from the fifth and sixth adds:

- **Scan for every followed programme, not only the new members.** The new
  conference's non-conference slate is where other conferences' members
  appear under spellings their own pages never print ("Fort Hays",
  "Texas-Tyler", "Midwestern" on RMAC pages, all collected as strangers;
  bead tl-clk.11). Compare every non-member slug against every enabled
  stanza's name tokens.
- **Run `box-vs-fixture` right after the first collect** and treat its
  UNRESOLVED lines as alias input. Box scores print a second vocabulary of
  abbreviations the schedule pages never show ("Colo. Sch. of Mines"; bead
  tl-clk.12). The check reads stored boxes with the served aliases, so a
  box-only alias needs a restart but no re-collect.
- **Not every stranger is an alias.** Slugs carrying a status word
  (`atlantis-canceled`), a leading "of" where "University of" lost its head
  noun (`of-south-florida`), or a bracket placeholder
  (`sunshine-state-conference-semifinal`, `rmac-semifinal`) are collector
  defects, filed as bead tl-v1q.8, not spellings to alias. Likewise a
  tournament host's schedule page can list a match it hosted but did not
  play, and the collector mints it as the host's own fixture (Westminster
  2023 and 2026; beads tl-clk.10 and tl-5ru). Note the row, leave it, and
  do not alias around it.

## 6. Verify the whole, then commit the data home

Run all four, in any order:

1. **`workflow_run("data-integrity", project="d2-soccer")`**, and count the
   checks. The workflow file has seven (`collect-gaps`, `goal-attribution`,
   `exhibition-markers`, `membership-sync`, `programmes-sync`, `twin-check`,
   `box-vs-fixture`); if the served run shows fewer, Keelson is serving a
   stale catalogue and needs a restart. `membership-sync` and
   `programmes-sync` must be `ok` and say byte-identical.
2. **`touchline_status(project="d2-soccer")`** lists every season of the new
   conference with programme, fixture and roster counts matching step 5.
3. **Scope of the diff** in the data home: `git status --short` shows only
   `*-{conference}.json` under fixtures, rosters, stats, matches and errors,
   `data/coverage.json`, `data/reference/membership.json`,
   `data/reference/programmes.json`, and new
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
epic). Two conferences landing together share one national regeneration.
The cadence script's conference set resolves from the membership record
(`bin/resolve-membership.ts conferences`), so it needs no edit. Since the
rib builds `programmes.json` from the stanzas (step 3) and the site reads
the mirrored copy, the reference rows are no longer hand-kept on the site;
the RMAC and SSC add was the last to write them by hand. The site's own
conference list is not derived from membership today; see the ledger
below.

Expect data-facing tests to trip, and read each failure as a finding: the
map test that wants a point per collected programme, the roster vocabulary
test for strings a new roster publishes, the sources test that catches a
member and a stranger playing the same side on the same day, and any
national fixture that assumed a unique leader. Fix the vocabulary and the
fixtures on the site; file the data defects as rib beads and carry them in
the test's known list under the bead id.

Journal generation runs the conferences side by side under a cap and
reports a failed conference by name without aborting the rest (site PR #9,
beads tl-4an.5 and tl-4an.6). The cadence script still calls the journal
once per changed conference, so it sees no concurrency until it passes the
changed keys in one call (bead tl-4an.10).

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
| `programmes.json`, `programme-coordinates.json` | 30 hand-kept reference rows: nickname, town as published, Gazetteer GEOID and centroid. Since tl-891 the rows are built in the rib from the stanza's `city` and mirrored to the data home; the site reads that file |
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

### 8.1 RMAC, the fifth conference (2026-09-02, epic tl-clk)

The first add run entirely from this page. Eleven programmes, all SideArm,
2022-2026, no churn in the window. Backfill run 6ee3e4c8, re-collected
2022-2025 after the alias round. Data home `fbf1fa9`: 11/11 programmes
every season, 59 gaps, every one a pre-season exhibition with no box link.

**Rib (tl-clk.1, PR #63)**

| touchpoint | change |
|---|---|
| `data/reference/membership.json` | `RMAC` added to `conferences`; 11 windows citing the 2022 statistics page and the live 2026 standings |
| `pipeline/config/schools.toml` | 11 stanzas from the probe, then hand-corrected: six initials abbreviations, two missing mascots, one mascot-laden alias, `enabled` flipped to true, peer-spelling aliases |
| `contracts/membership.json`, `contracts/CHANGELOG.md` | a third and fourth file the page did not name: the fixture's conference list must equal the packaged file's (tl-clk.5, since corrected in step 3) |
| `pipeline/tests/test_membership.py` | a fifth file: the test used RMAC as its example of an undeclared code and failed the day RMAC shipped (tl-clk.6) |
| `test/board.test.ts` | untouched; the shape assertion from the GLVC ledger held |
| production code | none |

**Operations (tl-clk.2)**

| touchpoint | what happened |
|---|---|
| hosts | one guessed host did not resolve (`gohardrockers.com`); the members page had the real one (tl-clk.8) |
| `keelson restart` | after each of the four merges (#63, #64, #65, #66) |
| `workflow_run("touchline-backfill")` | five collect slots succeeded, then the `report` node failed on a model backend 400 and marked the run `failed` (tl-clk.9) |
| alias round, PR #65 | four spellings, only one of them an RMAC member: "S.D. Mines" (RMAC), "Fort Hays" (GAC), "Texas-Tyler" and "The University of Texas at Tyler" (LSC), "Midwestern" (LSC) (tl-clk.11) |
| `box-vs-fixture`, PR #66 | three boxes printing "Colo. Sch. of Mines" resolved no side; one alias, restart, no re-collect (tl-clk.12) |
| Westminster's schedule | a tournament other-match result line minted as a Westminster fixture in 2023 and twice in 2026 (tl-clk.10, tl-5ru) |
| data-integrity | served run showed 6 checks against 7 in the workflow file; `programmes-sync` landed with rib #67 after the collect |
| finished-season `scheduled` rows | four to nine per season: the same exhibitions plus one tournament placeholder; noted, not gaps |

**Site (tl-clk.3, site PR #6 with the SSC, then #7, #8, #9)**

| touchpoint | change |
|---|---|
| `src/site.config.ts` | 2 lines |
| `programmes.json`, `programme-coordinates.json` | 11 hand-kept rows, the last time (rib #67 builds them, site #7 reads the mirror) |
| tests that tripped | geo (rows missing, then Eckerd's point 1.7px offshore of the simplified basemap); roster vocabulary (three strings); sources (four Westminster rows carried as known under tl-5ru); national fixture (a shared top scorer made its claim false) |
| journal | first RMAC journal plus national, batched with the SSC; the generation passed ten minutes with six conferences in sequence and one conference's model error aborted the ones after it (tl-4an.5, tl-4an.6, fixed in site #9) |
| docs | two em dashes in this page tripped `check-docs-drift` on the merge that corrected step 3 (#68) |

**What would make the next add cheaper**, each filed as a bead for the
coding peer:

1. **Probe drafts that paste** (tl-clk.7): the site's abbreviation, not
   initials; `enabled = true`; aliases last; mascot stripped from
   title-derived aliases; mascot read from the title.
2. **Hosts from the members page** (tl-clk.8): now in step 2.
3. **A backfill whose report cannot fail the run** (tl-clk.9): a
   deterministic summary, or a non-fatal prose node.
4. **A fixture read from a schedule page has the owner as one side**
   (tl-clk.10, tl-5ru): otherwise skip or file as a named skip.
5. **Alias scan across every followed programme** (tl-clk.11), and
   **box-vs-fixture UNRESOLVED lines as alias input** (tl-clk.12).
6. **The contract fixture's conference list derived from the packaged
   file** (tl-clk.5), so the add is two data files again.
7. **No test names the next conference** (tl-clk.6).

### 8.2 SSC, the sixth conference (2026-09-02, epic tl-v1q)

The third run from this page, authored and collected the same day as the
RMAC. Eleven programmes, 2022-2026, no churn; ten SideArm sites and one
PrestoSports site (Tampa). Backfill run 499e7bdc. Data home `1a32d89`:
10/11 programmes first-hand every season, 29 box gaps plus 20 Tampa
no-collector gaps. No alias round was needed; every non-member slug was a
stranger or another conference's canonical slug.

**Rib (tl-v1q.1, PR #64)**

| touchpoint | change |
|---|---|
| `data/reference/membership.json` | `SSC` added; 11 windows |
| `pipeline/config/schools.toml` | 11 stanzas: nine initials abbreviations corrected, five mascots added, one mascot-laden alias trimmed, `enabled` flipped; Tampa's stanza names `prestosports` for both scrapers |
| `contracts/membership.json`, `contracts/CHANGELOG.md` | bumped in the same PR, the tl-clk.5 lesson applied |
| tests | none touched |

**Operations (tl-v1q.2)**

| touchpoint | what happened |
|---|---|
| probe | `tampaspartans.com` came back platform unknown, every layer error, no seasons, with a SideArm stanza drafted anyway; a browser showed PrestoSports and the pipeline's user agent gets a 403 (tl-v1q.6, tl-v1q.5) |
| Tampa in the data | its fixtures land only from the ten members' pages, single-source, so no twin can check a Tampa score; roster and stats absent in every season, four no-collector gaps per season |
| collect summary | fixture totals 132/128/139/131 against played+upcoming 121/123/123/130; the difference is exactly the cancelled and postponed rows (hurricane weeks 2022 and 2024), which the summary does not print (tl-v1q.7) |
| opponent slugs | `atlantis-canceled`, `of-south-florida`, `new-of-florida`, `of-mount-olive` beside `mount-olive`, `saint-petersburg-aztecs` beside `saint-pete-aztecs`, 2026 bracket placeholders; strangers and twins the site cannot fold, none of them members (tl-v1q.8) |
| `keelson restart` | shared with the RMAC merges |
| data-integrity | 6 checks served, membership-sync byte-identical, no alarm |

**Site (tl-v1q.3, site PR #6 with the RMAC)**

| touchpoint | change |
|---|---|
| `src/site.config.ts` | 2 lines, in the same commit as the RMAC's |
| reference rows | 11 hand-kept rows; Saint Leo's Gazetteer spelling ("St. Leo town") matched by GEOID with a note on the row |
| Tampa | renders its designed absence state; no test assumed a roster or stats for it |
| journal, national | batched with the RMAC; one national regeneration for both |

**What would make the next add cheaper**, filed for the coding peer:

1. **A PrestoSports collector** (tl-v1q.5), gated before the next batch:
   Westmont, Wilmington and St. Thomas Aquinas are PrestoSports too. The
   403 to non-browser user agents is a second problem for that collector.
2. **The probe names the platform behind a 403** (tl-v1q.6): HTTP status
   per URL and a PrestoSports fingerprint from the `/sports/msoc` URL
   shape, so the stanza is right without a hand fetch.
3. **The collect summary prints cancelled and postponed counts**
   (tl-v1q.7), so the shortfall is named, not inferred.
4. **Opponent slugs without status words, "of" residue or event
   placeholders** (tl-v1q.8).

Between the two ledgers, the rib's two-file add measured on the GLVC held
for the SSC once tl-clk.5 was known; the operations cost is now dominated
by the alias vocabulary and by any site the pipeline cannot read. The
runbook itself absorbed the corrections into steps 2, 3, 5 and 7 above.

**What you just exercised:**
[Conference is configuration](../../design/conference-as-configuration/),
[Season is a dimension](../../concepts/season-and-membership/),
[Absence is data](../../concepts/absence-is-data/).

## Related

- [Onboard a school](../onboard-a-school/): the per-site probe and stanza.
- [Run a collection](../run-a-collection/): one conference-season and its manifest.
- [Audit the data](../audit-the-data/): the data-integrity workflow in detail.
