// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { packageDir } from "../src/datahome.ts";
import { activeConferences, loadMembership, resolveConference } from "../src/membership.ts";

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
      "resolve-programmes",
      "collect",
      "report",
    ]);
    const resolve = wf.nodes.find((n) => n.id === "resolve-programmes");
    expect(resolve?.depends_on).toEqual(["resolve-pipeline"]);
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
    slots.forEach((n, i) => {
      expect(n.depends_on).toEqual([i === 0 ? "resolve-pipeline" : `collect-${i}`]);
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
