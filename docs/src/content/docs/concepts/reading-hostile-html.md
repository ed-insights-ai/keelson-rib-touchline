---
title: Reading hostile HTML
description: "Published pages come from templates that mislabel, reorder, and omit. The collector treats position as the weakest evidence: it classifies by content, types free text conservatively, and names its failures."
sidebar:
  order: 4
---

A published sports page is not a data feed. It is a rendering, produced by
whatever template a school's athletics site happens to run, and templates
lie: they mislabel element ids, reorder tables between site generations,
encode facts in CSS classes, and list teams in whichever order the layout
prefers. The collector in `pipeline/src/sidearm_live.py` therefore treats
every structural assumption as a hypothesis to test against the page itself.
Tables are found by what they say they are, not where they sit. Labels are
read as a human reader sees them, not from element ids. Team references are
resolved against the page's own name table and stored with the resolution.
This page is the theory of that stance, learned across two generations of
hostile templates.

## Find tables by what they claim to be

A box-score page renders a pile of `<table>` elements, and nothing about a
table's position says what it is. `parse_boxscore_page` in
`pipeline/src/sidearm_live.py` matches each table by its `<caption>` text:
`Team Score By Period`, `Team Statistics`, `Scoring Summary`,
`Cautions and Ejections`, and the per-side player and goalie tables whose
captions end in a known suffix. The cumulative-statistics reader
(`parse_stats_page`) goes one layer deeper: within a captioned table it
keys every stat cell by its `data-label` attribute and anchors each player
row on `a[data-player-id]`, which is also what keeps the Total and
Opponents footer rows out; a footer names no player, so it carries no
anchor. The docstring records the measurement that earned the trust: seven
sites, seasons back to 2016, every one server-rendering those two tables
with those labels.

When a page cannot prove what it is, the collector refuses it rather than
guessing. `assert_served_match` demands the box-score title name the
fixture's own date, and `collect_match` raises `LiveCollectionError` when
the score-by-period table renders anything but exactly two teams. A refusal
is a named gap, never a silently wrong row.

## Read the label the reader sees

Two cases taught the collector to distrust markup attributes and trust
visible text, and one taught it the inverse.

The first is the Fouls id: the SideArm template mislabels the Fouls stat
group with `id="offsides"`, so keying stat groups by element id would
silently file fouls under offsides. `_TEAM_STAT_LABELS` in
`pipeline/src/sidearm_live.py` keys its map by the visible header text
instead. The id is the template's opinion; the visible label is what the
site actually asserts to its readers.

The second is the inverse: a fact visible only in markup. On a SideArm page,
whether a card is yellow or red is encoded in the CSS class of the type
cell, not in the cell's text. A table reader that flattens cells to text
structurally cannot see the color, so the cautions reader in
`parse_boxscore_page` checks the cell's class list for `yellow` or `red`
and stores `unknown` when neither appears. The lesson generalizes: choose
the extraction tool per datum, not per page.

## Type free text conservatively

The play-by-play panel is free text typed by each home stat crew. The
collector keeps the raw line as the record and assigns a `type` only when
the wording matches a known SideArm phrasing (`_PLAY_TYPE_PATTERNS`), first
match wins: a penalty goal reads "PENALTY KICK GOAL by" and is a goal
before it is a penalty. A line that matches nothing stays untyped rather
than mistyped. Attribution is structural: the desktop layout renders one
column per team, so the column an event lives in is its team, resolved
through the column header's own abbreviation.

## A state machine at the substitutes row

A player table is secretly two lists: starters, then substitutes, separated
by a section row. The `match_lines` reader in `parse_boxscore_page` walks
it as a two-state machine: the `Starters` header group sets the flag, the
`Substitutes` header group flips it, and every player row in between
inherits the current state. A fact about each player is never printed on
the player's row; it is carried as parser state from a row that names no
player at all.

## Team references are evidence, not row order

Within one box-score page, teams are referenced by whatever abbreviation
the page chose: consistent within the page, not across pages, and sometimes
truncated ("Hardin"). So every reference in the scoring summary, the
cautions table, and the player-table captions is resolved against the score
by period table's own name and abbreviation pairs and stored as an index
into `teams`. Orientation against the fixture is then settled by
`orient_match` and recorded as `home_index`, so a stored box score knows
which side is which without trusting page order.

The cautionary tale is gh-21, from the retired box-score scraper this
collector replaced. When that parser corrected a home/away swap, the player
rosters, collected in page order, did not swap with it, and every roster
was stamped with the opposing team's name. One orientation bug taught the
whole family the rule above: a side is an identity resolved from evidence
on the page, never an index inherited from layout.

## Fail with a name

When a page defeats the collector, the failure is captured, not discarded.
A programme layer that cannot be proven lands in `data/coverage.json` as a
cell with a `reason`; a box score that cannot be collected lands in the
matches file's `missing` map and in the run's
`data/errors/collect-board-{season}-{gender}-{conference}.json` gap ledger.
And because `write_raw_pages` archived the served bytes first, the failed
parse is debuggable months later without re-fetching the page.

Lab: [Read a raw page](../../tutorials/read-a-raw-page/) fetches a SideArm
box score, walks its caption-keyed tables by hand, and springs the payload
trap on your archived schedule page.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): the workflow that feeds
  the collector real pages.
- [Audit the data](../../guides/audit-the-data/): run the standing checks
  over what the collector produced.

**Understand it**

- [Proof before parse](../proof-before-parse/): the layer above, which decides
  whether a page deserves parsing at all.
- [Identity](../identity/): where the parsed team strings become canonical
  identities.
- [Raw archive as system of record](../../design/raw-archive-as-system-of-record/):
  why every parser decision is re-runnable against the archived HTML.
