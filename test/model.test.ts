import { describe, expect, test } from "bun:test";
import { fixtureSchema, isPlayed } from "../src/model";

const base = {
  id: "sidearm:rogers-state:7655",
  date: "2026-08-13",
  home: "rogers-state",
  away: "oklahoma-wesleyan",
  status: "final",
};

// The collector writes what the sites publish; the strict contract here is
// what the board will actually load. A field the writer emits but the reader
// rejects silently takes down the whole season shard.
describe("the fixture contract", () => {
  test("an exhibition marking is part of the strict contract", () => {
    const parsed = fixtureSchema.parse({ ...base, match_type: "exhibition" });
    expect(parsed.match_type).toBe("exhibition");
  });

  test("an unknown field is still rejected", () => {
    expect(() => fixtureSchema.parse({ ...base, surprise: true })).toThrow();
  });

  test("a final without a published score is played", () => {
    // At least one modern theme publishes completion with no score entered;
    // the game happened, and the board must not render it as upcoming.
    expect(isPlayed(fixtureSchema.parse(base))).toBe(true);
  });

  test("a scheduled game is not played, even past its date", () => {
    expect(isPlayed(fixtureSchema.parse({ ...base, status: "scheduled" }))).toBe(false);
  });
});
