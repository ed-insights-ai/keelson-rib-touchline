// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { describe, expect, test } from "bun:test";
import { mkdtemp, writeFile } from "node:fs/promises";
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
