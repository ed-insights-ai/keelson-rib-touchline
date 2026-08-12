// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { conferenceSlug } from "./datahome.ts";
import { monogram, titleFromSlug } from "./membership.ts";
import {
  type Fixture,
  type FixturesFile,
  isPlayed,
  type KeeperStats,
  type MatchDetail,
  type MatchesFile,
  type MatchPlay,
  type MatchTeam,
  type Player,
  type PlayerStats,
  type Roster,
  type RostersFile,
  type StatsFile,
  type TeamStats,
} from "./model.ts";

// ─────────────────────────────────────────────────────────────────────────────
// The board is an `html` snapshot: the composer returns a plain HTML string
// that the host renders in a sandboxed iframe. A strict CSP applies — no
// network of any kind — so everything is inline and self-contained.
//
// DESIGN
//
// A season's native artifact is a FIXTURE LIST — a dated, ruled column read top
// to bottom — not a dashboard of tiles. So the structure here is a single ruled
// sheet: masthead, season rail, one stat line, then the ledger. Cards, nested
// panels and stat tiles are deliberately absent; they made every state look
// identical and buried the one thing this rib uniquely knows, which is how much
// of the season exists yet.
//
// The boldness is spent in ONE place: the season rail. Everything around it is
// quiet — chalk rules, condensed caps for labels, tabular figures for anything
// countable. The palette stays on keelson's own ground because the frame sits
// inside the keelson app; a cream sports-programme palette would read as pasted
// in next to the host chrome. The identity is carried by structure and type.
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
--bg:#f4f4f8;--sheet:#fff;--sunk:#eeeef5;
--band:transparent;--raise:#eeeef5;--hover:#eeeef5;--zebra:transparent;
--ink:#151827;--ink-2:#454b63;--muted:#6b7189;--faint:#9aa0b5;
--rule:#e2e3ec;--rule-firm:#c9cbd9;
--accent:#6d4fe0;--accent-soft:#efeafd;
--played:#15834f;--played-soft:#e3f1e9;
--live:#c2410c;--live-soft:#fbe9df;
--late:#be123c;--late-soft:#fbe6ea;
--draw:#b57a00;
--gk:#7b61d7;--def:#3f70a9;--mid:#3b8a72;--fwd:#b8820f;
--gr:#232a45;--sr:#7a2148;--jr:#a03b62;--so:#cf8ba3;--fr:#e9bfcc;
--ret:#4c5566;--arr:#2b7f8e;
}
/* Dark is the light theme's structure translated surface-by-surface, not one
   navy applied everywhere: a four-step ladder (page < shell < band < raised)
   where light's white-vs-lavender gaps become deliberate tonal steps. */
:root[data-theme="dark"]{
--bg:#0b1224;--sheet:#101831;--sunk:#192542;
--band:#182340;--raise:#1f2d4e;--hover:#23345b;--zebra:#131b36;
--ink:#e9edf7;--ink-2:#aab5cd;--muted:#8b97b5;--faint:#6d7994;
--rule:#263554;--rule-firm:#3a4b72;
--accent:#9b8eff;--accent-soft:#252b52;
--played:#57cf90;--played-soft:#12301f;
--live:#f5924d;--live-soft:#2a2117;
--late:#f0879a;--late-soft:#331a22;
--draw:#f0c04f;
--gk:#a895ff;--def:#74a7e2;--mid:#61c39f;--fwd:#eac160;
--gr:#e8ecfb;--sr:#e77ba3;--jr:#c05a82;--so:#7e4260;--fr:#5c3247;
--ret:#9aa5b8;--arr:#6fc4d4;
}
*{box-sizing:border-box}
html,body{margin:0}
body{position:relative;background:var(--bg);color:var(--ink);padding:12px;
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
/* Condensed caps are the scoreboard voice: labels, team names, section heads. */
.cond{font-family:"Avenir Next Condensed","Roboto Condensed","Arial Narrow","Helvetica Neue",sans-serif;
font-weight:700;letter-spacing:.02em}
.num{font-variant-numeric:tabular-nums}

.sheet{background:var(--sheet);border:1px solid var(--rule-firm);border-radius:10px;overflow:hidden}

/* ── masthead ─────────────────────────────────────────────────────────── */
.mast{display:flex;align-items:baseline;flex-wrap:wrap;gap:6px 14px;padding:12px 18px 8px}
.mast h1{margin:0;font-size:25px;line-height:1;text-transform:uppercase;letter-spacing:.015em;
font-family:"Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;font-weight:700}
.mast .season{font-size:25px;line-height:1;color:var(--faint);font-variant-numeric:tabular-nums;
font-family:"Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;font-weight:700}
.mast .sp{margin-left:auto}
.mast .stamp{font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums;white-space:nowrap}
.mast .seasons{display:inline-flex;align-items:baseline;gap:5px}
.mast .yr{appearance:none;border:0;background:transparent;padding:0 3px;cursor:pointer;
font-size:21px;line-height:1;color:var(--faint);font-family:"Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;font-weight:700}
.mast .yr:hover{color:var(--ink)}
.mast .yr:focus-visible{outline:2px solid var(--accent);outline-offset:1px;border-radius:3px}
.mast .gen{align-self:center;font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--faint);border:1px solid var(--rule-firm);
border-radius:4px;padding:3px 6px 2px}

/* ── lens switch ──────────────────────────────────────────────────────── */
.lens{display:flex;gap:2px;padding:0 18px 10px;flex-wrap:wrap}
.lens button{appearance:none;border:1px solid var(--rule-firm);background:transparent;color:var(--muted);
font:700 10.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;letter-spacing:.09em;
text-transform:uppercase;padding:6px 10px;cursor:pointer;border-radius:4px}
.lens button:hover{color:var(--ink);border-color:var(--muted)}
.lens button[aria-selected="true"]{background:var(--ink);border-color:var(--ink);color:var(--sheet)}
.lens button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}

/* ── the season rail — the signature ──────────────────────────────────── */
.rail{border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
background:var(--sunk);padding:12px 18px;display:flex;align-items:flex-end;gap:20px;flex-wrap:wrap}
/* Weeks and month labels share one grid so a label sits exactly over the weeks
   it spans — the rail has to read as a calendar, not an abstract bar. */
.rail-strip{flex:0 0 auto}
.rail-weeks{display:grid;grid-template-columns:repeat(var(--n),16px);gap:3px;align-items:end;
padding-bottom:5px;border-bottom:1px solid var(--rule-firm)}
.wk{display:flex;flex-direction:column-reverse;gap:2px;min-height:9px}
.wk i{display:block;height:9px;border-radius:1.5px;border:1px solid var(--rule-firm);background:transparent}
.rail-months{display:grid;grid-template-columns:repeat(var(--n),16px);gap:3px;margin-top:5px}
.rail-months span{font:700 9px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--faint);white-space:nowrap}
.wk i.played{background:var(--played);border-color:var(--played)}
.wk i.w{background:var(--played);border-color:var(--played)}
.wk i.l{background:var(--late);border-color:var(--late)}
.wk i.d{background:var(--draw);border-color:var(--draw)}
.wk i.live{background:var(--live);border-color:var(--live)}
.wk i.late{background:var(--late-soft);border-color:var(--late)}
.wk i.off{background:repeating-linear-gradient(45deg,var(--rule),var(--rule) 2px,transparent 2px,transparent 4px)}
.wk.bye i{border-style:dotted;opacity:.5}
.wk.now i{border-color:var(--accent)}
.rail-foot{flex:1 1 200px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
font-size:11.5px;color:var(--muted);padding-bottom:1px}
.rail-foot b{color:var(--ink);font-weight:650}
.rail-foot .late-n{color:var(--late);font-weight:650}

/* ── one ruled stat line, not tiles ───────────────────────────────────── */
.tally{display:flex;flex-wrap:wrap;border-bottom:1px solid var(--rule)}
.tally div{flex:1 1 108px;padding:8px 18px;border-right:1px solid var(--rule)}
.tally div:last-child{border-right:0}
.tally b{display:block;font-size:20px;line-height:1.1;font-variant-numeric:tabular-nums;
font-family:"Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;font-weight:700}
.tally span{display:block;margin-top:1px;font:700 9.5px/1.3 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.13em;text-transform:uppercase;color:var(--faint)}
.tally .warn b{color:var(--live)}

/* ── notices ──────────────────────────────────────────────────────────── */
.note{margin:0;padding:10px 18px;font-size:12px;line-height:1.5;color:var(--ink-2);
border-bottom:1px solid var(--rule);background:var(--sunk)}
.note b{font-weight:650;color:var(--ink)}
.note.flag{border-left:3px solid var(--live);background:var(--live-soft)}

/* ── section head ─────────────────────────────────────────────────────── */
/* --band is transparent in light — white space does the separating there;
   dark has no white space, so the band carries the same structure tonally. */
.sec{display:flex;align-items:baseline;gap:10px;padding:10px 18px 7px;background:var(--band)}
.sec h2{margin:0;font:700 11px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.sec .count{margin-left:auto;font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums}

/* ── fixture ledger ───────────────────────────────────────────────────── */
.led{border-top:1px solid var(--rule)}
.row{display:grid;grid-template-columns:62px 22px 1fr auto;gap:0 12px;align-items:baseline;
padding:9px 18px;border-bottom:1px solid var(--rule);cursor:pointer}
.row:nth-child(even){background:var(--zebra)}
.row:hover{background:var(--hover)}
.row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.row .d{font:700 11px/1.35 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-variant-numeric:tabular-nums}
.row .d em{display:block;font-style:normal;color:var(--faint);font-size:9.5px;letter-spacing:.12em}
.row.both{grid-template-columns:62px 1fr auto}
.row .ha{font:700 9.5px/1.7 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.06em;color:var(--faint);border:1px solid var(--rule-firm);border-radius:3px;
text-align:center;height:17px}
.row .ha.h{color:var(--ink);border-color:var(--rule-firm)}
.row .opp{min-width:0}
.row .opp .n{display:block;font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .opp .v{display:block;font-size:11px;color:var(--faint);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .r{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.row .r .sc{font:700 16px/1.1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif}
.row .r .tm{font-size:12px;color:var(--muted)}
.row .r .st{display:block;font:700 9px/1.5 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.13em;text-transform:uppercase;color:var(--faint)}
.row.conf{box-shadow:inset 3px 0 0 var(--accent)}
.row.won .r .sc{color:var(--played)}
.row.lost .r .sc{color:var(--late)}
.row.tied .r .sc{color:var(--draw)}
.row.off{opacity:.55}
.row.off .r .st{color:var(--late)}
.chip{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:6px;vertical-align:baseline}

/* ── matchday matrix (conference lens) ────────────────────────────────── */
.key{display:flex;gap:12px;align-items:center;font-size:11px;color:var(--muted);flex-wrap:wrap}
.key span{display:inline-flex;align-items:center;gap:4px}
.mx-sel{display:flex;align-items:center;gap:12px;margin:4px 18px 12px;border:1px solid var(--rule);
border-radius:8px;background:var(--raise);padding:9px 13px;min-height:54px}
.mx-sel .db{flex:0 0 48px;text-align:center;border-right:1px solid var(--rule-firm);padding-right:12px}
.mx-sel .db .mo{font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.mx-sel .db .dy{font:700 22px/1.15 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
font-variant-numeric:tabular-nums}
.mx-sel .tt{font-size:13.5px;font-weight:600;line-height:1.3}
.mx-sel .nt{font-size:11.5px;color:var(--muted);margin-top:1px}
.mx-wrap{overflow-x:auto;border-top:1px solid var(--rule);
scrollbar-width:thin;scrollbar-color:var(--rule-firm) transparent}
.mx{border-collapse:separate;border-spacing:0;min-width:100%}
.mx th,.mx td{padding:0;border-bottom:1px solid var(--rule);text-align:center}
.mx thead th{background:var(--sunk)}
.mx .mo-h{font:700 9px/2.2 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--faint);border-left:1px solid var(--rule)}
.mx .dy-h{width:48px;min-width:48px;border-left:1px solid var(--rule);padding:4px 2px 6px;
font:700 10.5px/1.25 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.04em;color:var(--ink-2);font-variant-numeric:tabular-nums}
.mx .dy-h em{display:block;font-style:normal;font-size:8.5px;letter-spacing:.12em;color:var(--faint)}
.mx .tm-h{position:sticky;left:0;z-index:3;background:var(--sunk);min-width:148px;width:148px;
text-align:left;padding:6px 12px;border-right:1px solid var(--rule-firm);
font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.mx .tm{position:sticky;left:0;z-index:2;background:var(--sheet);text-align:left;
border-right:1px solid var(--rule-firm);padding:0}
.mx .tm button{appearance:none;border:0;background:transparent;color:var(--ink);cursor:pointer;
display:flex;align-items:center;gap:8px;width:100%;min-height:44px;padding:5px 12px;font:inherit;text-align:left}
.mx .tm .cd{flex:0 0 36px;display:inline-flex;align-items:center;justify-content:center;height:24px;
border:1px solid var(--rule-firm);border-radius:5px;background:var(--sunk);color:var(--ink-2);
font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;letter-spacing:.05em}
.mx .tm .nm{font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mx .tm .who{display:flex;flex-direction:column;gap:3px;min-width:0;flex:1}
.mx .tm .rec{display:flex;height:3px;border-radius:2px;overflow:hidden;max-width:120px}
.mx .tm .rec i{display:block}
.mx .tm .rec .w{background:var(--played)}
.mx .tm .rec .d{background:var(--draw)}
.mx .tm .rec .l{background:var(--late)}
.mx tr.foc .tm{box-shadow:inset 3px 0 0 var(--accent)}
.mx tr.foc .tm .cd{border-color:var(--accent);color:var(--accent)}
.mx td.c{width:48px;min-width:48px;height:46px;border-left:1px solid var(--rule);padding:4px 3px}
.m{appearance:none;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;
width:100%;height:100%;border:1px solid var(--rule-firm);border-radius:5px;background:transparent;
color:var(--ink);cursor:pointer;padding:0;
font:700 10px/1.1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;letter-spacing:.04em}
.m.h{background:var(--accent-soft);border-color:transparent}
.m.nc{border-style:dashed;color:var(--muted)}
.m .sc{font-size:9px;letter-spacing:.02em;font-variant-numeric:tabular-nums;color:var(--muted)}
.m.w .sc{color:var(--played)}.m.l .sc{color:var(--late)}.m.d .sc{color:var(--draw)}
.m.lt{border-color:var(--late);border-style:dotted}
.m.rel:not(.is-sel){box-shadow:inset 0 -3px 0 var(--accent)}
.m.is-sel{border-color:var(--accent);border-style:solid;box-shadow:0 0 0 1px var(--accent)}
.m.dim{opacity:.25}
.m:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.mx-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
padding:9px 18px 13px;font-size:11px;color:var(--muted)}
.mx-foot b{color:var(--ink);font-weight:650}
.mx-foot .late-n{color:var(--late);font-weight:650}

/* ── roster ───────────────────────────────────────────────────────────── */
/* Composition first: two bars say what the squad IS before the sheet lists
   who is in it. Position colours are role colours, never identity hues. */
.bars{display:grid;gap:8px;padding:12px 18px;background:var(--sunk);
border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.bar-row{display:grid;grid-template-columns:56px 1fr;gap:10px;align-items:center}
.bar-row .lbl{font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.11em;text-transform:uppercase;color:var(--faint)}
.bar{display:flex;height:17px;overflow:hidden;border-radius:3px}
.bar span{display:flex;align-items:center;justify-content:center;color:var(--bg);
font:700 9px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
min-width:0;overflow:hidden;white-space:nowrap}
.bar .gk{background:var(--gk)}.bar .d{background:var(--def)}
.bar .m{background:var(--mid)}.bar .f{background:var(--fwd)}
.bar .fr{background:var(--fr)}.bar .so{background:var(--so)}.bar .jr{background:var(--jr)}
.bar .sr{background:var(--sr)}.bar .gr{background:var(--gr)}
.bar .ret{background:var(--ret)}.bar .arr{background:var(--arr)}
/* The low-tenure end of the ramp sits near the theme ground, so its counts
   take ink rather than the bg text the saturated segments carry. */
.bar .so,.bar .fr{color:var(--ink)}
.bar .un{background:repeating-linear-gradient(45deg,var(--rule-firm),var(--rule-firm) 3px,transparent 3px,transparent 6px);color:var(--muted)}

/* Multi-column packing: a short group (four goalkeepers) shares its column
   with the next group instead of leaving a group-sized hole in a grid row. */
.rgrid{columns:300px;column-gap:28px;padding:10px 18px 16px}
.rgroup{min-width:0;break-inside:avoid;-webkit-column-break-inside:avoid}
/* A long group must be allowed to flow across columns — an unbreakable
   45-player block would otherwise render as one giant column. */
.rgroup.flow{break-inside:auto;-webkit-column-break-inside:auto}
.rgroup h3{break-after:avoid;break-inside:avoid}
.prow{break-inside:avoid}
.rgroup h3{display:flex;align-items:baseline;gap:7px;margin:10px 0 0;padding:0 2px 5px;
border-bottom:1px solid var(--rule-firm);font:700 10px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}
.rgroup h3 i{display:inline-block;width:14px;height:7px;border-radius:2px;align-self:center}
.rgroup h3 i.gk{background:var(--gk)}.rgroup h3 i.d{background:var(--def)}
.rgroup h3 i.m{background:var(--mid)}.rgroup h3 i.f{background:var(--fwd)}
.rgroup h3 i.un{background:repeating-linear-gradient(45deg,var(--rule-firm),var(--rule-firm) 3px,transparent 3px,transparent 6px)}
.rgroup h3 .n{margin-left:auto;color:var(--faint);font-size:10px;letter-spacing:.02em;font-variant-numeric:tabular-nums}
.prow{display:grid;grid-template-columns:26px minmax(0,1fr) 42px 38px;gap:0 10px;
align-items:baseline;padding:6px 2px 7px;border-bottom:1px solid var(--rule)}
.prow .no{font:700 12px/1.4 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
font-variant-numeric:tabular-nums;color:var(--faint);text-align:right}
.prow .nm{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prow .nm .new{margin-left:6px;vertical-align:1px;font:700 8px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
  letter-spacing:.12em;color:var(--faint);border:1px solid var(--rule-firm);border-radius:3px;padding:2px 3px 1px}
.prow .ht{font:700 11px/1.5 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
font-variant-numeric:tabular-nums;color:var(--ink-2);text-align:right;white-space:nowrap}
/* A low-key echo of the class ramp: a small tick in the class colour beside
   the muted abbrev — enough to tell a senior from a freshman at a scan
   without shouting on every row. */
.prow .yr{justify-self:end;display:inline-flex;align-items:center;gap:4px;
font:700 9.5px/1.7 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.05em;color:var(--muted);white-space:nowrap}
.prow .yr i{display:inline-block;width:7px;height:7px;border-radius:2px}
.prow .yr i.gr{background:var(--gr)}.prow .yr i.sr{background:var(--sr)}
.prow .yr i.jr{background:var(--jr)}.prow .yr i.so{background:var(--so)}
.prow .yr i.fr{background:var(--fr)}
/* Hometown lives ON the row — a second line under the name, city plain and an
   international region set apart, so the squad's reach is readable at a scan. */
.prow .home{grid-column:2 / -1;font-size:10.5px;color:var(--muted);
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prow .home b{font-weight:650;color:var(--ink-2);letter-spacing:.03em}
.prow .home .fl{font-style:normal;color:var(--accent);font-size:10px;margin-right:3px}

/* ── roster season-stat strip ─────────────────────────────────────────── */
/* A third line on the row: minutes as a bar against the squad's most-used
   player, then the two or three numbers that tell this player's season.
   Green and red keep their board-wide meanings — made and conceded. */
button.prow{appearance:none;border:0;border-bottom:1px solid var(--rule);background:transparent;
width:100%;font:inherit;color:inherit;text-align:left;cursor:pointer}
button.prow:hover .nm{text-decoration:underline}
button.prow:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.prow .st{grid-column:2 / -1;display:flex;flex-wrap:wrap;align-items:center;gap:3px 9px;margin-top:3px;min-width:0}
.prow .st .stat,.prow .st .mn{flex:0 0 auto}
.prow .st .mb{flex:0 0 58px;height:4px;border-radius:2px;background:var(--rule-firm);overflow:hidden}
.prow .st .mb span{display:block;height:100%;background:var(--accent);border-radius:2px}
.prow .st .mn{font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
color:var(--faint);font-variant-numeric:tabular-nums;white-space:nowrap}
.prow .st .stat{font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.06em;color:var(--muted);white-space:nowrap}
.prow .st .stat b{font-size:10.5px;font-variant-numeric:tabular-nums;color:var(--ink);margin-right:2px}
.prow .st .stat.g b,.prow .st .stat.sv b{color:var(--played)}
.prow .st .stat.ga b{color:var(--late)}

/* ── player drawer ────────────────────────────────────────────────────── */
/* The board iframe is auto-height — the host page scrolls, the frame never
   does — so a fixed drawer would pin to the document top, out of view for a
   row clicked far down the sheet. Both drawer and veil are absolute instead,
   and the frame script aligns the drawer with the element that opened it. */
.dr-veil{position:absolute;inset:0;z-index:40;appearance:none;border:0;cursor:pointer;
background:rgba(10,14,20,.45)}
.drawer{position:absolute;top:0;right:6px;z-index:41;width:min(400px,94vw);
background:var(--bg);border:1px solid var(--rule-firm);border-radius:9px;
box-shadow:0 18px 54px rgba(0,0,0,.35);padding-bottom:10px}
.dr-head{display:flex;gap:12px;align-items:flex-start;padding:18px 18px 13px;
border-bottom:1px solid var(--rule-firm)}
.dr-no{font:700 30px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
color:var(--faint);font-variant-numeric:tabular-nums}
.dr-head h2{margin:0;font:700 19px/1.15 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.02em}
.dr-head p{margin:3px 0 0;font-size:11.5px;color:var(--muted)}
.dr-x{appearance:none;margin-left:auto;flex:0 0 auto;width:26px;height:26px;
border:1px solid var(--rule-firm);border-radius:5px;background:transparent;
color:var(--muted);cursor:pointer;font-size:11px;line-height:1}
.dr-x:hover{color:var(--ink);border-color:var(--ink)}
.dr-x:focus-visible,.dr-veil:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.dr-bio{padding:10px 18px;font-size:12px;color:var(--ink-2);border-bottom:1px solid var(--rule)}
.dr-tenure{padding:8px 18px;font-size:11.5px;color:var(--muted);border-bottom:1px solid var(--rule)}
.dr-bio b{font-weight:650}
.dr-bio .fl{font-style:normal;color:var(--accent);font-size:10px;margin-right:3px}
.dr-sec{padding:14px 18px 0;font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.dr-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--rule);
border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);margin-top:8px}
.dr-grid div{background:var(--bg);padding:9px 12px 10px;min-width:0}
.dr-grid b{display:block;font:700 19px/1.1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
font-variant-numeric:tabular-nums}
.dr-grid span{font-size:9.5px;color:var(--muted);letter-spacing:.05em;text-transform:uppercase;white-space:nowrap}
.dr-bar-row{padding:12px 18px 0}
.dr-lbl{display:block;font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.dr-min-n{display:block;margin-top:4px;font-size:11.5px;color:var(--ink-2);font-variant-numeric:tabular-nums}
.dr-min{height:6px;border-radius:3px;background:var(--rule-firm);overflow:hidden;margin-top:5px}
.dr-min span{display:block;height:100%;background:var(--accent);border-radius:3px}
.dr-split{display:flex;height:18px;border-radius:3px;overflow:hidden;margin-top:6px}
.dr-split span{display:flex;align-items:center;justify-content:center;color:var(--bg);
font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
min-width:0;overflow:hidden;white-space:nowrap}
.dr-split .sv{background:var(--played)}
.dr-split .ga{background:var(--late)}
.dr-note{padding:10px 18px 0;margin:0;font-size:11.5px;color:var(--muted)}
.dr-note.dim{color:var(--faint);font-size:10.5px}
.dr-foot{padding:14px 18px 6px;margin:0;font-size:10px;color:var(--faint)}

/* ── match detail: row strip and drawer ───────────────────────────────── */
/* The strip sits under the opponent name, same register as the venue line. */
.row .msx{display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline;margin-top:2px}
.row .msx .ms{flex:0 0 auto;font:600 10px/1.4 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.06em;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.row .msx .gls{flex:0 0 auto;font-size:10.5px;color:var(--faint);font-variant-numeric:tabular-nums}
.cs{display:inline-block;width:7px;height:9px;border-radius:1.5px;vertical-align:-1px;margin-right:3px}
.cs.y{background:var(--draw)}
.cs.r{background:var(--late)}
.cs.u{background:var(--faint)}
.mhead .mteams{flex:1;min-width:0}
.mhead .mrow{display:flex;align-items:baseline;gap:10px;padding:1px 0}
.mhead .mrow span{flex:1;min-width:0;font:700 17px/1.3 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.02em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}
.mhead .mrow b{font:700 21px/1.2 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
font-variant-numeric:tabular-nums;color:var(--muted)}
.mhead .mrow.win span,.mhead .mrow.win b{color:var(--ink)}
.mhead .mrow:only-child span,.mhead .mrow:only-child b{color:var(--ink)}
.pline{border-collapse:collapse;margin:8px 18px 0;font-variant-numeric:tabular-nums}
.pline th,.pline td{padding:3px 10px;text-align:center;font-size:12px;border-bottom:1px solid var(--rule)}
.pline thead th{font:700 9px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;color:var(--faint)}
.pline tbody th{text-align:left;padding-left:0;font:700 10px/1.6 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.06em;color:var(--ink-2)}
.pline td b{font-weight:700}
/* Timeline rows: home reads from the left edge, away from the right. */
.evs{padding:6px 18px 0}
.ev{display:flex;gap:8px;align-items:baseline;padding:2.5px 0;font-size:12px}
.ev b{flex:0 0 30px;font:700 11px/1.5 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
color:var(--faint);font-variant-numeric:tabular-nums}
.ev .who{min-width:0}
.ev .who em{font-style:normal;display:block;font-size:10.5px;color:var(--faint)}
.ev.a{flex-direction:row-reverse;text-align:right}
/* Play-by-play periods fold shut so a 150-event narration stays scannable. */
.pbp{margin:6px 18px 0}
.pbp summary{cursor:pointer;padding:3px 0;font:700 10px/1.6 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.pbp summary:hover{color:var(--ink)}
.pbp summary:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.pbp .evs{padding:2px 0 6px}
.pbp .ev{font-size:11.5px}
.pbp .ev.gl .who{font-weight:700}
/* The chip is inline inside .who, so it sits after the text on both sides —
   row-reverse only reorders the flex items, not the narration's inline flow. */
.pbp .ev .ps{margin-left:6px;font-size:10.5px;color:var(--faint);font-variant-numeric:tabular-nums}
/* Team-statistic duels: bars grow from the centre toward each side. */
.duel{display:grid;grid-template-columns:26px 1fr 64px 1fr 26px;gap:8px;align-items:center;
padding:3px 18px 0;font-variant-numeric:tabular-nums}
.duel b{font:700 12.5px/1.5 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif}
.duel b:first-child{text-align:right}
.duel .dn{text-align:center;font:700 9px/1.6 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--faint)}
.duel .db{height:6px;border-radius:3px;background:var(--sunk);overflow:hidden;display:flex}
.duel .db.l{justify-content:flex-end}
.duel .db span{display:block;height:100%;background:var(--accent);border-radius:3px}
.duel.head{padding-top:12px}
.duel.head b{color:var(--faint);font-size:10px;letter-spacing:.08em}
.mx-open{appearance:none;margin-left:auto;align-self:center;flex:0 0 auto;border:1px solid var(--rule-firm);
border-radius:5px;background:transparent;color:var(--ink-2);cursor:pointer;
font:700 10px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.08em;text-transform:uppercase;padding:7px 10px}
.mx-open:hover{color:var(--ink);border-color:var(--ink)}
.mx-open:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

/* ── roster balance (conference lens) ─────────────────────────────────── */
.rbal{width:100%;border-collapse:collapse;font-size:12px}
.rbal th{background:var(--sunk);border-top:1px solid var(--rule);border-bottom:1px solid var(--rule-firm);
padding:7px 9px;text-align:right;white-space:nowrap;
font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
.rbal td{padding:7px 9px;border-bottom:1px solid var(--rule);text-align:right;font-variant-numeric:tabular-nums}
.rbal th:first-child,.rbal td:first-child{text-align:left;padding-left:18px}
.rbal th:last-child,.rbal td:last-child{padding-right:18px}
.rbal td b{font-weight:650}
.rbal .dim{color:var(--faint)}
.rbal .open{appearance:none;border:0;background:transparent;color:var(--ink);cursor:pointer;
display:inline-flex;align-items:center;gap:8px;font:inherit;padding:0;text-align:left}
.rbal .open:hover .tn2{text-decoration:underline}
.rbal .open:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.rbal .cd2{display:inline-flex;align-items:center;justify-content:center;width:38px;height:23px;
border:1px solid var(--rule-firm);border-radius:5px;background:var(--sunk);color:var(--ink-2);
font:700 9px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;letter-spacing:.05em}
.rbal .tn2{font-weight:600;white-space:nowrap}
/* Both composition bars — position and class — share one treatment: tall
   enough to carry their counts inline, read left to right. */
.rbal .cmix{display:flex;height:14px;min-width:128px;border-radius:2px;overflow:hidden;margin-left:auto}
.rbal .cmix span{display:flex;align-items:center;justify-content:center;color:var(--bg);
font:700 8.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
min-width:0;overflow:hidden;white-space:nowrap}
.rbal .cmix .gk{background:var(--gk)}.rbal .cmix .d{background:var(--def)}
.rbal .cmix .m{background:var(--mid)}.rbal .cmix .f{background:var(--fwd)}
.rbal .cmix .fr{background:var(--fr)}.rbal .cmix .so{background:var(--so)}
.rbal .cmix .jr{background:var(--jr)}.rbal .cmix .sr{background:var(--sr)}
.rbal .cmix .gr{background:var(--gr)}
.rbal .cmix .so,.rbal .cmix .fr{color:var(--ink)}
.rbal .cmix .un,.rbal .cmix.unp{background:repeating-linear-gradient(45deg,var(--rule-firm),var(--rule-firm) 3px,transparent 3px,transparent 6px);color:var(--muted)}
.rk{display:inline-flex;justify-content:flex-end;gap:8px;font-size:inherit;color:inherit}
.rk i{display:inline-block;width:13px;height:7px;border-radius:2px}
.rk i.gk{background:var(--gk)}.rk i.d{background:var(--def)}
.rk i.m{background:var(--mid)}.rk i.f{background:var(--fwd)}
.rk i.fr{background:var(--fr)}.rk i.so{background:var(--so)}
.rk i.jr{background:var(--jr)}.rk i.sr{background:var(--sr)}
.rk i.gr{background:var(--gr)}
.rbal-foot{display:flex;justify-content:flex-end;gap:8px 18px;flex-wrap:wrap;
padding:7px 18px 11px;font-size:11px;color:var(--muted)}

/* ── empty / alarm states ─────────────────────────────────────────────── */
.hero{padding:34px 22px 30px;text-align:center}
.hero h1{margin:0 0 8px;font-size:26px;text-transform:uppercase;letter-spacing:.02em;
font-family:"Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;font-weight:700}
.hero p{margin:0 auto;max-width:52ch;color:var(--muted);font-size:13.5px}
.say{margin:18px auto 0;max-width:52ch;border:1px dashed var(--rule-firm);border-radius:6px;
padding:11px 14px;text-align:left;font-size:13px;color:var(--ink-2)}
.say b{display:block;font:700 9.5px/1 "Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin-bottom:5px}
.alarm{border:1px solid var(--late);background:var(--late-soft);border-radius:8px;padding:13px 15px;font-size:13px}
.alarm b{color:var(--late)}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
`;

const SCRIPT = `
(function(){
  function post(type,payload){
    try{parent.postMessage({channel:"keelson:canvas:html:action",type:type,payload:payload},"*")}catch(e){}
  }
  document.addEventListener("click",function(ev){
    var el=ev.target.closest("[data-act]");
    if(!el)return;
    var p={};
    try{p=JSON.parse(el.getAttribute("data-payload")||"{}")}catch(e){}
    post(el.getAttribute("data-act"),p);
  });
  window.addEventListener("message",function(ev){
    var d=ev&&ev.data;
    if(d&&d.channel==="keelson:canvas:html:theme"&&d.theme){
      document.documentElement.setAttribute("data-theme",d.theme);
    }
  });
  // Place an open drawer inside the VISIBLE slice of the board. The frame is
  // auto-height and never scrolls itself, so document coordinates ARE host-page
  // coordinates — but the frame cannot read the host scroll directly. An
  // IntersectionObserver on the body can: even from a sandboxed frame it
  // reports which rectangle of the document the host viewport actually shows.
  // The drawer starts beside the element that opened it, then is clamped and
  // sized to that visible rectangle so it never opens below the fold.
  var dr=document.querySelector(".drawer");
  if(dr){
    var want=dr.getAttribute("data-anchor")||"";
    var anchor=null;
    if(want){
      var acts=document.querySelectorAll("[data-payload]");
      for(var i=0;i<acts.length;i++){
        if(acts[i].getAttribute("data-payload")===want){anchor=acts[i];break;}
      }
    }
    var anchorY=function(){return anchor?anchor.getBoundingClientRect().top:0};
    var docMax=document.body.scrollHeight-dr.offsetHeight-16;
    dr.style.top=Math.max(8,Math.min(anchorY()-12,docMax))+"px";
    // The drawer keeps its full content height — no inner scrollbox. It is
    // pulled up just enough to fit inside the visible slice when it can; when
    // it is taller than the window it starts at the visible top and the host
    // page scrolls through the rest like any other content.
    var place=function(visTop,visBottom){
      if(!(visBottom-visTop>120))return;
      var h=dr.offsetHeight;
      var y=anchor?anchorY()-12:visTop+12;
      y=Math.min(y,visBottom-h-12,document.body.scrollHeight-h-8);
      y=Math.max(y,visTop+12,8);
      dr.style.top=y+"px";
    };
    // A fresh observe() always fires once with the CURRENT rectangle, so a
    // one-shot observer is an async read of the visible slice. One reading is
    // not enough: this script runs mid document-swap, while the host is still
    // re-measuring the iframe for auto-height and restoring its scroll, so the
    // first rectangle often describes a transient layout. Re-read a few times
    // while the swap settles, and again whenever the host resizes the frame
    // (an iframe height change fires resize inside the frame). Once settled,
    // host scrolling fires nothing, so the drawer stays put while reading.
    var measure=function(){
      try{
        var io=new IntersectionObserver(function(entries){
          io.disconnect();
          var e=entries[entries.length-1];
          if(e&&e.intersectionRect&&e.intersectionRect.height>0){
            place(e.intersectionRect.top,e.intersectionRect.bottom);
          }
        });
        io.observe(document.body);
        setTimeout(function(){io.disconnect()},3000);
      }catch(e){}
    };
    measure();
    setTimeout(measure,250);
    setTimeout(measure,700);
    setTimeout(measure,1400);
    var rz;
    window.addEventListener("resize",function(){
      clearTimeout(rz);
      rz=setTimeout(measure,150);
    });
  }

  document.addEventListener("keydown",function(ev){
    if(ev.key==="Escape"){
      var dr=document.querySelector(".drawer");
      if(dr){
        var p={player:null};
        try{p=JSON.parse(dr.getAttribute("data-close-payload")||'{"player":null}')}catch(e){}
        post(dr.getAttribute("data-close")||"select-player",p);
      }
      return;
    }
    // Ledger rows are focusable divs; Enter and Space must act like the click.
    if((ev.key==="Enter"||ev.key===" ")&&ev.target&&ev.target.getAttribute&&
       ev.target.getAttribute("data-act")&&ev.target.tagName!=="BUTTON"){
      ev.preventDefault();
      var q={};
      try{q=JSON.parse(ev.target.getAttribute("data-payload")||"{}")}catch(e){}
      post(ev.target.getAttribute("data-act"),q);
    }
  });

  // The matchday matrix is interactive without the host: following a team and
  // inspecting a match are reading acts, so they stay inside the frame.
  var mx=document.querySelector(".mx");
  if(mx){
    var sum=document.getElementById("mx-sum");
    var card={mo:document.getElementById("mx-mo"),dy:document.getElementById("mx-dy"),
              tt:document.getElementById("mx-tt"),nt:document.getElementById("mx-nt")};
    var foc=null;
    mx.addEventListener("click",function(ev){
      var b=ev.target.closest("button");
      if(!b)return;
      if(b.hasAttribute("data-g")){
        var g=b.getAttribute("data-g");
        var ms=mx.querySelectorAll("[data-g]");
        for(var i=0;i<ms.length;i++){
          var on=ms[i].getAttribute("data-g")===g;
          ms[i].classList.toggle("is-sel",on);
          ms[i].setAttribute("aria-pressed",on?"true":"false");
        }
        if(card.tt){
          card.mo.textContent=b.getAttribute("data-mo")||"";
          card.dy.textContent=b.getAttribute("data-dy")||"";
          card.tt.textContent=b.getAttribute("data-tt")||"";
          card.nt.textContent=b.getAttribute("data-nt")||"";
        }
        var op=document.getElementById("mx-open");
        if(op){op.hidden=false;op.setAttribute("data-payload",JSON.stringify({fixture:g}));}
      }else if(b.hasAttribute("data-follow")){
        var t=b.getAttribute("data-follow");
        foc=(foc===t)?null:t;
        var rows=mx.querySelectorAll("tr[data-team]");
        for(var i=0;i<rows.length;i++){
          rows[i].classList.toggle("foc",rows[i].getAttribute("data-team")===foc);
        }
        var all=mx.querySelectorAll("[data-g]");
        for(var i=0;i<all.length;i++){
          var rel=!!foc&&(all[i].getAttribute("data-h")===foc||all[i].getAttribute("data-a")===foc);
          all[i].classList.toggle("dim",!!foc&&!rel);
          all[i].classList.toggle("rel",rel);
        }
        if(sum){
          var row=foc?mx.querySelector('tr[data-team="'+foc+'"]'):null;
          sum.textContent=row?row.getAttribute("data-sum"):sum.getAttribute("data-default");
        }
      }
    });
  }
})();
`;

function page(body: string): string {
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>${STYLE}</style></head><body><div class="sheet">${body}</div><script>${SCRIPT}</script></body></html>`;
}

// ── states before there is a season ─────────────────────────────────────────

export function composeNoProject(dataHomeNames: readonly string[]): string {
  const list = dataHomeNames.length
    ? `<p class="dek" style="text-align:center">Touchline data homes: ${dataHomeNames.map(esc).join(" · ")}</p>`
    : "";
  return page(`
    <div class="hero">
      <h1>Touchline</h1>
      <p>${
        dataHomeNames.length
          ? "Pick one of your data homes in the project picker above."
          : "No Touchline data home exists yet — run <code>/touchline my-soccer</code> to create one in the Keelson workspace."
      }</p>
      ${list}
    </div>`);
}

export function composeNotAHome(projectName: string, empty: boolean): string {
  return page(`
    <div class="hero">
      <h1>${esc(projectName)}</h1>
      <p>${
        empty
          ? "This folder is empty — exactly what Touchline expects. Open the Touchline chat with ✦ above and ask for a season; it initializes the folder and collects in one go."
          : "This folder is not a Touchline data home yet. Open the Touchline chat with ✦ above and ask for a season; Touchline will not disturb what is already here."
      }</p>
      <div class="say"><b>Say in chat</b>Get the 2026 schedule and roster for Harding men's soccer.</div>
    </div>`);
}

export function composeNoSeasons(projectName: string): string {
  return page(`
    <div class="hero">
      <h1>${esc(projectName)}</h1>
      <p>A Touchline data home, with nothing collected into it yet.</p>
      <div class="say"><b>Say in chat</b>Get the 2026 schedule and roster for Harding men's soccer.</div>
    </div>`);
}

export function composeUnreadable(detail: string): string {
  return page(`
    <div style="padding:14px">
      <div class="alarm"><b>THE BOARD DID NOT RENDER.</b> ${esc(detail)}
      <div style="margin-top:6px;color:var(--muted);font-size:12px">
      This is a read failure, not an empty season. The data files are unchanged — nothing has been lost.</div></div>
    </div>`);
}

// ── the board ───────────────────────────────────────────────────────────────

export interface BoardInput {
  projectName: string;
  fixtures: FixturesFile;
  rosters?: RostersFile;
  stats?: StatsFile;
  matches?: MatchesFile;
  /** Slug of the team lens, or undefined for the conference lens. */
  team?: string;
  /** Player key for the drawer — the roster's SideArm player id when it has
   *  one, else the player's name. Meaningful only alongside `team`. */
  player?: string;
  /** Fixture id for the match drawer. */
  fixture?: string;
  /** The roster archive for the shown gender — every season's roster file,
   *  for tenure lines. Order does not matter; each file carries its season. */
  rosterHistory?: readonly RostersFile[];
  /** Today, as YYYY-MM-DD. Passed in so the composer stays deterministic. */
  today: string;
  /** Every season on disk, so the masthead can step through the archive. */
  seasons?: ReadonlyArray<{ season: number; gender: string; conference: string }>;
}

const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

function parts(iso: string): { y: number; m: number; d: number; wd: number } {
  const p = iso.split("-").map(Number);
  const y = p[0] ?? 1970;
  const m = p[1] ?? 1;
  const d = p[2] ?? 1;
  return { y, m, d, wd: new Date(Date.UTC(y, m - 1, d)).getUTCDay() };
}

function fmtTime(hhmm: string): string {
  const p = hhmm.split(":").map(Number);
  const h = p[0] ?? 0;
  const m = p[1] ?? 0;
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
}

function daysBetween(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso}T00:00:00Z`);
  const b = Date.parse(`${toIso}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return 0;
  return Math.round((b - a) / 86_400_000);
}

function addDays(iso: string, n: number): string {
  const t = Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000;
  return new Date(t).toISOString().slice(0, 10);
}

function weekOf(iso: string, startIso: string): number {
  return Math.max(0, Math.floor(daysBetween(startIso, iso) / 7));
}

function displayName(slug: string, names: Map<string, string>): string {
  // A non-conference opponent has no programme entry, so its slug is all we
  // hold. Title-case it rather than printing `delta-state` at the reader — and
  // leave a bare acronym as an acronym, because "Dbu" is not a school.
  const known = names.get(slug);
  if (known) return known;
  if (!slug.includes("-") && slug.length <= 4) return slug.toUpperCase();
  // A trailing "-st" is the wire form of "State" (Delta St., Fort Hays St.);
  // "Saint" never abbreviates in trailing position, so the expansion is safe.
  return titleFromSlug(slug).replace(/ ST$/, " State");
}

/**
 * The season rail — the signature element.
 *
 * One tick per fixture, laid out by week across the whole season, so the shape
 * of the campaign is visible at a glance: dense weeks, bye weeks, and how far
 * the results have filled from the left. It doubles as a collection check — a
 * hollow tick BEHIND today is a match that has been played and never collected.
 */
/** A fixture's outcome from one team's perspective, once it is played. */
function outcomeFor(f: Fixture, team: string): "w" | "l" | "d" | undefined {
  if (!isPlayed(f) || typeof f.home_score !== "number" || typeof f.away_score !== "number")
    return undefined;
  if (f.home !== team && f.away !== team) return undefined;
  if (f.home_score === f.away_score) return "d";
  return (f.home === team) === f.home_score > f.away_score ? "w" : "l";
}

const OUTCOME_WORD = { w: "W", l: "L", d: "D" } as const;

function rail(fixtures: readonly Fixture[], today: string, team?: string): string {
  if (!fixtures.length) return "";
  const dates = fixtures.map((f) => f.date).sort();
  const first = dates[0] as string;
  const last = dates[dates.length - 1] as string;
  const total = weekOf(last, first) + 1;

  const buckets: Fixture[][] = Array.from({ length: total }, () => []);
  for (const f of fixtures) {
    const idx = Math.min(total - 1, weekOf(f.date, first));
    (buckets[idx] as Fixture[]).push(f);
  }
  const nowWeek = today >= first ? Math.min(total - 1, weekOf(today, first)) : -1;

  // Month labels span the weeks they cover, so the rail reads as a calendar
  // rather than an abstract bar chart.
  const monthAt: number[] = buckets.map((week, i) => {
    const anchor = week[0]?.date;
    return anchor ? parts(anchor).m : parts(addDays(first, i * 7)).m;
  });
  const runs: { m: number; start: number; len: number }[] = [];
  monthAt.forEach((m, i) => {
    const last = runs[runs.length - 1];
    if (last && last.m === m) last.len += 1;
    else runs.push({ m, start: i, len: 1 });
  });
  // A one-week fragment cannot hold a three-letter label without colliding with
  // its neighbour, so it goes unlabelled — the ticks still place it.
  const months = runs
    .filter((r) => r.len >= 2)
    .map(
      (r) =>
        `<span style="grid-column:${r.start + 1} / span ${r.len}">${MONS[r.m - 1] ?? ""}</span>`,
    )
    .join("");

  const weeks = buckets
    .map((week, i) => {
      const bars = week
        .map((f) => {
          // With a team in view the played tick carries the outcome — the rail
          // reads as a form strip: green won, red lost, amber drawn.
          const outcome = team ? outcomeFor(f, team) : undefined;
          const cls =
            f.status === "postponed" || f.status === "cancelled"
              ? "off"
              : f.status === "live"
                ? "live"
                : isPlayed(f)
                  ? (outcome ?? "played")
                  : f.date < today
                    ? "late"
                    : "";
          const title = outcome
            ? `${fmtDate(f.date)} · ${OUTCOME_WORD[outcome]} ${f.home_score}–${f.away_score}`
            : fmtDate(f.date);
          return `<i class="${cls}" title="${esc(title)}"></i>`;
        })
        .join("");
      const cls = [week.length ? "" : "bye", i === nowWeek ? "now" : ""].filter(Boolean).join(" ");
      return `<div class="wk ${cls}">${bars || "<i></i>"}</div>`;
    })
    .join("");

  const played = fixtures.filter(isPlayed).length;
  const late = fixtures.filter((f) => !isPlayed(f) && f.date < today && f.status === "scheduled");
  const toKickoff = daysBetween(today, first);

  const right =
    played === 0 && toKickoff > 0
      ? `First kickoff in <b>${toKickoff}</b> day${toKickoff === 1 ? "" : "s"}`
      : late.length
        ? `<span class="late-n">${late.length} played, not collected</span>`
        : `${total} week${total === 1 ? "" : "s"}`;

  return `
    <div class="rail">
      <div class="rail-strip" style="--n:${total}">
        <div class="rail-weeks">${weeks}</div>
        <div class="rail-months">${months}</div>
      </div>
      <div class="rail-foot">
        <span><b>${played}</b> of <b>${fixtures.length}</b> played</span>
        <span>${right}</span>
      </div>
    </div>`;
}

export function fmtDate(iso: string): string {
  const { m, d, wd } = parts(iso);
  return `${DAYS[wd]} ${MONS[m - 1]} ${d}`;
}

// ── match detail (box scores) ───────────────────────────────────────────────
// The matches file keys one box score per fixture id. Sides inside a detail
// are as the page served them; `home_index` is the collector's proof of which
// side is the fixture's home team, and everything oriented hangs off it.

/** Which served side is `perspective` (else the home side). Undefined when the
 *  collector could not prove orientation — render as-served or not at all. */
function sideIndexFor(detail: MatchDetail, f: Fixture, perspective?: string): number | undefined {
  const h = detail.home_index;
  if (h !== 0 && h !== 1) return undefined;
  if (!perspective || f.home === perspective) return h;
  return 1 - h;
}

function cardCount(detail: MatchDetail, side: number, kind: "yellow" | "red"): number {
  return (detail.cards ?? []).filter((c) => c.team === side && c.type === kind).length;
}

/** "82:11" → the 83rd minute, the way a goal is read aloud. */
function matchMinute(clock: string | undefined): string {
  const m = /^(\d+):(\d{2})/.exec(clock ?? "");
  if (!m) return "";
  const mins = Number(m[1]) + (m[2] === "00" ? 0 : 1);
  return `${mins}&prime;`;
}

/** The row's at-a-glance match: shot-on-goal and corner pairs read
 *  mine–theirs (home–away without a perspective), plus any cards. */
function matchStrip(f: Fixture, detail: MatchDetail | undefined, perspective?: string): string {
  if (!detail) return "";
  const mineIdx = sideIndexFor(detail, f, perspective);
  if (mineIdx === undefined) return "";
  const mine = detail.teams[mineIdx];
  const theirs = detail.teams[1 - mineIdx];
  if (!mine || !theirs) return "";
  const bits: string[] = [];
  const pair = (
    label: string,
    a: number | undefined,
    b: number | undefined,
    title: string,
  ): void => {
    if (typeof a === "number" && typeof b === "number")
      bits.push(`<span class="ms" title="${esc(title)}: ${a}–${b}">${label} ${a}–${b}</span>`);
  };
  pair("SOG", mine.sog, theirs.sog, "Shots on goal");
  pair("CK", mine.corners, theirs.corners, "Corner kicks");
  const yc = cardCount(detail, mineIdx, "yellow") + cardCount(detail, 1 - mineIdx, "yellow");
  const rc = cardCount(detail, mineIdx, "red") + cardCount(detail, 1 - mineIdx, "red");
  if (yc)
    bits.push(
      `<span class="ms" title="Yellow cards: ${cardCount(detail, mineIdx, "yellow")}–${cardCount(detail, 1 - mineIdx, "yellow")}"><i class="cs y"></i>${yc}</span>`,
    );
  if (rc)
    bits.push(
      `<span class="ms" title="Red cards: ${cardCount(detail, mineIdx, "red")}–${cardCount(detail, 1 - mineIdx, "red")}"><i class="cs r"></i>${rc}</span>`,
    );

  // In the team lens the row also names who scored — the one fact a coach
  // reads a results column for.
  let scorers = "";
  if (perspective) {
    const own = (detail.scoring ?? []).filter((s) => s.team === mineIdx);
    if (own.length) {
      scorers = `<span class="gls">${own
        .map((s) => `${esc(s.scorer)} ${matchMinute(s.time)}`)
        .join(" · ")}</span>`;
    }
  }
  return bits.length || scorers ? `<span class="msx">${bits.join("")}${scorers}</span>` : "";
}

/** One ledger row. In the team lens a fixture reads the way a schedule reads:
 *  home-or-away, then the opponent. In the conference lens both sides are named. */
function ledgerRow(
  f: Fixture,
  names: Map<string, string>,
  slugs: string[],
  perspective?: string,
  detail?: MatchDetail,
): string {
  const { m, d, wd } = parts(f.date);
  const played = isPlayed(f) || f.status === "live";
  const off = f.status === "postponed" || f.status === "cancelled";

  let outcome = "";
  if (
    played &&
    perspective &&
    typeof f.home_score === "number" &&
    typeof f.away_score === "number"
  ) {
    const mine = f.home === perspective ? f.home_score : f.away_score;
    const theirs = f.home === perspective ? f.away_score : f.home_score;
    outcome = mine > theirs ? "won" : mine < theirs ? "lost" : "tied";
  }

  // Without a perspective there is no H/A cell, so the row must switch to the
  // three-column grid — otherwise the opponent lands in the 22px H/A track.
  const cls = [
    perspective ? "" : "both",
    f.conference_game ? "conf" : "",
    off ? "off" : "",
    outcome,
  ]
    .filter(Boolean)
    .join(" ");

  let ha = "";
  let opponent: string;
  if (perspective) {
    const isHome = f.home === perspective;
    const other = isHome ? f.away : f.home;
    ha = `<div class="ha ${isHome ? "h" : ""}">${isHome ? "H" : "A"}</div>`;
    opponent = `<span class="n">${esc(displayName(other, names))}</span>`;
  } else {
    // No H/A badge in the conference lens: neither side is "ours", and an empty
    // bordered box on every row is an artifact, not information.
    ha = "";
    opponent = `<span class="n"><i class="chip" style="background:${hueFor(f.home, slugs)}"></i>${esc(
      displayName(f.home, names),
    )} <span style="color:var(--faint);font-weight:400">v</span> <i class="chip" style="background:${hueFor(
      f.away,
      slugs,
    )}"></i>${esc(displayName(f.away, names))}</span>`;
  }

  let right: string;
  if (off) {
    right = `<span class="st">${f.status === "postponed" ? "Postponed" : "Cancelled"}</span>`;
  } else if (played) {
    const a = f.home_score ?? "–";
    const b = f.away_score ?? "–";
    const score = perspective ? (f.home === perspective ? `${a}–${b}` : `${b}–${a}`) : `${a}–${b}`;
    right = `<span class="sc">${esc(score)}</span><span class="st">${f.status === "live" ? esc(f.clock ?? "Live") : "Final"}</span>`;
  } else {
    right = `<span class="tm">${f.time ? esc(fmtTime(f.time)) : "TBA"}</span>`;
  }

  const payload = esc(JSON.stringify({ fixture: f.id }));
  return `<div class="row ${cls}" tabindex="0" role="button" data-act="open-fixture" data-payload="${payload}"
      aria-label="Open match details">
      <div class="d">${MONS[m - 1]} ${d}<em>${DAYS[wd]}</em></div>
      ${ha}
      <div class="opp">${opponent}${f.venue ? `<span class="v">${esc(f.venue)}</span>` : ""}${matchStrip(f, detail, perspective)}</div>
      <div class="r">${right}</div>
    </div>`;
}

const WDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** What the selection card says about one fixture. Upcoming reads as a
 *  listing ("Away at Home"); a result reads as a scoreline, home side first,
 *  the way a final is reported. */
function cardBits(
  f: Fixture,
  names: Map<string, string>,
): { mo: string; dy: string; tt: string; nt: string } {
  const { m, d, wd } = parts(f.date);
  const home = displayName(f.home, names);
  const away = displayName(f.away, names);
  const off = f.status === "postponed" || f.status === "cancelled";
  const played = isPlayed(f) || f.status === "live";
  let tt: string;
  let nt: string;
  if (played) {
    tt = `${home} ${f.home_score ?? "–"}–${f.away_score ?? "–"} ${away}`;
    nt = [f.status === "live" ? (f.clock ?? "Live") : "Final", f.venue].filter(Boolean).join(" · ");
  } else {
    tt = `${away} at ${home}`;
    nt = off
      ? f.status === "postponed"
        ? "Postponed"
        : "Cancelled"
      : [WDAYS[wd], f.time ? fmtTime(f.time) : undefined, f.venue].filter(Boolean).join(" · ");
  }
  return { mo: MONS[m - 1] ?? "", dy: String(d), tt, nt };
}

/**
 * The matchday matrix — the conference lens when more than one programme is
 * collected. Teams are rows, real fixture dates are columns, and a cell names
 * the opponent: filled when the row team is at home, dashed when the opponent
 * is from outside the conference. Following a team and inspecting a match are
 * client-side; nothing here writes.
 */
function matrix(
  file: FixturesFile,
  fixtures: readonly Fixture[],
  names: Map<string, string>,
  today: string,
): string {
  const abbrs = new Map(file.programmes.map((p) => [p.slug, p.abbr]));
  const codeFor = (slug: string): string => {
    const a = abbrs.get(slug);
    if (a) return a;
    if (!slug.includes("-") && slug.length <= 4) return slug.toUpperCase();
    return monogram(displayName(slug, names));
  };

  const dates = [...new Set(fixtures.map((f) => f.date))].sort();
  const byCell = new Map<string, Fixture>();
  for (const f of fixtures) {
    for (const side of [f.home, f.away]) {
      const k = `${side}|${f.date}`;
      if (!byCell.has(k)) byCell.set(k, f);
    }
  }

  // Month heads span the dates they cover, exactly like the season rail.
  const runs: { m: number; len: number }[] = [];
  for (const d of dates) {
    const m = parts(d).m;
    const last = runs[runs.length - 1];
    if (last && last.m === m) last.len += 1;
    else runs.push({ m, len: 1 });
  }
  const monthRow = runs
    .map(
      (r) => `<th class="mo-h" colspan="${r.len}">${r.len >= 2 ? (MONS[r.m - 1] ?? "") : ""}</th>`,
    )
    .join("");
  const dayRow = dates
    .map((d) => {
      const p = parts(d);
      return `<th class="dy-h" scope="col">${MONS[p.m - 1]} ${p.d}<em>${DAYS[p.wd]}</em></th>`;
    })
    .join("");

  const teams = [...file.programmes].sort((a, b) => a.name.localeCompare(b.name));

  // Default selection: the next fixture from today, or the last one played.
  const pick = fixtures.find((f) => f.date >= today) ?? fixtures[fixtures.length - 1];

  const rows = teams
    .map((p) => {
      let homeN = 0;
      let awayN = 0;
      let confN = 0;
      const cells = dates
        .map((d) => {
          const f = byCell.get(`${p.slug}|${d}`);
          if (!f) return `<td class="c"></td>`;
          const isHome = f.home === p.slug;
          if (isHome) homeN += 1;
          else awayN += 1;
          if (f.conference_game) confN += 1;
          const opp = isHome ? f.away : f.home;
          const played = isPlayed(f);
          const late = !played && f.date < today && f.status === "scheduled";
          let out = "";
          let sc = "";
          if (played && typeof f.home_score === "number" && typeof f.away_score === "number") {
            const mine = isHome ? f.home_score : f.away_score;
            const theirs = isHome ? f.away_score : f.home_score;
            out = mine > theirs ? "w" : mine < theirs ? "l" : "d";
            sc = `<span class="sc">${mine}–${theirs}</span>`;
          }
          const bits = cardBits(f, names);
          const cls = [
            "m",
            isHome ? "h" : "",
            f.conference_game ? "" : "nc",
            late ? "lt" : "",
            out,
            f.id === pick?.id ? "is-sel" : "",
          ]
            .filter(Boolean)
            .join(" ");
          const label = `${p.name} ${isHome ? "hosts" : "visits"} ${displayName(opp, names)} on ${fmtDate(f.date)}${
            sc
              ? `, ${isHome ? f.home_score : f.away_score}–${isHome ? f.away_score : f.home_score}`
              : ""
          }`;
          return `<td class="c"><button type="button" class="${cls}" data-g="${esc(f.id)}"
            data-h="${esc(f.home)}" data-a="${esc(f.away)}"
            data-mo="${esc(bits.mo)}" data-dy="${esc(bits.dy)}" data-tt="${esc(bits.tt)}" data-nt="${esc(bits.nt)}"
            aria-pressed="${f.id === pick?.id}" aria-label="${esc(label)}">${esc(codeFor(opp))}${sc}</button></td>`;
        })
        .join("");
      // Once matches are played the team cell carries a thin record bar —
      // won, drawn, lost by share — so the left column reads as a table of
      // form without adding a standings table the matrix already implies.
      let wonN = 0;
      let drawnN = 0;
      let lostN = 0;
      for (const f of fixtures) {
        const o = outcomeFor(f, p.slug);
        if (o === "w") wonN += 1;
        else if (o === "d") drawnN += 1;
        else if (o === "l") lostN += 1;
      }
      const recTitle = `${wonN} won · ${drawnN} drawn · ${lostN} lost`;
      const rec =
        wonN + drawnN + lostN > 0
          ? `<span class="rec" title="${recTitle}" role="img" aria-label="${esc(`${p.name}: ${recTitle}`)}">${(
              [
                ["w", wonN],
                ["d", drawnN],
                ["l", lostN],
              ] as const
            )
              .filter(([, n]) => n > 0)
              .map(([k, n]) => `<i class="${k}" style="flex:${n}"></i>`)
              .join("")}</span>`
          : "";
      const sum = `${p.name} · ${wonN + drawnN + lostN ? `${wonN}W ${drawnN}D ${lostN}L · ` : ""}${homeN} home · ${awayN} away · ${confN} conference`;
      return `<tr data-team="${esc(p.slug)}" data-sum="${esc(sum)}">
        <th class="tm" scope="row"><button type="button" data-follow="${esc(p.slug)}" aria-label="Follow ${esc(p.name)}">
          <span class="cd">${esc(codeFor(p.slug))}</span><span class="who"><span class="nm">${esc(p.name)}</span>${rec}</span></button></th>
        ${cells}</tr>`;
    })
    .join("");

  const late = fixtures.filter((f) => !isPlayed(f) && f.date < today && f.status === "scheduled");
  const defaultSum = `${dates.length} matchday${dates.length === 1 ? "" : "s"} · ${fixtures.length} match${fixtures.length === 1 ? "" : "es"}`;
  const picked = pick ? cardBits(pick, names) : { mo: "", dy: "", tt: "", nt: "" };

  // The rail carried the countdown; in matrix mode the footer carries it.
  const playedN = fixtures.filter(isPlayed).length;
  const toKickoff = dates.length ? daysBetween(today, dates[0] as string) : 0;
  const middle =
    playedN === 0 && toKickoff > 0
      ? `<span>First kickoff in <b>${toKickoff}</b> day${toKickoff === 1 ? "" : "s"}</span>`
      : late.length
        ? `<span class="late-n">${late.length} played, not collected</span>`
        : "";

  // No legend: the home tint and each cell's spoken label carry venue, and the
  // selected cell explains itself — outlined, with the card above naming it.
  return `
    <div class="sec"><h2>Matchday board</h2></div>
    <div class="mx-sel" aria-live="polite">
      <div class="db" aria-hidden="true"><div class="mo" id="mx-mo">${esc(picked.mo)}</div>
        <div class="dy num" id="mx-dy">${esc(picked.dy)}</div></div>
      <div><div class="tt" id="mx-tt">${esc(picked.tt)}</div><div class="nt" id="mx-nt">${esc(picked.nt)}</div></div>
      <button type="button" class="mx-open" id="mx-open" ${pick ? "" : "hidden "}data-act="open-fixture"
        data-payload='${esc(JSON.stringify({ fixture: pick?.id ?? null }))}'>Match details</button>
    </div>
    <div class="mx-wrap" role="region" aria-label="Conference schedule grid" tabindex="0">
      <table class="mx">
        <thead>
          <tr><th class="tm-h" rowspan="2" scope="col">Team</th>${monthRow}</tr>
          <tr>${dayRow}</tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="mx-foot">
      <span id="mx-sum" data-default="${esc(defaultSum)}">${esc(defaultSum)}</span>
      ${middle}
      <span>Select a team to follow it · select a match to inspect it</span>
    </div>`;
}

// ── roster composition ──────────────────────────────────────────────────────
// Everything here counts what the roster file publishes; nothing is derived
// beyond bucketing the published strings, which range from full words
// ("Goalkeeper") to bare abbreviations ("GK", "D", "MF", "FWD") by theme.

// Attack-first, the way a team sheet is read aloud.
const POSITIONS = [
  { key: "f", abbr: "FWD", head: "Forwards", test: /^(f|fw|fwd)$|^(for|strik|wing)/i },
  { key: "m", abbr: "MID", head: "Midfielders", test: /^(m|mf)$|^mid/i },
  { key: "d", abbr: "DEF", head: "Defenders", test: /^(d|df)$|^def/i },
  { key: "gk", abbr: "GK", head: "Goalkeepers", test: /^(gk|k)$|^goal/i },
] as const;

function posKey(position?: string): string | null {
  if (!position) return null;
  for (const p of POSITIONS) if (p.test.test(position)) return p.key;
  return null;
}

// Most-senior first: the eye lands on the left of a bar, and experience is
// the thing a class mix is read for. The ramp fades with tenure — deep wine
// for graduates and seniors down to pale rose for freshmen.
const CLASSES = [
  { key: "gr", abbr: "GR", head: "Graduates (5th year+)", test: /grad/i },
  { key: "sr", abbr: "SR", head: "Seniors", test: /senior/i },
  { key: "jr", abbr: "JR", head: "Juniors", test: /junior/i },
  { key: "so", abbr: "SO", head: "Sophomores", test: /soph/i },
  { key: "fr", abbr: "FR", head: "Freshmen", test: /fresh/i },
] as const;

function classInfo(year?: string): { key: string; abbr: string } | null {
  if (!year) return null;
  for (const c of CLASSES) {
    if (c.test.test(year)) {
      return { key: c.key, abbr: /redshirt/i.test(year) ? `R-${c.abbr}` : c.abbr };
    }
  }
  return null;
}

/** US state names and their AP-style abbreviations, as roster pages print
 *  them — so an international hometown's region can be set apart. */
const US_REGIONS = new Set([
  ...[
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
  ],
  ...[
    "Ala.",
    "Ariz.",
    "Ark.",
    "Calif.",
    "Colo.",
    "Conn.",
    "Del.",
    "Fla.",
    "Ga.",
    "Ill.",
    "Ind.",
    "Kan.",
    "Ky.",
    "La.",
    "Md.",
    "Mass.",
    "Mich.",
    "Minn.",
    "Miss.",
    "Mo.",
    "Mont.",
    "Neb.",
    "Nev.",
    "N.H.",
    "N.J.",
    "N.M.",
    "N.Y.",
    "N.C.",
    "N.D.",
    "Okla.",
    "Ore.",
    "Pa.",
    "R.I.",
    "S.C.",
    "S.D.",
    "Tenn.",
    "Vt.",
    "Va.",
    "Wash.",
    "W.Va.",
    "Wis.",
    "Wyo.",
    "D.C.",
  ],
  ...[
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
  ],
]);

/** `5'8"` as printed → `5′8″` as typeset. */
function heightDisplay(height?: string): string {
  if (!height) return "";
  return height.replace(/'/g, "′").replace(/"/g, "″");
}

/** City plain; a region outside the US set apart — the squad's reach should be
 *  readable at a scan, which is why hometown lives on the row at all. */
function hometownHtml(hometown?: string): string {
  if (!hometown) return "";
  const cut = hometown.lastIndexOf(",");
  if (cut < 0) return esc(hometown);
  const city = hometown.slice(0, cut).trim();
  const region = hometown.slice(cut + 1).trim();
  if (US_REGIONS.has(region)) return `${esc(city)}, ${esc(region)}`;
  // The flag makes an international player findable at a scan; the bolded
  // country still carries the where.
  return `<i class="fl" aria-hidden="true">⚑</i>${esc(city)}, <b>${esc(region)}</b>`;
}

function compBar(
  segs: readonly { cls: string; count: number; title: string; abbr?: string }[],
  total: number,
): string {
  if (!total) return "";
  const inner = segs
    .filter((s) => s.count > 0)
    .map((s) => {
      const pct = (s.count / total) * 100;
      // This bar spans the panel, so even a modest share has room to name
      // itself; only a sliver falls back to its count or its title alone.
      const label = pct >= 6 && s.abbr ? `${s.count} ${s.abbr}` : pct >= 4 ? String(s.count) : "";
      return `<span class="${s.cls}" style="width:${pct.toFixed(2)}%" title="${esc(s.title)}: ${s.count}">${label}</span>`;
    })
    .join("");
  return `<div class="bar">${inner}</div>`;
}

// ── roster tenure ───────────────────────────────────────────────────────────
// SideArm's roster ids are per-season entry ids, not stable player ids, so
// continuity joins on exact name within a programme — verified clean across
// the collected archive (no name appears on two programmes in one season).
// Tenure states facts ("first season on this roster"), never conclusions
// ("transfer"): a debut sophomore may equally be a redshirt or late walk-on.

/** Which earlier seasons the archive holds a non-empty roster for, and whether
 *  that coverage runs unbroken from the programme's first collected roster to
 *  the season before the one shown. Own-roster tenure claims are absence
 *  claims — "first season on this roster" denies every earlier appearance, and
 *  "3rd season" denies a fourth — so a skipped or unreadable archive season
 *  could hide the very appearance a claim rules out. Complete coverage is the
 *  licence to make them; positive sightings (a prior stint elsewhere) need no
 *  such licence, because a gap can only hide more of them. */
function priorRosterCoverage(
  history: readonly RostersFile[],
  programme: string,
  season: number,
): { covered: number[]; complete: boolean } {
  const covered = history
    .filter((f) => f.season < season && (f.rosters[programme]?.players.length ?? 0) > 0)
    .map((f) => f.season)
    .sort((a, b) => a - b);
  const first = covered[0];
  const complete = first !== undefined && covered.length === season - first;
  return { covered, complete };
}

interface Tenure {
  /** Seasons up to and including the shown one where this name appears on
   *  this programme's roster, ascending. Later seasons are excluded so an
   *  archive board never counts a future the season did not know about. */
  seasons: number[];
  /** Earlier appearances on other programmes' rosters — the intra-conference
   *  move worth a scouting note. Keyed by slug; the caller resolves names. */
  elsewhere: { programme: string; seasons: number[] }[];
  /** Whether prior coverage for this programme is complete (see
   *  priorRosterCoverage). False suppresses every own-roster claim. */
  priorComplete: boolean;
}

function tenureFor(
  history: readonly RostersFile[],
  programme: string,
  name: string,
  season: number,
): Tenure {
  const seasons: number[] = [];
  const elsewhere = new Map<string, number[]>();
  for (const file of history) {
    if (file.season > season) continue;
    for (const [slug, roster] of Object.entries(file.rosters)) {
      if (slug === programme) {
        if (roster.players.some((p) => p.name === name)) seasons.push(file.season);
      } else if (file.season < season && roster.players.some((p) => p.name === name)) {
        elsewhere.set(slug, [...(elsewhere.get(slug) ?? []), file.season]);
      }
    }
  }
  return {
    seasons: seasons.sort((a, b) => a - b),
    elsewhere: [...elsewhere.entries()].map(([programme, ss]) => ({
      programme,
      seasons: ss.sort((a, b) => a - b),
    })),
    priorComplete: priorRosterCoverage(history, programme, season).complete,
  };
}

/** "2024–2026", "2022, 2024–2026" — consecutive seasons fold into a span. */
function fmtSeasonSpans(seasons: readonly number[]): string {
  const spans: string[] = [];
  let start: number | undefined;
  let prev: number | undefined;
  for (const s of seasons) {
    if (start === undefined || prev === undefined || s !== prev + 1) {
      if (start !== undefined && prev !== undefined)
        spans.push(start === prev ? String(start) : `${start}–${prev}`);
      start = s;
    }
    prev = s;
  }
  if (start !== undefined && prev !== undefined)
    spans.push(start === prev ? String(start) : `${start}–${prev}`);
  return spans.join(", ");
}

function ordinal(n: number): string {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${suffix}`;
}

/** The drawer's tenure sentence, or "" when the archive cannot support one. */
function tenureLine(
  tenure: Tenure,
  classYear: string | undefined,
  names: Map<string, string>,
): string {
  const parts: string[] = [];
  if (tenure.priorComplete) {
    if (tenure.seasons.length > 1) {
      parts.push(
        `${ordinal(tenure.seasons.length)} season on the roster (${fmtSeasonSpans(tenure.seasons)})`,
      );
    } else {
      parts.push("First season on this roster");
      // A debut above freshman class is the arrival worth flagging; the class
      // year is the roster's own word for where they are, so print it verbatim.
      const cls = classInfo(classYear);
      if (cls && cls.key !== "fr") parts.push(`arrived as ${classYear}`);
    }
  } else if (tenure.seasons.length > 1) {
    // Incomplete coverage (the 2020 rosters of two programmes are named
    // collection gaps, for instance): no count, no "first season" — but the
    // recorded sightings themselves are still facts worth stating.
    parts.push(`On the roster in ${fmtSeasonSpans(tenure.seasons)}`);
  }
  for (const e of tenure.elsewhere) {
    parts.push(`previously at ${displayName(e.programme, names)} (${fmtSeasonSpans(e.seasons)})`);
  }
  return parts.length ? `<div class="dr-tenure">${parts.map((p) => esc(p)).join(" · ")}</div>` : "";
}

// ── player season statistics ────────────────────────────────────────────────
// The stats file joins to the roster by SideArm's own player id — the tail of
// the roster bio URL and the id on the stats row's anchor are the same number.
// Name is the fallback for the rare row whose id differs between the pages.

function rosterPlayerId(p: Player): string | undefined {
  return /\/(\d+)\/?$/.exec(p.source_url ?? "")?.[1];
}

/** The select-player action key for a roster player: stable id when there is
 *  one, else the name. What the drawer looks up must match what the row posts. */
export function playerKey(p: Player): string {
  return rosterPlayerId(p) ?? p.name;
}

/** One player's season, as published: a keeper has both lines when they also
 *  appear in the offensive table. */
interface SeasonLine {
  field?: PlayerStats;
  keeper?: KeeperStats;
}

function statsIndex(team: TeamStats | undefined): Map<string, SeasonLine> {
  const by = new Map<string, SeasonLine>();
  if (!team) return by;
  const put = (key: string | undefined, patch: SeasonLine) => {
    if (key) by.set(key, { ...by.get(key), ...patch });
  };
  for (const s of team.players) {
    put(s.player_id, { field: s });
    put(s.name.toLowerCase(), { field: s });
  }
  for (const k of team.keepers) {
    put(k.player_id, { keeper: k });
    put(k.name.toLowerCase(), { keeper: k });
  }
  return by;
}

function lineFor(index: Map<string, SeasonLine>, p: Player): SeasonLine | undefined {
  return index.get(rosterPlayerId(p) ?? "") ?? index.get(p.name.toLowerCase());
}

/** The row's at-a-glance season: a minutes bar scaled to the squad's most-used
 *  player, then the two or three numbers that tell this player's story. */
function statStrip(line: SeasonLine | undefined, maxMinutes: number): string {
  if (!line) return "";
  const { field: f, keeper: k } = line;
  const minutes = k?.minutes ?? f?.minutes ?? 0;
  const pct = maxMinutes > 0 ? Math.min(100, (minutes / maxMinutes) * 100) : 0;
  const chips: string[] = [];
  const chip = (cls: string, value: number | string, label: string, title: string) =>
    chips.push(
      `<span class="stat ${cls}" title="${esc(title)}"><b>${esc(value)}</b>${esc(label)}</span>`,
    );
  if (k) {
    if (typeof k.saves === "number") chip("sv", k.saves, "SV", `${k.saves} saves`);
    if (typeof k.goals_against === "number")
      chip("ga", k.goals_against, "GA", `${k.goals_against} goals against`);
    if (typeof k.save_pct === "number")
      chip(
        "pc",
        `${Math.round(k.save_pct * 100)}%`,
        "",
        `Save percentage ${(k.save_pct * 100).toFixed(1)}%`,
      );
  } else if (f) {
    if (f.goals) chip("g", f.goals, "G", `${f.goals} goals`);
    if (f.assists) chip("a", f.assists, "A", `${f.assists} assists`);
    if (f.shots) chip("sh", f.shots, "SH", `${f.shots} shots`);
  }
  return `<span class="st"><span class="mb" title="${minutes} minutes played"><span style="width:${pct.toFixed(1)}%"></span></span><span class="mn">${minutes}&prime;</span>${chips.join("")}</span>`;
}

function teamRosterBlock(
  roster: Roster,
  stats: TeamStats | undefined,
  season: number,
  history: readonly RostersFile[],
): string {
  const players = roster.players;
  const idx = statsIndex(stats);

  // First-season players earn a quiet chip; returning is the default state
  // and carries no ink. Chips are absence claims, so they render only over
  // complete prior coverage (see priorRosterCoverage) — a missing archive
  // season could hide the appearance that would make a player returning, and
  // with no history at all "new" would describe our records, not the squad.
  const { complete: priorComplete } = priorRosterCoverage(history, roster.programme, season);
  const returning = new Set<string>();
  for (const file of history) {
    if (file.season >= season) continue;
    for (const p of file.rosters[roster.programme]?.players ?? []) returning.add(p.name);
  }
  const newChip = (p: Player) =>
    priorComplete && !returning.has(p.name)
      ? '<span class="new" title="First season on this roster">NEW</span>'
      : "";
  const maxMinutes = Math.max(
    0,
    ...(stats?.players ?? []).map((s) => s.minutes ?? 0),
    ...(stats?.keepers ?? []).map((k) => k.minutes ?? 0),
  );
  const num = (p: Player): number => {
    const n = Number.parseInt(p.number ?? "", 10);
    return Number.isNaN(n) ? 999 : n;
  };
  const sorted = [...players].sort((a, b) => num(a) - num(b) || a.name.localeCompare(b.name));

  const byPos = new Map<string | null, Player[]>();
  for (const p of sorted) {
    const k = posKey(p.position);
    const list = byPos.get(k) ?? [];
    list.push(p);
    byPos.set(k, list);
  }
  const unlisted = byPos.get(null)?.length ?? 0;
  const hasPos = players.length > unlisted;

  const posSegs = [
    ...POSITIONS.map((p) => ({
      cls: p.key,
      count: byPos.get(p.key)?.length ?? 0,
      title: p.head,
      abbr: p.abbr,
    })),
    { cls: "un", count: unlisted, title: "Position not published" },
  ];
  const clsCount = new Map<string, number>();
  let clsUnknown = 0;
  for (const p of sorted) {
    const c = classInfo(p.class_year);
    if (c) clsCount.set(c.key, (clsCount.get(c.key) ?? 0) + 1);
    else clsUnknown += 1;
  }
  const clsSegs = [
    ...CLASSES.map((c) => ({
      cls: c.key,
      count: clsCount.get(c.key) ?? 0,
      title: c.head,
      abbr: c.abbr,
    })),
    { cls: "un", count: clsUnknown, title: "Class not published" },
  ];

  // The continuity split at a glance: how much of the squad was here before.
  // Same complete-coverage guard as the chips, and for the same reason.
  const retCount = players.filter((p) => returning.has(p.name)).length;
  const tenSegs = [
    { cls: "ret", count: retCount, title: "Returning — on an earlier roster", abbr: "RET" },
    {
      cls: "arr",
      count: players.length - retCount,
      title: "First season on this roster",
      abbr: "NEW",
    },
  ];

  const barRow = (label: string, bar: string) =>
    `<div class="bar-row"><span class="lbl">${label}</span>${bar}</div>`;
  const bars = `<div class="bars">
    ${hasPos ? barRow("Position", compBar(posSegs, players.length)) : ""}
    ${barRow("Class", compBar(clsSegs, players.length))}
    ${priorComplete ? barRow("Tenure", compBar(tenSegs, players.length)) : ""}
  </div>`;

  const playerRow = (p: Player) => {
    const cls = classInfo(p.class_year);
    const inner = `
      <div class="no">${esc(p.number ?? "")}</div>
      <div class="nm">${esc(p.name)}${newChip(p)}</div>
      <div class="ht">${esc(heightDisplay(p.height))}</div>
      <div class="yr">${cls ? `<i class="${cls.key}"></i>${esc(cls.abbr)}` : ""}</div>
      ${p.hometown ? `<div class="home">${hometownHtml(p.hometown)}</div>` : ""}
      ${statStrip(lineFor(idx, p), maxMinutes)}`;
    // Every row opens the drawer: even before a season's statistics exist,
    // the drawer carries the published bio and the player's roster tenure —
    // and it says plainly that statistics are yet to come.
    return `<button type="button" class="prow act" data-act="select-player" data-payload='${esc(
      JSON.stringify({ player: playerKey(p) }),
    )}' aria-label="Open ${esc(p.name)}&#39;s details">${inner}</button>`;
  };

  const group = (tick: string, head: string, list: readonly Player[]) =>
    list.length
      ? `<div class="rgroup${list.length > 12 ? " flow" : ""}"><h3><i class="${tick}"></i>${esc(head)}<span class="n">${list.length}</span></h3>
        ${list.map(playerRow).join("")}</div>`
      : "";

  const groups = hasPos
    ? [
        ...POSITIONS.map((p) => group(p.key, p.head, byPos.get(p.key) ?? [])),
        group("un", "Position not listed", byPos.get(null) ?? []),
      ].join("")
    : group("un", "Squad", sorted);

  return `<div class="sec"><h2>Roster</h2><span class="count">${players.length} players</span></div>
    ${bars}<div class="rgrid">${groups}</div>`;
}

/** The player drawer: the roster row's person, then their published season.
 *  It renders over the sheet and closes from the veil, the ✕, or Escape. */
function playerDrawer(
  key: string,
  roster: Roster | undefined,
  stats: TeamStats | undefined,
  teamName: string,
  season: number,
  teamPlayed: number,
  history: readonly RostersFile[],
  names: Map<string, string>,
): string {
  const rosterP = roster?.players.find((p) => playerKey(p) === key || p.name === key);
  const idx = statsIndex(stats);
  const line = rosterP ? lineFor(idx, rosterP) : (idx.get(key) ?? idx.get(key.toLowerCase()));
  const f = line?.field;
  const k = line?.keeper;
  const name = rosterP?.name ?? f?.name ?? k?.name;
  if (!name) return "";
  const number = rosterP?.number ?? f?.number ?? k?.number;

  const bio = [
    rosterP?.position,
    rosterP?.class_year,
    heightDisplay(rosterP?.height) || undefined,
    rosterP?.weight,
  ]
    .filter(Boolean)
    .map((v) => esc(v))
    .join(" · ");
  const bioBlock =
    bio || rosterP?.hometown
      ? `<div class="dr-bio">${bio}${bio && rosterP?.hometown ? "<br>" : ""}${
          rosterP?.hometown ? hometownHtml(rosterP.hometown) : ""
        }</div>`
      : "";

  // Tenure needs a roster identity to join on: a stats-only player (no roster
  // row) gets no tenure claim rather than a name-matched guess.
  const tenureBlock =
    rosterP && roster && history.length
      ? tenureLine(
          tenureFor(history, roster.programme, rosterP.name, season),
          rosterP.class_year,
          names,
        )
      : "";

  const cell = (value: string, label: string) => `<div><b>${value}</b><span>${label}</span></div>`;
  const n = (value: number | undefined): string =>
    typeof value === "number" ? String(value) : "–";
  const sections: string[] = [];

  const appearances =
    line && typeof (k?.gp ?? f?.gp) === "number"
      ? `${n(k?.gp ?? f?.gp)} appearance${(k?.gp ?? f?.gp) === 1 ? "" : "s"}${
          typeof (k?.gs ?? f?.gs) === "number" ? `, ${n(k?.gs ?? f?.gs)} starts` : ""
        }`
      : "";
  const minutes = k?.minutes ?? f?.minutes;
  // Ninety minutes per played match is the honest denominator the schedule
  // provides; overtime can push a full-season figure past it, so clamp.
  const available = teamPlayed * 90;
  const minutesBlock =
    typeof minutes === "number"
      ? `<div class="dr-bar-row"><span class="dr-lbl">Minutes</span>
         <span class="dr-min-n">${minutes}&prime;${available ? ` of ${available}&prime; available` : ""}${appearances ? ` · ${appearances}` : ""}</span>
         ${available ? `<div class="dr-min"><span style="width:${Math.min(100, (minutes / available) * 100).toFixed(1)}%"></span></div>` : ""}
       </div>`
      : "";

  if (k) {
    const shots = (k.saves ?? 0) + (k.goals_against ?? 0);
    const split =
      shots > 0
        ? `<div class="dr-bar-row"><span class="dr-lbl">Shots on target faced</span>
           <div class="dr-split">${
             k.saves ? `<span class="sv" style="flex:${k.saves}">${k.saves} saved</span>` : ""
}${
             k.goals_against
               ? `<span class="ga" style="flex:${k.goals_against}">${k.goals_against} conceded</span>`
               : ""
}</div></div>`
        : "";
    const record =
      typeof k.wins === "number" || typeof k.losses === "number"
        ? cell(`${n(k.wins)}–${n(k.losses)}–${n(k.ties ?? 0)}`, "Record in goal")
        : "";
    sections.push(`<div class="dr-sec">Goalkeeping</div>
      <div class="dr-grid">
        ${cell(typeof k.save_pct === "number" ? `${(k.save_pct * 100).toFixed(1)}%` : "–", "Save pct")}
        ${cell(n(k.gaa), "Goals against avg")}
        ${cell(n(k.shutouts), "Shutouts")}
        ${cell(n(k.saves), "Saves")}
        ${cell(n(k.goals_against), "Goals against")}
        ${record || cell(n(k.shots_faced), "Shots faced")}
      </div>${split}`);
  }

  if (f && (!k || (f.shots ?? 0) > 0 || (f.goals ?? 0) > 0)) {
    const accuracy =
      (f.shots ?? 0) > 0 && typeof f.sog === "number"
        ? `<div class="dr-bar-row"><span class="dr-lbl">Shooting</span>
           <span class="dr-min-n">${f.sog} of ${f.shots} shots on target</span>
           <div class="dr-min acc"><span style="width:${(((f.sog ?? 0) / (f.shots || 1)) * 100).toFixed(1)}%"></span></div>
         </div>`
        : "";
    const extras: string[] = [];
    if (f.game_winners) extras.push(`${f.game_winners} game-winning`);
    if (f.penalty_attempts)
      extras.push(`${f.penalty_goals ?? 0} of ${f.penalty_attempts} penalties scored`);
    if ((f.yellow ?? 0) > 0 || (f.red ?? 0) > 0)
      extras.push(`${f.yellow ?? 0} yellow, ${f.red ?? 0} red`);
    sections.push(`<div class="dr-sec">${k ? "In front of goal" : "Season"}</div>
      <div class="dr-grid">
        ${cell(n(f.goals), "Goals")}
        ${cell(n(f.assists), "Assists")}
        ${cell(n(f.points), "Points")}
        ${cell(n(f.shots), "Shots")}
        ${cell(n(f.sog), "On target")}
        ${cell(typeof f.shot_pct === "number" ? `${(f.shot_pct * 100).toFixed(1)}%` : "–", "Conversion")}
      </div>${accuracy}${extras.length ? `<p class="dr-note">${esc(extras.join(" · "))}</p>` : ""}`);
  }

  const body = line
    ? `${minutesBlock}${sections.join("")}`
    : `<p class="dr-note">${
        stats
          ? `No minutes recorded in the ${season} season statistics — on the roster, but yet to appear.`
          : `No ${season} season statistics collected for ${esc(teamName)} yet.`
      }</p>`;

  // No data-anchor: the roster is a grid, so binding to the clicked card's row
  // would open the panel at arbitrary heights. An inspector belongs in one
  // predictable spot — the frame script places anchorless drawers at the top
  // of the visible slice. Match drawers keep their row anchor: the schedule is
  // a full-width list where "beside the row you clicked" reads naturally.
  const close = `data-act="select-player" data-payload='{"player":null}'`;
  return `<button type="button" class="dr-veil" ${close} aria-label="Close player details"></button>
    <aside class="drawer" role="dialog" aria-label="${esc(name)} season details" data-close="select-player" data-close-payload='{"player":null}'>
      <div class="dr-head">
        ${number ? `<span class="dr-no">${esc(number)}</span>` : ""}
        <div><h2>${esc(name)}</h2><p>${esc(teamName)} · ${season} season</p></div>
        <button type="button" class="dr-x" ${close} aria-label="Close">✕</button>
      </div>
      ${bioBlock}${tenureBlock}${body}
      <p class="dr-foot">From the programme&#39;s published ${line ? "season statistics" : "roster"}.</p>
    </aside>`;
}

/** The match drawer: the fixture's published box score. Opens from a ledger
 *  row or the matrix's selection card; closes from the veil, the ✕, or Escape.
 *  A fixture without a collected box score still opens — the drawer then says
 *  exactly why there is nothing behind it. */
function matchDrawer(
  fixtureId: string,
  file: FixturesFile,
  matches: MatchesFile | undefined,
  names: Map<string, string>,
): string {
  const f = file.fixtures.find((x) => x.id === fixtureId);
  if (!f) return "";
  const detail = matches?.matches[fixtureId];
  const played = isPlayed(f);

  const close = `data-act="open-fixture" data-payload='{"fixture":null}'`;
  const homeName = displayName(f.home, names);
  const awayName = displayName(f.away, names);

  // Sides in home/away order when proven; otherwise as the page served them.
  const hi = detail?.home_index;
  const oriented = hi === 0 || hi === 1;
  const sides: { team: MatchTeam; index: number }[] = detail
    ? oriented
      ? [
          { team: detail.teams[hi] as MatchTeam, index: hi },
          { team: detail.teams[1 - hi] as MatchTeam, index: 1 - hi },
        ]
      : detail.teams.map((team, index) => ({ team, index }))
    : [];
  const sideAbbr = (i: number): string => {
    const t = sides[i]?.team;
    return t?.abbr ?? monogram(t?.name ?? "");
  };
  // Map a served-side index (scoring/cards reference these) to drawer order.
  const drawerSide = (served: number | undefined): number | undefined => {
    const at = sides.findIndex((s) => s.index === served);
    return at === -1 ? undefined : at;
  };

  const scoreRows = oriented
    ? [
        { name: homeName, score: f.home_score },
        { name: awayName, score: f.away_score },
      ]
    : played && typeof f.home_score === "number"
      ? [
          { name: homeName, score: f.home_score },
          { name: awayName, score: f.away_score },
        ]
      : [
          { name: homeName, score: undefined },
          { name: awayName, score: undefined },
        ];
  const best = Math.max(...scoreRows.map((r) => r.score ?? -1));
  const head = `<div class="dr-head mhead">
      <div class="mteams">${scoreRows
        .map(
          (r) =>
            `<div class="mrow${typeof r.score === "number" && r.score === best && scoreRows.some((o) => o.score !== r.score) ? " win" : ""}"><span>${esc(r.name)}</span><b>${typeof r.score === "number" ? r.score : "–"}</b></div>`,
        )
        .join("")}</div>
      <button type="button" class="dr-x" ${close} aria-label="Close">✕</button>
    </div>
    <div class="dr-bio">${[
      `${fmtDate(f.date)} ${f.date.slice(0, 4)}`,
      played ? "Final" : f.time ? `Kickoff ${fmtTime(f.time)}` : "Scheduled",
      detail?.stadium ?? f.venue,
      typeof detail?.attendance === "number" ? `${detail.attendance} attended` : undefined,
    ]
      .filter(Boolean)
      .map((v) => esc(v))
      .join(" · ")}</div>`;

  const sections: string[] = [];

  if (detail && sides.length === 2) {
    const periodCount = Math.max(...sides.map((s) => s.team.periods.length));
    if (periodCount > 0) {
      const label = (i: number): string => (i < 2 ? String(i + 1) : i === 2 ? "OT" : `${i - 1}OT`);
      sections.push(`<div class="dr-sec">Score by period</div>
        <table class="pline"><thead><tr><th></th>${Array.from({ length: periodCount }, (_, i) => `<th>${label(i)}</th>`).join("")}<th>T</th></tr></thead>
        <tbody>${sides
          .map(
            (s, i) =>
              `<tr><th scope="row">${esc(sideAbbr(i))}</th>${Array.from(
                { length: periodCount },
                (_, p) => `<td>${s.team.periods[p] ?? ""}</td>`,
              ).join("")}<td><b>${s.team.score ?? "–"}</b></td></tr>`,
          )
          .join("")}</tbody></table>`);
    }

    const scoring = detail.scoring ?? [];
    if (scoring.length) {
      sections.push(
        `<div class="dr-sec">Scoring</div><div class="evs">${scoring
          .map((s) => {
            const at = drawerSide(s.team);
            const cls = at === 0 ? "h" : at === 1 ? "a" : "";
            return `<div class="ev ${cls}"><b>${matchMinute(s.time) || "–"}</b><span class="who">${esc(s.scorer)}${
              s.assist ? `<em>assist ${esc(s.assist)}</em>` : ""
            }</span></div>`;
          })
          .join("")}</div>`,
      );
    }

    const cards = detail.cards ?? [];
    if (cards.length) {
      sections.push(
        `<div class="dr-sec">Cautions</div><div class="evs">${cards
          .map((c) => {
            const at = drawerSide(c.team);
            const cls = at === 0 ? "h" : at === 1 ? "a" : "";
            // A card whose colour the page did not mark stays neutral — the
            // source being unreadable is not evidence of a yellow.
            const [swatch, label] =
              c.type === "red"
                ? ["r", "Red card"]
                : c.type === "yellow"
                  ? ["y", "Yellow card"]
                  : ["u", "Card"];
            return `<div class="ev ${cls}"><b>${matchMinute(c.time) || "–"}</b><span class="who"><i class="cs ${swatch}" title="${label}"></i>${esc(c.player)}</span></div>`;
          })
          .join("")}</div>`,
      );
    }

    const duels: { key: keyof MatchTeam; label: string }[] = [
      { key: "shots", label: "Shots" },
      { key: "sog", label: "On target" },
      { key: "saves", label: "Saves" },
      { key: "corners", label: "Corners" },
      { key: "fouls", label: "Fouls" },
      { key: "offsides", label: "Offsides" },
    ];
    const duelRows = duels
      .map(({ key, label }) => {
        const a = sides[0]?.team[key];
        const b = sides[1]?.team[key];
        if (typeof a !== "number" || typeof b !== "number") return "";
        const top = Math.max(a, b, 1);
        return `<div class="duel"><b>${a}</b><div class="db l"><span style="width:${((a / top) * 100).toFixed(1)}%"></span></div><span class="dn">${label}</span><div class="db r"><span style="width:${((b / top) * 100).toFixed(1)}%"></span></div><b>${b}</b></div>`;
      })
      .filter(Boolean)
      .join("");
    if (duelRows) {
      sections.push(`<div class="dr-sec">Team statistics</div>
        <div class="duel head"><b>${esc(sideAbbr(0))}</b><span class="dn"></span><b>${esc(sideAbbr(1))}</b></div>
        ${duelRows}`);
    }

    const keeperRows = sides
      .flatMap((s, i) =>
        (s.team.keepers ?? []).map(
          (k) =>
            `<div class="ev ${i === 0 ? "h" : "a"}"><b>${esc(sideAbbr(i))}</b><span class="who">${esc(k.name)}<em>${[
              typeof k.saves === "number" ? `${k.saves} saved` : undefined,
              typeof k.goals_against === "number" ? `${k.goals_against} conceded` : undefined,
              typeof k.minutes === "number" ? `${k.minutes}&prime;` : undefined,
            ]
              .filter(Boolean)
              .join(" · ")}</em></span></div>`,
        ),
      )
      .join("");
    if (keeperRows) {
      sections.push(`<div class="dr-sec">Goalkeepers</div><div class="evs">${keeperRows}</div>`);
    }

    // The play-by-play: the box score's own narration, folded one period at a
    // time. Lineup listings and start/end markers are structural rows whose
    // information the period grouping already carries, so they are not rows
    // here — every other event renders verbatim, typed or not.
    const plays = (detail.plays ?? []).filter((p) => p.type !== "lineup" && p.type !== "period");
    if (plays.length) {
      const periods: { token: string; plays: MatchPlay[] }[] = [];
      for (const p of plays) {
        const last = periods[periods.length - 1];
        if (last && last.token === p.period) last.plays.push(p);
        else periods.push({ token: p.period, plays: [p] });
      }
      const periodName = (token: string): string =>
        token === "SO"
          ? "Shootout"
          : token === "3"
            ? "Overtime"
            : token === "4"
              ? "Overtime 2"
              : `Period ${token}`;
      // Running scores are stored in served-team order; the drawer reads them
      // in its own home-first order.
      const runningScore = (s: [number, number] | undefined): string =>
        s ? `<span class="ps">${s[sides[0]?.index ?? 0]}–${s[sides[1]?.index ?? 1]}</span>` : "";
      const playRow = (p: MatchPlay): string => {
        const at = drawerSide(p.team);
        const cls = at === 0 ? "h" : at === 1 ? "a" : "";
        const swatch =
          p.type === "yellow"
            ? `<i class="cs y" title="Yellow card"></i>`
            : p.type === "red"
              ? `<i class="cs r" title="Red card"></i>`
              : "";
        return `<div class="ev ${cls}${p.type === "goal" ? " gl" : ""}"><b>${matchMinute(p.clock) || "–"}</b><span class="who">${swatch}${esc(p.text)}${runningScore(p.score)}</span></div>`;
      };
      sections.push(
        `<div class="dr-sec">Play by play</div>${periods
          .map(
            (g) =>
              `<details class="pbp"><summary>${esc(periodName(g.token))} · ${g.plays.length} play${
                g.plays.length === 1 ? "" : "s"
              }</summary><div class="evs">${g.plays.map(playRow).join("")}</div></details>`,
          )
          .join("")}`,
      );
    } else if (played) {
      sections.push(`<p class="dr-note dim">No play-by-play collected for this match.</p>`);
    }
  } else if (played) {
    const reason = matches?.missing?.[fixtureId];
    sections.push(
      `<p class="dr-note">${
        reason
          ? `No box score collected — ${esc(reason)}`
          : `No box score collected for this match yet. A re-collect of the ${file.season} season fetches it.`
      }</p>`,
    );
  } else {
    sections.push(`<p class="dr-note">Not played yet.</p>`);
  }

  const officials =
    detail?.officials?.length && sections.length
      ? `<p class="dr-note dim">${detail.officials.map((o) => esc(o)).join(" · ")}</p>`
      : "";
  const foot = detail ? `<p class="dr-foot">From the programme&#39;s published box score.</p>` : "";
  return `<button type="button" class="dr-veil" ${close} aria-label="Close match details"></button>
    <aside class="drawer" role="dialog" aria-label="Match details" data-close="open-fixture" data-close-payload='{"fixture":null}'
      data-anchor='${esc(JSON.stringify({ fixture: fixtureId }))}'>
      ${head}${sections.join("")}${officials}${foot}
    </aside>`;
}

/** The conference lens's roster section: comparable counts per programme, and
 *  a stacked position-mix bar. Names appear only after choosing a team. */
function rosterBalance(file: FixturesFile, rosters: RostersFile): string {
  const teams = [...file.programmes].sort((a, b) => a.name.localeCompare(b.name));
  const rows = teams
    .map((t) => {
      const r = rosters.rosters[t.slug];
      const open = `<button type="button" class="open" data-act="select-lens" data-payload='${esc(
        JSON.stringify({ team: t.slug }),
      )}' aria-label="Open ${esc(t.name)} roster">
        <span class="cd2">${esc(t.abbr ?? monogram(t.name))}</span><span class="tn2">${esc(t.name)}</span></button>`;
      if (!r?.players.length) {
        return `<tr><td>${open}</td><td class="dim">—</td><td class="dim" colspan="4">not collected</td><td></td><td></td></tr>`;
      }
      const counts = POSITIONS.map(
        (p) => r.players.filter((x) => posKey(x.position) === p.key).length,
      );
      const total = r.players.length;
      const unlisted = total - counts.reduce((a, b) => a + b, 0);
      const hasPos = total > unlisted;
      const seg = (cls: string, n: number, title: string) => {
        if (!n) return "";
        const pct = (n / total) * 100;
        return `<span class="${cls}" style="width:${pct.toFixed(2)}%" title="${esc(title)}: ${n}">${
          pct >= 10 ? n : ""
        }</span>`;
      };
      const mix = hasPos
        ? `<div class="cmix">${POSITIONS.map((p, i) => seg(p.key, counts[i] ?? 0, p.head)).join("")}${seg(
            "un",
            unlisted,
            "Position not published",
          )}</div>`
        : `<div class="cmix unp" title="positions not published"></div>`;
      const cells = counts
        .map((n) =>
          hasPos ? `<td>${n || '<span class="dim">0</span>'}</td>` : `<td class="dim">—</td>`,
        )
        .join("");

      // Experience is read per team, not just compared — the class ramp
      // carries its counts inline, seniors leftmost and deepest.
      const clsCount = new Map<string, number>();
      let clsUnknown = 0;
      for (const p of r.players) {
        const c = classInfo(p.class_year);
        if (c) clsCount.set(c.key, (clsCount.get(c.key) ?? 0) + 1);
        else clsUnknown += 1;
      }
      const cmix = `<div class="cmix">${CLASSES.map((c) =>
        seg(c.key, clsCount.get(c.key) ?? 0, c.head),
      ).join("")}${seg("un", clsUnknown, "Class not published")}</div>`;

      return `<tr><td>${open}</td><td><b>${total}</b></td>${cells}<td>${mix}</td><td>${cmix}</td></tr>`;
    })
    .join("");

  // The colour keys ARE the bar columns' headers — each sits directly above
  // the bars it decodes, where the eye actually asks what the colours mean.
  // The hatched note only appears when some programme left something
  // unpublished.
  const hatched = rows.includes('class="un"') || rows.includes("cmix unp");
  const posKeyHead = `<span class="key rk">${POSITIONS.map(
    (p) => `<span><i class="${p.key}"></i>${p.abbr}</span>`,
  ).join("")}</span>`;
  const classKeyHead = `<span class="key rk">${CLASSES.map(
    (c) => `<span><i class="${c.key}"></i>${c.abbr}</span>`,
  ).join("")}</span>`;
  return `
    <div class="sec"><h2>Roster balance</h2><span class="count">Select a team for players</span></div>
    <div class="mx-wrap"><table class="rbal">
      <thead><tr><th>Team</th><th>Players</th>${POSITIONS.map((p) => `<th>${p.abbr}</th>`).join("")}<th>${posKeyHead}</th><th>${classKeyHead}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    ${hatched ? `<div class="rbal-foot"><span>Hatched — not published by the programme.</span></div>` : ""}`;
}

export function composeBoard(input: BoardInput): string {
  const { fixtures: file, rosters, today } = input;
  const slugs = file.programmes.map((p) => p.slug).sort();
  const names = new Map(file.programmes.map((p) => [p.slug, p.name]));

  // A single-programme season IS that team's season: render the team lens
  // without requiring a stored scope. The conference framing only exists once
  // there is more than one team to relate.
  const single = file.programmes.length === 1;
  const team = input.team ?? (single ? file.programmes[0]?.slug : undefined);

  const mine = team
    ? file.fixtures.filter((f) => f.home === team || f.away === team)
    : file.fixtures;
  const shown = [...mine].sort((a, b) => a.date.localeCompare(b.date));

  const played = shown.filter(isPlayed).length;
  const conference = shown.filter((f) => f.conference_game).length;
  const roster = team ? rosters?.rosters[team] : undefined;
  const teamStats = team ? input.stats?.teams[team] : undefined;
  const rosterCount = team
    ? (roster?.players.length ?? 0)
    : rosters
      ? Object.values(rosters.rosters).reduce((n, r) => n + r.players.length, 0)
      : 0;
  const matchGaps = Object.keys(input.matches?.missing ?? {}).length;
  const gaps =
    (file.missing?.length ?? 0) +
    (rosters?.missing?.length ?? 0) +
    (input.stats?.missing?.length ?? 0) +
    matchGaps;

  const subject = team ? displayName(team, names) : file.conference;

  const lens = single
    ? ""
    : `<div class="lens" role="tablist">
      <button role="tab" aria-selected="${team ? "false" : "true"}" data-act="select-lens" data-payload='{"team":null}'>${esc(file.conference)}</button>
      ${file.programmes
        .map(
          (p) =>
            `<button role="tab" aria-selected="${team === p.slug ? "true" : "false"}" data-act="select-lens" data-payload='${esc(
              JSON.stringify({ team: p.slug }),
            )}'>${esc(p.abbr ?? monogram(p.name))}</button>`,
        )
        .join("")}
    </div>`;

  // The masthead year steps through whatever the archive holds for this
  // gender: one collected season renders as plain text, more grow chevrons.
  const seasonOptions = (input.seasons ?? [])
    .filter((s) => s.gender === file.gender && s.conference === conferenceSlug(file.conference))
    .sort((a, b) => a.season - b.season);
  const at = seasonOptions.findIndex((s) => s.season === file.season);
  const step = (
    target: { season: number; gender: string; conference: string } | undefined,
    glyph: string,
  ): string =>
    target === undefined
      ? ""
      : `<button class="yr" data-act="select-season" data-payload='${esc(
          JSON.stringify(target),
        )}' aria-label="View the ${target.season} season">${glyph}</button>`;
  const seasonCtl =
    seasonOptions.length > 1 && at >= 0
      ? `<span class="seasons">${step(seasonOptions[at - 1], "‹")}<span class="season num">${file.season}</span>${step(seasonOptions[at + 1], "›")}</span>`
      : `<span class="season num">${file.season}</span>`;

  // One header row carries everything the old dek line said better: the
  // gender as a small tag beside the season — the programme count is
  // self-evident from the chips and matrix, and the collected stamp lives in
  // the panel head's byline (see stampPanel in index.ts), not on the sheet.
  const head = `
    <div class="mast">
      <h1>${esc(subject)}</h1>
      ${seasonCtl}
      <span class="gen">${file.gender === "men" ? "Men" : "Women"}</span>
      <span class="sp"></span>
      ${played === 0 ? '<span class="stamp">pre-season</span>' : ""}
    </div>
    ${lens}`;

  const notices = [
    file.membership_extrapolated
      ? `<p class="note"><b>Membership carried forward.</b> The membership record is authored through an earlier season, so this ${file.season} member list is the most recent published one carried forward — well-founded, but not yet cited to a ${file.season} source.</p>`
      : "",
    gaps > 0
      ? `<p class="note flag"><b>${gaps} collection gap${gaps === 1 ? "" : "s"}.</b> ${[
          ...(file.missing ?? []).map((m) => `${esc(displayName(m, names))} (schedule)`),
          ...(rosters?.missing ?? []).map((m) => `${esc(displayName(m, names))} (roster)`),
          ...(input.stats?.missing ?? []).map((m) => `${esc(displayName(m, names))} (stats)`),
          ...(matchGaps ? [`${matchGaps} match box score${matchGaps === 1 ? "" : "s"}`] : []),
        ].join(" · ")} — named rather than dropped; a re-collect retries them.</p>`
      : "",
    played === 0 && shown.length
      ? `<p class="note">Pre-season is a valid state — a published ${file.season} schedule and roster with zero played matches is a complete collection.</p>`
      : "",
  ].join("");

  const tally = `
    <div class="tally">
      <div><b class="num">${shown.length}</b><span>Matches</span></div>
      <div><b class="num">${conference}</b><span>Conference</span></div>
      <div><b class="num">${rosterCount}</b><span>${team ? "Squad" : "Roster players"}</span></div>
      ${gaps ? `<div class="warn"><b class="num">${gaps}</b><span>Gaps</span></div>` : `<div><b class="num">${played}</b><span>Played</span></div>`}
    </div>`;

  // A conference of teams reads as a matrix — who plays whom, matchday by
  // matchday. One team's schedule reads as a ledger. Both are the subject's
  // native artifact; neither is a dashboard.
  const asMatrix = !team && file.programmes.length > 1 && shown.length > 0;
  const ledger = asMatrix
    ? matrix(file, shown, names, today)
    : shown.length
      ? `<div class="sec"><h2>Schedule</h2><span class="count">${shown.length} listed</span></div>
       <div class="led">${shown.map((f) => ledgerRow(f, names, slugs, team, input.matches?.matches[f.id])).join("")}</div>`
      : `<div class="sec"><h2>Schedule</h2></div>
       <p class="note">No ${file.season} schedule collected${team ? ` for ${esc(subject)}` : ""}. Ask in the Touchline chat to collect it — the sites publish schedule archives with results back to 2016.</p>`;

  const rosterBlock = team
    ? roster?.players.length
      ? teamRosterBlock(roster, teamStats, file.season, input.rosterHistory ?? [])
      : `<div class="sec"><h2>Roster</h2></div><p class="note">No roster collected for ${esc(subject)}.</p>`
    : asMatrix && rosters
      ? rosterBalance(file, rosters)
      : "";

  // One drawer at a time; the selection state enforces the exclusivity.
  const drawer = input.fixture
    ? matchDrawer(input.fixture, file, input.matches, names)
    : team && input.player
      ? playerDrawer(
          input.player,
          roster,
          teamStats,
          subject,
          file.season,
          played,
          input.rosterHistory ?? [],
          names,
        )
      : "";

  // The matrix header is itself the calendar, so the rail would say the same
  // thing twice; the rail stays where the ledger's dates run vertically.
  // A team page leads with its people: roster first, then the schedule.
  const body = team ? `${rosterBlock}${ledger}` : `${ledger}${rosterBlock}`;
  return page(
    `${head}${asMatrix ? "" : rail(shown, today, team)}${tally}${notices}${body}${drawer}`,
  );
}
