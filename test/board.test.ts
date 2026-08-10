// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { touchlineSystemPrompt } from "../src/agent.ts";
import {
  composeBoard,
  composeNoProject,
  composeNoSeasons,
  composeNotAHome,
  composeUnreadable,
} from "../src/board.ts";
import {
  bootstrapDataHome,
  dataHomeState,
  explainRefusal,
  isEffectivelyEmpty,
  listSeasons,
  loadFixtures,
  readMarker,
} from "../src/datahome.ts";
import { resolveConference, resolveTargets } from "../src/membership.ts";
import {
  computeTable,
  type FixturesFile,
  fixturesFileSchema,
  type RostersFile,
  type StatsFile,
  statsFileSchema,
} from "../src/model.ts";
import {
  planForSeason,
  planSummary,
  TOUCHLINE_V1_SEASON,
  unsupportedSeasonMessage,
} from "../src/season.ts";

const base: FixturesFile = {
  schema: "touchline.fixtures/1",
  season: 2026,
  gender: "men",
  conference: "GAC",
  collected_at: "2026-08-09T21:00:00Z",
  programmes: [
    { slug: "harding", name: "Harding" },
    { slug: "rogers-state", name: "Rogers State" },
  ],
  fixtures: [],
};

async function tempHome(): Promise<string> {
  return mkdtemp(join(tmpdir(), "touchline-test-"));
}

describe("membership resolution", () => {
  test("GAC men 2025 resolves to the authored member list", async () => {
    const res = await resolveConference("GAC", "men", 2025);
    expect(res.slugs).toEqual([
      "fort-hays-state",
      "harding",
      "newman",
      "northeastern-state",
      "ouachita-baptist",
      "rogers-state",
      "southern-nazarene",
    ]);
    expect(res.extrapolated).toBe(false);
  });

  test("a programme is absent from seasons before it joined", async () => {
    // Fort Hays State men are non_member 2016-2018, GAC from 2019.
    const before = await resolveConference("GAC", "men", 2018);
    const after = await resolveConference("GAC", "men", 2019);
    expect(before.slugs).not.toContain("fort-hays-state");
    expect(after.slugs).toContain("fort-hays-state");
  });

  test("a season past the authored windows is carried forward AND flagged", async () => {
    const res = await resolveConference("GAC", "men", 2026);
    expect(res.slugs.length).toBeGreaterThan(0);
    expect(res.extrapolated).toBe(true);
    expect(res.authoredThrough).toBe(2025);
  });

  test("an unknown conference resolves to nothing rather than guessing", async () => {
    const res = await resolveConference("NOT-A-CONFERENCE", "men", 2025);
    expect(res.slugs).toEqual([]);
    expect(res.known.length).toBeGreaterThan(0);
  });

  test("conference matching is case-insensitive", async () => {
    const lower = await resolveConference("gac", "men", 2025);
    const upper = await resolveConference("GAC", "men", 2025);
    expect(lower.slugs).toEqual(upper.slugs);
  });
});

describe("the conference table", () => {
  test("a non-member opponent never earns a row", () => {
    const file: FixturesFile = {
      ...base,
      fixtures: [
        {
          id: "1",
          date: "2026-09-01",
          home: "harding",
          away: "some-non-member",
          status: "final",
          home_score: 3,
          away_score: 0,
        },
      ],
    };
    const table = computeTable(file);
    expect(table.map((r) => r.slug).sort()).toEqual(["harding", "rogers-state"]);
    // ...and the non-conference win earns no points.
    expect(table.find((r) => r.slug === "harding")?.points).toBe(0);
    expect(table.find((r) => r.slug === "harding")?.played).toBe(0);
  });

  test("three for a win, one each for a draw", () => {
    const file: FixturesFile = {
      ...base,
      fixtures: [
        {
          id: "1",
          date: "2026-09-01",
          home: "harding",
          away: "rogers-state",
          status: "final",
          home_score: 2,
          away_score: 1,
        },
        {
          id: "2",
          date: "2026-09-08",
          home: "rogers-state",
          away: "harding",
          status: "final",
          home_score: 1,
          away_score: 1,
        },
      ],
    };
    const table = computeTable(file);
    const harding = table.find((r) => r.slug === "harding");
    const rogers = table.find((r) => r.slug === "rogers-state");
    expect(harding).toMatchObject({ played: 2, won: 1, drawn: 1, lost: 0, points: 4, goalDiff: 1 });
    expect(rogers).toMatchObject({ played: 2, won: 0, drawn: 1, lost: 1, points: 1, goalDiff: -1 });
    expect(table[0]?.slug).toBe("harding");
  });

  test("an explicit conference_game=false is excluded", () => {
    const file: FixturesFile = {
      ...base,
      fixtures: [
        {
          id: "1",
          date: "2026-09-01",
          home: "harding",
          away: "rogers-state",
          status: "final",
          home_score: 5,
          away_score: 0,
          conference_game: false,
        },
      ],
    };
    expect(computeTable(file).every((r) => r.played === 0)).toBe(true);
  });

  test("an unplayed fixture contributes nothing, and 0-0 is a real result", () => {
    const scheduled: FixturesFile = {
      ...base,
      fixtures: [
        { id: "1", date: "2026-09-01", home: "harding", away: "rogers-state", status: "scheduled" },
      ],
    };
    expect(computeTable(scheduled).every((r) => r.played === 0)).toBe(true);

    const nilNil: FixturesFile = {
      ...base,
      fixtures: [
        {
          id: "1",
          date: "2026-09-01",
          home: "harding",
          away: "rogers-state",
          status: "final",
          home_score: 0,
          away_score: 0,
        },
      ],
    };
    expect(computeTable(nilNil).every((r) => r.played === 1 && r.points === 1)).toBe(true);
  });

  test("every programme appears before a ball is kicked", () => {
    expect(
      computeTable(base)
        .map((r) => r.slug)
        .sort(),
    ).toEqual(["harding", "rogers-state"]);
  });
});

describe("the data home", () => {
  test("bootstrap marks an empty directory and is idempotent", async () => {
    const root = await tempHome();
    expect(await isEffectivelyEmpty(root)).toBe(true);
    expect((await readMarker(root)).state).toBe("unmarked");

    const first = await bootstrapDataHome(root);
    expect(first.alreadyMarked).toBe(false);
    const marker = await readMarker(root);
    expect(marker.state).toBe("marked");

    const second = await bootstrapDataHome(root);
    expect(second.alreadyMarked).toBe(true);
  });

  test("bootstrap REFUSES a directory holding someone else's work", async () => {
    const root = await tempHome();
    await writeFile(join(root, "package.json"), "{}", "utf8");
    await writeFile(join(root, "index.ts"), "export {};", "utf8");

    const state = await dataHomeState(root);
    expect(state.state).toBe("occupied");
    expect(explainRefusal(root, state)).toContain("already holds other work");
    await expect(bootstrapDataHome(root)).rejects.toThrow(/already holds other work/);

    // ...and nothing was written on the way to refusing.
    expect(await readMarker(root)).toMatchObject({ state: "unmarked" });
    await expect(readFile(join(root, "data", "fixtures", ".keep"), "utf8")).rejects.toThrow();
  });

  test("an occupied directory can still be adopted, but only deliberately", async () => {
    const root = await tempHome();
    await writeFile(join(root, "notes.txt"), "hi", "utf8");
    await expect(bootstrapDataHome(root)).rejects.toThrow();
    const forced = await bootstrapDataHome(root, { force: true });
    expect(forced.alreadyMarked).toBe(false);
    expect((await readMarker(root)).state).toBe("marked");
  });

  test("an already-initialized home stays usable however full it gets", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(join(root, "lots-of-data.json"), "{}", "utf8");
    const state = await dataHomeState(root);
    expect(state.state).toBe("ready");
    expect(explainRefusal(root, state)).toBeUndefined();
    await bootstrapDataHome(root); // must not throw
  });

  test("git bookkeeping alone still counts as empty", async () => {
    const root = await tempHome();
    await writeFile(join(root, ".gitignore"), "node_modules\n", "utf8");
    expect((await dataHomeState(root)).state).toBe("empty");
  });

  test("bootstrap refuses to scaffold over a foreign marker", async () => {
    const root = await tempHome();
    await writeFile(join(root, "touchline-data.yaml"), "kind: something-else\n", "utf8");
    expect((await readMarker(root)).state).toBe("foreign");
    await expect(bootstrapDataHome(root)).rejects.toThrow(/not a Touchline marker/);
  });

  test("bootstrap does not overwrite an existing README", async () => {
    const root = await tempHome();
    await writeFile(join(root, "README.md"), "MINE\n", "utf8");
    await bootstrapDataHome(root);
    expect(await readFile(join(root, "README.md"), "utf8")).toBe("MINE\n");
  });

  test("an absent season file reports absent rather than throwing", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    const res = await loadFixtures(root, 2026, "men");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.reason).toBe("absent");
    expect(await listSeasons(root)).toEqual([]);
  });

  test("a malformed season file reports invalid, never renders as empty", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(join(root, "data", "fixtures", "2026-men.json"), "{ not json", "utf8");
    const res = await loadFixtures(root, 2026, "men");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.reason).toBe("invalid");
  });

  test("a file failing the schema is invalid, not silently accepted", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(
      join(root, "data", "fixtures", "2026-men.json"),
      JSON.stringify({ schema: "touchline.fixtures/99", season: 2026 }),
      "utf8",
    );
    const res = await loadFixtures(root, 2026, "men");
    expect(res.ok).toBe(false);
  });

  test("a written season round-trips through the schema", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(join(root, "data", "fixtures", "2026-men.json"), JSON.stringify(base), "utf8");
    const res = await loadFixtures(root, 2026, "men");
    expect(res.ok).toBe(true);
    const seasons = await listSeasons(root);
    expect(seasons).toEqual([
      { season: 2026, gender: "men", conference: "GAC", hasFixtures: true, hasRosters: false },
    ]);
  });

  test("a roster-only past season is still listed", async () => {
    // The historic case: each programme serves its CURRENT fixtures at every
    // season address, so a 2019 collection lands a roster and no schedule. A
    // season list keyed on fixtures alone would hide exactly the data the
    // roster analysis needs.
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(join(root, "data", "fixtures", "2026-men.json"), JSON.stringify(base), "utf8");
    await writeFile(
      join(root, "data", "rosters", "2019-men.json"),
      JSON.stringify({
        schema: "touchline.rosters/1",
        season: 2019,
        gender: "men",
        collected_at: "2026-08-09T00:00:00Z",
        rosters: { harding: { programme: "harding", players: [{ name: "Aric McKinney" }] } },
      }),
      "utf8",
    );

    const seasons = await listSeasons(root);
    expect(seasons.map((s) => s.season)).toEqual([2026, 2019]);
    const past = seasons.find((s) => s.season === 2019);
    expect(past).toEqual({
      season: 2019,
      gender: "men",
      conference: "unknown",
      hasFixtures: false,
      hasRosters: true,
    });
  });
});

describe("the board markup", () => {
  const render = (over: Partial<FixturesFile> = {}, team?: string) =>
    composeBoard({
      projectName: "p",
      fixtures: { ...base, ...over },
      team,
      today: "2026-08-09",
    });

  test("the masthead grows chevrons only when the archive holds neighbours", () => {
    const seasons = [
      { season: 2026, gender: "men" },
      { season: 2025, gender: "men" },
      { season: 2024, gender: "men" },
    ];
    const mid = composeBoard({
      projectName: "p",
      fixtures: { ...base, season: 2025 },
      today: "2026-08-09",
      seasons,
    });
    expect(mid).toContain('data-act="select-season"');
    expect(mid).toContain("&quot;season&quot;:2024");
    expect(mid).toContain("&quot;season&quot;:2026");

    // The newest season has no forward step; the oldest no backward step.
    const newest = composeBoard({
      projectName: "p",
      fixtures: base,
      today: "2026-08-09",
      seasons,
    });
    expect(newest).toContain("&quot;season&quot;:2025");
    expect(newest).not.toContain("&quot;season&quot;:2026");

    // One season on disk is a year, not a control.
    const lone = composeBoard({ projectName: "p", fixtures: base, today: "2026-08-09" });
    expect(lone).not.toContain('data-act="select-season"');
  });

  test("a completed past season renders as results, not as lateness", () => {
    const html = composeBoard({
      projectName: "p",
      fixtures: {
        ...base,
        season: 2025,
        fixtures: [
          {
            id: "1",
            date: "2025-09-12",
            home: "harding",
            away: "rogers-state",
            status: "final",
            home_score: 2,
            away_score: 1,
            conference_game: true,
          },
        ],
      },
      team: "harding",
      today: "2026-08-09",
      seasons: [
        { season: 2026, gender: "men" },
        { season: 2025, gender: "men" },
      ],
    });
    expect(html).toContain("Final");
    expect(html).not.toContain("Pre-season");
    expect(html).not.toContain("First kickoff in");
  });

  test("a team's rail reads as a form strip — win, loss and draw ticks", () => {
    const html = composeBoard({
      projectName: "p",
      fixtures: {
        ...base,
        season: 2025,
        fixtures: [
          {
            id: "1",
            date: "2025-09-05",
            home: "harding",
            away: "rogers-state",
            status: "final",
            home_score: 2,
            away_score: 1,
          },
          {
            id: "2",
            date: "2025-09-12",
            home: "rogers-state",
            away: "harding",
            status: "final",
            home_score: 3,
            away_score: 0,
          },
          {
            id: "3",
            date: "2025-09-19",
            home: "harding",
            away: "rogers-state",
            status: "final",
            home_score: 1,
            away_score: 1,
          },
        ],
      },
      team: "harding",
      today: "2026-08-09",
    });
    expect(html).toContain('class="w" title="FRI SEP 5 · W 2–1"');
    expect(html).toContain('class="l" title="FRI SEP 12 · L 3–0"');
    expect(html).toContain('class="d" title="FRI SEP 19 · D 1–1"');

    // The conference rail keeps its single played colour — a matchday tick
    // aggregates several teams' games and has no one outcome.
    const conference = composeBoard({
      projectName: "p",
      fixtures: {
        ...base,
        programmes: [...base.programmes, { slug: "newman", name: "Newman" }],
        fixtures: [
          {
            id: "1",
            date: "2026-08-27",
            home: "harding",
            away: "rogers-state",
            status: "scheduled",
          },
        ],
      },
      today: "2026-08-09",
    });
    expect(conference).not.toContain('class="w"');
  });

  test("matrix team cells carry a record bar once matches are played", () => {
    const html = composeBoard({
      projectName: "p",
      fixtures: {
        ...base,
        season: 2025,
        fixtures: [
          {
            id: "1",
            date: "2025-09-05",
            home: "harding",
            away: "rogers-state",
            status: "final",
            home_score: 2,
            away_score: 1,
          },
          {
            id: "2",
            date: "2025-09-12",
            home: "rogers-state",
            away: "harding",
            status: "final",
            home_score: 3,
            away_score: 3,
          },
        ],
      },
      today: "2026-08-09",
    });
    expect(html).toContain('title="1 won · 1 drawn · 0 lost"');
    expect(html).toContain('title="0 won · 1 drawn · 1 lost"');

    // Pre-season: nothing played, no bar — the cell stays a name.
    const pre = composeBoard({
      projectName: "p",
      fixtures: {
        ...base,
        fixtures: [
          {
            id: "1",
            date: "2026-08-27",
            home: "harding",
            away: "rogers-state",
            status: "scheduled",
          },
        ],
      },
      today: "2026-08-09",
    });
    expect(pre).not.toContain('class="rec"');
  });

  test("pre-season shows a countdown and no table", () => {
    const html = render({
      fixtures: [
        { id: "1", date: "2026-08-27", home: "harding", away: "rogers-state", status: "scheduled" },
      ],
    });
    // The rail carries the countdown; a table of standings is not v1's job.
    expect(html).toContain("First kickoff in");
    expect(html).not.toContain("Member record");
    expect(html).toContain("Pre-season is a valid state");
  });

  test("a played fixture does not make v1 invent a standings table", () => {
    const html = render({
      conference_game_source: "derived:both-members",
      fixtures: [
        {
          id: "1",
          date: "2026-09-01",
          home: "harding",
          away: "rogers-state",
          status: "final",
          home_score: 2,
          away_score: 1,
        },
      ],
    });
    // Two programmes render the matchday matrix; the result appears in a cell,
    // never as a derived standings row.
    expect(html).toContain("Matchday board");
    expect(html).toContain("2\u20131");
    expect(html).not.toContain("Member record");
    expect(html).not.toContain("<th>Pts</th>");
  });

  test("the conference lens is a matchday matrix: one game, both rows", () => {
    const html = render({
      fixtures: [
        {
          id: "g1",
          date: "2026-09-17",
          time: "19:00",
          home: "harding",
          away: "rogers-state",
          venue: "Stevens Soccer Complex",
          status: "scheduled",
          conference_game: true,
        },
        // A non-conference visitor appears as a dashed cell, never as a row.
        {
          id: "g2",
          date: "2026-08-27",
          home: "harding",
          away: "delta-st",
          status: "scheduled",
          conference_game: false,
        },
      ],
    });
    // The game renders in the home row (shaded) and the away row (outlined).
    expect(html).toContain('class="m h"');
    expect(html).toContain('data-h="harding" data-a="rogers-state"');
    expect((html.match(/data-g="g1"/g) ?? []).length).toBe(2);
    // The outsider gets a cell in Harding's row only \u2014 no delta-st row exists,
    // and its slug expands to a readable name ("Delta ST" is not a school).
    expect(html).toContain('class="m h nc');
    expect(html).not.toContain('data-follow="delta-st"');
    expect(html).toContain("Delta State at Harding");
    // Each row carries its follow summary; the card names the next kickoff.
    expect(html).toContain("Harding \u00b7 2 home \u00b7 0 away \u00b7 1 conference");
    expect(html).toContain("Rogers State at Harding");
    expect(html).toContain("Thursday \u00b7 7:00 PM \u00b7 Stevens Soccer Complex");
  });

  describe("the roster sheet", () => {
    const rosters: RostersFile = {
      schema: "touchline.rosters/1",
      season: 2026,
      gender: "men",
      collected_at: "2026-08-09T21:00:00Z",
      rosters: {
        harding: {
          programme: "harding",
          players: [
            {
              number: "9",
              name: "Reik Barrack",
              position: "Forward",
              class_year: "Senior",
              height: "6'0\"",
              hometown: "Panama City, Panama",
            },
            {
              number: "1",
              name: "Dillon Hart",
              position: "Goalkeeper",
              class_year: "Sophomore",
              height: "6'5\"",
              hometown: "Lavon, Texas",
            },
          ],
        },
        "rogers-state": {
          programme: "rogers-state",
          // No positions published — the real shape of two GAC rosters.
          players: [{ name: "A Player", class_year: "Freshman", hometown: "Tulsa, Okla." }],
        },
      },
    };
    const compose = (team?: string) =>
      composeBoard({
        projectName: "p",
        fixtures: {
          ...base,
          programmes: [...base.programmes, { slug: "newman", name: "Newman" }],
          fixtures: [
            {
              id: "1",
              date: "2026-09-01",
              home: "harding",
              away: "rogers-state",
              status: "scheduled",
            },
          ],
        },
        rosters,
        team,
        today: "2026-08-09",
      });

    test("a team page leads with its people — roster above schedule", () => {
      const html = compose("harding");
      expect(html.indexOf("<h2>Roster</h2>")).toBeGreaterThan(-1);
      expect(html.indexOf("<h2>Roster</h2>")).toBeLessThan(html.indexOf("<h2>Schedule</h2>"));
    });

    test("the conference lens keeps the matchday board above roster balance", () => {
      const html = compose();
      expect(html.indexOf("Matchday board")).toBeLessThan(html.indexOf("Roster balance"));
    });

    test("the team lens groups attack-first with hometown and height on the row", () => {
      const html = compose("harding");
      expect(html.indexOf("Forwards")).toBeLessThan(html.indexOf("Goalkeepers"));
      // Height typeset with primes; an international region set apart; a US
      // region left plain.
      expect(html).toContain("6′0″");
      expect(html).toContain("Panama City, <b>Panama</b>");
      expect(html).toContain("Lavon, Texas");
      expect(html).not.toContain("Lavon, <b>");
    });

    test("a roster without published positions is a squad, never fake buckets", () => {
      const html = compose("rogers-state");
      expect(html).toContain("Squad");
      expect(html).not.toContain("Forwards");
    });

    test("abbreviated positions group the same as full words", () => {
      // Two live themes publish bare abbreviations: GK/D/MF/F and GK/DEF/MID/FWD.
      const abbreviated: RostersFile = {
        ...rosters,
        rosters: {
          harding: {
            programme: "harding",
            players: [
              { name: "A Fwd", position: "F" },
              { name: "B Fwd", position: "FWD" },
              { name: "C Mid", position: "MF" },
              { name: "D Mid", position: "MID" },
              { name: "E Def", position: "D" },
              { name: "F Def", position: "DEF" },
              { name: "G Keeper", position: "GK" },
            ],
          },
        },
      };
      const html = composeBoard({
        projectName: "p",
        fixtures: base,
        rosters: abbreviated,
        team: "harding",
        today: "2026-08-09",
      });
      for (const head of ["Forwards", "Midfielders", "Defenders", "Goalkeepers"]) {
        expect(html).toContain(head);
      }
      expect(html).not.toContain("Position not listed");
    });

    test("the conference lens compares rosters and names every absence", () => {
      const html = compose();
      expect(html).toContain("Roster balance");
      // rogers-state publishes no positions → hatched, dashed counts.
      expect(html).toContain('class="cmix unp"');
      // newman has no roster at all → named, not omitted.
      expect(html).toContain("not collected");
    });
  });

  describe("player season statistics", () => {
    const rosters: RostersFile = {
      schema: "touchline.rosters/1",
      season: 2025,
      gender: "men",
      collected_at: "2026-08-10T00:00:00Z",
      rosters: {
        harding: {
          programme: "harding",
          players: [
            {
              number: "11",
              name: "Nojus Grudis",
              position: "Forward",
              class_year: "Senior",
              source_url: "https://hardingsports.com/sports/mens-soccer/roster/nojus-grudis/18800",
            },
            {
              number: "1",
              name: "Rinner Stewart",
              position: "Goalkeeper",
              source_url:
                "https://hardingsports.com/sports/mens-soccer/roster/rinner-stewart/19271",
            },
            // No bio URL — the join must fall back to the published name.
            { number: "14", name: "Mason Hahn", position: "Forward" },
            // On the roster, never appeared: no stats line at all.
            { number: "31", name: "Fresh Walkon", position: "Midfielder" },
          ],
        },
      },
    };
    const stats: StatsFile = {
      schema: "touchline.stats/1",
      season: 2025,
      gender: "men",
      collected_at: "2026-08-10T00:00:00Z",
      teams: {
        harding: {
          programme: "harding",
          players: [
            {
              name: "Nojus Grudis",
              player_id: "18800",
              number: "11",
              gp: 16,
              gs: 16,
              minutes: 1152,
              goals: 4,
              assists: 2,
              points: 10,
              shots: 18,
              sog: 9,
              yellow: 3,
              red: 0,
            },
            { name: "Mason Hahn", player_id: "99999", minutes: 129, goals: 2, shots: 3 },
          ],
          keepers: [
            {
              name: "Rinner Stewart",
              player_id: "19271",
              gp: 14,
              gs: 14,
              minutes: 1212,
              goals_against: 31,
              gaa: 2.3,
              saves: 77,
              save_pct: 0.713,
              wins: 2,
              losses: 10,
              ties: 1,
              shutouts: 1,
              shots_faced: 246,
            },
          ],
        },
      },
    };
    const season2025: FixturesFile = {
      ...base,
      season: 2025,
      fixtures: [
        {
          id: "1",
          date: "2025-09-01",
          home: "harding",
          away: "rogers-state",
          status: "final",
          home_score: 2,
          away_score: 1,
        },
      ],
    };
    const compose = (player?: string, withStats = true) =>
      composeBoard({
        projectName: "p",
        fixtures: season2025,
        rosters,
        stats: withStats ? stats : undefined,
        team: "harding",
        player,
        today: "2026-08-09",
      });

    test("roster rows carry the season at a glance — minutes bar and the telling numbers", () => {
      const html = compose();
      // Grudis: joined by id; minutes scaled against the squad's most-used
      // player (the keeper's 1212).
      expect(html).toContain("1152&prime;");
      expect(html).toContain("<b>4</b>G");
      expect(html).toContain("<b>2</b>A");
      // The keeper row tells the keeper's story, not a shots story.
      expect(html).toContain("<b>77</b>SV");
      expect(html).toContain("<b>31</b>GA");
      expect(html).toContain("71%");
      // Name-fallback join: Hahn has no bio URL but still gets his line.
      expect(html).toContain("129&prime;");
    });

    test("rows are buttons into the drawer only once statistics exist", () => {
      const withStats = compose();
      expect(withStats).toContain('data-act="select-player"');
      expect(withStats).toContain("&quot;player&quot;:&quot;18800&quot;");
      // Hahn's key falls back to his name.
      expect(withStats).toContain("&quot;player&quot;:&quot;Mason Hahn&quot;");
      const without = compose(undefined, false);
      expect(without).not.toContain('data-act="select-player"');
    });

    test("the drawer tells one player's season, and every close path posts null", () => {
      const html = compose("18800");
      expect(html).toContain('role="dialog"');
      expect(html).toContain("Nojus Grudis");
      expect(html).toContain("Harding · 2025 season");
      // Minutes against the schedule's available minutes: 1 played match = 90.
      expect(html).toContain("1152&prime; of 90&prime; available");
      expect(html).toContain("<b>4</b><span>Goals</span>");
      expect(html).toContain("9 of 18 shots on target");
      expect(html).toContain("3 yellow, 0 red");
      const closes = html.match(/data-payload='\{"player":null\}'/g) ?? [];
      expect(closes.length).toBeGreaterThanOrEqual(2); // veil and ✕
    });

    test("a keeper's drawer is saves against goals, not a shooting card", () => {
      const html = compose("19271");
      expect(html).toContain("Goalkeeping");
      expect(html).toContain("71.3%");
      expect(html).toContain("77 saved");
      expect(html).toContain("31 conceded");
      expect(html).toContain("2–10–1");
      expect(html).not.toContain("<span>Conversion</span>");
    });

    test("a rostered player who never appeared gets an honest drawer, not zeros", () => {
      const html = compose("Fresh Walkon");
      expect(html).toContain("on the roster, but yet to appear");
      expect(html).not.toContain("<b>0</b><span>Goals</span>");
    });

    test("statistics gaps are named alongside schedule and roster gaps", () => {
      const html = composeBoard({
        projectName: "p",
        fixtures: season2025,
        rosters,
        stats: { ...stats, missing: ["rogers-state"] },
        today: "2026-08-09",
      });
      expect(html).toContain("Rogers State (stats)");
    });
  });

  test("a single-programme season keeps the ledger, not a one-row matrix", () => {
    const html = render({
      programmes: [{ slug: "harding", name: "Harding" }],
      fixtures: [
        { id: "1", date: "2026-09-01", home: "harding", away: "delta-st", status: "scheduled" },
      ],
    });
    expect(html).not.toContain("Matchday board");
    expect(html).toContain('class="led"');
  });

  test("collection gaps are named on the board, never hidden", () => {
    const html = render({ missing: ["rogers-state"] });
    expect(html).toContain("collection gap");
    expect(html).toContain("Rogers State");
  });

  test("extrapolated membership is disclosed", () => {
    expect(render({ membership_extrapolated: true })).toContain("Membership carried forward");
  });

  test("markup is escaped, so a hostile programme name cannot inject", () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const html = render({
      programmes: [
        { slug: "x", name: hostile },
        { slug: "rogers-state", name: "Rogers State" },
      ],
      // A fixture is needed for the full name to reach a card and a table row.
      fixtures: [
        {
          id: "1",
          date: "2026-09-01",
          home: "x",
          away: "rogers-state",
          status: "final",
          home_score: 1,
          away_score: 0,
          venue: '"><script>alert(2)</script>',
        },
      ],
    });
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("<script>alert(2)");
  });

  test("the team lens reports published fixtures without deriving a record", () => {
    const html = render(
      {
        fixtures: [
          {
            id: "1",
            date: "2026-09-01",
            home: "harding",
            away: "rogers-state",
            status: "final",
            home_score: 2,
            away_score: 1,
          },
        ],
      },
      "harding",
    );
    // The ledger orients the scoreline to the team being viewed, and no
    // W-L-D record is derived anywhere in v1.
    expect(html).toContain("2\u20131");
    expect(html).not.toContain("1–0–0");
    expect(html).toContain("Rogers State");
    expect(html).toContain(">H<");
  });

  test("every empty state renders real markup and names the next step", () => {
    for (const html of [
      composeNoProject(["a", "b"]),
      composeNotAHome("p", true),
      composeNotAHome("p", false),
      composeNoSeasons("p"),
    ]) {
      expect(html).toContain('<div class="sheet">');
      expect(html.length).toBeGreaterThan(500);
    }
    expect(composeNoProject([])).toContain("/touchline my-soccer");
    expect(composeUnreadable("boom")).toContain("THE BOARD DID NOT RENDER");
  });

  test("a read failure never renders as an empty season", () => {
    const html = composeUnreadable("no such file");
    expect(html).toContain("read failure, not an empty season");
  });
});

describe("the fixtures schema", () => {
  test("rejects an unknown field rather than ignoring it", () => {
    expect(() => fixturesFileSchema.parse({ ...base, surprise: 1 })).toThrow();
  });

  test("rejects a non-ISO date", () => {
    expect(() =>
      fixturesFileSchema.parse({
        ...base,
        fixtures: [{ id: "1", date: "9/1/2026", home: "a", away: "b", status: "scheduled" }],
      }),
    ).toThrow();
  });

  test("a stats file round-trips, and an unknown stat field is rejected", () => {
    const file = {
      schema: "touchline.stats/1",
      season: 2025,
      gender: "men",
      collected_at: "2026-08-10T00:00:00Z",
      teams: {
        harding: {
          programme: "harding",
          players: [{ name: "Nojus Grudis", player_id: "18800", goals: 4, minutes: 1152 }],
          keepers: [{ name: "Rinner Stewart", saves: 77, save_pct: 0.713 }],
        },
      },
    };
    expect(statsFileSchema.parse(file).teams.harding?.players[0]?.goals).toBe(4);
    const poisoned = structuredClone(file) as Record<string, unknown>;
    (
      (poisoned.teams as Record<string, { players: Record<string, unknown>[] }>).harding
        ?.players[0] as Record<string, unknown>
    ).xg = 1.2;
    expect(() => statsFileSchema.parse(poisoned)).toThrow();
  });
});

describe("understanding the ask", () => {
  test("the exact first-contact ask resolves and the agent no longer blocks 2026", async () => {
    const target = await resolveTargets("harding", "men", 2026);
    expect(target.kind).toBe("programme");
    if (target.kind === "programme") expect(target.slugs).toEqual(["harding"]);

    const prompt = touchlineSystemPrompt({ programmes: ["harding"] });
    expect(prompt).not.toContain("stop at the 2025 season");
    expect(prompt).not.toContain("This first flow is 2026 only");
    expect(prompt).toContain("What each season can give you");
    expect(prompt).toContain("Any earlier season back to 2016");
    expect(TOUCHLINE_V1_SEASON).toBe(2026);
  });

  test("a past season plans every layer — the archive serves them all", () => {
    // Remeasured 2026-08-09 with the DOM parser: every site serves genuine
    // past schedules (results included) in its rendered markup; only the
    // embedded payload is stuck on the current season. The old roster-only
    // plan was reading the wrong layer. Statistics measured 2026-08-10:
    // honest per-year pages on every site, back to 2016.
    const plan = planForSeason(2019);
    expect(plan.empty).toBe(false);
    expect(plan.attempted).toEqual(["schedule", "roster", "stats"]);
    expect(planSummary(plan)).toContain("Collecting schedule, roster, and stats for 2019");
  });

  test("the current season plans every layer", () => {
    const plan = planForSeason(2026);
    expect(plan.attempted).toEqual(["schedule", "roster", "stats"]);
    expect(plan.empty).toBe(false);
  });

  test("only an unservable season is refused outright", () => {
    const future = planForSeason(2031);
    expect(future.empty).toBe(true);
    expect(unsupportedSeasonMessage(2031)).toContain("has not been published yet");

    const ancient = planForSeason(1998);
    expect(ancient.empty).toBe(true);
    expect(unsupportedSeasonMessage(1998)).toContain("predates");
  });

  test("a conference resolves to its members for that season", async () => {
    const t = await resolveTargets("gac", "men", 2025);
    expect(t.kind).toBe("conference");
    if (t.kind === "conference") {
      expect(t.slugs).toContain("harding");
      expect(t.slugs.length).toBe(7);
    }
  });

  test("a single programme resolves to itself, not to its conference", async () => {
    const t = await resolveTargets("harding", "men", 2025);
    expect(t.kind).toBe("programme");
    if (t.kind === "programme") {
      expect(t.slugs).toEqual(["harding"]);
      expect(t.conference).toBe("GAC");
    }
  });

  test("an unknown school is reported, never guessed at", async () => {
    const t = await resolveTargets("wossamotta u", "men", 2025);
    expect(t.kind).toBe("unknown");
    if (t.kind === "unknown") {
      expect(t.suggestions.length).toBeGreaterThan(0);
      expect(t.knownConferences).toContain("GAC");
    }
  });

  test("a programme absent that season is still resolvable by name", async () => {
    // Fort Hays State men were non_member in 2018; the target still resolves,
    // and its conference for that season is reported honestly.
    const t = await resolveTargets("fort-hays-state", "men", 2018);
    expect(t.kind).toBe("programme");
    if (t.kind === "programme") expect(t.slugs).toEqual(["fort-hays-state"]);
  });
});
