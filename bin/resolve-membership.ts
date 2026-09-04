#!/usr/bin/env bun
// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

// ─────────────────────────────────────────────────────────────────────────────
// The membership resolver as a command line, for the surfaces that cannot
// import src/membership.ts: workflow bash nodes (touchline-collect,
// touchline-backfill) and the daily cadence script. One resolver, three
// callers, so the touchline_collect tool and the workflows share one answer to
// "who is in this conference this season". Nothing here names a conference.
//
//   bun bin/resolve-membership.ts conference <CONF> <gender> <season>
//     prints "<true|false> <slug,slug,...>" (extrapolated flag, then the
//     comma-separated member slugs); exit 1 with a reason on stderr when no
//     member resolves.
//
//   bun bin/resolve-membership.ts conferences <gender>
//     prints the conferences that author at least one membership window for
//     that gender, space-separated on one line, sorted; exit 1 when none do.
//
//   bun bin/resolve-membership.ts divisions <CONF> <gender> <season>
//     prints "<slug>=<division>" pairs, space-separated on one line, sorted
//     by slug, for every member whose window names a division; an empty
//     line for a conference that publishes one table. A separate mode so
//     the conference line keeps its two-token shape for the bash callers.
// ─────────────────────────────────────────────────────────────────────────────

import { activeConferences, knownConferences, resolveConference } from "../src/membership.ts";

const USAGE =
  "usage: resolve-membership.ts conference <CONF> <gender> <season> | conferences <gender> | divisions <CONF> <gender> <season>";

function fail(message: string): never {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

const [mode, ...rest] = process.argv.slice(2);

if (mode === "conference") {
  const [conference, gender, seasonText] = rest;
  if (!conference || !gender || !seasonText) fail(USAGE);
  const season = Number(seasonText);
  if (!/^\d{4}$/.test(seasonText) || !Number.isInteger(season)) {
    fail(`season ${seasonText} is not a four-digit year`);
  }
  const r = await resolveConference(conference, gender, season);
  if (!r.slugs.length) {
    fail(
      `no members resolve for ${r.conference} ${gender} ${season} (known conferences: ${(await knownConferences()).join(", ")})`,
    );
  }
  process.stdout.write(`${r.extrapolated ? "true" : "false"} ${r.slugs.join(",")}\n`);
} else if (mode === "divisions") {
  const [conference, gender, seasonText] = rest;
  if (!conference || !gender || !seasonText) fail(USAGE);
  const season = Number(seasonText);
  if (!/^\d{4}$/.test(seasonText) || !Number.isInteger(season)) {
    fail(`season ${seasonText} is not a four-digit year`);
  }
  const r = await resolveConference(conference, gender, season);
  if (!r.slugs.length) {
    fail(
      `no members resolve for ${r.conference} ${gender} ${season} (known conferences: ${(await knownConferences()).join(", ")})`,
    );
  }
  const pairs = Object.entries(r.divisions)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([slug, division]) => `${slug}=${division}`);
  process.stdout.write(`${pairs.join(" ")}\n`);
} else if (mode === "conferences") {
  const [gender] = rest;
  if (!gender) fail(USAGE);
  const active = await activeConferences(gender);
  if (!active.length) {
    fail(
      `no conference authors a ${gender} membership window (known conferences: ${(await knownConferences()).join(", ")})`,
    );
  }
  process.stdout.write(`${active.join(" ")}\n`);
} else {
  fail(USAGE);
}
