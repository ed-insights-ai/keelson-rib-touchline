#!/bin/sh
# Touchline daily cadence, installed shim (beads tl-cpn).
#
# This is the file that lives at the launchd path,
# ~/.keelson/scripts/touchline-collect-cadence.sh. It carries no cadence
# logic: it resolves the installed rib package the same way the cadence
# script's rib_package_dir does (packageDir in the keelson rib config, else
# the harness's node_modules copy) and execs the packaged
# bin/touchline-collect-cadence.sh with the same arguments, so upgrading the
# rib upgrades the cadence without touching launchd or this file.
#
# A missing packaged script is loud: one FATAL line in the cadence log (the
# same file launchd already redirects to) and exit 1. `sh <this file> version`
# proves the resolution end to end without taking the lock or collecting.
set -u
PATH="${TOUCHLINE_CADENCE_PATH:-/Users/danielscholl/.local/bin:/Users/danielscholl/.bun/bin:/opt/homebrew/bin:/usr/bin:/bin}"
export PATH

HOME_DIR="${HOME:-/Users/danielscholl}"
# The FATAL below lands in the log the packaged script would have used for
# this data home: the default home's (~/keelson/d2-soccer) log, or for any
# other TOUCHLINE_DATA_HOME the log keyed by its directory name — the same
# rule as the script's "one cadence per data home" block.
DEFAULT_DATA_HOME="$HOME_DIR/keelson/d2-soccer"
DATA_HOME="${TOUCHLINE_DATA_HOME:-$DEFAULT_DATA_HOME}"
LOG_SUFFIX=".$(basename "$DATA_HOME")"
if [ "$DATA_HOME" = "$DEFAULT_DATA_HOME" ]; then
  LOG_SUFFIX=""
elif _hp=$(cd "$DATA_HOME" 2>/dev/null && pwd -P) && _dp=$(cd "$DEFAULT_DATA_HOME" 2>/dev/null && pwd -P) \
    && [ "$_hp" = "$_dp" ]; then
  LOG_SUFFIX=""
fi
LOG_FILE="${TOUCHLINE_CADENCE_LOG_FILE:-$HOME_DIR/.keelson/logs/touchline-collect-cadence$LOG_SUFFIX.log}"
RIB_CFG="${TOUCHLINE_CONFIG_PATH:-$HOME_DIR/.keelson/rib-touchline/config.json}"

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

PKG=$(rib_package_dir)
SCRIPT="$PKG/bin/touchline-collect-cadence.sh"
if [ ! -f "$SCRIPT" ]; then
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null
  _line="[$(date '+%Y-%m-%d %H:%M:%S')] FATAL: cadence shim: packaged script not found at $SCRIPT (rib config $RIB_CFG) — install or upgrade the rib package."
  printf '%s\n' "$_line" >>"$LOG_FILE"
  printf '%s\n' "$_line" >&2
  exit 1
fi
exec /bin/sh "$SCRIPT" "$@"
