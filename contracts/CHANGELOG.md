# Contract changelog

One line per change to a published contract, newest first. A fixture change
without a line here is incomplete; a writer change without a fixture change
fails `pipeline/tests/test_contracts.py`.

## 2026-09-02

- `touchline.coverage/1`: cells may carry `verified: "unchanged"`, the
  conditional fetch's marker for a page reused rather than re-parsed (rib
  7a2f481). The first re-collect to write it (GLVC, 2026-09-02) was refused by
  the site's strict schema; the fixture now promises the value.
- All contracts: first published fixtures for `touchline.coverage/1`,
  `touchline.fixtures/2`, `touchline.rosters/1`, `touchline.stats/1`,
  `touchline.matches/1`, and the membership reference (beads tl-e26,
  tl-4sg.24).
