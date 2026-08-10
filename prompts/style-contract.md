# Scouting Report Style Contract

The rules every generated report obeys. The questionnaire says *what* to
answer; this file says *how it must read and look*. Tune the product here.

## The figures rule (absolute)

- Every number in the report comes from the digest
  (`data/reports/digest-<season>-<gender>.json`), verbatim. A figure that is
  not in the digest does not appear — no arithmetic beyond what the digest
  already computed, no estimates, no "roughly".
- News-layer claims (coaching changes, arrivals, polls) carry a source and
  a date, fetched and verified — or they are not made. "No verified news"
  is written when that is the truth.
- **If it isn't discoverable, it isn't in the report.** Attested-but-
  uncaptured claims never appear in report content — not as fact, not as a
  hedge, not in an uncertainty. They live only in the research artifacts,
  surfaced at the approval gate for a human to capture or discard. An
  undated source cannot date a claim: a name-only squad listing with no
  season stamp does not establish a current-season fact.
- Missing data is a named gap, stated plainly ("2026 roster not yet
  published — turnover unknown"), never papered over.
- Patterns computed over partial box-score coverage state the coverage
  ("18 of 18 matches", "11 of 14 matches").
- When conference membership was carried forward past its last authored
  season, the report says so once, up front.

## Voice

- Written by a scouting department for a coaching staff. Direct, specific,
  tactical. Short declarative sentences. No hype, no filler, no "exciting
  season ahead". Never flatter the reader.
- Insight is a hypothesis anchored to a cited number: "They conceded 9 of
  14 goals after the 60th minute — sustained second-half pressure is the
  percentage play." Not: "They tend to tire late."
- Players are named with position and class year on first mention.
- The reader knows soccer. Explain nothing about the sport; explain only
  what the data shows.

## Structure

1. Cover: competition, season, focus programme, "prepared" date, data
   provenance line (seasons held, collection date).
2. Conference landscape (table + returning-production visual + narrative).
3. The focus programme, honestly assessed.
4. One opponent section per conference opponent, in schedule order.
5. Watch list.
6. Provenance and caveats footer: what the digest covers, what it cannot
   see, when it was collected.

## Look

- Professional sports broadcast, not office memo: condensed display type,
  tabular numerals, disciplined color. It should feel like a team's own
  scouting department produced it.
- Cohesive with the Touchline board: Avenir Next Condensed display over a
  system text face; the board's palette families (ink/muted/faint text,
  one accent, semantic green/red for W/L) on a committed dark or light
  ground.
- Every visual is drawn from digest values only: W/D/L form strips,
  goals-by-minute band bars, returning-share bars, head-to-head timelines.
  Inline SVG, no chart libraries, no external assets.
- One signature visual per opponent section (the minute-band profile), not
  decoration everywhere. Numbers a coach must compare sit in tables, not
  prose.
- Branding: best look first. Company brand alignment (edinsights.ai —
  "Empowered Data. Artificial Intelligence. Real Results.") comes later; a
  discreet "EDInsights" provenance mark in the footer is enough for now.
