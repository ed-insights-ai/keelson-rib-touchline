// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { afterEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type Project, type RibContext } from "@keelson/shared";
import {
  activationConfigPath,
  ensureActivationConfig,
  readActivationConfig,
  resolveActivationDataDir,
  touchlineAuthStatus,
} from "../src/activation.ts";
import {
  initTouchlineHome,
  invokeTouchlineCommand,
  keelsonWorkspacePath,
  planTouchlineRemoval,
  removeTouchlineHome,
  touchlineProjectPath,
} from "../src/commands.ts";
import { dataHomeState } from "../src/datahome.ts";
import rib, { composeTouchlineBoard, setScope } from "../src/index.ts";
import { makeTouchlineTools } from "../src/tools.ts";

const originalWorkspace = process.env.KEELSON_WORKSPACE;
const originalConfigPath = process.env.TOUCHLINE_CONFIG_PATH;

afterEach(() => {
  if (originalWorkspace === undefined) delete process.env.KEELSON_WORKSPACE;
  else process.env.KEELSON_WORKSPACE = originalWorkspace;
  if (originalConfigPath === undefined) delete process.env.TOUCHLINE_CONFIG_PATH;
  else process.env.TOUCHLINE_CONFIG_PATH = originalConfigPath;
  rib.dispose?.();
});

async function tempRoot(label: string): Promise<string> {
  return mkdtemp(join(tmpdir(), `touchline-${label}-`));
}

function fakeContext(projects: Project[]): RibContext {
  return {
    getProjects: () => projects,
    getExec: () => ({
      runJSON: async <T = unknown>() => ({ ok: true as const, data: {} as T }),
      runText: async (cmd, args) => {
        if (cmd === "uv") return { ok: true as const, data: "uv 0.8.0", exitCode: 0 };
        expect(cmd).toBe("keelson");
        expect(args[0]).toBe("project");
        if (args[1] === "remove") {
          const at = projects.findIndex((p) => p.name === args[2]);
          if (at >= 0) projects.splice(at, 1);
          return { ok: true as const, data: "removed", exitCode: 0 };
        }
        expect(args[1]).toBe("add");
        projects.push({
          id: `touchline-project-${projects.length}`,
          name: args[2] as string,
          rootPath: args[3] as string,
          createdAt: "2026-08-09T00:00:00Z",
        });
        return { ok: true as const, data: "registered", exitCode: 0 };
      },
    }),
  };
}

describe("activation config", () => {
  test("the config follows KEELSON_HOME", () => {
    expect(activationConfigPath({ KEELSON_HOME: "/tmp/keelson-home" })).toBe(
      "/tmp/keelson-home/rib-touchline/config.json",
    );
  });

  test("TOUCHLINE_DATA_DIR overrides the remembered config directory", async () => {
    const root = await tempRoot("activation-env");
    const configPath = join(root, "config.json");
    await writeFile(
      configPath,
      JSON.stringify({ packageDir: "/package", dataDir: "/remembered" }),
      "utf8",
    );
    expect(
      await resolveActivationDataDir({
        configPath,
        env: { TOUCHLINE_DATA_DIR: "/explicit" },
      }),
    ).toEqual({ ok: true, dataDir: "/explicit", source: "env" });
  });

  test("a valid config supplies dataDir and invalid JSON is reported", async () => {
    const root = await tempRoot("activation-config");
    const configPath = join(root, "config.json");
    await writeFile(
      configPath,
      JSON.stringify({ packageDir: "/package", dataDir: "/remembered" }),
      "utf8",
    );
    expect(await resolveActivationDataDir({ configPath, env: {} })).toEqual({
      ok: true,
      dataDir: "/remembered",
      source: "config",
    });

    await writeFile(configPath, "{broken", "utf8");
    const invalid = await readActivationConfig({ configPath });
    expect(invalid.ok).toBe(false);
    if (!invalid.ok) expect(invalid.error).toContain("not valid JSON");
    await expect(ensureActivationConfig(undefined, { configPath })).rejects.toThrow(
      /not valid JSON/,
    );
  });

  test("activation keeps the config keys it does not own (the cadence's divisions)", async () => {
    const root = await tempRoot("activation-keep");
    const configPath = join(root, "config.json");
    await writeFile(
      configPath,
      JSON.stringify({
        packageDir: "/stale/package",
        dataDir: "/data/home",
        genders: ["men", "women"],
        conferences: { women: ["GAC"] },
      }),
      "utf8",
    );

    // a server start re-activates with no dataDir: the remembered one stands
    await ensureActivationConfig(undefined, { configPath });
    let written = JSON.parse(await readFile(configPath, "utf8"));
    expect(written.dataDir).toBe("/data/home");
    expect(written.packageDir).not.toBe("/stale/package");
    expect(written.genders).toEqual(["men", "women"]);
    expect(written.conferences).toEqual({ women: ["GAC"] });

    // a new dataDir replaces the old one and still keeps the rest
    await ensureActivationConfig("/data/other", { configPath });
    written = JSON.parse(await readFile(configPath, "utf8"));
    expect(written.dataDir).toBe("/data/other");
    expect(written.genders).toEqual(["men", "women"]);
  });

  test("auth status distinguishes an unmarked folder from an invalid config", async () => {
    const root = await tempRoot("activation-status");
    const emptyHome = join(root, "empty-home");
    await mkdir(emptyHome);
    process.env.TOUCHLINE_CONFIG_PATH = join(root, "config.json");
    await ensureActivationConfig(emptyHome);

    const empty = await touchlineAuthStatus(fakeContext([]));
    expect(empty.authenticated).toBe(false);
    expect(empty.statusMessage).toContain("empty and ready to initialize");

    await writeFile(process.env.TOUCHLINE_CONFIG_PATH, "{broken", "utf8");
    const invalid = await touchlineAuthStatus(fakeContext([]));
    expect(invalid.authenticated).toBe(false);
    expect(invalid.statusMessage).toContain("activation config is invalid");
  });
});

describe("first-contact commands", () => {
  test("the default workspace matches Keelson and a child path stays beneath it", () => {
    expect(keelsonWorkspacePath({ KEELSON_WORKSPACE: "/tmp/keelson-custom" })).toBe(
      "/tmp/keelson-custom",
    );
    expect(touchlineProjectPath("gac-soccer", { KEELSON_WORKSPACE: "/tmp/keelson-custom" })).toBe(
      "/tmp/keelson-custom/gac-soccer",
    );
  });

  test("/touchline with no argument only opens the agent", async () => {
    const projects: Project[] = [];
    const result = await invokeTouchlineCommand("", fakeContext(projects));
    expect(result).toEqual({
      ok: true,
      effect: { effect: "open-agent", ribId: "touchline", slug: "touchline" },
    });
    expect(projects).toHaveLength(0);
  });

  test("folder names follow Keelson's project-name contract", async () => {
    const result = await invokeTouchlineCommand("GAC Soccer", fakeContext([]));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("lowercase folder name");
  });

  test("/touchline name creates, initializes and registers a non-Git data home", async () => {
    const workspace = await tempRoot("workspace");
    const configRoot = await tempRoot("command-config");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(configRoot, "config.json");
    const projects: Project[] = [];
    const ctx = fakeContext(projects);

    const result = await invokeTouchlineCommand("gac-soccer", ctx);
    expect(result.ok).toBe(true);
    const root = join(workspace, "gac-soccer");
    expect(await dataHomeState(root)).toMatchObject({ state: "ready" });
    expect(projects).toContainEqual(
      expect.objectContaining({ name: "gac-soccer", rootPath: root }),
    );
    expect(await readFile(join(root, "touchline-data.yaml"), "utf8")).toContain(
      "kind: touchline-data",
    );
    await expect(stat(join(root, ".git"))).rejects.toThrow();
    await expect(stat(join(root, ".gitignore"))).rejects.toThrow();

    const auth = await touchlineAuthStatus(ctx);
    expect(auth.authenticated).toBe(true);
    expect(auth.statusMessage).toContain(root);
  });

  test("the same data home is reachable without the slash command", async () => {
    // A slash command is a COMPOSER affordance: neither `keelson chat` nor MCP
    // can invoke one. When the command was the only way to create a data home,
    // an agent asked to set one up could name the command but never run it —
    // and answered with an invented failure instead of naming the gap.
    const workspace = await tempRoot("tool-workspace");
    const configRoot = await tempRoot("tool-config");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(configRoot, "config.json");
    const projects: Project[] = [];
    const ctx = fakeContext(projects);

    const first = await initTouchlineHome("gac-soccer", ctx);
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    expect(first).toMatchObject({
      name: "gac-soccer",
      rootPath: join(workspace, "gac-soccer"),
      created: true,
      registered: true,
    });
    expect(await dataHomeState(first.rootPath)).toMatchObject({ state: "ready" });

    // Re-running must report rather than overwrite — the tool is safe to retry.
    const second = await initTouchlineHome("gac-soccer", ctx);
    expect(second).toMatchObject({ ok: true, created: false, registered: false });
    expect(projects).toHaveLength(1);
  });

  test("the collected stamp rides the panel byline and clears with the scope", async () => {
    const workspace = await tempRoot("byline-workspace");
    const configRoot = await tempRoot("byline-config");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(configRoot, "config.json");
    const projects: Project[] = [];
    let invalidations = 0;
    const ctx: RibContext = {
      ...fakeContext(projects),
      invalidateManifest: () => {
        invalidations += 1;
      },
    };

    const made = await initTouchlineHome("gac-soccer", ctx);
    expect(made.ok).toBe(true);
    if (!made.ok) return;
    await writeFile(
      join(made.rootPath, "data", "fixtures", "2025-men-gac.json"),
      JSON.stringify({
        schema: "touchline.fixtures/2",
        season: 2025,
        gender: "men",
        conference: "GAC",
        collected_at: "2026-08-09T21:00:00Z",
        programmes: [{ slug: "harding", name: "Harding", conference: "GAC" }],
        fixtures: [],
      }),
    );

    rib.registerTools?.(ctx);
    const project = projects[0];
    if (!project) throw new Error("init registered no project");
    setScope(project.id);
    try {
      const html = await composeTouchlineBoard();
      const header = rib.surfaces?.[0]?.layout.header as { byline?: string } | undefined;
      // The stamp lives in the panel head, not on the sheet, and setting it
      // nudged exactly one manifest re-fetch.
      expect(header?.byline).toBe("collected 2026-08-09 21:00");
      expect(invalidations).toBe(1);
      expect(html).not.toContain("collected 2026-08-09");
      // An unchanged stamp must not re-invalidate: every call re-fetches for
      // every client.
      await composeTouchlineBoard();
      expect(invalidations).toBe(1);
      // Pointing the board at nothing clears the stamp rather than leaving a
      // stale season's freshness beside an empty state.
      setScope(undefined);
      await composeTouchlineBoard();
      expect(header?.byline).toBeUndefined();
      expect(invalidations).toBe(2);
    } finally {
      setScope(undefined);
    }
  });

  test("season actions default only when one conference shard matches", async () => {
    const workspace = await tempRoot("season-action-workspace");
    const configRoot = await tempRoot("season-action-config");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(configRoot, "config.json");
    const projects: Project[] = [];
    const ctx = fakeContext(projects);
    const made = await initTouchlineHome("multi-conference", ctx);
    expect(made.ok).toBe(true);
    if (!made.ok) return;

    const fixture = (season: number, conference: string) =>
      JSON.stringify({
        schema: "touchline.fixtures/2",
        season,
        gender: "men",
        conference,
        collected_at: "2026-08-12T12:00:00Z",
        programmes: [{ slug: conference.toLowerCase(), name: conference, conference }],
        fixtures: [],
      });
    await writeFile(
      join(made.rootPath, "data", "fixtures", "2025-men-gac.json"),
      fixture(2025, "GAC"),
    );
    await writeFile(
      join(made.rootPath, "data", "fixtures", "2026-men-gac.json"),
      fixture(2026, "GAC"),
    );
    await writeFile(
      join(made.rootPath, "data", "fixtures", "2026-men-lsc.json"),
      fixture(2026, "LSC"),
    );

    rib.registerTools?.(ctx);
    const project = projects[0];
    if (!project) throw new Error("init registered no project");
    setScope(project.id);

    const sole = await rib.onAction?.(
      {
        type: "select-season",
        payload: { season: 2025, gender: "men" },
      },
      ctx,
    );
    expect(sole).toEqual({ ok: true });
    expect(await composeTouchlineBoard()).toContain("2025");

    const ambiguous = await rib.onAction?.(
      {
        type: "select-season",
        payload: { season: 2026, gender: "men" },
      },
      ctx,
    );
    expect(ambiguous).toMatchObject({ ok: false });
    if (ambiguous && !ambiguous.ok) expect(ambiguous.error).toContain("must name conference");

    const explicit = await rib.onAction?.(
      {
        type: "select-season",
        payload: { season: 2026, gender: "men", conference: "lsc" },
      },
      ctx,
    );
    expect(explicit).toEqual({ ok: true });
    expect(await composeTouchlineBoard()).toContain("LSC");
  });

  test("creating a second home leaves the active data home where it was, and says which it is", async () => {
    const workspace = await tempRoot("second-home");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(workspace, "config.json");
    const projects: Project[] = [];
    const ctx = fakeContext(projects);

    // the first home, with nothing active yet, becomes the active one
    const first = await initTouchlineHome("d2-soccer", ctx);
    expect(first).toMatchObject({ ok: true, activated: true });
    const d2 = join(workspace, "d2-soccer");
    expect((await readActivationConfig()).ok && (await readActivationConfig())).toMatchObject({
      value: { dataDir: d2 },
    });

    // the second does not move it — through the tool, as an agent calls it
    const init = makeTouchlineTools({ ctx, refreshBoard: () => undefined }).find(
      (t) => t.name === "touchline_init",
    );
    let reply = "";
    await init?.execute({ name: "d1-soccer", level: "d1" }, {
      emit: (chunk: { content?: string }) => {
        reply += chunk.content ?? "";
      },
    } as never);
    const config = JSON.parse(await readFile(process.env.TOUCHLINE_CONFIG_PATH, "utf8"));
    expect(config.dataDir).toBe(d2);
    expect(reply).toContain(
      `The active Touchline data home is still ${d2}; creating a home does not switch it.`,
    );
    expect(reply).toContain(
      "It collects NCAA d1; a collect of a conference at another level is refused.",
    );
    expect(await readFile(join(workspace, "d1-soccer", "touchline-data.yaml"), "utf8")).toContain(
      "\nlevel: d1\n",
    );
    // an explicit switch is still the picker's to make
    rib.registerTools?.(ctx);
    const d1Project = projects.find((p) => p.name === "d1-soccer");
    if (!d1Project) throw new Error("init registered no d1 project");
    expect(
      await rib.onAction?.({ type: "select-project", payload: { scopeId: d1Project.id } }, ctx),
    ).toEqual({ ok: true });
    expect(JSON.parse(await readFile(process.env.TOUCHLINE_CONFIG_PATH, "utf8")).dataDir).toBe(
      join(workspace, "d1-soccer"),
    );
    setScope(undefined);
  });

  test("init writes a level into a new marker, declares one on an unlevelled home, and refuses to change one", async () => {
    const workspace = await tempRoot("init-level");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(workspace, "config.json");
    const ctx = fakeContext([]);

    const plain = await initTouchlineHome("plain", ctx);
    expect(plain).toMatchObject({ ok: true, level: { level: "d2", declared: true } });
    expect(await readFile(join(workspace, "plain", "touchline-data.yaml"), "utf8")).toContain(
      "\nlevel: d2\n",
    );

    // a pre-level home: no level line until one is declared
    const old = join(workspace, "old-home");
    await mkdir(old);
    await writeFile(join(old, "touchline-data.yaml"), "kind: touchline-data\nversion: 1\n");
    const declared = await initTouchlineHome("old-home", ctx, { level: "d2" });
    expect(declared).toMatchObject({ ok: true, created: false, levelWritten: true });
    expect(await readFile(join(old, "touchline-data.yaml"), "utf8")).toBe(
      "kind: touchline-data\nversion: 1\nlevel: d2\n",
    );

    const changed = await initTouchlineHome("old-home", ctx, { level: "d1" });
    expect(changed.ok).toBe(false);
    if (!changed.ok) expect(changed.error).toContain("is already a d2 data home");
  });

  test("the init and remove tools are registered so MCP and chat can reach them", () => {
    const names = makeTouchlineTools({
      ctx: fakeContext([]),
      refreshBoard: () => undefined,
    }).map((t) => t.name);
    expect(names).toContain("touchline_init");
    expect(names).toContain("touchline_remove");
  });
});

describe("collecting a season", () => {
  // The collector reuses a stored box score whenever the fixture's result is
  // unchanged, so a parser change never reaches stored boxes unless the call
  // asks to re-fetch. The tool must pass --refetch through exactly when asked.
  async function collectCommand(
    label: string,
    extra: Record<string, unknown>,
  ): Promise<string[] | undefined> {
    const workspace = await tempRoot(`collect-${label}`);
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(workspace, "config.json");
    const projects: Project[] = [];
    const base = fakeContext(projects);
    let command: string[] | undefined;
    const ctx: RibContext = {
      ...base,
      getExec: () => ({
        ...base.getExec(),
        runText: async (cmd, args, opts) => {
          if (cmd === "uv" && args[0] === "run") {
            command = args;
            return { ok: true as const, data: "collected", exitCode: 0 };
          }
          return base.getExec().runText(cmd, args, opts);
        },
      }),
    };
    const home = await initTouchlineHome(`collect-${label}`, ctx);
    if (!home.ok) throw new Error(home.error);
    const collect = makeTouchlineTools({ ctx, refreshBoard: () => undefined }).find(
      (t) => t.name === "touchline_collect",
    );
    expect(collect).toBeDefined();
    let report = "";
    await collect?.execute(
      { target: "GAC", gender: "men", season: 2026, project: `collect-${label}`, ...extra },
      {
        emit: (chunk: { content?: string }) => {
          report += chunk.content ?? "";
        },
      } as never,
    );
    expect(report).toContain("Board now showing");
    return command;
  }

  test("refetch: true passes --refetch to collect-board", async () => {
    const command = await collectCommand("on", { refetch: true });
    expect(command).toContain("collect-board");
    expect(command).toContain("--refetch");
  });

  test("refetch false or absent leaves --refetch off", async () => {
    for (const [label, extra] of [
      ["off", { refetch: false }],
      ["absent", {}],
    ] as const) {
      const command = await collectCommand(label, extra);
      expect(command).toContain("collect-board");
      expect(command).not.toContain("--refetch");
    }
  });
});

describe("the collect tool's level guard", () => {
  async function attempt(level: string | undefined, target: string) {
    const workspace = await tempRoot(`guard-${level ?? "none"}-${target}`);
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(workspace, "config.json");
    const root = join(workspace, "home");
    await mkdir(root);
    await writeFile(
      join(root, "touchline-data.yaml"),
      `kind: touchline-data\nversion: 1\n${level ? `level: ${level}\n` : ""}`,
    );
    const projects: Project[] = [
      { id: "p-home", name: "home", rootPath: root, createdAt: "2026-11-15T00:00:00Z" },
    ];
    const base = fakeContext(projects);
    let fetched = false;
    const ctx: RibContext = {
      ...base,
      getExec: () => ({
        ...base.getExec(),
        runText: async (cmd, args, opts) => {
          if (cmd === "uv") {
            fetched = true;
            return { ok: true as const, data: "collected", exitCode: 0 };
          }
          return base.getExec().runText(cmd, args, opts);
        },
      }),
    };
    const collect = makeTouchlineTools({ ctx, refreshBoard: () => undefined }).find(
      (t) => t.name === "touchline_collect",
    );
    let report = "";
    let isError = false;
    await collect?.execute({ target, gender: "men", season: 2026, project: "home" }, {
      emit: (chunk: { content?: string; isError?: boolean }) => {
        report += chunk.content ?? "";
        isError ||= chunk.isError === true;
      },
    } as never);
    return { report, isError, fetched, root };
  }

  test("a D1 conference into a d2 home, and a D2 conference into a d1 home, are refused before any fetch", async () => {
    const intoD2 = await attempt("d2", "ACC");
    expect(intoD2.isError).toBe(true);
    expect(intoD2.fetched).toBe(false);
    expect(intoD2.report).toContain(
      `REFUSED: ACC is a d1 conference and the data home ${intoD2.root} collects d2 (declared in its marker).`,
    );
    const intoD1 = await attempt("d1", "GAC");
    expect(intoD1.isError).toBe(true);
    expect(intoD1.fetched).toBe(false);
    expect(intoD1.report).toContain(
      `REFUSED: GAC is a d2 conference and the data home ${intoD1.root} collects d1 (declared in its marker).`,
    );
    // a programme is held to its own level: Harding is a d2 programme
    const programme = await attempt("d1", "Harding");
    expect(programme.fetched).toBe(false);
    expect(programme.report).toContain("is a d2 conference");
  });

  test("a home with no level is read as d2, and the reply says it assumed so", async () => {
    const d1 = await attempt(undefined, "ACC");
    expect(d1.fetched).toBe(false);
    expect(d1.report).toContain("collects d2 (assumed: its marker declares no level)");
    const d2 = await attempt(undefined, "GAC");
    expect(d2.isError).toBe(false);
    expect(d2.fetched).toBe(true);
    expect(d2.report).toContain("declares no level, so it is read as d2");
    // and the collect left the marker as it was
    expect(await readFile(join(d2.root, "touchline-data.yaml"), "utf8")).toBe(
      "kind: touchline-data\nversion: 1\n",
    );
  });
});

describe("removing a data home", () => {
  async function home(name: string): Promise<{ root: string; ctx: RibContext; ps: Project[] }> {
    const workspace = await tempRoot(`rm-${name}`);
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(workspace, "config.json");
    const ps: Project[] = [];
    const ctx = fakeContext(ps);
    const created = await initTouchlineHome(name, ctx);
    if (!created.ok) throw new Error(created.error);
    return { root: created.rootPath, ctx, ps };
  }

  test("the plan reports what would be lost before anything is removed", async () => {
    const { root, ctx } = await home("doomed");
    await writeFile(
      join(root, "data", "rosters", "2019-men-gac.json"),
      JSON.stringify({
        schema: "touchline.rosters/1",
        season: 2019,
        gender: "men",
        collected_at: "2026-08-09T00:00:00Z",
        rosters: { harding: { programme: "harding", players: [{ name: "A" }, { name: "B" }] } },
      }),
      "utf8",
    );

    const planned = await planTouchlineRemoval("doomed", ctx);
    expect(planned.ok).toBe(true);
    if (!planned.ok) return;
    expect(planned.plan.isDataHome).toBe(true);
    expect(planned.plan.blocked).toBeUndefined();
    expect(planned.plan.seasons).toEqual([
      { season: 2019, gender: "men", fixtures: 0, players: 2 },
    ]);
    // Planning must never mutate.
    expect(await dataHomeState(root)).toMatchObject({ state: "ready" });
  });

  test("deleting without the exact confirmation removes nothing", async () => {
    const { root, ctx } = await home("guarded");
    const wrong = await removeTouchlineHome("guarded", ctx, {
      deleteData: true,
      confirm: "guarded ",
    });
    expect(wrong.ok).toBe(false);
    if (!wrong.ok) expect(wrong.error).toContain("confirm exactly equal to the project name");
    expect(await dataHomeState(root)).toMatchObject({ state: "ready" });
  });

  test("unregistering by default leaves every file on disk", async () => {
    const { root, ctx, ps } = await home("keepdata");
    const result = await removeTouchlineHome("keepdata", ctx, { deleteData: false });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.message).toContain("data is untouched");
    expect(await dataHomeState(root)).toMatchObject({ state: "ready" });
    expect(ps.find((p) => p.name === "keepdata")).toBeUndefined();
  });

  test("a confirmed delete removes the folder", async () => {
    const { root, ctx } = await home("gone");
    const result = await removeTouchlineHome("gone", ctx, {
      deleteData: true,
      confirm: "gone",
    });
    expect(result.ok).toBe(true);
    await expect(stat(root)).rejects.toThrow();
  });

  test("a git repository is refused even with a correct confirmation", async () => {
    // soccer-data is exactly this: a marked Touchline home that is also tracked
    // work. No confirmation should be able to delete somebody's repository.
    const { root, ctx } = await home("tracked");
    await mkdir(join(root, ".git"), { recursive: true });

    const planned = await planTouchlineRemoval("tracked", ctx);
    expect(planned.ok).toBe(true);
    if (planned.ok) expect(planned.plan.blocked).toContain("git repository");

    const result = await removeTouchlineHome("tracked", ctx, {
      deleteData: true,
      confirm: "tracked",
    });
    expect(result.ok).toBe(false);
    expect(await dataHomeState(root)).toMatchObject({ state: "ready" });
  });

  test("an unmarked folder is never deleted", async () => {
    const workspace = await tempRoot("rm-unmarked");
    process.env.KEELSON_WORKSPACE = workspace;
    const target = join(workspace, "someones-work");
    await mkdir(target, { recursive: true });
    await writeFile(join(target, "keep.txt"), "mine", "utf8");
    const ps: Project[] = [{ id: "x1", name: "someones-work", rootPath: target } as Project];
    const ctx = fakeContext(ps);

    const result = await removeTouchlineHome("someones-work", ctx, {
      deleteData: true,
      confirm: "someones-work",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("no Touchline marker");
    expect(await readFile(join(target, "keep.txt"), "utf8")).toBe("mine");
  });

  test("an existing occupied workspace child is refused without changing it", async () => {
    const workspace = await tempRoot("occupied-workspace");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(workspace, "config.json");
    const target = join(workspace, "taken");
    await mkdir(target);
    await Bun.write(join(target, "keep.txt"), "mine");

    const result = await invokeTouchlineCommand("taken", fakeContext([]));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain("already holds other work");
    expect(await readFile(join(target, "keep.txt"), "utf8")).toBe("mine");
    await expect(stat(join(target, "touchline-data.yaml"))).rejects.toThrow();
  });
});

describe("status reporting", () => {
  test("a final without a published score is reported as played", async () => {
    // The collect summary and the status report must agree on what played
    // means. This call site once kept an inline copy of the pre-#47
    // predicate (final AND a numeric score) and reported the same shard as
    // "0 played" that collection had just announced as "2 played" — the
    // isPlayed unit test alone would not catch that revert.
    const workspace = await tempRoot("status-workspace");
    const configRoot = await tempRoot("status-config");
    process.env.KEELSON_WORKSPACE = workspace;
    process.env.TOUCHLINE_CONFIG_PATH = join(configRoot, "config.json");
    const projects: Project[] = [];
    const ctx = fakeContext(projects);
    const home = await initTouchlineHome("status-home", ctx);
    expect(home.ok).toBe(true);
    if (!home.ok) return;

    const fixturesDir = join(home.rootPath, "data", "fixtures");
    await mkdir(fixturesDir, { recursive: true });
    await writeFile(
      join(fixturesDir, "2026-men-gac.json"),
      JSON.stringify({
        schema: "touchline.fixtures/2",
        season: 2026,
        gender: "men",
        conference: "GAC",
        collected_at: "2026-08-21T13:00:00+00:00",
        programmes: [],
        fixtures: [
          {
            id: "sidearm:rogers-state:7655",
            date: "2026-08-13",
            home: "rogers-state",
            away: "oklahoma-wesleyan",
            status: "final",
            match_type: "exhibition",
          },
          {
            id: "sidearm:rogers-state:7656",
            date: "2026-08-18",
            home: "rogers-state",
            away: "southwestern-christian",
            status: "scheduled",
          },
        ],
      }),
    );

    const tools = makeTouchlineTools({ ctx, refreshBoard: () => undefined });
    const status = tools.find((t) => t.name === "touchline_status");
    expect(status).toBeDefined();
    let report = "";
    await status?.execute({ project: "status-home" }, {
      emit: (chunk: { content?: string }) => {
        report += chunk.content ?? "";
      },
    } as never);
    expect(report).toContain("1 played");
  });
});
