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
  loadRosterHistory,
  readMarker,
  seasonFileName,
} from "../src/datahome.ts";
import {
  _resetMembershipCache,
  _setMembershipCache,
  knownConferences,
  type MembershipFile,
  resolveConference,
  resolveTargets,
} from "../src/membership.ts";
import {
  computeTable,
  type FixturesFile,
  fixturesFileSchema,
  type MatchesFile,
  matchesFileSchema,
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
  schema: "touchline.fixtures/2",
  season: 2026,
  gender: "men",
  conference: "GAC",
  collected_at: "2026-08-09T21:00:00Z",
  programmes: [
    { slug: "harding", name: "Harding", conference: "GAC" },
    { slug: "rogers-state", name: "Rogers State", conference: "GAC" },
  ],
  fixtures: [],
};

async function tempHome(): Promise<string> {
  return mkdtemp(join(tmpdir(), "touchline-test-"));
}

describe("membership resolution", () => {
  test("collectable conferences come from the shipped membership data", async () => {
    expect(await knownConferences()).toEqual(["GAC", "GSC", "LSC", "MIAA"]);
  });

  test("adding a conference to membership data advertises it without code changes", async () => {
    const membership: MembershipFile = {
      conferences: ["GAC", "LSC", "independent", "non_member"],
      memberships: {},
    };

    _setMembershipCache(membership);
    try {
      expect(await knownConferences()).toEqual(["GAC", "LSC"]);
    } finally {
      _resetMembershipCache();
    }
  });

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

  test("the authoring horizon is per-conference, not the file's global maximum", async () => {
    // non_member women are authored only through 2018, while GAC and MIAA women
    // run to 2025. Taking the maximum across the whole file borrowed 2025, which
    // stopped this from extrapolating, matched no window, and resolved to
    // nothing. Adding a conference authored further ahead than the GAC would do
    // exactly that to the GAC.
    const res = await resolveConference("non_member", "women", 2020);
    expect(res.authoredThrough).toBe(2018);
    expect(res.extrapolated).toBe(true);
    expect(res.slugs.length).toBeGreaterThan(0);
  });

  test("a conference with no windows for a gender borrows no horizon", async () => {
    // The file declares MIAA but authors no MIAA men's windows at all, so the
    // honest answer is that it authors nothing — not the GAC's 2025.
    const miaaMen = await resolveConference("MIAA", "men", 2025);
    expect(miaaMen.authoredThrough).toBe(0);
    expect(miaaMen.slugs).toEqual([]);
    // And the GAC's own horizon is unaffected by its neighbours.
    const gac = await resolveConference("GAC", "men", 2026);
    expect(gac.authoredThrough).toBe(2025);
    expect(gac.slugs.length).toBe(7);
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
    const res = await loadFixtures(root, 2026, "men", "GAC");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.reason).toBe("absent");
    expect(await listSeasons(root)).toEqual([]);
  });

  test("a malformed season file reports invalid, never renders as empty", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(join(root, "data", "fixtures", "2026-men-gac.json"), "{ not json", "utf8");
    const res = await loadFixtures(root, 2026, "men", "GAC");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.reason).toBe("invalid");
  });

  test("a file failing the schema is invalid, not silently accepted", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(
      join(root, "data", "fixtures", "2026-men-gac.json"),
      JSON.stringify({ schema: "touchline.fixtures/99", season: 2026 }),
      "utf8",
    );
    const res = await loadFixtures(root, 2026, "men", "GAC");
    expect(res.ok).toBe(false);
  });

  test("conference-sharded seasons round-trip without collapsing", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    const lsc = {
      ...base,
      conference: "LSC",
      programmes: [{ slug: "lubbock-christian", name: "Lubbock Christian", conference: "LSC" }],
    };
    await writeFile(
      join(root, "data", "fixtures", "2026-men-gac.json"),
      JSON.stringify(base),
      "utf8",
    );
    await writeFile(
      join(root, "data", "fixtures", "2026-men-lsc.json"),
      JSON.stringify(lsc),
      "utf8",
    );
    const res = await loadFixtures(root, 2026, "men", "GAC");
    expect(res.ok).toBe(true);
    expect(seasonFileName(2026, "men", " Lone Star Conference ")).toBe(
      "2026-men-lone-star-conference.json",
    );
    const seasons = await listSeasons(root);
    expect(seasons).toEqual([
      { season: 2026, gender: "men", conference: "gac", hasFixtures: true, hasRosters: false },
      { season: 2026, gender: "men", conference: "lsc", hasFixtures: true, hasRosters: false },
    ]);
  });

  test("legacy filenames are ignored until the data home is migrated", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(join(root, "data", "fixtures", "2026-men.json"), JSON.stringify(base), "utf8");
    expect(await listSeasons(root)).toEqual([]);
    const res = await loadFixtures(root, 2026, "men", "GAC");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.reason).toBe("absent");
  });

  test("a roster-only past season is still listed", async () => {
    // The historic case: each programme serves its CURRENT fixtures at every
    // season address, so a 2019 collection lands a roster and no schedule. A
    // season list keyed on fixtures alone would hide exactly the data the
    // roster analysis needs.
    const root = await tempHome();
    await bootstrapDataHome(root);
    await writeFile(
      join(root, "data", "fixtures", "2026-men-gac.json"),
      JSON.stringify(base),
      "utf8",
    );
    await writeFile(
      join(root, "data", "rosters", "2019-men-gac.json"),
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
      conference: "gac",
      hasFixtures: false,
      hasRosters: true,
    });
  });

  test("the roster history is per-gender, oldest first, and tolerates a corrupt season", async () => {
    const root = await tempHome();
    await bootstrapDataHome(root);
    const roster = (season: number, gender: string) =>
      JSON.stringify({
        schema: "touchline.rosters/1",
        season,
        gender,
        collected_at: "2026-08-09T00:00:00Z",
        rosters: { harding: { programme: "harding", players: [{ name: "Aric McKinney" }] } },
      });
    const dir = join(root, "data", "rosters");
    await writeFile(join(dir, "2026-men-gac.json"), roster(2026, "men"), "utf8");
    await writeFile(join(dir, "2024-men-gac.json"), roster(2024, "men"), "utf8");
    // A corrupt archive season narrows visible history, never fails the load.
    await writeFile(join(dir, "2025-men-gac.json"), "{not json", "utf8");
    await writeFile(join(dir, "2024-women-gac.json"), roster(2024, "women"), "utf8");

    const men = await loadRosterHistory(root, "men");
    expect(men.map((f) => f.season)).toEqual([2024, 2026]);
    const women = await loadRosterHistory(root, "women");
    expect(women.map((f) => f.season)).toEqual([2024]);
    expect(await loadRosterHistory(join(root, "nowhere"), "men")).toEqual([]);
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
      { season: 2026, gender: "men", conference: "gac" },
      { season: 2025, gender: "men", conference: "gac" },
      { season: 2025, gender: "men", conference: "lsc" },
      { season: 2024, gender: "men", conference: "gac" },
    ];
    const mid = composeBoard({
      projectName: "p",
      fixtures: { ...base, season: 2025 },
      today: "2026-08-09",
      seasons,
    });
    // Season chevrons stay within the conference; the separate rail offers the LSC jump.
    expect(mid).toContain('data-act="select-season"');
    expect(mid).toContain("&quot;season&quot;:2024");
    expect(mid).toContain("&quot;season&quot;:2026");
    expect(mid).toContain("&quot;conference&quot;:&quot;gac&quot;");
    expect(mid).toContain("&quot;conference&quot;:&quot;lsc&quot;");
    expect(mid).toContain(
      "&quot;season&quot;:2025,&quot;gender&quot;:&quot;men&quot;,&quot;conference&quot;:&quot;lsc&quot;",
    );

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
        { season: 2026, gender: "men", conference: "gac" },
        { season: 2025, gender: "men", conference: "gac" },
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
        programmes: [...base.programmes, { slug: "newman", name: "Newman", conference: "GAC" }],
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
    // No legend: the home tint and spoken labels carry venue.
    expect(html).not.toContain(">Selected<");
    // The masthead carries the gender as a tag; the dek line is gone, and the
    // collected stamp lives in the panel head, not on the sheet.
    expect(html).toContain('<span class="gen">Men</span>');
    expect(html).not.toContain("programmes</p>");
    expect(html).not.toContain("collected 2026-08-09");
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
          programmes: [...base.programmes, { slug: "newman", name: "Newman", conference: "GAC" }],
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

    test("rows are buttons into the drawer with or without statistics", () => {
      const withStats = compose();
      expect(withStats).toContain('data-act="select-player"');
      expect(withStats).toContain("&quot;player&quot;:&quot;18800&quot;");
      // Hahn's key falls back to his name.
      expect(withStats).toContain("&quot;player&quot;:&quot;Mason Hahn&quot;");
      // Pre-season the drawer still holds the bio and tenure, so the row
      // must open it even before any statistics are collected.
      const without = compose(undefined, false);
      expect(without).toContain('data-act="select-player"');
    });

    test("a pre-season drawer offers the bio and says statistics are yet to come", () => {
      const html = compose("18800", false);
      expect(html).toContain('role="dialog"');
      expect(html).toContain("Nojus Grudis");
      expect(html).toContain("Forward · Senior");
      expect(html).toContain("No 2025 season statistics collected for Harding yet.");
      expect(html).toContain("From the programme&#39;s published roster.");
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
      programmes: [{ slug: "harding", name: "Harding", conference: "GAC" }],
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
        { slug: "x", name: hostile, conference: "GAC" },
        { slug: "rogers-state", name: "Rogers State", conference: "GAC" },
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

  test("requires a conference on every programme", () => {
    expect(() =>
      fixturesFileSchema.parse({
        ...base,
        programmes: [{ slug: "harding", name: "Harding" }],
      }),
    ).toThrow();
  });

  test("a matches file round-trips, and an unknown match field is rejected", () => {
    const file = {
      schema: "touchline.matches/1",
      season: 2025,
      gender: "men",
      collected_at: "2026-08-10T00:00:00Z",
      matches: {
        "sidearm:harding:14830": {
          source_url: "https://hardingsports.com/sports/mens-soccer/stats/2025/snu/boxscore/14830",
          home_index: 1,
          teams: [
            {
              name: "Southern Nazarene",
              abbr: "SNU",
              periods: [0, 3],
              score: 3,
              winner: true,
              shots: 27,
            },
            {
              name: "Harding",
              abbr: "HU",
              periods: [1, 1],
              score: 2,
              shots: 10,
              keepers: [{ name: "Rinner Stewart", saves: 2 }],
            },
          ],
          scoring: [{ time: "37:00", team: 1, scorer: "Nojus Grudis", assist: "Romario Castro" }],
          cards: [{ time: "81:19", team: 1, type: "red", player: "Cian Halpin", number: "7" }],
          plays: [
            {
              period: "1",
              clock: "22:20",
              team: 0,
              text: "GOAL by SNU Fletcher, Alex.",
              type: "goal",
              score: [1, 0],
            },
            // Shootout rows carry no clock, and an untyped play is still a play.
            { period: "SO", team: 1, text: "Official's timeout." },
          ],
          stadium: "Stevens Soccer Complex",
          attendance: 175,
        },
      },
      missing: { "sidearm:harding:9999": "no box-score link on any collected schedule page" },
    };
    const parsed = matchesFileSchema.parse(file);
    expect(parsed.matches["sidearm:harding:14830"]?.teams[0]?.shots).toBe(27);
    expect(parsed.matches["sidearm:harding:14830"]?.plays?.[0]?.score).toEqual([1, 0]);
    expect(parsed.missing?.["sidearm:harding:9999"]).toContain("no box-score link");
    const poisoned = structuredClone(file) as Record<string, unknown>;
    const inner = (poisoned.matches as Record<string, Record<string, unknown>>)[
      "sidearm:harding:14830"
    ] as Record<string, unknown>;
    inner.xg = 1.2;
    expect(() => matchesFileSchema.parse(poisoned)).toThrow();
    // A play must narrate: text is required, a running score is exactly two
    // sides, and unknown play fields are refused like any other.
    const bad = (mutate: (play: Record<string, unknown>) => void): unknown => {
      const clone = structuredClone(file) as Record<string, unknown>;
      const detail = (clone.matches as Record<string, Record<string, unknown>>)[
        "sidearm:harding:14830"
      ] as Record<string, unknown>;
      mutate((detail.plays as Record<string, unknown>[])[0] as Record<string, unknown>);
      return clone;
    };
    expect(() => matchesFileSchema.parse(bad((p) => delete p.text))).toThrow();
    expect(() => matchesFileSchema.parse(bad((p) => (p.score = [1])))).toThrow();
    expect(() => matchesFileSchema.parse(bad((p) => (p.xg = 0.4)))).toThrow();
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
    // honest per-year pages on every site, back to 2016 — and the box scores
    // they link, measured the same day, prove their own match by title date.
    const plan = planForSeason(2019);
    expect(plan.empty).toBe(false);
    expect(plan.attempted).toEqual(["schedule", "roster", "stats", "matches"]);
    expect(planSummary(plan)).toContain("Collecting schedule, roster, stats, and matches for 2019");
  });

  test("the current season plans every layer", () => {
    const plan = planForSeason(2026);
    expect(plan.attempted).toEqual(["schedule", "roster", "stats", "matches"]);
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

  test("a programme reads its own conference horizon", async () => {
    const membership: MembershipFile = {
      conferences: ["GAC", "LSC", "independent", "non_member"],
      memberships: {
        harding: {
          men: [
            {
              conference: "GAC",
              from_season: 2016,
              to_season: 2024,
              source: "test",
            },
          ],
        },
        "ut-tyler": {
          men: [
            {
              conference: "LSC",
              from_season: 2019,
              to_season: 2026,
              source: "test",
            },
          ],
        },
      },
    };

    _setMembershipCache(membership);
    try {
      const lsc = await resolveTargets("ut-tyler", "men", 2026);
      expect(lsc.kind).toBe("programme");
      if (lsc.kind === "programme") {
        expect(lsc.conference).toBe("LSC");
        expect(lsc.extrapolated).toBe(false);
        expect(lsc.authoredThrough).toBe(2026);
      }

      const gac = await resolveTargets("harding", "men", 2026);
      expect(gac.kind).toBe("programme");
      if (gac.kind === "programme") {
        expect(gac.conference).toBe("GAC");
        expect(gac.extrapolated).toBe(true);
        expect(gac.authoredThrough).toBe(2024);
      }
    } finally {
      _resetMembershipCache();
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

describe("match detail (box scores)", () => {
  const season2025: FixturesFile = {
    ...base,
    season: 2025,
    fixtures: [
      {
        id: "sidearm:harding:14830",
        date: "2025-09-27",
        home: "harding",
        away: "rogers-state",
        status: "final",
        home_score: 2,
        away_score: 3,
        conference_game: true,
      },
      {
        id: "sidearm:harding:14840",
        date: "2025-10-04",
        home: "rogers-state",
        away: "harding",
        status: "final",
        home_score: 1,
        away_score: 0,
      },
      {
        id: "sidearm:harding:14850",
        date: "2025-11-20",
        home: "harding",
        away: "rogers-state",
        status: "scheduled",
        time: "19:00",
      },
    ],
  };
  const matches: MatchesFile = {
    schema: "touchline.matches/1",
    season: 2025,
    gender: "men",
    collected_at: "2026-08-10T00:00:00Z",
    matches: {
      "sidearm:harding:14830": {
        source_url: "https://hardingsports.com/sports/mens-soccer/stats/2025/rsu/boxscore/14830",
        home_index: 0,
        teams: [
          {
            name: "Harding",
            abbr: "HU",
            periods: [1, 1],
            score: 2,
            shots: 10,
            sog: 4,
            saves: 6,
            corners: 4,
            fouls: 9,
            keepers: [{ name: "Rinner Stewart", saves: 6, goals_against: 3, minutes: 90 }],
          },
          {
            name: "Rogers State",
            abbr: "RSU",
            periods: [0, 3],
            score: 3,
            winner: true,
            shots: 27,
            sog: 9,
            saves: 2,
            corners: 9,
            fouls: 7,
            keepers: [{ name: "Milo Stopper", saves: 2, goals_against: 2, minutes: 90 }],
          },
        ],
        scoring: [
          {
            time: "37:00",
            team: 0,
            scorer: "Nojus Grudis",
            season_total: 4,
            assist: "Romario Castro",
            description: "pass to middle, shot to bottom right corner",
          },
          { time: "50:59", team: 1, scorer: "Braxton Decker" },
          { time: "90:00", team: 0, scorer: "Sikan Akpanudo" },
        ],
        cards: [
          { time: "62:17", team: 1, type: "yellow", player: "Omarion Velasquez", number: "12" },
          { time: "81:19", team: 0, type: "red", player: "Cian Halpin", number: "7" },
        ],
        stadium: "Stevens Soccer Complex",
        attendance: 175,
        officials: ["Referee: Blake Kibboes"],
      },
    },
    missing: {
      "sidearm:harding:14840": "no box-score link on any collected schedule page",
    },
  };
  const compose = (
    fixture?: string,
    team: string | undefined = "harding",
    file: MatchesFile = matches,
  ) =>
    composeBoard({
      projectName: "p",
      fixtures: season2025,
      matches: file,
      team,
      fixture,
      today: "2026-08-09",
    });

  test("a played row carries the match at a glance — SOG and corner pairs, cards, scorers", () => {
    const html = compose();
    // Oriented mine–theirs from the team lens: Harding 4 SOG, RSU 9.
    expect(html).toContain("SOG 4–9");
    expect(html).toContain("CK 4–9");
    // One yellow, one red between the sides; the strip counts them.
    expect(html).toContain('class="cs y"');
    expect(html).toContain('class="cs r"');
    // The team lens names its own scorers with the goal minute read aloud.
    expect(html).toContain("Nojus Grudis 37&prime;");
    expect(html).toContain("Sikan Akpanudo 90&prime;");
    // The opponent's scorer stays off the row.
    expect(html).not.toContain("Braxton Decker 51&prime;");
    // A played fixture with no collected box score renders a plain row.
    const bare =
      html.split('data-payload="{&quot;fixture&quot;:&quot;sidearm:harding:14840&quot;}"')[1] ?? "";
    expect(bare.split('class="row')[0]).not.toContain("SOG");
  });

  test("the match drawer reads as a box score — period line, timeline, duels, keepers", () => {
    const html = compose("sidearm:harding:14830");
    // Header: both sides with the fixture's own scores, winner emphasised.
    expect(html).toContain("Rogers State");
    expect(html).toContain('class="mrow win"');
    // Meta line from the box score's own details.
    expect(html).toContain("Stevens Soccer Complex");
    expect(html).toContain("175 attended");
    // Period line with the served halves.
    expect(html).toContain("Score by period");
    // Scoring timeline: minute in bold, scorer, assist.
    expect(html).toContain("<b>37&prime;</b>");
    expect(html).toContain("assist Romario Castro");
    // 90:00 exactly is the 90th minute, not the 91st.
    expect(html).toContain("<b>90&prime;</b>");
    // Cautions with typed cards.
    expect(html).toContain("Omarion Velasquez");
    // Team statistic duels.
    expect(html).toContain(">Shots<");
    expect(html).toContain(">Corners<");
    // Keeper match lines from both sides.
    expect(html).toContain("Milo Stopper");
    expect(html).toContain("6 saved");
    // Closes back to no fixture: veil, ✕, and the Escape contract.
    expect(html.split('{"fixture":null}').length).toBeGreaterThan(2);
    expect(html).toContain('data-close="open-fixture"');
    expect(html).toContain("From the programme&#39;s published box score.");
  });

  test("the drawer narrates the play-by-play, folded by period", () => {
    const narrated = structuredClone(matches);
    const detail = narrated.matches["sidearm:harding:14830"];
    if (!detail) throw new Error("fixture missing from test data");
    detail.plays = [
      { period: "1", clock: "00:00", team: 0, text: "FOR HU: , #30 Morris, Caden", type: "lineup" },
      {
        period: "1",
        clock: "05:43",
        team: 1,
        text: "Shot by RSU Decker, Braxton, out right.",
        type: "shot",
      },
      { period: "1", clock: "19:27", text: "Corner kick [19:27].", type: "corner" },
      { period: "1", clock: "44:00", team: 0, text: "Official's timeout." },
      { period: "1", clock: "45:00", team: 0, text: "End of period [45:00].", type: "period" },
      {
        period: "2",
        clock: "50:59",
        team: 1,
        text: "GOAL by RSU Decker, Braxton.",
        type: "goal",
        score: [0, 1],
      },
      {
        period: "2",
        clock: "62:17",
        team: 1,
        text: "Yellow card on RSU Velasquez, Omarion.",
        type: "yellow",
      },
      {
        period: "SO",
        team: 0,
        text: "Shootout attempt by HU Grudis, Nojus MADE [Stopper, Milo].",
        type: "shootout",
      },
    ];
    const html = compose("sidearm:harding:14830", "harding", narrated);
    expect(html).toContain(">Play by play<");
    // Periods fold shut, each labelled with its own count — the lineup listing
    // and the end-of-period marker are structure, not plays.
    expect(html).toContain("Period 1 · 3 plays</summary>");
    expect(html).toContain("Period 2 · 2 plays</summary>");
    expect(html).toContain("Shootout · 1 play</summary>");
    expect(html).not.toContain("FOR HU:");
    expect(html).not.toContain("End of period");
    // An untyped play still renders — the text is the record.
    expect(html).toContain("Official&#39;s timeout.");
    // The goal is emphasised and carries the running score, home side first.
    const goal = html.split("GOAL by RSU Decker, Braxton.")[0]?.split('<div class="ev').pop() ?? "";
    expect(goal).toContain("a gl");
    expect(html).toContain('GOAL by RSU Decker, Braxton.<span class="ps">0–1</span>');
    // A shootout row has no game clock to read aloud.
    expect(html).toContain("<b>–</b>");
    expect(html).toContain("Shootout attempt by HU Grudis, Nojus");
  });

  test("running scores read home-first even when the page served home second", () => {
    const flipped = structuredClone(matches);
    const detail = flipped.matches["sidearm:harding:14830"];
    if (!detail) throw new Error("fixture missing from test data");
    // Served order [HU, RSU] with RSU proven home: a 0–1 in served order is
    // 1–0 from the drawer's home-first reading.
    detail.home_index = 1;
    detail.plays = [
      {
        period: "1",
        clock: "10:00",
        team: 1,
        text: "GOAL by RSU Decker, Braxton.",
        type: "goal",
        score: [0, 1],
      },
    ];
    const html = compose("sidearm:harding:14830", "harding", flipped);
    expect(html).toContain('<span class="ps">1–0</span>');
  });

  test("a played match whose box score has no play-by-play says so", () => {
    const html = compose("sidearm:harding:14830");
    expect(html).toContain("No play-by-play collected for this match.");
    expect(html).not.toContain(">Play by play<");
  });

  test("a card the source did not colour stays neutral, not presumed yellow", () => {
    const neutral = structuredClone(matches);
    const detail = neutral.matches["sidearm:harding:14830"];
    if (!detail) throw new Error("fixture missing from test data");
    detail.cards = [{ time: "12:00", team: 0, type: "unknown", player: "Omarion Velasquez" }];
    const html = composeBoard({
      projectName: "p",
      fixtures: season2025,
      matches: neutral,
      team: "harding",
      fixture: "sidearm:harding:14830",
      today: "2026-08-09",
    });
    expect(html).toContain('class="cs u" title="Card"');
    const drawer = html.split('class="drawer"')[1] ?? "";
    expect(drawer).not.toContain('title="Yellow card"');
  });

  test("a played match without a box score opens honestly, naming the collector's reason", () => {
    const html = compose("sidearm:harding:14840");
    expect(html).toContain("No box score collected");
    expect(html).toContain("no box-score link on any collected schedule page");
    expect(html).not.toContain("Score by period");
  });

  test("an upcoming fixture's drawer is a listing, not a result", () => {
    const html = compose("sidearm:harding:14850");
    expect(html).toContain("Not played yet");
    expect(html).toContain("Kickoff 7:00 PM");
  });

  test("missing box scores count as named gaps on the board", () => {
    const html = compose();
    expect(html).toContain("1 match box score");
  });

  test("the conference matrix card offers the drawer for its selected match", () => {
    const html = composeBoard({
      projectName: "p",
      fixtures: season2025,
      matches,
      today: "2026-08-09",
    });
    expect(html).toContain('id="mx-open"');
    expect(html).toContain("Match details");
  });
});

describe("roster tenure", () => {
  // The archive the tenure lines read from. Names join within a programme —
  // SideArm roster ids change every season, so identity is the printed name.
  const rosterFile = (
    season: number,
    rosters: Record<string, { name: string; class_year?: string }[]>,
  ): RostersFile => ({
    schema: "touchline.rosters/1",
    season,
    gender: "men",
    collected_at: "2026-08-10T00:00:00Z",
    rosters: Object.fromEntries(
      Object.entries(rosters).map(([programme, players]) => [programme, { programme, players }]),
    ),
  });

  const season2026 = (players: { name: string; class_year?: string }[]) =>
    rosterFile(2026, { harding: players });

  const compose = (current: RostersFile, history: RostersFile[], player?: string) =>
    composeBoard({
      projectName: "p",
      fixtures: base,
      rosters: current,
      rosterHistory: history,
      team: "harding",
      player,
      today: "2026-08-09",
    });

  test("a returning player's drawer counts their seasons on this roster", () => {
    const current = season2026([{ name: "Aitor Scholl", class_year: "Junior" }]);
    const history = [
      rosterFile(2024, { harding: [{ name: "Aitor Scholl" }] }),
      rosterFile(2025, { harding: [{ name: "Aitor Scholl" }] }),
      current,
    ];
    const html = compose(current, history, "Aitor Scholl");
    expect(html).toContain("3rd season on the roster (2024–2026)");
    expect(html).not.toContain("First season on this roster");
  });

  test("a gap year reads as separate spans, not a continuous run", () => {
    // 2023 is collected and Weir is simply not on it — a real gap year,
    // not a hole in the archive.
    const current = season2026([{ name: "Davis Weir", class_year: "Senior" }]);
    const history = [
      rosterFile(2022, { harding: [{ name: "Davis Weir" }] }),
      rosterFile(2023, { harding: [{ name: "Somebody Else" }] }),
      rosterFile(2024, { harding: [{ name: "Davis Weir" }] }),
      rosterFile(2025, { harding: [{ name: "Davis Weir" }] }),
      current,
    ];
    const html = compose(current, history, "Davis Weir");
    expect(html).toContain("4th season on the roster (2022, 2024–2026)");
  });

  test("a hole in the archive suppresses absence claims but not positive sightings", () => {
    // 2024 and 2026 collected, 2025 unreadable or never collected: the player
    // may well have been on the 2025 roster, so neither "first season" nor a
    // season count can be claimed — but a sighting at another programme is a
    // fact no gap can retract.
    const current = season2026([
      { name: "Jack Huls", class_year: "Sophomore" },
      { name: "Gael Gonzalez", class_year: "Graduate Student" },
    ]);
    const history = [
      rosterFile(2024, {
        harding: [{ name: "Jack Huls" }],
        "rogers-state": [{ name: "Gael Gonzalez" }],
      }),
      current,
    ];
    const huls = compose(current, history, "Jack Huls");
    expect(huls).not.toContain("season on the roster");
    // Recorded sightings still speak, without a count the gap could falsify.
    expect(huls).toContain("On the roster in 2024, 2026");
    const html = compose(current, history, "Gael Gonzalez");
    expect(html).not.toContain("First season on this roster");
    expect(html).toContain("previously at Rogers State (2024)");
    expect(html).not.toContain(">NEW<");
    expect(html).not.toContain(">Tenure<");
  });

  test("an above-freshman debut is flagged as an arrival, stated as fact not conclusion", () => {
    const current = season2026([{ name: "Jack Huls", class_year: "Sophomore" }]);
    const history = [rosterFile(2025, { harding: [{ name: "Somebody Else" }] }), current];
    const html = compose(current, history, "Jack Huls");
    expect(html).toContain("First season on this roster · arrived as Sophomore");
    expect(html).not.toContain("transfer");
    // The grid gives them the quiet chip.
    expect(html).toContain('title="First season on this roster">NEW<');
  });

  test("a freshman debut is new but not an arrival", () => {
    const current = season2026([{ name: "Quin Brice", class_year: "Freshman" }]);
    const history = [rosterFile(2025, { harding: [{ name: "Somebody Else" }] }), current];
    const html = compose(current, history, "Quin Brice");
    expect(html).toContain("First season on this roster");
    expect(html).not.toContain("arrived as");
  });

  test("the tenure bar splits the squad into returning and new", () => {
    const current = season2026([
      { name: "Aitor Scholl", class_year: "Junior" },
      { name: "Davis Weir", class_year: "Senior" },
      { name: "Quin Brice", class_year: "Freshman" },
    ]);
    const history = [
      rosterFile(2025, { harding: [{ name: "Aitor Scholl" }, { name: "Davis Weir" }] }),
      current,
    ];
    const html = compose(current, history);
    expect(html).toContain(">Tenure<");
    expect(html).toContain('title="Returning — on an earlier roster: 2"');
    expect(html).toContain('title="First season on this roster: 1"');
  });

  test("without an earlier roster in the archive, nobody is claimed to be new", () => {
    // "First season" with no prior data would describe our records, not the
    // squad — so both the chip and the drawer claim stay silent.
    const current = season2026([{ name: "Jack Huls", class_year: "Sophomore" }]);
    const html = compose(current, [current], "Jack Huls");
    expect(html).not.toContain(">NEW<");
    expect(html).not.toContain("First season on this roster");
    expect(html).not.toContain(">Tenure<");
  });

  test("a prior stint at another conference programme earns a note", () => {
    const current = season2026([{ name: "Gael Gonzalez", class_year: "Graduate Student" }]);
    const history = [rosterFile(2025, { "rogers-state": [{ name: "Gael Gonzalez" }] }), current];
    const html = compose(current, history, "Gael Gonzalez");
    expect(html).toContain("previously at Rogers State (2025)");
  });

  test("an archive season never counts rosters from its future", () => {
    // Viewing 2025: the player is on the 2025 and 2026 rosters, but 2025 was
    // their first season — the 2026 file must not inflate the count.
    const f2025 = rosterFile(2025, { harding: [{ name: "Noah Legge", class_year: "Freshman" }] });
    const f2026 = rosterFile(2026, { harding: [{ name: "Noah Legge", class_year: "Sophomore" }] });
    const f2024 = rosterFile(2024, { harding: [{ name: "Somebody Else" }] });
    const html = composeBoard({
      projectName: "p",
      fixtures: { ...base, season: 2025 },
      rosters: f2025,
      rosterHistory: [f2024, f2025, f2026],
      team: "harding",
      player: "Noah Legge",
      today: "2026-08-09",
    });
    expect(html).toContain("First season on this roster");
    expect(html).not.toContain("2nd season");
  });
});

describe("the surface states what the sites publish", () => {
  // Measured 2026-08-21: preseason exhibitions arrive as finals without a
  // score, and past-dated games the sites still list as upcoming carry no
  // result at all. The board must say each of those precisely — not imply
  // an upcoming game, an uncollected result, or an invented score.
  const file: FixturesFile = {
    ...base,
    fixtures: [
      {
        id: "sidearm:rogers-state:7655",
        date: "2026-08-13",
        home: "rogers-state",
        away: "oklahoma-wesleyan",
        status: "final",
        match_type: "exhibition",
        conference_game: false,
        venue: "Soldier Field",
      },
      {
        id: "sidearm:rogers-state:7656",
        date: "2026-08-18",
        home: "rogers-state",
        away: "harding",
        status: "scheduled",
        conference_game: true,
      },
    ],
  };

  test("an exhibition final's drawer names both truths: exhibition, and no published score", () => {
    const html = composeBoard({
      projectName: "p",
      fixtures: file,
      fixture: "sidearm:rogers-state:7655",
      today: "2026-08-21",
    });
    const drawer = html.split('class="drawer"')[1] ?? "";
    expect(drawer).toContain("Exhibition");
    expect(drawer).toContain("Final without a published score");
  });

  test("the exhibition marking rides the matchday card byline", () => {
    const html = composeBoard({ projectName: "p", fixtures: file, today: "2026-08-21" });
    expect(html).toContain("Exhibition · Final");
  });

  test("a scoreless final with a collected box score still carries the disclosure", () => {
    // The header shows dashes (schedule score) above a period table with real
    // numbers (box score); the disclosure is what reconciles them.
    const withDetail: MatchesFile = {
      schema: "touchline.matches/1",
      season: 2026,
      gender: "men",
      collected_at: "2026-08-21T13:00:00Z",
      matches: {
        "sidearm:rogers-state:7655": {
          source_url: "https://example.test/boxscore/7655",
          home_index: 0,
          teams: [
            { name: "Rogers State", periods: [1, 0], score: 1 },
            { name: "Oklahoma Wesleyan", periods: [0, 0], score: 0 },
          ],
        },
      },
    };
    const html = composeBoard({
      projectName: "p",
      fixtures: file,
      matches: withDetail,
      fixture: "sidearm:rogers-state:7655",
      today: "2026-08-21",
    });
    const drawer = html.split('class="drawer"')[1] ?? "";
    expect(drawer).toContain("Final without a published score");
    expect(drawer).toContain("Score by period");
  });

  test("a cancelled exhibition keeps its marking on the card byline", () => {
    const cancelled: FixturesFile = {
      ...base,
      fixtures: [
        {
          id: "sidearm:rogers-state:7656",
          date: "2026-08-18",
          home: "rogers-state",
          away: "harding",
          status: "cancelled",
          match_type: "exhibition",
          conference_game: false,
        },
      ],
    };
    const html = composeBoard({ projectName: "p", fixtures: cancelled, today: "2026-08-21" });
    expect(html).toContain("Exhibition · Cancelled");
  });

  test("the team-lens ledger marks the exhibition in its status cell", () => {
    const html = composeBoard({
      projectName: "p",
      fixtures: file,
      team: "rogers-state",
      today: "2026-08-21",
    });
    expect(html).toContain("Exh · Final");
  });

  test("the matrix cell's accessible label names the exhibition, exactly", () => {
    // The aria-label is the only exhibition cue a screen reader gets from
    // the cell, so it is pinned verbatim, not by a floating substring.
    const html = composeBoard({ projectName: "p", fixtures: file, today: "2026-08-21" });
    expect(html).toContain(
      'aria-label="Rogers State hosts Oklahoma Wesleyan on THU AUG 13 (exhibition)"',
    );
  });

  test("a past-dated fixture counts as unpublished, never as played-and-missed", () => {
    // Two separate counters render the late set — the conference matrix
    // foot and the team rail foot — and both must make the honest claim.
    const conference = composeBoard({ projectName: "p", fixtures: file, today: "2026-08-21" });
    expect(conference).toContain("1 past date, no result published");
    expect(conference).not.toContain("played, not collected");
    const team = composeBoard({
      projectName: "p",
      fixtures: file,
      team: "rogers-state",
      today: "2026-08-21",
    });
    expect(team).toContain("1 past date, no result published");
    expect(team).not.toContain("played, not collected");
  });
});
