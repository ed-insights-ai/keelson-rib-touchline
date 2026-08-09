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
import { computeTable, type FixturesFile, fixturesFileSchema } from "../src/model.ts";
import { parseRequest } from "../src/setup.ts";

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
    expect(seasons).toEqual([{ season: 2026, gender: "men", conference: "GAC" }]);
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
    expect(html).toContain("days to kickoff");
    expect(html).not.toContain("Member record");
    expect(html).toContain("Pre-season is a valid state");
  });

  test("a played season shows the table and labels it derived", () => {
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
    expect(html).toContain("Member record");
    expect(html).toContain("derived");
    expect(html).toContain("Not the published conference table");
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

  test("the team lens reports a record and offers player actions", () => {
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
    expect(html).toContain("1–0–0");
    expect(html).toContain("Harding");
  });

  test("every empty state renders real markup and names the next step", () => {
    for (const html of [
      composeNoProject(["a", "b"]),
      composeNotAHome("p", true),
      composeNotAHome("p", false),
      composeNoSeasons("p"),
    ]) {
      expect(html).toContain('<div class="wrap">');
      expect(html.length).toBeGreaterThan(500);
    }
    expect(composeNoProject([])).toContain("keelson project add");
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
  test("a conference ask yields gender, season and subject", () => {
    const r = parseRequest("Get the current schedule and rosters for D2 GAC men's soccer 2025");
    expect(r.gender).toBe("men");
    expect(r.season).toBe(2025);
    expect(r.subject).toBe("gac");
  });

  test("a single-programme ask survives the filler", () => {
    const r = parseRequest("pull down the schedule and roster for Harding 2025");
    expect(r.subject).toBe("harding");
    expect(r.season).toBe(2025);
  });

  test("women is detected and not swallowed by the men pattern", () => {
    expect(parseRequest("the whole GAC women 2024").gender).toBe("women");
    expect(parseRequest("GAC women's soccer").gender).toBe("women");
  });

  test("an ask with no year leaves season undefined rather than guessing", () => {
    expect(parseRequest("the whole GAC men").season).toBeUndefined();
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
