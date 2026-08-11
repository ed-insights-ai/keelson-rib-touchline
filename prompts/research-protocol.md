# Research Protocol

How offseason findings are retrieved, identity-bound, and graded — for
every research stage (report research loop and player profiles alike).
`scouting-questionnaire.md` says what the report must answer;
`style-contract.md` says how it must read; this file says how to look.
State it once here; the other files reference it.

## The sweep, per programme

1. **Club-first.** From player hometowns and the campus location, list
   plausible summer clubs in the gender-correct competitions and fetch
   each club's roster or squad page, cross-referencing names.
   - Men: USL League Two, NPSL, UPSL, pro-am circuits.
   - Women: USL W League, WPSL, UPSL (women's divisions).
   - "The League for Clubs" appears in older sweeps: confirm it still
     operates under that name and covers the region before treating a
     null result there as meaningful.
2. **Bare-name.** For each distinctive name, search the plain name alone —
   league award posts and social announcements surface there when
   structured queries miss. Every bare-name hit must pass identity
   binding before it becomes a finding.
3. **Honors follow-up.** Any membership hit triggers an immediate
   player+league honors search (all-conference, Team of the Season,
   Best XI, weekly awards).
4. **Special interest.** Players carrying availability or usage signals
   get bare name + hometown; summer activity for a player with a
   participation hole is the highest-value finding.
5. **Programme-level news.** Head-coach status (mandatory, recorded
   either way), preseason polls, signing-class announcements.

## Stopping rules

Effort is budgeted, not open-ended. Stop the club-first sweep for an
anchor geography after five consecutive clubs with no roster match. Stop
any query line when two consecutive query variants add nothing new.
Record what was not swept — and why — in `unswept` rather than searching
indefinitely.

## Identity binding (the false-positive rule)

A name match alone is never a finding — "discoverable but wrong" is the
pipeline's highest risk. Bind every hit to the player through at least
one corroborating attribute: school, hometown, club, age or class year,
jersey number, or a photo **caption or tag** naming them (a face that
looks right is not evidence). Recency matters: an identity anchor on a
current or recent page is strong; a hometown match on a five-year-old
roster cannot by itself confirm a current-season claim. A hit that
cannot be bound is dropped or recorded as `attested_uncaptured` — never
stretched.

## Source confidence and dating

- High: league or club official pages, federation records, local news.
- Medium: club social posts capturable at a stable URL; a player's own
  public posts, scoped strictly to on-field activity and publicly
  announced athletic status (a transfer announcement, a call-up).
  Health information is never sourced from personal accounts — injury
  status comes from official or press sources or stays unwritten.
- Lead generation only, never confirmation: Transfermarkt, Soccerway,
  and other crowd-sourced databases. Use them to find trails, then
  verify at an official or press source. Their youth and lower-tier US
  coverage is thin, so a null result there means little.
- **An undated source cannot date a claim.** A social post or squad
  listing with no timestamp cannot establish a current-season fact.
- Verdict and confidence are orthogonal: fetching a player's own post
  can raise a claim to *confirmed at medium confidence* — the fetch
  settles that the source says it; the tier still says what kind of
  source it is, and never rises by being fetched.

## Conflicting sources

When official pages disagree (class year, hometown, position), the most
recent programme-published page wins, then conference pages, then older
official pages, then press. Record the disagreement as a finding note —
a coach reading two class years deserves to know the record splits.

## One finding, one page

Never write a finding whose truth needs two pages to check — the
verifier fetches each finding's single URL and drops any claim that
page alone cannot support. Split compound claims (a coaching change is
one finding per page: current directory, appointment bio, prior-year
directory), and when a single page states the whole fact, prefer it.

## Platform techniques (try them; failures are unswept, not errors)

- **Direct public post URLs are often fetchable even when search cannot
  find them** — the wall is usually discovery, not access. A post URL
  supplied by a human or discovered on a profile page is worth one
  fetch. If the fetch fails, record the surface in `unswept`.
- **Threads often renders to a plain fetch** (`threads.com/@<handle>`),
  and league award posts sometimes live there dated on the league's own
  account. Try it before declaring a social surface unindexed — but
  treat it as a technique with an expected failure mode: logged-out
  access changes, and an Instagram handle maps to Threads only for
  accounts created that way.
- **When a club publishes no names, read its opponents.** Rival clubs'
  match reports, fan coverage, scorer lists, and tagged match photos
  name opposing players a roster-less club never will; the league's own
  news page and weekly-award posts are the other side of the same move.

## The dead-end bucket

`attested_uncaptured` is a dead end for report content: claims there
never reach the report in any form — not as fact, not as a hedge, not
as an uncertainty. They surface only in the run summary, for a human to
capture or discard. Downstream stages must not treat the bucket as soft
evidence.
