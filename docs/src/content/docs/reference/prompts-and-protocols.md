---
title: Prompt contracts
description: The four runtime-read markdown contracts under prompts/, what each governs, and which of their rules the gates enforce mechanically.
sidebar:
  order: 7
---

Four markdown files under `prompts/` are read by workflow nodes at runtime,
not baked into code. They are the tuning surface of the product: edit a
contract and the next run obeys it, with no rebuild. Each file states its own
jurisdiction, and the three report-side files divide it cleanly: the
questionnaire says what the report must answer, the style contract says how
it must read and look, the research protocol says how to look. Rules stated
in a contract bind every stage that reads it; a subset of them is also
enforced mechanically by the gates in `workflows/touchline-report.yml`, and
that split is tabled at the foot of this page.

| Contract | Governs | Read at runtime by |
|---|---|---|
| `prompts/research-protocol.md` | Retrieval, identity binding, source grading, stopping rules, for every research stage | The `research` loop in `workflows/touchline-report.yml`; second read of the player-profile research node |
| `prompts/player-profile.md` | How to research one player; the three verdicts | First read of the `research` node in `workflows/touchline-player-profile.yml` |
| `prompts/scouting-questionnaire.md` | The report's content: the candidate question set E1 to W1 and the card mapping | `narrative-core` and `narrative-cards` in `workflows/touchline-report.yml` |
| `prompts/style-contract.md` | The report's prose, credibility rules, budgets, insight filter, and look | `narrative-core` and `narrative-cards` |

The narrative nodes also read the `touchline.report-narrative/4` contract at
the top of `pipeline/src/report.py`. The adversarial verify pass takes its
instructions from its workflow node inline, not from a prompt file.

## research-protocol.md

The sweep, per programme, in order:

| Step | Move |
|---|---|
| Club-first | From hometowns and the campus location, list plausible summer clubs in the gender-correct competitions (men: USL League Two, NPSL, UPSL; women: USL W League, WPSL, UPSL) and fetch each club's roster or squad page, cross-referencing names |
| Bare-name | Search each distinctive name alone; every hit passes identity binding before it becomes a finding |
| Honors follow-up | Any membership hit triggers an immediate player plus league honors search |
| Special interest | Players carrying availability or usage signals get bare name plus hometown |
| Programme-level news | Head-coach status is mandatory and structured, recorded either way; plus preseason polls and signing classes |

**Stopping rules.** Effort is budgeted, not open-ended: stop the club-first
sweep for an anchor geography after five consecutive clubs with no roster
match; stop any query line when two consecutive variants add nothing new.
What was not swept is recorded in `unswept` with a reason, never searched
indefinitely.

**Identity binding.** A name match alone is never a finding. Every hit binds
through at least one corroborating attribute: school, hometown, club, age or
class year, jersey number, or a photo caption or tag naming them. Recency
weights the anchor; a hit that cannot be bound is dropped or filed as
`attested_uncaptured`, never stretched.

**Source confidence.**

| Grade | Sources |
|---|---|
| High | League or club official pages, federation records, local news |
| Medium | Club social posts at a stable URL; a player's own posts scoped to on-field activity (health information never comes from personal accounts) |
| Lead generation only | Transfermarkt, Soccerway, and other crowd databases: trails to verify elsewhere, never confirmation |

An undated source cannot date a claim. Verdict and confidence are orthogonal
axes: fetching a player's own post yields confirmed at medium, and the tier
never rises by being fetched. The report-entry rule follows the grade: a
confirmed claim at high confidence may appear in prose freely; a
confirmed-at-medium claim enters only with its source kind named in the
sentence, and never stands as the sole support for a decision or a
major-news item.

**Conflicting sources** resolve by precedence: most recent
programme-published page, then conference pages, then older official pages,
then press, with the disagreement recorded as a finding note.

**One finding, one page.** Never a finding whose truth needs two pages to
check; the verify pass fetches each finding's single URL and drops any claim
that page alone cannot support, so compound claims split.

**The dead-end bucket.** `attested_uncaptured` holds claims believed true
but not capturable at a fetched URL; they never reach the report in any
form, surfacing only in the run summary. The protocol also carries platform
techniques (direct post URLs, a Threads plain fetch, reading a roster-less
club's opponents), each with an expected failure mode filed as `unswept`.

## player-profile.md

The method, in order: disambiguate first (count the namesakes, never merge
two people); anchor on fetched official pages; build the timeline backward
from the focus year, naming each find's competition tier against the style
contract's experience ladder; sweep adjacent competition; then chase the
focus year explicitly, because search results skew toward whichever season
published more.

| Verdict | Meaning |
|---|---|
| Confirmed | Verified at a URL that was fetched and identity-bound to this player |
| Ruled out | A specific page was read and the name is absent: the strong form of absence |
| No indexed mention | The search surface cannot see it; a finding about coverage filed in `unswept`, never evidence of absence |

## scouting-questionnaire.md

The questions are the candidate set: the full sweep the analysis performs.
The style contract's page budgets, tier system, and insight filter decide
which answers survive onto the page; an answer with no surviving home stays
in the working notes. Voice is outside-in third person throughout, never
"we" or "our".

| Slot | Answers |
|---|---|
| E1 | The bottom line, at most 70 words; the cover headline is its compression |
| E2 | The three findings that matter most, each split evidence / meaning / implication |
| E3 | At most three preseason decisions, each passing the generic-decision test |
| E4 | The preseason scorecard: testable checks, rendered on the roster page |
| E5 | Season indicators, rendered as tiles on brief page one |
| L1 | Last season's conference table in one ten-second read |
| L2 | Returning and departed production, ranked by a named measure |
| L3 | Rising and exposed programmes, and where the focus side sits |
| L4 | Conference-wide offseason change; the wide view only, never a single programme's item |
| O1 | Form: overall and conference record, goal difference, clean sheets |
| O2 | Goal timing by half and 15-minute band, sample stated |
| O3 | Shot and corner volume: territorial exposure, never "chances" or possession |
| O4 | Discipline profile only; no dedicated card field |
| O5 | Goalkeeping and whether the keeper returns; no dedicated field |
| O6 | Roster turnover, written as people with shares in tables |
| O7 | Returning threats ranked by a named measure |
| O8 | Head-to-head: the held record, never "all-time" |
| O9 | When and where the focus side plays them |
| O10 | This programme's verified news; "no verified news" is a valid answer |
| O11 | Exactly one testable match-preparation implication |
| O12 | The bench: who runs the programme and for how long, read through the bench lens |
| R1 | The squad map by line of the team |
| R2 | The line-by-line read, shape figures split from judgment |
| F1 | The focus programme outside-in: what the public record shows an opposing staff |
| F2 | The summer ledger: at most three consolidated signals, sources inline |
| W1 | Up to two watchlist players per opponent, filter-admitted, never by quota |

**Card mapping.** The card fields (identity, bench line, roster change, key
threat, potential opening, implication, up to two news items, head-to-head
strip) absorb O1 and O9 into the header, O2 and O3 as threat and opening
evidence, O6 as the roster change, O7 as the key threat, O8 as the strip,
O10 as the news items, O11 as the implication, and O12 as the bench line. O4
and O5 have no dedicated home and survive only through the filter; the
stated samples of O2 and O3 serve as the card's caveat. Cards run benchmark
tier first, then swing, ordered within a tier by first meeting date.

## style-contract.md

**The figures rule (absolute).** Every number comes verbatim from
`data/scratch/digest-{season}-{gender}-{focus}.json`. The news layer is the
one exception: a news claim's own figures come verbatim from the cited page.
A named coverage gap ("2026 roster not yet published") is required content; a
hedged shadow of an uncaptured claim is banned in the same clause.

The named rule sets, one line each: credibility rules (records read W-L-T;
evidence and judgment never share a sentence; a gap is a signal, not a
diagnosis; no conclusions from absence of evidence; claim only what the data
measures; small samples stated; shares are people, not portfolios);
decisions are preseason calls; the international lens; the experience ladder
(the canonical rungs live here, other files reference them); the bench lens;
major news travels to every report; the generic-decision test; anti-formula
rules (tier names never appear in prose); the toolkit rule; length (roughly
150 to 200 words of prose per rendered page); no self-reference; captions;
punctuation and cadence; voice; structure (the page budgets); look.

**The insight filter.** Before an insight enters the report, score it:

| Axis | Points |
|---|---|
| Focus-side relevance | 0-2 |
| Changes a coaching decision | 0-2 |
| Evidence strength | 0-2 |
| Non-duplicative | 0-1 |
| Current for this season | 0-1 |
| Adequate sample | 0-1 |
| Explainable in one sentence | 0-1 |

Placement by total: 7-10 enters the main report; 5-6 becomes a compact line
on the card it concerns, or a watchlist profile when it is player-shaped;
below 5 is cut. There is no overflow bin. Major news (a verified head-coach
change, intra-conference transfer, or decorated arrival) bypasses the filter
entirely and is never scored out; the card's two-item news cap applies to
ordinary news only, and when majors alone exceed two, every item runs,
ordered coach change first, then intra-conference transfers, then decorated
arrivals.

## What a gate enforces, and what only the contract carries

The gates check shape and budget; everything else binds only through the
contract text the nodes read. Changing a rule that appears in both places
(a word budget, a finding count) means editing the contract and the gate
together, or the gate stops the run.

| Rule | Enforced by |
|---|---|
| Exactly 3 findings, 1 to 3 decisions, non-empty bottom line | `validate-narrative` |
| Bottom line at most 70 words, landscape 100, overview 110, watchlist "why" 90 | `validate-narrative` |
| Evidence and meaning present on every finding | `validate-narrative` (implication presence is contract-only) |
| Offseason ledger at most 3 signals; no dossier section | `validate-narrative` |
| Watchlist at most 2 per opponent, none for the focus side, known slugs only | `validate-narrative` and `assemble-narrative` |
| The literal strings "digest", "roster shape", "roster_shape", and "verified pool" out of prose | `validate-narrative` |
| Card shape, tier and label enums, programme slug match, schema tags | `assemble-narrative` |
| A research file with a coach object for every programme | `validate-research` |
| Per-programme verified schema, exactly one coach entry, fresher than the digest | `merge-verified` |
| Coach entries carried, never dropped (count invariant) | `validate-verified` |
| Canonical line-per-fact research formatting | The `normalize` node (`normalize-research`), which exits nonzero on any skipped file |
| Insight-filter scores and the major-news bypass | Contract only |
| Identity binding, stopping rules, source grades, precedence, one finding one page | Contract only |
| The three verdicts, W-L-T in prose, shares as people, diction, anti-formula, voice | Contract only |
| Experience ladder, bench lens, toolkit rule, generic-decision test, no self-reference | Contract only |

Two things the renderer fixes in code regardless of prose: `record_line` in
`pipeline/src/report.py` prints every digest record W-L-T, and evidence
labels render through `LABEL_NAMES` ("signal" prints as "Unverified
signal"), with missing narrative sections rendered as explicit placeholders.

## Related

**Run it**

- [Run a scouting report](../../guides/run-a-report/): the workflow that reads these contracts end to end.
- [Build a player profile](../../guides/build-a-player-profile/): the single-player run under the same protocol.
- [Gates and exit codes](../gates-and-exit-codes/): every gate above, with its exit semantics.

**Understand it**

- [Evidence, not recall](../../concepts/evidence-not-recall/): why the protocol reads the way it does.
- [The determinism boundary](../../concepts/the-determinism-boundary/): the numeric wall the figures rule guards.
- [Contracts beat examples](../../design/contracts-not-examples/): the decision record behind tuning in prose contracts.
