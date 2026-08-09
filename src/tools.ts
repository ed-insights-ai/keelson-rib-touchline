// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import type { Project, RibContext, ToolContext, ToolDefinition } from "@keelson/shared";
import { z } from "zod";
import {
  bootstrapDataHome,
  dataHomeState,
  explainRefusal,
  listSeasons,
  loadFixtures,
  loadRosters,
  packageDir,
} from "./datahome.ts";
import { resolveConference, titleFromSlug } from "./membership.ts";
import { findProject, getSelection, setScope, setSeason, setTeam } from "./state.ts";

// ─────────────────────────────────────────────────────────────────────────────
// The rib's front door in chat. `execute` returns void — everything the model
// sees is emitted as a tool_result chunk, and every handler is wrapped so a
// throw becomes an honest error result rather than an escaped exception.
// ─────────────────────────────────────────────────────────────────────────────

function emit(ctx: ToolContext, content: string, isError = false): void {
  ctx.emit({ type: "tool_result", toolUseId: "", content, ...(isError ? { isError: true } : {}) });
}

function guarded(
  fn: (input: unknown, ctx: ToolContext) => Promise<void>,
): (input: unknown, ctx: ToolContext) => Promise<void> {
  return async (input, ctx) => {
    try {
      await fn(input, ctx);
    } catch (err) {
      emit(ctx, `touchline tool failed: ${err instanceof Error ? err.message : String(err)}`, true);
    }
  };
}

export interface ToolDeps {
  ctx: RibContext;
  refreshBoard: () => void;
}

/** Resolve which project a tool should act on: an explicit name wins, then the
 *  board's current scope. Ambiguity is reported, never guessed. */
function pickProject(
  projects: readonly Project[],
  explicit: string | undefined,
): { ok: true; project: Project } | { ok: false; message: string } {
  if (explicit) {
    const found = findProject(projects, explicit);
    if (!found) {
      return {
        ok: false,
        message: `No keelson project named '${explicit}'. Registered: ${
          projects.map((p) => p.name).join(", ") || "(none)"
        }. Register one with: keelson project add <name> <dir>`,
      };
    }
    return { ok: true, project: found };
  }
  const scopeId = getSelection().scopeId;
  const scoped = scopeId ? projects.find((p) => p.id === scopeId) : undefined;
  if (scoped) return { ok: true, project: scoped };
  return {
    ok: false,
    message: `No project chosen. Pass project=<name>, or pick one in the Touchline surface's project picker. Registered: ${
      projects.map((p) => p.name).join(", ") || "(none)"
    }`,
  };
}

export function makeTouchlineTools(deps: ToolDeps): ToolDefinition[] {
  const { ctx, refreshBoard } = deps;
  const projects = (): readonly Project[] => ctx.getProjects?.() ?? [];

  const statusTool: ToolDefinition = {
    name: "touchline_status",
    description:
      "Report what soccer data a project holds: whether it is a Touchline data home, which seasons have been collected, how many fixtures and roster players each has, and any named collection gaps. Read-only. Use before collecting to see what already exists.",
    inputSchema: z.object({
      project: z
        .string()
        .optional()
        .describe("Keelson project name. Defaults to the Touchline surface's selected project."),
    }),
    execute: guarded(async (input, tctx) => {
      const args = input as { project?: string };
      const picked = pickProject(projects(), args.project);
      if (!picked.ok) return emit(tctx, picked.message, true);
      const root = picked.project.rootPath;

      const home = await dataHomeState(root);
      if (home.state === "foreign" || home.state === "missing" || home.state === "occupied") {
        return emit(tctx, `${picked.project.name}: ${explainRefusal(root, home)}`, true);
      }
      if (home.state === "empty") {
        return emit(
          tctx,
          `${picked.project.name} (${root}) is an empty folder — ready to become a Touchline data home. Run touchline_collect to initialize it and collect a season.`,
        );
      }

      const seasons = await listSeasons(root);
      if (!seasons.length) {
        return emit(
          tctx,
          `${picked.project.name} (${root}) is a Touchline data home (marker v${home.version}) but holds no collected seasons yet. Run touchline_collect.`,
        );
      }
      const lines: string[] = [
        `${picked.project.name} — ${seasons.length} season file(s) at ${root}`,
      ];
      for (const s of seasons) {
        const fx = await loadFixtures(root, s.season, s.gender);
        const rs = await loadRosters(root, s.season, s.gender);
        if (!fx.ok) {
          lines.push(`  ${s.season} ${s.gender}: UNREADABLE (${fx.reason}) ${fx.path}`);
          continue;
        }
        const played = fx.value.fixtures.filter(
          (f) => f.status === "final" && typeof f.home_score === "number",
        ).length;
        const players = rs.ok
          ? Object.values(rs.value.rosters).reduce((n, r) => n + r.players.length, 0)
          : 0;
        const gaps = [...(fx.value.missing ?? []), ...(rs.ok ? (rs.value.missing ?? []) : [])];
        lines.push(
          `  ${s.season} ${s.gender} (${fx.value.conference}): ${fx.value.programmes.length} programmes, ${fx.value.fixtures.length} fixtures, ${played} played, ${players} roster players${
            gaps.length ? `, GAPS: ${gaps.join(", ")}` : ""
          }${rs.ok ? "" : `, no roster file (${rs.reason})`}`,
        );
      }
      emit(tctx, lines.join("\n"));
    }),
  };

  const collectTool: ToolDefinition = {
    name: "touchline_collect",
    description:
      "The front door: collect a conference season (schedule + rosters) into a project and light up the Touchline board. Resolves a conference name and gender to its member programmes from the membership record, initializes an empty directory as a Touchline data home if needed, then builds the season's fixture and roster files. Use when the user asks to get, retrieve, or scrape a schedule, season, or rosters.",
    inputSchema: z.object({
      conference: z.string().describe("Conference name, e.g. 'GAC'."),
      gender: z.enum(["men", "women"]).describe("Which programme."),
      season: z
        .number()
        .int()
        .optional()
        .describe("Season year, e.g. 2026. Defaults to the most recent season with data."),
      project: z
        .string()
        .optional()
        .describe("Keelson project to collect into. Defaults to the surface's selected project."),
    }),
    state_changing: true,
    execute: guarded(async (input, tctx) => {
      const args = input as {
        conference: string;
        gender: string;
        season?: number;
        project?: string;
      };
      const picked = pickProject(projects(), args.project);
      if (!picked.ok) return emit(tctx, picked.message, true);
      const root = picked.project.rootPath;
      const out: string[] = [];

      // 1. Resolve the target from membership data — never a hardcoded list.
      const season = args.season ?? new Date().getUTCFullYear();
      const res = await resolveConference(args.conference, args.gender, season);
      if (!res.slugs.length) {
        return emit(
          tctx,
          `No programmes resolved for ${res.conference} ${args.gender} ${season}. Conferences the membership record knows: ${res.known.join(", ")}.`,
          true,
        );
      }
      out.push(
        `Resolved ${res.conference} · ${args.gender} · ${season} → ${res.slugs.length} programmes: ${res.slugs
          .map(titleFromSlug)
          .join(", ")}`,
      );
      if (res.extrapolated) {
        out.push(
          `NOTE: the membership record is authored through ${res.authoredThrough}. This ${season} member list is ${res.authoredThrough}'s carried forward — well-founded, but not cited to a ${season} source.`,
        );
      }

      // 2. Make the directory a data home — refusing anything that is neither
      //    empty nor already ours, so a collection can never scribble into a
      //    project the user merely had selected.
      const home = await dataHomeState(root);
      if (home.state !== "empty" && home.state !== "ready") {
        return emit(tctx, explainRefusal(root, home) as string, true);
      }
      const boot = await bootstrapDataHome(root);
      out.push(
        boot.alreadyMarked
          ? `Data home already initialized at ${root}.`
          : `Initialized ${root} as a Touchline data home (${boot.created.length} paths created).`,
      );

      // 3. Build the season files from the local archive.
      const exec = ctx.getExec();
      const pipelineDir = `${packageDir()}/pipeline`;
      const run = await exec.runText(
        "uv",
        [
          "run",
          "--project",
          pipelineDir,
          "export-board",
          "--conference",
          res.conference,
          "--gender",
          args.gender,
          "--season",
          String(season),
          "--programmes",
          res.slugs.join(","),
        ],
        {
          cwd: root,
          timeoutMs: 300_000,
          acceptNonZeroExit: true,
          env: { TOUCHLINE_DATA_DIR: root },
        },
      );
      if (!run.ok) {
        out.push(`Season build FAILED: ${run.error}`);
        emit(tctx, out.join("\n"), true);
        return;
      }
      out.push(run.data.trim());

      // 4. Point the board at what we just built and repaint.
      setScope(picked.project.id);
      setSeason(season, args.gender);
      refreshBoard();
      out.push(
        `Board now showing ${res.conference} ${args.gender} ${season} — open the Touchline surface.`,
      );
      emit(tctx, out.join("\n"));
    }),
  };

  const focusTool: ToolDefinition = {
    name: "touchline_focus",
    description:
      "Point the Touchline board at a season or a single team. Use when the user asks to see a specific team's schedule, or to switch the board to another season.",
    inputSchema: z.object({
      project: z.string().optional().describe("Keelson project name."),
      season: z.number().int().optional().describe("Season year to show."),
      gender: z.enum(["men", "women"]).optional(),
      team: z
        .string()
        .optional()
        .describe(
          "Programme slug for the team lens, e.g. 'harding'. Omit to show the whole conference.",
        ),
    }),
    state_changing: true,
    execute: guarded(async (input, tctx) => {
      const args = input as { project?: string; season?: number; gender?: string; team?: string };
      const picked = pickProject(projects(), args.project);
      if (!picked.ok) return emit(tctx, picked.message, true);
      setScope(picked.project.id);
      const seasons = await listSeasons(picked.project.rootPath);
      if (!seasons.length) {
        return emit(
          tctx,
          `${picked.project.name} holds no collected seasons yet — run touchline_collect first.`,
          true,
        );
      }
      const want = seasons.find(
        (s) =>
          (args.season === undefined || s.season === args.season) &&
          (args.gender === undefined || s.gender === args.gender),
      );
      if (!want) {
        return emit(
          tctx,
          `No season file matches. Available: ${seasons.map((s) => `${s.season} ${s.gender}`).join(", ")}`,
          true,
        );
      }
      setSeason(want.season, want.gender);
      if (args.team) {
        const fx = await loadFixtures(picked.project.rootPath, want.season, want.gender);
        if (fx.ok && !fx.value.programmes.some((p) => p.slug === args.team)) {
          return emit(
            tctx,
            `'${args.team}' is not in ${want.season} ${want.gender}. Programmes: ${fx.value.programmes
              .map((p) => p.slug)
              .join(", ")}`,
            true,
          );
        }
      }
      setTeam(args.team);
      refreshBoard();
      emit(
        tctx,
        `Board now showing ${want.conference} ${want.gender} ${want.season}${
          args.team ? ` — ${titleFromSlug(args.team)}` : " — whole conference"
        }.`,
      );
    }),
  };

  return [statusTool, collectTool, focusTool];
}
