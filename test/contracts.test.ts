// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { COVERAGE_SCHEMA, coverageFileSchema } from "../src/coverage.ts";
import { packageDir } from "../src/datahome.ts";
import { membershipFileSchema, membershipPath } from "../src/membership.ts";
import {
  FIXTURES_SCHEMA,
  fixtureStatusSchema,
  fixturesFileSchema,
  MATCHES_SCHEMA,
  matchCardSchema,
  matchesFileSchema,
  ROSTERS_SCHEMA,
  rostersFileSchema,
  STATS_SCHEMA,
  statsFileSchema,
} from "../src/model.ts";
import { PROGRAMMES_SCHEMA, programmesFileSchema, programmesPath } from "../src/programmes.ts";

// The contract fixtures under contracts/ are the samples the site's strict
// schemas test against. This side proves each one parses under the rib's own
// zod contract (the site vendors src/model.ts verbatim), so a fixture the
// pipeline tests admit is also a fixture the site can read. The pipeline
// suite (pipeline/tests/test_contracts.py) proves the writers stay within
// them; together the two close the gap that let `verified: "unchanged"`
// reach the published build unannounced.

const contractsDir = join(packageDir(), "contracts");
const read = (name: string): unknown => JSON.parse(readFileSync(join(contractsDir, name), "utf8"));

const PUBLISHED = [
  ["coverage-1.json", COVERAGE_SCHEMA, coverageFileSchema],
  ["fixtures-2.json", FIXTURES_SCHEMA, fixturesFileSchema],
  ["rosters-1.json", ROSTERS_SCHEMA, rostersFileSchema],
  ["stats-1.json", STATS_SCHEMA, statsFileSchema],
  ["matches-1.json", MATCHES_SCHEMA, matchesFileSchema],
] as const;

describe("every published contract fixture parses under the rib's strict schema", () => {
  for (const [file, tag, schema] of PUBLISHED) {
    test(`${file} is ${tag}`, () => {
      const parsed = schema.parse(read(file));
      expect(parsed.schema).toBe(tag);
    });
  }

  test("programmes-2.json parses, and so does the packaged source of record", () => {
    const fixture = programmesFileSchema.parse(read("programmes-2.json"));
    expect(fixture.schema).toBe(PROGRAMMES_SCHEMA);
    const packaged = programmesFileSchema.parse(JSON.parse(readFileSync(programmesPath(), "utf8")));
    // Every row carries all four facts with a dated provenance each. The
    // point is the Gazetteer's, named by GEOID, except a stanza's own point
    // for a town the Gazetteer covers nowhere (Simon Fraser, Burnaby, B.C.),
    // whose provenance says so in its note instead.
    for (const [slug, row] of Object.entries(packaged.programmes)) {
      const point = row.provenance.point;
      expect(
        point.geoid ?? (point.note?.startsWith("stanza point") ? point.note : undefined),
        slug,
      ).toBeTruthy();
      expect(row.city, slug).toMatch(/, /);
    }
    expect(Object.keys(packaged.programmes).length).toBeGreaterThan(0);
  });

  test("membership.json parses, and so does the packaged source of record", () => {
    const fixture = membershipFileSchema.parse(read("membership.json"));
    const packaged = membershipFileSchema.parse(JSON.parse(readFileSync(membershipPath(), "utf8")));
    expect(fixture.conferences).toEqual(packaged.conferences);
  });

  test("no fixture exists without a schema to read it", () => {
    const named = new Set([
      ...PUBLISHED.map(([file]) => file),
      "membership.json",
      "programmes-2.json",
    ]);
    const onDisk = readdirSync(contractsDir).filter((f) => f.endsWith(".json"));
    expect(new Set(onDisk)).toEqual(named);
  });
});

describe("the fixtures exercise every value the schemas enumerate", () => {
  test("coverage: every state, every layer, and the unchanged marker", () => {
    const file = coverageFileSchema.parse(read("coverage-1.json"));
    const cells = Object.values(file.cells);
    expect(new Set(cells.map((c) => c.state))).toEqual(
      new Set(["complete", "empty", "unavailable", "no-collector"]),
    );
    expect(new Set(cells.map((c) => c.layer))).toEqual(
      new Set(["schedule", "roster", "stats", "matches"]),
    );
    expect(cells.some((c) => c.verified === "unchanged")).toBe(true);
    expect(cells.some((c) => (c.skips?.length ?? 0) > 0)).toBe(true);
  });

  test("fixtures: every status the writer can print", () => {
    const file = fixturesFileSchema.parse(read("fixtures-2.json"));
    expect(new Set(file.fixtures.map((f) => f.status))).toEqual(
      new Set(fixtureStatusSchema.options),
    );
    expect(file.fixtures.some((f) => f.match_type === "exhibition")).toBe(true);
    expect(file.fixtures.some((f) => f.conference_game_source === "derived:membership")).toBe(true);
    expect(file.fixtures.some((f) => f.neutral === true)).toBe(true);
    expect(file.programmes.some((p) => p.abbr === undefined)).toBe(true);
  });

  test("matches: every card type, and a match the page could not orient", () => {
    const file = matchesFileSchema.parse(read("matches-1.json"));
    const details = Object.values(file.matches);
    const types = new Set(details.flatMap((m) => (m.cards ?? []).map((c) => c.type)));
    expect(types).toEqual(new Set(matchCardSchema.shape.type.options));
    expect(details.some((m) => m.home_index === undefined)).toBe(true);
    expect(Object.keys(file.missing ?? {}).length).toBeGreaterThan(0);
  });
});
