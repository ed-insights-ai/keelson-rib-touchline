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
| `matches-2.json` | `touchline.matches/2` | `pipeline/scripts/collect_board.py` |
| `membership.json` | untagged membership reference | authored at `data/reference/membership.json` |
| `programmes-2.json` | `touchline.programmes/2` | built at `data/reference/programmes.json` by `pipeline/scripts/build_programmes.py` |
| `fixtures-2-women.json`, `rosters-1-women.json`, `stats-1-women.json`, `matches-2-women.json` | the four season schemas above | companions: see below |

A season file names one `gender` at its root, so one document can promise
only one of the two values the writer emits. Each season schema therefore
has a women's companion, cut from GAC women 2026 in the D2 home and trimmed
to a couple of rows; the contract is the union of the fixture and its
companion (`Contract.companions` in `pipeline/src/contracts.py`).

## Where readers get them

This folder and `samples/` are copied to the private
`ed-insights-ai/touchline-contracts` repo on every merge to main
(`.github/workflows/publish-contracts.yml`). The site and the desk read that
copy; change the fixtures here, never there.

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
uv run check-contracts ~/keelson/d2-soccer ~/keelson/d1-soccer
# or, as a test:
TOUCHLINE_CONTRACT_DATA_DIR=~/keelson/d2-soccer uv run pytest tests/test_contracts.py
```

Every season file, the coverage manifest and both reference files
(`data/reference/programmes.json`, `data/reference/membership.json`) under
that root must stay within the samples. Run it before shipping a fixture
change, against the longest history you have. It also runs:

- in the daily cadence (`bin/touchline-collect-cadence.sh`, step 2b), over
  the whole data home after the collects and before the publish. Drift is
  logged by fact, recorded as `contracts` in the run record, and fails the
  run; it does not hold back the publish, because the site's strict schemas
  already refuse anything they cannot read at build time.
- in CI, over every sample data home under `samples/`.

Any publish job built later (the cloud pipeline) should run
`uv run check-contracts <home>` the same way, before it uploads anything.

## Real rows added 2026-11-23

`matches-2.json` gained two real box scores, trimmed to two player lines a
side and a few plays, for shapes the D1 and D2 homes carried that the
fixture did not:

- `sidearm:slippery-rock:12568` (PSAC men 2026): team `offsides` counts,
  and a keeper resolved through the season roster (`player_ref.source:
  "roster"` on a keeper line, not only on an outfield one).
- `sidearm:barton:5414` (Conference Carolinas men 2023 final): a shootout
  the page sectioned as period `"5"` after two overtimes. The period is the
  page's own token, so a shootout is not always `"SO"`; a reader that wants
  shootouts should go by the play's `type: "shootout"`.

## Two values no collect has produced yet

The fixtures promise what the writer *can* emit, not only what it has:

- `fixtures-2.json` carries a `status: "live"` row. The schedule parser
  emits it between kickoff and the final whistle; the cadence has not yet
  caught one.
- `matches-2.json` carries a card of `type: "unknown"`. The box-score parser
  emits it when the phrasing names neither colour.
- `matches-2.json` carries every `player_ref.source` (`page`, `twin`,
  `roster`, `key`) across its lines; the `twin`, `roster` and `key` refs are
  restamped onto the 2016 rows, whose page linked no bio for those players.
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

- `membership.json` carries `"code_is_word": false` on the `CACC` profile,
  the one place the optional flag appears: no packaged profile needs it,
  because no collected conference's code is an ordinary English word. Every
  `level` is `d2` for the same reason the conference list is what it is:
  the fixture's conferences must equal the packaged file's, a profile for
  an undeclared code is refused, and no Division I or III conference is
  declared yet. `d1` and `d3` join the fixture with the first conference
  authored at that level.

## Names are invented

Every person's name in the season samples is made up (CHANGELOG, 2026-11-23):
each real name part was swapped for an invented one with the same first
letter and letter case, consistently across files, so the shapes are the
collector's own. A row cut into a fixture later gets the same treatment by
hand before it lands: invent its names, keep its punctuation.

All were restamped from real rows and are called out here so nobody goes
looking for the page they came from.
