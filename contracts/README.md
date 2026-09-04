# Contract fixtures

One sample document per schema this rib publishes across the repo boundary,
each cut from what the collector actually wrote and trimmed to the fewest
rows that still exercise every field, every optional, and every enumerated
value the writer can emit.

| File | Schema | Writer |
|---|---|---|
| `coverage-1.json` | `touchline.coverage/1` | `pipeline/src/coverage.py`, stamped by `pipeline/scripts/collect_board.py` |
| `fixtures-2.json` | `touchline.fixtures/2` | `pipeline/scripts/collect_board.py` |
| `rosters-1.json` | `touchline.rosters/1` | `pipeline/scripts/collect_board.py` |
| `stats-1.json` | `touchline.stats/1` | `pipeline/scripts/collect_board.py` |
| `matches-1.json` | `touchline.matches/1` | `pipeline/scripts/collect_board.py` |
| `membership.json` | untagged membership reference | authored at `data/reference/membership.json` |
| `programmes-2.json` | `touchline.programmes/2` | built at `data/reference/programmes.json` by `pipeline/scripts/build_programmes.py` |

## The rule

A writer may not emit a shape its fixture does not carry. On this side
`pipeline/tests/test_contracts.py` runs a full collect and reduces every
payload to shape facts (field path, JSON kind, and the value where the field
is enumerated); any fact the fixture lacks fails the suite.
`test/contracts.test.ts` proves each fixture parses under the rib's own
strict zod schemas (`src/model.ts`, `src/coverage.ts`, `src/membership.ts`),
which the site vendors.

So a change to a writer lands in three places in one commit: the writer, its
fixture here, and a line in `CHANGELOG.md`. The site's schema tests read these
same files; a fixture that moves without the site's schema moving is the
site's failure to catch, in its CI, before the published build.

## Checking a real data home

```bash
cd pipeline
TOUCHLINE_CONTRACT_DATA_DIR=~/keelson/d2-soccer uv run pytest tests/test_contracts.py
```

Every season file and the coverage manifest under that root must stay within
the fixtures. Run it before shipping a fixture change, against the longest
history you have.

## Two values no collect has produced yet

The fixtures promise what the writer *can* emit, not only what it has:

- `fixtures-2.json` carries a `status: "live"` row. The schedule parser
  emits it between kickoff and the final whistle; the cadence has not yet
  caught one.
- `matches-1.json` carries a card of `type: "unknown"`. The box-score parser
  emits it when the phrasing names neither colour.
- `fixtures-2.json` carries a `forfeit: "away"` row (an optional field
  naming the side a forfeit was awarded to, `home` or `away`; status stays
  `final`). The one archived forfeit, Upper Iowa 2024 game 9017, is the
  `forfeit: "home"` row beside it, scores 2-2 as the host printed them; the
  away row is restamped from a real away win with the 1-0 convention the
  collector writes when the page prints no score.

- `membership.json` carries `contract-example-divisional`, a synthetic
  slug whose two windows exhibit the divisional split (a `division` string
  spelled as the conference prints it; `Southwest` 2023, then `Northwest`
  from 2024, conference unchanged). The shape is Conference Carolinas'
  (North Greenville, batch 4), restamped onto the `SSC` code because the
  fixture's conference list must equal the packaged file's and CC lands
  with its windows. `fixtures-2.json` carries the same `division` on one
  `programmes[]` entry. No packaged window names a division yet.

All were restamped from real rows and are called out here so nobody goes
looking for the page they came from.
