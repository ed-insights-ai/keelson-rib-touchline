// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

// ─────────────────────────────────────────────────────────────────────────────
// Season is a DIMENSION, not a constant. What varies by season is which layer a
// collector can serve — so this module plans a collection rather than forbidding
// one, and the collector remains the authority on what actually lands.
//
// Measured against the live sites on 2026-08-09, twice:
//
//   ROSTER    served for every season tried. Harding returned 30 players for
//             2026, 29 for 2022 and 26 for 2019, with zero name overlap between
//             2026 and 2019 and four between 2022 and 2019 — exactly what a
//             four-year career window predicts. Past rosters are real data.
//
//   STATS     served for every season tried, back to 2016 across seven sites
//             (measured 2026-08-10). The cumulative-statistics page is fully
//             server-rendered with an honest per-year title everywhere —
//             including the two sites whose SCHEDULE pages canonicalise the
//             COVID season — so it carries no payload trap at all.
//
//   MATCHES   the box scores behind every played fixture, linked from the
//             schedule page itself (measured 2026-08-10, 63 (site, season)
//             cells back to 2016, COVID 2020 included). Server-rendered and
//             match-specific: the title names the opponent and the exact
//             date, which is the guard's join key — COVID-2020 matches were
//             honestly played and titled in spring 2021.
//
//   SCHEDULE  served for every season tried, back to 2016 across seven sites —
//             but only in the server-rendered DOM. The embedded event payload
//             names the CURRENT season at every season URL, so the first
//             measurement (which read only the payload) concluded past
//             schedules were unreachable. The remeasure with the DOM parser
//             found honest titles, game-id sets fully disjoint from the
//             current season's, and complete W/L results. The collector reads
//             a past season DOM-only and refuses the one dangerous shape — a
//             site that canonicalises a past URL to its current schedule
//             (measured: two sites do this for the COVID 2020 season).
//
// So both layers are attempted for any plausible season, and per-(site,
// season) refusals surface as named gaps in the coverage manifest rather than
// as a plan-time wall.
// ─────────────────────────────────────────────────────────────────────────────

export const TOUCHLINE_LAYERS = ["schedule", "roster", "stats", "matches"] as const;
export type TouchlineLayer = (typeof TOUCHLINE_LAYERS)[number];

/** The season the athletics sites currently publish as "this year".
 *  It gates only the SCHEDULE layer, and it advances once a year. */
export const TOUCHLINE_CURRENT_SEASON = 2026;

/** Kept for the surface copy that still says "the current season". */
export const TOUCHLINE_V1_SEASON = TOUCHLINE_CURRENT_SEASON;

/** How far back a roster request is worth attempting. Below this the sites
 *  predate SideArm's roster component and return nothing useful. */
export const EARLIEST_LIVE_SEASON = 2010;

export interface LayerPlan {
  layer: TouchlineLayer;
  /** Whether to attempt this layer at all for the requested season. */
  attempt: boolean;
  /** Why not, in the user's language. Present only when `attempt` is false. */
  reason?: string;
}

export interface CollectionPlan {
  season: number;
  layers: LayerPlan[];
  /** The layers to actually pass to the collector. */
  attempted: TouchlineLayer[];
  /** True when nothing at all can be attempted for this season. */
  empty: boolean;
}

export function planForSeason(season: number): CollectionPlan {
  const layers: LayerPlan[] = [];

  if (season > TOUCHLINE_CURRENT_SEASON) {
    layers.push({
      layer: "schedule",
      attempt: false,
      reason: `${season} has not been published yet — the sites are still serving ${TOUCHLINE_CURRENT_SEASON}.`,
    });
    layers.push({
      layer: "roster",
      attempt: false,
      reason: `${season} rosters have not been published yet.`,
    });
    layers.push({
      layer: "stats",
      attempt: false,
      reason: `${season} statistics have not been published yet.`,
    });
    layers.push({
      layer: "matches",
      attempt: false,
      reason: `${season} has no played matches to detail yet.`,
    });
  } else if (season < EARLIEST_LIVE_SEASON) {
    for (const layer of TOUCHLINE_LAYERS) {
      layers.push({
        layer,
        attempt: false,
        reason: `${season} predates the published season pages Touchline can read.`,
      });
    }
  } else {
    for (const layer of TOUCHLINE_LAYERS) layers.push({ layer, attempt: true });
  }

  const attempted = layers.filter((p) => p.attempt).map((p) => p.layer);
  return { season, layers, attempted, empty: attempted.length === 0 };
}

/** What to tell someone who asked for a season nothing can serve. */
export function unsupportedSeasonMessage(season: number): string {
  const plan = planForSeason(season);
  const reasons = plan.layers.map((p) => p.reason).filter(Boolean);
  return reasons.length
    ? `Touchline cannot collect ${season}. ${reasons[0]}`
    : `Touchline cannot collect ${season}.`;
}

/** One line naming what this season's collection will and will not include. */
export function planSummary(plan: CollectionPlan): string {
  const yes = plan.layers.filter((p) => p.attempt).map((p) => p.layer);
  const no = plan.layers.filter((p) => !p.attempt);
  const listed =
    yes.length > 2 ? `${yes.slice(0, -1).join(", ")}, and ${yes.at(-1)}` : yes.join(" and ");
  const head = yes.length
    ? `Collecting ${listed} for ${plan.season}.`
    : `Nothing can be collected for ${plan.season}.`;
  return no.length ? `${head} ${no.map((p) => p.reason).join(" ")}` : head;
}
