# Sample data homes

Two small data homes cut from the private Division I and II datasets, so
every public Touchline repo can build and test from a plain clone. Each is laid
out exactly like a full home (`touchline-data.yaml`, `data/...`) and carries a
`data/sample.json` manifest that says it is a sample and lists, with sizes and
SHA-256s, the season files it holds.

| Home | Level | Conference | Season | Genders | Programmes | Fixtures | Box scores |
|---|---|---|---|---|---|---|---|
| `d2-soccer/` | Division II | GAC (Great American Conference) | 2026 | men, women | 7 + 7 | 95 + 90 | 85 + 85 |
| `d1-soccer/` | Division I | A10 (Atlantic 10 Conference) | 2026 | men, women | 13 + 14 | 185 + 201 | 165 + 187 |

GAC and A10 are the conferences the site's Division II and Division I builds
already open on (`site.config` `home`), and `harding` and `saint-louis`, the
programmes its checks sample, are members.

## What each home holds

- `data/{fixtures,rosters,stats,matches}/2026-{men,women}-{conf}.json`, the
  real home's files with every person given an invented name (below).
  Fixtures name no one and stay byte-identical.
- `data/coverage.json`, only the 2026 cells for the conference's members.
- `data/reference/programmes.json`, only the programmes those fixtures name
  (members and opponents).
- `data/reference/membership.json`, only the members, and for each only the
  window covering 2026 (the latest authored one, which the collector carries
  forward).

## Invented people

These homes are public, so nobody in them keeps a real name. The cut runs
`pipeline/scripts/sample_names.py` over the season files: every name token
of every player, keeper, scorer, assister, carded player and match official
is swapped for an invented token, and the swap is applied wherever that token
appears (name fields, play-by-play and goal text, the name slug in roster and
bio URLs, and key-sourced `player_ref` ids, which are re-folded). The map
works on tokens, so "Payton Roehrich", "Roehrich, Payton", "ROEHRICH,PAYTON"
and "P. Roehrich" stay one person. An invented token keeps the real one's
first letter, case, accent and apostrophe, and the map is one-to-one, so
initials, accent folding and joins behave as they did on the real data.

Everything else is as collected: numbers, positions, hometowns, player and
page ids, teams, scores, times and every count. The cut refuses to write a
sample in which any real name token survives in those fields. Tokens of one
or two letters (JJ, Li) and particles and suffixes (de, van, Jr) are kept.

Nothing else comes across: no other season, no other conference, no raw HTML,
errors, research or reports. The full homes hold every season from 2016 to 2026
across 19 to 31 conferences per division and gender; the sample is one
conference of one season per division, about 21 MB, and it is the same season
the public site already renders for those conferences.

## Re-cutting

After a collect, from `pipeline/`:

```bash
uv run python -m scripts.cut_sample --home ~/keelson/d2-soccer --conference gac --out ../samples/d2-soccer
uv run python -m scripts.cut_sample --home ~/keelson/d1-soccer --conference a10 --out ../samples/d1-soccer
```

The script only reads the source home. Never hand-edit a sample; re-cut it.
The desk's `fixtures/oracle/season-files` are copies of `d2-soccer`'s match
and fixture files: re-copy them (and move `snapshot/touchline-desk.sha`) after
a re-cut changes the GAC files.

## Building the site from it

touchline-ui narrows a build to the sample's conference when the home it reads
has a `data/sample.json` (a full home has none, so every configured conference
stays required there):

```bash
TOUCHLINE_DATA_DIR=../touchline-contracts/samples/d2-soccer bun run build
TOUCHLINE_NCAA_DIVISION=d1 TOUCHLINE_DATA_DIR=../touchline-contracts/samples/d1-soccer bun run build
```

## Published copy

This folder and `contracts/` are copied to the private
`ed-insights-ai/touchline-contracts` repo on every merge to main
(`.github/workflows/publish-contracts.yml`). Readers clone that repo; this one
stays the source, so re-cut here and never edit the copy.
