# Player Profile Research Method

How the player-profile workflow's research stage works one player. This file
is the strategy contract — tune the research here, not in workflow YAML. The
caller supplies the parameters (player name, programme, gender, focus year)
and the structured output contract; this file governs *how to look* and
*what counts as evidence*.

## Method, in order

0. **Disambiguate first.** Search the bare name and establish how many
   people share it in this sport. If multiple candidates exist, say so and
   list them; never silently merge two people into one profile. Every later
   finding must attach to THIS player via hometown, school, club, age, or
   photo context.
1. **Anchor on official sources.** The player's athletics bio page, the
   current roster page, and the programme's schedule/news pages — fetched in
   full, not skimmed from search snippets. Official pages set the identity
   spine everything else must match.
2. **Build the timeline backward.** Focus year first, then prior seasons,
   then the pre-college trail: youth clubs, signing announcements, selection
   events, high-school honors, previous colleges, and (for international
   players) federation or Transfermarkt/Soccerway records. Name the
   COMPETITION TIER of what you find — MLS Next, ECNL, a pro or federation
   academy, USL academy, JUCO, NAIA, a lower NCAA division — because the
   tier is the experience signal: an MLS Next or ECNL background marks a
   player proven above standard high-school level, and a JUCO season is
   real minutes against variable competition. A club name without its tier
   is half a finding.
3. **Sweep adjacent competition.** Summer and offseason leagues — USL League
   Two, NPSL, UPSL, The League for Clubs, pro-am circuits — plus all-star or
   selection events and national-team / dual-citizenship angles. Work
   club-first from geography (hometown and campus), fetching squad pages and
   cross-referencing, then bare-name queries; any membership hit triggers an
   immediate player+league honors search (all-conference, Team of the
   Season, Best XI, weekly awards).
4. **Chase the focus year specifically.** Roster status, number, published
   stats, news mentions, and honors dated to the focus year. Search results
   skew toward whichever season has the most published data — without this
   step an August profile is written mostly about last year. If the season
   has not started, say exactly that and report what IS known.

## Rules of evidence

Three verdicts, never blurred — the difference between a scouting document
you can trust and one you cannot:

- **Confirmed** — verified at a URL that was fetched (or that appears
  unambiguously in results) AND identity-matched to this player.
- **Ruled out** — a specific source was checked and the player is absent
  ("not on the FC Dallas U23s published roster").
- **No indexed mention** — the search surface simply cannot see it (private
  or unindexed social accounts, JS-only rosters, 403-blocked pages). This is
  a *finding about coverage*, not evidence of absence — record it in
  `unswept` with the reason.

Further rules:

- Never fill a gap with plausible-sounding inference. An injury-shortened
  season, a missing summer roster, or an unindexed Instagram is itself a
  finding — report it as one.
- A claim believed true but not capturable at a URL goes to
  `attested_uncaptured`, never into findings.
- Confidence tiers: league/club official pages and local news are high; club
  social capturable at a stable URL is medium; a player's own public posts
  are medium and soccer-relevant only — never personal life.
- Note context that changes interpretation: position changes, injuries,
  level of competition, conference strength.
- "Nothing found" per source is a normal result. Report it plainly.
- **Direct public social post URLs are usually fetchable even when search
  cannot find them** — the wall is discovery, not access. A post URL that is
  supplied (by a human at the approval gate) or discovered (on a profile
  page, in a Google snippet, via a site: query) should always be fetched:
  one fetch can upgrade an attested claim to confirmed with a date.
- **When a club publishes no names, read its opponents.** Rival clubs' match
  reports, fan-site coverage (e.g. an academy side's beat coverage), scorer
  lists, and tagged match photos name opposing players a roster-less club
  never will. The league's own news page and weekly-award posts are the
  other side of the same move.
- **Threads profiles render fully to a plain fetch.** For any league or club
  in scope, fetch `threads.com/@<handle>` directly — award posts (Team of
  the Season, Best XI) often live there verbatim, dated, on the league's own
  account. Check Threads BEFORE declaring a social surface unindexed;
  Instagram handles usually map to the same name on Threads.
