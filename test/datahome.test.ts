// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { homeLevel, MARKER_FILE, markerLevel, packageDir, readMarker } from "../src/datahome.ts";
import type { ConferenceLevel } from "../src/levels.ts";

// One set of vectors for every marker reader: src/datahome.ts here, the
// shell surfaces through bin/resolve-membership.ts home-level (the cadence and
// the workflow guards read the marker only through it), and
// pipeline/src/paths.py (pipeline/tests/test_paths.py reads the same file).
const pkg = packageDir();
const resolver = join(pkg, "bin", "resolve-membership.ts");
const { vectors } = JSON.parse(
  await readFile(join(pkg, "pipeline", "tests", "fixtures", "marker_levels.json"), "utf8"),
) as { vectors: { name: string; text: string; expect: string }[] };

async function run(cmd: string[]) {
  const proc = Bun.spawn(cmd, { stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  return { code: await proc.exited, stdout, stderr };
}

describe("the marker's level line (shared vectors)", () => {
  test("the vectors cover absent, declared and invalid", () => {
    const kinds = new Set(vectors.map((v) => (v.expect.startsWith("d") ? "declared" : v.expect)));
    expect([...kinds].sort()).toEqual(["absent", "declared", "invalid"]);
  });

  for (const vector of vectors) {
    test(`${vector.name}: ${vector.expect}`, async () => {
      const root = await mkdtemp(join(tmpdir(), "touchline-marker-"));
      await writeFile(join(root, MARKER_FILE), vector.text);
      const parsed = markerLevel(vector.text);
      const marker = await readMarker(root);
      const level = await homeLevel(root);
      const cli = await run(["bun", resolver, "home-level", root]);
      if (vector.expect === "invalid") {
        expect(parsed.state).toBe("invalid");
        expect(marker.state).toBe("foreign");
        expect(level).toBeUndefined();
        expect(cli.code).toBe(1);
        expect(cli.stderr).toContain("is not a usable marker");
      } else if (vector.expect === "absent") {
        expect(parsed).toEqual({ state: "absent" });
        expect(level).toMatchObject({ level: "d2", declared: false });
        expect(cli.code).toBe(0);
        expect(cli.stdout.trim()).toBe("d2 assumed");
      } else {
        const declared = vector.expect as ConferenceLevel;
        expect(parsed).toEqual({ state: "declared", level: declared });
        expect(level).toEqual({ level: declared, declared: true });
        expect(cli.code).toBe(0);
        expect(cli.stdout.trim()).toBe(`${vector.expect} declared`);
      }
    });
  }
});
