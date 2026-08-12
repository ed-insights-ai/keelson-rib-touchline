// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

// Render the board straight to a file, using the same composer the rib
// registers, so a design change can be looked at without a server round trip.
//
//   bun dev/preview.ts <data-home> [season] [gender] [conference] [team] > out.html

import { composeBoard } from "../src/board.ts";
import { bootstrapDataHome, listSeasons, loadFixtures, loadRosters } from "../src/datahome.ts";

const [root, seasonArg, genderArg, conferenceArg, teamArg] = process.argv.slice(2);
if (!root) {
  console.error("usage: bun dev/preview.ts <data-home> [season] [gender] [conference] [team]");
  process.exit(2);
}

await bootstrapDataHome(root);

const seasons = await listSeasons(root);
if (!seasons.length) {
  console.error(`no season files under ${root}/data/fixtures`);
  process.exit(1);
}
const want =
  seasons.find(
    (s) =>
      (seasonArg === undefined || s.season === Number(seasonArg)) &&
      (genderArg === undefined || s.gender === genderArg) &&
      (conferenceArg === undefined || s.conference === conferenceArg),
  ) ?? seasons[0];
if (!want) {
  console.error("no season matched");
  process.exit(1);
}

const fx = await loadFixtures(root, want.season, want.gender, want.conference);
if (!fx.ok) {
  console.error(`fixtures unreadable: ${fx.reason} ${fx.path}`);
  process.exit(1);
}
const rs = await loadRosters(root, want.season, want.gender, want.conference);

process.stdout.write(
  composeBoard({
    projectName: root.split("/").pop() ?? root,
    fixtures: fx.value,
    rosters: rs.ok ? rs.value : undefined,
    team: teamArg,
    today: new Date().toISOString().slice(0, 10),
  }),
);
