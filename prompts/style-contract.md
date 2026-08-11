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
  surfaced in the run summary for a human to capture or discard. An
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
- **"Fitness" is never established by goal timing.** Late concessions can
  reflect substitutions, tactics, score effects, or concentration. Write
  "performance after 60 minutes" until film isolates the cause.
- **Name the measure when ranking a player.** "Shot-on-target rate" or
  "conversion", never bare "efficiency".
- **Small-sample reads get humble headers.** A weakness inferred from a
  goal-timing sample is a "potential opening", not a vulnerability or a
  conclusion.
- **Shares are people, not portfolios.** A team never "returns 26% of its
  goals" — players return. Write "the players who scored three-quarters
  of their goals are gone", "no midfielder who played last season is
  back", "their goalkeeper returns after playing every minute". If a
  returning-share number cannot be attached to people in the sentence,
  rewrite the sentence. Tables may carry the raw percentages; prose
  carries the people.
- **More diction swaps** (the left column is banned): "for the focus
  side" → "for <team name>"; "inflection date" → "first competitive
  checkpoint"; "shapes everything downstream" → "must be decided early";
  "tempo disruption" → what to actually do ("keep the match level", "slow
  their restarts"); "planning surface" → "the schedule".

## Decisions are preseason calls

An executive "decision" is something the staff settles before the first
match: a selection, a role, a training investment. A fixture to circle, a
checkpoint, or a mid-season milestone is not a decision — if it matters,
it belongs in the opponent card or the schedule, once.

## The international lens (D2 recruiting)

Division II eligibility rules let international players arrive older and
more experienced than domestic freshmen, and some programmes recruit
internationally at volume to buy experience wholesale. The digest counts
each squad's international share from published hometowns. Read a
heavily-international newcomer class differently from a domestic freshman
class: class year understates experience, and the impact variance runs
high in both directions. This is a structural recruiting pattern to note
when sizing a roster — never a judgment about a named individual, whose
record and film speak for themselves.

The same lens extends to every incoming player: class year is the
weakest experience signal, and verified pedigree calibrates it. As a
rough ladder — pro or federation academies and senior international
club football sit at the top; MLS Next and ECNL club backgrounds mark a
freshman proven at a higher level than standard high-school play, often
comparable to a JUCO transfer; JUCO and lower-division college transfers
carry real minutes but against variable competition. A freshman from an
MLS Next academy and a freshman from an ordinary high school are not the
same "unproven newcomer", and a JUCO All-American is not automatically
more ready than either. Use the ladder to set expectations when the
research holds verified pedigree; where it holds nothing, say the
newcomer is unscouted rather than guessing a tier.

## Major news travels to every report

A verified head-coach change, intra-conference transfer, or decorated
arrival appears in that programme's card in every report that covers it,
not only the programme's own. The lens shifts with the reader: a new
coach means the opponent's film library just expired and last season's
patterns are provisional; a transfer moves a known threat between cards;
an arrival changes a depth chart. Length cuts never remove this class of
news.

## The generic-decision test

If a decision's title would sit unchanged in another team's report, it is
under-specified — "name the second attacking route" fits half the teams
in college soccer. Rebind it to this team's facts until it could belong
to no one else: not "find a second scorer" but "replace Ovelar's 15
goals" for one team and "decide who plays off Grudis" for another. The
same underlying concern, told through different facts, produces
different decisions. Apply the same test to findings, priorities, and
dossier verdicts.

## Anti-formula rules

- **Vary the scaffold.** Consecutive items in one list (watchlist notes,
  implications, questions, priorities) must not share an opening verb or
  sentence shape. Eleven notes that all begin "Track the returning
  forward's..." are a formula wearing analysis clothes.
- **Contract examples are illustrations, not required phrasing.** A
  concept named in this contract ("performance after 60 minutes") applies
  only where THIS team's data flags it — do not import another report's
  storyline vocabulary because the contract used it in an example.
- **Tier names never appear in prose.** "Benchmark", "swing", and
  "update" are layout classifications the card already displays; prose
  that announces "tier X as a swing" is the system narrating itself. Say
  what to do about the opponent instead.
- **A watchlist draws from different evidence classes** where the record
  offers them: a verified offseason move, a small-sample riser, an
  availability or usage signal, a top returner. One class repeated five
  times is a formula, not a watchlist.

## The toolkit rule (absolute)

The page structure is a toolkit, not a template. Which decisions surface,
which players get profile pages, which opponents land in which tier, and
which position groups get attention all come from the current team's
digest and verified findings at generation time. Never carry a previous
report's topics forward: no report assumes a goalkeeper battle, a scoring
gap, or any other specific storyline exists until the data for THIS team
shows it. The freedom runs the other way too: when the findings support
an angle no prior report has used — a new kind of decision, an unusual
dossier subject, a watchlist built on something unexpected — take it.
The toolkit shows how to lay out and communicate efficiently; it never
limits what the analysis is allowed to conclude.

## Length

2,400–2,900 words of prose for the whole report. Each page is a complete
story with one conclusion, stated once. Repetition, not facts, is what
makes a report long: if a point appears in the executive brief, it does
not reappear as a takeaway elsewhere.

## The insight filter

Before an insight enters the report, score it: focus-side relevance
(0-2), changes a coaching decision (0-2), evidence strength (0-2),
non-duplicative (0-1), current for this season (0-1), adequate sample
(0-1), explainable in one sentence (0-1). Score 7-10 → main report; 5-6 →
watchlist or appendix; below 5 → cut. Every major block must be able to
populate Evidence, Meaning, Action, and Caveat — if there is no Action a
coach could take, it does not belong in the coach-facing report.

## No self-reference (absolute)

The report never talks about itself. It does not explain why content was
included, what the analysis system can or cannot see, how sections relate
to each other, or who the intended reader is. Lines like "that is why
they belong in this report" or "this page is about the battle" are
editorial scaffolding — delete them and let the content stand. Provenance
lives in exactly two places: the cover's data line and the technical appendix.

## Captions

A visual's caption exists only for a legend the reader needs or a caveat
that changes interpretation (coverage, sample, carried-forward data).
Pure provenance ("observed, computed from published rosters") is never a
caption: the evidence chips and the cover legend already carry it.

## Punctuation and cadence

- **The em-dash is a once-per-paragraph tool at most**, used only where a
  comma, colon, period, or parentheses cannot carry the break. Two
  em-dash sentences in a row read as generated text. Numeric ranges keep
  the en-dash (75'–90'); this rule is about prose.
- Banned reflexes: the "claim — elaboration" pivot as a default sentence
  shape; "not just X — Y"; "X isn't A; it's B" antithesis mirrored across
  consecutive sentences; aphoristic fragments as paragraph closers;
  three-item rhythm as the automatic list shape.
- Default cadence: short declarative sentences, plain connectors, varied
  sentence length. A colon introduces. Parentheses hold asides. The
  period is the workhorse.
- Test: read the paragraph aloud. If it sounds like a keynote or an ad,
  rewrite it as a memo from one coach to another.

## Voice

- Written by a scouting department for a coaching staff. Direct, specific,
  tactical. Short declarative sentences. No hype, no filler, no "exciting
  season ahead". Never flatter the reader.
- Plain soccer language, never consulting language: "reset expectations",
  not "re-price the season"; "controllable gaps", not "coaching surface
  area"; "early roster integration", not "chemistry curve". If a coach
  would not say the phrase at training, rewrite it.
- **Word choice is the loudest tell.** Write with the vocabulary of a
  beat writer or an assistant coach, not an analyst deck: "the league
  order is wide open", not "the conference hierarchy is unusually
  fluid"; "the two biggest calls of preseason", not "the two
  highest-leverage decisions"; "a second goal scorer", not "a second
  source of attacking production"; "they spent the year pinned in their
  own end", not "sustained territorial exposure". If a word belongs in a
  quarterly business review (leverage, hierarchy, fluidity, structural,
  optimize, capability), swap it for the word the locker room uses.
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

Page budgets are hard print boundaries. Prioritization is the product:
fewer, stronger items beat coverage.

1. Cover: competition, season, focus programme, headline, "prepared"
   date, data provenance line, and the evidence-label legend.
2. Executive brief — exactly two pages. Page one: bottom line (≤70
   words), season indicators, 3 split findings. Page two: at most 3
   decisions, then the view from outside — the published numbers,
   goal-timing chart, overview (≤110 words), verified news, offseason
   ledger (max 3 consolidated signals, footnoted sources).
3. Roster decisions and preseason scorecard — at most two pages: squad
   map, line-by-line read, availability and usage signals, priorities,
   scorecard.
4. Conference landscape and where the focus side gains ground — one
   page: standings table, gap chart, prose ≤100 words.
5. Opponent cards, one per sheet at about three-quarters of a page:
   identity, roster change, key threat, potential opening, implication,
   at most 2 news items, head-to-head strip. Benchmark tier first.
6. Watchlist — one sheet per opponent: exactly two half-page player
   profiles (held career line, why watch ≤90 words, what preseason
   verifies). No focus-side entries, no separate dossier section.

There is no schedule sheet and no sources page. The collection file
ledger lives in the technical appendix; definitions travel with the
evidence chips and the cover legend.

## Look

- Professional sports broadcast, not office memo: condensed display type,
  tabular numerals, disciplined color. It should feel like a team's own
  scouting department produced it.
- Print-neutral palette, always: near-black ink on white paper, one
  restrained accent for structure, semantic green/red for W/L, muted rose
  for risk. Never a school's colors — the report is independent analysis
  and school-agnostic by design, and the same palette must serve every
  programme and conference without retheming. Avenir Next Condensed
  display over a system text face.
- Every visual is drawn from digest values only: W/D/L form strips,
  goals-by-minute band bars, returning-share bars, head-to-head timelines.
  Inline SVG, no chart libraries, no external assets.
- One signature visual per opponent section (the minute-band profile), not
  decoration everywhere. Numbers a coach must compare sit in tables, not
  prose.
- Branding: best look first. Company brand alignment (edinsights.ai —
  "Empowered Data. Artificial Intelligence. Real Results.") comes later; a
  discreet "EDInsights" provenance mark in the footer is enough for now.
