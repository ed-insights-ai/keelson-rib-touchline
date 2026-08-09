// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import type { Project } from "@keelson/shared";
import type { HomeState, SeasonRef } from "./datahome.ts";
import { explainRefusal } from "./datahome.ts";

// ─────────────────────────────────────────────────────────────────────────────
// The setup banner: the rib's front door, rendered by the HOST rather than by
// our own markup.
//
// This is a `view`/board payload, not the html board, and that is deliberate.
// A board action's dispatch carries trusted `board` origin and can collect
// input through `fields`; a sandboxed html frame can post on load with no user
// gesture, so directory creation and collection launches must never be
// reachable from there. The season board stays html; anything that WRITES
// lives here.
// ─────────────────────────────────────────────────────────────────────────────

/** The one field every entry point collects: what the user actually wants. */
const REQUEST_FIELD = {
  name: "request",
  label: "What do you want to collect?",
  placeholder: "the whole GAC, men, 2025    ·    or:  Harding 2025",
  required: true,
} as const;

function askAction(label: string, glyph: string) {
  return {
    type: "collect-request",
    label,
    glyph,
    tone: "ok" as const,
    // An always-open form: the input IS the affordance here, so there is no
    // disclosure click between the reader and the one thing to do.
    expanded: true,
    submitLabel: "Collect",
    fields: [REQUEST_FIELD],
  };
}

/** Hand off to a seeded chat when the ask is more than the parser can take. */
const CHAT_ACTION = {
  type: "open-touchline-chat",
  label: "Ask Touchline instead",
  glyph: "✦",
  tone: "neutral" as const,
  hint: "Opens a chat that knows what Touchline can collect and how.",
};

export interface SetupInput {
  project?: Project;
  allProjects: readonly Project[];
  home?: HomeState;
  seasons: readonly SeasonRef[];
}

/** The banner board. It is never hidden — it is the control strip — but its
 *  content changes completely between "nowhere to put data" and "ready". */
export function composeSetup(input: SetupInput): unknown {
  const { project, allProjects, home, seasons } = input;

  if (!project) {
    return {
      view: "board",
      title: "Touchline",
      sections: [
        {
          kind: "rows",
          title: "Choose where your soccer data lives",
          items: [
            {
              text: "Pick a project above",
              detail:
                "An empty folder is the right starting point — Touchline initializes it for you. It will refuse any folder that already holds other work.",
            },
            ...(allProjects.length
              ? [
                  {
                    text: "Registered projects",
                    trailing: allProjects.map((p) => p.name).join(" · "),
                  },
                ]
              : [
                  {
                    text: "No projects registered",
                    detail: "keelson project add my-soccer ~/my-soccer",
                  },
                ]),
          ],
        },
      ],
    };
  }

  // A folder we must not touch. Say why, and offer the only useful next step.
  if (home && (home.state === "occupied" || home.state === "foreign" || home.state === "missing")) {
    return {
      view: "board",
      title: project.name,
      header: { status: { text: "Not a data home", tone: "warn" } },
      sections: [
        {
          kind: "rows",
          items: [
            {
              text: "Touchline will not collect here",
              detail: explainRefusal(project.rootPath, home),
            },
          ],
        },
        {
          kind: "actions",
          items: [CHAT_ACTION],
        },
      ],
    };
  }

  const ready = home?.state === "ready";
  const collected = seasons.length;

  return {
    view: "board",
    title: project.name,
    header: {
      status: ready
        ? collected
          ? { text: `${collected} season${collected === 1 ? "" : "s"} collected`, tone: "ok" }
          : { text: "Ready — nothing collected yet", tone: "info" }
        : { text: "Empty folder — ready to initialize", tone: "info" },
      chip: project.rootPath,
    },
    sections: [
      {
        kind: "actions",
        items: [
          askAction(collected ? "Collect another season" : "Collect a season", "◎"),
          CHAT_ACTION,
        ],
      },
      ...(collected
        ? [
            {
              kind: "rows",
              title: "In this data home",
              items: seasons.map((s) => ({
                text: `${s.season} · ${s.gender}`,
                trailing: s.conference,
              })),
            },
          ]
        : [
            {
              kind: "rows",
              items: [
                {
                  text: "Nothing collected yet",
                  detail:
                    'Name a conference and season ("GAC men 2025") or a single programme ("Harding 2025"). Touchline resolves members from its membership record — it never guesses a team it has no recipe for.',
                },
              ],
            },
          ]),
    ],
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Parsing the ask.
//
// Deterministic on purpose. A model turn is the fallback (the chat handoff),
// not the primary path: the common asks are a conference or a programme plus a
// season, and a parser that reports exactly what it did and did not understand
// beats one that quietly guesses.
// ─────────────────────────────────────────────────────────────────────────────

export interface ParsedRequest {
  gender?: string;
  season?: number;
  /** Free text left after removing the parts we understood. */
  subject: string;
}

export function parseRequest(raw: string): ParsedRequest {
  // Normalize the curly apostrophe a Mac types by default, then drop every
  // possessive: "men's soccer" is the most natural way to ask, and a leftover
  // "'s" would otherwise reach the resolver as part of the subject.
  let text = ` ${raw.toLowerCase().replace(/[‘’ʼ]/g, "'").replace(/'s\b/g, "")} `;

  let season: number | undefined;
  const year = /\b(19|20)\d{2}\b/.exec(text);
  if (year) {
    season = Number(year[0]);
    text = text.replace(year[0], " ");
  }

  // Women first: "women" contains "men", so testing men first would
  // misclassify every women's request.
  let gender: string | undefined;
  if (/\b(womens?|ladies|female)\b/.test(text)) gender = "women";
  else if (/\b(mens?|male)\b/.test(text)) gender = "men";
  if (gender) text = text.replace(/\b(womens?|ladies|female|mens?|male)\b/g, " ");

  // Strip the filler a person naturally types around the subject. Order
  // matters only in that this runs after gender and season are lifted out;
  // what survives is meant to be a conference or a programme and nothing else.
  const FILLER = [
    // verbs
    "get",
    "give",
    "pull",
    "fetch",
    "scrape",
    "collect",
    "retrieve",
    "download",
    "show",
    "want",
    "need",
    "grab",
    // particles and pronouns
    "down",
    "up",
    "me",
    "my",
    "us",
    "our",
    "i",
    "we",
    "please",
    "and",
    "a",
    "an",
    "the",
    "of",
    "for",
    "from",
    "in",
    "on",
    "to",
    // scope words
    "whole",
    "entire",
    "all",
    "both",
    "every",
    "current",
    "latest",
    "this",
    // domain nouns that carry no target information
    "schedule",
    "schedules",
    "fixture",
    "fixtures",
    "roster",
    "rosters",
    "result",
    "results",
    "season",
    "seasons",
    "soccer",
    "football",
    "team",
    "teams",
    "programme",
    "programmes",
    "program",
    "programs",
    "conference",
    "d1",
    "d2",
    "d3",
    "ncaa",
    "naia",
    "division",
    // institution suffixes — the slug never carries them
    "university",
    "college",
  ];
  const subject = text
    .replace(new RegExp(`\\b(${FILLER.join("|")})\\b`, "g"), " ")
    .replace(/[.,;:!?'"]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  return { gender, season, subject };
}
