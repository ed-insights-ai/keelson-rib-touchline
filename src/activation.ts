// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { randomUUID } from "node:crypto";
import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { RibAuthStatus, RibContext } from "@keelson/shared";
import { dataHomeState, explainRefusal, packageDir } from "./datahome.ts";

/**
 * The activation file has two jobs:
 *
 * 1. Give workflow subprocesses a stable route back to the installed package.
 * 2. Remember the most recently selected Touchline data home for CLI/status
 *    calls that happen outside the surface's in-memory project selection.
 *
 * `TOUCHLINE_DATA_DIR` always wins over the remembered directory. This keeps
 * tests, one-off CLI runs, and recovery work explicit and reversible.
 */
export interface ActivationConfig {
  packageDir: string;
  dataDir?: string;
}

interface ActivationOptions {
  configPath?: string;
  env?: Readonly<Record<string, string | undefined>>;
}

export type ConfigReadResult =
  | { ok: true; value?: ActivationConfig }
  | { ok: false; error: string };

export type DataDirResolution =
  | { ok: true; dataDir?: string; source: "env" | "config" | "none" }
  | { ok: false; error: string };

export function activationConfigPath(
  env: Readonly<Record<string, string | undefined>> = process.env,
): string {
  const override = env.TOUCHLINE_CONFIG_PATH?.trim();
  const keelsonHome = env.KEELSON_HOME?.trim() || join(homedir(), ".keelson");
  return override || join(keelsonHome, "rib-touchline", "config.json");
}

function pathFor(opts: ActivationOptions): string {
  return opts.configPath ?? activationConfigPath(opts.env);
}

export async function readActivationConfig(
  opts: ActivationOptions = {},
): Promise<ConfigReadResult> {
  const path = pathFor(opts);
  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code === "ENOENT") return { ok: true };
    return { ok: false, error: `cannot read ${path}: ${String(err)}` };
  }

  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    return { ok: false, error: `${path} is not valid JSON: ${String(err)}` };
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, error: `${path} must contain a JSON object` };
  }
  const record = raw as Record<string, unknown>;
  if (record.packageDir !== undefined && typeof record.packageDir !== "string") {
    return { ok: false, error: `${path} has a non-string packageDir` };
  }
  if (record.dataDir !== undefined && typeof record.dataDir !== "string") {
    return { ok: false, error: `${path} has a non-string dataDir` };
  }

  return {
    ok: true,
    value: {
      packageDir: typeof record.packageDir === "string" ? record.packageDir : packageDir(),
      ...(typeof record.dataDir === "string" && record.dataDir.trim()
        ? { dataDir: record.dataDir }
        : {}),
    },
  };
}

/** Write atomically so a process interruption cannot leave half a JSON file. */
export async function ensureActivationConfig(
  dataDir?: string,
  opts: ActivationOptions = {},
): Promise<ActivationConfig> {
  const path = pathFor(opts);
  const existing = await readActivationConfig({ ...opts, configPath: path });
  if (!existing.ok) throw new Error(existing.error);

  const value: ActivationConfig = {
    packageDir: packageDir(),
    ...(dataDir?.trim()
      ? { dataDir }
      : existing.value?.dataDir
        ? { dataDir: existing.value.dataDir }
        : {}),
  };
  // Activation owns packageDir and dataDir and nothing else. The file also
  // carries settings other readers own — the daily cadence's "genders" and
  // "conferences" (bin/touchline-collect-cadence.sh) — and rewriting it with
  // only the two keys this function sets silently erased them on every server
  // start. Every other key the file holds is kept as it was.
  const kept = await readOtherKeys(path);
  await mkdir(dirname(path), { recursive: true });
  const temp = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temp, `${JSON.stringify({ ...kept, ...value }, null, 2)}\n`, "utf8");
  await rename(temp, path);
  return value;
}

/** The keys of the config file activation does not own, as written. The file
 *  was already validated by readActivationConfig, so a missing file is the
 *  only case left to tolerate. */
async function readOtherKeys(path: string): Promise<Record<string, unknown>> {
  let raw: unknown;
  try {
    raw = JSON.parse(await readFile(path, "utf8"));
  } catch {
    return {};
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const { packageDir: _p, dataDir: _d, ...rest } = raw as Record<string, unknown>;
  return rest;
}

export async function resolveActivationDataDir(
  opts: ActivationOptions = {},
): Promise<DataDirResolution> {
  const env = opts.env ?? process.env;
  const override = env.TOUCHLINE_DATA_DIR?.trim();
  if (override) return { ok: true, dataDir: override, source: "env" };

  const config = await readActivationConfig(opts);
  if (!config.ok) return config;
  if (config.value?.dataDir) {
    return { ok: true, dataDir: config.value.dataDir, source: "config" };
  }
  return { ok: true, source: "none" };
}

async function pipelineExists(): Promise<boolean> {
  try {
    await access(join(packageDir(), "pipeline", "pyproject.toml"));
    return true;
  } catch {
    return false;
  }
}

/** The status shown by `keelson rib show touchline`. Never throws. */
export async function touchlineAuthStatus(ctx: RibContext): Promise<RibAuthStatus> {
  try {
    await ensureActivationConfig();
  } catch (err) {
    return {
      authenticated: false,
      statusMessage: `Touchline activation config is invalid: ${err instanceof Error ? err.message : String(err)}`,
    };
  }

  if (!(await pipelineExists())) {
    return {
      authenticated: false,
      statusMessage: `Touchline pipeline is missing from ${join(packageDir(), "pipeline")}. Reinstall the rib.`,
    };
  }

  const uv = await ctx.getExec().runText("uv", ["--version"], { timeoutMs: 5_000 });
  if (!uv.ok) {
    return {
      authenticated: false,
      statusMessage:
        "Touchline is installed, but uv is not available. Install uv before collecting.",
    };
  }

  const resolved = await resolveActivationDataDir();
  if (!resolved.ok) return { authenticated: false, statusMessage: resolved.error };
  if (!resolved.dataDir) {
    return {
      authenticated: false,
      statusMessage:
        "Touchline is installed and uv is available. Select an empty Keelson project to initialize its data home.",
    };
  }

  const home = await dataHomeState(resolved.dataDir);
  if (home.state === "ready") {
    return {
      authenticated: true,
      statusMessage: `Ready — Touchline data home at ${resolved.dataDir} (${resolved.source}).`,
    };
  }
  if (home.state === "empty") {
    return {
      authenticated: false,
      statusMessage: `${resolved.dataDir} is empty and ready to initialize from the Touchline surface.`,
    };
  }
  return {
    authenticated: false,
    statusMessage: explainRefusal(resolved.dataDir, home),
  };
}
