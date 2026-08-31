---
title: Proof before parse
description: A fetched page must prove which season and which match it is before a single value is read, because sports sites answer wrong URLs with confident, well-formed pages.
sidebar:
  order: 3
---

The first question a Touchline collector asks is never "what does this page
say" but "what is this page". The sites it reads are not malicious, just
unhelpfully accommodating: ask a SideArm host for a season it no longer
serves and it will often answer HTTP 200 with a plausible page for a
different season. A parser pointed at an unproven page produces confident,
well-formed, wrong data, which is the worst failure mode a data product has.
So every collector proves a page's provenance first, and refuses loudly, with
a typed error, when it cannot.

## Prove the season

The live collector fetches `{base_url}/{kind}/{year}` through
`fetch_published_page` (`pipeline/src/sidearm_live.py`), which calls
`assert_served_season` before anything reads the page. The assert consults
two witnesses: the year in the final URL path (`_season_in_path`) and the
year in the page title (`_season_in_title`). Every witness that speaks must
name the requested year; when both speak they must agree; and when neither
speaks the page is refused with a `LiveCollectionError` saying it cannot
prove which season was served. Absence of proof is treated as failure, not as
benefit of the doubt.

The nuance is that redirects themselves are innocent. Sites routinely
canonicalise the current season to a bare `/schedule` address, and rejecting
on URL shape alone would refuse the very season that was requested. The guard
encodes "acceptable only when proven": a redirect is fine exactly when the
served page still independently names the requested year.

Historical discovery runs the same defense one layer earlier.
`discover_sidearm_season` (`pipeline/src/sidearm_discovery.py`) harvests
box-score links from a schedule page, and treats a redirect as a defect only
when the season actually served differs from the season requested, or cannot
be determined at all, resolving it from the final path's year segment first
and the title as a fallback. A
`2020-21` slug is season 2020, so only the leading year is compared. Each
harvested link then carries its own embedded season year, which must equal
the requested one. A few mismatches are logged and dropped; if every link is
rejected, the run raises `DiscoveryError` naming the seasons the page
actually served, because a schedule with zero correct-season links is not a
thin season, it is the wrong page.

## The payload trap

SideArm pages publish the schedule twice: as embedded component JSON (the
one-line `var obj = {...};` payloads decoded by `_component_objects`) and as
server-rendered DOM. The JSON is the richer source, with ISO timestamps and
typed results. It is also the lying one: its `schedule.title` names the
current season at every season URL, so at a past-season address the payload
still describes this year's fixtures. The DOM is honest and renders the
season you asked for.

The collector's response is source discipline rather than source averaging.
`parse_schedule_page` keeps a payload event only when its schedule title and
its date both name the requested year, which makes past seasons DOM-only by
construction. One dangerous shape remains: a server that canonicalises a past
URL to the current schedule under an honest-looking wrapper, where the
rendered games and the payload's events are the same games.
`assert_untrapped_schedule` catches exactly that: when the payload does not
name the requested year, any parsed fixture sharing an event id with the
payload betrays the page, and the season is refused. Titles can be
sweet-talked; shared ids cannot. The measurements behind this split between
honest DOM and current-season payload are recorded, with their dates, in the
module docstring of `pipeline/src/sidearm_live.py`.

## Prove the match, not the season

Box scores need a sharper identity proof than "right season".
`assert_served_match` (`pipeline/src/sidearm_live.py`) requires four things
of a fetched box score: the final URL is actually a `/boxscore/` page; the
trailing box-score id equals the one requested, because a redirect that swaps
the id is a different match even when the date matches (a tournament day can
put two same-day matches on one site); the title calls itself a box score;
and the date in the title equals the fixture's own date.

The proof deliberately never compares season years. The COVID-2020 season was
played in spring 2021, and its box scores honestly carry 2021 dates under
season-2020 addresses. A season-year check would refuse every one of them. A
record's identity is its own fields, matched against what was asked for, not
the folder it arrived in.

## Knowing when to stop

The oldest lineage has the subtlest proof problem: knowing that a season has
ended. Legacy StatCrew sites publish games at predictable numbered URLs, so
`discover_season_games` (`pipeline/src/discovery.py`) probes
`{year}/{prefix}-{nn}.htm` sequentially. The stopping rule trusts the body,
not the status code: the probe never checks for a 404 at all, and the first
response under 1000 bytes is read as the end of the season.

A stopping rule invites an ambiguity, and the collector refuses to live with
it. A list truncated by a network error mid-probe would be indistinguishable
from a season that genuinely ended, so `discover_season_games` raises
`DiscoveryError` instead of returning the partial list. An ambiguous truncation must never masquerade as a completed
season; a run that cannot tell the difference fails, and the gap stays
visible.

## Scraper citizenship

Proof protects the data. The same code is equally deliberate about protecting
the source, because a collector that behaves badly loses its access and its
legitimacy together.

- **Transparent identity.** Every session says what it is instead of
  impersonating a browser build: `"Mozilla/5.0 (Educational/Research
  Scraper)"` in `pipeline/src/fetcher.py`, `pipeline/src/discovery.py`, and
  `pipeline/src/sidearm_discovery.py`, and `"Mozilla/5.0 (Touchline
  educational/research collector)"` in `build_session`
  (`pipeline/src/sidearm_live.py`).
- **Politeness paid on the network only.** `GameFetcher.fetch` sleeps half a
  second after each network fetch, and a cache hit pays nothing, so replays
  cost the site nothing at all. The board collector parallelizes across
  hosts, never against one: `HostGate` (`pipeline/src/fetch_pool.py`) caps
  every host at a single in-flight request and spaces consecutive requests
  to the same host 0.2 seconds apart — refused fetches pay too, because the
  spacing is charged per request, not per success.
- **Backoff for outages, not answers.** The discovery and live-collection
  sessions retry with
  `Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])`:
  exponential backoff on server errors only. A 4xx is an answer, and
  retrying an answer is just hammering.
- **TLS verified the way browsers verify.** Some SideArm hosts serve an
  incomplete certificate chain, so certifi-based verification fails even
  though every browser loads the site fine. The wrong fix is `verify=False`.
  Touchline's fix is `TruststoreHTTPAdapter` (`pipeline/src/tls.py`), which
  verifies through the OS trust store; the OS verifier chases the missing
  intermediate via AIA exactly like the browsers these sites target.
  Verification stays enabled everywhere.

Lab: [Read a raw page](../../tutorials/read-a-raw-page/) makes this physical:
you open an archived schedule page and find the payload trap with your own
eyes.

## Related

**Run it**

- [Run a collection](../../guides/run-a-collection/): the command whose
  refusals these guards produce.
- [Onboard a school](../../guides/onboard-a-school/): probing a new site
  read-only before any of it is trusted.

**Understand it**

- [The archive is the system of record](../archive-first/): where a proven
  page lands, and why it is kept verbatim.
- [Reading hostile HTML](../reading-hostile-html/): what parsing does after
  the page has proven itself.
- [Absence is data](../absence-is-data/): how a refused season becomes a
  named gap instead of a silent hole.
