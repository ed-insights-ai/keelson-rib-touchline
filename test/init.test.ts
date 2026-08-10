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
import rib from "../src/index.ts";
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

  test("the init and remove tools are registered so MCP and chat can reach them", () => {
    const names = makeTouchlineTools({
      ctx: fakeContext([]),
      refreshBoard: () => undefined,
    }).map((t) => t.name);
    expect(names).toContain("touchline_init");
    expect(names).toContain("touchline_remove");
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
      join(root, "data", "rosters", "2019-men.json"),
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
