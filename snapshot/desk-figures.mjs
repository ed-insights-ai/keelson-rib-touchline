// The desk's figures for snapshot/agree.py: one row per program and per
// player line, read straight from a published index with the desk's own
// DuckDB (its `query` command caps rows for the app's tools).
//
//   node snapshot/desk-figures.mjs <desk checkout> <touchline.duckdb> > desk.json
import { createRequire } from "node:module";
import { join } from "node:path";

const [desk, file] = process.argv.slice(2);
if (!desk || !file) {
  console.error("usage: node desk-figures.mjs <desk checkout> <touchline.duckdb>");
  process.exit(2);
}
const require = createRequire(join(desk, "packages/data/package.json"));
const { DuckDBInstance } = require("@duckdb/node-api");

const SQL = `
select 'team' as kind, division, gender, season, team, null as name,
  count(*) filter (where result = 'W')::integer as won,
  count(*) filter (where result = 'T')::integer as drawn,
  count(*) filter (where result = 'L')::integer as lost,
  coalesce(sum(gf), 0)::integer as goals_for, coalesce(sum(ga), 0)::integer as goals_against,
  count(*)::integer as played,
  null::integer as gp, null::integer as gs, null::integer as goals, null::integer as assists,
  null::integer as shots, null::integer as k_gp, null::integer as k_saves, null::integer as k_ga
from team_games where counted and result is not null
group by all
union all
select 'player', division, gender, season, team, name,
  null, null, null, null, null, null,
  gp::integer, gs::integer, goals::integer, assists::integer, shots::integer,
  k_gp::integer, k_saves::integer, k_ga::integer
from players`;

const instance = await DuckDBInstance.create(file, { access_mode: "READ_ONLY" });
const connection = await instance.connect();
const reader = await connection.runAndReadAll(SQL);
const rows = reader.getRowObjectsJS().map((r) =>
  Object.fromEntries(Object.entries(r).map(([k, v]) => [k, typeof v === "bigint" ? Number(v) : v])),
);
process.stdout.write(`${JSON.stringify({ schema: "touchline.desk-figures/1", rows })}\n`);
connection.closeSync();
instance.closeSync();
