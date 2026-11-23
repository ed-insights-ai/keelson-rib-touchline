#!/usr/bin/env bash
# The collector's raw-HTML fetch cache, kept in the data bucket instead of on
# one machine (or in the Actions cache, which the data jobs never use):
#
#   s3://$BUCKET/raw/$DIVISION/raw_html/<slug>/<season>-<gender>-<kind>.{html,state.json}
#
# the same layout as data/raw_html in a data home. `down` restores the season's
# pages for the given programmes into a work home, so collect-board can verify
# a page unchanged (and reparse an archived box score) instead of treating it
# as new; `up` archives what the work home holds. Nothing is ever deleted: the
# publish role cannot, and raw/ is kept forever (re-parse, never re-scrape).
#
#   raw-sync.sh down <work home> <slugs file>
#   raw-sync.sh up   <work home>
#
# Needs BUCKET, DIVISION and SEASON in the environment and AWS credentials for
# the touchline-publish role.
set -euo pipefail
: "${BUCKET:?}" "${DIVISION:?}" "${SEASON:?}"
case "$SEASON" in [0-9][0-9][0-9][0-9]) ;; *) echo "SEASON '$SEASON' is not a year" >&2; exit 2 ;; esac
case "$DIVISION" in d[0-9]) ;; *) echo "DIVISION '$DIVISION' is not a level" >&2; exit 2 ;; esac
mode=${1:?down or up}
home=${2:?work home}
prefix="s3://$BUCKET/raw/$DIVISION/raw_html/"
cache="$home/data/raw_html"
mkdir -p "$cache"
summary=${GITHUB_STEP_SUMMARY:-/dev/null}

count() { find "$cache" -type f | wc -l | tr -d ' '; }
size() { du -sh "$cache" | cut -f1; }

case "$mode" in
  down)
    slugs=${3:?slugs file}
    args=(--exclude '*')
    while IFS= read -r slug; do
      case "$slug" in ''|*[!a-z0-9-]*) continue ;; esac
      args+=(--include "$slug/$SEASON-*")
    done <"$slugs"
    if [ "${#args[@]}" -le 2 ]; then
      echo "raw $DIVISION: no programmes to restore"
      exit 0
    fi
    aws s3 sync "$prefix" "$cache/" "${args[@]}" --only-show-errors --no-progress
    echo "raw $DIVISION: restored $(count) file(s), $(size), for $(grep -c . "$slugs") programme(s)" | tee -a "$summary"
    ;;
  up)
    before=$(count)
    if [ "$before" = 0 ]; then
      echo "raw $DIVISION: nothing to archive"
      exit 0
    fi
    # Only season files live in a work home's cache. Unchanged files keep the
    # bucket's timestamp from the download, so sync skips them.
    aws s3 sync "$cache/" "$prefix" --exclude '*' --include "*/$SEASON-*" --only-show-errors --no-progress
    echo "raw $DIVISION: archived the work home's cache ($before file(s), $(size)) to raw/$DIVISION/" | tee -a "$summary"
    ;;
  *)
    echo "usage: raw-sync.sh down <work home> <slugs file> | up <work home>" >&2
    exit 2
    ;;
esac
