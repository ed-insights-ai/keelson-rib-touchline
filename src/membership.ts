// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { packageDir } from "./datahome.ts";

// ─────────────────────────────────────────────────────────────────────────────
// Conference membership is DATA, not code. "GAC men's 2026" resolves to a list
// of programme slugs by reading the authored membership windows. Nothing in
// this rib may hardcode a conference's member list; conferences change, and
// the product is meant to expand beyond the one we started with.
//
// Two copies of membership.json exist, and nothing syncs them. This rib reads
// the copy shipped in its own package (packageDir()/data/reference/
// membership.json). The Python pipeline reads the consumer data home's copy
// (TOUCHLINE_DATA_DIR/data/reference/membership.json, via membership_path()
// in pipeline/src/paths.py) — a file bootstrapDataHome() never seeds. An edit
// to one copy must be propagated to the other by hand, or the two surfaces
// resolve different member lists for the same season.
// ─────────────────────────────────────────────────────────────────────────────

export interface Window {
  conference: string;
  from_season: number;
  to_season: number;
  source: string;
}

export interface MembershipFile {
  conferences: string[];
  memberships: Record<string, Record<string, Window[]>>;
}

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
  for (const [slug, byGender] of Object.entries(file.memberships)) {
    const windows = byGender[gender];
    if (!windows?.length) continue;
    const hit = windows.find((w) => effective >= w.from_season && effective <= w.to_season);
    if (hit && hit.conference.toUpperCase() === wanted) slugs.push(slug);
  }
  slugs.sort();

  return {
    conference: wanted,
    gender,
    season,
    slugs,
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

/** Resolve free text ("the whole GAC", "Harding") to a target set. */
export async function resolveTargets(
  subject: string,
  gender: string,
  season: number,
): Promise<Target> {
  const file = await loadMembership();
  const wanted = normalize(subject);

  // 1. A conference name wins — it is the broader ask, and conference names
  //    are short tokens unlikely to collide with a programme.
  for (const conf of file.conferences) {
    if (conf === "independent" || conf === "non_member") continue;
    if (normalize(conf) === wanted || wanted.includes(normalize(conf))) {
      const res = await resolveConference(conf, gender, season);
      return {
        kind: "conference",
        conference: res.conference,
        slugs: res.slugs,
        extrapolated: res.extrapolated,
        authoredThrough: res.authoredThrough,
      };
    }
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
