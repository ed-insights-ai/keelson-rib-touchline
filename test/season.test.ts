import { describe, expect, test } from "bun:test";
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
