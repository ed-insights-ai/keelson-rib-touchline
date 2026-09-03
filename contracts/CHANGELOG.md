# Contract changelog

One line per change to a published contract, newest first. A fixture change
without a line here is incomplete; a writer change without a fixture change
fails `pipeline/tests/test_contracts.py`.

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
