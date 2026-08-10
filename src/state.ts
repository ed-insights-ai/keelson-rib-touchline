// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import type { Project } from "@keelson/shared";

// ─────────────────────────────────────────────────────────────────────────────
// What the board is currently looking at. Module scope, like every other rib:
// the harness gives us ctx once (in registerTools) and the composer runs later
// with no arguments, so the selection has to live somewhere both can reach.
//
// None of this is persisted. A restart resets to "nothing selected", which is
// the honest resting state — the SPA re-posts its project selection on mount.
// ─────────────────────────────────────────────────────────────────────────────

export interface Selection {
  /** Keelson project id chosen in the surface's project picker. */
  scopeId?: string;
  season?: number;
  gender?: string;
  /** Programme slug for the team lens; undefined = conference lens. */
  team?: string;
  /** Player key for the drawer — SideArm player id when the roster has one,
   *  else the player's name. Only meaningful while a team is selected. */
  player?: string;
  /** Fixture id for the match drawer. One drawer at a time: selecting a
   *  fixture clears the player and vice versa. */
  fixture?: string;
}

const selection: Selection = {};

export function getSelection(): Readonly<Selection> {
  return selection;
}

export function setScope(scopeId: string | undefined): void {
  if (selection.scopeId === scopeId) return;
  selection.scopeId = scopeId;
  // A different project is a different data home — every downstream choice is
  // stale, and carrying a season across would render one project's board under
  // another project's name.
  selection.season = undefined;
  selection.gender = undefined;
  selection.team = undefined;
  selection.player = undefined;
  selection.fixture = undefined;
}

export function setSeason(season: number | undefined, gender: string | undefined): void {
  selection.season = season;
  selection.gender = gender;
  selection.team = undefined;
  selection.player = undefined;
  selection.fixture = undefined;
}

export function setTeam(team: string | undefined): void {
  if (selection.team !== team) {
    selection.player = undefined;
    selection.fixture = undefined;
  }
  selection.team = team;
}

export function setPlayer(player: string | undefined): void {
  selection.player = player;
  if (player !== undefined) selection.fixture = undefined;
}

export function setFixture(fixture: string | undefined): void {
  selection.fixture = fixture;
  if (fixture !== undefined) selection.player = undefined;
}

export function resetSelection(): void {
  selection.scopeId = undefined;
  selection.season = undefined;
  selection.gender = undefined;
  selection.team = undefined;
  selection.player = undefined;
  selection.fixture = undefined;
}

/** The project the board should render, resolved against the live list. */
export function resolveProject(
  projects: readonly Project[],
  scopeId: string | undefined,
): Project | undefined {
  if (!scopeId) return undefined;
  return projects.find((p) => p.id === scopeId);
}

/** Find a project by name or id — how a chat tool names one. */
export function findProject(
  projects: readonly Project[],
  nameOrId: string | undefined,
): Project | undefined {
  if (!nameOrId) return undefined;
  const wanted = nameOrId.trim().toLowerCase();
  return projects.find((p) => p.name.toLowerCase() === wanted || p.id === nameOrId);
}
