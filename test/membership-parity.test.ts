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
import { packageDir } from "../src/datahome.ts";
import {
  _resetMembershipCache,
  _setMembershipCache,
  emptyResolutionReason,
  type MembershipFile,
  membershipPath,
  resolveConference,
} from "../src/membership.ts";

// ─────────────────────────────────────────────────────────────────────────────
// Two resolvers answer "who is in this conference this season": this rib's
// resolveConference, which turns a request into the programme list a collect
// is sent, and the pipeline's members_in_effect (pipeline/src/membership.py,
// conference_in_effect), which the collector checks that list against and
// files each programme's season under. Where they disagree a workflow
// requests a programme the collector files elsewhere, or parses with another
// conference's identity table. So they are compared, not trusted: every
// conference the file declares (the structural codes included), both
// genders, every season from 2016 to 2027 (one past the authored horizon,
// the carry-forward season), on the shipped record and on synthetic records
// shaped like each horizon case a review found.
// ─────────────────────────────────────────────────────────────────────────────

const pkg = packageDir();
const FIRST = 2016;
const LAST = 2027;

const PYTHON = `
import json, sys
from src.membership import load_membership, members_in_effect
doc = load_membership(sys.argv[1])
first, last = int(sys.argv[2]), int(sys.argv[3])
print(json.dumps({
    f"{conference}|{gender}|{season}": sorted(
        members_in_effect(conference, gender, season, document=doc)
    )
    for conference in doc["conferences"]
    for gender in ("men", "women")
    for season in range(first, last + 1)
}))
`;

async function pythonResolutions(path: string): Promise<Record<string, string[]>> {
  const proc = Bun.spawn(
    [
      "uv",
      "run",
      "--project",
      join(pkg, "pipeline"),
      "python",
      "-c",
      PYTHON,
      path,
      String(FIRST),
      String(LAST),
    ],
    { cwd: join(pkg, "pipeline"), stdout: "pipe", stderr: "pipe" },
  );
  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  if ((await proc.exited) !== 0) throw new Error(`python resolver failed: ${stderr}`);
  return JSON.parse(stdout) as Record<string, string[]>;
}

async function typescriptResolutions(file: MembershipFile): Promise<Record<string, string[]>> {
  _setMembershipCache(file);
  try {
    const out: Record<string, string[]> = {};
    for (const conference of file.conferences) {
      for (const gender of ["men", "women"]) {
        for (let season = FIRST; season <= LAST; season += 1) {
          out[`${conference}|${gender}|${season}`] = (
            await resolveConference(conference, gender, season)
          ).slugs;
        }
      }
    }
    return out;
  } finally {
    _resetMembershipCache();
  }
}

/** Every key whose member lists differ, with what each resolver said. */
function differences(ts: Record<string, string[]>, py: Record<string, string[]>): string[] {
  const keys = new Set([...Object.keys(ts), ...Object.keys(py)]);
  return [...keys]
    .sort()
    .filter((key) => JSON.stringify(ts[key]) !== JSON.stringify(py[key]))
    .map((key) => `${key}: ts=${JSON.stringify(ts[key])} py=${JSON.stringify(py[key])}`);
}

async function compare(file: MembershipFile): Promise<{ compared: number; differ: string[] }> {
  const dir = await mkdtemp(join(tmpdir(), "touchline-parity-"));
  const path = join(dir, "membership.json");
  await writeFile(path, JSON.stringify(file));
  const [ts, py] = [await typescriptResolutions(file), await pythonResolutions(path)];
  return { compared: Object.keys(ts).length, differ: differences(ts, py) };
}

const window = (conference: string, from: number, to: number) => ({
  conference,
  from_season: from,
  to_season: to,
  source: "test fixture",
});

const profiles = {
  LOWER: { level: "d2" as const, names: ["Lower Conference"] },
  UPPER: { level: "d1" as const, names: ["Upper Conference"] },
};

/** The reviewer's horizon shape: LOWER is authored through 2025; `mover`
 *  is LOWER's through 2025 and UPPER's from 2026, the season right after
 *  LOWER's horizon; `stayer` is LOWER's through 2025 with nothing after. */
const MOVES_AT_THE_HORIZON: MembershipFile = {
  conferences: ["LOWER", "UPPER", "independent", "non_member"],
  conference_profiles: profiles,
  memberships: {
    mover: { men: [window("LOWER", 2022, 2025), window("UPPER", 2026, 2027)] },
    stayer: { men: [window("LOWER", 2022, 2025)] },
    anchor: { men: [window("UPPER", 2022, 2027)] },
  },
};

describe("resolveConference and members_in_effect agree", () => {
  test("on the shipped membership record, every conference, gender and season 2016-2027", async () => {
    const file = JSON.parse(await readFile(membershipPath(), "utf8")) as MembershipFile;
    const { compared, differ } = await compare(file);
    expect(compared).toBe(file.conferences.length * 2 * (LAST - FIRST + 1));
    expect(differ).toEqual([]);
  }, 30_000);

  test("when a programme moves in the season right after its old conference's horizon", async () => {
    const { differ } = await compare(MOVES_AT_THE_HORIZON);
    expect(differ).toEqual([]);
    _setMembershipCache(MOVES_AT_THE_HORIZON);
    try {
      // the mover's own 2026 window wins over LOWER's carry-forward
      const lower = await resolveConference("LOWER", "men", 2026);
      expect(lower).toMatchObject({ slugs: ["stayer"], extrapolated: true });
      expect((await resolveConference("UPPER", "men", 2026)).slugs).toEqual(["anchor", "mover"]);
    } finally {
      _resetMembershipCache();
    }
  }, 30_000);
});

/** The former-member shape: LOWER is authored through 2025; `former` is
 *  LOWER's 2022-2025 and UPPER's for 2026 only, so in 2027 neither of its
 *  windows covers the season. It moved on after LOWER's horizon, so no
 *  carry-forward may restore it to LOWER. */
const MOVED_ON_AFTER_THE_HORIZON: MembershipFile = {
  ...MOVES_AT_THE_HORIZON,
  memberships: {
    former: { men: [window("LOWER", 2022, 2025), window("UPPER", 2026, 2026)] },
    stayer: { men: [window("LOWER", 2022, 2025)] },
    anchor: { men: [window("UPPER", 2022, 2027)] },
  },
};

describe("carry-forward never restores a former member", () => {
  test("a programme that moved on after the horizon is in neither conference once that window ends", async () => {
    const { differ } = await compare(MOVED_ON_AFTER_THE_HORIZON);
    expect(differ).toEqual([]);
    _setMembershipCache(MOVED_ON_AFTER_THE_HORIZON);
    try {
      expect((await resolveConference("LOWER", "men", 2025)).slugs).toEqual(["former", "stayer"]);
      expect((await resolveConference("LOWER", "men", 2026)).slugs).toEqual(["stayer"]);
      expect(await resolveConference("LOWER", "men", 2027)).toMatchObject({
        slugs: ["stayer"],
        extrapolated: true,
      });
      expect((await resolveConference("UPPER", "men", 2027)).slugs).toEqual(["anchor"]);
    } finally {
      _resetMembershipCache();
    }
  }, 30_000);
});

describe("an empty conference request is refused with its reason", () => {
  test("past the horizon with every member authored elsewhere, and a code the record does not know", async () => {
    const ended: MembershipFile = {
      ...MOVES_AT_THE_HORIZON,
      memberships: { mover: MOVES_AT_THE_HORIZON.memberships.mover ?? {} },
    };
    _setMembershipCache(ended);
    try {
      const lower = await resolveConference("LOWER", "men", 2026);
      expect(lower.slugs).toEqual([]);
      expect(emptyResolutionReason(lower)).toBe(
        "the membership record authors LOWER men through 2025, and every programme of its 2025 roster is authored elsewhere for 2026, so none is carried forward",
      );
      expect(emptyResolutionReason(await resolveConference("NOPE", "men", 2026))).toBe(
        "NOPE is not a conference the membership record declares",
      );
      expect(emptyResolutionReason(await resolveConference("LOWER", "women", 2026))).toBe(
        "the membership record authors no women window in LOWER",
      );
      expect(emptyResolutionReason(await resolveConference("LOWER", "men", 2020))).toBe(
        "no men window places a programme in LOWER for 2020",
      );
      expect(emptyResolutionReason(await resolveConference("LOWER", "men", 2024))).toBeUndefined();
    } finally {
      _resetMembershipCache();
    }
  });

  test("the resolver command refuses WAC men 2026 by its reason", async () => {
    const proc = Bun.spawn(
      ["bun", join(pkg, "bin", "resolve-membership.ts"), "conference", "WAC", "men", "2026"],
      { stdout: "pipe", stderr: "pipe" },
    );
    const stderr = await new Response(proc.stderr).text();
    expect(await proc.exited).toBe(1);
    expect(stderr).toContain(
      "no members resolve for WAC men 2026: the membership record authors WAC men through 2025, and every programme of its 2025 roster is authored elsewhere for 2026, so none is carried forward. Nothing to collect",
    );
  });
});
