# Contract changelog

One line per change to a published contract, newest first. A fixture change
without a line here is incomplete; a writer change without a fixture change
fails `pipeline/tests/test_contracts.py`.

## 2026-11-20

- Membership reference: seven NCAA Division I conferences that sponsor
  women's soccer and not men's join `conferences`, each with a
  `conference_profiles` entry at `level` `d1` (`BIG12`, `BIGSKY`, `CUSA`,
  `SEC`, `SOUTHLAND`, `SWAC`, `UAC`; `code_is_word` true on `SOUTHLAND`).
  The fixture carries each with one women's 2026 window copied from the
  packaged file (its first Division I women's windows), so its conference
  list still equals the packaged one; `UAC` (Abilene Christian) exhibits a
  `division` as the United Athletic Conference's 2026 table prints it. No
  shape change: the packaged file gains Division I women's windows for 2026
  (and the 2024-2025 seasons of three movers from Division II), and no men's
  or Division II window, profile or resolver answer changes.
- Membership reference: `MAC` (the Mid-American Conference, which
  sponsored Division I men's soccer through 2022) joins `conferences` with
  a `conference_profiles` entry at `level` `d1` (`names` "Mid-American
  Conference", "Mid-American"). The fixture carries it with one men's window
  copied from the packaged file (Western Michigan, MAC 2022), so its
  conference list still equals the packaged one. No shape change: the
  packaged file's Division I men's windows now reach back to 2022, the ACC's
  2022 windows carry `division` ("Atlantic", "Coastal") as its 2022
  standings print them, and no Division II window or profile changes.

## 2026-11-15

- Membership reference: the 24 NCAA Division I men's soccer conferences
  join `conferences`, each with a `conference_profiles` entry at `level`
  `d1` (`A10`, `AAC`, `ACC`, `AE`, `ASUN`, `B1G`, `BIGEAST`, `BIGSOUTH`,
  `BIGWEST`, `CAA`, `HORIZON`, `IVY`, `MAAC`, `MVC`, `MW`, `NEC`, `OVC`,
  `PAC12`, `PATRIOT`, `SOCON`, `SUMMIT`, `SUNBELT`, `WAC`, `WCC`;
  `code_is_word` true on `HORIZON`, `IVY`, `PATRIOT` and `SUMMIT`). The
  fixture carries each with one men's window copied from the packaged file,
  so its conference list still equals the packaged one; `BIGEAST` (Akron,
  "Midwest Division") and `CAA` (Campbell, "South") exhibit divisions
  spelled as the standings print them. No shape change: the packaged file
  gains Division I windows for 2023-2026 only, and no Division II window,
  profile or resolver answer changes.
- Membership reference: a required top-level `conference_profiles` map,
  keyed by conference code, each entry `{level, names, code_is_word?}`: the
  conference as a record instead of a bare code. `level` is the NCAA level
  it plays at, one of `d1`, `d2`, `d3` (the word is `level` because
  `division` already means a conference's own split on a window). `names`
  is the non-empty list of long names the conference is printed under in
  schedule headers ("Great American Conference", "Great American"), which
  the schedule parser reads a tournament header by where the header carries
  neither the word "conference" nor the code; the table of Division II
  names that lived in `pipeline/src/sidearm_live.py` is now these entries,
  every alternative kept. `code_is_word`, optional and false when absent,
  says the code is an ordinary English word, so the code alone never names
  the conference in a header. `conferences` and the map are one set: every
  declared conference except the structural `independent` and `non_member`
  carries a profile, and a profile for an undeclared or structural code is
  refused, by `validate` in `pipeline/src/membership.py` and by the rib's
  `membershipFileSchema`. The packaged file and the fixture carry the 21
  collected conferences, all `d2`; the fixture exhibits `code_is_word` once
  (`false`, on `CACC`). `conference_level` and `conferences_at_level`
  (Python), `conferenceLevel` and `activeConferences(gender, level)`
  (TypeScript) and `bin/resolve-membership.ts conferences <gender> --level
  <d1|d2|d3>` expose the level; the un-flagged `conferences <gender>` line
  is unchanged. Same untagged reference. No season file's shape changes:
  measured over all 2,313 archived schedule pages of the Division II data
  home, every one of the 1,110 (header, conference) classifications and
  every parsed fixture is identical before and after.
- `touchline.coverage/1`: `collector` gains the value `wmt-live`, written on
  every cell of a programme whose stanza names `live_scraper = "wmt"` (WMT
  Digital athletics sites). Same schema version: the site's `coverage.ts`
  reads `collector` as a free string. The fixture exhibits it on Seattle U's
  2025 stats cell. The WMT recipe writes the existing fixture, roster, stats
  and match shapes unchanged.

## 2026-11-08

- Membership reference: `NSIC` joins `conferences`, with one window
  (Minnesota State, women, 2026) so the fixture exhibits it; the fixture's
  conference list must equal the packaged file's. NSIC is the first code with
  no men's window.
- `touchline.fixtures/2`: a fixture may carry `stage`, where in the season the
  match sits, as its schedule page groups it. `stage.phase` is `regular`,
  `postseason` or `unknown`; a postseason stage carries `competition`
  (`conference` or `ncaa`) and `source`, the tournament block's header as
  printed ("NCAA Division II Championship", "2025 GAC Men's Soccer
  Tournament"), and may carry `round_published`, the row's own round label
  verbatim ("GAC Championship Game", "First Round"). `regular` is stamped only
  on a page that marks a postseason block, and only before that page's first
  postseason date; another body's postseason ("NCCAA National
  Championships") is `unknown` with its `source`. A row with no `stage` says
  nothing about phase, and the site reads it as unknown, never as regular.
  A fixture may also carry `result_published`, the result cell verbatim, on a
  level score that prints a shootout, and `shootout: {winner, home, away}`
  when the cell names the winner by a letter or by one of the two sides'
  names. Never from digit order: anderson 2025 prints the winner's count
  first, lincoln-memorial 2025 its own ("T, 0-0 , 2-3 Penalty Kicks", which
  carries `result_published` and no `shootout`). The scores stay the drawn
  ones; a shootout is a draw in every record. Same schema version: optional
  fields the site's `model.ts` reads as optional, the same widening as
  `forfeit`. The fixture exhibits every phase, both competitions, a shootout,
  and a printed shootout with no winner.

## 2026-09-07

- `touchline.matches/2` (was `/1`): every player and keeper line on both
  sides carries `player_ref: {id, source}`, who the line is, resolved from
  the season's own files, with `source` one of `page` (the page's own bio
  link; `id` equals `player_id`), `twin` (the opponent's own box score of
  the same match), `roster` (the programme's season roster) or `key`
  (unresolved; a synthetic `<slug>:<folded name>:<number>`). `player_id`
  keeps its meaning, the id as printed on the page, absent when the page
  printed none. The rules run in that order, stop at the first hit, and
  never guess a spelling (exact folded name, or shirt number and surname,
  each unique). Reason: a SideArm box links bios for the owner's roster
  only, so `player_id` was absent on 95% of opponent lines and no
  opponent line could be joined to the same player anywhere else (bead
  tl-y8q). The rib's `matchesFileSchema` admits `/1` and `/2` until the
  backfill rewrites every season; the writer emits `/2` only. New check
  `check-player-identity` (data-integrity node `player-identity`) reports
  coverage by route per file and every twin/roster disagreement.

## 2026-09-05

- Membership reference: `CCAA`, `PACWEST` and `GNAC` join `conferences`,
  with one window each (Cal Poly Pomona, CCAA 2022-2026; Biola, PacWest
  2022-2026; Seattle Pacific, GNAC 2022-2026) so the fixture exhibits them
  (batch 5 membership PR; the fixture's conference list must equal the
  packaged file's). The packaged file carries 37 new windows on 35 new
  slugs: Fresno Pacific (PacWest 2022-2025, then CCAA 2026) and Menlo
  (PacWest 2024-2025, then CCAA 2026) each carry two, the Young Harris
  shape across two conferences of the same batch. `standings_archives`
  gains `GNAC` (ids 44, 45, 46, 96 and 127 for 2021-2025; the live 2026
  table carries no id), the GNAC publishing no records table before 2024,
  and every GNAC window's `source` names that archive. No row shape
  changes: the programmes reference's Simon Fraser row carries a point
  read from the stanza rather than the Gazetteer, its point provenance
  citing `point_source` with a note and no GEOID, which
  `touchline.programmes/2` already admits (geoid optional).

## 2026-09-05 (batch 4)

- Membership reference: `SAC`, `CC` and `PBC` join `conferences`, with one
  window each (Wingate, SAC 2022-2026; North Greenville, whose three CC
  windows carry the first packaged `division` strings, `Southwest` 2023
  then `Northwest` 2024-2026 after an undivided 2022; Lander, PBC
  2022-2026) so the fixture exhibits them (batch 4 membership PR; the
  fixture's conference list must equal the packaged file's). The packaged
  file carries 48 new windows on 33 new slugs plus a second window on
  `shorter` (GSC 2016-2023, then CC 2024-2026 Southwest) and a Peach Belt
  2022 window before Young Harris's CC 2023-2026 Southwest window, the
  Trevecca shape across two conferences of the same batch. Every SAC
  window's `source` names the `standings_archives.SAC` page for its
  seasons, the SAC having no records pages. The synthetic
  `contract-example-divisional` slug stays until a later cleanup.

## 2026-09-04

- Membership reference: a window may carry `division`, a string spelled
  exactly as the conference prints it ("East", "Northwest", "Southwest"
  for Conference Carolinas from 2023), the conference's own grouping of
  its members. Optional; absent for every conference that publishes one
  table. A division change splits the window with the conference
  unchanged (North Greenville: Southwest 2023, then Northwest from 2024;
  the Trevecca shape on one slug), and `check-membership` holds each
  conference-season to all-or-none: every member's window carries a
  division or none does, a mix being refused naming the conference-season
  and the odd members. `conference_for`'s sibling `division_for`,
  `members_of`'s sibling `divisions_of`, the TypeScript `resolveConference`
  (`divisions`, by slug) and `bin/resolve-membership.ts divisions` expose
  it. Same untagged reference; the site's `membership.ts` reads it as an
  optional string. The fixture exhibits a synthetic split (called out in
  the README); no packaged window carries one until the batch 4 CC windows
  land (bead tl-4sg.40, coordinator's ruling 2026-09-04).

- `touchline.fixtures/2`: a `programmes[]` entry may carry `division`
  beside `conference`, the string the programme's membership window names
  for the season, so the site can group a standings table by division when
  every programme of the conference-season carries one. Absent otherwise;
  never read off a stanza. Same schema version: an optional field the
  site's `model.ts` reads as an optional string, the same widening as
  `abbr` (bead tl-4sg.40).

- Membership reference: an optional top-level `standings_archives` map,
  keyed by conference code, each entry `{url_template, seasons}`: the
  archived standings page a conference with no per-season records pages
  keeps its member lists in (`url_template` carries `{id}`, `seasons` maps
  each four-digit season to that page's id). Evidence for the `source`
  sentences and for `check-membership --standings <captured html>
  --conference <code> --season <year>`, which reads a captured page back
  against the windows; the resolver never reads it. The fixture and the
  packaged file carry the one real entry, the SAC (thesac.com answers "no
  statistics available" for every year 2021-2026; ids 72-75, 178 and 191
  per the batch 4 research; bead tl-4an.29). Same untagged reference; the
  site's `membership.ts` reads the map as optional.

- `touchline.fixtures/2`: a fixture may carry `forfeit`, `"home"` or
  `"away"`, the side a forfeited match was awarded to, set only when the
  schedule row itself says forfeit ("Win by forfeit", "Loss by forfeit",
  "forfeited"). Status stays `final`; the scores are the printed ones when
  the host prints them (upper-iowa 2024, game 9017: "W, 2-2" beside "Win by
  forfeit", stored 2-2 with `forfeit: "home"`), else the sport's 1-0
  convention to the awarded side. The collector stops refusing such rows
  (beads tl-wyv, closing tl-49e; owner's ruling 2026-09-04). Same schema
  version: an optional field the site's `model.ts` reads as an optional
  enum, the same widening as `neutral`. The fixture exhibits both values.

- Membership reference: `GLIAC` joins `conferences`, with one window
  (Purdue Northwest, 2022-2026) so the fixture exhibits it (batch 3
  membership PR; the fixture's conference list must equal the packaged
  file's). The packaged file carries eight GLIAC windows on seven new slugs
  plus a second window on `upper-iowa` (GLIAC 2022 before its GLVC
  2023-2026), the Trevecca shape.

## 2026-09-03

- `touchline.coverage/1`: cells gain an optional `skips` array of strings,
  one line per row the collector read and deliberately did not mint
  (`hosted other-match skipped: {date}, {A} v {B}`: a tournament match the
  programme hosted but did not play, listed on its own schedule page; beads
  tl-clk.10, tl-5ru, tl-v1q.14). A sibling of `reason` on a cell whose
  `state` is unchanged by it. Same schema version; the site's
  `coverage.ts` reads it as an optional string array. The fixture exhibits
  it on one complete schedule cell.
- Membership reference: `PSAC`, `MEC` and `G-MAC` join `conferences`, with
  one window each (Bloomsburg, Charleston and Ashland, 2022-2026) so the
  fixture exhibits them (batch 2 membership PR; the fixture's conference
  list must equal the packaged file's). `G-MAC` is the first conference
  code with a hyphen: `programme_slug` mints `g-mac`, so its season files
  are `{season}-{gender}-g-mac.json`.

## 2026-09-02

- Membership reference: `NE10`, `CACC` and `ECC` join `conferences`, with
  one window each (Adelphi, Caldwell and Molloy, 2022-2026) so the fixture
  exhibits them (batch 1 membership PR; the fixture's conference list must
  equal the packaged file's).
- `touchline.coverage/1`: `collector` gains the value `presto-live`, written
  on every cell of a programme whose stanza names `live_scraper =
  "prestosports"`; SideArm programmes keep `sidearm-live` (bead tl-v1q.5,
  PR 3, owner's ruling 2026-09-02 that the coverage contract names the
  PrestoSports collector rather than filing its cells under sidearm-live).
  Same schema version: the site's `coverage.ts` reads `collector` as a
  free string. The fixture exhibits it on Tampa's 2025 stats and matches
  cells.
- `touchline.programmes/2`: first published fixture for the programmes
  reference (bead tl-891). One row per programme slug — `name`, `nickname`,
  `abbreviation`, `city` (AP state style), `point` — each fact with a
  `provenance` entry (`source`, `accessed`, optional `url`; the point's also
  `geoid`, `name`, `state`, optional `note`). Built by `uv run
  build-programmes` from `pipeline/config/schools.toml` (new `city`,
  `city_source`, `identity_accessed`, `gazetteer_geoid`) and the pinned
  U.S. Census Bureau 2023 Gazetteer Files (Places, national),
  https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_place_national.zip,
  server Last-Modified 2023-09-26; the rows it resolved to are the offline
  fixture `pipeline/data/gazetteer/2023_Gaz_place_trimmed.txt`. A Gazetteer
  refresh is a contract bump recorded here, never a build-time drift.
  Version 1 was the site's local `programmes.json` (nickname, city, no
  provenance) and `programme-coordinates.json`, which this replaces.
- Membership reference: `SSC` joins `conferences`, with one window (Rollins,
  2022-2026) so the fixture exhibits it (bead tl-v1q.1).
- Membership reference: `RMAC` joins `conferences`, with one window (Regis,
  2022-2026) so the fixture exhibits it. The fixture's conference list must
  equal the packaged file's, so every conference add touches this file
  (bead tl-clk.1).
- `touchline.fixtures/2`: a fixture may carry `neutral: true`, set when the
  schedule page itself marks a neutral site (the theme's
  `sidearm-schedule-neutral-game` row class, or `location_indicator: "N"` in
  the events payload). Home and away stay as published; the flag gives the
  site's neutral fold a first-hand source in place of twin disagreement
  (bead tl-4sg.25). Restamped from goriverhawksgo.com 2022 game 12745.
- `touchline.coverage/1`: cells may carry `verified: "unchanged"`, the
  conditional fetch's marker for a page reused rather than re-parsed (rib
  7a2f481). The first re-collect to write it (GLVC, 2026-09-02) was refused by
  the site's strict schema; the fixture now promises the value.
- All contracts: first published fixtures for `touchline.coverage/1`,
  `touchline.fixtures/2`, `touchline.rosters/1`, `touchline.stats/1`,
  `touchline.matches/1`, and the membership reference (beads tl-e26,
  tl-4sg.24).
