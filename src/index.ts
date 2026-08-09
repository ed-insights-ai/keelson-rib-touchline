// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import type {
  AgentSummary,
  OpenChatSeed,
  Project,
  Rib,
  RibAction,
  RibContext,
  SnapshotManager,
} from "@keelson/shared";
import { z } from "zod";
import { TOUCHLINE_AGENT_SLUG, touchlineSystemPrompt } from "./agent.ts";
import {
  composeBoard,
  composeNoProject,
  composeNoSeasons,
  composeNotAHome,
  composeUnreadable,
} from "./board.ts";
import {
  dataHomeState,
  explainRefusal,
  type HomeState,
  listSeasons,
  loadFixtures,
  loadRosters,
  type SeasonRef,
} from "./datahome.ts";
import { BOARD_KEY, SETUP_KEY, TOUCHLINE_SURFACE_ID } from "./keys.ts";
import { knownProgrammes, resolveTargets, titleFromSlug } from "./membership.ts";
import { composeSetup, parseRequest } from "./setup.ts";
import {
  getSelection,
  resetSelection,
  resolveProject,
  setScope,
  setSeason,
  setTeam,
} from "./state.ts";
import { makeTouchlineTools } from "./tools.ts";

// Captured in registerTools — the one hook the harness calls with ctx. The
// composers run later with no arguments, so anything they need lives here.
let snapshots: SnapshotManager | undefined;
let unregisterBoard: (() => void) | undefined;
let unregisterSetup: (() => void) | undefined;
let getProjects: (() => readonly Project[]) | undefined;
let seedTimer: ReturnType<typeof setTimeout> | undefined;

// The boot-time compose can run before the server has finished loading
// projects, so the first frame can honestly report "no projects registered"
// and then be wrong seconds later. One re-seed repaints past that race without
// waiting for a user interaction.
const SEED_RETRY_MS = 15_000;

function refresh(): void {
  // Fail-soft: a repaint nudge must never take a tool result down with it.
  snapshots?.recompose(BOARD_KEY).catch(() => undefined);
  snapshots?.recompose(SETUP_KEY).catch(() => undefined);
}

const selectProjectPayload = z.object({ scopeId: z.string().min(1).optional() });
const lensPayload = z.object({ team: z.string().min(1).nullable().optional() });
const collectPayload = z.object({ request: z.string().min(1) });

/** Today as YYYY-MM-DD, UTC. Passed into the composer so its output is a pure
 *  function of (data, date) and a test can pin the day. */
function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Everything both composers need about where the board is pointed. */
async function currentScope(): Promise<{
  project?: Project;
  all: readonly Project[];
  home?: HomeState;
  seasons: SeasonRef[];
}> {
  const sel = getSelection();
  const all = getProjects?.() ?? [];
  const project = resolveProject(all, sel.scopeId);
  if (!project) return { all, seasons: [] };
  const home = await dataHomeState(project.rootPath);
  const seasons = home.state === "ready" ? await listSeasons(project.rootPath) : [];
  return { project, all, home, seasons };
}

async function composeTouchlineBoard(): Promise<string> {
  const sel = getSelection();
  const { project, all, home } = await currentScope();
  if (!project) return composeNoProject(all.map((p) => p.name));
  if (!home) return composeUnreadable(`${project.rootPath} could not be inspected.`);

  if (home.state === "foreign" || home.state === "missing" || home.state === "occupied") {
    return composeUnreadable(explainRefusal(project.rootPath, home) as string);
  }
  if (home.state === "empty") return composeNotAHome(project.name, true);

  const root = project.rootPath;
  const seasons = await listSeasons(root);
  if (!seasons.length) return composeNoSeasons(project.name);

  const want =
    seasons.find((s) => s.season === sel.season && s.gender === sel.gender) ?? seasons[0];
  if (!want) return composeNoSeasons(project.name);

  const fx = await loadFixtures(root, want.season, want.gender);
  if (!fx.ok) {
    return composeUnreadable(
      fx.reason === "absent"
        ? `No fixtures file at ${fx.path}.`
        : `${fx.reason} fixtures file at ${fx.path} — ${"detail" in fx ? fx.detail : ""}`,
    );
  }
  const rs = await loadRosters(root, want.season, want.gender);

  return composeBoard({
    projectName: project.name,
    fixtures: fx.value,
    rosters: rs.ok ? rs.value : undefined,
    team: sel.team,
    today: todayIso(),
  });
}

async function composeSetupBanner(): Promise<unknown> {
  const { project, all, home, seasons } = await currentScope();
  return composeSetup({ project, allProjects: all, home, seasons });
}

/** Build the chat seed from the live situation, so the agent opens knowing
 *  where it is rather than asking. */
async function buildSeed(openingPrompt?: string): Promise<OpenChatSeed> {
  const { project, home, seasons } = await currentScope();
  const programmes = await knownProgrammes("men").catch(() => [] as string[]);
  return {
    name: "Touchline",
    systemPrompt: touchlineSystemPrompt({
      projectName: project?.name,
      projectRoot: project?.rootPath,
      homeState: home?.state,
      seasons: seasons.map((s) => `${s.season} ${s.gender} (${s.conference})`),
      conferences: ["GAC", "MIAA"],
      programmes,
    }),
    ...(openingPrompt ? { openingPrompt } : {}),
  };
}

const rib: Rib = {
  id: "touchline",
  displayName: "Touchline",

  views: [
    // The season board is `html`: a self-contained markup string rendered in a
    // sandboxed iframe. The kind is resolved by exact key match.
    { key: BOARD_KEY, canvasKind: "html", title: "Touchline board" },
    // The setup banner is a `view` board so the HOST renders its form. A form
    // that creates directories and launches collection must dispatch with
    // trusted board origin, never from inside the sandboxed frame.
    { key: SETUP_KEY, canvasKind: "view", title: "Touchline setup" },
  ],

  surfaces: [
    {
      id: TOUCHLINE_SURFACE_ID,
      title: "Touchline",
      heading: "Touchline",
      subtitle:
        "College soccer, collected on demand into your own repository. Schedule, rosters, and results — read straight from your data files.",
      projectScoped: true,
      layout: {
        // The banner never collapses and never hides: it is the control strip,
        // and in every state it is the thing to act on.
        banner: {
          key: SETUP_KEY,
          title: "Collect",
          glyph: { char: "✦", tone: "brand" },
        },
        header: {
          key: BOARD_KEY,
          title: "Season board",
          glyph: { char: "◎", tone: "ok" },
          live: true,
        },
        rows: [],
      },
    },
  ],

  listAgents: (): readonly AgentSummary[] => [
    {
      slug: TOUCHLINE_AGENT_SLUG,
      name: "Touchline",
      description:
        "Ask for soccer data in words — a conference season or one programme — and it collects into your project and lights up the board.",
    },
  ],

  resolveAgent: async (slug: string) => {
    if (slug !== TOUCHLINE_AGENT_SLUG) return null;
    return buildSeed();
  },

  contributeDocs: () => [
    {
      title: "Touchline",
      summary:
        "The Touchline rib for Keelson: on-demand college-soccer collection into a consumer-owned data repository, with a live season board for a conference or a single team.",
      content: [
        "# Touchline rib",
        "",
        "Collects college soccer schedules, rosters, and results into a directory the",
        "user owns, and renders them as a season board. No database is required: the",
        "board reads the project's own JSON files.",
        "",
        "## Getting started",
        "",
        "1. Register a directory as a keelson project — an EMPTY one:",
        "   `keelson project add my-soccer ~/my-soccer`.",
        "2. Pick it in the Touchline surface's project picker.",
        "3. Type the ask into the Collect banner, or open the Touchline agent and say it.",
        "",
        "## The empty-or-ours rule",
        "",
        "Touchline only ever initializes a folder that is EMPTY, and only ever collects",
        "into a folder carrying its own `touchline-data.yaml` marker. A directory holding",
        "anything else is refused by name. This is what keeps a collection from writing",
        "into a source repository that happened to be selected in the picker.",
        "",
        "## The data files",
        "",
        "- `data/fixtures/<season>-<gender>.json` — the schedule, one entry per fixture,",
        "  with status `scheduled`, `live`, `final`, `postponed`, or `cancelled`.",
        "  Scores are null until played — never 0, which is a real scoreline.",
        "- `data/rosters/<season>-<gender>.json` — rosters per programme.",
        "",
        "Both name what could NOT be collected in a `missing` array. A gap is always",
        "reported, never silently dropped.",
        "",
        "## Conference membership is data",
        "",
        "A conference resolves to its members by reading authored, season-aware",
        "membership windows — a programme that joined in 2019 is absent from 2018.",
        "Nothing hardcodes a member list. Past the last authored season the most recent",
        "membership is carried forward and the result is flagged as extrapolated.",
        "",
        "## Tools",
        "",
        "- `touchline_status` — what a project holds (read-only).",
        "- `touchline_collect` — resolve a target, initialize the data home, build the",
        "  season files, and point the board at them.",
        "- `touchline_focus` — switch the board to another season, or to one team.",
        "",
        "## Workflows",
        "",
        "- `touchline-collect` — the collection run the Collect banner launches.",
        "- `data-integrity` — eleven fail-closed checks over the archive. Never writes.",
      ].join("\n"),
    },
  ],

  registerTools: (ctx: RibContext) => {
    // Drop stale registrations first: register() throws on a duplicate key, and
    // a dev reload would otherwise take the server down.
    unregisterBoard?.();
    unregisterSetup?.();
    unregisterBoard = undefined;
    unregisterSetup = undefined;
    snapshots = ctx.getSnapshotManager?.();
    getProjects = () => ctx.getProjects?.() ?? [];

    if (snapshots) {
      unregisterBoard = snapshots.register(BOARD_KEY, async () => {
        try {
          return await composeTouchlineBoard();
        } catch (err) {
          // A composer that throws leaves the previous frame in place, which on
          // a first paint means an empty panel. Render the failure instead.
          return composeUnreadable(err instanceof Error ? err.message : String(err));
        }
      });
      unregisterSetup = snapshots.register(SETUP_KEY, async () => {
        try {
          return await composeSetupBanner();
        } catch (err) {
          return {
            view: "board",
            sections: [
              {
                kind: "rows",
                items: [
                  {
                    text: "Touchline setup could not render",
                    detail: err instanceof Error ? err.message : String(err),
                  },
                ],
              },
            ],
          };
        }
      });
      refresh();
      if (seedTimer) clearTimeout(seedTimer);
      seedTimer = setTimeout(refresh, SEED_RETRY_MS);
    }

    return makeTouchlineTools({ ctx, refreshBoard: refresh });
  },

  onAction: async (action: RibAction) => {
    // Anything that WRITES or SPENDS must come from host chrome. A sandboxed
    // frame's script can post on load with no user gesture, so a collection
    // launch reachable from there would be a drive-by.
    const fromFrame = action.origin === "canvas-html";

    if (action.type === "select-project") {
      const parsed = selectProjectPayload.safeParse(action.payload ?? {});
      if (!parsed.success) {
        return { ok: false as const, error: "select-project payload must be { scopeId?: string }" };
      }
      setScope(parsed.data.scopeId);
      refresh();
      return { ok: true as const };
    }

    // Read-only: safe from the frame, which is where the lens buttons live.
    if (action.type === "select-lens") {
      const parsed = lensPayload.safeParse(action.payload ?? {});
      if (!parsed.success) {
        return {
          ok: false as const,
          error: "select-lens payload must be { team?: string | null }",
        };
      }
      setTeam(parsed.data.team ?? undefined);
      refresh();
      return { ok: true as const };
    }

    if (action.type === "open-touchline-chat") {
      if (fromFrame) {
        return {
          ok: false as const,
          error: "opening a chat is not available from the board frame",
        };
      }
      return { ok: true as const, data: { effect: "open-chat", seed: await buildSeed() } };
    }

    if (action.type === "collect-request") {
      if (fromFrame) {
        return { ok: false as const, error: "collection cannot be launched from the board frame" };
      }
      const parsed = collectPayload.safeParse(action.payload ?? {});
      if (!parsed.success) {
        return { ok: false as const, error: "collect payload must be { request: string }" };
      }
      const { project, home } = await currentScope();
      if (!project) {
        return {
          ok: false as const,
          error: "Pick a project first — that is where the data lands.",
        };
      }
      if (home && home.state !== "empty" && home.state !== "ready") {
        return { ok: false as const, error: explainRefusal(project.rootPath, home) as string };
      }

      const ask = parseRequest(parsed.data.request);
      const gender = ask.gender ?? "men";
      const season = ask.season ?? new Date().getUTCFullYear() - 1;
      const target = await resolveTargets(ask.subject, gender, season);

      if (target.kind === "unknown") {
        // Hand the un-parseable ask to the agent rather than guessing at it.
        return {
          ok: true as const,
          data: {
            effect: "open-chat",
            seed: await buildSeed(parsed.data.request),
          },
        };
      }
      if (!target.slugs.length) {
        return {
          ok: false as const,
          error: `Nothing resolved for "${parsed.data.request}" in ${season}. Known conferences: ${
            target.kind === "conference" ? target.conference : ""
          }`,
        };
      }

      return {
        ok: true as const,
        data: {
          effect: "run-workflow",
          workflow: "touchline-collect",
          args: {
            conference: target.conference,
            gender,
            season: String(season),
            programmes: target.slugs.join(","),
          },
          // Keep the operator on the board; the run streams into a drawer beside it.
          stay: true,
        },
      };
    }

    if (action.type === "open-fixture" || action.type === "player-profile") {
      return {
        ok: false as const,
        error: `'${action.type}' is not implemented yet — the research workflow behind it is still to be built.`,
      };
    }

    return { ok: false as const, error: `touchline does not handle '${action.type}'` };
  },

  onRunEvent: (event) => {
    // A finished collection changed the files the board reads. Delivery is not
    // guaranteed, so this is a nudge on top of the cadence, never the only path.
    if (event.workflowName === "touchline-collect" && event.status === "succeeded") refresh();
  },

  dispose(): void {
    if (seedTimer) clearTimeout(seedTimer);
    seedTimer = undefined;
    unregisterBoard?.();
    unregisterSetup?.();
    unregisterBoard = undefined;
    unregisterSetup = undefined;
    snapshots = undefined;
    getProjects = undefined;
    resetSelection();
  },
};

export default rib;

// Re-exported for the tests, which drive the composers through their seams.
export { composeSetupBanner, composeTouchlineBoard, setScope, setSeason, setTeam, titleFromSlug };
