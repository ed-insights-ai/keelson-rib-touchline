// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import { packageDir } from "./datahome.ts";

// ─────────────────────────────────────────────────────────────────────────────
// Conference membership is DATA, not code. "GAC men's 2026" resolves to a list
// of programme slugs by reading the authored membership windows. Nothing in
// this rib may hardcode a conference's member list; conferences change, and
// the product is meant to expand beyond the one we started with.
//
// The copy shipped in this package (packageDir()/data/reference/
// membership.json, read here) is the SOURCE OF RECORD: version-controlled and
// reviewed. The consumer data home's copy (TOUCHLINE_DATA_DIR/data/reference/
// membership.json) is a deployment artifact mirrored from it — the Python
// pipeline prefers the packaged copy and falls back to the mirror
// (pipeline/src/membership.py), collect refreshes the mirror at the start of
// every run (pipeline/scripts/collect_board.py, sync_membership_reference),
// and the data-integrity workflow's membership-sync check reports any
// divergence with the exact diff. Edit ONLY the packaged copy.
// ─────────────────────────────────────────────────────────────────────────────

/** One authored window: a programme's conference over an inclusive season
 *  range, with the citation that supports it. `division` is the
 *  conference's own grouping of the programme, spelled as the conference
 *  prints it ("East", "Northwest", "Southwest" for Conference Carolinas
 *  from 2023); optional, and a change of division splits the window the way
 *  a change of conference does. check-membership holds each
 *  conference-season to all-or-none: every member's window carries one or
 *  none does. */
export const membershipWindowSchema = z
  .object({
    conference: z.string().min(1),
    from_season: z.number().int(),
    to_season: z.number().int(),
    source: z.string().min(1),
    division: z.string().min(1).optional(),
  })
  .strict();
export type Window = z.infer<typeof membershipWindowSchema>;

/** Where a conference with no per-season records pages keeps its member
 *  lists: a standings archive addressed by an opaque page id, one id per
 *  season. Evidence for the `source` sentences and for `check-membership
 *  --standings`, not membership itself; the resolver never reads it. */
export const standingsArchiveSchema = z
  .object({
    /** The page URL with `{id}` where the season's id goes. */
    url_template: z.string().min(1),
    /** Season (four digits) to page id. */
    seasons: z.record(z.string().regex(/^\d{4}$/), z.string().min(1)),
  })
  .strict();
export type StandingsArchive = z.infer<typeof standingsArchiveSchema>;

/** The membership reference's contract. It carries no `schema` tag: the file
 *  predates the tagged season files and is authored, not collected. The
 *  sample at contracts/membership.json is the shape both this loader and
 *  pipeline/src/membership.py read. */
export const membershipFileSchema = z
  .object({
    version: z.number().int().optional(),
    /** The authored horizon, inclusive. */
    seasons: z.object({ from: z.number().int(), to: z.number().int() }).strict().optional(),
    conferences: z.array(z.string().min(1)),
    description: z.string().optional(),
    memberships: z.record(z.string(), z.record(z.string(), z.array(membershipWindowSchema))),
    /** Keyed by conference code; optional, and absent for every conference
     *  whose records pages are the evidence. */
    standings_archives: z.record(z.string().min(1), standingsArchiveSchema).optional(),
  })
  .strict();
export type MembershipFile = z.infer<typeof membershipFileSchema>;

let cached: MembershipFile | undefined;

export function membershipPath(): string {
  return join(packageDir(), "data", "reference", "membership.json");
}

export async function loadMembership(): Promise<MembershipFile> {
  if (cached) return cached;
  const text = await readFile(membershipPath(), "utf8");
  const parsed = JSON.parse(text) as MembershipFile;
  if (!parsed?.memberships) throw new Error(`${membershipPath()} has no memberships map`);
  cached = parsed;
  return parsed;
}

/** Reset the cache — tests only. */
export function _resetMembershipCache(): void {
  cached = undefined;
}

/** Set the cache — tests only. */
export function _setMembershipCache(file: MembershipFile): void {
  cached = file;
}

export interface Resolution {
  conference: string;
  gender: string;
  season: number;
  slugs: string[];
  /** Each member's division for the season, by slug, read off the window
   *  that resolved it; a slug is absent when its window names none. Empty
   *  for a conference that publishes one table. */
  divisions: Record<string, string>;
  /** True when `season` is past the last authored window and the most recent
   *  membership had to be carried forward. The caller must surface this: a
   *  carried-forward roster is a well-founded guess, not a cited fact. */
  extrapolated: boolean;
  /** The last season the file authors for THIS conference and gender. */
  authoredThrough: number;
  /** Every conference name the file knows, for a helpful error. */
  known: string[];
}

/** Programme slugs belonging to `conference` for a gender and season.
 *
 *  Windows are inclusive on both ends. For a season beyond the authored range
 *  we carry each programme's LAST window forward and flag the result, rather
 *  than returning an empty list that would read as "this conference does not
 *  exist" — the failure a new user would hit first, asking for the season that
 *  has not started yet. */
export async function resolveConference(
  conference: string,
  gender: string,
  season: number,
): Promise<Resolution> {
  const file = await loadMembership();
  const wanted = conference.trim().toUpperCase();
  const known = [...new Set(file.conferences.map((c) => c))];

  // Scoped to the conference asked about, not the whole file. A global maximum
  // reads one conference's authoring horizon off another's: with the GAC
  // authored through 2025 and a second conference through 2026, a GAC 2026 ask
  // would stop extrapolating, match no window, and resolve to nothing — adding
  // a conference would break the conference already there.
  let authoredThrough = 0;
  for (const byGender of Object.values(file.memberships)) {
    for (const w of byGender[gender] ?? []) {
      if (w.conference.toUpperCase() !== wanted) continue;
      if (w.to_season > authoredThrough) authoredThrough = w.to_season;
    }
  }

  const extrapolated = season > authoredThrough && authoredThrough > 0;
  const effective = extrapolated ? authoredThrough : season;

  const slugs: string[] = [];
  const divisions: Record<string, string> = {};
  for (const [slug, byGender] of Object.entries(file.memberships)) {
    const windows = byGender[gender];
    if (!windows?.length) continue;
    const hit = windows.find((w) => effective >= w.from_season && effective <= w.to_season);
    if (!hit || hit.conference.toUpperCase() !== wanted) continue;
    slugs.push(slug);
    if (hit.division) divisions[slug] = hit.division;
  }
  slugs.sort();

  return {
    conference: wanted,
    gender,
    season,
    slugs,
    divisions,
    extrapolated,
    authoredThrough,
    known,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Turning what a person typed into a target set.
//
// Two shapes, one code path downstream: a CONFERENCE resolves to its members
// for that season, a PROGRAMME resolves to itself. Anything we cannot place is
// reported by name — "I have no recipe for that programme" is a real answer and
// a much better one than collecting the wrong school.
// ─────────────────────────────────────────────────────────────────────────────

export type Target =
  | {
      kind: "conference";
      conference: string;
      slugs: string[];
      extrapolated: boolean;
      authoredThrough: number;
    }
  | {
      kind: "programme";
      conference: string;
      slugs: string[];
      extrapolated: boolean;
      authoredThrough: number;
    }
  | { kind: "unknown"; subject: string; knownConferences: string[]; suggestions: string[] };

function normalize(s: string): string {
  return s
    .toLowerCase()
    .replace(/\b(university|college|state university|the)\b/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Every programme slug the membership record knows for a gender. */
export async function knownProgrammes(gender: string): Promise<string[]> {
  const file = await loadMembership();
  return Object.entries(file.memberships)
    .filter(([, byGender]) => (byGender[gender]?.length ?? 0) > 0)
    .map(([slug]) => slug)
    .sort();
}

/** Every conference the membership record advertises as collectable. */
export async function knownConferences(): Promise<string[]> {
  const file = await loadMembership();
  return file.conferences.filter((c) => c !== "independent" && c !== "non_member");
}

/** The conferences a scheduled collect should sweep for one gender: every
 *  advertised conference that authors at least one membership window in that
 *  gender, sorted. A conference the file knows only through another gender's
 *  windows (or none at all) has no member to collect, so it is left out rather
 *  than sent to the sites to be refused. Nothing here names a conference; a
 *  newly authored one joins the set the day its windows merge. */
export async function activeConferences(gender: string): Promise<string[]> {
  const file = await loadMembership();
  const advertised = new Set(await knownConferences());
  const active = new Set<string>();
  for (const byGender of Object.values(file.memberships)) {
    for (const w of byGender[gender] ?? []) {
      const conference = w.conference.toUpperCase();
      if (advertised.has(conference)) active.add(conference);
    }
  }
  return [...active].sort();
}

/** Resolve free text ("the whole GAC", "Harding") to a target set. */
export async function resolveTargets(
  subject: string,
  gender: string,
  season: number,
): Promise<Target> {
  const file = await loadMembership();
  const wanted = normalize(subject);

  // 1. A conference name wins — it is the broader ask, and conference names
  //    are short tokens unlikely to collide with a programme. The code must
  //    be the whole ask or one of its words: a substring test read "ECC"
  //    and "CCAA" as the CC, whichever code came first in the file
  //    (2026-09-12, two seasons collected into the wrong conference).
  const padded = ` ${wanted} `;
  const conferences = file.conferences.filter(
    (conf) => conf !== "independent" && conf !== "non_member",
  );
  const named =
    conferences.find((conf) => normalize(conf) === wanted) ??
    conferences.find((conf) => padded.includes(` ${normalize(conf)} `));
  if (named) {
    const res = await resolveConference(named, gender, season);
    return {
      kind: "conference",
      conference: res.conference,
      slugs: res.slugs,
      extrapolated: res.extrapolated,
      authoredThrough: res.authoredThrough,
    };
  }

  // 2. A single programme, matched on its slug's normalized form.
  const programmes = await knownProgrammes(gender);
  const exact = programmes.find((slug) => normalize(slug) === wanted);
  const partial =
    exact ??
    programmes.find((slug) => {
      const n = normalize(slug);
      return wanted.length >= 3 && (n.startsWith(wanted) || wanted.startsWith(n));
    });

  if (partial) {
    const windows = file.memberships[partial]?.[gender] ?? [];
    const programmeThrough = windows.reduce((maximum, window) => {
      return Math.max(maximum, window.to_season);
    }, 0);
    const effective = programmeThrough > 0 && season > programmeThrough ? programmeThrough : season;
    const hit = windows.find((w) => effective >= w.from_season && effective <= w.to_season);
    const conference = (hit?.conference ?? "independent").toUpperCase();
    // Read the authoring horizon from the programme's own conference, never a hardcoded one.
    const res = await resolveConference(conference, gender, season);
    return {
      kind: "programme",
      conference,
      slugs: [partial],
      extrapolated: res.extrapolated,
      authoredThrough: res.authoredThrough,
    };
  }

  return {
    kind: "unknown",
    subject,
    knownConferences: await knownConferences(),
    suggestions: programmes,
  };
}

/** The fleet a collect run can grow to, which is what its budget must fit.
 *
 *  collect-board only ever widens a season file's scope: a one-programme ask
 *  against a data home that already holds this conference-season absorbs the
 *  existing programmes rather than discarding their data. So a programme
 *  request may refresh its whole conference, and budgeting for the requested
 *  fleet alone re-creates the killed-mid-run failure this sizing exists to
 *  prevent. The conference's membership is the widening's upper bound. */
export async function collectFleetSize(
  target: Exclude<Target, { kind: "unknown" }>,
  gender: string,
  season: number,
): Promise<number> {
  if (target.kind !== "programme") return target.slugs.length;
  const conference = await resolveConference(target.conference, gender, season);
  return Math.max(target.slugs.length, conference.slugs.length);
}

/** Turn a slug into a display name: `oklahoma-baptist` → `Oklahoma Baptist`.
 *  Collection overwrites this with the programme's own published name; it is
 *  only the honest placeholder for a programme we have not fetched yet. */
export function titleFromSlug(slug: string): string {
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) =>
      part.length <= 2 ? part.toUpperCase() : (part[0] ?? "").toUpperCase() + part.slice(1),
    )
    .join(" ");
}

/** A stable 2–4 letter monogram for a crest tile. Deterministic, so a
 *  programme's mark never changes between renders. */
export function monogram(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return (words[0] ?? "").slice(0, 3).toUpperCase();
  return words
    .slice(0, 3)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase();
}
