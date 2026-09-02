#!/usr/bin/env node
// Guards the docs against the drift classes a build alone does not catch:
// LLM-output corruption (angle-bracket placeholders the generator strips,
// leaving blank commands), stale claims that fall out of sync with the rib
// source (renamed workflows/keys/gates, retired schema tags and filenames),
// hardcoded counts the code owns, and glossary/rail rot. Run after
// `astro build`, against docs/dist/llms-full.txt and the repo source.

import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const docsDir = join(scriptDir, "..");
const repoRoot = join(docsDir, "..");
const distLlms = join(docsDir, "dist", "llms-full.txt");
const contentDir = join(docsDir, "src", "content", "docs");
const archFile = join(docsDir, "ARCHITECTURE.md");
const canonFile = join(repoRoot, "pipeline", "src", "canon.py");
const workflowsDir = join(repoRoot, "workflows");
const promptsDir = join(repoRoot, "prompts");

const failures = [];
const fail = (msg) => failures.push(msg);

// --- gather inputs -----------------------------------------------------------

if (!existsSync(distLlms)) {
  console.error(`check-docs-drift: ${relative(repoRoot, distLlms)} missing — run \`bun run build\` first.`);
  process.exit(1);
}
const llms = readFileSync(distLlms, "utf8");

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (/\.mdx?$/.test(entry.name)) out.push(full);
  }
  return out;
}
const sourceDocs = [...walk(contentDir), archFile].filter(existsSync);

// --- 1. obsolete terms (source pages + generated output) ---------------------

// [pattern, message, allowContext?] — a line matching allowContext is exempt,
// so migration docs may name the legacy fixtures tag while describing the
// /1 -> /2 upgrade without presenting it as current.
const FORBIDDEN = [
  [/\b\d{4}-(?:men|women)\.json\b/, "retired unsharded season filename (season files are conference-sharded, e.g. {season}-{gender}-{conference}.json)"],
  [/touchline\.fixtures\/1(?![\d])/, 'retired schema tag "touchline.fixtures/1" presented as current (fixtures are /2; naming it in migration context requires "legacy"/"upgrade" wording or the /2 tag on the same line)', /touchline\.fixtures\/2|legacy|upgrad/i],
  [/\bem dash—/, "malformed em-dash reference"],
];

function scanLines(label, text) {
  const lines = text.split("\n");
  for (const [re, msg, allow] of FORBIDDEN) {
    lines.forEach((line, i) => {
      if (re.test(line) && !(allow && allow.test(line))) fail(`${label}:${i + 1}: ${msg} — ${line.trim()}`);
    });
  }
}
for (const file of sourceDocs) scanLines(relative(repoRoot, file), readFileSync(file, "utf8"));
scanLines("dist/llms-full.txt", llms);

// --- 2. em dashes in docs prose (family voice law) ---------------------------
// Docs-site prose bans the em dash; code fences may carry whatever the code
// carries, so fenced blocks are skipped.

for (const file of sourceDocs.filter((f) => f !== archFile)) {
  let fenced = false;
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (/^\s*```/.test(line)) fenced = !fenced;
    if (!fenced && line.includes("—")) {
      fail(`${relative(repoRoot, file)}:${i + 1}: em dash in docs prose (use a comma, colon, parentheses, or two sentences) — ${line.trim()}`);
    }
  });
}

// --- 3. angle-bracket placeholders left in source ----------------------------

const ANGLE = /<(conference|season|gender|slug|school|year|player|id|path|data-home|focus)>/;
for (const file of sourceDocs) {
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (ANGLE.test(line)) {
      fail(`${relative(repoRoot, file)}:${i + 1}: angle-bracket placeholder (use curly form, e.g. {slug}) — ${line.trim()}`);
    }
  });
}

// --- 4. documented sets match the source ------------------------------------

const WORKFLOWS = [
  "touchline-collect",
  "touchline-backfill",
  "touchline-report",
  "touchline-player-profile",
  "data-integrity",
];
if (existsSync(workflowsDir)) {
  const onDisk = readdirSync(workflowsDir)
    .filter((f) => f.endsWith(".yml"))
    .map((f) => f.replace(/\.yml$/, ""));
  for (const wf of onDisk) {
    if (!WORKFLOWS.includes(wf)) fail(`workflow "${wf}" exists in workflows/ but is missing from this script's WORKFLOWS golden set.`);
  }
  for (const wf of WORKFLOWS) {
    if (!onDisk.includes(wf)) fail(`workflow "${wf}" is in the golden set but no longer exists in workflows/.`);
  }
}
for (const wf of WORKFLOWS) {
  if (!llms.includes(wf)) fail(`workflow "${wf}" is not documented in llms-full.txt.`);
}

const KEYS = ["rib:touchline:board"];
for (const key of KEYS) {
  if (!llms.includes(key)) fail(`snapshot key "${key}" is not documented in llms-full.txt.`);
}

const SCHEMAS = [
  "touchline.fixtures/2",
  "touchline.rosters/1",
  "touchline.stats/1",
  "touchline.matches/1",
  "touchline.digest/1",
  "touchline.research/1",
  "touchline.report-narrative/4",
  "touchline.player-profile/1",
  "touchline.coverage/1",
];
for (const tag of SCHEMAS) {
  if (!llms.includes(tag)) fail(`versioned schema tag "${tag}" is not documented in llms-full.txt.`);
}

const GATES = ["validate-research", "validate-verified", "validate-narrative"];
for (const gate of GATES) {
  if (!llms.includes(gate)) fail(`gate "${gate}" is not documented in llms-full.txt.`);
}

if (existsSync(promptsDir)) {
  for (const p of readdirSync(promptsDir).filter((f) => f.endsWith(".md"))) {
    const name = p.replace(/\.md$/, "");
    if (!llms.includes(name)) fail(`prompt contract "${name}" (prompts/${p}) is not documented in llms-full.txt.`);
  }
}

// --- 5. glossary golden set --------------------------------------------------
// Terms the site's vocabulary hangs on. Each must survive into llms-full.txt;
// a renamed concept breaks here instead of orphaning the glossary.

const GLOSSARY = [
  "data home",
  "programme",
  "fixture",
  "coverage",
  "payload trap",
  "adjudication",
  "membership window",
  "digest",
  "finding",
  "identity binding",
  "attested_uncaptured",
  "unswept",
  "season rail",
];
for (const term of GLOSSARY) {
  if (!llms.toLowerCase().includes(term.toLowerCase())) {
    fail(`glossary term "${term}" is not documented in llms-full.txt.`);
  }
}

// --- 6. tutorials rail and reading paths ------------------------------------
// The syllabus routes by slug; a renamed rail page must break CI, not the map.

const RAIL = [
  "first-season-board",
  "read-a-raw-page",
  "trace-an-identity",
  "interrogate-the-digest",
  "break-a-gate",
  "research-with-receipts",
  "capstone-scout-a-season",
];
const tutorialsDir = join(contentDir, "tutorials");
if (existsSync(tutorialsDir)) {
  const stops = readdirSync(tutorialsDir)
    .filter((f) => /\.mdx?$/.test(f))
    .map((f) => f.replace(/\.mdx?$/, ""));
  for (const stop of RAIL) {
    if (!stops.includes(stop)) fail(`rail stop "${stop}" has no page in tutorials/.`);
  }
  const syllabusFile = ["syllabus.md", "syllabus.mdx"].map((f) => join(tutorialsDir, f)).find(existsSync);
  if (!syllabusFile) {
    fail("tutorials/syllabus is missing.");
  } else {
    const syllabus = readFileSync(syllabusFile, "utf8");
    for (const stop of RAIL) {
      if (!syllabus.includes(stop)) fail(`syllabus does not route to rail stop "${stop}".`);
    }
  }
}

// --- 7. computed counts the code owns ----------------------------------------
// Never trust a hardcoded adjudication count: count the entries in canon.py's
// ADJUDICATIONS dict and require any "N adjudication(s)" claim to match.

if (existsSync(canonFile)) {
  const canon = readFileSync(canonFile, "utf8");
  const block = canon.match(/ADJUDICATIONS[^=]*=\s*\{([\s\S]*?)\n\}/);
  if (!block) {
    fail("could not locate the ADJUDICATIONS dict in pipeline/src/canon.py — update this script's parser.");
  } else {
    const count = (block[1].match(/"classification":/g) || []).length;
    const claimRe = /\b(\d+)\s+adjudications?\b/gi;
    for (const file of sourceDocs) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(claimRe)) {
        if (Number(m[1]) !== count) {
          fail(`${relative(repoRoot, file)}: claims "${m[0]}" but pipeline/src/canon.py holds ${count} adjudication entries.`);
        }
      }
    }
  }
} else {
  console.warn(`check-docs-drift: ${relative(repoRoot, canonFile)} not found — skipping adjudication count cross-check.`);
}

// --- report ------------------------------------------------------------------

if (failures.length > 0) {
  console.error(`\ncheck-docs-drift: ${failures.length} issue(s) found:\n`);
  for (const f of failures) console.error(`  - ${f}`);
  console.error("");
  process.exit(1);
}

console.log(
  `check-docs-drift: ok (${sourceDocs.length} source pages; ${WORKFLOWS.length} workflows, ${KEYS.length} keys, ${SCHEMAS.length} schema tags, ${GATES.length} gates, ${GLOSSARY.length} glossary terms, ${RAIL.length} rail stops checked; no stripped placeholders, em dashes, or stale counts).`,
);
