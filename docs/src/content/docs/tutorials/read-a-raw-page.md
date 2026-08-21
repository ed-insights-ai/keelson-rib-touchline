---
title: Read a page the way the parser does
description: Parse a real box-score page naively, watch three template defects flatten away, then follow the production parsers, the payload trap, and a forensics artifact.
sidebar:
  order: 3
---

The naive theory of this system is one line long: a box score is a table,
and pandas reads tables. This lab runs that theory against a page from
your own season, watches it fail three ways, then reads how the production
parsers survive. Writes go only to the scratch tier and your
practice home.

By the end you can:

- pull a verbatim copy of a box-score page the collector already proved
- say which facts a flattened `pd.read_html` table cannot carry
- verify three template defects in the parser sources
- classify tables by column signature and diff against the classifier
- spring the payload trap on your archived schedule page, and read a
  parse-forensics artifact

You need the data home from [Stand up a season](../first-season-board/)
(`{data-home}`, `{practice-dir}`, `{season}`), plus `jq` and `uv`.
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

The one-liner:

```sh
uv run --project {package-dir}/pipeline python -c '
from io import StringIO
import pandas as pd
tables = pd.read_html(StringIO(open("data/scratch/box.html").read()))
print(len(tables), "tables")
for i, t in enumerate(tables):
    print(i, t.shape, [str(c).lower() for c in t.columns][:8])'
```

It works, and that is the trap: a pile of anonymous shapes. The page knows
which table is which, in `caption` elements pandas never showed you; the
live reader keys table lookups on that text (`parse_boxscore_page` in
`pipeline/src/sidearm_live.py`):

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
grep -n "offsides\|penalty-type" {package-dir}/pipeline/src/sidearm_live.py \
  {package-dir}/pipeline/src/sidearm_parser.py
grep -ni "substitutes" {package-dir}/pipeline/src/parser.py \
  {package-dir}/pipeline/src/sidearm_parser.py
```

**The mislabeled Fouls id.** The template stamps the Fouls stat group with
`id="offsides"`, so a reader keyed by element id silently swaps fouls and
offsides; `_TEAM_STAT_LABELS` in `pipeline/src/sidearm_live.py` keys by
the visible header text instead.

**Card color lives in a CSS class.** Yellow or red is encoded in the class
attribute of the type cell, and `pd.read_html` flattens cells to text, so
the naive pass structurally cannot see it. `_parse_cautions_table` in
`pipeline/src/sidearm_parser.py` drops to BeautifulSoup and checks for
`"red"` in the class list, as does `parse_boxscore_page` on the live page.

**The substitutes flip.** Starter versus substitute is never printed on a
player's row; it is carried by a section row. Both lineages read the table
as a two-state machine: `is_starter` starts true and flips at the
"substitutes" row (`parse_player_stats_table` in `pipeline/src/parser.py`,
`_parse_player_table` in `pipeline/src/sidearm_parser.py`, and the
`Starters`/`Substitutes` header groups in `match_lines`).

**Check yourself**: the stored card types have a closed vocabulary,
because the class attribute is their only source; verify with this
command:

```sh
jq -r '[.matches[].cards // [] | .[].type] | unique[]' \
  data/matches/{season}-men-gac.json
```

Every line is `yellow`, `red`, or `unknown`, the three values
`parse_boxscore_page` can produce.

## 4. Try it: classify by signature, then diff

Classify each table in your listing by hand with the signatures in
`pipeline/src/sidearm_parser.py`: columns containing `_PLAYER_COLS` make a
player table, `_GOALIE_COLS` a goalie table, `_SCORING_COLS` a scoring
summary; a `statistic` column marks team stats; the score table holds a
`team` column and sits first; four columns with `type` is cautions. Then
run the classifier:

```sh
uv run --project {package-dir}/pipeline python -c '
from io import StringIO
import pandas as pd
from src.sidearm_parser import _classify_tables
c = _classify_tables(pd.read_html(StringIO(open("data/scratch/box.html").read())))
print({k: len(v) if isinstance(v, list) else v is not None for k, v in c.items()})'
```

**Check yourself**: your hand verdicts and the printout agree table for
table; verify with the command above. Where a caption from exercise 2
names a table the signatures missed, the columns name the reason: a header
outside the signature's dialect (the live reader's label map accepts both
`MIN` and `Mins.`). The StatCrew lineage trusts headers
even less: `identify_table_type` in `pipeline/src/parser.py` checks goalie
signatures before player ones and confirms a player table statistically
with `has_jersey_number_column`.

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

## 6. Try it: break a page and read the forensics

When a page defeats the parser, the failure is recorded, not discarded:
`pipeline/scripts/scrape.py` calls `log_parse_error`
(`pipeline/src/parser.py`) with the raw HTML, and the game still fails the
run's exit code. Reproduce it on a scratch copy, artifact routed to your
practice home:

```sh
cp data/scratch/box.html data/scratch/broken.html
TOUCHLINE_DATA_DIR={practice-dir} uv run --project {package-dir}/pipeline python -c '
from bs4 import BeautifulSoup
from src.parser import log_parse_error
from src.sidearm_parser import parse_sidearm_game
soup = BeautifulSoup(open("data/scratch/broken.html").read(), "lxml")
for table in soup.find_all("table")[3:]:
    table.decompose()
html = str(soup)
open("data/scratch/broken.html", "w").write(html)
try:
    parse_sidearm_game(html, 999, "scratch", {season})
except Exception as exc:
    log_parse_error(999, {season}, exc, html)'
```

The gutted page fails the fail-fast bound: fewer than seven tables raises
`ValueError` in `parse_sidearm_game`.

**Check yourself**: the artifact names the error and still describes each
surviving table, debuggable without re-fetching; verify with this command:

```sh
jq -r '.error_type, .error_message' \
  {practice-dir}/data/errors/{season}/game_999.json
jq -r '.tables[] | "\(.index)  \(.shape)  \(.columns | join(","))"' \
  {practice-dir}/data/errors/{season}/game_999.json
```

The first prints `ValueError` and its message; the second, one line per
surviving table.

## Next stop

Every row you parsed still names its teams with whatever string the site
rendered that week. The next lab follows those strings through
normalization, aliases, and adjudication to canonical identities. Read
[Identity](../../concepts/identity/) on the way. Next stop:
[Trace an identity](../trace-an-identity/).

## Related

**Run it**

- [Rebuild from the archive](../../guides/rebuild-from-the-archive/):
  `reparse` re-runs these parsers over every archived page, offline.
- [Audit the data](../../guides/audit-the-data/): the caption check that
  re-audits the whole cached population.

**Understand it**

- [Reading hostile HTML](../../concepts/reading-hostile-html/): the theory
  of every defense this lab tripped.
- [Proof before parse](../../concepts/proof-before-parse/): why the season
  and the match are proven before any parser runs.
