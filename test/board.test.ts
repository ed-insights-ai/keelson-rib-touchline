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

    test("the conference lens compares rosters and names every absence", () => {
      const html = compose();
      expect(html).toContain("Roster balance");
      // rogers-state publishes no positions → hatched, dashed counts.
      expect(html).toContain('class="cmix unp"');
      // newman has no roster at all → named, not omitted.
      expect(html).toContain("not collected");
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
    expect(prompt).toContain("the roster ONLY");
    expect(TOUCHLINE_V1_SEASON).toBe(2026);
  });

  test("a past season plans the roster and explains the missing schedule", () => {
    const plan = planForSeason(2019);
    expect(plan.empty).toBe(false);
    expect(plan.attempted).toEqual(["roster"]);
    const schedule = plan.layers.find((l) => l.layer === "schedule");
    expect(schedule?.attempt).toBe(false);
    // Measured against the live sites: /schedule/2019 answers 200 and its
    // payload carries the 2026 season. The reason must say that, not "2019 is
    // forbidden" — the difference is what makes historic rosters reachable.
    expect(schedule?.reason).toContain("serves its 2026 fixtures at every season address");
    expect(planSummary(plan)).toContain("Collecting roster for 2019");
  });

  test("the current season plans both layers", () => {
    const plan = planForSeason(2026);
    expect(plan.attempted).toEqual(["schedule", "roster"]);
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
