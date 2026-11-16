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
//   bun bin/resolve-membership.ts conferences <gender> [--level d1|d2|d3]
//     prints the conferences that author at least one membership window for
//     that gender, space-separated on one line, sorted; exit 1 when none do.
//     With --level, only the conferences whose profile names that NCAA
//     level; exit 1 when none do, or when a conference carries no profile.
//     Without it the line is exactly what it was before levels existed.
//     With --season <YYYY>, only the conferences at least one programme
//     resolves to that season (carry-forward included); each conference the
//     record authors but that has no member that season is named on stderr
//     ("skipped (no <gender> <season> members): WAC") and left out, never
//     failed. Exit 1 when none is left.
//
//   bun bin/resolve-membership.ts home-level <dir>
//     prints "<level> declared" or "<level> assumed" for the data home at
//     <dir>: the level its touchline-data.yaml states, or d2 for a marker
//     with none (src/datahome.ts says why), with the sentence saying so on
//     stderr. Exit 1 naming the reason when <dir> is not a data home or its
//     marker states a level that is not d1, d2 or d3.
//
//   bun bin/resolve-membership.ts guard <dir> <CONF> [<CONF> ...]
//     refuses (exit 1, one "REFUSED: ..." line per conference on stdout,
//     naming the conference's level and the home's) any conference whose
//     NCAA level is not the data home's, or that has no profile; prints one
//     "level OK: ..." line and exits 0 when every one matches. The check the
//     cadence and the collect/backfill workflows make before any fetch.
//
//   bun bin/resolve-membership.ts divisions <CONF> <gender> <season>
//     prints "<slug>=<division>" pairs, space-separated on one line, sorted
//     by slug, for every member whose window names a division; an empty
//     line for a conference that publishes one table. A separate mode so
//     the conference line keeps its two-token shape for the bash callers.
// ─────────────────────────────────────────────────────────────────────────────

import { homeLevel, levelMismatch, MARKER_FILE, readMarker } from "../src/datahome.ts";
import {
  activeConferences,
  activeConferencesInSeason,
  CONFERENCE_LEVELS,
  type ConferenceLevel,
  conferenceProfile,
  emptyResolutionReason,
  knownConferences,
  resolveConference,
} from "../src/membership.ts";

const USAGE =
  "usage: resolve-membership.ts conference <CONF> <gender> <season> | conferences <gender> [--level d1|d2|d3] [--season YYYY] | divisions <CONF> <gender> <season> | home-level <dir> | guard <dir> <CONF>...";

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
      `no members resolve for ${r.conference} ${gender} ${season}: ${emptyResolutionReason(r)}. Nothing to collect (known conferences: ${(await knownConferences()).join(", ")})`,
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
      `no members resolve for ${r.conference} ${gender} ${season}: ${emptyResolutionReason(r)}. Nothing to collect (known conferences: ${(await knownConferences()).join(", ")})`,
    );
  }
  const pairs = Object.entries(r.divisions)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([slug, division]) => `${slug}=${division}`);
  process.stdout.write(`${pairs.join(" ")}\n`);
} else if (mode === "conferences") {
  // `--level d2` or `--level=d2` (and --season the same), before or after
  // the gender.
  let levelText: string | undefined;
  let seasonText: string | undefined;
  const positional: string[] = [];
  for (let index = 0; index < rest.length; index += 1) {
    const argument = rest[index] ?? "";
    if (argument === "--level") {
      levelText = rest[index + 1] ?? "";
      index += 1;
    } else if (argument.startsWith("--level=")) {
      levelText = argument.slice("--level=".length);
    } else if (argument === "--season") {
      seasonText = rest[index + 1] ?? "";
      index += 1;
    } else if (argument.startsWith("--season=")) {
      seasonText = argument.slice("--season=".length);
    } else if (argument.startsWith("--")) {
      fail(USAGE);
    } else {
      positional.push(argument);
    }
  }
  const [gender] = positional;
  if (!gender || positional.length !== 1) fail(USAGE);
  if (seasonText !== undefined) {
    if (!/^\d{4}$/.test(seasonText)) fail(`season ${seasonText} is not a four-digit year`);
    let level: ConferenceLevel | undefined;
    if (levelText !== undefined) {
      level = CONFERENCE_LEVELS.find((known) => known === levelText?.toLowerCase());
      if (!level) fail(`level '${levelText}' is not one of ${CONFERENCE_LEVELS.join(", ")}`);
    }
    let result: { conferences: string[]; skipped: string[] };
    try {
      result = await activeConferencesInSeason(gender, Number(seasonText), level);
    } catch (error) {
      fail(error instanceof Error ? error.message : String(error));
    }
    if (result.skipped.length) {
      process.stderr.write(
        `skipped (no ${gender} ${seasonText} members): ${result.skipped.join(" ")}\n`,
      );
    }
    if (!result.conferences.length) {
      fail(
        `no ${level ? `${level} ` : ""}conference has a ${gender} member in ${seasonText} (known conferences: ${(await knownConferences()).join(", ")})`,
      );
    }
    process.stdout.write(`${result.conferences.join(" ")}\n`);
  } else if (levelText === undefined) {
    const active = await activeConferences(gender);
    if (!active.length) {
      fail(
        `no conference authors a ${gender} membership window (known conferences: ${(await knownConferences()).join(", ")})`,
      );
    }
    process.stdout.write(`${active.join(" ")}\n`);
  } else {
    const level = CONFERENCE_LEVELS.find((known) => known === levelText.toLowerCase());
    if (!level) {
      fail(`level '${levelText}' is not one of ${CONFERENCE_LEVELS.join(", ")}`);
    }
    let active: string[];
    try {
      active = await activeConferences(gender, level satisfies ConferenceLevel);
    } catch (error) {
      fail(error instanceof Error ? error.message : String(error));
    }
    if (!active.length) {
      fail(
        `no ${level} conference authors a ${gender} membership window (known conferences: ${(await knownConferences()).join(", ")})`,
      );
    }
    process.stdout.write(`${active.join(" ")}\n`);
  }
} else if (mode === "home-level") {
  const [dir] = rest;
  if (!dir || rest.length !== 1) fail(USAGE);
  const marker = await readMarker(dir);
  if (marker.state === "unmarked") fail(`${dir} is not a Touchline data home (no ${MARKER_FILE})`);
  if (marker.state === "foreign")
    fail(`${dir}/${MARKER_FILE} is not a usable marker (${marker.detail})`);
  const level = await homeLevel(dir);
  if (!level) fail(`${dir} is not a Touchline data home`);
  if (level.note) process.stderr.write(`${level.note}\n`);
  process.stdout.write(`${level.level} ${level.declared ? "declared" : "assumed"}\n`);
} else if (mode === "guard") {
  const [dir, ...conferences] = rest;
  if (!dir || !conferences.length) fail(USAGE);
  const marker = await readMarker(dir);
  if (marker.state === "unmarked") {
    process.stdout.write(`REFUSED: ${dir} is not a Touchline data home (no ${MARKER_FILE}).\n`);
    process.exit(1);
  }
  if (marker.state === "foreign") {
    process.stdout.write(
      `REFUSED: ${dir}/${MARKER_FILE} is not a usable marker (${marker.detail}). Nothing was fetched or written.\n`,
    );
    process.exit(1);
  }
  const home = await homeLevel(dir);
  if (!home) fail(`${dir} is not a Touchline data home`);
  const refusals: string[] = [];
  const levels: string[] = [];
  for (const conference of conferences) {
    const profile = await conferenceProfile(conference);
    if (!profile) {
      refusals.push(
        `REFUSED: ${conference.toUpperCase()} has no conference profile in the membership record, so its NCAA level is unknown and it cannot be checked against the data home's ${home.level}. Nothing was fetched or written.`,
      );
      continue;
    }
    const why = levelMismatch(dir, home, conference.toUpperCase(), profile.level);
    if (why) refusals.push(why);
    else levels.push(conference.toUpperCase());
  }
  if (home.note) process.stdout.write(`NOTE: ${home.note}\n`);
  if (refusals.length) {
    process.stdout.write(`${refusals.join("\n")}\n`);
    process.exit(1);
  }
  process.stdout.write(
    `level OK: ${levels.join(" ")} ${levels.length === 1 ? "is" : "are"} ${home.level}, the data home's level (${home.declared ? "declared" : "assumed"}).\n`,
  );
} else {
  fail(USAGE);
}
