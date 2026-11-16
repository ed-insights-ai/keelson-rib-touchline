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
  homeLevel,
  levelMismatch,
  listSeasons,
  loadFixtures,
  loadRosters,
  packageDir,
} from "./datahome.ts";
import { CONFERENCE_LEVELS, type ConferenceLevel } from "./levels.ts";
import {
  collectFleetSize,
  conferenceProfile,
  emptyResolutionReason,
  knownConferences,
  programmeLevel,
  resolveConference,
  resolveTargets,
  titleFromSlug,
} from "./membership.ts";
import { isPlayed } from "./model.ts";
import {
  collectTimeoutMs,
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

      const level = await homeLevel(root);
      const levelLine = level
        ? `Level: ${level.level} (${level.declared ? "declared in its marker" : `assumed — ${level.note}`}).`
        : "Level: unreadable marker.";
      const seasons = await listSeasons(root);
      if (!seasons.length) {
        return emit(
          tctx,
          `${picked.project.name} (${root}) is a Touchline data home (marker v${home.version}) but holds no collected seasons yet. ${levelLine} Run touchline_collect.`,
        );
      }
      const lines: string[] = [
        `${picked.project.name} — ${seasons.length} season file(s) at ${root}`,
        `  ${levelLine}`,
      ];
      for (const s of seasons) {
        // A shard of another level is what the level guard exists to prevent;
        // one that predates it is named, never hidden.
        const shardLevel = (await conferenceProfile(s.conference))?.level;
        if (level && shardLevel && shardLevel !== level.level) {
          lines.push(
            `  WARNING: ${s.season} ${s.gender} ${s.conference.toUpperCase()} is a ${shardLevel} conference in this ${level.level} home.`,
          );
        }
        const fx = await loadFixtures(root, s.season, s.gender, s.conference);
        const rs = await loadRosters(root, s.season, s.gender, s.conference);
        if (!fx.ok) {
          lines.push(`  ${s.season} ${s.gender}: UNREADABLE (${fx.reason}) ${fx.path}`);
          continue;
        }
        // The shared definition, not an inline copy: a final without a
        // published score is still a played game.
        const played = fx.value.fixtures.filter(isPlayed).length;
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
      level: z
        .enum(CONFERENCE_LEVELS)
        .optional()
        .describe(
          "The one NCAA level this home collects: d1, d2 or d3, written into its marker. A collect of a conference at another level is refused. Defaults to d2 for a new home. An existing home with no level is already d2 (every home made before levels is Division II), so only d2 can be declared on it; any other level is refused.",
        ),
    }),
    state_changing: true,
    execute: guarded(async (input, tctx) => {
      const { name, level } = input as { name: string; level?: ConferenceLevel };
      const result = await initTouchlineHome(name, ctx, level ? { level } : {});
      if (!result.ok) return emit(tctx, result.error, true);

      const levelLine = result.level.declared
        ? `It collects NCAA ${result.level.level}${
            result.levelWritten
              ? " (declared now: its marker had no level)"
              : !result.created || level
                ? ""
                : ` (the default; pass level to make a d1 or d3 home)`
          }; a collect of a conference at another level is refused.`
        : `Its marker declares no level, so it is read as ${result.level.level}. ${result.level.note ?? ""}`;
      const activeLine = result.activated
        ? `It is now the active Touchline data home (there was none).`
        : result.activeDataDir === result.rootPath
          ? `It is the active Touchline data home.`
          : `The active Touchline data home is still ${result.activeDataDir ?? "(none)"}${
              result.activeSource === "env" ? " (TOUCHLINE_DATA_DIR)" : ""
            }; creating a home does not switch it. To work in '${result.name}', name it as the project, or select it in the Touchline surface's project picker.`;
      const lines = [
        result.created
          ? `Initialized ${result.rootPath} as a Touchline data home.`
          : `${result.rootPath} was already a Touchline data home — nothing was overwritten.`,
        result.registered
          ? `Registered it as the Keelson project '${result.name}'.`
          : `It was already registered as the Keelson project '${result.name}'.`,
        levelLine,
        activeLine,
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
      "The front door: collect published college-soccer data for a conference or one programme into the project, and light up the Touchline board. Any season back to 2016 serves its schedule (results included), its roster, its player season statistics, and a box score for every played match from each site's published archive; the rare (site, season) refusal comes back as a named gap. Use when the user asks to get, retrieve, pull down or scrape a schedule, roster, past results, player stats or match statistics. One season per call, and an archive season is a long call — for a multi-season backfill prefer the touchline-collect workflow (workflow_run), which runs each season durably outside any client deadline.",
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
      refetch: z
        .boolean()
        .optional()
        .describe(
          "Re-fetch every stored box score and page instead of reusing unchanged ones, for a parser change.",
        ),
    }),
    state_changing: true,
    execute: guarded(async (input, tctx) => {
      const args = input as {
        target?: string;
        conference?: string;
        gender: string;
        season?: number;
        project?: string;
        refetch?: boolean;
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
      const existingLevel = await homeLevel(root);
      if (target.kind === "unknown") {
        // A home holds one level: offer the conferences it can collect.
        const offered = existingLevel
          ? await knownConferences(existingLevel.level)
          : target.knownConferences;
        return emit(
          tctx,
          `Touchline has no ${args.gender} collection recipe for '${subject}'. Known conferences${
            existingLevel ? ` at this home's level (${existingLevel.level})` : ""
          }: ${offered.join(", ")}. Known programmes: ${target.suggestions.map(titleFromSlug).join(", ")}.`,
          true,
        );
      }
      if (!target.slugs.length) {
        // A conference with no member this season is refused with its reason
        // (past its horizon, every member authored elsewhere; or no window at
        // all), never sent to the collector as an empty or stale list.
        const reason =
          target.kind === "conference"
            ? emptyResolutionReason(await resolveConference(target.conference, args.gender, season))
            : undefined;
        return emit(
          tctx,
          `REFUSED: no programmes resolved for ${subject} ${args.gender} ${season}${reason ? `: ${reason}` : ""}. Nothing was fetched or written.`,
          true,
        );
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
      // 2a. A home collects one NCAA level. The target's level — its
      //     conference's, or for a programme the level its windows put it at
      //     this season — must be the home's, or nothing is fetched: this is
      //     what stops Division I data landing in a Division II home by a slip
      //     of the project picker. An empty folder becomes a home at the
      //     target's level.
      const targetLevel =
        target.kind === "programme"
          ? await programmeLevel(target.slugs[0] as string, args.gender, season)
          : (await conferenceProfile(target.conference))?.level;
      if (!targetLevel) {
        return emit(
          tctx,
          `REFUSED: ${subject} (${target.conference}) has no NCAA level in the membership record, so it cannot be checked against this data home's level. Nothing was fetched or written.`,
          true,
        );
      }
      if (existingLevel) {
        const why = levelMismatch(root, existingLevel, target.conference, targetLevel);
        if (why) return emit(tctx, why, true);
        if (existingLevel.note) out.push(`NOTE: ${existingLevel.note}`);
      }
      // A collect never edits an existing marker: only a new home is given
      // its level here (declaring an old one is touchline_init's job).
      const boot = await bootstrapDataHome(root, existingLevel ? {} : { level: targetLevel });
      out.push(
        boot.alreadyMarked
          ? `Data home already initialized at ${root} (${boot.level.level}).`
          : `Initialized ${root} as a ${boot.level.level} Touchline data home, the level of ${target.conference} (${boot.created.length} paths created).`,
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
      // Stored box scores are reused whenever a fixture's result is unchanged,
      // so a parser change never reaches them without this flag (tl-ir6).
      if (args.refetch === true) command.push("--refetch");
      // Budgeted for the fleet the run can BECOME, not the fleet requested:
      // a one-programme ask against a home already holding this conference-
      // season widens to refresh the whole unit.
      const run = await exec.runText("uv", command, {
        cwd: root,
        timeoutMs: collectTimeoutMs(await collectFleetSize(target, args.gender, season)),
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
      const requestedConference = args.conference ? conferenceSlug(args.conference) : undefined;
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
