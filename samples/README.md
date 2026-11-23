# Sample data homes

Two small, real data homes cut from the private Division I and II datasets, so
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

- `data/{fixtures,rosters,stats,matches}/2026-{men,women}-{conf}.json`,
  byte-identical to the real home's files.
- `data/coverage.json`, only the 2026 cells for the conference's members.
- `data/reference/programmes.json`, only the programmes those fixtures name
  (members and opponents).
- `data/reference/membership.json`, only the members, and for each only the
  window covering 2026 (the latest authored one, which the collector carries
  forward).

Nothing else comes across: no other season, no other conference, no raw HTML,
errors, research or reports. The full homes hold every season from 2016 to 2026
across 19 to 31 conferences per division and gender; the sample is one
conference of one season per division, about 21 MB, and it is the same season
the public site already renders for those conferences.

## Re-cutting

After a collect, from `pipeline/`:

```bash
python3 -I scripts/cut_sample.py --home ~/keelson/d2-soccer --conference gac --out ../samples/d2-soccer
python3 -I scripts/cut_sample.py --home ~/keelson/d1-soccer --conference a10 --out ../samples/d1-soccer
```

The script only reads the source home. Never hand-edit a sample; re-cut it.

## Building the site from it

touchline-ui narrows a build to the sample's conference when the home it reads
has a `data/sample.json` (a full home has none, so every configured conference
stays required there):

```bash
TOUCHLINE_DATA_DIR=<this repo>/samples/d2-soccer bun run build
TOUCHLINE_NCAA_DIVISION=d1 TOUCHLINE_DATA_DIR=<this repo>/samples/d1-soccer bun run build
```

These homes move to the public `touchline-contracts` repo, beside the contract
fixtures in `contracts/`, once that repo exists.
