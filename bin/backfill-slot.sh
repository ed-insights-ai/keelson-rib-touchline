#!/bin/sh
# One season of a touchline-backfill run (workflows/touchline-backfill.yml).
#
# Each collect-N node in that workflow runs this script with SLOT=N. The slot's
# season is from_season + (SLOT - 1); a slot past to_season prints a SKIPPED
# line and exits 0, so a shorter range leaves its unused slots idle instead of
# failing. The script lives in the rib (not inline in the YAML) so the eight
# slot nodes share one body and one test.
#
# Environment (the workflow's bash-node contract):
#   SLOT                                1-based slot number
#   KEELSON_INPUTS_conference / _gender / _from_season / _to_season / _layers
#   KEELSON_INPUTS_refetch              "true" to pass --refetch to collect-board
#   KEELSON_NODE_resolve_pipeline_OUTPUT  the pipeline directory, last line
#   cwd                                 the Touchline data home
#
# Exit: 0 when the slot is idle or collect-board wrote its coverage manifest;
# collect-board's own exit code otherwise (no manifest, nothing landed).
set -u

SLOT="${SLOT:?SLOT is required}"
FROM="${KEELSON_INPUTS_from_season:?from_season input is required}"
TO="${KEELSON_INPUTS_to_season:?to_season input is required}"
CONF="${KEELSON_INPUTS_conference:?conference input is required}"
GENDER="${KEELSON_INPUTS_gender:?gender input is required}"
LAYERS="${KEELSON_INPUTS_layers:-schedule,roster,stats,matches}"

SEASON=$((FROM + SLOT - 1))
if [ "$SEASON" -gt "$TO" ]; then
  printf 'SKIPPED: slot %s has no season (range %s-%s).\n' "$SLOT" "$FROM" "$TO"
  exit 0
fi

PIPELINE_DIR=$(printf '%s' "${KEELSON_NODE_resolve_pipeline_OUTPUT:-}" | tr -d '\r' | tail -1)
if [ ! -f "$PIPELINE_DIR/pyproject.toml" ]; then
  printf 'ALARM: pipeline not found at %s (resolve-pipeline output did not carry a usable path)\n' "${PIPELINE_DIR:-<empty>}"
  exit 1
fi
PKG_DIR=$(dirname "$PIPELINE_DIR")
RESOLVER="$PKG_DIR/bin/resolve-membership.ts"
if [ ! -f "$RESOLVER" ]; then
  printf 'ALARM: membership resolver not found at %s\n' "$RESOLVER"
  exit 1
fi

# Programme lists resolve from the packaged membership record at run time;
# the season decides the window, so every slot resolves its own.
RES=$(bun "$RESOLVER" conference "$CONF" "$GENDER" "$SEASON" 2>&1)
RC=$?
if [ "$RC" -ne 0 ] || [ -z "$RES" ]; then
  printf 'REFUSED: membership resolution failed for %s %s %s: %s\n' "$CONF" "$GENDER" "$SEASON" "${RES:-no output}"
  exit 1
fi
EXTRAPOLATED=${RES%% *}
PROGRAMMES=${RES#* }
EXTRA=""
if [ "$EXTRAPOLATED" = "true" ]; then
  EXTRA="--membership-extrapolated"
  printf 'NOTE: %s %s membership is carried forward past its last authored season (extrapolated).\n' "$CONF" "$SEASON"
fi
# Stored box scores are reused whenever a fixture's result is unchanged, so a
# parser change never reaches them unless the run asks to re-fetch (tl-ir6).
if [ "${KEELSON_INPUTS_refetch:-}" = "true" ]; then
  EXTRA="$EXTRA --refetch"
  printf 'NOTE: refetch requested; every stored page and box score is fetched and parsed again.\n'
fi

printf 'season %s: %s %s -> %s\n' "$SEASON" "$CONF" "$GENDER" "$PROGRAMMES"

# shellcheck disable=SC2086 # EXTRA is a short list of controlled flags or empty.
TOUCHLINE_DATA_DIR="$PWD" uv run --project "$PIPELINE_DIR" collect-board \
  --conference "$CONF" \
  --gender "$GENDER" \
  --season "$SEASON" \
  --programmes "$PROGRAMMES" \
  --layers "$LAYERS" \
  $EXTRA
RC=$?
if [ "$RC" -ne 0 ]; then
  printf '\nseason %s: collection exited %s. No coverage manifest was written, so nothing above is a claim that data landed.\n' "$SEASON" "$RC"
  exit "$RC"
fi
printf 'season %s: collected.\n' "$SEASON"
