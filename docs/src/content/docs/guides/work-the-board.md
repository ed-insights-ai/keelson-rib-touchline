---
title: Work the board
description: Read the season board's rail and drawers, act on its notices, and point it at a season or team with touchline_focus.
sidebar:
  order: 4
---

The season board is the rib's one surface panel: a self-contained HTML
snapshot rendered in a sandboxed iframe under the snapshot key
`rib:touchline:board` (`BOARD_KEY` in `src/keys.ts`). The composer is a pure
function of the season files and the day: `composeBoard` in `src/board.ts`
takes `today` as an input, so the same data always renders the same sheet.

## 1. Point it at a project

Pick a project in the surface's project picker; only actual Touchline data
homes are offered. The selection (project, season, team, open drawer) lives
in module state (`src/state.ts`) and is not persisted: a restart resets to
nothing selected, and choosing a different project clears everything
downstream, because a different project is a different data home.

## 2. Read the season rail

One tick per fixture, laid out by week, so the campaign's shape is visible
at a glance: dense weeks, bye weeks, and how far results have filled in from
the left.

- A solid tick is a played match (`isPlayed` in `src/model.ts`: status
  `final`; a final whose site never published a score still counts).
- On the team lens a played tick carries the outcome: green won, red lost,
  amber drawn.
- A hatched tick is postponed or cancelled.
- An unfilled tick behind today is the rail's honesty check: it flags in
  rose, and the rail's footer counts it as "past date, no result published".
  The collector reads the sites' own completion marks, so this is the site's
  silence, not an uncollected result.

The conference lens with more than one programme shows the matchday matrix
instead (teams as rows, fixture dates as columns); its header is itself the
calendar, so the rail appears where dates run vertically: the team lens and
single-programme seasons.

## 3. Open the drawers

Any schedule row (or the matrix's selection card) opens the match drawer:
score by period, scoring, cautions, play by play, closing from the veil,
the close button, or Escape. A played fixture without a collected box score
still opens; the drawer says exactly why there is nothing behind it, reading
the reason from the matches file's `missing` map. A final the site marked
finished but never scored gets its own line, because the schedule page's
silence is a fact of its own.

On the team lens, every roster row opens the player drawer: the published
bio, a tenure line, and the season's statistics, or a plain statement that
none exist yet. Tenure claims are absence claims, so "First season on this
roster" and the NEW chip render only when the archive holds complete prior
roster coverage (`priorRosterCoverage` in `src/board.ts`); sightings at
other programmes need no such licence. One drawer at a time: selecting a
fixture clears the player and vice versa (`src/state.ts`).

## 4. Act on the notices and markings

- **Membership carried forward**: the fixtures file's
  `membership_extrapolated` flag renders as a notice that the member list is
  the most recent published one carried forward, not yet cited to a source
  for the shown season.
- **Collection gaps**: each missing programme is named with its layer, plus
  a count of missing box scores, "named rather than dropped; a re-collect
  retries them". Fix them with a re-collect, not by squinting.
- **Pre-season is a valid state**: a published schedule and roster with zero
  played matches is a complete collection, and the masthead stamps
  "pre-season" rather than implying something failed.
- **Exhibitions**: a fixture whose `match_type` is `"exhibition"` is marked
  "Exh" in its row's status cell and "Exhibition" in the card and drawer
  bylines. That is the site's own marking that the game does not count, and
  it explains a missing score and a record that stays 0-0.

## 5. Point it from chat

The `touchline_focus` tool moves the board to a season, a conference shard,
or a single team. Ambiguity is reported, never guessed: two matching shards
ask you to name a conference, and a team absent from the shown season is
refused along with the programmes that are in it. The masthead does the same
on the sheet: chevrons step through the seasons on disk, and conference tabs
switch shards.

## 6. Nothing on the board writes

The board's actions (`select-project`, `select-season`, `select-lens`,
`select-player`, `open-fixture`, all handled in `src/index.ts`) each move
the selection and repaint; none touches the data home's files. Every write path
(init, collect, focus, remove) lives in the chat tools, which carry their
own gates and confirmations. The panel opens the Touchline agent for exactly
that reason: collection is a conversation, not a form on the board.

**What you just exercised:**
[Absence is data](../../concepts/absence-is-data/) (the rail's honesty
check, the gaps notice, the drawer that says why),
[Identity](../../concepts/identity/) (identity hues are never borrowed from
status colours: green always means a result),
[The determinism boundary](../../concepts/the-determinism-boundary/) (a
composer that is a pure function of data and date), and
[Season is a dimension](../../concepts/season-and-membership/) (the
extrapolation notice).

## Related

**Run it**

- [Run a collection](../run-a-collection/): fill the gaps the notices name.
- [Rib surface](../../reference/rib-surface/): the tools, board actions, and snapshot key as a contract.

**Understand it**

- [Absence is data](../../concepts/absence-is-data/): why the board renders what is missing instead of hiding it.
- [Stand up a season](../../tutorials/first-season-board/): the lab that reads this surface end to end.
