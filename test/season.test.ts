import { afterEach, describe, expect, test } from "bun:test";
import {
  _resetMembershipCache,
  _setMembershipCache,
  collectFleetSize,
} from "../src/membership";
import { collectTimeoutMs } from "../src/season";

// The flat five-minute exec budget killed the first cold nine-programme
// archive collect mid-run, with the shard unwritten. Pin the replacement's
// contract: never stingier than the budget that already worked, growing
// with the fleet, and still finite.
describe("the collect subprocess budget", () => {
  test("a single programme keeps the proven five-minute budget", () => {
    expect(collectTimeoutMs(1)).toBe(300_000);
  });

  test("no fleet size is ever given less than the old flat budget", () => {
    for (let fleet = 0; fleet <= 40; fleet++) {
      expect(collectTimeoutMs(fleet)).toBeGreaterThanOrEqual(300_000);
    }
  });

  test("each additional programme buys more time", () => {
    expect(collectTimeoutMs(2)).toBeGreaterThan(collectTimeoutMs(1));
    // A nine-programme conference is the measured shape the flat budget
    // killed; it must clear the workflow-proven 900s comfortably enough
    // to absorb a cold cache.
    expect(collectTimeoutMs(9)).toBeGreaterThanOrEqual(780_000);
  });

  test("the budget is capped, so a hang is still caught", () => {
    expect(collectTimeoutMs(1000)).toBe(1_800_000);
  });

  test("a degenerate zero-programme call gets the single-programme budget", () => {
    // The handler refuses an empty fleet before it ever execs; this only
    // pins that the arithmetic cannot go below the floor if that changes.
    expect(collectTimeoutMs(0)).toBe(collectTimeoutMs(1));
  });
});

// collect-board only ever widens a season file's scope: a one-programme ask
// against a home already holding its conference-season refreshes the whole
// unit. The budget must therefore fit the conference, not the ask — sizing
// from the requested fleet alone re-creates the killed-mid-run failure.
describe("the budget fleet", () => {
  afterEach(() => _resetMembershipCache());

  const window = (conference: string) => [
    { conference, from_season: 2016, to_season: 2026, source: "test" },
  ];

  test("a programme ask is budgeted at its conference's full fleet", async () => {
    _setMembershipCache({
      conferences: ["GAC"],
      memberships: {
        harding: { men: window("GAC") },
        "rogers-state": { men: window("GAC") },
        newman: { men: window("GAC") },
      },
    });
    const fleet = await collectFleetSize(
      {
        kind: "programme",
        conference: "GAC",
        slugs: ["harding"],
        extrapolated: false,
        authoredThrough: 2026,
      },
      "men",
      2020,
    );
    expect(fleet).toBe(3);
  });

  test("a conference ask is already the whole fleet", async () => {
    const fleet = await collectFleetSize(
      {
        kind: "conference",
        conference: "GAC",
        slugs: ["harding", "newman"],
        extrapolated: false,
        authoredThrough: 2026,
      },
      "men",
      2020,
    );
    expect(fleet).toBe(2);
  });

  test("the requested fleet is a floor even when membership resolves smaller", async () => {
    // A slug can outlive its window in the record; the ask itself is still
    // going to be collected, so the budget never drops below it.
    _setMembershipCache({ conferences: ["GAC"], memberships: {} });
    const fleet = await collectFleetSize(
      {
        kind: "programme",
        conference: "GAC",
        slugs: ["harding"],
        extrapolated: false,
        authoredThrough: 2026,
      },
      "men",
      2020,
    );
    expect(fleet).toBe(1);
  });
});
