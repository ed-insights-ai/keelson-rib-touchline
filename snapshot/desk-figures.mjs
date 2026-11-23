// The desk's figures for snapshot/agree.py: one row per program, per game
// the desk counts beyond the program's team page, and per player line, read straight from a published index with the desk's own
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

// A program's record counts the games its own conference file lists with a
// result, as its team page does (touchline-ui recordOf over one conference's
// season), and leaves a forfeit's awarded score out of goals, as the page and
// the desk's counters do. Other games the desk counts for it (listed only on
// an opponent's schedule, or with no result yet on its own) come out as
// 'extra' rows: the desk folds the whole division, the page reads one file.
const SQL = `
with own as (
  select t.*,
    exists (select 1 from fixtures f where f.division = t.division and f.season = t.season
      and f.gender = t.gender and f.game_id = t.game_id and f.conf_key = t.team_conf
      and t.team in (f.home, f.away)) as listed,
    exists (select 1 from fixtures f where f.division = t.division and f.season = t.season
      and f.gender = t.gender and f.game_id = t.game_id and f.conf_key = t.team_conf
      and t.team in (f.home, f.away) and f.status = 'final'
      and f.home_score is not null and f.away_score is not null) as scored
  from team_games t where t.counted and t.result is not null)
select 'team' as kind, division, gender, season, team, null as name,
  count(*) filter (where result = 'W')::integer as won,
  count(*) filter (where result = 'T')::integer as drawn,
  count(*) filter (where result = 'L')::integer as lost,
  coalesce(sum(gf) filter (where forfeit is null), 0)::integer as goals_for,
  coalesce(sum(ga) filter (where forfeit is null), 0)::integer as goals_against,
  count(*)::integer as played,
  null::integer as gp, null::integer as gs, null::integer as goals, null::integer as assists,
  null::integer as shots, null::integer as k_gp, null::integer as k_saves, null::integer as k_ga,
  null as date, null as opponent, null as why
from own where scored
group by all
union all
select 'extra', division, gender, season, team, null,
  null, null, null, gf::integer, ga::integer, null,
  null, null, null, null, null, null, null, null,
  date::varchar, opponent,
  case when listed then 'its own schedule has no result for it'
    else 'not on its own schedule' end
from own where not scored
union all
select 'player', division, gender, season, team, name,
  null, null, null, null, null, null,
  gp::integer, gs::integer, goals::integer, assists::integer, shots::integer,
  k_gp::integer, k_saves::integer, k_ga::integer, null, null, null
from players`;

const instance = await DuckDBInstance.create(file, { access_mode: "READ_ONLY" });
const connection = await instance.connect();
const reader = await connection.runAndReadAll(SQL);
const rows = reader.getRowObjectsJS().map((r) =>
  Object.fromEntries(Object.entries(r).map(([k, v]) => [k, typeof v === "bigint" ? Number(v) : v])),
);
process.stdout.write(`${JSON.stringify({ schema: "touchline.desk-figures/2", rows })}\n`);
connection.closeSync();
instance.closeSync();
