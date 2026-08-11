# Player Profile Research Method

How the player-profile workflow's research stage researches one player.
This file is the strategy contract — tune the research here, not in
workflow YAML. The caller supplies the parameters (player name, programme,
gender, focus year) and the structured output contract; this file governs
*how to look* and *what counts as evidence*. Identity binding, source
confidence, gender-correct league lists, stopping rules, and platform
techniques live in `research-protocol.md` and apply throughout.

## Method, in order

0. **Disambiguate first.** Search the bare name and establish how many
   people share it in this sport. If multiple candidates exist, say so and
   list them; never silently merge two people into one profile. Every
   later finding must bind to THIS player per the protocol's identity
   rules (school, hometown, club, age or class year, jersey, or a photo
   caption or tag naming them — never a face that looks right).
1. **Anchor on official sources.** The player's athletics bio page, the
   current roster page, and the programme's schedule/news pages — fetched
   in full, not skimmed from search snippets. Official pages set the
   identity spine everything else must match.
2. **Build the timeline backward.** Focus year first, then prior seasons,
   then the pre-college trail: youth clubs, signing announcements,
   selection events, high-school honors, previous colleges, and (for
   international players) federation records — crowd-sourced databases
   are lead generation only, per the protocol. Name the COMPETITION TIER
   of what you find and place it on the style contract's experience
   ladder — the contract is canonical, so read the rungs there rather
   than from memory. A club name without its tier is half a finding.
   The protocol's stopping rules decide when the trail ends.
3. **Sweep adjacent competition.** Summer and offseason leagues from the
   protocol's gender-correct list, plus all-star or selection events and
   national-team / dual-citizenship angles. Work club-first from
   geography, then bare-name, with the protocol's honors follow-up and
   stopping rules.
4. **Chase the focus year specifically.** Roster status, number, published
   stats, news mentions, and honors dated to the focus year. Search
   results skew toward whichever season has the most published data —
   without this step an August profile is written mostly about last year.
   Say precisely where the focus season stands as of the run date: "no
   matches played yet as of <date>" and "matches played but no statistics
   published as of <date>" are different findings, and the profile states
   which one it found.

## Rules of evidence

Three verdicts, never blurred — the difference between a scouting document
you can trust and one you cannot:

- **Confirmed** — verified at a URL that was FETCHED and identity-bound to
  this player. A claim seen only in a search snippet is never confirmed:
  fetch the page, or the claim goes to `attested_uncaptured`.
- **Ruled out** — a specific source was checked and the player is absent
  ("not on the FC Dallas U23s published roster"). This is the strong form
  of absence: the page was read and the name is not there.
- **No indexed mention** — the search surface simply cannot see it
  (private or unindexed social accounts, JS-only rosters, 403-blocked
  pages). This is a *finding about coverage*, not evidence of absence —
  record it in `unswept` with the reason.

Downstream, the distinction carries: when a participation gap is narrated
in a report it wears the "Unverified signal — requires confirmation"
label either way, but a gap backed by ruled-out checks is a stronger
signal than one sitting on unswept coverage, and the research file must
make clear which the reader has.

Further rules:

- Never fill a gap with plausible-sounding inference. An injury-shortened
  season, a missing summer roster, or an unindexed Instagram is itself a
  finding — report it as one.
- A claim believed true but not capturable at a fetched URL goes to
  `attested_uncaptured` — and that bucket is a dead end for report
  content, surfaced only in run summaries (see the protocol).
- Verdicts and confidence tiers are orthogonal, per the protocol: a
  fetched player self-post yields confirmed-at-medium; the tier never
  rises by being fetched.
- Note context that changes interpretation: position changes, injuries
  (from official or press sources only), level of competition, conference
  strength. When sources conflict, apply the protocol's precedence and
  record the split.
- "Nothing found" per source is a normal result. Report it plainly.
