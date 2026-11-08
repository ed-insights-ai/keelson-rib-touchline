// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

// The daily cadence script (bin/touchline-collect-cadence.sh) and its
// installed shim, run for real under /bin/sh against a throwaway world: a
// temp HOME carrying the keelson rib config, a temp package dir holding the
// script, a temp git data home with one board file set and a bare upstream,
// a temp site checkout with a bare upstream, and a fakes directory first on
// the script's PATH standing in for keelson, bun and just. git, jq, tar and
// zstd are the real ones (the archive scenarios skip by name when zstd is not
// on PATH). Each scenario asserts on the run record JSON line, the cadence
// log, and the git state the run leaves behind.

import { describe, expect, test } from "bun:test";
import { existsSync, realpathSync } from "node:fs";
import { chmod, mkdir, mkdtemp, readdir, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { packageDir } from "../src/datahome.ts";

const rib = packageDir();
const SEASON = "2026";
const GENDER = "men";
const LAYERS = ["fixtures", "rosters", "stats", "matches"] as const;
const BUILD = "2026-09-06T06:31:00Z";
// The journal legs are polled by the script's `capped` every 5s plus a 1s
// stamp settle per leg; a loop run with a publish needs the long timeout.
const LOOP_TIMEOUT = 120_000;
// The archive step needs a real zstd; ubuntu-latest ships one, a machine
// without it skips those scenarios under a name that says so.
const ZSTD = Bun.which("zstd");
const NEEDS_ZSTD = ZSTD ? "" : " [skipped: zstd is not on PATH]";

// Board file shape the fake collect rewrites: the churn scenario rewrites
// only the collected_at line, so the initial file must carry the same layout.
// The board names its conference and programmes the way the real one does
// (data/fixtures/<season>-<gender>-<conf>.json: .conference, .programmes[].slug),
// which the archive step joins against coverage.json for a cell's conference.
function board(lc: string, stamp: string, rows: string, season: string = SEASON): string {
  return (
    `{\n  "collected_at": "${stamp}",\n  "conference": "${lc.toUpperCase()}",\n` +
    `  "season": ${season},\n  "gender": "${GENDER}",\n` +
    `  "programmes": [{"slug": "${lc}-alpha"}, {"slug": "${lc}-beta"}],\n  "rows": [${rows}]\n}\n`
  );
}
function initialBoard(lc: string): string {
  return board(lc, "2026-01-01T00:00:00Z", "");
}

// Local calendar date, the way the script's `date +%Y-%m-%d` names the
// archive directory, and ISO weekday the way `date +%u` reports it.
function today(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}
function weekday(): number {
  return new Date().getDay() || 7;
}

interface RunResult {
  code: number;
  stdout: string;
  stderr: string;
}

async function run(cmd: string[], env: Record<string, string>, cwd?: string): Promise<RunResult> {
  const proc = Bun.spawn(cmd, { cwd, env, stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  return { code: await proc.exited, stdout, stderr };
}

// The project id keelson assigns the d2-soccer data home; the status envelope
// carries it, not the name, so the cadence matches on workingDir instead.
const PROJECT_ID = "0f063a68-64bd-4055-9993-04426cc43e6f";

const FAKE_KEELSON = `#!/bin/sh
# Fake keelson. \`workflow status --json\` answers from CADENCE_FAKE_BUSY
# ("<workflow>:<runId>:<startedAt>") with the keelson 0.103.0 envelope shape,
# {"ok":true,"data":{"runs":[...]}} where each run is a workflowRunSummary
# (runId, workflowName, status, startedAt, completedAt, error, conversationId,
# projectId, workingDir, worktreePath, worktreeBase, origin, ribId), otherwise
# an empty run list. \`workflow run touchline-collect ... --inputs conference=X\`
# writes the data home the way the plan says (CADENCE_FAKE_PLAN is
# "CONF=changed,CONF=churn,CONF=failed,CONF=locked"; unnamed conferences are
# changed) and prints the JSON line the cadence parses from its last line.
# CADENCE_FAKE_SIDE_WRITE=<path> makes the failed and locked actions also
# write that path under the data home: another writer's file landing while
# this collect runs, which a rollback must leave alone.
# CADENCE_FAKE_SERVER_DOWN=1 makes every call answer the real NO_SERVER
# envelope (exit 3) until \`keelson start\` brings the fake server up (a marker
# beside the fake log); CADENCE_FAKE_START_FAIL=1 makes that start fail.
printf 'keelson %s\\n' "$*" >>"$CADENCE_FAKE_LOG"
home="$TOUCHLINE_DATA_HOME"
if [ -n "\${CADENCE_FAKE_SERVER_DOWN:-}" ] && [ ! -f "$CADENCE_FAKE_LOG.up" ]; then
  if [ "$1" = "start" ]; then
    if [ -n "\${CADENCE_FAKE_START_FAIL:-}" ]; then
      printf 'keelson start: the server did not come up\\n'; exit 1
    fi
    : >"$CADENCE_FAKE_LOG.up"
    printf 'keelson server running at http://127.0.0.1:4100\\n'
    exit 0
  fi
  printf '{"ok":false,"error":"workflow status requires a running server; start it with keelson start first","code":"NO_SERVER"}\\n'
  exit 3
fi
if [ "$1 $2" = "workflow status" ]; then
  if [ -n "\${CADENCE_FAKE_BUSY:-}" ]; then
    bw=$(printf '%s' "$CADENCE_FAKE_BUSY" | cut -d: -f1)
    bid=$(printf '%s' "$CADENCE_FAKE_BUSY" | cut -d: -f2)
    bat=$(printf '%s' "$CADENCE_FAKE_BUSY" | cut -d: -f3-)
    printf '{"ok":true,"data":{"runs":[{"runId":"%s","workflowName":"%s","status":"running","startedAt":"%s","completedAt":null,"error":null,"conversationId":null,"projectId":"${PROJECT_ID}","workingDir":"%s","worktreePath":null,"worktreeBase":null,"origin":"manual","ribId":"touchline"}]}}\\n' \\
      "$bid" "$bw" "$bat" "$home"
  else
    printf '{"ok":true,"data":{"runs":[]}}\\n'
  fi
  exit 0
fi
conf=""
for a in "$@"; do case "$a" in conference=*) conf=\${a#conference=} ;; esac; done
lc=$(printf '%s' "$conf" | tr '[:upper:]' '[:lower:]')
action=changed
for p in $(printf '%s' "\${CADENCE_FAKE_PLAN:-}" | tr ',' ' '); do
  case "$p" in "$conf="*) action=\${p#*=} ;; esac
done
if [ -n "\${CADENCE_FAKE_SLEEP:-}" ]; then sleep "$CADENCE_FAKE_SLEEP"; fi
stamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
write_board() { # $1 = layer, $2 = rows; the layout test/cadence.test.ts board() writes
  printf '{\\n  "collected_at": "%s",\\n  "conference": "%s",\\n  "season": %s,\\n  "gender": "%s",\\n  "programmes": [{"slug": "%s-alpha"}, {"slug": "%s-beta"}],\\n  "rows": [%s]\\n}\\n' \\
    "$stamp" "$conf" "$TOUCHLINE_SEASON" "$TOUCHLINE_GENDER" "$lc" "$lc" "$2" \\
    >"$home/data/$1/\${TOUCHLINE_SEASON}-\${TOUCHLINE_GENDER}-\${lc}.json"
}
write_churn() { # coverage, raw_html and errors churn on every fetch, never a signal
  # the real layout: one shared coverage.json (touchline.coverage/1, merged,
  # never overwritten: cells keyed <season>/<gender>/<programme>/<layer>),
  # raw pages per programme slug (the fake bun resolves <lc>-alpha,<lc>-beta)
  # named <season>-<gender>-* with a .state.json sidecar each, and one errors
  # file per conference board
  mkdir -p "$home/data/errors"
  for s in alpha beta; do
    d="$home/data/raw_html/\${lc}-$s"
    mkdir -p "$d"
    printf '<html>%s %s</html>\\n' "$s" "$stamp" \\
      >"$d/\${TOUCHLINE_SEASON}-\${TOUCHLINE_GENDER}-schedule.html"
    printf '{"fetched_at":"%s"}\\n' "$stamp" \\
      >"$d/\${TOUCHLINE_SEASON}-\${TOUCHLINE_GENDER}-schedule.state.json"
  done
  cov="$home/data/coverage.json"
  [ -f "$cov" ] || printf '{"schema":"touchline.coverage/1","cells":{}}\\n' >"$cov"
  jq --arg s "$TOUCHLINE_SEASON" --arg g "$TOUCHLINE_GENDER" --arg lc "$lc" --arg at "$stamp" '
    def cell(slug): {season: ($s | tonumber), gender: $g, programme: slug, layer: "matches",
                     state: "complete", collector: "fake", confirmed_at: $at};
    .schema = "touchline.coverage/1" | .updated_at = $at
    | .cells = ((.cells // {})
        + {"\\($s)/\\($g)/\\($lc)-alpha/matches": cell("\\($lc)-alpha"),
           "\\($s)/\\($g)/\\($lc)-beta/matches": cell("\\($lc)-beta")})' "$cov" >"$cov.tmp" \\
    && mv "$cov.tmp" "$cov"
  printf '{"errors":[]}\\n' \\
    >"$home/data/errors/collect-board-\${TOUCHLINE_SEASON}-\${TOUCHLINE_GENDER}-\${lc}.json"
}
side_write() {
  if [ -n "\${CADENCE_FAKE_SIDE_WRITE:-}" ]; then
    mkdir -p "$(dirname "$home/$CADENCE_FAKE_SIDE_WRITE")"
    printf '{\\n  "collected_at": "%s",\\n  "rows": ["side-row"]\\n}\\n' "$stamp" >"$home/$CADENCE_FAKE_SIDE_WRITE"
  fi
}
case "$action" in
  changed)
    for l in fixtures rosters stats matches; do write_board "$l" '"new-row"'; done
    write_churn
    printf 'collect %s: 1 fixture landed\\n' "$conf"
    printf '{"ok":true,"data":{"status":"succeeded"}}\\n'
    ;;
  lost)
    # the collector's named gap: <lc>-alpha could not be fetched, so every
    # layer lists it under missing (the real collector drops its records too)
    for l in fixtures rosters stats matches; do write_board "$l" '"new-row"'; done
    for l in fixtures rosters stats; do
      f="$home/data/$l/\${TOUCHLINE_SEASON}-\${TOUCHLINE_GENDER}-\${lc}.json"
      jq --arg s "\${lc}-alpha" '.missing = [$s]' "$f" >"$f.tmp" && mv "$f.tmp" "$f"
    done
    write_churn
    printf 'collect %s: %s-alpha is a named gap\\n' "$conf" "$lc"
    printf '{"ok":true,"data":{"status":"succeeded"}}\\n'
    ;;
  churn)
    for l in fixtures rosters stats matches; do write_board "$l" ''; done
    write_churn
    printf 'collect %s: nothing new\\n' "$conf"
    printf '{"ok":true,"data":{"status":"succeeded"}}\\n'
    ;;
  failed)
    write_board fixtures '"partial-row"'
    write_churn
    side_write
    printf 'collect %s: boom\\n' "$conf"
    printf '{"ok":false,"code":"E_COLLECT","error":"fake collect blew up"}\\n'
    exit 2
    ;;
  locked)
    # the server's mutation lock refuses at start: HTTP 409, nothing written
    side_write
    printf '{"error":"%s","code":"REQUEST_FAILED"}\\n' \\
      'project ${PROJECT_ID} is locked by run:abc for \\"touchline-backfill\\"'
    exit 1
    ;;
  *) printf 'fake keelson: unknown action %s\\n' "$action" >&2; exit 99 ;;
esac
`;

const FAKE_BUN = `#!/bin/sh
# Fake bun: the three shapes the cadence uses. The membership CLI answers
# from fixed strings; \`bun -e\` (resolve_programmes) reads RESOLVE_CONF; the
# journal run touches the journal + validation files for each key.
printf 'bun %s\\n' "$*" >>"$CADENCE_FAKE_LOG"
if [ "$1" = "run" ] && [ "$2" = "journal" ] && [ -n "\${TOUCHLINE_RECOLLECTED:-}" ]; then
  printf 'bun env TOUCHLINE_RECOLLECTED=%s\\n' "$TOUCHLINE_RECOLLECTED" >>"$CADENCE_FAKE_LOG"
fi
case "$1" in
  *resolve-membership.ts)
    case "$2" in
      conferences) printf '%s\\n' "\${CADENCE_FAKE_CONFERENCES:-GAC LSC}"; exit 0 ;;
      conference) printf 'false %s-alpha,%s-beta\\n' "$3" "$3"; exit 0 ;;
    esac
    ;;
  -e)
    case ",\${CADENCE_FAKE_RESOLVE_FAIL:-}," in
      *",$RESOLVE_CONF,"*)
        printf 'no members resolve for %s %s %s (known: )\\n' \\
          "$RESOLVE_CONF" "$RESOLVE_GENDER" "$RESOLVE_SEASON" >&2
        exit 1 ;;
    esac
    lc=$(printf '%s' "$RESOLVE_CONF" | tr '[:upper:]' '[:lower:]')
    printf 'false %s-alpha,%s-beta\\n' "$lc" "$lc"
    exit 0
    ;;
  run)
    keys=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --conference) keys=$2; shift ;;
        --national) keys=national ;;
      esac
      shift
    done
    if [ -n "\${CADENCE_FAKE_JOURNAL_FAIL:-}" ]; then
      printf 'journal: model call failed\\n'; exit 1
    fi
    for k in $(printf '%s' "$keys" | tr ',' ' '); do
      printf '{"key":"%s","generated":"%s"}\\n' "$k" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \\
        >"$TOUCHLINE_UI_DIR/journal/journal-\${TOUCHLINE_SEASON}-\${TOUCHLINE_GENDER}-$k.json"
      printf '{"ok":true}\\n' \\
        >"$TOUCHLINE_UI_DIR/journal/journal-\${TOUCHLINE_SEASON}-\${TOUCHLINE_GENDER}-$k.validation.json"
    done
    printf 'journal: wrote [%s]\\n' "$keys"
    exit 0
    ;;
esac
printf 'fake bun: unhandled args: %s\\n' "$*" >&2
exit 97
`;

const FAKE_JUST = `#!/bin/sh
# Fake just: records the recipe and writes the built index with the
# touchline-build meta the cadence reads for its build stamp.
printf 'just %s (cwd %s)\\n' "$*" "$(pwd)" >>"$CADENCE_FAKE_LOG"
if [ "$1" != "publish" ]; then printf 'fake just: unknown recipe %s\\n' "$1" >&2; exit 98; fi
if [ -n "\${TOUCHLINE_RECOLLECTED:-}" ]; then
  printf 'just env TOUCHLINE_RECOLLECTED=%s\\n' "$TOUCHLINE_RECOLLECTED" >>"$CADENCE_FAKE_LOG"
fi
if [ -n "\${CADENCE_FAKE_PUBLISH_FAIL:-}" ]; then
  printf 'publish: deployed host assertion FAILED\\n'; exit 1
fi
mkdir -p dist
printf '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Touchline</title><meta name="touchline-build" content="%s"><meta name="description" content="x"></head><body></body></html>\\n' \\
  "\${CADENCE_FAKE_BUILD:-${BUILD}}" >dist/index.html
printf 'publish: gh-pages updated, deployed host asserted\\n'
exit 0
`;

interface Harness {
  root: string;
  home: string;
  pkg: string;
  script: string;
  shim: string;
  data: string;
  dataRemote: string;
  site: string;
  siteRemote: string;
  fakes: string;
  archive: string;
  fakeLog: string;
  logFile: string;
  runsFile: string;
  env: Record<string, string>;
  git(cwd: string, ...args: string[]): Promise<string>;
  cadence(mode: string, extra?: Record<string, string>): Promise<RunResult>;
  log(): Promise<string>;
  calls(): Promise<string>;
  records(): Promise<any[]>;
}

async function writeExec(path: string, body: string): Promise<void> {
  await writeFile(path, body);
  await chmod(path, 0o755);
}

async function makeHarness(): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), "touchline-cadence-"));
  const home = join(root, "home");
  const pkg = join(root, "pkg");
  const data = join(root, "data");
  const dataRemote = join(root, "data-remote.git");
  const site = join(root, "site");
  const siteRemote = join(root, "site-remote.git");
  const fakes = join(root, "fakes");
  const archive = join(root, "archive");
  const fakeLog = join(root, "fake-calls.log");
  const logFile = join(home, ".keelson", "logs", "touchline-collect-cadence.log");
  const runsFile = join(home, ".keelson", "logs", "touchline-cadence-runs.jsonl");

  // git identity and defaults isolated from the machine
  const gitconfig = join(root, "gitconfig");
  await writeFile(
    gitconfig,
    "[user]\n\tname = Cadence Test\n\temail = cadence@test.invalid\n[init]\n\tdefaultBranch = main\n",
  );
  const base: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined) continue;
    if (k.startsWith("TOUCHLINE_") || k.startsWith("CADENCE_FAKE_")) continue;
    base[k] = v;
  }
  const env: Record<string, string> = {
    ...base,
    HOME: home,
    GIT_CONFIG_GLOBAL: gitconfig,
    GIT_CONFIG_NOSYSTEM: "1",
    TOUCHLINE_DATA_HOME: data,
    TOUCHLINE_UI_DIR: site,
    TOUCHLINE_SEASON: SEASON,
    TOUCHLINE_GENDER: GENDER,
    TOUCHLINE_CADENCE_PATH: `${fakes}:${process.env.PATH ?? "/usr/bin:/bin"}`,
    // the archive step is off unless a scenario turns it on (`always`), so a
    // Sunday run of the suite behaves like any other day; its root is a temp
    // dir, never ~/keelson/archive
    TOUCHLINE_ARCHIVE_DAY: "0",
    TOUCHLINE_ARCHIVE_DIR: archive,
    CADENCE_FAKE_LOG: fakeLog,
  };
  const git = async (cwd: string, ...args: string[]): Promise<string> => {
    const r = await run(["git", "-C", cwd, ...args], env);
    if (r.code !== 0) throw new Error(`git ${args.join(" ")} in ${cwd}: ${r.stderr}`);
    return r.stdout.trim();
  };

  // HOME: the keelson rib config the script and the shim resolve the package from
  await mkdir(join(home, ".keelson", "rib-touchline"), { recursive: true });
  await writeFile(
    join(home, ".keelson", "rib-touchline", "config.json"),
    JSON.stringify({ packageDir: pkg, dataDir: site }, null, 2),
  );

  // package dir: the packaged script, the shim, and the files the resolvers check
  await mkdir(join(pkg, "bin"), { recursive: true });
  await mkdir(join(pkg, "src"), { recursive: true });
  await writeFile(join(pkg, "src", "membership.ts"), "// membership stub for the cadence tests\n");
  await writeFile(join(pkg, "bin", "resolve-membership.ts"), "// cli stub\n");
  await writeFile(
    join(pkg, "package.json"),
    JSON.stringify({ name: "@keelson/rib-touchline", version: "9.9.9-test" }),
  );
  const script = join(pkg, "bin", "touchline-collect-cadence.sh");
  const shim = join(pkg, "bin", "touchline-collect-cadence.shim.sh");
  await writeExec(script, await readFile(join(rib, "bin", "touchline-collect-cadence.sh"), "utf8"));
  await writeExec(
    shim,
    await readFile(join(rib, "bin", "touchline-collect-cadence.shim.sh"), "utf8"),
  );

  // fakes first on the script's PATH
  await mkdir(fakes, { recursive: true });
  await writeExec(join(fakes, "keelson"), FAKE_KEELSON);
  await writeExec(join(fakes, "bun"), FAKE_BUN);
  await writeExec(join(fakes, "just"), FAKE_JUST);
  await writeFile(fakeLog, "");

  // data home: marked, one board file set per conference, committed, upstream set
  await mkdir(data, { recursive: true });
  await writeFile(join(data, "touchline-data.yaml"), "kind: touchline-data\nversion: 1\n");
  for (const layer of LAYERS) {
    await mkdir(join(data, "data", layer), { recursive: true });
    for (const lc of ["gac", "lsc"]) {
      await writeFile(
        join(data, "data", layer, `${SEASON}-${GENDER}-${lc}.json`),
        initialBoard(lc),
      );
    }
  }
  await git(data, "init", "-q", "-b", "main");
  await git(data, "add", "-A");
  await git(data, "commit", "-q", "-m", "chore(data): initial board");
  await git(root, "init", "-q", "--bare", "-b", "main", dataRemote);
  await git(data, "remote", "add", "origin", dataRemote);
  await git(data, "push", "-q", "-u", "origin", "main");

  // site checkout on main with a journal dir and an upstream
  await mkdir(join(site, "journal"), { recursive: true });
  await writeFile(join(site, "justfile"), "publish:\n\t@echo real just is never reached\n");
  await writeFile(join(site, "journal", ".gitkeep"), "");
  await writeFile(join(site, ".gitignore"), "dist/\nnode_modules/\n");
  await git(site, "init", "-q", "-b", "main");
  await git(site, "add", "-A");
  await git(site, "commit", "-q", "-m", "chore: site skeleton");
  await git(root, "init", "-q", "--bare", "-b", "main", siteRemote);
  await git(site, "remote", "add", "origin", siteRemote);
  await git(site, "push", "-q", "-u", "origin", "main");

  return {
    root,
    home,
    pkg,
    script,
    shim,
    data,
    dataRemote,
    site,
    siteRemote,
    fakes,
    archive,
    fakeLog,
    logFile,
    runsFile,
    env,
    git,
    cadence: (mode, extra = {}) => run(["/bin/sh", script, mode], { ...env, ...extra }, root),
    log: () => readFile(logFile, "utf8"),
    calls: () => readFile(fakeLog, "utf8"),
    records: async () =>
      existsSync(runsFile)
        ? (await readFile(runsFile, "utf8"))
            .split("\n")
            .filter((l) => l.trim() !== "")
            .map((l) => JSON.parse(l))
        : [],
  };
}

async function boardFile(h: Harness, layer: string, lc: string): Promise<string> {
  return readFile(join(h.data, "data", layer, `${SEASON}-${GENDER}-${lc}.json`), "utf8");
}

describe("bin/touchline-collect-cadence.sh", () => {
  test("(a) a changed collect commits in the data home and marks the conference changed", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=changed",
    });
    expect(r.code).toBe(0);

    const head = await h.git(h.data, "rev-parse", "--short", "HEAD");
    expect(head).not.toBe(before);
    expect(await h.git(h.data, "log", "-1", "--format=%s")).toBe(
      `chore(data): cadence collect GAC ${GENDER} ${SEASON}`,
    );
    expect(await h.git(h.data, "status", "--porcelain")).toBe("");
    expect(await boardFile(h, "fixtures", "gac")).toContain('"new-row"');
    // coverage and raw_html churn ride along in the same commit
    const shown = await h.git(h.data, "show", "--stat", "--format=", "HEAD");
    expect(shown).toContain("data/coverage.json");
    expect(shown).toContain(`data/raw_html/gac-alpha/${SEASON}-${GENDER}-schedule.html`);

    const log = await h.log();
    expect(log).toContain(
      `touchline cadence: mode=collect season=${SEASON} gender=${GENDER} conferences=[GAC]`,
    );
    expect(log).toContain(`  GAC: board CHANGED — committed ${head}.`);

    const [rec] = await h.records();
    expect(rec).toBeDefined();
    expect(rec.mode).toBe("collect");
    expect(rec.season).toBe(2026);
    expect(rec.gender).toBe(GENDER);
    expect(rec.conferences).toEqual(["GAC"]);
    expect(rec.collect).toEqual({ GAC: "changed" });
    expect(rec.changed).toEqual(["gac"]);
    expect(rec.failed).toEqual([]);
    expect(rec.data_head).toBe(head);
    expect(rec.exit).toBe(0);
  });

  test("(b) stamp-only churn rolls back and reports no-change", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=churn",
    });
    expect(r.code).toBe(0);

    expect(await h.git(h.data, "rev-parse", "--short", "HEAD")).toBe(before);
    expect(await h.git(h.data, "status", "--porcelain")).toBe("");
    expect(await boardFile(h, "fixtures", "gac")).toBe(initialBoard("gac"));
    expect(existsSync(join(h.data, "data", "coverage.json"))).toBe(false);
    expect(existsSync(join(h.data, "data", "raw_html", "gac-alpha"))).toBe(false);
    expect(existsSync(join(h.data, "data", "raw_html", "gac-beta"))).toBe(false);
    expect(
      existsSync(join(h.data, "data", "errors", `collect-board-${SEASON}-${GENDER}-gac.json`)),
    ).toBe(false);

    const log = await h.log();
    expect(log).toContain(
      "  GAC: no change beyond the collected_at stamp — churn rolled back, journal skipped.",
    );

    const [rec] = await h.records();
    expect(rec.collect).toEqual({ GAC: "no-change" });
    expect(rec.changed).toEqual([]);
    expect(rec.data_head).toBe(before);
    expect(rec.exit).toBe(0);
  });

  test("(c) a failed collect rolls back its partial write and the run continues to the next conference with exit 1", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC LSC",
      CADENCE_FAKE_PLAN: "GAC=failed,LSC=changed",
    });
    expect(r.code).toBe(1);

    // GAC's partial write is gone; LSC's real change is committed on top of the old HEAD
    expect(await boardFile(h, "fixtures", "gac")).toBe(initialBoard("gac"));
    expect(existsSync(join(h.data, "data", "raw_html", "gac-alpha"))).toBe(false);
    expect(await boardFile(h, "fixtures", "lsc")).toContain('"new-row"');
    expect(await h.git(h.data, "status", "--porcelain")).toBe("");
    const head = await h.git(h.data, "rev-parse", "--short", "HEAD");
    expect(head).not.toBe(before);
    expect(await h.git(h.data, "log", "--format=%s", `${before}..HEAD`)).toBe(
      `chore(data): cadence collect LSC ${GENDER} ${SEASON}`,
    );

    const log = await h.log();
    expect(log).toContain(
      "  GAC: collect FAILED (exit 2, error(E_COLLECT): fake collect blew up) — partial writes rolled back; continuing with the next conference.",
    );
    expect(log).toContain(`  LSC: board CHANGED — committed ${head}.`);
    expect(log).toMatch(/run summary: mode=collect .* failed=\[GAC\] .* exit=1 /);

    const [rec] = await h.records();
    expect(rec.collect).toEqual({ GAC: "failed", LSC: "changed" });
    expect(rec.failed).toEqual(["GAC"]);
    expect(rec.changed).toEqual(["lsc"]);
    expect(rec.exit).toBe(1);
  });

  test("a membership resolution failure is recorded as resolve-failed and skips the collect", async () => {
    const h = await makeHarness();
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_RESOLVE_FAIL: "GAC",
    });
    expect(r.code).toBe(1);
    expect(await h.calls()).not.toContain("keelson workflow run");
    expect(await h.log()).toContain("  membership resolution FAILED — no members resolve for GAC");
    const [rec] = await h.records();
    expect(rec.collect).toEqual({ GAC: "resolve-failed" });
    expect(rec.failed).toEqual(["GAC"]);
    expect(rec.exit).toBe(1);
  });

  test("(d) mode collect stops after collect+detect: no journal, no publish, no data push", async () => {
    const h = await makeHarness();
    const r = await h.cadence("collect", { CADENCE_FAKE_PLAN: "GAC=changed,LSC=changed" });
    expect(r.code).toBe(0);

    const calls = await h.calls();
    // the conference set came from membership (the fake answers "GAC LSC")
    expect(calls).toContain("resolve-membership.ts conferences men");
    expect(calls).toContain("conference=GAC");
    expect(calls).toContain("conference=LSC");
    expect(calls).not.toContain("run journal");
    expect(calls).not.toContain("just publish");

    const log = await h.log();
    expect(log).toContain("touchline cadence: conferences resolved from membership: [GAC LSC]");
    expect(log).toContain("mode=collect — stopping after collect+detect (no journal, no publish).");
    expect(log).not.toContain("data home push");
    // collect mode never pushes: the two commits stay ahead of upstream
    expect(await h.git(h.data, "rev-list", "--count", "origin/main..HEAD")).toBe("2");

    const [rec] = await h.records();
    expect(rec.mode).toBe("collect");
    expect(rec.conferences).toEqual(["GAC", "LSC"]);
    expect(rec.collect).toEqual({ GAC: "changed", LSC: "changed" });
    expect(rec.changed).toEqual(["gac", "lsc"]);
    expect(rec.journal_model_calls).toBe(0);
    expect(rec.journal_commit).toBe("none");
    expect(rec.journaled).toEqual([]);
    expect(rec.data_push).toBe("skipped");
    expect(rec.build_stamp).toBeNull();
    expect(rec.publish).toBe("skipped (no change)");
    expect(rec.data_head).toBe(await h.git(h.data, "rev-parse", "--short", "HEAD"));
    expect(rec.exit).toBe(0);
  });

  test(
    "(e) loop mode with one changed conference journals it and the national leg, commits on the site's main, publishes, pushes, and writes the full record",
    async () => {
      const h = await makeHarness();
      const r = await h.cadence("loop", {
        TOUCHLINE_CONFERENCES: "GAC",
        CADENCE_FAKE_PLAN: "GAC=changed",
      });
      expect(r.code).toBe(0);

      // the legs ran in order: conference journal, national journal, publish
      const calls = await h.calls();
      const iJournal = calls.indexOf("bun run journal run --conference gac --write");
      const iNational = calls.indexOf("bun run journal run --national --write");
      const iPublish = calls.indexOf(`just publish (cwd ${h.site})`);
      expect(iJournal).toBeGreaterThan(-1);
      expect(iNational).toBeGreaterThan(iJournal);
      expect(iPublish).toBeGreaterThan(iNational);

      // journals committed on the site's main and pushed
      const siteHead = await h.git(h.site, "rev-parse", "--short", "HEAD");
      const siteSubject = await h.git(h.site, "log", "-1", "--format=%s");
      expect(siteSubject).toMatch(
        /^chore\(journal\): cadence regeneration \d{4}-\d{2}-\d{2} \[gac national\]$/,
      );
      const staged = await h.git(h.site, "show", "--name-only", "--format=", "HEAD");
      for (const key of ["gac", "national"]) {
        expect(staged).toContain(`journal/journal-${SEASON}-${GENDER}-${key}.json`);
        expect(staged).toContain(`journal/journal-${SEASON}-${GENDER}-${key}.validation.json`);
      }
      expect(await h.git(h.site, "status", "--porcelain")).toBe("");
      expect(await h.git(h.siteRemote, "rev-parse", "--short", "main")).toBe(siteHead);

      // the data home's collect commit reached its upstream
      const dataHead = await h.git(h.data, "rev-parse", "--short", "HEAD");
      expect(await h.git(h.dataRemote, "rev-parse", "--short", "main")).toBe(dataHead);

      const log = await h.log();
      expect(log).toContain(
        "journal [gac]: regenerating — LIVE MODEL CALLS (claude -p), 1 spend(s), one pooled call, cap 1800s.",
      );
      expect(log).toContain("  journal gac regenerated and validated.");
      expect(log).toContain(
        "journal [national]: regenerating — LIVE MODEL CALL (claude -p), 1 spend, cap 900s.",
      );
      expect(log).toContain("  journal national regenerated and validated.");
      expect(log).toContain(`journal commit: ${siteHead} on main [gac national].`);
      expect(log).toContain("journal push: origin/main updated.");
      expect(log).toContain(
        `publish succeeded — the deployed host was asserted by the recipe itself. build=${BUILD}`,
      );
      expect(log).toContain("data home push: 1 commit(s) sent to upstream.");
      expect(log).toMatch(
        new RegExp(
          `^\\[\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\] run summary: mode=loop season=${SEASON} ` +
            `collect=\\[GAC=changed\\] changed=\\[gac\\] failed=\\[none\\] journal_model_calls=2 ` +
            `journal_commit=${siteHead} publish=succeeded exit=0 data_head=${dataHead} build=${BUILD} ` +
            `locked=\\[none\\] busy=none archive=skipped \\(disabled; archive day 0, today is ${weekday()}\\)$`,
          "m",
        ),
      );

      const records = await h.records();
      expect(records).toHaveLength(1);
      const rec = records[0]!;
      expect(Object.keys(rec).sort()).toEqual(
        [
          "started_at",
          "finished_at",
          "mode",
          "season",
          "gender",
          "conferences",
          "collect",
          "changed",
          "failed",
          "locked",
          "busy",
          "journal_model_calls",
          "journal_commit",
          "journaled",
          "data_head",
          "data_push",
          "build_stamp",
          "publish",
          "exit",
          "archive",
        ].sort(),
      );
      expect(rec.started_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
      expect(rec.finished_at >= rec.started_at).toBe(true);
      expect(rec.mode).toBe("loop");
      expect(rec.collect).toEqual({ GAC: "changed" });
      expect(rec.changed).toEqual(["gac"]);
      expect(rec.locked).toEqual([]);
      expect(rec.busy).toBeNull();
      expect(rec.journal_model_calls).toBe(2);
      expect(rec.journal_commit).toBe(siteHead);
      expect(rec.journaled).toEqual(["gac", "national"]);
      expect(rec.data_head).toBe(dataHead);
      expect(rec.data_push).toBe("ok");
      expect(rec.build_stamp).toBe(BUILD);
      expect(rec.publish).toBe("succeeded");
      expect(rec.archive).toBe(`skipped (disabled; archive day 0, today is ${weekday()})`);
      expect(rec.exit).toBe(0);
    },
    LOOP_TIMEOUT,
  );

  test(
    "loop mode with a failed publish keeps the data commits, records the failure with a null build stamp and exits 1",
    async () => {
      const h = await makeHarness();
      const r = await h.cadence("loop", {
        TOUCHLINE_CONFERENCES: "GAC",
        CADENCE_FAKE_PLAN: "GAC=changed",
        CADENCE_FAKE_PUBLISH_FAIL: "1",
      });
      expect(r.code).toBe(1);
      const log = await h.log();
      expect(log).toContain("PUBLISH FAILED (exit 1) — the live site did NOT update.");
      expect(log).toMatch(
        /run summary: .* publish=FAILED \(exit 1\) exit=1 data_head=[0-9a-f]{7,} build=none locked=\[none\] busy=none archive=skipped \(disabled; archive day 0, today is [1-7]\)$/m,
      );
      const [rec] = await h.records();
      expect(rec.publish).toBe("FAILED (exit 1)");
      expect(rec.build_stamp).toBeNull();
      expect(rec.journaled).toEqual(["gac", "national"]);
      expect(rec.data_push).toBe("ok");
      expect(rec.exit).toBe(1);
    },
    LOOP_TIMEOUT,
  );

  test(
    "a conference that came back unchanged hands its fresh stamp to the publish, while its board keeps the committed one",
    async () => {
      const h = await makeHarness();
      const r = await h.cadence("loop", {
        TOUCHLINE_CONFERENCES: "GAC LSC",
        CADENCE_FAKE_PLAN: "GAC=changed,LSC=churn",
      });
      expect(r.code).toBe(0);
      // the board is rolled back to its committed stamp...
      expect(await boardFile(h, "fixtures", "lsc")).toBe(initialBoard("lsc"));
      // ...and the stamp the collect wrote reaches the site's build, and the
      // journal legs before it, so both date the quiet conference alike
      const lines = (await h.calls()).split("\n");
      const env = lines.find((l) => l.startsWith("just env TOUCHLINE_RECOLLECTED="));
      expect(env).toMatch(
        /^just env TOUCHLINE_RECOLLECTED=lsc=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/,
      );
      const journalEnv = lines.filter((l) => l.startsWith("bun env TOUCHLINE_RECOLLECTED="));
      expect(journalEnv).toHaveLength(2); // the conference leg and the national leg
      for (const l of journalEnv) expect(l.slice(4)).toBe((env as string).slice(5));
      const [rec] = await h.records();
      expect(rec.collect).toEqual({ GAC: "changed", LSC: "no-change" });
      expect(rec.publish).toBe("succeeded");
    },
    LOOP_TIMEOUT,
  );

  test(
    "a quiet loop run journals nothing and commits nothing, but republishes so the site is dated by the look",
    async () => {
      const h = await makeHarness();
      const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
      const r = await h.cadence("loop", {
        TOUCHLINE_CONFERENCES: "GAC",
        CADENCE_FAKE_PLAN: "GAC=churn",
      });
      expect(r.code).toBe(0);
      const calls = await h.calls();
      expect(calls).not.toContain("run journal");
      expect(calls).toContain(`just publish (cwd ${h.site})`);
      expect(calls).toMatch(/^just env TOUCHLINE_RECOLLECTED=gac=\S+$/m);
      expect(await h.log()).toContain(
        "no conference changed — nothing to journal; republishing so the site is dated by this run's look.",
      );
      expect(await h.git(h.data, "rev-parse", "--short", "HEAD")).toBe(before);
      const [rec] = await h.records();
      expect(rec.mode).toBe("loop");
      expect(rec.collect).toEqual({ GAC: "no-change" });
      expect(rec.journal_model_calls).toBe(0);
      expect(rec.journal_commit).toBe("none");
      expect(rec.publish).toBe("succeeded");
      expect(rec.data_push).toBe("skipped");
      expect(rec.exit).toBe(0);
    },
    LOOP_TIMEOUT,
  );

  test("a loop run where nothing collected journals nothing and publishes nothing", async () => {
    // Every collect failed: there is no look to date the site by, so the
    // published site keeps the stamps it has — which now read as old, the
    // signal a reader is owed.
    const h = await makeHarness();
    const r = await h.cadence("loop", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=failed",
    });
    expect(r.code).toBe(1);
    const calls = await h.calls();
    expect(calls).not.toContain("run journal");
    expect(calls).not.toContain("just publish");
    expect(await h.log()).toContain(
      "no conference changed and none collected — nothing to journal, nothing to publish. No-op run complete.",
    );
    const [rec] = await h.records();
    expect(rec.collect).toEqual({ GAC: "failed" });
    expect(rec.publish).toBe("skipped (no change)");
    expect(rec.build_stamp).toBeNull();
  });

  test("(f) the lock: a second concurrent start is a logged no-op", async () => {
    const h = await makeHarness();
    const env = {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=changed",
      CADENCE_FAKE_SLEEP: "6",
    };
    const first = h.cadence("collect", env);
    // wait until the first run holds the lock and is inside its (slow) collect
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      if (existsSync(h.logFile) && (await h.log()).includes(`collect GAC ${GENDER} ${SEASON}:`))
        break;
      await Bun.sleep(100);
    }
    const second = await h.cadence("collect", env);
    expect(second.code).toBe(0);
    const r1 = await first;
    expect(r1.code).toBe(0);

    const log = await h.log();
    expect(log).toMatch(/cadence already running \(pid \d+\) — exiting without work\./);
    expect((log.match(/run summary:/g) ?? []).length).toBe(1);
    expect((await h.calls()).match(/keelson workflow run/g) ?? []).toHaveLength(1);
    expect(await h.records()).toHaveLength(1);
    expect(existsSync(join(h.home, ".keelson", "locks", "touchline-collect-cadence.lock"))).toBe(
      false,
    );
  }, 60_000);

  test("(g) a collect or backfill already running on the data home makes the start a busy exit: no sweep, no collect, and the record says why", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    // a sibling's uncommitted board change already sits in the data home
    const sibling = join(h.data, "data", "fixtures", `${SEASON}-${GENDER}-lsc.json`);
    await writeFile(sibling, board("lsc", "2026-09-05T00:00:00Z", '"backfill-row"'));
    const r = await h.cadence("loop", {
      TOUCHLINE_CONFERENCES: "GAC LSC",
      CADENCE_FAKE_PLAN: "GAC=changed",
      CADENCE_FAKE_BUSY: "touchline-backfill:run-abc:2026-09-06T12:00:00Z",
    });
    expect(r.code).toBe(0);

    // nothing swept, nothing collected: HEAD stands and the sibling's change is intact and dirty
    expect(await h.git(h.data, "rev-parse", "--short", "HEAD")).toBe(before);
    expect(await readFile(sibling, "utf8")).toContain('"backfill-row"');
    expect(await h.git(h.data, "status", "--porcelain")).toBe(
      `M data/fixtures/${SEASON}-${GENDER}-lsc.json`,
    );
    const calls = await h.calls();
    expect(calls).toContain("keelson workflow status --json");
    expect(calls).not.toContain("keelson workflow run");
    expect(calls).not.toContain("run journal");
    expect(calls).not.toContain("just publish");

    const log = await h.log();
    expect(log).toContain(
      "data home busy: touchline-backfill run run-abc started 2026-09-06T12:00:00Z, owner manual — exiting without a sweep or a collect",
    );
    expect(log).not.toContain("sweeping leftovers");
    expect(log).toMatch(
      /run summary: mode=loop season=2026 collect=\[none\] changed=\[none\] failed=\[none\] .* exit=0 .* locked=\[none\] busy=touchline-backfill run-abc archive=skipped \(not reached\)$/m,
    );

    const [rec] = await h.records();
    expect(rec.busy).toBe("touchline-backfill run-abc");
    expect(rec.archive).toBe("skipped (not reached)");
    expect(rec.collect).toEqual({});
    expect(rec.conferences).toEqual(["GAC", "LSC"]);
    expect(rec.changed).toEqual([]);
    expect(rec.locked).toEqual([]);
    expect(rec.data_head).toBe(before);
    expect(rec.exit).toBe(0);
  });

  test(
    "(h) a collect refused by the server's mutation lock is locked, never rolled back, skips the rest of the set by name, and the run still journals and publishes what changed",
    async () => {
      const h = await makeHarness();
      const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
      const r = await h.cadence("loop", {
        TOUCHLINE_CONFERENCES: "GAC LSC GSC",
        CADENCE_FAKE_PLAN: "GAC=changed,LSC=locked",
        // the holder's own file lands during the refused collect
        CADENCE_FAKE_SIDE_WRITE: "data/scratch/holder-note.json",
      });
      expect(r.code).toBe(1);

      // GAC committed and pushed; the holder's file is untouched and still uncommitted
      const head = await h.git(h.data, "rev-parse", "--short", "HEAD");
      expect(head).not.toBe(before);
      expect(await h.git(h.data, "log", "--format=%s", `${before}..HEAD`)).toBe(
        `chore(data): cadence collect GAC ${GENDER} ${SEASON}`,
      );
      expect(await h.git(h.dataRemote, "rev-parse", "--short", "main")).toBe(head);
      expect(existsSync(join(h.data, "data", "scratch", "holder-note.json"))).toBe(true);
      expect(await h.git(h.data, "status", "--porcelain")).toBe("?? data/scratch/");

      // GSC never ran; the journal and publish legs ran for GAC
      const calls = await h.calls();
      expect(calls).toContain("conference=LSC");
      expect(calls).not.toContain("conference=GSC");
      expect(calls).toContain("bun run journal run --conference gac --write");
      expect(calls).toContain(`just publish (cwd ${h.site})`);

      const log = await h.log();
      expect(log).toContain(
        `  LSC: collect LOCKED — project ${PROJECT_ID} is locked by run:abc for "touchline-backfill"`,
      );
      expect(log).toContain(
        "  data home held by another run — skipping the remaining conference(s) [GSC] this run; nothing of theirs was written or rolled back.",
      );
      expect(log).not.toContain("partial writes rolled back");
      expect(log).not.toContain("churn rolled back");
      expect(log).toMatch(
        /run summary: mode=loop season=2026 collect=\[GAC=changed LSC=locked\] changed=\[gac\] failed=\[none\] journal_model_calls=2 .* publish=succeeded exit=1 .* locked=\[LSC\] busy=none archive=skipped \(disabled; .*\)$/m,
      );

      const [rec] = await h.records();
      expect(rec.collect).toEqual({ GAC: "changed", LSC: "locked" });
      expect(rec.locked).toEqual(["LSC"]);
      expect(rec.failed).toEqual([]);
      expect(rec.changed).toEqual(["gac"]);
      expect(rec.busy).toBeNull();
      expect(rec.journaled).toEqual(["gac", "national"]);
      expect(rec.publish).toBe("succeeded");
      expect(rec.data_push).toBe("ok");
      expect(rec.exit).toBe(1);
    },
    LOOP_TIMEOUT,
  );

  test("(i) a failed collect's rollback restores only that conference's paths: a sibling's write landing mid-collect survives, still uncommitted", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=failed",
      // written by the fake during GAC's collect, after the sweep has run
      CADENCE_FAKE_SIDE_WRITE: `data/fixtures/${SEASON}-${GENDER}-lsc.json`,
    });
    expect(r.code).toBe(1);
    expect(await h.git(h.data, "rev-parse", "--short", "HEAD")).toBe(before);

    // GAC's board, errors, raw_html and coverage paths are back to HEAD or gone
    expect(await boardFile(h, "fixtures", "gac")).toBe(initialBoard("gac"));
    expect(
      existsSync(join(h.data, "data", "errors", `collect-board-${SEASON}-${GENDER}-gac.json`)),
    ).toBe(false);
    expect(existsSync(join(h.data, "data", "raw_html", "gac-alpha"))).toBe(false);
    expect(existsSync(join(h.data, "data", "coverage.json"))).toBe(false);
    // LSC's write survived the rollback and is still dirty
    expect(await boardFile(h, "fixtures", "lsc")).toContain('"side-row"');
    expect(await h.git(h.data, "status", "--porcelain")).toBe(
      `M data/fixtures/${SEASON}-${GENDER}-lsc.json`,
    );

    const log = await h.log();
    expect(log).toContain(
      "  GAC: collect FAILED (exit 2, error(E_COLLECT): fake collect blew up) — partial writes rolled back; continuing with the next conference.",
    );
    const [rec] = await h.records();
    expect(rec.collect).toEqual({ GAC: "failed" });
    expect(rec.failed).toEqual(["GAC"]);
    expect(rec.locked).toEqual([]);
    expect(rec.busy).toBeNull();
    expect(rec.exit).toBe(1);
  });

  test("(j) the pre-run sweep names what it commits per conference, shared and unattributed, and the commit message lists the conferences", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    const leftGac = board("gac", "2026-09-05T00:00:00Z", '"left-row"');
    const leftLsc = board("lsc", "2026-09-05T00:00:00Z", '"left-row"');
    await writeFile(join(h.data, "data", "fixtures", `${SEASON}-${GENDER}-gac.json`), leftGac);
    await writeFile(join(h.data, "data", "rosters", `${SEASON}-${GENDER}-gac.json`), leftGac);
    await writeFile(join(h.data, "data", "stats", `${SEASON}-${GENDER}-lsc.json`), leftLsc);
    await mkdir(join(h.data, "data", "raw_html", "lsc-beta"), { recursive: true });
    await writeFile(
      join(h.data, "data", "raw_html", "lsc-beta", `${SEASON}-${GENDER}-roster.html`),
      "<html>left</html>\n",
    );
    await writeFile(join(h.data, "data", "coverage.json"), '{"collected_at":"left"}\n');
    await writeFile(join(h.data, "data", "notes.txt"), "stray\n");
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC LSC",
      CADENCE_FAKE_PLAN: "GAC=changed,LSC=changed",
    });
    expect(r.code).toBe(0);

    const log = await h.log();
    expect(log).toContain(
      `  sweep GAC: 2 path(s): data/fixtures/${SEASON}-${GENDER}-gac.json data/rosters/${SEASON}-${GENDER}-gac.json`,
    );
    // git lists tracked changes before untracked paths
    expect(log).toContain(
      `  sweep LSC: 2 path(s): data/stats/${SEASON}-${GENDER}-lsc.json data/raw_html/lsc-beta/${SEASON}-${GENDER}-roster.html`,
    );
    expect(log).toContain("  sweep shared: 1 path(s): data/coverage.json");
    expect(log).toContain("  sweep unattributed: 1 path(s): data/notes.txt");
    expect(log).toContain("  leftover board changes touch GAC — it counts as changed.");
    expect(log).toContain("  leftover board changes touch LSC — it counts as changed.");

    // the sweep commit comes first and carries every dirty path; the collects commit after it
    const subjects = await h.git(h.data, "log", "--reverse", "--format=%s", `${before}..HEAD`);
    expect(subjects.split("\n")).toEqual([
      "chore(data): sweep uncommitted changes found before cadence run [GAC LSC]",
      `chore(data): cadence collect GAC ${GENDER} ${SEASON}`,
      `chore(data): cadence collect LSC ${GENDER} ${SEASON}`,
    ]);
    const swept = await h.git(h.data, "show", "--name-only", "--format=", "HEAD~2");
    for (const p of [
      `data/fixtures/${SEASON}-${GENDER}-gac.json`,
      `data/rosters/${SEASON}-${GENDER}-gac.json`,
      `data/stats/${SEASON}-${GENDER}-lsc.json`,
      `data/raw_html/lsc-beta/${SEASON}-${GENDER}-roster.html`,
      "data/coverage.json",
      "data/notes.txt",
    ]) {
      expect(swept).toContain(p);
    }
    expect(await h.git(h.data, "status", "--porcelain")).toBe("");
    // membership resolved once per conference for the whole run: the sweep's
    // raw_html attribution and the collect loop share the cache
    expect((await h.calls()).match(/^bun -e /gm) ?? []).toHaveLength(2);

    const [rec] = await h.records();
    expect(rec.changed).toEqual(["gac", "lsc"]);
    expect(rec.collect).toEqual({ GAC: "changed", LSC: "changed" });
    expect(rec.exit).toBe(0);
  });

  test("(k) a down keelson server is started before collecting, and the run goes on", async () => {
    const h = await makeHarness();
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=changed",
      CADENCE_FAKE_SERVER_DOWN: "1",
    });
    expect(r.code).toBe(0);

    const calls = await h.calls();
    expect(calls).toContain("keelson start");
    expect(calls).toContain("keelson workflow run touchline-collect");
    expect(await boardFile(h, "fixtures", "gac")).toContain('"new-row"');

    const log = await h.log();
    expect(log).toContain(
      "keelson server is down — starting it (keelson start) before collecting.",
    );
    expect(log).toContain("keelson server started — continuing.");
    expect(log).not.toContain("NO_SERVER): --project");

    const [rec] = await h.records();
    expect(rec.collect).toEqual({ GAC: "changed" });
    expect(rec.exit).toBe(0);
  });

  test("(l) a server that stays down stops the run with one FATAL: no sweep, no collect", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    const sibling = join(h.data, "data", "fixtures", `${SEASON}-${GENDER}-lsc.json`);
    await writeFile(sibling, board("lsc", "2026-09-05T00:00:00Z", '"leftover-row"'));
    const r = await h.cadence("loop", {
      TOUCHLINE_CONFERENCES: "GAC LSC",
      CADENCE_FAKE_SERVER_DOWN: "1",
      CADENCE_FAKE_START_FAIL: "1",
    });
    expect(r.code).toBe(1);

    expect(await h.git(h.data, "rev-parse", "--short", "HEAD")).toBe(before);
    expect(await h.git(h.data, "status", "--porcelain")).toBe(
      `M data/fixtures/${SEASON}-${GENDER}-lsc.json`,
    );
    const calls = await h.calls();
    expect(calls).toContain("keelson start");
    expect(calls).not.toContain("keelson workflow run");
    expect(calls).not.toContain("run journal");
    expect(calls).not.toContain("just publish");

    const log = await h.log();
    expect(log).toContain(
      "FATAL: keelson server is down and keelson start did not bring it up — every collect needs it, so nothing was swept or collected.",
    );
    expect(log).not.toContain("sweeping leftovers");
    expect(log).not.toContain("collect GAC");

    const [rec] = await h.records();
    expect(rec.collect).toEqual({});
    expect(rec.failed).toEqual([]);
    expect(rec.data_head).toBe(before);
    expect(rec.exit).toBe(1);
  });

  test("(m) a collect that drops a programme HEAD held is rolled back as lost, counted failed, and the run goes on", async () => {
    const h = await makeHarness();
    const before = await h.git(h.data, "rev-parse", "--short", "HEAD");
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC LSC",
      CADENCE_FAKE_PLAN: "GAC=lost,LSC=changed",
    });
    expect(r.code).toBe(1);

    // GAC keeps its last commit, gap and all gone; LSC's real change lands
    for (const layer of LAYERS) {
      expect(await boardFile(h, layer, "gac")).toBe(initialBoard("gac"));
    }
    expect(existsSync(join(h.data, "data", "raw_html", "gac-alpha"))).toBe(false);
    expect(await boardFile(h, "fixtures", "lsc")).toContain('"new-row"');
    expect(await h.git(h.data, "status", "--porcelain")).toBe("");
    expect(await h.git(h.data, "log", "--format=%s", `${before}..HEAD`)).toBe(
      `chore(data): cadence collect LSC ${GENDER} ${SEASON}`,
    );

    const log = await h.log();
    // the fake board holds no rosters or teams map, so only fixtures had gac-alpha to lose
    expect(log).toContain(
      "  GAC: collect LOST data HEAD held (fixtures:gac-alpha) — a programme that served before is a named gap now; board rolled back to its last commit",
    );
    expect(log).toMatch(/run summary: mode=collect .* failed=\[GAC\] .* exit=1 /);

    const [rec] = await h.records();
    expect(rec.collect).toEqual({ GAC: "lost", LSC: "changed" });
    expect(rec.failed).toEqual(["GAC"]);
    expect(rec.changed).toEqual(["lsc"]);
    expect(rec.exit).toBe(1);
  });

  test("(n) a gap HEAD already carried is not a loss, and TOUCHLINE_ACCEPT_LOSS lands a real one", async () => {
    // a gap the board already records: the same slug missing again is no loss
    const chronic = await makeHarness();
    for (const layer of ["fixtures", "rosters", "stats"]) {
      const f = join(chronic.data, "data", layer, `${SEASON}-${GENDER}-gac.json`);
      const doc = JSON.parse(await readFile(f, "utf8"));
      doc.missing = ["gac-alpha"];
      await writeFile(f, `${JSON.stringify(doc, null, 2)}\n`);
    }
    await chronic.git(chronic.data, "commit", "-qam", "chore(data): gac-alpha already a gap");
    const r1 = await chronic.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=lost",
    });
    expect(r1.code).toBe(0);
    expect(await chronic.log()).not.toContain("LOST");
    expect((await chronic.records())[0].collect).toEqual({ GAC: "changed" });

    // a loss the owner says is real lands, and says so
    const accepted = await makeHarness();
    const r2 = await accepted.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=lost",
      TOUCHLINE_ACCEPT_LOSS: "lsc,GAC",
    });
    expect(r2.code).toBe(0);
    expect(await accepted.log()).toContain(
      "  GAC: collect drops data HEAD held (fixtures:gac-alpha) — accepted by TOUCHLINE_ACCEPT_LOSS.",
    );
    expect(JSON.parse(await boardFile(accepted, "fixtures", "gac")).missing).toEqual(["gac-alpha"]);
    expect((await accepted.records())[0].collect).toEqual({ GAC: "changed" });
  });

  test("an unknown mode is a logged FATAL", async () => {
    const h = await makeHarness();
    const r = await h.cadence("publish");
    expect(r.code).toBe(1);
    expect(await h.log()).toContain("FATAL: unknown mode 'publish'");
    expect(await h.records()).toHaveLength(0);
  });

  test("mode collect records the archive as skipped by mode", async () => {
    const h = await makeHarness();
    const r = await h.cadence("collect", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=churn",
      TOUCHLINE_ARCHIVE_DAY: "always",
    });
    expect(r.code).toBe(0);
    expect(existsSync(h.archive)).toBe(false);
    expect(await h.log()).not.toContain("archive:");
    const [rec] = await h.records();
    expect(rec.archive).toBe("skipped (mode collect)");
  });

  test("version mode prints the packaged script path and version, takes no lock and writes no log", async () => {
    const h = await makeHarness();
    const r = await h.cadence("version");
    expect(r.code).toBe(0);
    expect(r.stdout).toMatch(
      /^touchline-collect-cadence: script=\S+\/bin\/touchline-collect-cadence\.sh package=\S+ version=9\.9\.9-test git=not a checkout$/m,
    );
    expect(existsSync(h.logFile)).toBe(false);
    expect(existsSync(join(h.home, ".keelson", "locks", "touchline-collect-cadence.lock"))).toBe(
      false,
    );
    expect(await h.records()).toHaveLength(0);
    expect(await h.calls()).toBe("");
  });
});

// ── the weekly raw HTML archive (tl-ttj) ─────────────────────────────────────

// Season-named raw pages for a conference's two slugs, the way the collector
// leaves them on disk: <season>-<gender>-schedule.html plus its .state.json.
async function seedRawPages(h: Harness, lc: string, season: string, slugs?: string[]) {
  for (const slug of slugs ?? [`${lc}-alpha`, `${lc}-beta`]) {
    const dir = join(h.data, "data", "raw_html", slug);
    await mkdir(dir, { recursive: true });
    await writeFile(
      join(dir, `${season}-${GENDER}-schedule.html`),
      `<html>${slug} ${season}</html>\n`,
    );
    await writeFile(
      join(dir, `${season}-${GENDER}-schedule.state.json`),
      `{"fetched_at":"${season}-09-01T00:00:00Z"}\n`,
    );
  }
}

// coverage.json in its real shape (touchline.coverage/1), merged into
// whatever the data home already holds: one matches cell per (season, slug).
async function seedCoverage(h: Harness, cells: Array<{ season: string; slug: string }>) {
  const path = join(h.data, "data", "coverage.json");
  const manifest = existsSync(path)
    ? JSON.parse(await readFile(path, "utf8"))
    : { schema: "touchline.coverage/1", cells: {} };
  for (const { season, slug } of cells) {
    manifest.cells[`${season}/${GENDER}/${slug}/matches`] = {
      season: Number(season),
      gender: GENDER,
      programme: slug,
      layer: "matches",
      state: "complete",
      collector: "seed",
      confirmed_at: `${season}-09-01T00:00:00Z`,
    };
  }
  manifest.updated_at = "2026-09-01T00:00:00Z";
  await writeFile(path, `${JSON.stringify(manifest, null, 2)}\n`);
}

async function tarball(path: string): Promise<string[]> {
  const r = await run(["/bin/sh", "-c", `zstd -dc "$1" | tar -tf -`, "sh", path], {
    ...process.env,
  } as Record<string, string>);
  if (r.code !== 0) throw new Error(`listing ${path}: ${r.stderr}`);
  return r.stdout
    .split("\n")
    .filter((l) => l.trim() !== "")
    .sort();
}

function pages(slug: string, season: string): string[] {
  return [
    `data/raw_html/${slug}/${season}-${GENDER}-schedule.html`,
    `data/raw_html/${slug}/${season}-${GENDER}-schedule.state.json`,
  ];
}

async function seedDated(h: Harness, name: string, complete: boolean) {
  const dir = join(h.archive, name);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, `${SEASON}-${GENDER}-gac.tar.zst`), "old\n");
  if (complete) await writeFile(join(dir, ".done"), "");
}

describe("bin/touchline-collect-cadence.sh archive step", () => {
  test.skipIf(!ZSTD)(
    `(a) a loop run on the archive day writes one tar.zst per (season, gender, conference) the data home collected, with exactly that cell's pages${NEEDS_ZSTD}`,
    async () => {
      const h = await makeHarness();
      // an older season GAC collected once: its board, pages and coverage cell
      // are already in the data home; the run's own collects add 2026 for GAC and LSC
      await writeFile(
        join(h.data, "data", "fixtures", `2025-${GENDER}-gac.json`),
        board("gac", "2025-11-01T00:00:00Z", "", "2025"),
      );
      await seedRawPages(h, "gac", "2025", ["gac-alpha"]);
      await seedCoverage(h, [{ season: "2025", slug: "gac-alpha" }]);
      await h.git(h.data, "add", "-A");
      await h.git(h.data, "commit", "-q", "-m", "chore(data): 2025 gac");

      const r = await h.cadence("loop", {
        TOUCHLINE_CONFERENCES: "GAC LSC",
        CADENCE_FAKE_PLAN: "GAC=changed,LSC=changed",
        TOUCHLINE_ARCHIVE_DAY: "always",
      });
      expect(r.code).toBe(0);

      const dir = join(h.archive, today());
      expect((await readdir(dir)).sort()).toEqual([
        ".done",
        `2025-${GENDER}-gac.tar.zst`,
        `${SEASON}-${GENDER}-gac.tar.zst`,
        `${SEASON}-${GENDER}-lsc.tar.zst`,
      ]);
      expect(await tarball(join(dir, `${SEASON}-${GENDER}-gac.tar.zst`))).toEqual(
        [...pages("gac-alpha", SEASON), ...pages("gac-beta", SEASON)].sort(),
      );
      expect(await tarball(join(dir, `${SEASON}-${GENDER}-lsc.tar.zst`))).toEqual(
        [...pages("lsc-alpha", SEASON), ...pages("lsc-beta", SEASON)].sort(),
      );
      expect(await tarball(join(dir, `2025-${GENDER}-gac.tar.zst`))).toEqual(
        pages("gac-alpha", "2025").sort(),
      );

      const log = await h.log();
      expect(log).toContain(`archive: writing ${dir} from ${h.data}/data/raw_html`);
      expect(log).toMatch(/archive 2025 men GAC: 2 file\(s\), \S+$/m);
      expect(log).toMatch(/archive 2026 men GAC: 4 file\(s\), \S+$/m);
      expect(log).toMatch(/archive 2026 men LSC: 4 file\(s\), \S+$/m);
      expect(log).toContain("archive unassigned: none");
      expect(log).toMatch(new RegExp(`archive total: 3 tarball\\(s\\), \\S+, ${dir}$`, "m"));
      expect(log).toContain("archive retention: kept 1 of 1");
      // the archive ran after the data push and before the summary
      expect(log.indexOf("data home push:")).toBeLessThan(log.indexOf("archive: writing"));
      expect(log).toMatch(new RegExp(`run summary: .* busy=none archive=ok ${dir} \\S+$`, "m"));

      const [rec] = await h.records();
      expect(rec.archive).toMatch(new RegExp(`^ok ${dir} \\S+$`));
      expect(rec.exit).toBe(0);
    },
    LOOP_TIMEOUT,
  );

  test.skipIf(!ZSTD)(
    `(b) retention keeps the newest four complete dated directories, today's included, and removes an incomplete one${NEEDS_ZSTD}`,
    async () => {
      const h = await makeHarness();
      for (const d of ["2026-08-09", "2026-08-16", "2026-08-23", "2026-08-30"]) {
        await seedDated(h, d, true);
      }
      await seedDated(h, "2026-09-01", false);
      await seedRawPages(h, "gac", SEASON);
      await seedCoverage(h, [
        { season: SEASON, slug: "gac-alpha" },
        { season: SEASON, slug: "gac-beta" },
      ]);

      const r = await h.cadence("archive");
      expect(r.code).toBe(0);

      expect((await readdir(h.archive)).sort()).toEqual([
        "2026-08-16",
        "2026-08-23",
        "2026-08-30",
        today(),
      ]);
      const log = await h.log();
      expect(log).toContain(
        `archive retention: removed ${h.archive}/2026-09-01 (incomplete, no .done marker)`,
      );
      expect(log).toContain(
        `archive retention: removed ${h.archive}/2026-08-09 (beyond the newest 4)`,
      );
      expect(log).toContain("archive retention: kept 4 of 6");
      expect(existsSync(join(h.archive, today(), ".done"))).toBe(true);
    },
  );

  test("(c) TOUCHLINE_ARCHIVE_DAY=0 and a day that is not today skip the step and say why", async () => {
    const h = await makeHarness();
    const r0 = await h.cadence("loop", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=churn",
      TOUCHLINE_ARCHIVE_DAY: "0",
    });
    expect(r0.code).toBe(0);
    const notToday = String((weekday() % 7) + 1);
    const r1 = await h.cadence("loop", {
      TOUCHLINE_CONFERENCES: "GAC",
      CADENCE_FAKE_PLAN: "GAC=churn",
      TOUCHLINE_ARCHIVE_DAY: notToday,
    });
    expect(r1.code).toBe(0);

    expect(existsSync(h.archive)).toBe(false);
    const log = await h.log();
    expect(log).toContain(`archive: skipped (disabled; archive day 0, today is ${weekday()})`);
    expect(log).toContain(
      `archive: skipped (not archive day; today is ${weekday()}, archive day ${notToday})`,
    );
    const [rec0, rec1] = await h.records();
    expect(rec0.archive).toBe(`skipped (disabled; archive day 0, today is ${weekday()})`);
    expect(rec1.archive).toBe(
      `skipped (not archive day; today is ${weekday()}, archive day ${notToday})`,
    );
  });

  test.skipIf(!ZSTD)(
    `(e) a page no coverage cell claims lands in unassigned.tar.zst and in no cell tarball${NEEDS_ZSTD}`,
    async () => {
      const h = await makeHarness();
      await seedRawPages(h, "gac", SEASON);
      await seedCoverage(h, [
        { season: SEASON, slug: "gac-alpha" },
        { season: SEASON, slug: "gac-beta" },
      ]);
      // a slug no cell names, and a known slug's page from before coverage
      await mkdir(join(h.data, "data", "raw_html", "stray-u"), { recursive: true });
      await writeFile(
        join(h.data, "data", "raw_html", "stray-u", `2019-${GENDER}-schedule.html`),
        "<html>stray</html>\n",
      );
      await writeFile(
        join(h.data, "data", "raw_html", "gac-alpha", `2019-${GENDER}-schedule.html`),
        "<html>older than coverage</html>\n",
      );

      const r = await h.cadence("archive");
      expect(r.code).toBe(0);

      const dir = join(h.archive, today());
      expect((await readdir(dir)).sort()).toEqual([
        ".done",
        `${SEASON}-${GENDER}-gac.tar.zst`,
        "unassigned.tar.zst",
      ]);
      expect(await tarball(join(dir, "unassigned.tar.zst"))).toEqual([
        `data/raw_html/gac-alpha/2019-${GENDER}-schedule.html`,
        `data/raw_html/stray-u/2019-${GENDER}-schedule.html`,
      ]);
      expect(await tarball(join(dir, `${SEASON}-${GENDER}-gac.tar.zst`))).toEqual(
        [...pages("gac-alpha", SEASON), ...pages("gac-beta", SEASON)].sort(),
      );
      const log = await h.log();
      expect(log).toMatch(
        /archive unassigned: 2 file\(s\) across 2 slug\(s\) \(gac-alpha, stray-u\), \S+$/m,
      );
      expect(log).toMatch(new RegExp(`archive total: 2 tarball\\(s\\), \\S+, ${dir}$`, "m"));
    },
  );

  test.skipIf(!ZSTD)(
    `(d) archive mode runs only the archive step under the PID lock: no collect, a second start is the logged no-op, the record says mode=archive${NEEDS_ZSTD}`,
    async () => {
      const h = await makeHarness();
      await seedRawPages(h, "gac", SEASON);
      await seedRawPages(h, "lsc", SEASON);
      await seedCoverage(h, [
        { season: SEASON, slug: "gac-alpha" },
        { season: SEASON, slug: "gac-beta" },
        { season: SEASON, slug: "lsc-alpha" },
        { season: SEASON, slug: "lsc-beta" },
      ]);
      // a zstd that dawdles, first on the PATH, so the first run holds the lock
      // long enough for the second to find it
      const slow = join(h.root, "slow");
      await mkdir(slow, { recursive: true });
      await writeExec(join(slow, "zstd"), `#!/bin/sh\nsleep 4\nexec "${ZSTD}" "$@"\n`);
      const first = h.cadence("archive", {
        TOUCHLINE_CADENCE_PATH: `${slow}:${h.env.TOUCHLINE_CADENCE_PATH}`,
      });
      const deadline = Date.now() + 10_000;
      while (Date.now() < deadline) {
        if (existsSync(h.logFile) && (await h.log()).includes("archive: writing")) break;
        await Bun.sleep(100);
      }
      const second = await h.cadence("archive");
      expect(second.code).toBe(0);
      const r1 = await first;
      expect(r1.code).toBe(0);

      const log = await h.log();
      expect(log).toMatch(/cadence already running \(pid \d+\) — exiting without work\./);
      expect(log).toContain(
        `touchline cadence: mode=archive season=${SEASON} gender=${GENDER} conferences=[]`,
      );
      expect(log).not.toMatch(/\] collect /);
      expect(log).not.toContain("sweeping leftovers");
      expect(log).not.toContain("data home push");
      expect(log).toMatch(/archive 2026 men GAC: 4 file\(s\)/);
      expect(log).toMatch(/archive 2026 men LSC: 4 file\(s\)/);
      expect((log.match(/run summary:/g) ?? []).length).toBe(1);
      // nothing but the archive: no keelson, no bun, no just
      expect(await h.calls()).toBe("");
      expect(await h.git(h.data, "status", "--porcelain")).toContain("?? data/coverage.json");

      const records = await h.records();
      expect(records).toHaveLength(1);
      expect(records[0].mode).toBe("archive");
      expect(records[0].conferences).toEqual([]);
      expect(records[0].collect).toEqual({});
      expect(records[0].data_push).toBe("skipped");
      expect(records[0].publish).toBe("skipped (no change)");
      expect(records[0].archive).toMatch(/^ok /);
      expect(records[0].exit).toBe(0);
      expect(existsSync(join(h.home, ".keelson", "locks", "touchline-collect-cadence.lock"))).toBe(
        false,
      );
    },
    60_000,
  );

  test("(f) without zstd on PATH, loop mode dies in preflight naming it and collect mode does not", async () => {
    const h = await makeHarness();
    // every executable the real PATH offers except zstd and its siblings
    const nozstd = join(h.root, "nozstd");
    await mkdir(nozstd, { recursive: true });
    const seen = new Set<string>();
    for (const dir of (process.env.PATH ?? "/usr/bin:/bin").split(":")) {
      let names: string[] = [];
      try {
        names = await readdir(dir);
      } catch {
        continue;
      }
      for (const name of names) {
        if (seen.has(name) || name.startsWith("zstd") || name === "unzstd") continue;
        seen.add(name);
        try {
          await symlink(join(dir, name), join(nozstd, name));
        } catch {}
      }
    }
    const env = { TOUCHLINE_CADENCE_PATH: `${h.fakes}:${nozstd}`, TOUCHLINE_CONFERENCES: "GAC" };

    const loop = await h.cadence("loop", { ...env, CADENCE_FAKE_PLAN: "GAC=churn" });
    expect(loop.code).toBe(1);
    expect(await h.log()).toContain("FATAL: required tool 'zstd' is not on PATH");
    expect(await h.records()).toHaveLength(0);

    const collect = await h.cadence("collect", { ...env, CADENCE_FAKE_PLAN: "GAC=churn" });
    expect(collect.code).toBe(0);
    const [rec] = await h.records();
    expect(rec.mode).toBe("collect");
    expect(rec.collect).toEqual({ GAC: "no-change" });
  });
});

describe("bin/touchline-collect-cadence.shim.sh", () => {
  test("resolves the package from the keelson rib config and execs the packaged script", async () => {
    const h = await makeHarness();
    const r = await run(["/bin/sh", h.shim, "version"], h.env, h.root);
    expect(r.code).toBe(0);
    // the script prints its physical path (pwd -P): macOS tmp dirs are symlinked
    expect(r.stdout).toContain(`script=${realpathSync(h.pkg)}/bin/touchline-collect-cadence.sh`);
    expect(r.stdout).toContain("version=9.9.9-test");
  });

  test("passes the mode through: collect via the shim behaves as collect", async () => {
    const h = await makeHarness();
    const r = await run(
      ["/bin/sh", h.shim, "collect"],
      { ...h.env, TOUCHLINE_CONFERENCES: "GAC", CADENCE_FAKE_PLAN: "GAC=churn" },
      h.root,
    );
    expect(r.code).toBe(0);
    const [rec] = await h.records();
    expect(rec.mode).toBe("collect");
    expect(rec.collect).toEqual({ GAC: "no-change" });
  });

  test("fails loudly to the cadence log when the packaged script is missing", async () => {
    const h = await makeHarness();
    // a package dir that passes the membership check but ships no cadence script
    const bare = join(h.root, "bare-pkg");
    await mkdir(join(bare, "src"), { recursive: true });
    await writeFile(join(bare, "src", "membership.ts"), "");
    await writeFile(
      join(h.home, ".keelson", "rib-touchline", "config.json"),
      JSON.stringify({ packageDir: bare }),
    );
    const r = await run(["/bin/sh", h.shim, "version"], h.env, h.root);
    expect(r.code).toBe(1);
    expect(r.stderr).toContain(
      `FATAL: cadence shim: packaged script not found at ${bare}/bin/touchline-collect-cadence.sh`,
    );
    expect(await h.log()).toContain("FATAL: cadence shim: packaged script not found at");
  });

  test("falls back to the harness node_modules copy when the config names no usable package", async () => {
    const h = await makeHarness();
    const fallback = join(h.home, ".keelson", "node_modules", "@keelson", "rib-touchline");
    await mkdir(join(fallback, "bin"), { recursive: true });
    await mkdir(join(fallback, "src"), { recursive: true });
    await writeFile(join(fallback, "src", "membership.ts"), "");
    await writeFile(join(fallback, "package.json"), JSON.stringify({ version: "0.0.0-fallback" }));
    await writeExec(
      join(fallback, "bin", "touchline-collect-cadence.sh"),
      await readFile(h.script, "utf8"),
    );
    await writeFile(join(h.home, ".keelson", "rib-touchline", "config.json"), JSON.stringify({}));
    const r = await run(["/bin/sh", h.shim, "version"], h.env, h.root);
    expect(r.code).toBe(0);
    expect(r.stdout).toContain("version=0.0.0-fallback");
    expect(r.stdout).toContain(
      "node_modules/@keelson/rib-touchline/bin/touchline-collect-cadence.sh",
    );
  });
});
