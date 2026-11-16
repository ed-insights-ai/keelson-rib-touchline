// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { CONFERENCE_LEVELS, type ConferenceLevel, isConferenceLevel } from "./levels.ts";
import {
  type FixturesFile,
  fixturesFileSchema,
  type MatchesFile,
  matchesFileSchema,
  type RostersFile,
  rostersFileSchema,
  type StatsFile,
  statsFileSchema,
} from "./model.ts";

// ─────────────────────────────────────────────────────────────────────────────
// A Touchline data home is any directory carrying `touchline-data.yaml`. The
// marker is what separates "the user pointed us at their data" from "the user
// pointed us at their home directory"; we never write a data tree into a
// directory that has not been marked, and marking is the one thing bootstrap
// does that cannot be undone by deleting a data file.
// ─────────────────────────────────────────────────────────────────────────────

export const MARKER_FILE = "touchline-data.yaml";
export const MARKER_KIND = "touchline-data";

/** The rib package root — the parent of src/. Resolved from this module's own
 *  location so it works for a symlinked dev install and a copied one alike. */
export function packageDir(): string {
  return resolve(dirname(new URL(import.meta.url).pathname), "..");
}

export interface DataHome {
  root: string;
  fixturesDir: string;
  rostersDir: string;
  statsDir: string;
  matchesDir: string;
}

export function dataHome(root: string): DataHome {
  return {
    root,
    fixturesDir: join(root, "data", "fixtures"),
    rostersDir: join(root, "data", "rosters"),
    statsDir: join(root, "data", "stats"),
    matchesDir: join(root, "data", "matches"),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// A data home collects ONE NCAA level. The marker may say which:
//
//   kind: touchline-data
//   version: 1
//   level: d1
//
// `level` is optional because every home made before levels existed carries
// none, and every one of those is Division II: until the Division I men's
// conferences were onboarded the membership record held Division II
// conferences only, so nothing any rib could collect into such a home was at
// another level. That is the one place the default is provably what the home
// means, so an absent level reads as d2 (UNDECLARED_HOME_LEVEL) — and never
// silently: `homeLevel` returns `declared: false`, and every reader that acts
// on the level (the collect guard, the cadence, the workflow preflights,
// touchline_status, the Python collector's own guard) says it assumed d2 and
// how to declare it. A level the marker states but that is not d1/d2/d3 is a
// broken marker and refuses like a foreign one: guessing past a typo is how a
// home ends up collecting the wrong level.
// ─────────────────────────────────────────────────────────────────────────────

/** What a marker with no `level` line means. See the block above for why d2
 *  and only d2 is provable. */
export const UNDECLARED_HOME_LEVEL: ConferenceLevel = "d2";

export type MarkerState =
  | { state: "marked"; version: number; level?: ConferenceLevel }
  | { state: "unmarked" }
  | { state: "foreign"; detail: string };

/** What a marker's text says about its level: no `level` line at all (the
 *  legacy default applies), a valid declaration, or a line the reader
 *  cannot use (refused, never defaulted past). */
export type MarkerLevelText =
  | { state: "absent" }
  | { state: "declared"; level: ConferenceLevel }
  | { state: "invalid"; detail: string };

/** Read the `level` key of a marker's text. The rule pipeline/src/paths.py
 *  `marker_level` holds, checked against the same vectors
 *  (pipeline/tests/fixtures/marker_levels.json): the key is found apart from
 *  its value; an inline comment is stripped (`level: d1 # Division I` is
 *  d1); one pair of matching quotes is unwrapped; the case is folded. What
 *  remains must be exactly d1, d2 or d3: an empty value, two words
 *  (`level: d4 extra`) or the key stated twice is invalid. Only a marker
 *  with no `level` line is absent. */
export function markerLevel(text: string): MarkerLevelText {
  const found = [...text.replace(/\r\n/g, "\n").matchAll(/^[ \t]*level[ \t]*:(.*)$/gm)];
  if (found.length === 0) return { state: "absent" };
  if (found.length > 1) {
    return {
      state: "invalid",
      detail: `level is stated ${found.length} times; a marker declares one level`,
    };
  }
  const raw = found[0]?.[1] ?? "";
  let value = raw.replace(/(?:^|[ \t])#.*$/, "").trim();
  const quote = value[0];
  if (value.length >= 2 && (quote === "'" || quote === '"') && value.endsWith(quote)) {
    value = value.slice(1, -1).trim();
  }
  const level = value.toLowerCase();
  if (!isConferenceLevel(level)) {
    return {
      state: "invalid",
      detail: `level: ${raw.trim() || "(empty)"} is not one of ${CONFERENCE_LEVELS.join(", ")}`,
    };
  }
  return { state: "declared", level };
}

/** Read the marker without throwing. `unmarked` means "empty or not ours yet";
 *  `foreign` means a file of that name exists but is not a Touchline marker,
 *  which is a refuse-to-touch condition rather than a scaffold opportunity. */
export async function readMarker(root: string): Promise<MarkerState> {
  let text: string;
  try {
    text = await readFile(join(root, MARKER_FILE), "utf8");
  } catch {
    return { state: "unmarked" };
  }
  const kind = /^\s*kind:\s*(\S+)\s*$/m.exec(text)?.[1];
  if (kind !== MARKER_KIND) {
    return { state: "foreign", detail: `kind: ${kind ?? "(absent)"}` };
  }
  const version = Number(/^\s*version:\s*(\d+)\s*$/m.exec(text)?.[1] ?? "1");
  const level = markerLevel(text);
  if (level.state === "absent") return { state: "marked", version };
  if (level.state === "invalid") return { state: "foreign", detail: level.detail };
  return { state: "marked", version, level: level.level };
}

/** The NCAA level a data home collects at. `declared` is false when the
 *  marker carries no level and `level` is the d2 every pre-level home is;
 *  `note` is then the sentence a reader must surface rather than swallow. */
export interface HomeLevel {
  level: ConferenceLevel;
  declared: boolean;
  note?: string;
}

export function undeclaredLevelNote(root: string): string {
  return `${root}/${MARKER_FILE} declares no level, so it is read as ${UNDECLARED_HOME_LEVEL}: every data home made before levels existed is Division II. Add the line "level: ${UNDECLARED_HOME_LEVEL}" to the marker to declare it.`;
}

/** The level of a marked home; undefined for anything that is not one. */
export async function homeLevel(root: string): Promise<HomeLevel | undefined> {
  const marker = await readMarker(root);
  if (marker.state !== "marked") return undefined;
  if (marker.level) return { level: marker.level, declared: true };
  return { level: UNDECLARED_HOME_LEVEL, declared: false, note: undeclaredLevelNote(root) };
}

/** Why a collect of a `conferenceLevel` conference into a `home` must be
 *  refused, or undefined when the levels agree. Names both levels: this is
 *  the guard that keeps Division I data out of a Division II home after a
 *  slip of the project picker. */
export function levelMismatch(
  root: string,
  home: HomeLevel,
  conference: string,
  conferenceLevel: ConferenceLevel,
): string | undefined {
  if (home.level === conferenceLevel) return undefined;
  return `REFUSED: ${conference} is a ${conferenceLevel} conference and the data home ${root} collects ${home.level} (${
    home.declared ? "declared in its marker" : "assumed: its marker declares no level"
  }). A home holds one NCAA level; collect ${conference} into a ${conferenceLevel} home instead. Nothing was fetched or written.`;
}

/** True when the directory holds nothing but VCS/OS bookkeeping — the
 *  "brand new empty folder" the first-contact story starts from. */
export async function isEffectivelyEmpty(root: string): Promise<boolean> {
  let entries: string[];
  try {
    entries = await readdir(root);
  } catch {
    return false;
  }
  const ignorable = new Set([".git", ".DS_Store", ".gitignore", ".gitkeep", "README.md"]);
  return entries.every((e) => ignorable.has(e));
}

/** What a directory is, as far as Touchline is concerned.
 *
 *  The `occupied` case is the one that matters: a directory holding somebody
 *  else's work is NOT a place to scaffold a data tree, even though it carries
 *  no conflicting marker. Without this check the rib would happily write
 *  data/ and a marker into a source directory the user merely had selected
 *  in the project picker. Refusing is the whole point — a collection target
 *  must be a folder we created or one a previous run already claimed. */
export type HomeState =
  | { state: "ready"; version: number }
  | { state: "empty" }
  | { state: "occupied"; entries: string[] }
  | { state: "foreign"; detail: string }
  | { state: "missing" };

export async function dataHomeState(root: string): Promise<HomeState> {
  const marker = await readMarker(root);
  if (marker.state === "foreign") return { state: "foreign", detail: marker.detail };
  if (marker.state === "marked") return { state: "ready", version: marker.version };

  let entries: string[];
  try {
    entries = await readdir(root);
  } catch {
    return { state: "missing" };
  }
  const ignorable = new Set([".git", ".DS_Store", ".gitignore", ".gitkeep", "README.md"]);
  const notable = entries.filter((e) => !ignorable.has(e));
  if (notable.length === 0) return { state: "empty" };
  return { state: "occupied", entries: notable.slice(0, 8) };
}

/** One sentence a human can act on, for each refusing state. */
export function explainRefusal(root: string, state: HomeState): string | undefined {
  switch (state.state) {
    case "occupied":
      return `${root} already holds other work (${state.entries.join(", ")}${
        state.entries.length >= 8 ? ", …" : ""
      }). Touchline only collects into an empty folder or one it has already initialized, so it will not scaffold here. Point it at a new folder, or initialize this one deliberately if it really is meant to be a data home.`;
    case "foreign":
      return `${root} has a ${MARKER_FILE} that is not a Touchline marker (${state.detail}). Refusing to scaffold over it.`;
    case "missing":
      return `${root} does not exist or cannot be read.`;
    default:
      return undefined;
  }
}

function markerBody(level: ConferenceLevel): string {
  return [
    "# Marker file: identifies this directory as a Touchline data home.",
    "# The touchline rib validates this file before running workflows here.",
    "# level: the one NCAA level this home collects (d1, d2 or d3); a collect",
    "# of a conference at any other level is refused.",
    `kind: ${MARKER_KIND}`,
    "version: 1",
    `level: ${level}`,
    "",
  ].join("\n");
}

const README_BODY = [
  "# Touchline data",
  "",
  "Your soccer data, in an ordinary directory. Collected by the Touchline keelson rib.",
  "Git is not required; Keelson project registration only gives the folder a name and scope.",
  "",
  "| Path | What lives here |",
  "| --- | --- |",
  "| `data/fixtures/` | Published schedules — one JSON file per season, gender, and conference. |",
  "| `data/rosters/` | Published rosters — one JSON file per season, gender, and conference. |",
  "| `data/stats/` | Published player season statistics — one JSON file per season, gender, and conference. |",
  "| `data/matches/` | Published per-match box scores — one JSON file per season, gender, and conference. |",
  "| `data/raw_html/` | The pages exactly as fetched, so any parse can be redone offline. |",
  "| `data/errors/` | Anything a collection run could not parse, kept rather than dropped. |",
  "",
  "The schedule and roster files are the complete Touchline v1 deliverable.",
  "Nothing here requires Git or a database.",
  "",
].join("\n");

export interface BootstrapResult {
  created: string[];
  alreadyMarked: boolean;
  /** The home's level after bootstrap, and whether its marker states it. */
  level: HomeLevel;
  /** True when this call added a `level:` line to an existing marker. */
  levelWritten: boolean;
}

/** Make a directory into a Touchline data home. Idempotent: an already-marked
 *  home gets its missing subdirectories filled in and nothing overwritten.
 *
 *  A new marker always states its level: `opts.level`, else d2 (the caller
 *  reports which). An existing marker with no level gets `opts.level`
 *  appended when one is passed — declaring what the home is, never changing
 *  it, so only d2, the level such a home already is — and an existing marker
 *  whose effective level (stated, or the undeclared d2) DIFFERS is refused:
 *  a home's level is what its data is, and relabelling it would not move a
 *  single file.
 *
 *  Refuses anything that is neither empty nor already ours. `force` exists for
 *  the deliberate "yes, adopt this populated directory" case and must never be
 *  set from an inferred intent — only from an explicit human instruction. */
export async function bootstrapDataHome(
  root: string,
  opts: { force?: boolean; level?: ConferenceLevel } = {},
): Promise<BootstrapResult> {
  const state = await dataHomeState(root);
  if (state.state === "foreign" || state.state === "missing") {
    throw new Error(explainRefusal(root, state) as string);
  }
  if (state.state === "occupied" && !opts.force) {
    throw new Error(explainRefusal(root, state) as string);
  }
  const marker = await readMarker(root);
  // The existing level is the EFFECTIVE one: a marker with no level line is
  // already a d2 home (UNDECLARED_HOME_LEVEL; its data is Division II), so it
  // can only be declared d2. Appending another level would relabel its
  // Division II files and let the guards admit that level beside them.
  const existing = marker.state === "marked" ? (marker.level ?? UNDECLARED_HOME_LEVEL) : undefined;
  if (existing && opts.level && existing !== opts.level) {
    throw new Error(
      marker.state === "marked" && marker.level
        ? `${root} is already a ${existing} data home (its ${MARKER_FILE} says level: ${existing}); it cannot become a ${opts.level} home. Create a separate home for ${opts.level}.`
        : `${root} is already a ${existing} data home: its ${MARKER_FILE} declares no level, and a home made before levels existed is Division II, so it can only be declared ${existing}. It cannot become a ${opts.level} home. Create a separate home for ${opts.level}.`,
    );
  }
  let levelWritten = false;
  if (marker.state === "marked" && !marker.level && opts.level) {
    const path = join(root, MARKER_FILE);
    const text = await readFile(path, "utf8");
    await writeFile(
      path,
      `${text}${text.endsWith("\n") ? "" : "\n"}level: ${opts.level}\n`,
      "utf8",
    );
    levelWritten = true;
  }
  const created: string[] = [];
  const home = dataHome(root);
  for (const dir of [
    home.fixturesDir,
    home.rostersDir,
    home.statsDir,
    home.matchesDir,
    join(root, "data", "raw_html"),
    join(root, "data", "errors"),
    join(root, "data", "reference"),
  ]) {
    await mkdir(dir, { recursive: true });
    created.push(dir.slice(root.length + 1));
  }
  const writeIfAbsent = async (rel: string, body: string) => {
    const path = join(root, rel);
    try {
      await readFile(path, "utf8");
    } catch {
      await writeFile(path, body, "utf8");
      created.push(rel);
    }
  };
  await writeIfAbsent(MARKER_FILE, markerBody(opts.level ?? UNDECLARED_HOME_LEVEL));
  await writeIfAbsent("README.md", README_BODY);
  const level = await homeLevel(root);
  if (!level) throw new Error(`${root} carries no readable ${MARKER_FILE} after bootstrap.`);
  return { created, alreadyMarked: marker.state === "marked", level, levelWritten };
}

// ─────────────────────────────────────────────────────────────────────────────
// Reading a season. Every failure is reported as a typed reason — a board that
// cannot read its data must say which file and why, never render as empty.
// ─────────────────────────────────────────────────────────────────────────────

export function conferenceSlug(conference: string): string {
  const slug = conference
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!slug) throw new Error("Conference must contain at least one letter or number.");
  return slug;
}

export function seasonFileName(season: number, gender: string, conference: string): string {
  return `${season}-${gender}-${conferenceSlug(conference)}.json`;
}

const SEASON_FILE_NAME = /^(\d{4})-(men|women)-([a-z0-9-]+)\.json$/;

export type LoadResult<T> =
  | { ok: true; value: T }
  | { ok: false; reason: "absent"; path: string }
  | { ok: false; reason: "unreadable" | "invalid"; path: string; detail: string };

async function loadJson<T>(path: string, parse: (raw: unknown) => T): Promise<LoadResult<T>> {
  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code === "ENOENT") return { ok: false, reason: "absent", path };
    return { ok: false, reason: "unreadable", path, detail: String(err) };
  }
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    return { ok: false, reason: "invalid", path, detail: `not JSON: ${String(err)}` };
  }
  try {
    return { ok: true, value: parse(raw) };
  } catch (err) {
    return { ok: false, reason: "invalid", path, detail: String(err) };
  }
}

export function loadFixtures(
  root: string,
  season: number,
  gender: string,
  conference: string,
): Promise<LoadResult<FixturesFile>> {
  const path = join(dataHome(root).fixturesDir, seasonFileName(season, gender, conference));
  return loadJson(path, (raw) => fixturesFileSchema.parse(raw));
}

export function loadRosters(
  root: string,
  season: number,
  gender: string,
  conference: string,
): Promise<LoadResult<RostersFile>> {
  const path = join(dataHome(root).rostersDir, seasonFileName(season, gender, conference));
  return loadJson(path, (raw) => rostersFileSchema.parse(raw));
}

export function loadStats(
  root: string,
  season: number,
  gender: string,
  conference: string,
): Promise<LoadResult<StatsFile>> {
  const path = join(dataHome(root).statsDir, seasonFileName(season, gender, conference));
  return loadJson(path, (raw) => statsFileSchema.parse(raw));
}

export function loadMatches(
  root: string,
  season: number,
  gender: string,
  conference: string,
): Promise<LoadResult<MatchesFile>> {
  const path = join(dataHome(root).matchesDir, seasonFileName(season, gender, conference));
  return loadJson(path, (raw) => matchesFileSchema.parse(raw));
}

/** Every readable roster file for a gender, oldest season first — the archive
 *  the board's tenure lines are computed from. Tenure is enrichment: a corrupt
 *  or missing archive season narrows a player's visible history rather than
 *  failing the current board, so unreadable files are skipped, not raised. */
export async function loadRosterHistory(root: string, gender: string): Promise<RostersFile[]> {
  const home = dataHome(root);
  let files: string[];
  try {
    files = await readdir(home.rostersDir);
  } catch {
    return [];
  }
  const out: RostersFile[] = [];
  for (const f of files) {
    const m = SEASON_FILE_NAME.exec(f);
    if (!m || m[2] !== gender) continue;
    const loaded = await loadRosters(root, Number(m[1]), gender, m[3] as string);
    if (loaded.ok) out.push(loaded.value);
  }
  return out.sort((a, b) => a.season - b.season);
}

export interface SeasonRef {
  season: number;
  gender: string;
  conference: string;
  /** Which layers actually landed. A past season commonly has a roster and no
   *  schedule, because each programme serves its CURRENT fixtures at every
   *  season address — so a season keyed on fixtures alone would hide it. */
  hasFixtures: boolean;
  hasRosters: boolean;
}

/** Every season present in the data home, newest first. Drives the board's
 *  default selection and the "what do I have?" answer in chat. */
export async function listSeasons(root: string): Promise<SeasonRef[]> {
  const home = dataHome(root);

  const scan = async (dir: string): Promise<Set<string>> => {
    try {
      const files = await readdir(dir);
      return new Set(files.filter((f) => SEASON_FILE_NAME.test(f)));
    } catch {
      return new Set();
    }
  };

  const [fixtureFiles, rosterFiles] = await Promise.all([
    scan(home.fixturesDir),
    scan(home.rostersDir),
  ]);

  const out: SeasonRef[] = [];
  for (const f of new Set([...fixtureFiles, ...rosterFiles])) {
    const m = SEASON_FILE_NAME.exec(f);
    if (!m) continue;
    const season = Number(m[1]);
    const gender = m[2] as string;
    const conference = m[3] as string;
    const hasFixtures = fixtureFiles.has(f);
    out.push({
      season,
      gender,
      conference,
      hasFixtures,
      hasRosters: rosterFiles.has(f),
    });
  }
  return out.sort(
    (a, b) =>
      b.season - a.season ||
      a.gender.localeCompare(b.gender) ||
      a.conference.localeCompare(b.conference),
  );
}
