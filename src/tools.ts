// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import type { Project, RibContext, ToolContext, ToolDefinition } from "@keelson/shared";
import { z } from "zod";
import { initTouchlineHome, planTouchlineRemoval, removeTouchlineHome } from "./commands.ts";
import {
  bootstrapDataHome,
  conferenceSlug,
  dataHomeState,
  explainRefusal,
  listSeasons,
  loadFixtures,
  loadRosters,
  packageDir,
} from "./datahome.ts";
import { resolveTargets, titleFromSlug } from "./membership.ts";
import {
  planForSeason,
  planSummary,
  TOUCHLINE_V1_SEASON,
  unsupportedSeasonMessage,
} from "./season.ts";
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
        }. Create one with the touchline_init tool (or /touchline <folder-name> in the composer). It lives in the default Keelson workspace and does not need Git.`,
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
        const fx = await loadFixtures(root, s.season, s.gender, s.conference);
        const rs = await loadRosters(root, s.season, s.gender, s.conference);
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

  // The MCP- and chat-reachable equivalent of `/touchline <name>`. Without it
  // an agent can NAME the slash command but never run one — slash commands are
  // a composer affordance the chat CLI and MCP cannot invoke — so the first
  // step of the product is unreachable from the surface the product is sold on.
  const initTool: ToolDefinition = {
    name: "touchline_init",
    description:
      "Create a new Touchline data home: makes a folder in the Keelson workspace, initializes it, and registers it as a Keelson project. Use when someone wants to start collecting soccer data and has no project yet, or names a project that does not exist. Git is neither required nor initialized. Safe to re-run: an existing Touchline home is reported, never overwritten.",
    inputSchema: z.object({
      name: z
        .string()
        .describe(
          "Folder name, lowercase, e.g. 'gac-soccer'. Created under the Keelson workspace.",
        ),
    }),
    state_changing: true,
    execute: guarded(async (input, tctx) => {
      const { name } = input as { name: string };
      const result = await initTouchlineHome(name, ctx);
      if (!result.ok) return emit(tctx, result.error, true);

      const lines = [
        result.created
          ? `Initialized ${result.rootPath} as a Touchline data home.`
          : `${result.rootPath} was already a Touchline data home — nothing was overwritten.`,
        result.registered
          ? `Registered it as the Keelson project '${result.name}'.`
          : `It was already registered as the Keelson project '${result.name}'.`,
        "",
        `Nothing has been collected yet. Name a conference or programme and a season to fill it — for example "Harding men ${TOUCHLINE_V1_SEASON}".`,
      ];
      refreshBoard();
      emit(tctx, lines.join("\n"));
    }),
  };

  // Removal is deliberately two-step. Called without `confirm` it only REPORTS
  // what would be lost; deleting requires repeating the project's own name back,
  // the way a destructive action should read to whoever is about to approve it.
  const removeTool: ToolDefinition = {
    name: "touchline_remove",
    description:
      "Remove a Touchline project. By default this only unregisters it and leaves every collected file on disk. Deleting the data is a separate, irreversible step that requires confirmation. Call it WITHOUT confirm first to see exactly what would be lost, relay that to the user, and only then call again with confirm.",
    inputSchema: z.object({
      project: z.string().describe("Keelson project name to remove."),
      delete_data: z
        .boolean()
        .optional()
        .describe(
          "Also delete the folder and every collected file. Irreversible. Requires confirm.",
        ),
      confirm: z
        .string()
        .optional()
        .describe("To delete data, this must equal the project name exactly."),
    }),
    state_changing: true,
    requires_confirmation: true,
    execute: guarded(async (input, tctx) => {
      const args = input as { project: string; delete_data?: boolean; confirm?: string };
      const planned = await planTouchlineRemoval(args.project, ctx);
      if (!planned.ok) return emit(tctx, planned.error, true);
      const { plan } = planned;

      const inventory = plan.seasons.length
        ? plan.seasons
            .map(
              (s) =>
                `  ${s.season} ${s.gender}: ${s.fixtures} fixtures, ${s.players} roster players`,
            )
            .join("\n")
        : "  (no collected seasons)";

      // No confirmation supplied — report only, change nothing.
      if (args.delete_data && args.confirm !== plan.name) {
        return emit(
          tctx,
          [
            `Nothing has been deleted. Deleting '${plan.name}' would permanently remove ${plan.rootPath}, containing:`,
            inventory,
            `  ${plan.rawPages} archived source page(s)`,
            "",
            plan.blocked
              ? `REFUSED: ${plan.blocked}`
              : `To proceed, call touchline_remove again with delete_data and confirm exactly "${plan.name}". This cannot be undone. Ask the user before doing so.`,
          ].join("\n"),
          true,
        );
      }

      const result = await removeTouchlineHome(args.project, ctx, {
        deleteData: args.delete_data === true,
        ...(args.confirm ? { confirm: args.confirm } : {}),
      });
      if (!result.ok) return emit(tctx, result.error, true);
      refreshBoard();
      emit(
        tctx,
        args.delete_data ? result.message : `${result.message}\n\nWhat it held:\n${inventory}`,
      );
    }),
  };

  const collectTool: ToolDefinition = {
    name: "touchline_collect",
    description:
      "The front door: collect published college-soccer data for a conference or one programme into the project, and light up the Touchline board. Any season back to 2016 serves its schedule (results included), its roster, its player season statistics, and a box score for every played match from each site's published archive; the rare (site, season) refusal comes back as a named gap. Use when the user asks to get, retrieve, pull down or scrape a schedule, roster, past results, player stats or match statistics.",
    inputSchema: z.object({
      target: z
        .string()
        .optional()
        .describe("Conference or programme name, e.g. 'GAC' or 'Harding'."),
      conference: z
        .string()
        .optional()
        .describe("Backward-compatible conference name. Prefer target."),
      gender: z.enum(["men", "women"]).describe("Which programme."),
      season: z
        .number()
        .int()
        .optional()
        .describe(
          `Season year, ${TOUCHLINE_V1_SEASON} by default. Any year back to 2016 collects that season's schedule, roster, player statistics, and per-match box scores.`,
        ),
      project: z
        .string()
        .optional()
        .describe("Keelson project to collect into. Defaults to the surface's selected project."),
    }),
    state_changing: true,
    execute: guarded(async (input, tctx) => {
      const args = input as {
        target?: string;
        conference?: string;
        gender: string;
        season?: number;
        project?: string;
      };
      const picked = pickProject(projects(), args.project);
      if (!picked.ok) return emit(tctx, picked.message, true);
      const root = picked.project.rootPath;
      const out: string[] = [];

      // 1. Resolve the target from membership data — never a hardcoded list.
      const season = args.season ?? TOUCHLINE_V1_SEASON;
      const plan = planForSeason(season);
      if (plan.empty) {
        return emit(tctx, unsupportedSeasonMessage(season), true);
      }
      out.push(planSummary(plan));
      const subject = args.target ?? args.conference;
      if (!subject) {
        return emit(tctx, "Name a target to collect, such as 'Harding' or 'GAC'.", true);
      }
      const target = await resolveTargets(subject, args.gender, season);
      if (target.kind === "unknown") {
        return emit(
          tctx,
          `Touchline has no ${args.gender} collection recipe for '${subject}'. Known conferences: ${target.knownConferences.join(", ")}. Known programmes: ${target.suggestions.map(titleFromSlug).join(", ")}.`,
          true,
        );
      }
      if (!target.slugs.length) {
        return emit(tctx, `No programmes resolved for ${subject} ${args.gender} ${season}.`, true);
      }
      out.push(
        `Resolved ${target.conference} · ${args.gender} · ${season} → ${target.slugs.length} programme${target.slugs.length === 1 ? "" : "s"}: ${target.slugs
          .map(titleFromSlug)
          .join(", ")}`,
      );
      if (target.extrapolated) {
        out.push(
          `NOTE: the membership record is authored through ${target.authoredThrough}. This ${season} member list is ${target.authoredThrough}'s carried forward — well-founded, but not cited to a ${season} source.`,
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

      // 3. Fetch the official season schedule and roster pages. The collector
      //    asserts the served season before parsing, so a site's silent
      //    fallback to last year cannot land in the data home.
      const exec = ctx.getExec();
      const pipelineDir = `${packageDir()}/pipeline`;
      const command = [
        "run",
        "--project",
        pipelineDir,
        "collect-board",
        "--conference",
        target.conference,
        "--gender",
        args.gender,
        "--season",
        String(season),
        "--programmes",
        target.slugs.join(","),
      ];
      command.push("--layers", plan.attempted.join(","));
      if (target.extrapolated) command.push("--membership-extrapolated");
      const run = await exec.runText("uv", command, {
        cwd: root,
        timeoutMs: 300_000,
        acceptNonZeroExit: true,
        env: { TOUCHLINE_DATA_DIR: root },
      });
      // Exit 0 means the coverage manifest was written and describes reality.
      // Named gaps travel in that manifest and in the run's own output — they
      // are data, not failure, and discarding a good collection because one
      // programme's roster is unpublished would be the worse error.
      if (!run.ok || (run.exitCode != null && run.exitCode !== 0)) {
        out.push(
          !run.ok
            ? `Collection FAILED: ${run.error}`
            : `Collection FAILED (exit ${run.exitCode}): ${run.data.trim()}`,
        );
        emit(tctx, out.join("\n"), true);
        return;
      }
      out.push(run.data.trim());

      // 4. Point the board at what we just built and repaint.
      setScope(picked.project.id);
      setSeason(season, args.gender, conferenceSlug(target.conference));
      setTeam(target.kind === "programme" ? target.slugs[0] : undefined);
      refreshBoard();
      out.push(
        `Board now showing ${target.conference} ${args.gender} ${season}${
          target.kind === "programme" ? ` — ${titleFromSlug(target.slugs[0] as string)}` : ""
        } — open the Touchline surface.`,
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
      conference: z
        .string()
        .optional()
        .describe("Conference name or shard slug, required to disambiguate matching shards."),
      team: z
        .string()
        .optional()
        .describe(
          "Programme slug for the team lens, e.g. 'harding'. Omit to show the whole conference.",
        ),
    }),
    state_changing: true,
    execute: guarded(async (input, tctx) => {
      const args = input as {
        project?: string;
        season?: number;
        gender?: string;
        conference?: string;
        team?: string;
      };
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
      const candidates = seasons.filter(
        (s) =>
          (args.season === undefined || s.season === args.season) &&
          (args.gender === undefined || s.gender === args.gender),
      );
      const requestedConference = args.conference
        ? conferenceSlug(args.conference)
        : undefined;
      const want = requestedConference
        ? candidates.find((s) => s.conference === requestedConference)
        : candidates.length === 1 || (args.season === undefined && args.gender === undefined)
          ? candidates[0]
          : undefined;
      if (!want) {
        return emit(
          tctx,
          candidates.length > 1 && !requestedConference
            ? `More than one conference shard matches; name one of: ${candidates
                .map((s) => s.conference)
                .join(", ")}`
            : `No season file matches. Available: ${seasons
                .map((s) => `${s.season} ${s.gender} ${s.conference}`)
                .join(", ")}`,
          true,
        );
      }
      setSeason(want.season, want.gender, want.conference);
      if (args.team) {
        const fx = await loadFixtures(
          picked.project.rootPath,
          want.season,
          want.gender,
          want.conference,
        );
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

  return [initTool, statusTool, collectTool, focusTool, removeTool];
}
