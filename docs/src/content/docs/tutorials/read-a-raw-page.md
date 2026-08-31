---
title: Read a page the way the parser does
description: Parse a real box-score page naively, watch three template defects flatten away, then follow the production reader, the payload trap, and a named refusal.
sidebar:
  order: 3
---

The naive theory of this system is one line long: a box score is a table,
and pandas reads tables. This lab runs that theory against a page from
your own season, watches it fail three ways, then reads how the production
reader survives. Writes go only to the scratch tier.

By the end you can:

- pull a verbatim copy of a box-score page the collector already proved
- say which facts a flattened table dump cannot carry
- verify three template defects in the collector source
- classify tables by caption and diff against the reader
- spring the payload trap on your archived schedule page, and read a
  named refusal

You need the data home from [Stand up a season](../first-season-board/)
(`{data-home}`, `{season}`), plus `jq` and `uv`.
`{package-dir}` is the installed rib package root.

## 1. Try it: pull the page the collector proved

The live collector archives schedule, roster, and stats pages verbatim
(`write_raw_pages` in `pipeline/src/sidearm_live.py`); a box score lands
parsed in `data/matches/`, stamped with its `source_url`. Fetch a verbatim
copy of one through the collector's own session (`build_session`). Pick a
carded match, so every defect is on your page:

```sh
cd {data-home}
url="$(jq -r '.matches | to_entries[]
  | select(.value.cards and ([.value.teams[].players | length] | min > 0))
  | .value.source_url' data/matches/{season}-men-gac.json | head -n 1)"
mkdir -p data/scratch
BOX_URL="$url" uv run --project {package-dir}/pipeline python -c '
import os
from bs4 import BeautifulSoup
from src.sidearm_live import build_session
html = build_session().get(os.environ["BOX_URL"], timeout=30).text
open("data/scratch/box.html", "w").write(html)
print(BeautifulSoup(html, "lxml").title.get_text(" ").strip())'
```

If it prints nothing, drop the `select` filter.

**Check yourself**: the printed title says "Box Score" and carries an
"on M/D/YYYY" date, the two title proofs `assert_served_match` in
`pipeline/src/sidearm_live.py` demands before parsing; verify with the
command above.

## 2. Try it: parse it naively

The one-liner, every `<table>` flattened to rows of text:

```sh
uv run --project {package-dir}/pipeline python -c '
from bs4 import BeautifulSoup
soup = BeautifulSoup(open("data/scratch/box.html").read(), "lxml")
tables = soup.find_all("table")
print(len(tables), "tables")
for i, t in enumerate(tables):
    rows = t.find_all("tr")
    heads = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")][:8]
    print(i, len(rows), "rows", heads)'
```

It works, and that is the trap: a pile of anonymous shapes. The page knows
which table is which, in `caption` elements the flattening never showed
you; the live reader keys table lookups on that text (`parse_boxscore_page`
in `pipeline/src/sidearm_live.py`):

```sh
uv run --project {package-dir}/pipeline python -c '
import re
from bs4 import BeautifulSoup
soup = BeautifulSoup(open("data/scratch/box.html").read(), "lxml")
for c in soup.find_all("caption"):
    print(re.sub(r"\s+", " ", c.get_text(strip=True)))'
```

**Check yourself**: the captions include `Team Score By Period`,
`Cautions and Ejections`, and one caption per side ending
`- Player Stats` and `- Goalie Statistics`; verify with the command above.

## 3. Try it: verify the three defects in source

Each defect is written down where it is survived:

```sh
grep -n "offsides" {package-dir}/pipeline/src/sidearm_live.py
grep -ni "starters\|substitutes" {package-dir}/pipeline/src/sidearm_live.py
```

**The mislabeled Fouls id.** The template stamps the Fouls stat group with
`id="offsides"`, so a reader keyed by element id silently swaps fouls and
offsides; `_TEAM_STAT_LABELS` in `pipeline/src/sidearm_live.py` keys by
the visible header text instead.

**Card color lives in a CSS class.** Yellow or red is encoded in the class
attribute of the type cell, and a naive table pass flattens cells to text,
so it structurally cannot see the color. The cautions reader in
`parse_boxscore_page` checks the cell's class list for `yellow` or `red`
and stores `unknown` when neither appears.

**The substitutes flip.** Starter versus substitute is never printed on a
player's row; it is carried by a section row. `match_lines` in
`parse_boxscore_page` reads the table as a two-state machine: the
`Starters` header group sets the flag and the `Substitutes` header group
flips it.

**Check yourself**: the stored card types have a closed vocabulary,
because the class attribute is their only source; verify with this
command:

```sh
jq -r '[.matches[].cards // [] | .[].type] | unique[]' \
  data/matches/{season}-men-gac.json
```

Every line is `yellow`, `red`, or `unknown`, the three values
`parse_boxscore_page` can produce.

## 4. Try it: classify by caption, then diff

Classify each table in your caption listing from exercise 2 by hand:
`Team Score By Period` is the name table every reference resolves against,
`Team Statistics` is the label-keyed stat groups, `Scoring Summary` and
`Cautions and Ejections` are event lists, and the captions ending in a
player or goalie suffix are the two sides' rosters. Then run the reader
and compare what it extracted against your verdicts:

```sh
uv run --project {package-dir}/pipeline python -c '
from src.sidearm_live import parse_boxscore_page
d = parse_boxscore_page(open("data/scratch/box.html").read(), page_url="scratch")
print({k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in d.items()})'
```

**Check yourself**: `teams` holds exactly 2 entries, and the scoring,
cards, and plays counts match the rows you can see in the page's own
tables; verify with the command above. A caption the reader does not
know is left unread on purpose: an unknown table is no evidence, and
reading it by position would be a guess.

## 5. Try it: spring the payload trap

Pick any `{programme}` from `ls data/raw_html`. A SideArm page publishes
its schedule twice: rendered markup, and embedded component JSON decoded
from `var obj = {...};` lines by `_component_objects` in
`pipeline/src/sidearm_live.py`. The trap: the payload's `schedule.title`
names the current season at every season URL. Prove it:

```sh
uv run --project {package-dir}/pipeline python -c '
from src.sidearm_live import payload_seasons
html = open("data/raw_html/{programme}/{season}-men-schedule.html").read()
print(sorted(payload_seasons(html)) or "no events payload")'
```

For a completed season this prints the current year, never `{season}`; a
theme may ship no payload, and the markup is the complete source
either way. So past seasons are collected DOM-only, and
`assert_untrapped_schedule` refuses the one dangerous shape: parsed
fixtures sharing event ids with the payload under a past-season URL.

**Check yourself**: the payload never names your completed `{season}`,
yet your schedule cell is proven, because seasons are proven from URL
path and title
(`assert_served_season`), never from the payload; verify with this
command:

```sh
jq -r '.cells["{season}/men/{programme}/schedule"].state' data/coverage.json
```

## 6. Try it: break a page and watch the refusal

When a page defeats the collector, the failure is recorded with a name,
not discarded. Reproduce the defeat on a scratch copy by cutting out the
one table every reference resolves against:

```sh
cp data/scratch/box.html data/scratch/broken.html
uv run --project {package-dir}/pipeline python -c '
from bs4 import BeautifulSoup
from src.sidearm_live import parse_boxscore_page
soup = BeautifulSoup(open("data/scratch/broken.html").read(), "lxml")
for table in soup.find_all("table"):
    caption = table.find("caption")
    if caption is not None and caption.get_text(strip=True) == "Team Score By Period":
        table.decompose()
detail = parse_boxscore_page(str(soup), page_url="scratch")
print(len(detail.get("teams") or []), "team(s) in the score-by-period table")'
```

Zero teams: with the name table gone, no reference on the page can be
resolved. In a real run `collect_match` raises `LiveCollectionError` at
exactly this point, naming the fixture and the count it saw, and the
refusal lands three places rather than none: the matches file's `missing`
map, the coverage cell's `reason`, and the run's
`data/errors/collect-board-{season}-{gender}-{conference}.json` gap
ledger. Because the served bytes were archived first, the failed parse is
debuggable later without re-fetching the page.

**Check yourself**: any box score the collector could not confirm is a
named reason, one line per fixture; verify with this command:

```sh
jq -r '.missing // {} | to_entries[] | "\(.key): \(.value)"' \
  data/matches/{season}-men-gac.json
```

An empty listing means every played fixture carries its box score; each
line that does print names the fixture and why.

## Next stop

Every row you parsed still names its teams with whatever string the site
rendered that week. The next lab follows those strings through
normalization, aliases, and adjudication to canonical identities. Read
[Identity](../../concepts/identity/) on the way. Next stop:
[Trace an identity](../trace-an-identity/).

## Related

**Run it**

- [Rebuild from the archive](../../guides/rebuild-from-the-archive/):
  re-derive the season files from the archived pages, offline where the
  archive allows it.
- [Audit the data](../../guides/audit-the-data/): the standing checks over
  what the collector produced.

**Understand it**

- [Reading hostile HTML](../../concepts/reading-hostile-html/): the theory
  of every defense this lab tripped.
- [Proof before parse](../../concepts/proof-before-parse/): why the season
  and the match are proven before any parser runs.
