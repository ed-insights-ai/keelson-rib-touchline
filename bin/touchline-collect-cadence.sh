#!/bin/sh
# Touchline daily cadence (beads tl-z1j, tl-1of, tl-d8r) — keeps the d2-soccer
# season board tracking the published record, and the public site tracking the
# board, without a human asking.
#
# Fired daily at 06:30 by launchd
# (~/Library/LaunchAgents/ai.edinsights.touchline-collect.plist), which
# redirects stdout+stderr to ~/.keelson/logs/touchline-collect-cadence.log.
# The plist is untouched by tl-1of/tl-d8r: the same trigger now runs the whole
# loop. A manual run is the same thing: sh touchline-collect-cadence.sh
#
# This file is the versioned copy (beads tl-cpn): it ships in the rib package
# at bin/touchline-collect-cadence.sh, and the launchd path
# (~/.keelson/scripts/touchline-collect-cadence.sh) holds only the shim
# bin/touchline-collect-cadence.shim.sh, which resolves the installed package
# and execs this script. Upgrading the rib upgrades the cadence.
#
# The loop (house process — one conference-season per collect invocation):
#   1. COLLECT  each configured conference sequentially through the keelson
#               `touchline-collect` workflow. One conference failing is logged
#               and its partial writes rolled back (that conference's paths
#               only, see restore_conference); the others still run.
#   2. DETECT   per conference, from the data home's git state. Every collect
#               rewrites the four board files' collected_at stamp, so "any
#               diff" would journal daily forever; a real change is a diff
#               BEYOND that stamp (or a new board file). Real change -> commit
#               in the data home (collects are the only writer there, and the
#               collect step owns its commits). Stamp-only churn -> rolled
#               back, so a quiet day leaves no commit and spends nothing.
#   3. JOURNAL  regenerate only the changed conferences (`bun run journal run
#               --conference <key> --write` in touchline-ui, as a consumer of
#               its recipes). EACH CALL IS A LIVE MODEL CALL (claude -p): at
#               most one per changed conference per run, every one logged. A
#               journal failure or dropped claims never block the loop — the
#               site is built to keep the previous journal.
#   3b. COMMIT  the regenerated journal/*.json + *.validation.json in
#               touchline-ui (tl-151). The journals are model output, not
#               reproducible from the data; leaving them uncommitted put the
#               deployed site ahead of its own source. Committed on main only
#               (any other checkout is logged and skipped), then pushed —
#               a push failure is loud but never blocks the publish.
#   4. PUBLISH  once at the end, only if a conference changed: `just publish`
#               in touchline-ui. Its recipe already rebuilds with the base
#               path, link-checks the artefact, pushes gh-pages, and asserts
#               the DEPLOYED host serves correctly — that gate is trusted
#               here, not duplicated (so no separate `just build` first).
#               A publish failure is loud: logged and exits non-zero.
#   5. PUSH     the data home's branch (tl-151, full loop only): every commit
#               ahead of upstream is pushed, so the collected record leaves
#               this machine without a hand reconciliation.
#   6. ARCHIVE  (tl-ttj, full loop only, on the archive day: `date +%u`
#               equals TOUCHLINE_ARCHIVE_DAY, default 7, Sunday; 0 disables,
#               `always` forces) the raw HTML fetch cache, data/raw_html, is
#               no longer tracked by the data home, so once a week it is
#               tarred as tar.zst per (season, gender, conference) plus one
#               unassigned tarball for anything on disk no cell claims, under
#               TOUCHLINE_ARCHIVE_DIR (default ~/keelson/archive/raw-html),
#               one dated directory per run, newest four complete kept. A
#               failure is a WARNING and exit 1, never a stop.
#
# Modes:  (no argument)   the full loop — what launchd runs.
#         collect         collect+detect only, no journal/build/publish.
#                         touchline-ui's justfile delegates its collect step
#                         to this script; set
#                           TOUCHLINE_COLLECT_CMD="sh <this script> collect"
#                         there so `just` does not run the journal twice.
#         archive         the archive step only, under the same PID lock,
#                         regardless of the day: no collect, no journal, no
#                         publish, no push. The way to take a tarball set
#                         by hand or to catch up a missed Sunday.
#         version         print the packaged script path and its version
#                         (package.json version, git describe when the
#                         package is a checkout) and exit 0. No lock, no
#                         log, no collect: the way to prove the shim resolves.
#
# Run record: every completed run appends one JSON line to
# ~/.keelson/logs/touchline-cadence-runs.jsonl (TOUCHLINE_CADENCE_RUNS_FILE
# overrides the path) carrying what the run summary line carries plus the
# data home HEAD, the push result and the deployed build stamp.
#
# Conference membership is DATA, not code: programme lists resolve at run time
# from the rib's data/reference/membership.json (the same file the pipeline
# reads), carrying the last authored window forward when the season is beyond
# it — nothing here hardcodes a member list. The conference set and season are
# overridable: TOUCHLINE_CONFERENCES, TOUCHLINE_SEASON, TOUCHLINE_GENDER.
#
# The college-soccer season is the calendar year of its fall semester: from
# June onward collect the current year, January–May still means last fall's
# season, so a spring wake-up refreshes the archive instead of asking the
# sites for a season that does not exist yet.
#
# Non-interactive by construction: absolute PATH, no prompts, a PID lock so a
# double fire is a logged no-op, and change detection that makes a re-run of
# an already-collected day converge to "nothing to do".
#
# Two locks (bead tl-5go). The PID lock above serialises cadence starts, and
# the touchline-backfill workflow's preflight refuses while it is live. The
# data home itself is guarded by keelson: touchline-collect and
# touchline-backfill both declare mutates_checkout, so the server holds one
# exclusive per-project mutation lock across them and a collect started while
# a backfill holds it fails at start with HTTP 409 and the envelope
#   {"error":"project <id> is locked by <owner> for \"<purpose>\"","code":"REQUEST_FAILED"}
# (workspace_lease is a worktree lease, not a mutex, and is not used here).
# Before the sweep this script asks `keelson workflow status --json` whether
# such a run is already in flight and, if so, exits 0 naming it, so the sweep
# and the rollbacks never touch a data home another run is writing. A collect
# refused by that lock mid-run is reported as `locked`, never rolled back.
set -u
# Absolute PATH: launchd hands the script almost none. TOUCHLINE_CADENCE_PATH
# is the test harness's way to put its fakes first; unset, nothing changes.
PATH="${TOUCHLINE_CADENCE_PATH:-/Users/danielscholl/.local/bin:/Users/danielscholl/.bun/bin:/opt/homebrew/bin:/usr/bin:/bin}"
export PATH
umask 022

HOME_DIR="${HOME:-/Users/danielscholl}"
DATA_HOME="${TOUCHLINE_DATA_HOME:-$HOME_DIR/keelson/d2-soccer}"
UI_DIR="${TOUCHLINE_UI_DIR:-$HOME_DIR/edinsights-ai/project/touchline-ui}"
CONFERENCES="${TOUCHLINE_CONFERENCES:-}"
GENDER="${TOUCHLINE_GENDER:-men}"
LOG_FILE="$HOME_DIR/.keelson/logs/touchline-collect-cadence.log"
RUNS_FILE="${TOUCHLINE_CADENCE_RUNS_FILE:-$HOME_DIR/.keelson/logs/touchline-cadence-runs.jsonl}"
# TOUCHLINE_CADENCE_LOCK_DIR is the test harness's override; the backfill
# workflow's preflight reads the same path (and the same override) to refuse
# while the cadence is running.
LOCK_DIR="${TOUCHLINE_CADENCE_LOCK_DIR:-$HOME_DIR/.keelson/locks/touchline-collect-cadence.lock}"
RIB_CFG="$HOME_DIR/.keelson/rib-touchline/config.json"
MODE="${1:-loop}"
STARTED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$LOCK_DIR")"

# ── logging ──────────────────────────────────────────────────────────────────
# Every run lands in the one log exactly once: lines are appended straight to
# LOG_FILE, and echoed to stdout only when stdout is a terminal (a manual run
# being watched). The old detection — [ /dev/fd/1 -ef "$LOG_FILE" ] — can never
# be true on macOS: fdescfs gives /dev/fd/1 its own device and inode, so under
# launchd (stdout redirected to the log) the check failed and every line was
# written twice, once by the redirect and once by the append.
log() {
  _line="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  printf '%s\n' "$_line" >>"$LOG_FILE"
  if [ -t 1 ]; then printf '%s\n' "$_line"; fi
}
logblock() { # indent stdin into the log, line by line
  while IFS= read -r _l || [ -n "$_l" ]; do log "    $_l"; done
}
die() { log "FATAL: $*"; exit 1; }

case "$MODE" in loop|collect|archive|version) ;; *) die "unknown mode '$MODE' — use no argument (full loop), 'collect', 'archive' or 'version'." ;; esac

# ── version: prove the shim resolves without taking the lock or collecting ──
if [ "$MODE" = "version" ]; then
  SELF=$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)/$(basename "$0")
  PKG=$(cd "$(dirname "$0")/.." 2>/dev/null && pwd -P)
  PKG_VERSION=$(jq -r '.version // "unknown"' "$PKG/package.json" 2>/dev/null || printf 'unknown')
  PKG_DESCRIBE=$(git -C "$PKG" describe --tags --always --dirty 2>/dev/null || printf 'not a checkout')
  printf 'touchline-collect-cadence: script=%s package=%s version=%s git=%s\n' \
    "$SELF" "$PKG" "${PKG_VERSION:-unknown}" "${PKG_DESCRIBE:-not a checkout}"
  exit 0
fi

# ── season ───────────────────────────────────────────────────────────────────
YEAR=$(date +%Y)
MONTH=$(date +%m)
MONTH=${MONTH#0}
if [ "$MONTH" -lt 6 ]; then
  SEASON=$((YEAR - 1))
else
  SEASON=$YEAR
fi
SEASON="${TOUCHLINE_SEASON:-$SEASON}"

# ── lock: a double fire is a no-op, a dead run's lock is not a jail ─────────
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  OTHER=$(cat "$LOCK_DIR/pid" 2>/dev/null || printf '')
  if [ -n "$OTHER" ] && kill -0 "$OTHER" 2>/dev/null; then
    log "cadence already running (pid $OTHER) — exiting without work."
    exit 0
  fi
  log "stale lock (pid ${OTHER:-unknown} gone) — taking over."
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || die "cannot take the cadence lock at $LOCK_DIR"
fi
printf '%s\n' "$$" >"$LOCK_DIR/pid"
# PROG_CACHE holds one membership resolution per conference for the whole run
# (the sweep attribution and the collect loop share it).
PROG_CACHE=$(mktemp -d)
trap 'rm -rf "$LOCK_DIR" "$PROG_CACHE"' EXIT
trap 'rm -rf "$LOCK_DIR" "$PROG_CACHE"; exit 130' INT TERM

# ── preflight ────────────────────────────────────────────────────────────────
for tool in git jq bun keelson; do
  command -v "$tool" >/dev/null 2>&1 || die "required tool '$tool' is not on PATH ($PATH)"
done
[ -f "$DATA_HOME/touchline-data.yaml" ] || die "$DATA_HOME is not a Touchline data home (no touchline-data.yaml)"
git -C "$DATA_HOME" rev-parse --git-dir >/dev/null 2>&1 || die "$DATA_HOME is not a git repository — change detection needs one"
if [ "$MODE" = "loop" ]; then
  command -v just >/dev/null 2>&1 || die "required tool 'just' is not on PATH"
  [ -f "$UI_DIR/justfile" ] || die "touchline-ui not found at $UI_DIR (no justfile)"
fi
# the archive step (loop and archive modes) compresses through zstd; tar is
# assumed, zstd is not (Homebrew on the machine, the zstd package on CI)
if [ "$MODE" = "loop" ] || [ "$MODE" = "archive" ]; then
  command -v zstd >/dev/null 2>&1 || die "required tool 'zstd' is not on PATH ($PATH)"
fi

log "touchline cadence: mode=$MODE season=$SEASON gender=$GENDER conferences=[$CONFERENCES] data_home=$DATA_HOME"

# ── membership: conference -> programme slugs, resolved from data ────────────
rib_package_dir() {
  _pkg=""
  if [ -f "$RIB_CFG" ]; then
    _pkg=$(jq -r '.packageDir // empty' "$RIB_CFG" 2>/dev/null)
  fi
  if [ -z "$_pkg" ] || [ ! -f "$_pkg/src/membership.ts" ]; then
    _pkg="$HOME_DIR/.keelson/node_modules/@keelson/rib-touchline"
  fi
  printf '%s\n' "$_pkg"
}

# conference set: every conference the membership record authors a window for
# this gender, unless TOUCHLINE_CONFERENCES pins it (rib bin/resolve-membership.ts).
# archive mode collects nothing and reads its membership from the data home
# (see archive_rows), so it never resolves the set.
if [ -z "$CONFERENCES" ] && [ "$MODE" != "archive" ]; then
  CONFERENCES=$(bun "$(rib_package_dir)/bin/resolve-membership.ts" conferences "$GENDER" 2>&1) \
    || die "cannot resolve the conference set from membership: $CONFERENCES"
  log "touchline cadence: conferences resolved from membership: [$CONFERENCES]"
fi

resolve_programmes() { # $1 = conference; prints "true|false slug1,slug2,…"
  RESOLVE_PKG=$(rib_package_dir) \
  RESOLVE_CONF="$1" RESOLVE_GENDER="$GENDER" RESOLVE_SEASON="$SEASON" \
  bun -e '
    const { resolveConference } = await import(process.env.RESOLVE_PKG + "/src/membership.ts");
    const r = await resolveConference(
      process.env.RESOLVE_CONF, process.env.RESOLVE_GENDER, Number(process.env.RESOLVE_SEASON));
    if (!r.slugs.length) {
      console.error("no members resolve for " + process.env.RESOLVE_CONF +
        " " + process.env.RESOLVE_GENDER + " " + process.env.RESOLVE_SEASON +
        " (known: " + r.known.join(",") + ")");
      process.exit(1);
    }
    console.log((r.extrapolated ? "true" : "false") + " " + r.slugs.join(","));
  '
}

# One live resolution per conference per run: the first caller pays, every
# later one (the sweep attribution, then the collect loop) reads the cached
# output and exit code back.
resolve_programmes_cached() { # $1 = conference; same output and rc as resolve_programmes
  _cf="$PROG_CACHE/$1"
  if [ ! -f "$_cf.rc" ]; then
    resolve_programmes "$1" >"$_cf" 2>&1
    printf '%s' "$?" >"$_cf.rc"
  fi
  cat "$_cf"
  return "$(cat "$_cf.rc")"
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# ── change detection ─────────────────────────────────────────────────────────
# Real change = a new board file, or a board-file diff with any line beyond
# the top-level collected_at stamp. Board files only; coverage and errors
# churn on every fetch and are committed alongside a real change, never
# counted as one. raw_html churns the same way but is no longer tracked
# (tl-ttj): the pages live on disk as the collector's fetch cache and in the
# weekly archive (step 6), not in the data home's git history.
has_signal() { # $1 = lowercase conference key
  _lc="$1"
  set -- "data/fixtures/${SEASON}-${GENDER}-${_lc}.json" \
         "data/rosters/${SEASON}-${GENDER}-${_lc}.json" \
         "data/stats/${SEASON}-${GENDER}-${_lc}.json" \
         "data/matches/${SEASON}-${GENDER}-${_lc}.json"
  if git -C "$DATA_HOME" status --porcelain -- "$@" 2>/dev/null | grep -q '^??'; then return 0; fi
  if git -C "$DATA_HOME" diff HEAD -U0 -- "$@" 2>/dev/null \
      | grep -e '^+' -e '^-' \
      | grep -v -e '^+++' -e '^---' \
      | grep -v '"collected_at"' \
      | grep -q .; then return 0; fi
  return 1
}

# Scoped rollback (tl-5go): a churned or failed collect is undone for the
# collected conference's paths and nothing else, so a write another run left
# in the data home is never reset by this one. The paths are
#   data/{fixtures,rosters,stats,matches}/<season>-<gender>-<lc>.json
#   data/errors/collect-board-<season>-<gender>-<lc>.json
#   data/raw_html/<slug>/<season>-<gender>-*        for each resolved slug
#   data/coverage.json
# coverage.json is one shared manifest for every conference, so restoring it
# is all-or-nothing: the churn this collect wrote to it goes, and so would a
# line another conference's collect had written since the last commit (inside
# one run there is none: every successful collect commits before the next
# starts). Only paths git reports dirty are touched, so a path that does not
# exist is fine: tracked ones go back to HEAD, untracked ones are cleaned.
restore_conference() { # $1 = lowercase conference key, $2 = comma-separated programme slugs
  _lc="$1"
  _slugs="${2:-}"
  set -- "data/fixtures/${SEASON}-${GENDER}-${_lc}.json" \
         "data/rosters/${SEASON}-${GENDER}-${_lc}.json" \
         "data/stats/${SEASON}-${GENDER}-${_lc}.json" \
         "data/matches/${SEASON}-${GENDER}-${_lc}.json" \
         "data/errors/collect-board-${SEASON}-${GENDER}-${_lc}.json" \
         "data/coverage.json"
  for _slug in $(printf '%s' "$_slugs" | tr ',' ' '); do
    set -- "$@" "data/raw_html/$_slug/${SEASON}-${GENDER}-*"
  done
  git -C "$DATA_HOME" status --porcelain -uall -- "$@" 2>/dev/null >"$PROG_CACHE/restore"
  while IFS= read -r _l || [ -n "$_l" ]; do
    _p=${_l#???}
    case "$_l" in
      # -d: without it git clean skips a file that sits in an untracked
      # directory (a slug's first raw page); the path limits it to that file.
      '??'*) git -C "$DATA_HOME" clean -qfd -- "$_p" ;;
      *) git -C "$DATA_HOME" checkout -q HEAD -- "$_p" ;;
    esac
  done <"$PROG_CACHE/restore"
  # a slug directory the cleaned pages leave empty goes too (git never tracked it)
  for _slug in $(printf '%s' "$_slugs" | tr ',' ' '); do
    rmdir "$DATA_HOME/data/raw_html/$_slug" 2>/dev/null || true
  done
}

# Sweep attribution (tl-5go): names the owner of every dirty path the pre-run
# sweep is about to commit. Board and errors files carry the conference in
# their <season>-<gender>-<conf> suffix, raw_html pages belong to whichever
# conference in this run's set resolves their slug, coverage.json is shared
# by every conference, and anything else is unattributed.
attribute_path() { # $1 = path relative to the data home; prints the lowercase key, "shared" or nothing
  case "$1" in
    data/coverage.json) printf 'shared'; return 0 ;;
    data/fixtures/*.json|data/rosters/*.json|data/stats/*.json|data/matches/*.json|data/errors/collect-board-*.json)
      _b=${1##*/}; _b=${_b%.json}; _b=${_b#collect-board-}
      _k=${_b#*-}; _k=${_k#*-} # drop <season>- then <gender>-; a key may itself carry a dash (g-mac)
      for _c in $CONFERENCES; do
        if [ "$(lower "$_c")" = "$_k" ]; then printf '%s' "$_k"; return 0; fi
      done
      return 0 ;;
    data/raw_html/*/*)
      _s=${1#data/raw_html/}; _s=${_s%%/*}
      for _c in $CONFERENCES; do
        _r=$(resolve_programmes_cached "$_c") || continue
        case ",${_r#* }," in *",$_s,"*) lower "$_c"; return 0 ;; esac
      done
      return 0 ;;
  esac
  return 0
}

commit_home() { # $1 = message
  git -C "$DATA_HOME" add -A
  if git -C "$DATA_HOME" diff --cached --quiet; then
    log "  nothing staged to commit."
    return 0
  fi
  git -C "$DATA_HOME" commit -q -m "$1" || log "  WARNING: commit in $DATA_HOME failed"
}

mark_changed() { # $1 = lowercase key, deduplicated
  case " ${CHANGED:-} " in *" $1 "*) ;; *) CHANGED="${CHANGED:-} $1" ;; esac
  CHANGED=${CHANGED# }
}

# ── bounded run: the journal's model call is the one leg with no timeout of
#    its own; cap it so a hung call cannot jail tomorrow's run ────────────────
capped() { # $1 = seconds, rest = command; returns 124 on timeout
  _cap=$1; shift
  ( "$@" ) &
  _cpid=$!
  _t=0
  while kill -0 "$_cpid" 2>/dev/null; do
    if [ "$_t" -ge "$_cap" ]; then
      kill "$_cpid" 2>/dev/null
      sleep 2
      kill -9 "$_cpid" 2>/dev/null
      wait "$_cpid" 2>/dev/null
      return 124
    fi
    sleep 5
    _t=$((_t + 5))
  done
  wait "$_cpid"
}

# shellcheck disable=SC2317 # invoked indirectly through capped.
journal_leg() { cd "$UI_DIR" && bun run journal run --conference "$JR_KEYS" --write; }
# The national leg runs AFTER the conference legs: its brief reads the cards'
# lines and the wires, so it must see today's conference journals (justfile
# `journal` orders them the same way). One more model call per run.
# shellcheck disable=SC2317 # invoked indirectly through capped.
national_leg() { cd "$UI_DIR" && bun run journal run --national --write; }

# ── build stamp: the deployed site's touchline-build meta, read from the
#    artefact `just publish` built, so the run record names the build it
#    shipped ─────────────────────────────────────────────────────────────────
build_stamp() { # prints the meta content, or nothing
  [ -f "$UI_DIR/dist/index.html" ] || return 0
  grep -o '<meta[^>]*name="touchline-build"[^>]*>' "$UI_DIR/dist/index.html" 2>/dev/null \
    | sed -n 's/.*content="\([^"]*\)".*/\1/p' | head -1
}

# ── archive (tl-ttj): the raw HTML fetch cache, weekly, as tar.zst ───────────
# data/raw_html left the data home's index (gitignored, history kept), so the
# pages the collector fetched exist only on this disk. On the archive day the
# loop, or the `archive` mode any day, writes
#   $ARCHIVE_ROOT/<YYYY-MM-DD>/<season>-<gender>-<conf>.tar.zst
# per (season, gender, conference) with paths relative to the data home
# (data/raw_html/<slug>/<season>-<gender>-*, the .state.json sidecars
# included), then <date>/unassigned.tar.zst for every file under data/raw_html
# no cell claimed, then a .done marker, and keeps the newest four complete
# dated directories. Every tarball is written to <name>.tmp and moved into
# place; a run that fails leaves no .done, and the next retention pass removes
# the directory.
#
# Membership is DATA read from the data home, not a live resolution: the
# coverage manifest says which (season, gender, programme) cells this home
# collected, and the fixtures board of that season and gender says which
# conference collected the programme. jq paths (schema touchline.coverage/1):
#   data/coverage.json                     .cells[] | .season, .gender, .programme
#   data/fixtures/<season>-<gender>-<conf>.json
#                                          .season, .gender, .conference, .programmes[].slug
# A coverage cell carries no conference field, hence the join through the
# board the same collect wrote. A slug two boards of one season name goes to
# the first by conference key; a cell no board names, a slug no cell names, a
# page older than coverage, a disabled or dead-host stanza's pages: all land
# in unassigned.tar.zst, so nothing on disk is left out.
ARCHIVE_ROOT="${TOUCHLINE_ARCHIVE_DIR:-$HOME_DIR/keelson/archive/raw-html}"
ARCHIVE_DAY="${TOUCHLINE_ARCHIVE_DAY:-7}"
ARCHIVE_KEEP=4

hsize() { du -sh "$1" | cut -f1 | tr -d ' '; } # BSD du pads the column

archive_fail() { # $1 = reason; a WARNING and exit 1 at the end, never a stop
  log "WARNING: archive FAILED ($1); no .done marker is written, the next retention pass removes the directory."
  ARCHIVE_RESULT="FAILED ($1)"
  RUN_RC=1
}

archive_rows() { # prints "season gender CONF slug" rows, one per (cell, slug) the data home claims
  set --
  for _f in "$DATA_HOME"/data/fixtures/*.json; do
    [ -f "$_f" ] && set -- "$@" "$_f"
  done
  [ $# -gt 0 ] || return 0
  jq -r -n --slurpfile cov "$DATA_HOME/data/coverage.json" '
    ([$cov[0].cells // {} | .[]
        | select(.season != null and .gender != null and .programme != null)
        | "\(.season) \(.gender) \(.programme)"]
      | map({key: ., value: true}) | from_entries) as $cells
    | [inputs
        | select(.conference != null and .season != null and .gender != null)
        | (.season | tostring) as $s | .gender as $g | .conference as $c
        | (.programmes // [])[] | select(.slug != null)
        | {k: "\($s) \($g) \(.slug)", s: $s, g: $g, c: $c, slug: .slug}]
    | sort_by(.k, .c) | group_by(.k) | map(.[0])
    | .[] | select($cells[.k] == true)
    | "\(.s) \(.g) \(.c) \(.slug)"' "$@"
}

archive_tarball() { # $1 = target .tar.zst, $2 = file list relative to the data home
  rm -f "$1.tmp" "$ARCH/tar.err"
  # the pipeline's status is zstd's, so tar reports through the sentinel file
  (tar -C "$DATA_HOME" -cf - -T "$2" 2>"$ARCH/tar.err" || printf 'tar exit %s\n' "$?" >>"$ARCH/tar.err") \
    | zstd -q -T0 -o "$1.tmp" 2>>"$ARCH/tar.err"
  _zrc=$?
  if [ "$_zrc" -ne 0 ] || [ -s "$ARCH/tar.err" ]; then
    rm -f "$1.tmp"
    archive_fail "${1##*/}: $(head -1 "$ARCH/tar.err" 2>/dev/null | tr -d '\n'; [ "$_zrc" -ne 0 ] && printf ' zstd exit %s' "$_zrc")"
    return 1
  fi
  mv "$1.tmp" "$1" || { archive_fail "cannot move $1.tmp into place"; return 1; }
}

archive_retention() { # newest four complete dated directories stay; incomplete ones go
  _n=0
  _k=0
  find "$ARCHIVE_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sed 's|.*/||' \
    | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | LC_ALL=C sort -r >"$ARCH/dated"
  while IFS= read -r _d || [ -n "$_d" ]; do
    [ -n "$_d" ] || continue
    _n=$((_n + 1))
    if [ ! -f "$ARCHIVE_ROOT/$_d/.done" ]; then
      rm -rf "${ARCHIVE_ROOT:?}/${_d:?}" && log "archive retention: removed $ARCHIVE_ROOT/$_d (incomplete, no .done marker)"
    elif [ "$_k" -ge "$ARCHIVE_KEEP" ]; then
      rm -rf "${ARCHIVE_ROOT:?}/${_d:?}" && log "archive retention: removed $ARCHIVE_ROOT/$_d (beyond the newest $ARCHIVE_KEEP)"
    else
      _k=$((_k + 1))
    fi
  done <"$ARCH/dated"
  log "archive retention: kept $_k of $_n"
}

archive_gate() { # loop mode only: is today the archive day? logs the skip otherwise
  _u=$(date +%u)
  case "$ARCHIVE_DAY" in
    always) return 0 ;;
    0) ARCHIVE_RESULT="skipped (disabled; archive day 0, today is $_u)" ;;
    [1-7])
      [ "$_u" = "$ARCHIVE_DAY" ] && return 0
      ARCHIVE_RESULT="skipped (not archive day; today is $_u, archive day $ARCHIVE_DAY)" ;;
    *)
      log "WARNING: TOUCHLINE_ARCHIVE_DAY='$ARCHIVE_DAY' is not 0-7 or 'always'; archive skipped."
      ARCHIVE_RESULT="skipped (TOUCHLINE_ARCHIVE_DAY='$ARCHIVE_DAY' invalid)"
      RUN_RC=1 ;;
  esac
  log "archive: $ARCHIVE_RESULT"
  return 1
}

archive_step() {
  ARCHIVE_DATE=$(date +%Y-%m-%d)
  ARCHIVE_OUT="$ARCHIVE_ROOT/$ARCHIVE_DATE"
  ARCH="$PROG_CACHE/archive"
  if ! mkdir -p "$ARCH" "$ARCHIVE_OUT" 2>/dev/null; then
    archive_fail "cannot create $ARCHIVE_OUT"
    return 0
  fi
  rm -f "$ARCHIVE_OUT/.done" # a second run today is incomplete until it finishes
  log "archive: writing $ARCHIVE_OUT from $DATA_HOME/data/raw_html"
  if [ ! -f "$DATA_HOME/data/coverage.json" ]; then
    log "archive: no data/coverage.json in the data home; every page on disk is unassigned."
    : >"$ARCH/rows"
  elif ! archive_rows >"$ARCH/rows" 2>"$ARCH/rows.err"; then
    archive_fail "membership rows: $(head -1 "$ARCH/rows.err" | tr -d '\n')"
    return 0
  fi
  # one slug list per cell, cells sorted by season, gender, conference
  : >"$ARCH/cells"
  rm -f "$ARCH"/slugs.* "$ARCH"/list.*
  while read -r _s _g _c _slug; do
    [ -n "$_slug" ] || continue
    printf '%s %s %s\n' "$_s" "$_g" "$_c" >>"$ARCH/cells"
    printf '%s\n' "$_slug" >>"$ARCH/slugs.${_s}-${_g}-$(lower "$_c")"
  done <"$ARCH/rows"
  LC_ALL=C sort -u -o "$ARCH/cells" "$ARCH/cells"
  : >"$ARCH/claimed"
  N_TARBALLS=0
  while read -r _s _g _c; do
    [ -n "$_c" ] || continue
    _cell="${_s}-${_g}-$(lower "$_c")"
    _list="$ARCH/list.$_cell"
    (cd "$DATA_HOME" && while read -r _slug; do
      [ -d "data/raw_html/$_slug" ] && find "data/raw_html/$_slug" -maxdepth 1 -type f -name "${_s}-${_g}-*"
    done <"$ARCH/slugs.$_cell") | LC_ALL=C sort -u >"$_list"
    _n=$(wc -l <"$_list" | tr -d ' ')
    if [ "$_n" -eq 0 ]; then
      log "archive $_s $_g $_c: no raw pages on disk, skipped."
      continue
    fi
    archive_tarball "$ARCHIVE_OUT/$_cell.tar.zst" "$_list" || return 0
    cat "$_list" >>"$ARCH/claimed"
    N_TARBALLS=$((N_TARBALLS + 1))
    log "archive $_s $_g $_c: $_n file(s), $(hsize "$ARCHIVE_OUT/$_cell.tar.zst")"
  done <"$ARCH/cells"
  # nothing on disk may be left out: the sorted claimed set against every file
  (cd "$DATA_HOME" && [ -d data/raw_html ] && find data/raw_html -type f) | LC_ALL=C sort -u >"$ARCH/all"
  LC_ALL=C sort -u -o "$ARCH/claimed" "$ARCH/claimed"
  LC_ALL=C comm -13 "$ARCH/claimed" "$ARCH/all" >"$ARCH/unassigned"
  _n=$(wc -l <"$ARCH/unassigned" | tr -d ' ')
  if [ "$_n" -eq 0 ]; then
    log "archive unassigned: none"
  else
    archive_tarball "$ARCHIVE_OUT/unassigned.tar.zst" "$ARCH/unassigned" || return 0
    N_TARBALLS=$((N_TARBALLS + 1))
    sed -e 's|^data/raw_html/||' -e 's|/.*||' "$ARCH/unassigned" | LC_ALL=C sort -u >"$ARCH/unassigned.slugs"
    _k=$(wc -l <"$ARCH/unassigned.slugs" | tr -d ' ')
    log "archive unassigned: $_n file(s) across $_k slug(s) ($(head -3 "$ARCH/unassigned.slugs" | paste -sd ',' - | sed 's/,/, /g')), $(hsize "$ARCHIVE_OUT/unassigned.tar.zst")"
  fi
  : >"$ARCHIVE_OUT/.done"
  ARCHIVE_SIZE=$(hsize "$ARCHIVE_OUT")
  log "archive total: $N_TARBALLS tarball(s), $ARCHIVE_SIZE, $ARCHIVE_OUT"
  ARCHIVE_RESULT="ok $ARCHIVE_OUT $ARCHIVE_SIZE"
  archive_retention
}

# ── state ────────────────────────────────────────────────────────────────────
ARCHIVE_RESULT="skipped (not reached)"
CHANGED=""
JOURNALED=""
COLLECT_SUMMARY=""
FAILED_COLLECTS=""
LOCKED_COLLECTS=""
BUSY=""
JOURNAL_SPEND=0
PUBLISH_RESULT="skipped (no change)"
JOURNAL_COMMIT="none"
DATA_PUSH="skipped"
BUILD_STAMP=""
RUN_RC=0

# ── run record and summary: the same run as data (one JSON line) and as the
#    log's last line. Called at the end of every run that got past preflight,
#    the busy exit included, so tomorrow's reader sees the cause on one line.
#    data_head is the data home's HEAD after the push step (the pre-run value
#    when this mode never pushes). Written before the summary line so a
#    reader of either sees the same run; a record that cannot be written is
#    a WARNING, never a changed exit code. ──────────────────────────────────
finish_run() {
  DATA_HEAD=$(git -C "$DATA_HOME" rev-parse --short HEAD 2>/dev/null || printf 'unknown')
  FINISHED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  if RECORD=$(jq -cn \
      --arg started_at "$STARTED_AT" --arg finished_at "$FINISHED_AT" \
      --arg mode "$MODE" --arg season "$SEASON" --arg gender "$GENDER" \
      --arg conferences "$CONFERENCES" --arg collect "${COLLECT_SUMMARY:-}" \
      --arg changed "${CHANGED:-}" --arg failed "${FAILED_COLLECTS:-}" \
      --arg locked "${LOCKED_COLLECTS:-}" --arg busy "${BUSY:-}" \
      --arg journal_model_calls "$JOURNAL_SPEND" --arg journal_commit "$JOURNAL_COMMIT" \
      --arg journaled "${JOURNALED:-}" --arg data_head "$DATA_HEAD" --arg data_push "$DATA_PUSH" \
      --arg build_stamp "$BUILD_STAMP" --arg publish "$PUBLISH_RESULT" --arg exit "$RUN_RC" \
      --arg archive "$ARCHIVE_RESULT" \
      'def words: split(" ") | map(select(. != ""));
       {started_at: $started_at, finished_at: $finished_at, mode: $mode,
        season: ($season | tonumber? // $season), gender: $gender,
        conferences: ($conferences | words),
        collect: ($collect | words | map(split("=") | {key: .[0], value: (.[1:] | join("="))}) | from_entries),
        changed: ($changed | words), failed: ($failed | words), locked: ($locked | words),
        busy: (if $busy == "" then null else $busy end),
        journal_model_calls: ($journal_model_calls | tonumber), journal_commit: $journal_commit,
        journaled: ($journaled | words), data_head: $data_head, data_push: $data_push,
        build_stamp: (if $build_stamp == "" then null else $build_stamp end),
        publish: $publish, exit: ($exit | tonumber), archive: $archive}' 2>&1); then
    mkdir -p "$(dirname "$RUNS_FILE")" 2>/dev/null
    printf '%s\n' "$RECORD" >>"$RUNS_FILE" || log "WARNING: run record not written to $RUNS_FILE"
  else
    log "WARNING: run record could not be built — $RECORD"
  fi
  log "run summary: mode=$MODE season=$SEASON collect=[${COLLECT_SUMMARY:-none}] changed=[${CHANGED:-none}] failed=[${FAILED_COLLECTS:-none}] journal_model_calls=$JOURNAL_SPEND journal_commit=$JOURNAL_COMMIT publish=$PUBLISH_RESULT exit=$RUN_RC data_head=$DATA_HEAD build=${BUILD_STAMP:-none} locked=[${LOCKED_COLLECTS:-none}] busy=${BUSY:-none} archive=$ARCHIVE_RESULT"
}

# ── archive mode: the archive step alone, under the lock taken above, any
#    day. No busy check (nothing here writes the data home), no sweep, no
#    collect, no journal, no publish, no push. ──────────────────────────────
if [ "$MODE" = "archive" ]; then
  archive_step
  finish_run
  exit "$RUN_RC"
fi

# ── busy check (tl-5go): is another run already writing this data home? The
#    `keelson workflow status --json` envelope is {"ok":true,"data":{"runs":[…]}}
#    (keelson 0.103.0, workflowRunSummarySchema): each run carries runId,
#    workflowName, status (running|paused|succeeded|failed|cancelled),
#    startedAt, completedAt, origin (manual|scheduled), projectId (the
#    project's UUID, not its name) and workingDir (the project's root path).
#    The cadence passes --project d2-soccer by name, so the match is on
#    workingDir against the data home, raw and physical (macOS tmp dirs are
#    symlinks). A status call that fails (exit 3 with the server down, or an
#    envelope jq cannot read) is logged and the run continues as before: the
#    server-side lock still refuses a collect that races another run. ───────
DATA_HOME_P=$(cd "$DATA_HOME" 2>/dev/null && pwd -P)
SOUT=$(keelson workflow status --json 2>&1)
src=$?
if [ "$src" -ne 0 ]; then
  log "workflow status unavailable (exit $src): $(printf '%s\n' "$SOUT" | tail -1) — busy check skipped; a collect that races another run is still refused by the server's lock."
elif BUSY_LINE=$(printf '%s\n' "$SOUT" | tail -1 | jq -r --arg home "$DATA_HOME" --arg home_p "${DATA_HOME_P:-$DATA_HOME}" '
      (.data.runs // [])[]
      | select((.status == "running" or .status == "paused")
          and (.workflowName == "touchline-collect" or .workflowName == "touchline-backfill")
          and ((.workingDir // "") == $home or (.workingDir // "") == $home_p))
      | "\(.workflowName) \(.runId) \(.startedAt) \(.origin // "manual")"' 2>&1); then
  BUSY_LINE=$(printf '%s\n' "$BUSY_LINE" | head -1)
  if [ -n "$BUSY_LINE" ]; then
    # shellcheck disable=SC2086 # four space-separated words by construction.
    set -- $BUSY_LINE
    BUSY="$1 $2"
    log "data home busy: $1 run $2 started $3, owner $4 — exiting without a sweep or a collect; the next fire retries."
    finish_run
    exit 0
  fi
else
  log "workflow status unparseable — busy check skipped; a collect that races another run is still refused by the server's lock."
fi

# ── sweep: attribute any pre-existing uncommitted writes (an interrupted
#    earlier run) before today's collects, so per-conference detection stays
#    exact. Every dirty path is named by owner (attribute_path) in the log,
#    and the commit message lists the conferences it touched ────────────────
if [ -n "$(git -C "$DATA_HOME" status --porcelain)" ]; then
  log "data home dirty before collecting — sweeping leftovers into a commit first:"
  git -C "$DATA_HOME" status --porcelain | head -25 | logblock
  git -C "$DATA_HOME" status --porcelain -uall >"$PROG_CACHE/sweep"
  rm -f "$PROG_CACHE"/sweep.*
  while IFS= read -r _l || [ -n "$_l" ]; do
    _p=${_l#???}
    _owner=$(attribute_path "$_p")
    printf '%s\n' "$_p" >>"$PROG_CACHE/sweep.${_owner:-unattributed}"
  done <"$PROG_CACHE/sweep"
  SWEPT_CONFS=""
  for CONF in $CONFERENCES; do
    lc=$(lower "$CONF")
    if [ -f "$PROG_CACHE/sweep.$lc" ]; then
      SWEPT_CONFS="${SWEPT_CONFS:+$SWEPT_CONFS }$CONF"
      log "  sweep $CONF: $(wc -l <"$PROG_CACHE/sweep.$lc" | tr -d ' ') path(s): $(head -4 "$PROG_CACHE/sweep.$lc" | paste -sd ' ' -)"
    fi
    if has_signal "$lc"; then
      mark_changed "$lc"
      log "  leftover board changes touch $CONF — it counts as changed."
    fi
  done
  for _owner in shared unattributed; do
    if [ -f "$PROG_CACHE/sweep.$_owner" ]; then
      log "  sweep $_owner: $(wc -l <"$PROG_CACHE/sweep.$_owner" | tr -d ' ') path(s): $(head -4 "$PROG_CACHE/sweep.$_owner" | paste -sd ' ' -)"
    fi
  done
  commit_home "chore(data): sweep uncommitted changes found before cadence run [${SWEPT_CONFS:-none}]"
fi

# ── 1+2: collect and detect, per conference, isolated ────────────────────────
for CONF in $CONFERENCES; do
  lc=$(lower "$CONF")
  log "collect $CONF $GENDER $SEASON:"

  if ! RES=$(resolve_programmes_cached "$CONF") || [ -z "$RES" ]; then
    log "  membership resolution FAILED — ${RES:-no output}; skipping $CONF, continuing."
    FAILED_COLLECTS="${FAILED_COLLECTS:+$FAILED_COLLECTS }$CONF"
    COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=resolve-failed"
    RUN_RC=1
    continue
  fi
  EXTRAPOLATED=${RES%% *}
  PROGRAMMES=${RES#* }
  EXTRA=""
  if [ "$EXTRAPOLATED" = "true" ]; then
    EXTRA="--inputs membership_extrapolated=true"
    log "  membership carried forward past its last authored season (extrapolated)."
  fi
  log "  programmes: $PROGRAMMES"

  # shellcheck disable=SC2086 # EXTRA is one controlled flag pair or empty.
  OUT=$(keelson workflow run touchline-collect \
    --project d2-soccer \
    --no-watch --json \
    --inputs "conference=$CONF" \
    --inputs "gender=$GENDER" \
    --inputs "season=$SEASON" \
    --inputs "programmes=$PROGRAMMES" \
    $EXTRA 2>&1)
  crc=$?
  printf '%s\n' "$OUT" | tail -3 | logblock
  STATUS=$(printf '%s\n' "$OUT" | tail -1 \
    | jq -r 'if .ok == true then (.data.status // "unknown") else "error(" + (.code // "?") + "): " + (.error // "unknown") end' 2>/dev/null)
  STATUS=${STATUS:-unparseable}
  # The server's per-project mutation lock refuses a collect at start with
  # HTTP 409 and `{"error":"project <id> is locked by <owner> for \"<purpose>\"",
  # "code":"REQUEST_FAILED"}`: nothing was written, so nothing is rolled back.
  ERR=$(printf '%s\n' "$OUT" | tail -1 | jq -r 'if .ok == true then "" else (.error // "") end' 2>/dev/null)
  case "${ERR:-}" in *"is locked by"*) LOCKED_NOW=1 ;; *) LOCKED_NOW=0 ;; esac

  if [ "$crc" -eq 0 ] && [ "$STATUS" = "succeeded" ]; then
    if has_signal "$lc"; then
      commit_home "chore(data): cadence collect $CONF $GENDER $SEASON"
      mark_changed "$lc"
      log "  $CONF: board CHANGED — committed $(git -C "$DATA_HOME" rev-parse --short HEAD)."
      COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=changed"
    else
      restore_conference "$lc" "$PROGRAMMES"
      log "  $CONF: no change beyond the collected_at stamp — churn rolled back, journal skipped."
      COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=no-change"
    fi
  elif [ "$LOCKED_NOW" -eq 1 ]; then
    log "  $CONF: collect LOCKED — $ERR"
    LOCKED_COLLECTS="${LOCKED_COLLECTS:+$LOCKED_COLLECTS }$CONF"
    COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=locked"
    RUN_RC=1
    # the holder outlives this loop; the conferences after this one would
    # only be refused the same way, so they are skipped by name (no retry:
    # the next fire is the retry) and the journal/publish legs run for
    # whatever changed before it.
    REMAINING=""
    _after=0
    for _c in $CONFERENCES; do
      if [ "$_after" -eq 1 ]; then REMAINING="${REMAINING:+$REMAINING }$_c"; elif [ "$_c" = "$CONF" ]; then _after=1; fi
    done
    if [ -n "$REMAINING" ]; then
      log "  data home held by another run — skipping the remaining conference(s) [$REMAINING] this run; nothing of theirs was written or rolled back."
    fi
    break
  else
    restore_conference "$lc" "$PROGRAMMES"
    log "  $CONF: collect FAILED (exit $crc, $STATUS) — partial writes rolled back; continuing with the next conference."
    FAILED_COLLECTS="${FAILED_COLLECTS:+$FAILED_COLLECTS }$CONF"
    COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=failed"
    RUN_RC=1
  fi
done

# ── 3+4: journal the changed conferences, then publish once ──────────────────
if [ "$MODE" = "collect" ]; then
  log "mode=collect — stopping after collect+detect (no journal, no publish)."
  ARCHIVE_RESULT="skipped (mode collect)"
elif [ -z "$CHANGED" ]; then
  log "no conference changed — nothing to journal, nothing to publish. No-op run complete."
else
  # one call for every changed conference: the CLI runs them under its pool
  # (cap 4) and reports each by key; a failure is exit 1 at the end, never a
  # stop. Success per conference = its validation file is newer than the stamp.
  JR_KEYS=$(printf '%s' "$CHANGED" | tr ' ' ',')
  # shellcheck disable=SC2086 # CHANGED is a space-separated key list; one line per key is the point.
  N_CHANGED=$(printf '%s\n' $CHANGED | wc -l | tr -d ' ')
  JOURNAL_SPEND=$N_CHANGED
  JR_CAP=$((1200 + 600 * ((N_CHANGED + 3) / 4)))
  JR_STAMP=$(mktemp) ; sleep 1
  log "journal [$JR_KEYS]: regenerating — LIVE MODEL CALLS (claude -p), $N_CHANGED spend(s), one pooled call, cap ${JR_CAP}s."
  JOUT=$(capped "$JR_CAP" journal_leg 2>&1)
  jrc=$?
  printf '%s\n' "$JOUT" | logblock
  if [ "$jrc" -eq 124 ]; then
    log "  journal call TIMED OUT after ${JR_CAP}s — conferences without a fresh file keep their previous journal."
  elif [ "$jrc" -ne 0 ]; then
    log "  journal call exited $jrc — at least one conference failed; the site keeps its previous journal for those."
  fi
  for lc in $CHANGED; do
    # shellcheck disable=SC3013 # -nt is not POSIX but every sh this runs under (macOS bash-as-sh, dash) has it.
    if [ "$UI_DIR/journal/journal-${SEASON}-${GENDER}-${lc}.validation.json" -nt "$JR_STAMP" ]; then
      log "  journal $lc regenerated and validated."
      JOURNALED="${JOURNALED:+$JOURNALED }$lc"
    else
      log "  journal $lc not regenerated — the site keeps its previous journal; continuing."
    fi
  done
  rm -f "$JR_STAMP"

  # ── 3a: the national journal (home page headline, division wires). Skipped
  #    when no conference journal was regenerated — the brief would only
  #    restate yesterday's cards. Its files follow the conference naming
  #    (journal-<season>-<gender>-national.json), so the commit step below
  #    stages them through the same loop.
  if [ -n "$JOURNALED" ]; then
    NJ_CAP=900
    NJ_STAMP=$(mktemp) ; sleep 1
    log "journal [national]: regenerating — LIVE MODEL CALL (claude -p), 1 spend, cap ${NJ_CAP}s."
    NOUT=$(capped "$NJ_CAP" national_leg 2>&1)
    njrc=$?
    printf '%s\n' "$NOUT" | logblock
    JOURNAL_SPEND=$((JOURNAL_SPEND + 1))
    if [ "$njrc" -eq 124 ]; then
      log "  national journal call TIMED OUT after ${NJ_CAP}s — the home page keeps its previous headline."
    elif [ "$njrc" -ne 0 ]; then
      log "  national journal call exited $njrc — the home page keeps its previous headline."
    fi
    # shellcheck disable=SC3013 # see the conference leg above.
    if [ "$UI_DIR/journal/journal-${SEASON}-${GENDER}-national.validation.json" -nt "$NJ_STAMP" ]; then
      log "  journal national regenerated and validated."
      JOURNALED="$JOURNALED national"
    else
      log "  journal national not regenerated — the home page keeps its previous headline; continuing."
    fi
    rm -f "$NJ_STAMP"
  fi

  # ── 3b: commit the regenerated record (tl-151). The journals are model
  #    output — NOT reproducible from the data — so a published site whose
  #    journal files sit uncommitted leaves the deploy ahead of its own
  #    source. Stage exactly the files the validated legs rewrote, commit on
  #    main, and push so the record leaves this machine. A push failure is
  #    loud but never blocks the publish.
  if [ -n "$JOURNALED" ]; then
    UI_BRANCH=$(git -C "$UI_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown')
    if [ "$UI_BRANCH" != "main" ]; then
      log "touchline-ui is on branch '$UI_BRANCH', not main — leaving journal files uncommitted; reconcile by hand."
      JOURNAL_COMMIT="skipped (branch $UI_BRANCH)"
      RUN_RC=1
    else
      for lc in $JOURNALED; do
        git -C "$UI_DIR" add \
          "journal/journal-${SEASON}-${GENDER}-${lc}.json" \
          "journal/journal-${SEASON}-${GENDER}-${lc}.validation.json" 2>&1 | logblock
      done
      if git -C "$UI_DIR" diff --cached --quiet; then
        log "journal commit: regenerated files match HEAD — nothing to commit."
        JOURNAL_COMMIT="no-op"
      elif git -C "$UI_DIR" commit -q -m "chore(journal): cadence regeneration $(date '+%Y-%m-%d') [$JOURNALED]"; then
        JOURNAL_COMMIT=$(git -C "$UI_DIR" rev-parse --short HEAD)
        log "journal commit: $JOURNAL_COMMIT on main [$JOURNALED]."
        UPOUT=$(git -C "$UI_DIR" push origin main 2>&1)
        uprc=$?
        if [ "$uprc" -eq 0 ]; then
          log "journal push: origin/main updated."
        else
          printf '%s\n' "$UPOUT" | tail -3 | logblock
          log "WARNING: push of touchline-ui main FAILED (exit $uprc) — commit $JOURNAL_COMMIT is local only; push by hand."
          RUN_RC=1
        fi
      else
        log "WARNING: journal commit in $UI_DIR failed — files left staged; reconcile by hand."
        JOURNAL_COMMIT="FAILED"
        RUN_RC=1
      fi
    fi
  fi

  log "publish: changed=[$CHANGED] — running 'just publish' in $UI_DIR (rebuild + link check + gh-pages push + deployed-host assertion)."
  POUT=$(cd "$UI_DIR" && just publish 2>&1)
  prc=$?
  printf '%s\n' "$POUT" | tail -25 | logblock
  if [ "$prc" -ne 0 ]; then
    PUBLISH_RESULT="FAILED (exit $prc)"
    log "PUBLISH FAILED (exit $prc) — the live site did NOT update. Data home commits are intact; fix and re-run 'just publish' in $UI_DIR."
    RUN_RC=1
  else
    PUBLISH_RESULT="succeeded"
    BUILD_STAMP=$(build_stamp)
    log "publish succeeded — the deployed host was asserted by the recipe itself. build=${BUILD_STAMP:-none}"
  fi
fi

# ── push the data home's record (tl-151, full loop only): collects commit
#    locally; a record that never leaves the machine is a daily hand-
#    reconciliation. Push whatever is ahead of upstream — even on a no-change
#    day an earlier interrupted run may have left commits behind.
if [ "$MODE" = "loop" ]; then
  if git -C "$DATA_HOME" rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
    AHEAD=$(git -C "$DATA_HOME" rev-list --count '@{upstream}..HEAD' 2>/dev/null || printf '0')
    if [ "${AHEAD:-0}" -gt 0 ]; then
      DHOUT=$(git -C "$DATA_HOME" push 2>&1)
      dhrc=$?
      if [ "$dhrc" -eq 0 ]; then
        DATA_PUSH="ok"
        log "data home push: $AHEAD commit(s) sent to upstream."
      else
        DATA_PUSH="failed"
        printf '%s\n' "$DHOUT" | tail -3 | logblock
        log "WARNING: data home push FAILED (exit $dhrc) — $AHEAD commit(s) remain local; push by hand."
        RUN_RC=1
      fi
    fi
  else
    log "WARNING: data home branch has no upstream — collect commits stay local; set one to let the cadence push."
  fi
fi

# ── 6: archive the raw HTML cache (tl-ttj, full loop only, on the archive
#    day). After the push so the record is safe first; before the run record
#    so it carries the result. A failure is a WARNING and exit 1, never a stop.
if [ "$MODE" = "loop" ]; then
  if archive_gate; then archive_step; fi
fi

# ── run record and summary line (finish_run, defined above the sweep) ────────
finish_run
exit "$RUN_RC"
