// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { monogram } from "./membership.ts";
import {
  computeTable,
  type Fixture,
  type FixturesFile,
  groupByDate,
  isPlayed,
  type RostersFile,
} from "./model.ts";

// ─────────────────────────────────────────────────────────────────────────────
// The board is an `html` snapshot: the composer returns a plain HTML string
// that the host renders in a sandboxed iframe. A strict CSP applies — no
// network of any kind — so everything is inline and self-contained.
//
// Palette: the frame sits INSIDE the keelson app, so it opens on keelson's own
// ground (tokens copied from @keelson/shared design-tokens) and adds a sport
// layer on top. A cream-paper sports programme would read as pasted-in.
// The host stamps data-theme on the root and pushes changes on
// `keelson:canvas:html:theme`.
// ─────────────────────────────────────────────────────────────────────────────

export function esc(s: unknown): string {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Identity hues. A programme is assigned one at first render by its position
 *  in the sorted slug list and keeps it — status colour is never borrowed for
 *  identity, so "green" always means a result and never a team. */
const IDENTITY = [
  "#4f7df0",
  "#c27718",
  "#0e9d8f",
  "#ba3d78",
  "#5f6e0a",
  "#9b8eff",
  "#3f8edb",
  "#d4663f",
  "#2fa876",
  "#d260a4",
  "#7c8cff",
  "#b5892a",
  "#4aa3a3",
  "#a0507f",
  "#6f7f3a",
  "#8f7ad6",
];

const FALLBACK_HUE = "#5e6789";

export function hueFor(slug: string, allSlugs: readonly string[]): string {
  const i = allSlugs.indexOf(slug);
  if (i < 0) {
    // Deterministic fallback for a slug outside the declared programme list
    // (a non-conference opponent) — stable across renders, never random.
    let h = 0;
    for (const ch of slug) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return IDENTITY[h % IDENTITY.length] ?? FALLBACK_HUE;
  }
  return IDENTITY[i % IDENTITY.length] ?? FALLBACK_HUE;
}

const STYLE = `
:root{
--bg:#0d1429;--bg-soft:#131a30;--card:#161e3b;--card-2:#1f2a4d;--border:#2a3258;--border-soft:#1f2746;
--fg:#d8def0;--fg-strong:#f0f3ff;--muted:#8993b2;--dim:#5e6789;--accent:#9b8eff;
--pitch:#3fbf82;--pitch-soft:#1c3b30;
--win:#6dd28d;--win-soft:#17331f;--loss:#f08793;--loss-soft:#35202a;--draw:#f5c352;--draw-soft:#33290f;
--shadow:0 1px 2px rgba(0,0,0,.35),0 6px 18px rgba(0,0,0,.22);
}
:root[data-theme="light"]{
--bg:#f3f0fa;--bg-soft:#eeeaf7;--card:#fff;--card-2:#eeeaf7;--border:#c8bfdc;--border-soft:#d9d1e8;
--fg:#161b31;--fg-strong:#0b0f1e;--muted:#5d5876;--dim:#7e7896;--accent:#6d4fe0;
--pitch:#15834f;--pitch-soft:#e2f0e8;
--win:#15834f;--win-soft:#e2f0e8;--loss:#d9385e;--loss-soft:#fbe6ea;--draw:#b57a00;--draw-soft:#f8eed6;
--shadow:0 1px 2px rgba(11,15,30,.06),0 6px 18px rgba(11,15,30,.06);
}
*{box-sizing:border-box}
body{margin:0;padding:14px;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.cond{font-family:"Avenir Next Condensed","Arial Narrow","Helvetica Neue",sans-serif;font-weight:700}
.wrap{display:grid;gap:12px}
.head{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 15px;
display:flex;flex-wrap:wrap;align-items:center;gap:11px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.head::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,var(--pitch),var(--accent))}
.head h1{margin:0;font-size:18px;letter-spacing:.04em;text-transform:uppercase;color:var(--fg-strong);
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif;font-weight:700}
.head .sub{color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums}
.head .sp{margin-left:auto}
.stamp{color:var(--dim);font-size:11.5px;font-variant-numeric:tabular-nums}
.lens{display:flex;border:1px solid var(--border);border-radius:7px;overflow:hidden;flex-wrap:wrap}
.lens button{appearance:none;border:0;background:transparent;color:var(--muted);font:600 12px/1 inherit;
letter-spacing:.06em;text-transform:uppercase;padding:7px 12px;cursor:pointer}
.lens button[aria-selected="true"]{background:var(--accent);color:#fff}
.lens button:focus-visible{outline:2px solid var(--pitch);outline-offset:-2px}
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));gap:9px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 12px;box-shadow:var(--shadow)}
.stat b{display:block;font-size:23px;line-height:1.1;color:var(--fg-strong);font-variant-numeric:tabular-nums;
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif;font-weight:700}
.stat span{font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim)}
.stat.warn b{color:var(--draw)}
.split{display:grid;grid-template-columns:1fr 280px;gap:12px;align-items:start}
@media(max-width:840px){.split{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow);overflow:hidden}
.panel>h2{margin:0;padding:10px 14px;border-bottom:1px solid var(--border-soft);font-size:11.5px;
letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:700;display:flex;align-items:center;gap:8px}
.panel>h2 .n{margin-left:auto;color:var(--dim);letter-spacing:0;font-size:11.5px;font-variant-numeric:tabular-nums}
.pb{padding:12px 14px 15px}
.day{margin:0 0 15px}.day:last-child{margin-bottom:0}
.day h3{margin:0 0 8px;font-size:10.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--pitch);
font-weight:700;display:flex;align-items:center;gap:8px}
.day h3::after{content:"";flex:1;height:1px;background:var(--border-soft)}
.fx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(228px,1fr));gap:9px}
.fx{background:var(--bg-soft);border:1px solid var(--border-soft);border-left:3px solid var(--dim);
border-radius:8px;padding:9px 11px;display:grid;gap:5px}
.fx .side{display:flex;align-items:center;gap:7px}
.fx .hue{width:3px;height:14px;border-radius:2px;flex:none}
.fx .nm{font-weight:600;font-size:13.5px;color:var(--fg-strong);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fx .nm.dim{color:var(--muted);font-weight:500}
.fx .g{margin-left:auto;font-size:17px;font-variant-numeric:tabular-nums;color:var(--fg-strong);
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif;font-weight:700}
.fx .g.dim{color:var(--muted)}
.fx .ft{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--dim);overflow:hidden}
.tag{font-size:9.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;padding:2px 6px;border-radius:3px;white-space:nowrap}
.fx.up{border-left-color:var(--pitch)}.fx.up .tag{background:var(--pitch-soft);color:var(--pitch)}
.fx.won{border-left-color:var(--win)}.fx.won .tag{background:var(--win-soft);color:var(--win)}
.fx.lost{border-left-color:var(--loss)}.fx.lost .tag{background:var(--loss-soft);color:var(--loss)}
.fx.tied{border-left-color:var(--draw)}.fx.tied .tag{background:var(--draw-soft);color:var(--draw)}
.fx.live{border-left-color:var(--loss)}.fx.live .tag{background:var(--loss-soft);color:var(--loss)}
.fx.off{border-left-color:var(--draw)}.fx.off .tag{background:var(--draw-soft);color:var(--draw)}
table{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
th{text-align:left;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);
font-weight:700;padding:5px;border-bottom:1px solid var(--border)}
td{padding:5px;border-bottom:1px solid var(--border-soft)}
td.r{text-align:right}.pts{font-weight:700;color:var(--fg-strong)}
.chip{display:inline-block;width:3px;height:11px;border-radius:2px;margin-right:7px;vertical-align:-1px}
.empty{text-align:center;padding:20px 12px}
.empty .big{font-size:42px;line-height:1;color:var(--pitch);font-variant-numeric:tabular-nums;
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif;font-weight:700}
.empty .lab{font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:var(--dim);margin-top:3px}
.empty p{color:var(--muted);font-size:12.5px;margin:10px 0 0}
.hero{background:var(--card);border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow);
padding:26px 22px;text-align:center;max-width:640px;margin:0 auto}
.hero h1{margin:0 0 6px;font-size:23px;color:var(--fg-strong);
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif;font-weight:700;text-transform:uppercase;letter-spacing:.03em}
.hero p{color:var(--muted);margin:0 0 14px;font-size:13.5px}
.hero .say{display:inline-block;background:var(--bg-soft);border:1px solid var(--border);border-radius:8px;
padding:11px 15px;color:var(--fg-strong);font-size:13.5px;text-align:left}
.hero .say b{color:var(--pitch);display:block;font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;margin-bottom:5px}
.hero code{background:var(--bg-soft);border:1px solid var(--border-soft);border-radius:4px;padding:1px 5px;font-size:12px}
.team-head{display:flex;align-items:center;gap:12px;padding:13px 14px 3px;flex-wrap:wrap}
.crest{width:38px;height:38px;border-radius:8px;display:grid;place-items:center;color:#fff;font-size:14px;
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif;font-weight:700;flex:none}
.team-head h2{margin:0;font-size:24px;text-transform:uppercase;color:var(--fg-strong);
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif;font-weight:700}
.team-head .rec{margin-left:auto;text-align:right}
.team-head .rec b{font-size:20px;color:var(--fg-strong);font-variant-numeric:tabular-nums;
font-family:"Avenir Next Condensed","Arial Narrow",sans-serif}
.team-head .rec span{display:block;font-size:9.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim)}
.run{display:flex;gap:4px;padding:10px 14px 4px;overflow-x:auto}
.tick{flex:none;width:30px;height:34px;border-radius:5px;display:grid;place-items:center;font-size:11px;
font-weight:700;border:1.5px solid var(--border);color:var(--dim)}
.tick small{font-size:8px;font-weight:600}
.tick.w{background:var(--win-soft);border-color:var(--win);color:var(--win)}
.tick.l{background:var(--loss-soft);border-color:var(--loss);color:var(--loss)}
.tick.d{background:var(--draw-soft);border-color:var(--draw);color:var(--draw)}
.tick.q{border-style:dashed}
.rost tr{cursor:pointer}
.rost tr:hover td{background:var(--card-2)}
.rost td.no{color:var(--pitch);font-weight:700;width:28px}
.hint{color:var(--dim);font-size:11px;padding:7px 14px 12px}
.note{color:var(--dim);font-size:11.5px;text-align:center}
.alarm{background:var(--loss-soft);border:1px solid var(--loss);border-radius:9px;padding:11px 14px;color:var(--fg-strong)}
.alarm b{color:var(--loss)}
.warnbox{background:var(--draw-soft);border:1px solid var(--draw);border-radius:9px;padding:10px 13px;font-size:12.5px}
.warnbox b{color:var(--draw)}
`;

const SCRIPT = `
(function(){
  function post(type,payload){
    try{parent.postMessage({channel:"keelson:canvas:html:action",type:type,payload:payload||{}},"*");}catch(e){}
  }
  document.addEventListener("click",function(e){
    var el=e.target&&e.target.closest?e.target.closest("[data-act]"):null;
    if(!el)return;
    var type=el.getAttribute("data-act");
    var raw=el.getAttribute("data-payload");
    var payload={};
    if(raw){try{payload=JSON.parse(raw);}catch(_){}}
    post(type,payload);
  });
  window.addEventListener("message",function(e){
    var d=e&&e.data;
    if(d&&d.channel==="keelson:canvas:html:theme"&&(d.theme==="dark"||d.theme==="light")){
      document.documentElement.setAttribute("data-theme",d.theme);
    }
  });
})();
`;

function page(body: string): string {
  return `<style>${STYLE}</style><div class="wrap">${body}</div><script>${SCRIPT}</script>`;
}

// ── Empty / guidance states ─────────────────────────────────────────────────

export function composeNoProject(projectNames: readonly string[]): string {
  const list = projectNames.length
    ? `<p class="note">Registered projects: ${projectNames.map(esc).join(" · ")}</p>`
    : `<p class="note">No projects registered yet — <code>keelson project add &lt;name&gt; &lt;dir&gt;</code>.</p>`;
  return page(`
    <div class="hero">
      <h1>Touchline</h1>
      <p>Pick a project above to choose where your soccer data lives. An empty folder is the right starting point — Touchline will set it up.</p>
      <div class="say"><b>Then say in chat</b>Get the current schedule and rosters for D2 GAC men's soccer.</div>
    </div>
    ${list}`);
}

export function composeNotAHome(projectName: string, empty: boolean): string {
  return page(`
    <div class="hero">
      <h1>${esc(projectName)}</h1>
      <p>${
        empty
          ? "This folder is empty — exactly what a first collection expects. Ask in chat and Touchline will set it up and collect a season into it."
          : "This folder is not a Touchline data home yet. Ask in chat to collect a season; Touchline will initialize it without disturbing what is already here."
      }</p>
      <div class="say"><b>Say in chat</b>Get the current schedule and rosters for D2 GAC men's soccer.</div>
    </div>`);
}

export function composeNoSeasons(projectName: string): string {
  return page(`
    <div class="hero">
      <h1>${esc(projectName)}</h1>
      <p>This is a Touchline data home, but no season has been collected into it yet.</p>
      <div class="say"><b>Say in chat</b>Get the current schedule and rosters for D2 GAC men's soccer.</div>
    </div>`);
}

export function composeUnreadable(detail: string): string {
  return page(`
    <div class="alarm"><b>THE BOARD DID NOT RENDER.</b> ${esc(detail)}
    <div style="margin-top:6px;color:var(--muted);font-size:12.5px">
    This is a read failure, not an empty season. The data files are unchanged — nothing has been lost.</div></div>`);
}

// ── The board ───────────────────────────────────────────────────────────────

export interface BoardInput {
  projectName: string;
  fixtures: FixturesFile;
  rosters?: RostersFile;
  /** Slug of the team lens, or undefined for the conference lens. */
  team?: string;
  /** Today, as YYYY-MM-DD. Passed in so the composer stays deterministic. */
  today: string;
}

function fixtureClass(f: Fixture, perspective?: string): string {
  if (f.status === "postponed" || f.status === "cancelled") return "off";
  if (f.status === "live") return "live";
  if (!isPlayed(f)) return "up";
  if (!perspective) return "won"; // neutral 'final' styling in the conference lens
  const hs = f.home_score as number;
  const as = f.away_score as number;
  if (hs === as) return "tied";
  const teamIsHome = f.home === perspective;
  const teamWon = teamIsHome ? hs > as : as > hs;
  return teamWon ? "won" : "lost";
}

function statusTag(f: Fixture): string {
  if (f.status === "postponed") return "Postponed";
  if (f.status === "cancelled") return "Cancelled";
  if (f.status === "live") return esc(f.clock ?? "Live");
  if (isPlayed(f)) {
    const hs = f.home_score as number;
    const as = f.away_score as number;
    return hs === as ? "Final · Draw" : "Final";
  }
  return f.time ? esc(fmtTime(f.time)) : "TBA";
}

function fmtTime(hhmm: string): string {
  const parts = hhmm.split(":").map(Number);
  const h = parts[0] ?? 0;
  const m = parts[1] ?? 0;
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
}

function fmtDate(iso: string): string {
  const parts = iso.split("-").map(Number);
  const y = parts[0] ?? 1970;
  const m = parts[1] ?? 1;
  const d = parts[2] ?? 1;
  const dt = new Date(Date.UTC(y, m - 1, d));
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const mons = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${days[dt.getUTCDay()]} · ${mons[dt.getUTCMonth()]} ${dt.getUTCDate()}`;
}

function daysBetween(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso}T00:00:00Z`);
  const b = Date.parse(`${toIso}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return 0;
  return Math.round((b - a) / 86_400_000);
}

function fixtureCard(
  f: Fixture,
  names: Map<string, string>,
  slugs: string[],
  perspective?: string,
): string {
  const cls = fixtureClass(f, perspective);
  const played = isPlayed(f) || f.status === "live";
  const hs = f.home_score;
  const as = f.away_score;
  const loserDim = (mine: number | null | undefined, theirs: number | null | undefined) =>
    typeof mine === "number" && typeof theirs === "number" && mine < theirs ? " dim" : "";
  const side = (
    slug: string,
    score: number | null | undefined,
    other: number | null | undefined,
  ) => `
      <div class="side">
        <i class="hue" style="background:${hueFor(slug, slugs)}"></i>
        <span class="nm${played ? loserDim(score, other) : ""}">${esc(names.get(slug) ?? slug)}</span>
        ${played ? `<span class="g${loserDim(score, other)}">${score ?? "–"}</span>` : ""}
      </div>`;
  const payload = esc(JSON.stringify({ fixture: f.id, team: perspective ?? null }));
  return `<div class="fx ${cls}" data-act="open-fixture" data-payload="${payload}">
      ${side(f.home, hs, as)}
      ${side(f.away, as, hs)}
      <div class="ft"><span class="tag">${statusTag(f)}</span>${f.venue ? esc(f.venue) : ""}</div>
    </div>`;
}

export function composeBoard(input: BoardInput): string {
  // `today` is consumed by the lens builders through `input`, not here.
  const { fixtures: file, rosters, team } = input;
  const slugs = file.programmes.map((p) => p.slug).sort();
  const names = new Map(file.programmes.map((p) => [p.slug, p.name]));
  for (const f of file.fixtures) {
    if (!names.has(f.home)) names.set(f.home, f.home);
    if (!names.has(f.away)) names.set(f.away, f.away);
  }

  const played = file.fixtures.filter(isPlayed).length;
  const rosterCount = rosters
    ? Object.values(rosters.rosters).reduce((n, r) => n + r.players.length, 0)
    : 0;
  const gaps = (file.missing?.length ?? 0) + (rosters?.missing?.length ?? 0);

  const lens = `
    <div class="lens" role="tablist">
      <button role="tab" aria-selected="${team ? "false" : "true"}" data-act="select-lens" data-payload='{"team":null}'>Conference</button>
      ${file.programmes
        .map(
          (p) =>
            `<button role="tab" aria-selected="${team === p.slug ? "true" : "false"}" data-act="select-lens" data-payload='${esc(
              JSON.stringify({ team: p.slug }),
            )}'>${esc(p.abbr ?? monogram(p.name))}</button>`,
        )
        .join("")}
    </div>`;

  const head = `
    <div class="head">
      <h1>${esc(file.conference)} · ${file.gender === "men" ? "Men's" : "Women's"} Soccer</h1>
      <span class="sub">${file.season}</span>
      ${lens}
      <span class="sp"></span>
      <span class="stamp">${played === 0 ? "pre-season · " : ""}collected ${esc(file.collected_at.slice(0, 16).replace("T", " "))}</span>
    </div>`;

  const warn = file.membership_extrapolated
    ? `<div class="warnbox"><b>Membership carried forward.</b> The membership record is authored through an earlier season, so this ${file.season} member list is the most recent published one carried forward — well-founded, but not yet cited to a ${file.season} source.</div>`
    : "";

  const gapsBox =
    gaps > 0
      ? `<div class="warnbox"><b>${gaps} collection gap${gaps === 1 ? "" : "s"}.</b> ${[
          ...(file.missing ?? []).map((m) => `${esc(names.get(m) ?? m)} (schedule)`),
          ...(rosters?.missing ?? []).map((m) => `${esc(names.get(m) ?? m)} (roster)`),
        ].join(" · ")} — named rather than dropped; a re-collect retries them.</div>`
      : "";

  const body = team
    ? teamLens(input, slugs, names)
    : conferenceLens(input, slugs, names, played, rosterCount, gaps);

  return page(`${head}${warn}${gapsBox}${body}`);
}

function conferenceLens(
  input: BoardInput,
  slugs: string[],
  names: Map<string, string>,
  played: number,
  rosterCount: number,
  gaps: number,
): string {
  const file = input.fixtures;
  const upcoming = file.fixtures.filter((f) => !isPlayed(f) && f.date >= input.today);
  const recent = file.fixtures.filter(isPlayed).sort((a, b) => b.date.localeCompare(a.date));

  // Pre-season shows the opening slate; in-season shows the current week
  // forward plus what just happened. Either way the reader sees "what's next".
  const showFixtures = upcoming.length ? upcoming.slice(0, 12) : recent.slice(0, 12);
  const groups = groupByDate(showFixtures);

  const firstDate = file.fixtures.map((f) => f.date).sort()[0];
  const toKickoff = firstDate ? daysBetween(input.today, firstDate) : 0;

  const table = computeTable(file);
  const anyPlayed = played > 0;
  // The archive publishes no conference flag, so the exporter derives one.
  // The board must say so wherever the derived number is shown.
  const derived = (file.conference_game_source ?? "").startsWith("derived");

  const rail = anyPlayed
    ? `<table>
        <thead><tr><th>Team</th><th class="r">P</th><th class="r">W</th><th class="r">D</th><th class="r">L</th><th class="r">GD</th><th class="r">Pts</th></tr></thead>
        <tbody>${table
          .map(
            (r) => `<tr>
              <td><i class="chip" style="background:${hueFor(r.slug, slugs)}"></i>${esc(r.name)}</td>
              <td class="r">${r.played}</td><td class="r">${r.won}</td><td class="r">${r.drawn}</td>
              <td class="r">${r.lost}</td><td class="r">${r.goalDiff > 0 ? "+" : ""}${r.goalDiff}</td>
              <td class="r pts">${r.points}</td></tr>`,
          )
          .join("")}</tbody></table>`
    : `<div class="empty">
        <div class="big">${toKickoff > 0 ? toKickoff : "—"}</div>
        <div class="lab">${toKickoff > 0 ? "days to kickoff" : "season dates"}</div>
        <p>The table appears after the first result. Fixture cards flip to scores as games are played.</p>
      </div>`;

  return `
    <div class="strip">
      <div class="stat"><b>${file.programmes.length}</b><span>Programmes</span></div>
      <div class="stat"><b>${file.fixtures.length}</b><span>Fixtures</span></div>
      <div class="stat"><b>${rosterCount}</b><span>Roster players</span></div>
      <div class="stat"><b>${played}</b><span>Played</span></div>
      ${gaps ? `<div class="stat warn"><b>${gaps}</b><span>Collection gaps</span></div>` : ""}
    </div>
    <div class="split">
      <div class="panel">
        <h2>${upcoming.length ? "Upcoming" : "Results"}<span class="n">${showFixtures.length} of ${file.fixtures.length}</span></h2>
        <div class="pb">
          ${
            groups.length
              ? groups
                  .map(
                    (g) => `<div class="day"><h3>${fmtDate(g.date)}</h3>
                      <div class="fx-grid">${g.fixtures.map((f) => fixtureCard(f, names, slugs)).join("")}</div></div>`,
                  )
                  .join("")
              : `<p class="note">No fixtures in this season file.</p>`
          }
        </div>
      </div>
      <aside class="panel">
        <h2>${anyPlayed ? "Member record" : "Kickoff"}${
          anyPlayed && derived ? '<span class="n">derived</span>' : ""
        }</h2>
        <div class="pb">${rail}${
          anyPlayed && derived
            ? `<p class="hint" style="padding:9px 0 0">Every result between two member programmes, including postseason meetings. Not the published conference table — the archive carries no conference flag, so this is derived from membership.</p>`
            : ""
        }</div>
      </aside>
    </div>
    ${played === 0 ? `<p class="note">Pre-season is a valid state — a full slate with zero results is what a correct first collection looks like.</p>` : ""}`;
}

function teamLens(input: BoardInput, slugs: string[], names: Map<string, string>): string {
  const file = input.fixtures;
  const team = input.team as string;
  const name = names.get(team) ?? team;
  const mine = file.fixtures
    .filter((f) => f.home === team || f.away === team)
    .sort((a, b) => a.date.localeCompare(b.date));

  let w = 0;
  let d = 0;
  let l = 0;
  const ticks = mine
    .map((f) => {
      if (!isPlayed(f)) {
        const opp = f.home === team ? f.away : f.home;
        const oppName = names.get(opp) ?? opp;
        return `<div class="tick q" title="${esc(oppName)}">${esc(monogram(oppName))}</div>`;
      }
      const hs = f.home_score as number;
      const as = f.away_score as number;
      const isHome = f.home === team;
      const mineScore = isHome ? hs : as;
      const theirs = isHome ? as : hs;
      let cls: string;
      let ch: string;
      if (mineScore > theirs) {
        cls = "w";
        ch = "W";
        w++;
      } else if (mineScore < theirs) {
        cls = "l";
        ch = "L";
        l++;
      } else {
        cls = "d";
        ch = "D";
        d++;
      }
      return `<div class="tick ${cls}">${ch}<small>${mineScore}–${theirs}</small></div>`;
    })
    .join("");

  const next = mine.filter((f) => !isPlayed(f) && f.date >= input.today).slice(0, 4);
  const roster = input.rosters?.rosters[team];

  const rosterBody = roster
    ? `<table class="rost">
        <thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Class</th><th>Hometown</th></tr></thead>
        <tbody>${roster.players
          .map(
            (p) => `<tr data-act="player-profile" data-payload='${esc(
              JSON.stringify({ team, player: p.name }),
            )}'>
              <td class="no">${esc(p.number ?? "")}</td><td>${esc(p.name)}</td>
              <td>${esc(p.position ?? "")}</td><td>${esc(p.class_year ?? "")}</td>
              <td>${esc(p.hometown ?? "")}</td></tr>`,
          )
          .join("")}</tbody></table>
        <p class="hint" style="padding:9px 0 0">Click a player to research a profile.</p>`
    : `<p class="note" style="padding:14px 0">No roster collected for ${esc(name)} yet.</p>`;

  return `
    <div class="split">
      <div class="panel">
        <div class="team-head">
          <div class="crest" style="background:${hueFor(team, slugs)}">${esc(monogram(name))}</div>
          <h2>${esc(name)}</h2>
          <div class="rec"><b>${w}–${l}–${d}</b><span>${w + l + d === 0 ? "Season not started" : "W–L–D"}</span></div>
        </div>
        <div class="run">${ticks || '<span class="note">No fixtures.</span>'}</div>
        <p class="hint">Results fill the run-in left to right; hollow ticks are still to play.</p>
        <div class="pb" style="border-top:1px solid var(--border-soft)">${rosterBody}</div>
      </div>
      <aside class="panel">
        <h2>Next up</h2>
        <div class="pb">
          ${
            next.length
              ? `<div class="fx-grid" style="grid-template-columns:1fr">${next
                  .map((f) => fixtureCard(f, names, slugs, team))
                  .join("")}</div>`
              : `<p class="note">No fixtures remaining.</p>`
          }
        </div>
      </aside>
    </div>`;
}
