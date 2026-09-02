# Contract changelog

One line per change to a published contract, newest first. A fixture change
without a line here is incomplete; a writer change without a fixture change
fails `pipeline/tests/test_contracts.py`.

## 2026-09-02

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
