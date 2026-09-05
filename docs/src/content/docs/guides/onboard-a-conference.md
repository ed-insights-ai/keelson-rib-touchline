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

A conference site with no records pages (the South Atlantic Conference:
`thesac.com/stats.aspx?path=msoc&year={season}&conf=true` answers "no
statistics available" for every year 2021-2026) keeps its per-season
member list in a standings archive instead, one opaque page id per season
(`https://www.thesac.com/standings.aspx?standings=73` is 2022). Read the
ids off the site's standings index, save them as data, not in a script:
the `standings_archives` block of `data/reference/membership.json`, keyed
by conference code, carries `url_template` (with `{id}`) and the id per
season, and every `source` sentence for that conference names the archived
page the same way a records-page sentence names its `year=`. Capture each
page and reproduce the count offline before authoring the windows:

```bash
uv run --project pipeline check-membership \
  --standings sac-standings-2022.html --conference SAC --season 2022
```

reads the team names off the captured `standings.aspx` page, mints them
the way opponent text is minted (the gender's stanza aliases, then
`programme_slug`), holds them against the members the windows resolve for
that season, and refuses a page served for another season or gender. A
name the windows do not claim, or a window the page does not list, is
printed by slug. The same command reproduces the count for a records-page
conference from a captured `standings.aspx?path=msoc` too; nothing about
those conferences changes.

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
- **Same-named as a programme already in the rib.** The slug `name` mints
  keys every per-programme map (the collect's candidates, coverage cells,
  membership windows, the programmes reference), so two enabled stanzas of
  one gender may not mint the same slug: `load_schools` refuses the pair,
  naming both stanzas, before any collect or build runs. There is no
  separate slug field. Disambiguation lives in the words, the way opponent
  text already mints it (the GAC archive carries `lincoln-memorial` beside
  the GLVC's `lincoln`): give the newcomer a qualified `name` ("Lincoln
  Pennsylvania", say, minting `lincoln-pennsylvania`) and key its
  membership windows by the qualified slug. The programme already in the
  rib keeps its slug; slugs never rename. Identity is the separate check:
  every spelling a stanza claims, `display_name` included, resolves
  opponent text, and a parenthetical is dropped before matching, so the
  newcomer's `display_name` must be a form only it claims ("Lincoln
  University (Pa.)" reduces to a key the incumbent does not hold; "Lincoln
  (Pa.)" reduces to `lincoln` and `check-membership` refuses it). The bare
  "Lincoln" keeps resolving to the incumbent, and peer schedules that print
  only the bare name for the newcomer are the alias round's problem, not
  the loader's.
- **Non-participation is not a membership break.** Spring Hill and West
  Florida are absent from the GSC's 2020 statistics because the conference
  postponed the season; their windows stay continuous and the collect names
  the gap. Only a records page that lists the school in the seasons either
  side and not in the middle is a real lapse, and none has been seen yet.

A programme that changes conference inside the window (Trevecca, G-MAC
2022-2023 then GSC from 2024) gets a second window on the same slug and
keeps ONE stanza in `schools.toml`. The stanza's `conference` is its
current conference and only the default: the collect resolves each
programme's conference per season from the windows, both for the member
set behind the conference-game test and for the `programmes[].conference`
the fixtures file carries, and falls back to the stanza only for a season
no window covers.

A conference that prints its standings in **divisions** (Conference
Carolinas: East, Northwest and Southwest from 2023) puts the division on
each window as an optional `division` string, spelled exactly as the
conference's standings page prints it (source 1), never abbreviated or
normalised. A division change splits the window the way a conference
change does: North Greenville is one window `Southwest` for 2023 and a
second `Northwest` from 2024, same conference, same slug. The rule is
all-or-none per conference-season: for every conference, gender and
season, either every member's window carries a division or none does, and
`check-membership` refuses a mix naming the conference-season and the odd
members. A conference that publishes one table carries no `division`
anywhere. The resolvers carry it through (`division_for` and
`divisions_of` in `pipeline/src/membership.py`, `divisions` on
`resolveConference` in `src/membership.ts`, `bin/resolve-membership.ts
divisions`), and the fixtures file's `programmes[]` entries carry it beside
`conference`, which is how the site groups a standings table without any
per-conference configuration.

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
A PrestoSports URL may be given as `/sports/msoc` or `/sports/msoc/index`
(`wsoc` likewise); the probe treats both as the same landing page and
drafts the bare form. A one-letter abbreviation guess is refused: the
stanza prints `abbreviation = ""` with a comment, the summary lists the
host under "hand edits still needed: abbreviation", and the short form is
set by hand from the conference's own records (batch 4 minted "C" for five
hosts and "L" for Lee).

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
them by hand now or in the alias round after the first collect. Every
spelling a stanza claims (name, `display_name`, `abbreviation`, `aliases`)
must be claimed by one stanza per gender: `check-membership` refuses a
collision naming the pair and the spelling, and a bare initialism two
schools share ("RU", "SCSU") stays display-only on every stanza that
carries it with `abbreviation_resolves = false`.

Expect a guessed hostname or two to fail name resolution (two of fifteen did
for the GLVC); correct them and re-probe rather than trusting a guess. A
site that refuses the probe (Tampa, SSC, did on 2026-09-02) comes back with
what HTTP said on every line: the
platform line reads `unknown` with the status and the URL, every layer reads
`error (HTTP 403)`, the candidate seasons are listed as not seen with their
status, and a stanza is still drafted (bead tl-v1q.6). Re-probe on another
day before naming the platform by hand: Tampa answered 200 to the pipeline's
own session on the next run, and the probe read PrestoSports off its markup.
A 403 on every path for every client on every day is a different signal:
the host is not the athletics site at all. Lee (GSC) showed 403 on every
board 2016-2026 because `leeflames.com` is an Adobe Portfolio fan page; the
real SideArm site is `leeuflames.com`, and the probe read every layer and
season off it on 2026-09-04 (bead tl-rqz). Check the site root in a browser
before filing a WAF gap.
A PrestoSports site is probed at its sport landing page
(`https://{host}/sports/msoc`), its seasons are academic-year paths
(`/sports/msoc/2025-26/schedule` is the 2025 season), and its stanza sets
`scraper` and `live_scraper` to `"prestosports"`, which collects all four
layers (its season statistics from the team page's print template, its box
scores from the pages the schedule links) and files its coverage cells
under the `presto-live` collector. Record the verdict for every site in
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
   place with `gazetteer_geoid = "<GEOID>"` on the stanza. A town the places
   file lacks (New England towns, New Jersey townships, New York towns)
   resolves through the county subdivisions file automatically, and a pin
   may be either file's GEOID. A pinned row must be named for the town in
   the city string, unless the stanza also carries `gazetteer_note`
   saying the printed town is an unincorporated community inside the
   pinned place (University Center, Mich. inside Kochville township): then
   the row keeps the town the school prints as its `city`, takes the
   pinned place's point, and the note lands in the point's provenance.
   A town the Gazetteer covers nowhere (Simon Fraser plays in Burnaby,
   B.C.; the Gazetteer is US-only) takes a `point = { lat, lon }` on the
   stanza with a `point_source` naming where the pair was read, and the
   row's point provenance cites that source with no GEOID. The build
   honours a `point` only when the Gazetteer resolves the city to nothing
   at all and refuses one on a city it does resolve, so a pin can never
   silently override a real place.
   The offline Gazetteer fixtures under
   `pipeline/data/gazetteer/` are rewritten by the same run.
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

A PrestoSports host answers HTTP 202 with an empty body once a season
unit's burst trips its CloudFront challenge (Tampa 2026-09-02; five CACC and
ECC hosts 2026-09-03). The collector paces those hosts itself: 5 seconds
between requests, a 30-second then 90-second retry on a 202, a 10-minute
cool-down when the host keeps challenging, and one retry of every challenged
page after it, all logged as `pacing:` lines. A season unit on a PrestoSports
host therefore takes minutes rather than seconds, and a unit that hit the
cool-down takes ten minutes more; that is the run working, not hanging. Hand
spacing between season units is no longer needed, and a page the run still
names `HTTP 202` after its retry is re-collected alone on a later run.

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
   cancelled fixture, or a tournament placeholder opponent. A row the page
   marks completed or "Final" with no score is stored `scheduled` too,
   since final requires scores, and the collect log names it by fixture id
   (`page reads final with no score`). Note them; they are not collect
   gaps.

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
| ranked rows | the collector strips a leading poll rank or seed in every published form ("#5", "No. 8", "/#5", "(#1 Seed)", "#T-15", "RV") before the opponent slug (tl-cgb); `5-mercy` and `9-adelphi` in the ECC files fold on their re-collect |

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

### 8.3 GLIAC, batch 3 (2026-09-04)

Authored from this page on 2026-09-04; not yet merged or collected, so
this is the rib half of the ledger. Seven programmes, all SideArm, no dead
hosts, no PrestoSports host, 2022-2026 with churn inside the window: the
7/6/7/7/7 count hides two moves (Upper Iowa out after 2022, Roosevelt in
from 2024), and only the per-season lists catch both.

**Rib (batch 3 membership PR)**

| touchpoint | change |
|---|---|
| `data/reference/membership.json` | `GLIAC` added; 8 windows on 7 new slugs plus a second window on the existing `upper-iowa` slug (GLIAC 2022 before GLVC 2023-2026, the Trevecca shape); `description` names gliac.org |
| `pipeline/config/schools.toml` | 7 stanzas from the probe, then hand-corrected: six initials abbreviations, four missing mascots, `enabled` flipped, aliases last, `city_source` on every one; Upper Iowa's existing GLVC stanza gains 2022 in `years` with a comment, no new stanza |
| `data/reference/programmes.json` | rebuilt: 7 new rows, 152 in all; the 145 existing rows unchanged |
| `contracts/membership.json`, `contracts/CHANGELOG.md` | `GLIAC` joins the fixture with one window (Purdue Northwest) |
| tests | none touched |

**Where this page was wrong or silent**

| finding | what happened |
|---|---|
| a name the records never print | the records and standings print "Parkside" in every season; the stanza carries the school's own name "Wisconsin-Parkside" (the data home already held both spellings from opponents' pages) and "Parkside" is an alias, so the membership key is `wisconsin-parkside`, not the records label |
| a records label with punctuation | "St. Cloud State" mints `st-cloud-state`; opponents' pages had minted `saint-cloud-state` in 17 rows, so "Saint Cloud State" is an alias for the alias round |
| a provisional member | Roosevelt was NCAA-provisional for 2024 and 2025 and still counted: a plain row on the 2024 records page and a regular-season co-champion on the 2024 standings (`standings.aspx?standings=307`), so the window starts 2024. The `year=` parameter on `standings.aspx` is ignored; past standings live under an id |
| a mid-window mover already in the rib | Upper Iowa was a men's soccer affiliate on the 2021 and 2022 GLIAC records pages with no gliac.org team page, and is in the GLVC from 2023. Step 1's checklist reads as if a mover were new to the rib; here the slug, stanza and GLVC window existed, so the change is a second window before the first and one `years` entry |
| a town the Gazetteer does not have | Saginaw Valley State plays at "University Center, Mich.", a mailing-address community with no 2023 Gazetteer place in Michigan and no matching county subdivision. Step 3's pin needed the pinned row's name to start with the city string, so a pin to Kochville township (the county subdivision the campus is in) was refused under "University Center". The rule now accepts such a pin when the stanza carries `gazetteer_note` saying why, so the row keeps "University Center, Mich." as its city over the township's point, with the note in the point's provenance (a fifth file, `pipeline/src/gazetteer.py`, plus `config.py` and `programmes.py`, changed for it) |
| a second source for every written fact | the coordinator's rule for this batch: no single-sourced fact lands in a comment, a `source` sentence, a city or a nickname. It cost fourteen paced fetches (conference releases, school main sites, the NCAA directory, the NSIC member JSON, a township site) on top of the records pages, and it caught one claim the research had wrong: Davenport's roster page prints "Grand Rapids, Mich." only as player hometowns, so the city's second source is the gliac.org member JSON, not the roster |
| abbreviations across conferences | RU, DU and SCSU are the gliac.org and school short forms for Roosevelt, Davenport and St. Cloud State, and also Rockhurst's, Drury's and Daemen's, and Southern Connecticut's. `identity_aliases` is one map per gender across every stanza, last stanza wins, so a bare "RU" or "SCSU" on any men's schedule now resolves to the GLIAC programme. The Drury/Daemen pair already had this shape; a per-conference scope for bare initialisms is the fix if it bites |

### 8.4 SAC, Conference Carolinas and the Peach Belt, batch 4 (2026-09-05)

Authored from this page on 2026-09-05; not yet merged or collected, so this
is the rib half of the ledger. Three conferences in one PR, 2022-2026: 33
programmes (SAC 12, Conference Carolinas 14 new beside the GSC's Shorter,
Peach Belt 7 with Young Harris counted once), 48 windows, the first
conference in the region the site is about, the first with divisions, the
first with a dead host inside the depth, and the first where a mover
crosses two conferences of the same batch. Counts 12/12/12/11/11,
12/13/14/15/15 and 7/6/6/7/7 reproduce through the resolver; every other
conference's per-season count is unchanged before and after.

**Rib (batch 4 membership PR)**

| touchpoint | change |
|---|---|
| `data/reference/membership.json` | `SAC`, `CC`, `PBC` added; 48 windows: 12 SAC citing the standings archive by id, 28 CC (every 2022 window undivided, every window from 2023 carrying `division`), 8 PBC; a second window on `shorter` (CC 2024-2026 Southwest) and a PBC 2022 window on `young-harris` before its CC window; `description` names the three authorities |
| `pipeline/config/schools.toml` | 33 stanzas in three sections after the GLIAC: 32 from the probe, hand-corrected (fourteen initials abbreviations, thirteen missing mascots, two mascots read short, `enabled` flipped, aliases last, `city_source` on every one), plus a dead-host stanza for Limestone; Shorter's GSC stanza gains 2024-2026 in `years` with a comment, no new stanza; five PrestoSports stanzas in the Tampa shape |
| `data/reference/programmes.json` | rebuilt: 33 new rows, 185 in all; the 152 existing rows unchanged; no Gazetteer pin needed |
| `contracts/membership.json`, `contracts/CHANGELOG.md` | the three join the fixture with one window each; North Greenville's is the first packaged divisional window |
| `pipeline/tests/test_membership.py` | a fifth file: two tests asserted the pre-batch-4 shipped file (no packaged division anywhere; the SAC archive page reading against no SAC window), and both tripped the day the data landed, the tl-clk.6 lesson again. They now assert the divisional shape and the agreement |

**Where this page was wrong or silent**

| finding | what happened |
|---|---|
| a window with no stanza | the plan wanted Limestone (host dead) as a window only. `check-membership` refuses a window whose slug has no stanza (`unknown institution slug`), so the batch 1 shape stands: an enabled stanza on the dead host, every fetch failing, the absence filed. Step 1's "never sponsored" bullet should say so |
| the standings archive as source 1 | the SAC's twelve windows cite `standings.aspx?standings={id}` for their edge seasons and the live table for 2026; `check-membership --standings` reproduced 12/12/12/11/11 from the captured pages before a line was authored |
| the first divisional conference | the CC 2022 tables print no division and 2023 on print three, so every member in from 2022 has two windows, and North Greenville three (Southwest 2023, Northwest from 2024). `resolve-membership divisions` prints nothing for 2022 and the three names from 2023 |
| PrestoSports hosts that answer 202 | five SAC hosts are PrestoSports. Three answered an empty HTTP 202 to the probe's first burst and read on the 60 s retry; two (Carson-Newman, Tusculum) never read and were settled by a paced curl pass with a browser User-Agent the next day. Carson-Newman keys men's soccer under `m-soccer`, not `msoc`, which the probe refuses (bead tl-7lu). Each such stanza carries a line saying a 202 is the challenge, not a dead host |
| a season the site labels wrongly | Coker's `/sports/msoc/2022-23/schedule` answers a page titled "2023 Men's Soccer Schedule", so the probe proves no 2022 season and `years` starts 2023 while the window starts 2022; the collect will name the gap |
| the town on a PrestoSports site | the probe reads no home town off a PrestoSports schedule page. The five towns came from the schools' own schedule pages (footer address or home rows) with the thesac.com member JSON as the second source; Tusculum's own page prints Greeneville, not the Wikipedia town |
| short forms | the standings pages print no abbreviations. The SideArm root page JSON carries `home_short_name` / `away_short_name` for every scoreboard row, so each abbreviation was read off the school's own scoreboard or a peer's; WU, AU, TU and LMC are other stanzas' and carry `abbreviation_resolves = false`, and Lander carries LAN over LU (Lincoln's) |
| a slug the records would not mint | the Peach Belt prints "USCA" and "Middle Georgia"; opponents' pages had minted `usc-aiken` and `middle-georgia-state`, so the stanzas carry the schools' names and the records labels are aliases |

### 8.5 CCAA, PacWest and GNAC, batch 5 (2026-09-05)

Authored from this page on 2026-09-05; not yet merged or collected, so this
is the rib half of the ledger. Three conferences in one PR, 2022-2026, the
first batch in the west: 35 programmes (CCAA 15, PacWest 15, GNAC 7, with
Fresno Pacific and Menlo counted once), 37 windows, every host SideArm,
one dead host (Holy Names), two movers crossing two conferences of the
same batch (Fresno Pacific and Menlo, PacWest to CCAA for 2026), five
windows ending inside the depth with the host alive (Sonoma State, San
Francisco State, Academy of Art, Montana State Billings after 2024; Azusa
Pacific after 2025), and the first programme outside the United States
(Simon Fraser, placed by a stanza `point`). Counts 12/12/12/11/13,
11/11/14/13/10 and 7/7/7/6/6 reproduce through the resolver; every other
conference's per-season count is unchanged before and after.

**Rib (batch 5 membership PR)**

| touchpoint | change |
|---|---|
| `data/reference/membership.json` | `CCAA`, `PACWEST`, `GNAC` added; 37 windows on 35 new slugs, two each on `fresno-pacific` and `menlo`; `standings_archives.GNAC` (ids 44, 45, 46, 96, 127), the GNAC having no records table before 2024; `description` names the three authorities |
| `pipeline/config/schools.toml` | 35 stanzas in three sections after the PBC: 34 from the probe, hand-corrected (fourteen initials or missing abbreviations, seven missing or short mascots, three misread towns, `enabled` flipped, aliases last, `city_source` on every one), plus a dead-host stanza for Holy Names in the Limestone shape; the CACC's Dominican stanza gains `display_name = "Dominican (N.Y.)"` |
| `data/reference/programmes.json` | rebuilt: 35 new rows, 220 in all; the 185 existing rows unchanged; Simon Fraser's row carries the stanza point with no GEOID |
| `pipeline/src/config.py`, `pipeline/src/programmes.py`, `pipeline/src/gazetteer.py` | a stanza `point` with `point_source`, validated at load (shape, range, source, never beside a GEOID pin) and honoured by the build only where the Gazetteer resolves nothing; `Gazetteer.candidates` is the lookup `resolve` and the build now share |
| `contracts/membership.json`, `contracts/CHANGELOG.md` | the three join the fixture with one window each and the GNAC archive; no row shape changes |
| tests | the point is refused on a Gazetteer-resolvable city and carried for Burnaby; the loader's point validation; the shipped Simon Fraser row. A fifth file: `test/contracts.test.ts` asserted a GEOID on every packaged row and tripped on Simon Fraser's, the tl-clk.6 lesson again; it now accepts the stanza-point note |

**Where this page was wrong or silent**

| finding | what happened |
|---|---|
| a display name the identity check refuses | the ruling wanted `display_name = "Dominican (Calif.)"` on the newcomer; a parenthetical drops before matching, the key `dominican` is the CACC incumbent's name, and `check-membership` refuses the pair, exactly as step 1 warns for "Lincoln (Pa.)". The stanza carries the published name "Dominican University of California" instead, and the same rule drops the aliases "Dominican (Calif.)", "Dominican (CA)" and "Concordia (CA)" (which reduces to the bare polluted "Concordia"). Step 1's other example, "Lincoln University (Pa.)", reduces to `lincoln` too, since "University" is an institution word: a qualified display name must add a word that survives the fold |
| a town outside the Gazetteer | Simon Fraser prints "Burnaby, B.C.", which parses to no US state. Step 3's pin could not help (no GEOID exists), so the stanza `point` above was added, second-sourced to the CGNDB entry and the university's address. The row's city is carried as printed, not AP-normalised |
| a home ground the site names without a town | Hawai'i Pacific's schedule prints the venue only for home matches (Waipio Stadium, in Waipahu by Chaminade's schedule) and Honolulu only for the away match at Chaminade; the member JSON prints Kaneohe. The town used is the university's own address (Honolulu, hpu.edu and the NCAA directory), with the other two in the stanza comment |
| the probe reads the first fixture's venue as the home town | three CCAA drafts carried the away venue of the first 2026 fixture (Dallas, Kansas City twice); the schedule page's home rows and the member JSON settled Hayward (address, since the 2026 home venue is in Alameda), Los Angeles and San Marcos |
| a school site that refuses every fetch | www.sonoma.edu and calstate.edu answer 403 to a browser User-Agent; the NCAA directory (web3.ncaa.org/directory/orgDetail) was the second source for Rohnert Park, Hayward, Honolulu and San Diego |
| a town whose Census row is a CCD | "Honolulu, Hawaii" matched nothing in the places file (the Census carries "Urban Honolulu CDP") and fell through to the county subdivisions, where "Honolulu CCD" spans the whole county to the Northwestern Hawaiian Islands and centres in the open ocean (27.79 N, 175.85 W). The build accepted it without a word, since one row matched. Chaminade and Hawai'i Pacific pin the Urban Honolulu CDP (1571550) with a `gazetteer_note`; read the point of every new row before committing, not only the failures |
| SideArm conference sites answer 404 pages that still embed the member JSON | thepacwest.com/members is a 404 whose body carries the members component; the JSON is read off the standings page instead |

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
