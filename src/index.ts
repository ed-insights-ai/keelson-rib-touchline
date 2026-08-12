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
import { ensureActivationConfig, touchlineAuthStatus } from "./activation.ts";
import { TOUCHLINE_AGENT_SLUG, touchlineSystemPrompt } from "./agent.ts";
import {
  composeBoard,
  composeNoProject,
  composeNoSeasons,
  composeNotAHome,
  composeUnreadable,
} from "./board.ts";
import { invokeTouchlineCommand, TOUCHLINE_COMMAND } from "./commands.ts";
import {
  conferenceSlug,
  dataHomeState,
  explainRefusal,
  type HomeState,
  listSeasons,
  loadFixtures,
  loadMatches,
  loadRosterHistory,
  loadRosters,
  loadStats,
  readMarker,
  type SeasonRef,
} from "./datahome.ts";
import { BOARD_KEY, TOUCHLINE_SURFACE_ID } from "./keys.ts";
import { knownConferences, knownProgrammes, titleFromSlug } from "./membership.ts";
import {
  getSelection,
  resetSelection,
  resolveProject,
  setFixture,
  setPlayer,
  setScope,
  setSeason,
  setTeam,
} from "./state.ts";
import { makeTouchlineTools } from "./tools.ts";

// Captured in registerTools — the one hook the harness calls with ctx. The
// composers run later with no arguments, so anything they need lives here.
let snapshots: SnapshotManager | undefined;
let unregisterBoard: (() => void) | undefined;
let getProjects: (() => readonly Project[]) | undefined;
let seedTimer: ReturnType<typeof setTimeout> | undefined;
let invalidateManifest: (() => void) | undefined;

// The board panel's head is host chrome, static per manifest fetch — but the
// rib contract sanctions mutating a declared region's presentation and calling
// invalidateManifest when a value really changed. The collected stamp lives
// there as the region byline, out of the sheet entirely: the composer knows
// which season file it just rendered, so the stamp follows the viewed season.
const boardPanel: {
  key: string;
  title: string;
  glyph: { char: string; tone: "ok" };
  live: boolean;
  byline?: string;
} = {
  key: BOARD_KEY,
  title: "Season board",
  glyph: { char: "◎", tone: "ok" },
  live: true,
};

function stampPanel(collectedAt?: string): void {
  const byline = collectedAt
    ? `collected ${collectedAt.slice(0, 16).replace("T", " ")}`
    : undefined;
  if (boardPanel.byline === byline) return;
  if (byline === undefined) delete boardPanel.byline;
  else boardPanel.byline = byline;
  invalidateManifest?.();
}

// The boot-time compose can run before the server has finished loading
// projects, so the first frame can honestly report "no projects registered"
// and then be wrong seconds later. One re-seed repaints past that race without
// waiting for a user interaction.
const SEED_RETRY_MS = 15_000;

function refresh(): void {
  // Fail-soft: a repaint nudge must never take a tool result down with it.
  snapshots?.recompose(BOARD_KEY).catch(() => undefined);
}

const selectProjectPayload = z.object({ scopeId: z.string().min(1).optional() });
const lensPayload = z.object({ team: z.string().min(1).nullable().optional() });
const seasonPayload = z.object({
  season: z.number().int(),
  gender: z.string().min(1),
  conference: z
    .string()
    .regex(/[a-z0-9]/i)
    .optional(),
});
const playerPayload = z.object({ player: z.string().min(1).nullable().optional() });
const fixturePayload = z.object({ fixture: z.string().min(1).nullable().optional() });

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
  try {
    const { html, collectedAt } = await composeTouchlineBoardInner();
    stampPanel(collectedAt);
    return html;
  } catch (err) {
    // The registered callback renders a failure sheet for a throwing composer;
    // a stale "collected …" byline must not survive next to it.
    stampPanel(undefined);
    throw err;
  }
}

async function composeTouchlineBoardInner(): Promise<{ html: string; collectedAt?: string }> {
  const sel = getSelection();
  const { project, all, home } = await currentScope();
  if (!project) {
    // Offer only actual Touchline data homes — a picker listing every
    // registered repository invites collecting into somebody else's folder.
    const homes: string[] = [];
    for (const p of all) {
      const marker = await readMarker(p.rootPath).catch(() => ({ state: "unmarked" as const }));
      if (marker.state === "marked") homes.push(p.name);
    }
    return { html: composeNoProject(homes) };
  }
  if (!home) return { html: composeUnreadable(`${project.rootPath} could not be inspected.`) };

  if (home.state === "foreign" || home.state === "missing" || home.state === "occupied") {
    return { html: composeUnreadable(explainRefusal(project.rootPath, home) as string) };
  }
  if (home.state === "empty") return { html: composeNotAHome(project.name, true) };

  const root = project.rootPath;
  const seasons = await listSeasons(root);
  if (!seasons.length) return { html: composeNoSeasons(project.name) };

  const selectedShards = seasons.filter((s) => s.season === sel.season && s.gender === sel.gender);
  const selectedConference = sel.conference ? conferenceSlug(sel.conference) : undefined;
  const want =
    (selectedConference
      ? selectedShards.find((s) => s.conference === selectedConference)
      : selectedShards.length === 1
        ? selectedShards[0]
        : undefined) ?? seasons[0];
  if (!want) return { html: composeNoSeasons(project.name) };

  const fx = await loadFixtures(root, want.season, want.gender, want.conference);
  if (!fx.ok) {
    return {
      html: composeUnreadable(
        fx.reason === "absent"
          ? `No fixtures file at ${fx.path}.`
          : `${fx.reason} fixtures file at ${fx.path} — ${"detail" in fx ? fx.detail : ""}`,
      ),
    };
  }
  const rs = await loadRosters(root, want.season, want.gender, want.conference);
  const st = await loadStats(root, want.season, want.gender, want.conference);
  const mt = await loadMatches(root, want.season, want.gender, want.conference);
  // The full roster archive feeds tenure lines — how many seasons a player
  // has been on the roster, and prior stints at other conference programmes.
  const history = await loadRosterHistory(root, want.gender);

  // A team lens carried across seasons only holds if the team is actually in
  // the season being shown — a 2016 board has three programmes, not seven.
  const team =
    sel.team && fx.value.programmes.some((p) => p.slug === sel.team) ? sel.team : undefined;

  const html = composeBoard({
    projectName: project.name,
    fixtures: fx.value,
    rosters: rs.ok ? rs.value : undefined,
    stats: st.ok ? st.value : undefined,
    matches: mt.ok ? mt.value : undefined,
    rosterHistory: history,
    team,
    player: team ? sel.player : undefined,
    fixture: sel.fixture,
    today: todayIso(),
    seasons: seasons.map((s) => ({
      season: s.season,
      gender: s.gender,
      conference: s.conference,
    })),
  });
  return { html, collectedAt: fx.value.collected_at };
}

/** Build the chat seed from the live situation, so the agent opens knowing
 *  where it is rather than asking. */
async function buildSeed(openingPrompt?: string): Promise<OpenChatSeed> {
  const { project, home, seasons } = await currentScope();
  const programmes = await knownProgrammes("men").catch(() => [] as string[]);
  const conferences = await knownConferences().catch(() => [] as string[]);
  return {
    name: "Touchline",
    systemPrompt: touchlineSystemPrompt({
      projectName: project?.name,
      projectRoot: project?.rootPath,
      homeState: home?.state,
      seasons: seasons.map((s) => `${s.season} ${s.gender} (${s.conference})`),
      conferences,
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
  ],

  surfaces: [
    {
      id: TOUCHLINE_SURFACE_ID,
      title: "Touchline",
      heading: "Touchline",
      subtitle:
        "Published college-soccer schedules, rosters, results and player statistics — current season and archive — collected into your own data folder.",
      projectScoped: true,
      layout: {
        // One panel: the board. Collection is a conversation — the panel's ✦
        // opens the Touchline agent, which holds every write path (init,
        // collect, focus, remove) as tools. A parallel form would be a second,
        // dumber way to say the same thing.
        header: boardPanel,
        rows: [],
      },
    },
  ],

  listAgents: (): readonly AgentSummary[] => [
    {
      slug: TOUCHLINE_AGENT_SLUG,
      name: "Touchline",
      description:
        "Name a conference or programme and Touchline collects its schedule, roster, and player statistics — any season back to 2016 — into your project.",
    },
  ],

  resolveAgent: async (slug: string) => {
    if (slug !== TOUCHLINE_AGENT_SLUG) return null;
    return buildSeed();
  },

  listCommands: () => [TOUCHLINE_COMMAND],

  invokeCommand: (name: string, arg: string, ctx: RibContext) => {
    if (name !== "touchline") {
      return { ok: false as const, error: `touchline does not provide /${name}` };
    }
    return invokeTouchlineCommand(arg, ctx);
  },

  contributeDocs: () => [
    {
      title: "Touchline",
      summary:
        "The Touchline rib for Keelson: on-demand college-soccer collection into a consumer-owned data folder, with a live season board for a conference or a single team.",
      content: [
        "# Touchline rib",
        "",
        "Collects the published 2026 college-soccer schedule and roster into a directory",
        "the user owns, then renders those files as a season board. They are the complete",
        "v1 deliverable; no database, historical archive, or generated report is required.",
        "",
        "## Getting started",
        "",
        "1. Run `/touchline my-soccer`. Touchline creates `my-soccer` under Keelson's",
        "   default workspace, registers it for UI/workflow scope, and initializes it.",
        "   It is an ordinary directory — Git is neither initialized nor required.",
        "2. Say `Harding men 2026` or `GAC men 2026` in the opened Touchline chat.",
        "",
        "## The empty-or-ours rule",
        "",
        "Touchline only ever initializes a folder that is EMPTY, and only ever collects",
        "into a folder carrying its own `touchline-data.yaml` marker. A directory holding",
        "anything else is refused by name. This is what keeps a collection from writing",
        "into somebody else's directory that happened to be selected in the picker.",
        "",
        "## The data files",
        "",
        "- `data/fixtures/<season>-<gender>.json` — the published schedule, one entry per fixture,",
        "  with status `scheduled`, `live`, `final`, `postponed`, or `cancelled`.",
        "  Scores are null until played — never 0, which is a real scoreline.",
        "- `data/rosters/<season>-<gender>.json` — the published roster per programme.",
        "- `data/stats/<season>-<gender>.json` — each programme's published cumulative player",
        "  statistics: minutes, goals, assists, shots for outfield players; saves, goals",
        "  against, and save percentage for goalkeepers.",
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
        "- `touchline_focus` — switch the board to one programme's schedule and roster.",
        "",
        "## Workflows",
        "",
        "- `touchline-collect` — the schedule-and-roster run the touchline_collect tool launches.",
      ].join("\n"),
    },
  ],

  registerTools: (ctx: RibContext) => {
    // Drop stale registrations first: register() throws on a duplicate key, and
    // a dev reload would otherwise take the server down.
    unregisterBoard?.();
    unregisterBoard = undefined;
    snapshots = ctx.getSnapshotManager?.();
    getProjects = () => ctx.getProjects?.() ?? [];
    invalidateManifest = ctx.invalidateManifest;
    // Workflow bash nodes cannot see this module's location. Persist the
    // package route at activation; authStatus reports any write/parse failure.
    void ensureActivationConfig().catch(() => undefined);

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
      refresh();
      if (seedTimer) clearTimeout(seedTimer);
      seedTimer = setTimeout(refresh, SEED_RETRY_MS);
    }

    return makeTouchlineTools({ ctx, refreshBoard: refresh });
  },

  onAction: async (action: RibAction) => {
    // Every write path lives in the chat tools, which carry their own gates.
    // The board's actions are all reads: pointing the board somewhere else.
    if (action.type === "select-project") {
      const parsed = selectProjectPayload.safeParse(action.payload ?? {});
      if (!parsed.success) {
        return { ok: false as const, error: "select-project payload must be { scopeId?: string }" };
      }
      setScope(parsed.data.scopeId);
      const selected = resolveProject(getProjects?.() ?? [], parsed.data.scopeId);
      if (selected) {
        try {
          await ensureActivationConfig(selected.rootPath);
        } catch (err) {
          return {
            ok: false as const,
            error: `Could not record the Touchline data home: ${err instanceof Error ? err.message : String(err)}`,
          };
        }
      }
      refresh();
      return { ok: true as const };
    }

    // Read-only: the masthead chevrons step through seasons already on disk.
    // The team lens survives the step when the target season has that team;
    // composeTouchlineBoard drops it when it does not.
    if (action.type === "select-season") {
      const parsed = seasonPayload.safeParse(action.payload ?? {});
      if (!parsed.success) {
        return {
          ok: false as const,
          error:
            "select-season payload must be { season: number, gender: string, conference?: string }",
        };
      }
      const candidates = (await currentScope()).seasons.filter(
        (s) => s.season === parsed.data.season && s.gender === parsed.data.gender,
      );
      const conference = parsed.data.conference
        ? conferenceSlug(parsed.data.conference)
        : undefined;
      const want = conference
        ? candidates.find((s) => s.conference === conference)
        : candidates.length === 1
          ? candidates[0]
          : undefined;
      if (!want) {
        return {
          ok: false as const,
          error:
            candidates.length > 1 && !conference
              ? `select-season must name conference; available shards: ${candidates
                  .map((s) => s.conference)
                  .join(", ")}`
              : `No collected ${parsed.data.season} ${parsed.data.gender}${
                  conference ? ` ${conference}` : ""
                } season shard exists.`,
        };
      }
      const keptTeam = getSelection().team;
      setSeason(want.season, want.gender, want.conference);
      if (keptTeam) setTeam(keptTeam);
      refresh();
      return { ok: true as const };
    }

    // Read-only: opens or closes the player drawer on the team page. The key
    // is the roster's SideArm player id when it has one, else the name.
    if (action.type === "select-player") {
      const parsed = playerPayload.safeParse(action.payload ?? {});
      if (!parsed.success) {
        return {
          ok: false as const,
          error: "select-player payload must be { player?: string | null }",
        };
      }
      setPlayer(parsed.data.player ?? undefined);
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

    // Read-only: opens or closes the match drawer — the fixture's box score.
    if (action.type === "open-fixture") {
      const parsed = fixturePayload.safeParse(action.payload ?? {});
      if (!parsed.success) {
        return {
          ok: false as const,
          error: "open-fixture payload must be { fixture?: string | null }",
        };
      }
      setFixture(parsed.data.fixture ?? undefined);
      refresh();
      return { ok: true as const };
    }

    if (action.type === "player-profile") {
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

  authStatus: (ctx: RibContext) => touchlineAuthStatus(ctx),

  dispose(): void {
    if (seedTimer) clearTimeout(seedTimer);
    seedTimer = undefined;
    unregisterBoard?.();
    unregisterBoard = undefined;
    snapshots = undefined;
    getProjects = undefined;
    resetSelection();
  },
};

export default rib;

// Re-exported for the tests, which drive the composers through their seams.
export { composeTouchlineBoard, setScope, setSeason, setTeam, titleFromSlug };
