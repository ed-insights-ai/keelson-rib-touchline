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

## Credibility rules (absolute)

- **Records read W-L-T** — wins, losses, ties — everywhere, labeled on
  first use. American college coaches read `2-14-2` as W-L-T; a W-D-L
  record silently misreports the season.
- **Evidence and judgment never share a sentence.** Every executive
  finding splits into evidence (the fact), meaning (the interpretation),
  and implication (what the staff does with it). "Roster returns 19
  players" is observed; "continuity makes them the better pick" is
  judgment — the split keeps both honest.
- **A gap is a signal, not a diagnosis.** Participation gaps and minutes
  collapses are labeled *Unverified signal — requires confirmation*, never
  "projected injury". The gap is observed; the cause is not.
- **No conclusions from absence of evidence.** "No other public summer
  minutes found" is a defensible statement of coverage. "The rest of the
  squad trained all summer" is invention — never write the second kind.
- **Claim only what the data measures.** Corner counts show territorial
  and restart exposure, not marking quality or set-piece defending; shot
  counts show shot volume, not possession. Recommend the film audit, do
  not pre-judge its result.
- **Small samples stay small.** A player with two goals from 129 minutes
  is a watchlist line, not a breakout narrative. State the sample beside
  any claim built on it.
- **Held records are not all-time records.** Head-to-head and historical
  claims say "since <first archived season>" or "held record".

## The insight filter

Before an insight enters the report, score it: focus-side relevance
(0-2), changes a coaching decision (0-2), evidence strength (0-2),
non-duplicative (0-1), current for this season (0-1), adequate sample
(0-1), explainable in one sentence (0-1). Score 7-10 → main report; 5-6 →
watchlist or appendix; below 5 → cut. Every major block must be able to
populate Evidence, Meaning, Action, and Caveat — if there is no Action a
coach could take, it does not belong in the coach-facing report.

## Voice

- Written by a scouting department for a coaching staff. Direct, specific,
  tactical. Short declarative sentences. No hype, no filler, no "exciting
  season ahead". Never flatter the reader.
- Plain soccer language, never consulting language: "reset expectations",
  not "re-price the season"; "controllable gaps", not "coaching surface
  area"; "early roster integration", not "chemistry curve". If a coach
  would not say the phrase at training, rewrite it.
- Insight is a hypothesis anchored to a cited number: "They conceded 9 of
  14 goals after the 60th minute — sustained second-half pressure is the
  percentage play." Not: "They tend to tire late."
- Players are named with position and class year on first mention.
- The reader knows soccer. Explain nothing about the sport; explain only
  what the data shows.
- The focus side's own roster needs no introduction — its coach picked it.
  Cover the focus programme outside-in: what the public record shows an
  opponent, and say so. Trend signals about focus players (availability
  gaps, usage shifts, offseason footprints) stay — they show what others
  can see.

## Structure

Ten to twelve finished US Letter pages. Prioritization is the product:
fewer, stronger items beat coverage.

1. Cover: competition, season, focus programme, "prepared" date, data
   provenance line (seasons held, collection date).
2. Executive brief: bottom line, 3-4 split findings, at most 3 decisions,
   preseason priorities.
3. The focus programme from outside — what the public record shows;
   availability signals, usage shifts, offseason ledger (max 3
   consolidated signals, footnoted sources).
4. Conference landscape and where the focus side gains ground — one page.
5. Preseason validation questions + the schedule as a planning matrix
   (turnaround, venue, opponent continuity, priority — not history).
6. Priority opponents as half-page cards, two per page: identity, roster
   change, key threat, vulnerability, implication.
7. Rest of the conference compact + watchlist (one line per monitoring
   candidate).
8. Two player dossiers.
9. Sources, definitions, evidence labels. The collection file ledger goes
   to a separate technical appendix, not the main report.

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
