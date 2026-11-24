#!/usr/bin/env bun
// Which conferences of one build need a new journal: those whose data was
// collected since their journal was written (data_collected_at differs from
// the season file's collected_at), or that have no journal yet. A collect
// commits only what changed, so an unchanged conference keeps its stamp and
// its journal.
//
//   cd <touchline-ui checkout> && TOUCHLINE_DATA_DIR=… TOUCHLINE_NCAA_DIVISION=… \
//     TOUCHLINE_GENDER=… bun <rib>/site/journal/stale.ts [--only a,b]
//
// Prints one line: this build's journal directory (journal/ or journal/d1,
// under the checkout), a tab, and the keys comma-separated (empty when none).
// --only names the conferences to write whatever their stamps, kept to the
// ones this build follows: a trial, or a rewrite asked for by hand.
//
// Runs inside touchline-ui so its own loader and configuration decide what a
// conference and its season are.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export interface Seasonish {
  key: string;
  file: string;
  collectedAt: string;
}

/** The same instant, however the two files spell it. */
export function sameMoment(a: string, b: string): boolean {
  const x = Date.parse(a);
  const y = Date.parse(b);
  return Number.isNaN(x) || Number.isNaN(y) ? a === b : x === y;
}

export function staleKeys(seasons: readonly Seasonish[], dir: string): string[] {
  const out: string[] = [];
  for (const s of seasons) {
    const path = join(dir, s.file);
    if (!existsSync(path)) {
      out.push(s.key);
      continue;
    }
    let wrote: unknown;
    try {
      wrote = JSON.parse(readFileSync(path, "utf8"))?.data_collected_at;
    } catch {
      out.push(s.key);
      continue;
    }
    if (typeof wrote !== "string" || !sameMoment(wrote, s.collectedAt)) out.push(s.key);
  }
  return out;
}

interface UiSeason {
  key: string;
  collectedAt: string;
  fixtures: { season: number; gender: string };
}

/** --only's keys that this build follows, in the build's own order. */
export function onlyKeys(seasons: readonly Seasonish[], only: string): string[] {
  const asked = new Set(
    only
      .split(",")
      .map((k) => k.trim().toLowerCase())
      .filter(Boolean),
  );
  return seasons.filter((s) => asked.has(s.key)).map((s) => s.key);
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const i = argv.indexOf("--only");
  const only = i >= 0 ? (argv[i + 1] ?? "") : "";
  const ui = process.cwd();
  const { homeSeasons } = await import(join(ui, "src/lib/home.ts"));
  const { journalDir } = await import(join(ui, "src/lib/journal.ts"));
  const dir = journalDir() as string;
  const seasons = (homeSeasons() as UiSeason[]).map((s) => ({
    key: s.key,
    file: `journal-${s.fixtures.season}-${s.fixtures.gender}-${s.key}.json`,
    collectedAt: s.collectedAt,
  }));
  const keys = only.trim() ? onlyKeys(seasons, only) : staleKeys(seasons, dir);
  process.stdout.write(`${dir}\t${keys.join(",")}\n`);
  return 0;
}

if (import.meta.main) process.exit(await main());
