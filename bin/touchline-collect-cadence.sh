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
#               and its partial writes rolled back; the others still run.
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
#
# Modes:  (no argument)   the full loop — what launchd runs.
#         collect         collect+detect only, no journal/build/publish.
#                         touchline-ui's justfile delegates its collect step
#                         to this script; set
#                           TOUCHLINE_COLLECT_CMD="sh <this script> collect"
#                         there so `just` does not run the journal twice.
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
LOCK_DIR="$HOME_DIR/.keelson/locks/touchline-collect-cadence.lock"
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

case "$MODE" in loop|collect|version) ;; *) die "unknown mode '$MODE' — use no argument (full loop), 'collect' or 'version'." ;; esac

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
trap 'rm -rf "$LOCK_DIR"' EXIT
trap 'rm -rf "$LOCK_DIR"; exit 130' INT TERM

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
# this gender, unless TOUCHLINE_CONFERENCES pins it (rib bin/resolve-membership.ts)
if [ -z "$CONFERENCES" ]; then
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

# ── change detection ─────────────────────────────────────────────────────────
# Real change = a new board file, or a board-file diff with any line beyond
# the top-level collected_at stamp. Board files only; coverage/raw_html/errors
# churn on every fetch and are committed alongside a real change, never
# counted as one.
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

restore_home() { # roll back everything uncommitted (churn, or a failed collect's partial writes)
  git -C "$DATA_HOME" reset -q --hard
  git -C "$DATA_HOME" clean -qfd data
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

# ── state ────────────────────────────────────────────────────────────────────
CHANGED=""
JOURNALED=""
COLLECT_SUMMARY=""
FAILED_COLLECTS=""
JOURNAL_SPEND=0
PUBLISH_RESULT="skipped (no change)"
JOURNAL_COMMIT="none"
DATA_PUSH="skipped"
BUILD_STAMP=""
RUN_RC=0

# ── sweep: attribute any pre-existing uncommitted writes (an interrupted
#    earlier run) before today's collects, so per-conference detection stays
#    exact ───────────────────────────────────────────────────────────────────
if [ -n "$(git -C "$DATA_HOME" status --porcelain)" ]; then
  log "data home dirty before collecting — sweeping leftovers into a commit first:"
  git -C "$DATA_HOME" status --porcelain | head -25 | logblock
  for CONF in $CONFERENCES; do
    lc=$(printf '%s' "$CONF" | tr '[:upper:]' '[:lower:]')
    if has_signal "$lc"; then
      mark_changed "$lc"
      log "  leftover board changes touch $CONF — it counts as changed."
    fi
  done
  commit_home "chore(data): sweep uncommitted changes found before cadence run"
fi

# ── 1+2: collect and detect, per conference, isolated ────────────────────────
for CONF in $CONFERENCES; do
  lc=$(printf '%s' "$CONF" | tr '[:upper:]' '[:lower:]')
  log "collect $CONF $GENDER $SEASON:"

  if ! RES=$(resolve_programmes "$CONF" 2>&1) || [ -z "$RES" ]; then
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

  if [ "$crc" -eq 0 ] && [ "$STATUS" = "succeeded" ]; then
    if has_signal "$lc"; then
      commit_home "chore(data): cadence collect $CONF $GENDER $SEASON"
      mark_changed "$lc"
      log "  $CONF: board CHANGED — committed $(git -C "$DATA_HOME" rev-parse --short HEAD)."
      COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=changed"
    else
      restore_home
      log "  $CONF: no change beyond the collected_at stamp — churn rolled back, journal skipped."
      COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=no-change"
    fi
  else
    restore_home
    log "  $CONF: collect FAILED (exit $crc, $STATUS) — partial writes rolled back; continuing with the next conference."
    FAILED_COLLECTS="${FAILED_COLLECTS:+$FAILED_COLLECTS }$CONF"
    COLLECT_SUMMARY="${COLLECT_SUMMARY:+$COLLECT_SUMMARY }$CONF=failed"
    RUN_RC=1
  fi
done

# ── 3+4: journal the changed conferences, then publish once ──────────────────
if [ "$MODE" = "collect" ]; then
  log "mode=collect — stopping after collect+detect (no journal, no publish)."
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

# ── run record: the summary line as data, one JSON line per completed run.
#    data_head is the data home's HEAD after the push step (the pre-run value
#    when this mode never pushes). Written before the summary line so a
#    reader of either sees the same run; a record that cannot be written is
#    a WARNING, never a changed exit code.
DATA_HEAD=$(git -C "$DATA_HOME" rev-parse --short HEAD 2>/dev/null || printf 'unknown')
FINISHED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
if RECORD=$(jq -cn \
    --arg started_at "$STARTED_AT" --arg finished_at "$FINISHED_AT" \
    --arg mode "$MODE" --arg season "$SEASON" --arg gender "$GENDER" \
    --arg conferences "$CONFERENCES" --arg collect "${COLLECT_SUMMARY:-}" \
    --arg changed "${CHANGED:-}" --arg failed "${FAILED_COLLECTS:-}" \
    --arg journal_model_calls "$JOURNAL_SPEND" --arg journal_commit "$JOURNAL_COMMIT" \
    --arg journaled "${JOURNALED:-}" --arg data_head "$DATA_HEAD" --arg data_push "$DATA_PUSH" \
    --arg build_stamp "$BUILD_STAMP" --arg publish "$PUBLISH_RESULT" --arg exit "$RUN_RC" \
    'def words: split(" ") | map(select(. != ""));
     {started_at: $started_at, finished_at: $finished_at, mode: $mode,
      season: ($season | tonumber? // $season), gender: $gender,
      conferences: ($conferences | words),
      collect: ($collect | words | map(split("=") | {key: .[0], value: (.[1:] | join("="))}) | from_entries),
      changed: ($changed | words), failed: ($failed | words),
      journal_model_calls: ($journal_model_calls | tonumber), journal_commit: $journal_commit,
      journaled: ($journaled | words), data_head: $data_head, data_push: $data_push,
      build_stamp: (if $build_stamp == "" then null else $build_stamp end),
      publish: $publish, exit: ($exit | tonumber)}' 2>&1); then
  mkdir -p "$(dirname "$RUNS_FILE")" 2>/dev/null
  printf '%s\n' "$RECORD" >>"$RUNS_FILE" || log "WARNING: run record not written to $RUNS_FILE"
else
  log "WARNING: run record could not be built — $RECORD"
fi

log "run summary: mode=$MODE season=$SEASON collect=[${COLLECT_SUMMARY:-none}] changed=[${CHANGED:-none}] failed=[${FAILED_COLLECTS:-none}] journal_model_calls=$JOURNAL_SPEND journal_commit=$JOURNAL_COMMIT publish=$PUBLISH_RESULT exit=$RUN_RC data_head=$DATA_HEAD build=${BUILD_STAMP:-none}"
exit "$RUN_RC"
