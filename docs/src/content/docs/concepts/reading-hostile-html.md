---
title: Reading hostile HTML
description: "Box scores come from templates that mislabel, reorder, and omit. The parsers treat position as the weakest evidence: they classify by content, fall back in layers, and leave forensics when they fail."
sidebar:
  order: 4
---

A box-score page is not a data feed. It is a rendering, produced by whatever
template a school's athletics site happens to run, and templates lie: they
mislabel element ids, reorder tables between site generations, encode facts in
CSS classes, and list teams in whichever order the layout prefers. Touchline's
parsers therefore treat every structural assumption as a hypothesis to test
against the page itself. Tables are classified by what their columns contain
rather than where they sit. Labels are read as a human reader sees them, not
from element ids. Home and away are reconciled from geographic evidence
and tagged with the evidence used. This page is the theory of that stance,
learned from two generations of hostile templates.

## Two lineages, one contract

The archive holds two site generations. The older **StatCrew** custompages era
is parsed by `pipeline/src/parser.py`; the modern **SideArm** era by
`pipeline/src/sidearm_parser.py`. The two pages share almost no structure, so
the parsers share almost no code. What they share is the output contract: both
`parse_game` and `parse_sidearm_game` return the same dict of `game`,
`player_stats`, `team_stats`, `events`, `abbrev_map`, and
`home_away_resolution`, built from the dataclasses in
`pipeline/src/models.py` (`Game`, `PlayerGameStats`, `TeamGameStats`,
`GameEvent`). Downstream code never learns which lineage produced a row.
Hostility is absorbed at the boundary; everything after the boundary sees one
schema.

## Classify tables by what they contain

`pd.read_html` pulls every `<table>` off the page, and nothing about a table's
position says what it is. The SideArm module docstring documents the nominal
ten-table layout of a modern box score, then immediately disclaims it: older
pages omit the cautions table or reorder the rest. So `_classify_tables` in
`pipeline/src/sidearm_parser.py` identifies each table by a column-set
signature (a table whose columns are a superset of `_PLAYER_COLS` is a player
table, of `_GOALIE_COLS` a goalie table) rather than by hardcoded index; the
one positional check it keeps is the score table, which must also sit first
on the page. When a page has
too few tables to be a box score at all, the parser refuses it with a
`ValueError` rather than guessing.

The StatCrew side goes further, because StatCrew headers are inconsistent
enough that even column names cannot be fully trusted. `identify_table_type`
in `pipeline/src/parser.py` classifies by heuristics: it checks goalie
signatures before player signatures because a goalie table would otherwise
pass the player test, and it confirms a player table statistically with
`has_jersey_number_column`, which demands a column where at least 70 percent
of values look like one or two digit jersey numbers. The cautions table has no
reliable header at all, so `is_cautions_table` recognizes it purely by shape
and content: exactly five columns with "yellow card" or "red card" in the card
column. This is schema-on-read in its honest form: the schema is inferred from
the data, and the inference is written down as a testable predicate.

## Read the label the reader sees

Two cases taught the parsers to distrust markup attributes and trust visible
text. The first is the Fouls id: the SideArm template mislabels the Fouls
stat group with `id="offsides"`, so keying stat groups by element id would
silently file fouls under offsides. The live box-score reader in
`pipeline/src/sidearm_live.py` keys its `_TEAM_STAT_LABELS` map by the visible
header text instead, and its `parse_boxscore_page` matches tables by their
`<caption>` text. The id is the template's opinion; the visible label is what
the site actually asserts to its readers.

The second is the inverse: a fact visible only in markup. On a SideArm page,
whether a card is yellow or red is encoded in the CSS class of the
`penalty-type` cell, not in the cell's text. `pd.read_html` flattens every
cell to text, so a naive table reader structurally cannot see the color.
`_parse_cautions_table` in `pipeline/src/sidearm_parser.py` drops down to
BeautifulSoup, finds each `td` with class `penalty-type`, and reads the card
from the class list. The lesson generalizes: choose the extraction tool per
datum, not per page.

## Fall back in layers

The StatCrew module opens with its own strategy in one line: tables first,
play-by-play second, regex last. Structured tables are the most reliable
witness, so `parse_game` prefers table-derived goal and card events and uses
play-by-play events only when the tables produced none; substitutions exist
only in play-by-play, so they always come from there. Within the play-by-play
layer, goals are matched by two regex patterns over the page text,
deduplicated through the `goals_found` clock set so a goal matched by both
patterns lands once. Header
metadata layers the same way: `parse_game_header` tries the `<title>` tag
first and falls back to a broader regex over visible text. Even a missing
statistic gets a documented derivation rather than a hole: when the period
tables omit team shots on goal, `parse_boxscore_tables` sums the team's
player shots on goal instead. Each layer is worse evidence than the one above
it, and the order encodes that ranking.

## A state machine at the substitutes row

A player table is secretly two lists: starters, then substitutes, separated by
a section row. Both parsers read it with a two-state machine: `is_starter`
begins true and flips to false at the "substitutes" row, in
`parse_player_stats_table` on the StatCrew side and `_parse_player_table` on
the SideArm side. A fact about each player is never printed on the player's
row; it is carried as parser state from a row that names no player at all.

## Home and away are evidence, not row order

StatCrew lists the away team in row 0, and the SideArm parser trusts that
same away-first convention only as a last resort. Betting a dataset on row
order is how it quietly inverts half its results, so both parsers reconcile
the sides through `resolve_home_away` in `pipeline/src/home_cities.py`, which
weighs the venue city against the scraping school's home city and the
opponent's and falls back to row order only when the venue evidence decides
nothing. It returns
not just a side but a provenance bucket (`resolved-by-venue`,
`resolved-by-order-fallback`, `neutral`, `venue-city-unmatched`), surfaced as
`home_away_resolution` in every parse result. The claim carries its evidence,
so an auditor can later ask how each game's orientation was decided.

The cautionary tale is gh-21. When the SideArm parser swaps the home and away
labels, the player tables, collected in page order, must swap with them. In
the original code they did not: every roster was stamped with the opposing
team's name, while `team_game_stats`, keyed by abbreviation rather than
position, survived unaided. The comment above the swap in
`pipeline/src/sidearm_parser.py` records the incident, the regression test
`test_swap_relabels_player_rosters` in `pipeline/tests/test_sidearm_parser.py`
pins the fix, and `pipeline/scripts/check_sidearm_captions.py` audits the
whole stored population by re-parsing every cached page and comparing goalie
`<caption>` text against stored roster labels, classifying each game as
`aligned`, `swapped`, `ambiguous`, `unmatched`, or `missing_pages`, and
exiting nonzero unless every game aligned. One orientation bug produced a permanent audit.

## Fail with forensics

When a page defeats all the layers, the failure is captured, not discarded.
`log_parse_error` in `pipeline/src/parser.py` writes
`data/errors/{year}/game_{game_id}.json` with the traceback plus every
table's shape, columns, and first row, so a parse failure is debuggable
months later without re-fetching the page. Below that, failure is scoped
narrowly: each row loop catches only `(ValueError, TypeError, KeyError,
IndexError)`, so one malformed row skips without killing its table, while an
unexpected exception (an `AttributeError` from a genuine bug) still raises
and lands in the forensics file. Expected dirt is skipped; unexpected bugs
are loud.

Lab: [Read a raw page](../../tutorials/read-a-raw-page/) fetches a SideArm
box score, walks its table classification by hand, and springs the payload
trap on your archived schedule page.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): the workflow that feeds
  these parsers real pages.
- [Audit the data](../../guides/audit-the-data/): run the caption check and
  the other standing audits yourself.

**Understand it**

- [Proof before parse](../proof-before-parse/): the layer above, which decides
  whether a page deserves parsing at all.
- [Identity](../identity/): where the parsed team strings become canonical
  identities.
- [Raw archive as system of record](../../design/raw-archive-as-system-of-record/):
  why every parser decision is re-runnable against the committed HTML.
