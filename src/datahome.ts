// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
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

export type MarkerState =
  | { state: "marked"; version: number }
  | { state: "unmarked" }
  | { state: "foreign"; detail: string };

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
  return { state: "marked", version };
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

const MARKER_BODY = [
  "# Marker file: identifies this directory as a Touchline data home.",
  "# The touchline rib validates this file before running workflows here.",
  `kind: ${MARKER_KIND}`,
  "version: 1",
  "",
].join("\n");

const README_BODY = [
  "# Touchline data",
  "",
  "Your soccer data, in an ordinary directory. Collected by the Touchline keelson rib.",
  "Git is not required; Keelson project registration only gives the folder a name and scope.",
  "",
  "| Path | What lives here |",
  "| --- | --- |",
  "| `data/fixtures/` | Published schedules — one JSON file per season and gender. |",
  "| `data/rosters/` | Published rosters — one JSON file per season and gender. |",
  "| `data/stats/` | Published player season statistics — one JSON file per season and gender. |",
  "| `data/matches/` | Published per-match box scores — one JSON file per season and gender. |",
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
}

/** Make a directory into a Touchline data home. Idempotent: an already-marked
 *  home gets its missing subdirectories filled in and nothing overwritten.
 *
 *  Refuses anything that is neither empty nor already ours. `force` exists for
 *  the deliberate "yes, adopt this populated directory" case and must never be
 *  set from an inferred intent — only from an explicit human instruction. */
export async function bootstrapDataHome(
  root: string,
  opts: { force?: boolean } = {},
): Promise<BootstrapResult> {
  const state = await dataHomeState(root);
  if (state.state === "foreign" || state.state === "missing") {
    throw new Error(explainRefusal(root, state) as string);
  }
  if (state.state === "occupied" && !opts.force) {
    throw new Error(explainRefusal(root, state) as string);
  }
  const marker = await readMarker(root);
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
  await writeIfAbsent(MARKER_FILE, MARKER_BODY);
  await writeIfAbsent("README.md", README_BODY);
  return { created, alreadyMarked: marker.state === "marked" };
}

// ─────────────────────────────────────────────────────────────────────────────
// Reading a season. Every failure is reported as a typed reason — a board that
// cannot read its data must say which file and why, never render as empty.
// ─────────────────────────────────────────────────────────────────────────────

export function seasonFileName(season: number, gender: string): string {
  return `${season}-${gender}.json`;
}

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
): Promise<LoadResult<FixturesFile>> {
  const path = join(dataHome(root).fixturesDir, seasonFileName(season, gender));
  return loadJson(path, (raw) => fixturesFileSchema.parse(raw));
}

export function loadRosters(
  root: string,
  season: number,
  gender: string,
): Promise<LoadResult<RostersFile>> {
  const path = join(dataHome(root).rostersDir, seasonFileName(season, gender));
  return loadJson(path, (raw) => rostersFileSchema.parse(raw));
}

export function loadStats(
  root: string,
  season: number,
  gender: string,
): Promise<LoadResult<StatsFile>> {
  const path = join(dataHome(root).statsDir, seasonFileName(season, gender));
  return loadJson(path, (raw) => statsFileSchema.parse(raw));
}

export function loadMatches(
  root: string,
  season: number,
  gender: string,
): Promise<LoadResult<MatchesFile>> {
  const path = join(dataHome(root).matchesDir, seasonFileName(season, gender));
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
  const NAME = /^(\d{4})-(men|women)\.json$/;
  const out: RostersFile[] = [];
  for (const f of files) {
    const m = NAME.exec(f);
    if (!m || m[2] !== gender) continue;
    const loaded = await loadRosters(root, Number(m[1]), gender);
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
  const NAME = /^(\d{4})-(men|women)\.json$/;

  const scan = async (dir: string): Promise<Set<string>> => {
    try {
      const files = await readdir(dir);
      return new Set(files.filter((f) => NAME.test(f)));
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
    const m = NAME.exec(f);
    if (!m) continue;
    const season = Number(m[1]);
    const gender = m[2] as string;
    const hasFixtures = fixtureFiles.has(f);
    const loaded = hasFixtures ? await loadFixtures(root, season, gender) : undefined;
    out.push({
      season,
      gender,
      conference: loaded?.ok ? loaded.value.conference : "unknown",
      hasFixtures,
      hasRosters: rosterFiles.has(f),
    });
  }
  return out.sort((a, b) => b.season - a.season || a.gender.localeCompare(b.gender));
}
