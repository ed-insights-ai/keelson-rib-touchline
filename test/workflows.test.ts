// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { describe, expect, test } from "bun:test";
import { realpathSync } from "node:fs";
import { mkdir, mkdtemp, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { packageDir } from "../src/datahome.ts";
import {
  _resetMembershipCache,
  _setMembershipCache,
  activeConferences,
  activeConferencesInSeason,
  CONFERENCE_LEVELS,
  conferenceLevel,
  loadMembership,
  type MembershipFile,
  programmeLevel,
  resolveConference,
} from "../src/membership.ts";

const pkg = packageDir();
const resolver = join(pkg, "bin", "resolve-membership.ts");
const slotScript = join(pkg, "bin", "backfill-slot.sh");

interface WorkflowInput {
  name: string;
  required?: boolean;
}
interface WorkflowNode {
  id: string;
  depends_on?: string[];
  trigger_rule?: string;
  bash?: string;
  prompt?: string;
  loop?: { until_bash?: string; prompt?: string };
}
interface Workflow {
  name: string;
  inputs: WorkflowInput[];
  nodes: WorkflowNode[];
}

async function loadWorkflow(name: string): Promise<Workflow> {
  const text = await Bun.file(join(pkg, "workflows", `${name}.yml`)).text();
  return Bun.YAML.parse(text) as Workflow;
}

async function run(cmd: string[], env: Record<string, string> = {}, cwd?: string) {
  const proc = Bun.spawn(cmd, {
    cwd,
    env: { ...process.env, ...env },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  return { code: await proc.exited, stdout, stderr };
}

// A conference the shipped membership record authors for men, chosen from the
// data rather than named: the tests must survive a conference joining or
// leaving without a literal to edit.
async function sampleConference(): Promise<{ conference: string; season: number }> {
  const file = await loadMembership();
  for (const byGender of Object.values(file.memberships)) {
    const w = byGender.men?.[0];
    if (w && w.conference !== "independent" && w.conference !== "non_member") {
      return { conference: w.conference, season: w.to_season };
    }
  }
  throw new Error("membership.json authors no men's conference window");
}

describe("bin/resolve-membership.ts", () => {
  test("conference mode prints the extrapolated flag and the member slugs", async () => {
    const { conference, season } = await sampleConference();
    const expected = await resolveConference(conference, "men", season);
    const r = await run(["bun", resolver, "conference", conference, "men", String(season)]);
    expect(r.code).toBe(0);
    const [flag, slugs] = r.stdout.trim().split(" ");
    expect(flag).toBe(expected.extrapolated ? "true" : "false");
    expect(slugs?.split(",")).toEqual(expected.slugs);
  });

  test("the shipped record resolves GLVC men 2024 to 15 slugs when it authors GLVC", async () => {
    // tl-4sg.17 acceptance, guarded on the data so the test does not itself
    // hardcode that GLVC exists: it asserts the count only when the record
    // authors the conference.
    const file = await loadMembership();
    if (!file.conferences.includes("GLVC")) return;
    const r = await run(["bun", resolver, "conference", "GLVC", "men", "2024"]);
    expect(r.code).toBe(0);
    const [flag, slugs] = r.stdout.trim().split(" ");
    expect(flag).toBe("false");
    expect(slugs?.split(",")).toHaveLength(15);
  });

  test("divisions mode prints slug=division pairs, and nothing for a one-table conference", async () => {
    const { conference, season } = await sampleConference();
    const expected = await resolveConference(conference, "men", season);
    const r = await run(["bun", resolver, "divisions", conference, "men", String(season)]);
    expect(r.code).toBe(0);
    const pairs = Object.entries(expected.divisions)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([slug, division]) => `${slug}=${division}`);
    expect(r.stdout).toBe(`${pairs.join(" ")}\n`);
    // The conference line keeps its two-token shape whatever the divisions say.
    const line = await run(["bun", resolver, "conference", conference, "men", String(season)]);
    expect(line.stdout.trim().split(" ")).toHaveLength(2);
  });

  test("an unknown conference exits 1 naming the known ones", async () => {
    const r = await run(["bun", resolver, "conference", "NOPE", "men", "2024"]);
    expect(r.code).toBe(1);
    expect(r.stdout).toBe("");
    expect(r.stderr).toContain("no members resolve for NOPE men 2024");
    expect(r.stderr).toContain("known conferences:");
  });

  test("a season that is not a four-digit year is refused", async () => {
    const r = await run(["bun", resolver, "conference", "GAC", "men", "24"]);
    expect(r.code).toBe(1);
    expect(r.stderr).toContain("not a four-digit year");
  });

  test("conferences mode lists the conferences with a window for the gender, from data", async () => {
    const file = await loadMembership();
    for (const gender of ["men", "women"]) {
      const expected = new Set<string>();
      for (const byGender of Object.values(file.memberships)) {
        for (const w of byGender[gender] ?? []) {
          if (w.conference !== "independent" && w.conference !== "non_member") {
            expected.add(w.conference);
          }
        }
      }
      const r = await run(["bun", resolver, "conferences", gender]);
      expect(r.code).toBe(0);
      expect(r.stdout.trim().split(" ")).toEqual([...expected].sort());
      expect(await activeConferences(gender)).toEqual([...expected].sort());
    }
  });

  test("conferences mode never lists the structural codes", async () => {
    for (const gender of ["men", "women"]) {
      const active = await activeConferences(gender);
      expect(active).not.toContain("independent");
      expect(active).not.toContain("non_member");
    }
  });

  test("a gender nobody authors exits 1", async () => {
    const r = await run(["bun", resolver, "conferences", "mixed"]);
    expect(r.code).toBe(1);
    expect(r.stderr).toContain("no conference authors a mixed membership window");
  });

  test("conferences --level keeps only that NCAA level, read from the profiles", async () => {
    const file = await loadMembership();
    for (const gender of ["men", "women"]) {
      const all = await activeConferences(gender);
      const seen: string[] = [];
      for (const level of CONFERENCE_LEVELS) {
        const expected = all.filter((code) => file.conference_profiles[code]?.level === level);
        expect(await activeConferences(gender, level)).toEqual(expected);
        const r = await run(["bun", resolver, "conferences", gender, "--level", level]);
        if (expected.length) {
          expect(r.code).toBe(0);
          expect(r.stdout).toBe(`${expected.join(" ")}\n`);
        } else {
          // A level nobody is authored at is a refusal, never an empty line.
          expect(r.code).toBe(1);
          expect(r.stdout).toBe("");
          expect(r.stderr).toContain(
            `no ${level} conference authors a ${gender} membership window`,
          );
        }
        seen.push(...expected);
      }
      // The levels partition the sweep: every conference at exactly one.
      expect(seen.sort()).toEqual(all);
    }
  });

  test("the level flag reads in either position and either spelling", async () => {
    const plain = await run(["bun", resolver, "conferences", "men", "--level", "d2"]);
    expect(plain.code).toBe(0);
    for (const args of [
      ["conferences", "--level", "d2", "men"],
      ["conferences", "men", "--level=d2"],
      ["conferences", "men", "--level", "D2"],
    ]) {
      const r = await run(["bun", resolver, ...args]);
      expect(r.code).toBe(0);
      expect(r.stdout).toBe(plain.stdout);
    }
  });

  test("the un-flagged conferences line is the level-blind one, byte for byte", async () => {
    for (const gender of ["men", "women"]) {
      const r = await run(["bun", resolver, "conferences", gender]);
      expect(r.code).toBe(0);
      expect(r.stdout).toBe(`${(await activeConferences(gender)).join(" ")}\n`);
      expect(r.stderr).toBe("");
    }
  });

  test("a level that is not one of the three is refused by name", async () => {
    for (const args of [
      ["conferences", "men", "--level", "division-two"],
      ["conferences", "men", "--level"],
    ]) {
      const r = await run(["bun", resolver, ...args]);
      expect(r.code).toBe(1);
      expect(r.stdout).toBe("");
      expect(r.stderr).toContain("is not one of d1, d2, d3");
    }
    const stray = await run(["bun", resolver, "conferences", "men", "--division", "d2"]);
    expect(stray.code).toBe(1);
    expect(stray.stderr).toContain("usage:");
  });
});

describe("conference levels", () => {
  const file: MembershipFile = {
    conferences: ["UPPER", "LOWER", "independent", "non_member"],
    conference_profiles: {
      UPPER: { level: "d1", names: ["Upper Test League"], code_is_word: true },
      LOWER: { level: "d2", names: ["Lower Test Conference"] },
    },
    memberships: {
      one: { men: [{ conference: "UPPER", from_season: 2024, to_season: 2026, source: "t" }] },
      two: { men: [{ conference: "LOWER", from_season: 2024, to_season: 2026, source: "t" }] },
      three: { women: [{ conference: "LOWER", from_season: 2024, to_season: 2026, source: "t" }] },
    },
  };

  test("a sweep filtered by level keeps that level's conferences only", async () => {
    _setMembershipCache(file);
    try {
      expect(await activeConferences("men")).toEqual(["LOWER", "UPPER"]);
      expect(await activeConferences("men", "d1")).toEqual(["UPPER"]);
      expect(await activeConferences("men", "d2")).toEqual(["LOWER"]);
      expect(await activeConferences("men", "d3")).toEqual([]);
      expect(await activeConferences("women", "d1")).toEqual([]);
      expect(await conferenceLevel("upper")).toBe("d1");
    } finally {
      _resetMembershipCache();
    }
  });

  test("a conference that ended is carried nowhere: its members' own windows win over its horizon", async () => {
    // ENDED authors through 2025; both its members are authored elsewhere for
    // 2026, so a 2026 ENDED collect has nobody. KEPT authors through 2025 too,
    // but its member has no 2026 window, so it is carried forward (flagged).
    _setMembershipCache({
      conferences: ["ENDED", "MOVED", "KEPT"],
      conference_profiles: {
        ENDED: { level: "d1", names: ["Ended League"] },
        MOVED: { level: "d1", names: ["Moved League"] },
        KEPT: { level: "d1", names: ["Kept League"] },
      },
      memberships: {
        a: {
          men: [
            { conference: "ENDED", from_season: 2023, to_season: 2025, source: "t" },
            { conference: "MOVED", from_season: 2026, to_season: 2026, source: "t" },
          ],
        },
        b: {
          men: [
            { conference: "ENDED", from_season: 2023, to_season: 2025, source: "t" },
            { conference: "independent", from_season: 2026, to_season: 2026, source: "t" },
          ],
        },
        c: { men: [{ conference: "KEPT", from_season: 2023, to_season: 2025, source: "t" }] },
      },
    });
    try {
      expect(await resolveConference("ENDED", "men", 2025)).toMatchObject({ slugs: ["a", "b"] });
      expect(await resolveConference("ENDED", "men", 2026)).toMatchObject({
        slugs: [],
        extrapolated: true,
      });
      expect(await resolveConference("KEPT", "men", 2026)).toMatchObject({
        slugs: ["c"],
        extrapolated: true,
      });
      expect(await activeConferencesInSeason("men", 2026, "d1")).toEqual({
        conferences: ["KEPT", "MOVED"],
        skipped: ["ENDED"],
      });
      expect(await programmeLevel("b", "men", 2026)).toBe("d1");
    } finally {
      _resetMembershipCache();
    }
  });

  test("the shipped record: the 2026 Division I men's sweep is 23 conferences, the WAC left out by name", async () => {
    const r = await run([
      "bun",
      resolver,
      "conferences",
      "men",
      "--level",
      "d1",
      "--season",
      "2026",
    ]);
    expect(r.code).toBe(0);
    expect(r.stdout.trim().split(" ")).toHaveLength(23);
    expect(r.stdout).not.toContain("WAC");
    expect(r.stderr).toBe("skipped (no men 2026 members): WAC\n");
    const wac = await run(["bun", resolver, "conference", "WAC", "men", "2026"]);
    expect(wac.code).toBe(1);
  });

  test("a conference with no profile stops a level-filtered sweep, never thins it", async () => {
    _setMembershipCache({
      ...file,
      conference_profiles: { LOWER: file.conference_profiles.LOWER! },
    });
    try {
      // Un-filtered, the sweep is what it always was.
      expect(await activeConferences("men")).toEqual(["LOWER", "UPPER"]);
      expect(activeConferences("men", "d2")).rejects.toThrow(
        "conference 'UPPER' has no conference_profiles entry",
      );
    } finally {
      _resetMembershipCache();
    }
  });
});

describe("workflows/touchline-collect.yml", () => {
  test("programmes is optional and resolved by its own node before collect", async () => {
    const wf = await loadWorkflow("touchline-collect");
    const programmes = wf.inputs.find((i) => i.name === "programmes");
    expect(programmes?.required).toBe(false);
    for (const name of ["conference", "gender", "season"]) {
      expect(wf.inputs.find((i) => i.name === name)?.required).toBe(true);
    }

    const ids = wf.nodes.map((n) => n.id);
    expect(ids).toEqual([
      "preflight",
      "resolve-pipeline",
      "level-guard",
      "resolve-programmes",
      "collect",
      "report",
    ]);
    expect(wf.nodes.find((n) => n.id === "level-guard")?.depends_on).toEqual(["resolve-pipeline"]);
    const resolve = wf.nodes.find((n) => n.id === "resolve-programmes");
    expect(resolve?.depends_on).toEqual(["level-guard"]);
    expect(resolve?.bash).toContain("bin/resolve-membership.ts");
    const collect = wf.nodes.find((n) => n.id === "collect");
    expect(collect?.depends_on).toEqual(["resolve-programmes"]);
    expect(collect?.bash).toContain("KEELSON_NODE_resolve_programmes_OUTPUT");
    expect(collect?.bash).not.toContain("KEELSON_INPUTS_programmes");

    // Preflight no longer refuses an empty programmes input.
    const preflight = wf.nodes.find((n) => n.id === "preflight");
    const loop = preflight?.bash?.match(/for v in ([^;]+);/)?.[1] ?? "";
    expect(loop).not.toContain("KEELSON_INPUTS_programmes");
  });

  test("the resolve-programmes node body passes a caller list through untouched", async () => {
    // The node body is raw bash; run it with the inputs a caller would supply
    // and no pipeline at all, which must not matter on the pass-through path.
    const wf = await loadWorkflow("touchline-collect");
    const body = wf.nodes.find((n) => n.id === "resolve-programmes")?.bash ?? "";
    const r = await run(["bash", "-c", body], {
      KEELSON_INPUTS_programmes: "alpha,beta",
      KEELSON_INPUTS_membership_extrapolated: "true",
      KEELSON_INPUTS_conference: "X",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_season: "2024",
      KEELSON_NODE_resolve_pipeline_OUTPUT: "/nowhere/pipeline",
    });
    expect(r.code).toBe(0);
    expect(r.stdout.trim()).toBe("true alpha,beta");
  });

  test("the resolve-programmes node body resolves an empty input from the packaged record", async () => {
    const { conference, season } = await sampleConference();
    const expected = await resolveConference(conference, "men", season);
    const wf = await loadWorkflow("touchline-collect");
    const body = wf.nodes.find((n) => n.id === "resolve-programmes")?.bash ?? "";
    const r = await run(["bash", "-c", body], {
      KEELSON_INPUTS_programmes: "",
      KEELSON_INPUTS_conference: conference,
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_season: String(season),
      KEELSON_NODE_resolve_pipeline_OUTPUT: join(pkg, "pipeline"),
    });
    expect(r.code).toBe(0);
    expect(r.stdout.trim()).toBe(
      `${expected.extrapolated ? "true" : "false"} ${expected.slugs.join(",")}`,
    );
  });

  test("the resolve-programmes node refuses an unknown conference instead of collecting", async () => {
    const wf = await loadWorkflow("touchline-collect");
    const body = wf.nodes.find((n) => n.id === "resolve-programmes")?.bash ?? "";
    const r = await run(["bash", "-c", body], {
      KEELSON_INPUTS_conference: "NOPE",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_season: "2024",
      KEELSON_NODE_resolve_pipeline_OUTPUT: join(pkg, "pipeline"),
    });
    expect(r.code).toBe(1);
    expect(r.stdout).toContain("REFUSED: no programmes resolve for NOPE men 2024");
  });
});

describe("workflows/touchline-backfill.yml", () => {
  test("wires one collect node per season slot, chained, and reports every slot", async () => {
    const wf = await loadWorkflow("touchline-backfill");
    const preflight = wf.nodes.find((n) => n.id === "preflight");
    const max = Number(preflight?.bash?.match(/MAX_SEASONS=(\d+)/)?.[1]);
    expect(max).toBeGreaterThan(1);

    const slots = wf.nodes.filter((n) => /^collect-\d+$/.test(n.id));
    expect(slots.map((n) => n.id)).toEqual(
      Array.from({ length: max }, (_, i) => `collect-${i + 1}`),
    );
    expect(wf.nodes.find((n) => n.id === "level-guard")?.depends_on).toEqual(["resolve-pipeline"]);
    slots.forEach((n, i) => {
      expect(n.depends_on).toEqual([i === 0 ? "level-guard" : `collect-${i}`]);
      if (i > 0) expect(n.trigger_rule).toBe("all_done");
      expect(n.bash).toContain(`SLOT=${i + 1} sh`);
      expect(n.bash).toContain("bin/backfill-slot.sh");
    });

    const report = wf.nodes.find((n) => n.id === "report");
    expect(report?.trigger_rule).toBe("all_done");
    for (const n of slots) expect(report?.prompt).toContain(`$${n.id}.output`);

    for (const name of ["conference", "gender", "from_season", "to_season"]) {
      expect(wf.inputs.find((i) => i.name === name)?.required).toBe(true);
    }
    expect(wf.inputs.find((i) => i.name === "layers")?.required).toBe(false);
    expect(wf.inputs.find((i) => i.name === "refetch")?.required).toBe(false);
  });

  test("a slot passes --refetch to collect-board only when the refetch input is true", async () => {
    // Stored box scores are reused whenever a fixture's result is unchanged,
    // so a parser change never reaches them unless the run asks to re-fetch.
    // A fake `uv` ahead on PATH records the collect-board command instead of
    // running the pipeline.
    const { conference, season } = await sampleConference();
    const binDir = await mkdtemp(join(tmpdir(), "touchline-fake-uv-"));
    await writeFile(join(binDir, "uv"), '#!/bin/sh\nprintf "UV %s\\n" "$*"\n', { mode: 0o755 });
    const base = {
      SLOT: "1",
      PATH: `${binDir}:${process.env.PATH ?? ""}`,
      KEELSON_INPUTS_conference: conference,
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_from_season: String(season),
      KEELSON_INPUTS_to_season: String(season),
      KEELSON_NODE_resolve_pipeline_OUTPUT: join(pkg, "pipeline"),
    };

    const on = await run(["sh", slotScript], { ...base, KEELSON_INPUTS_refetch: "true" });
    expect(on.code).toBe(0);
    const onCommand = on.stdout.split("\n").find((l) => l.startsWith("UV "));
    expect(onCommand).toContain(" collect-board ");
    expect(onCommand?.split(" ")).toContain("--refetch");
    expect(on.stdout).toContain("NOTE: refetch requested");

    for (const env of [base, { ...base, KEELSON_INPUTS_refetch: "false" }]) {
      const off = await run(["sh", slotScript], env);
      expect(off.code).toBe(0);
      const offCommand = off.stdout.split("\n").find((l) => l.startsWith("UV "));
      expect(offCommand).toContain(" collect-board ");
      expect(offCommand).not.toContain("--refetch");
      expect(off.stdout).not.toContain("NOTE: refetch requested");
    }
  });

  test("preflight refuses a range longer than the wired slots, and an inverted one", async () => {
    const wf = await loadWorkflow("touchline-backfill");
    const body = wf.nodes.find((n) => n.id === "preflight")?.bash ?? "";
    const home = await mkdtemp(join(tmpdir(), "touchline-backfill-"));
    await writeFile(join(home, "touchline-data.yaml"), "kind: touchline-data\n");
    const base = {
      KEELSON_INPUTS_conference: "X",
      KEELSON_INPUTS_gender: "men",
    };

    const tooLong = await run(
      ["bash", "-c", body],
      { ...base, KEELSON_INPUTS_from_season: "2010", KEELSON_INPUTS_to_season: "2026" },
      home,
    );
    expect(tooLong.code).toBe(1);
    expect(tooLong.stdout).toContain("REFUSED: 17 seasons requested");

    const inverted = await run(
      ["bash", "-c", body],
      { ...base, KEELSON_INPUTS_from_season: "2025", KEELSON_INPUTS_to_season: "2024" },
      home,
    );
    expect(inverted.code).toBe(1);
    expect(inverted.stdout).toContain("REFUSED: from_season 2025 is after to_season 2024");

    const ok = await run(
      ["bash", "-c", body],
      { ...base, KEELSON_INPUTS_from_season: "2022", KEELSON_INPUTS_to_season: "2026" },
      home,
    );
    expect(ok.code).toBe(0);
    expect(ok.stdout).toContain("range: X men 2022-2026 (5 seasons, 8 slots)");
  });

  test("preflight refuses while the cadence's pid lock is live and passes once that pid is gone", async () => {
    const wf = await loadWorkflow("touchline-backfill");
    const body = wf.nodes.find((n) => n.id === "preflight")?.bash ?? "";
    const home = await mkdtemp(join(tmpdir(), "touchline-backfill-"));
    await writeFile(join(home, "touchline-data.yaml"), "kind: touchline-data\n");
    // the cadence's lock dir, pointed at by the same override the cadence honours
    const lock = join(home, "touchline-collect-cadence.lock");
    await mkdir(lock);
    const env = {
      KEELSON_INPUTS_conference: "X",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_from_season: "2025",
      KEELSON_INPUTS_to_season: "2026",
      TOUCHLINE_CADENCE_LOCK_DIR: lock,
    };

    await writeFile(join(lock, "pid"), `${process.pid}\n`);
    const live = await run(["bash", "-c", body], env, home);
    expect(live.code).toBe(1);
    expect(live.stdout).toContain(
      `REFUSED: the touchline cadence for this data home is running (pid ${process.pid}, lock ${lock}); retry after it finishes.`,
    );

    // a lock whose pid is gone is stale: the range check runs as before
    const gone = Bun.spawn(["true"]);
    await gone.exited;
    await writeFile(join(lock, "pid"), `${gone.pid}\n`);
    const ok = await run(["bash", "-c", body], env, home);
    expect(ok.code).toBe(0);
    expect(ok.stdout).toContain("range: X men 2025-2026 (2 seasons, 8 slots)");
  });

  test("a slot past the range is skipped without touching the pipeline", async () => {
    const r = await run(["sh", slotScript], {
      SLOT: "6",
      KEELSON_INPUTS_conference: "X",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_from_season: "2022",
      KEELSON_INPUTS_to_season: "2026",
      KEELSON_NODE_resolve_pipeline_OUTPUT: "/nowhere/pipeline",
    });
    expect(r.code).toBe(0);
    expect(r.stdout.trim()).toBe("SKIPPED: slot 6 has no season (range 2022-2026).");
  });

  test("a slot in range alarms on a missing pipeline before resolving anything", async () => {
    const r = await run(["sh", slotScript], {
      SLOT: "2",
      KEELSON_INPUTS_conference: "X",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_from_season: "2022",
      KEELSON_INPUTS_to_season: "2026",
      KEELSON_NODE_resolve_pipeline_OUTPUT: "/nowhere/pipeline",
    });
    expect(r.code).toBe(1);
    expect(r.stdout).toContain("ALARM: pipeline not found at /nowhere/pipeline");
  });

  test("a slot in range refuses an unknown conference before collecting", async () => {
    const r = await run(["sh", slotScript], {
      SLOT: "1",
      KEELSON_INPUTS_conference: "NOPE",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_from_season: "2024",
      KEELSON_INPUTS_to_season: "2024",
      KEELSON_NODE_resolve_pipeline_OUTPUT: join(pkg, "pipeline"),
    });
    expect(r.code).toBe(1);
    expect(r.stdout).toContain("REFUSED: membership resolution failed for NOPE men 2024");
  });
});

// ── one NCAA level per data home ─────────────────────────────────────────────

// A marked data home at `dir` (created), with `level` in its marker when given.
async function markedHome(dir: string, level?: string): Promise<string> {
  await mkdir(dir, { recursive: true });
  await writeFile(
    join(dir, "touchline-data.yaml"),
    `kind: touchline-data\nversion: 1\n${level ? `level: ${level}\n` : ""}`,
  );
  // physical, the way a bash node's $PWD reports it (macOS tmp is a symlink)
  return realpathSync(dir);
}

// One conference at each level, chosen from the shipped record's profiles.
async function conferenceAt(level: string): Promise<string> {
  const file = await loadMembership();
  const found = Object.entries(file.conference_profiles).find(([, p]) => p.level === level);
  if (!found) throw new Error(`the shipped record profiles no ${level} conference`);
  return found[0];
}

describe("the level guard (workflows' level-guard node, bin/resolve-membership.ts guard)", () => {
  for (const name of ["touchline-collect", "touchline-backfill"]) {
    test(`${name}: a conference of the other level is refused before anything is fetched, naming both levels`, async () => {
      const wf = await loadWorkflow(name);
      const body = wf.nodes.find((n) => n.id === "level-guard")?.bash ?? "";
      expect(body).toContain("guard");
      const root = await mkdtemp(join(tmpdir(), "touchline-level-"));
      const d1Home = await markedHome(join(root, "d1-soccer"), "d1");
      const d2Home = await markedHome(join(root, "d2-soccer"), "d2");
      const d1 = await conferenceAt("d1");
      const d2 = await conferenceAt("d2");
      const env = { KEELSON_NODE_resolve_pipeline_OUTPUT: join(pkg, "pipeline") };

      const intoD2 = await run(
        ["bash", "-c", body],
        { ...env, KEELSON_INPUTS_conference: d1 },
        d2Home,
      );
      expect(intoD2.code).toBe(1);
      expect(intoD2.stdout).toContain(
        `REFUSED: ${d1} is a d1 conference and the data home ${d2Home} collects d2 (declared in its marker).`,
      );
      const intoD1 = await run(
        ["bash", "-c", body],
        { ...env, KEELSON_INPUTS_conference: d2 },
        d1Home,
      );
      expect(intoD1.code).toBe(1);
      expect(intoD1.stdout).toContain(
        `REFUSED: ${d2} is a d2 conference and the data home ${d1Home} collects d1 (declared in its marker).`,
      );
      const ok = await run(["bash", "-c", body], { ...env, KEELSON_INPUTS_conference: d1 }, d1Home);
      expect(ok.code).toBe(0);
      expect(ok.stdout).toContain(`level OK: ${d1} is d1, the data home's level (declared).`);
    });
  }

  test("a marker with no level is read as d2 and says so: d2 passes, d1 is refused", async () => {
    const wf = await loadWorkflow("touchline-collect");
    const body = wf.nodes.find((n) => n.id === "level-guard")?.bash ?? "";
    const home = await markedHome(await mkdtemp(join(tmpdir(), "touchline-nolevel-")));
    const env = { KEELSON_NODE_resolve_pipeline_OUTPUT: join(pkg, "pipeline") };
    const d2 = await run(
      ["bash", "-c", body],
      { ...env, KEELSON_INPUTS_conference: await conferenceAt("d2") },
      home,
    );
    expect(d2.code).toBe(0);
    expect(d2.stdout).toContain(
      `NOTE: ${home}/touchline-data.yaml declares no level, so it is read as d2: every data home made before levels existed is Division II.`,
    );
    expect(d2.stdout).toContain("the data home's level (assumed).");
    const d1 = await run(
      ["bash", "-c", body],
      { ...env, KEELSON_INPUTS_conference: await conferenceAt("d1") },
      home,
    );
    expect(d1.code).toBe(1);
    expect(d1.stdout).toContain("collects d2 (assumed: its marker declares no level)");
  });

  test("a marker stating a level that is not d1, d2 or d3 is refused, never guessed past", async () => {
    const home = await mkdtemp(join(tmpdir(), "touchline-badlevel-"));
    await writeFile(
      join(home, "touchline-data.yaml"),
      "kind: touchline-data\nversion: 1\nlevel: D4\n",
    );
    const r = await run(["bun", resolver, "guard", home, await conferenceAt("d2")]);
    expect(r.code).toBe(1);
    expect(r.stdout).toContain("level: D4 is not one of d1, d2, d3");
    const lv = await run(["bun", resolver, "home-level", home]);
    expect(lv.code).toBe(1);
  });
});

describe("the backfill preflight consults its own home's cadence lock", () => {
  test("with the D2 cadence lock live, a D1 home's backfill proceeds and a D2 home's refuses; the lock matches the cadence's own", async () => {
    const wf = await loadWorkflow("touchline-backfill");
    const body = wf.nodes.find((n) => n.id === "preflight")?.bash ?? "";
    const fakeHome = await mkdtemp(join(tmpdir(), "touchline-two-homes-"));
    const d2Home = await markedHome(join(fakeHome, "keelson", "d2-soccer"));
    const d1Home = await markedHome(join(fakeHome, "keelson", "d1-soccer"), "d1");
    const locks = join(fakeHome, ".keelson", "locks");
    const d2Lock = join(locks, "touchline-collect-cadence.lock");
    await mkdir(d2Lock, { recursive: true });
    await writeFile(join(d2Lock, "pid"), `${process.pid}\n`);
    const env = {
      HOME: fakeHome,
      TOUCHLINE_CADENCE_LOCK_DIR: "",
      KEELSON_INPUTS_conference: "X",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_from_season: "2025",
      KEELSON_INPUTS_to_season: "2026",
    };

    const d1 = await run(["bash", "-c", body], env, d1Home);
    expect(d1.code).toBe(0);
    const d1Lock = join(locks, "touchline-collect-cadence.d1-soccer.lock");
    expect(d1.stdout).toContain(`cadence lock: ${d1Lock} (not held)`);
    const d2 = await run(["bash", "-c", body], env, d2Home);
    expect(d2.code).toBe(1);
    expect(d2.stdout).toContain(
      `REFUSED: the touchline cadence for this data home is running (pid ${process.pid}, lock ${d2Lock})`,
    );

    // the D1 home's own cadence running refuses its backfill
    await mkdir(d1Lock, { recursive: true });
    await writeFile(join(d1Lock, "pid"), `${process.pid}\n`);
    expect((await run(["bash", "-c", body], env, d1Home)).code).toBe(1);

    // the cadence derives the very same lock paths for both homes
    for (const [home, lock] of [
      [d2Home, d2Lock],
      [d1Home, d1Lock],
    ] as const) {
      const paths = await run(
        ["/bin/sh", join(pkg, "bin", "touchline-collect-cadence.sh"), "paths"],
        {
          HOME: fakeHome,
          TOUCHLINE_DATA_HOME: home,
          TOUCHLINE_CADENCE_LOCK_DIR: "",
        },
      );
      expect(paths.stdout).toContain(`lock_dir=${lock}\n`);
    }
  });
});

describe("workflows/touchline-report.yml research pool", () => {
  // The research pool is conference-scoped: data/research/{season}-{gender}/
  // {conference-shard}/. Two conferences reported in one season must never
  // share files, or one report cites the other's findings and the sweep
  // loop ends on the neighbour's count.
  const flat = /data\/research\/\$\{KEELSON_INPUTS_season\}-\$\{KEELSON_INPUTS_gender\}"/;

  test("every path into the pool carries the conference shard", async () => {
    const wf = await loadWorkflow("touchline-report");
    let seen = 0;
    for (const n of wf.nodes) {
      for (const body of [n.bash, n.loop?.until_bash]) {
        if (!body?.includes("data/research/")) continue;
        seen++;
        expect(body, n.id).not.toMatch(flat);
        expect(body, n.id).toMatch(
          /D="data\/research\/\$\{KEELSON_INPUTS_season\}-\$\{KEELSON_INPUTS_gender\}\/\$CONF"/,
        );
        expect(body, n.id).toContain("$KEELSON_INPUTS_conference");
      }
      for (const body of [n.prompt, n.loop?.prompt]) {
        if (!body?.includes("data/research/$inputs")) continue;
        seen++;
        expect(body, n.id).not.toContain("data/research/$inputs.season-$inputs.gender/research");
        expect(body, n.id).not.toContain("data/research/$inputs.season-$inputs.gender/verified");
        expect(body, n.id).toContain(
          "data/research/$inputs.season-$inputs.gender/$conference-shard.output/",
        );
      }
    }
    expect(seen).toBeGreaterThanOrEqual(8);
  });

  async function pool(conference: string) {
    // A data home with a two-programme digest for the focus, a neighbouring
    // conference's complete flat pool, and nothing yet for this conference.
    const home = await mkdtemp(join(tmpdir(), "touchline-research-"));
    await mkdir(join(home, "data", "scratch"), { recursive: true });
    const digest = join(home, "data", "scratch", "digest-2026-men-alpha.json");
    await writeFile(digest, JSON.stringify({ programmes: { alpha: {}, beta: {} } }));
    // bash's -nt compares whole seconds on macOS; date the digest back so
    // files written moments later count as newer.
    const past = new Date(Date.now() - 60_000);
    await utimes(digest, past, past);
    const research = (slug: string) =>
      JSON.stringify({ programme: slug, coach: { name: "Coach", status: "returning" } });
    const flatDir = join(home, "data", "research", "2026-men");
    await mkdir(flatDir, { recursive: true });
    for (const slug of ["alpha", "beta", "gamma"]) {
      await writeFile(join(flatDir, `research-${slug}.json`), research(slug));
    }
    const env = {
      KEELSON_INPUTS_season: "2026",
      KEELSON_INPUTS_gender: "men",
      KEELSON_INPUTS_conference: conference,
      KEELSON_INPUTS_focus: "alpha",
    };
    return { home, env, research };
  }

  test("the sweep probe ignores a neighbouring conference's flat pool", async () => {
    const wf = await loadWorkflow("touchline-report");
    const probe = wf.nodes.find((n) => n.id === "research")?.loop?.until_bash ?? "";
    const gate = wf.nodes.find((n) => n.id === "validate-research")?.bash ?? "";
    const { home, env, research } = await pool("Test Conf");

    // Flat files alone: the sweep has done nothing, so the loop must continue
    // and the gate must fail.
    expect((await run(["bash", "-c", probe], env, home)).code).toBe(1);
    const alarm = await run(["bash", "-c", gate], env, home);
    expect(alarm.code).toBe(1);
    expect(alarm.stdout).toContain("alpha(no-file) beta(no-file)");

    // Files in this conference's own pool (shard slug of the input) satisfy
    // both, and only the digest's programmes are counted.
    const scoped = join(home, "data", "research", "2026-men", "test-conf");
    await mkdir(scoped, { recursive: true });
    await writeFile(join(scoped, "research-alpha.json"), research("alpha"));
    expect((await run(["bash", "-c", probe], env, home)).code).toBe(1);
    await writeFile(join(scoped, "research-beta.json"), research("beta"));
    expect((await run(["bash", "-c", probe], env, home)).code).toBe(0);
    const ok = await run(["bash", "-c", gate], env, home);
    expect(ok.code).toBe(0);
    expect(ok.stdout).toContain("research OK: 2 programmes");
  });

  test("merge-verified writes verified.json inside the conference pool", async () => {
    const wf = await loadWorkflow("touchline-report");
    const merge = wf.nodes.find((n) => n.id === "merge-verified")?.bash ?? "";
    const { home, env } = await pool("Test Conf");
    const scoped = join(home, "data", "research", "2026-men", "test-conf");
    await mkdir(scoped, { recursive: true });
    for (const slug of ["alpha", "beta"]) {
      await writeFile(
        join(scoped, `verified-${slug}.json`),
        JSON.stringify({
          schema: "touchline.research-verified/1",
          findings: [{ player: null, type: "news", text: slug }],
          coaches: { [slug]: { name: "Coach", status: "returning" } },
          dropped: [],
          attested_uncaptured: [],
          unswept: [],
        }),
      );
    }
    const r = await run(["bash", "-c", merge], env, home);
    expect(r.code, r.stdout + r.stderr).toBe(0);
    expect(r.stdout).toContain("verified merge: 2 coaches, 2 findings");
    expect(await Bun.file(join(scoped, "verified.json")).exists()).toBe(true);
    expect(
      await Bun.file(join(home, "data", "research", "2026-men", "verified.json")).exists(),
    ).toBe(false);
  });
});
