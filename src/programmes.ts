// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

// The programmes reference: identity per programme slug, with provenance.
//
// Contract touchline.programmes/2 (contracts/programmes-2.json). Built in the
// rib from pipeline/config/schools.toml and the pinned 2023 Census Gazetteer
// by `uv run build-programmes`, mirrored into the data home by collect beside
// membership.json. The site vendors this schema and reads the mirrored file;
// a programme it follows with no row is a build failure there, never a guess.

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import { packageDir } from "./datahome.ts";

export const PROGRAMMES_SCHEMA = "touchline.programmes/2";

/** Where one fact came from and when it was read. */
export const provenanceSchema = z
  .object({
    source: z.string().min(1),
    url: z.string().min(1).optional(),
    /** ISO date the source was read. */
    accessed: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    /** Gazetteer only: the place the point resolved to. */
    geoid: z.string().min(1).optional(),
    name: z.string().min(1).optional(),
    state: z.string().length(2).optional(),
    note: z.string().min(1).optional(),
  })
  .strict();

export const programmeRowSchema = z
  .object({
    /** The reader-facing programme name. */
    name: z.string().min(1),
    nickname: z.string().min(1),
    /** The programme's own short form — the monogram. */
    abbreviation: z.string().min(1),
    /** AP state style, as the contract normalises it: "Searcy, Ark." */
    city: z.string().min(1),
    /** The town centroid the programme plays in — never the campus. */
    point: z.object({ lat: z.number(), lon: z.number() }).strict(),
    provenance: z
      .object({
        nickname: provenanceSchema,
        abbreviation: provenanceSchema,
        city: provenanceSchema,
        point: provenanceSchema,
      })
      .strict(),
  })
  .strict();
export type ProgrammeRow = z.infer<typeof programmeRowSchema>;

export const programmesFileSchema = z
  .object({
    schema: z.literal(PROGRAMMES_SCHEMA),
    description: z.string().optional(),
    gazetteer: z
      .object({
        source: z.string().min(1),
        url: z.string().min(1),
        file_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        license: z.string().min(1),
      })
      .strict(),
    programmes: z.record(z.string(), programmeRowSchema),
  })
  .strict();
export type ProgrammesFile = z.infer<typeof programmesFileSchema>;

/** The packaged source of record, built and reviewed in the rib. */
export function programmesPath(): string {
  return join(packageDir(), "data", "reference", "programmes.json");
}

let cached: ProgrammesFile | undefined;

export async function loadProgrammes(): Promise<ProgrammesFile> {
  if (!cached) {
    cached = programmesFileSchema.parse(JSON.parse(await readFile(programmesPath(), "utf8")));
  }
  return cached;
}
