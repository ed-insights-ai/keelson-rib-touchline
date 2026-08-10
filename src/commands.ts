// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { mkdir, readdir, rm, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import type {
  CommandInvokeResult,
  Project,
  RibCommandDescriptor,
  RibContext,
} from "@keelson/shared";
import { ensureActivationConfig } from "./activation.ts";
import { TOUCHLINE_AGENT_SLUG } from "./agent.ts";
import {
  bootstrapDataHome,
  dataHomeState,
  explainRefusal,
  listSeasons,
  loadFixtures,
  loadRosters,
} from "./datahome.ts";
import { findProject, setScope } from "./state.ts";

export const TOUCHLINE_COMMAND: RibCommandDescriptor = {
  name: "touchline",
  description: "Create and initialize a Touchline project, or open Touchline.",
  argument: {
    hint: "folder-name (optional)",
  },
};

function openAgent(): CommandInvokeResult {
  return {
    ok: true,
    effect: { effect: "open-agent", ribId: "touchline", slug: TOUCHLINE_AGENT_SLUG },
  };
}

/** Match Keelson's own server default exactly: KEELSON_WORKSPACE when set,
 * otherwise ~/keelson. A Touchline home is an ordinary child directory here;
 * project registration supplies UI/workflow scope and does NOT imply Git. */
export function keelsonWorkspacePath(
  env: Readonly<Record<string, string | undefined>> = process.env,
): string {
  return resolve(env.KEELSON_WORKSPACE?.trim() || join(homedir(), "keelson"));
}

export function touchlineProjectPath(
  name: string,
  env: Readonly<Record<string, string | undefined>> = process.env,
): string {
  return join(keelsonWorkspacePath(env), name);
}

function validateFolderName(
  raw: string,
): { ok: true; name: string } | { ok: false; error: string } {
  const name = raw.trim();
  if (!name) return { ok: false, error: "Folder name is empty." };
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(name)) {
    return {
      ok: false,
      error:
        "Use a lowercase folder name of up to 64 letters, numbers, dashes, or underscores — for example /touchline gac-soccer.",
    };
  }
  return { ok: true, name };
}

function conflict(
  projects: readonly Project[],
  name: string,
  rootPath: string,
): string | undefined {
  const sameName = projects.find((p) => p.name.toLowerCase() === name.toLowerCase());
  if (sameName && sameName.rootPath !== rootPath) {
    return `A Keelson project named '${name}' already points at ${sameName.rootPath}. Nothing was changed.`;
  }
  const samePath = projects.find((p) => p.rootPath === rootPath);
  if (samePath && samePath.name.toLowerCase() !== name.toLowerCase()) {
    return `${rootPath} is already registered as the Keelson project '${samePath.name}'. Nothing was changed.`;
  }
  return undefined;
}

export type InitHomeResult =
  | {
      ok: true;
      name: string;
      rootPath: string;
      /** False when a previous run had already initialized this folder. */
      created: boolean;
      registered: boolean;
    }
  | { ok: false; error: string };

/**
 * Create, initialize and register a Touchline data home.
 *
 * This is shared by BOTH entry points on purpose. `/touchline <name>` is a
 * composer affordance: the chat CLI and MCP cannot invoke a slash command, so a
 * rib whose only path to a data home is the command leaves an agent unable to
 * complete the very first step of the product — and an agent that cannot act
 * tends to narrate a plausible failure instead of naming the gap. The
 * `touchline_init` tool calls this same function so the two cannot drift.
 */
export async function initTouchlineHome(rawName: string, ctx: RibContext): Promise<InitHomeResult> {
  const parsed = validateFolderName(rawName);
  if (!parsed.ok) return parsed;
  const name = parsed.name;
  const rootPath = touchlineProjectPath(name);
  const before = ctx.getProjects?.() ?? [];
  const conflictMessage = conflict(before, name, rootPath);
  if (conflictMessage) return { ok: false, error: conflictMessage };

  const existing = before.find(
    (p) => p.name.toLowerCase() === name.toLowerCase() && p.rootPath === rootPath,
  );

  let home = await dataHomeState(rootPath);
  if (home.state === "missing") {
    try {
      // Recursive: the Keelson workspace itself may not exist on a fresh
      // install, and an ENOENT naming a parent directory is not an error a
      // first-time user can act on.
      await mkdir(rootPath, { recursive: true });
    } catch (err) {
      return {
        ok: false,
        error: `Could not create ${rootPath}: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
    home = await dataHomeState(rootPath);
  }
  if (home.state !== "empty" && home.state !== "ready") {
    return {
      ok: false,
      error: explainRefusal(rootPath, home) ?? `${rootPath} cannot be initialized.`,
    };
  }

  let alreadyMarked = false;
  try {
    const boot = await bootstrapDataHome(rootPath);
    alreadyMarked = boot.alreadyMarked;
    await ensureActivationConfig(rootPath);
  } catch (err) {
    return {
      ok: false,
      error: `Could not initialize ${rootPath}: ${err instanceof Error ? err.message : String(err)}`,
    };
  }

  if (!existing) {
    const registered = await ctx.getExec().runText("keelson", ["project", "add", name, rootPath], {
      timeoutMs: 30_000,
      acceptNonZeroExit: true,
    });
    if (!registered.ok) {
      return {
        ok: false,
        error: `Touchline initialized ${rootPath}, but Keelson could not register it: ${registered.error}`,
      };
    }
    if (registered.exitCode != null && registered.exitCode !== 0) {
      return {
        ok: false,
        error: `Touchline initialized ${rootPath}, but Keelson project registration exited ${registered.exitCode}: ${registered.data.trim()}`,
      };
    }
  }

  const projects = ctx.getProjects?.() ?? [];
  const project =
    projects.find((p) => p.name.toLowerCase() === name.toLowerCase() && p.rootPath === rootPath) ??
    existing;
  if (project) setScope(project.id);
  return {
    ok: true,
    name,
    rootPath,
    created: !alreadyMarked,
    registered: !existing,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Removal. A data home holds collected data, so the destructive path is gated
// behind an informed confirmation rather than a boolean: the caller must first
// be told what would be lost, then repeat the project's own name back.
//
// Three refusals are absolute and cannot be confirmed away:
//   · a folder carrying no Touchline marker — we never delete what we did not
//     create, which is the same rule that governs collection;
//   · a git repository — that is somebody's tracked work, and `soccer-data` is
//     exactly such a home, marker and all;
//   · the workspace root or a home directory.
// ─────────────────────────────────────────────────────────────────────────────

export interface RemovalPlan {
  name: string;
  rootPath: string;
  isDataHome: boolean;
  isGitRepo: boolean;
  seasons: { season: number; gender: string; fixtures: number; players: number }[];
  rawPages: number;
  /** Absent when nothing blocks deletion. */
  blocked?: string;
}

async function countFiles(dir: string): Promise<number> {
  try {
    const entries = await readdir(dir, { withFileTypes: true, recursive: true });
    return entries.filter((e) => e.isFile()).length;
  } catch {
    return 0;
  }
}

export async function planTouchlineRemoval(
  nameOrId: string,
  ctx: RibContext,
): Promise<{ ok: true; plan: RemovalPlan } | { ok: false; error: string }> {
  const projects = ctx.getProjects?.() ?? [];
  const project = findProject(projects, nameOrId);
  if (!project) {
    return {
      ok: false,
      error: `No Keelson project named '${nameOrId}'. Registered: ${
        projects.map((p) => p.name).join(", ") || "(none)"
      }`,
    };
  }
  const root = project.rootPath;
  const home = await dataHomeState(root);
  const isDataHome = home.state === "ready";

  const seasons = [];
  for (const ref of isDataHome ? await listSeasons(root) : []) {
    const fx = await loadFixtures(root, ref.season, ref.gender);
    const rs = await loadRosters(root, ref.season, ref.gender);
    seasons.push({
      season: ref.season,
      gender: ref.gender,
      fixtures: fx.ok ? fx.value.fixtures.length : 0,
      players: rs.ok
        ? Object.values(rs.value.rosters).reduce((n, r) => n + r.players.length, 0)
        : 0,
    });
  }

  const isGitRepo = await stat(join(root, ".git"))
    .then(() => true)
    .catch(() => false);

  const workspace = keelsonWorkspacePath();
  const forbidden = resolve(root) === workspace || resolve(root) === resolve(homedir());

  let blocked: string | undefined;
  if (forbidden) {
    blocked = `${root} is the Keelson workspace root or your home directory. Touchline will not delete it.`;
  } else if (isGitRepo) {
    blocked = `${root} is a git repository — that is tracked work, not a disposable data home. Remove the project registration instead, and delete the folder yourself if you really mean to.`;
  } else if (!isDataHome) {
    blocked = `${root} carries no Touchline marker, so Touchline will not delete it. It only deletes folders it created.`;
  }

  return {
    ok: true,
    plan: {
      name: project.name,
      rootPath: root,
      isDataHome,
      isGitRepo,
      seasons,
      rawPages: isDataHome ? await countFiles(join(root, "data", "raw_html")) : 0,
      ...(blocked ? { blocked } : {}),
    },
  };
}

export async function removeTouchlineHome(
  nameOrId: string,
  ctx: RibContext,
  opts: { deleteData: boolean; confirm?: string },
): Promise<{ ok: true; message: string } | { ok: false; error: string }> {
  const planned = await planTouchlineRemoval(nameOrId, ctx);
  if (!planned.ok) return planned;
  const { plan } = planned;

  if (opts.deleteData) {
    if (plan.blocked) return { ok: false, error: plan.blocked };
    if (opts.confirm !== plan.name) {
      return {
        ok: false,
        error: `Deletion not confirmed. To delete ${plan.rootPath} and everything in it, pass confirm exactly equal to the project name: "${plan.name}".`,
      };
    }
  }

  const unregistered = await ctx.getExec().runText("keelson", ["project", "remove", plan.name], {
    timeoutMs: 30_000,
    acceptNonZeroExit: true,
  });
  if (!unregistered.ok || (unregistered.exitCode != null && unregistered.exitCode !== 0)) {
    return {
      ok: false,
      error: `Could not unregister '${plan.name}': ${unregistered.ok ? unregistered.data.trim() : unregistered.error}. Nothing was deleted.`,
    };
  }

  if (!opts.deleteData) {
    return {
      ok: true,
      message: `Unregistered '${plan.name}'. The data is untouched at ${plan.rootPath} — re-register it any time, or delete it with delete_data.`,
    };
  }

  try {
    await rm(plan.rootPath, { recursive: true, force: true });
  } catch (err) {
    return {
      ok: false,
      error: `Unregistered '${plan.name}', but could not delete ${plan.rootPath}: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
  setScope(undefined);
  return {
    ok: true,
    message: `Deleted ${plan.rootPath} and unregistered '${plan.name}'. This removed ${plan.seasons.length} season file(s) and ${plan.rawPages} archived source page(s). It cannot be undone.`,
  };
}

export async function invokeTouchlineCommand(
  arg: string,
  ctx: RibContext,
): Promise<CommandInvokeResult> {
  if (!arg.trim()) return openAgent();
  const result = await initTouchlineHome(arg, ctx);
  if (!result.ok) return { ok: false, error: result.error };
  return openAgent();
}
