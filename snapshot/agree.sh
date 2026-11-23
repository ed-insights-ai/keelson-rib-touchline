#!/bin/sh
# Check that the site and the desk show the same numbers (snapshot/agree.py).
#
# For every site build (division x gender, the season the bundle was cut for)
# touchline-ui's scripts/figures.ts prints the figures its pages show; the
# desk's are read from the `all` index this run published. Writes the summary
# to $OUT and exits 1 when a program's figures differ.
#
# Environment:
#   UI          touchline-ui checkout at the site's pin, installed
#   BUNDLE      the site bundle (one <division>-soccer per division)
#   DESK        touchline-desk checkout at the snapshot's pin, built
#   INDEX       the `all` index folder (holding touchline.duckdb)
#   CONTRACTS   the rib's contracts/ (as the site build gets them)
#   DIVISIONS   e.g. "d2 d1"
#   OUT         the Markdown summary to write
set -eu

: "${UI:?}" "${BUNDLE:?}" "${DESK:?}" "${INDEX:?}" "${CONTRACTS:?}" "${DIVISIONS:?}" "${OUT:?}"
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

csv() { printf '%s' "$1" | tr -s ' ' ','; }
figures=""
for d in $DIVISIONS; do
  home="$BUNDLE/$d-soccer"
  season=$(python3 -I -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["season"]))' "$home/data/bundle.json")
  for g in men women; do
    file="$work/figures-$d-$g.json"
    (cd "$UI" && env TOUCHLINE_DATA_DIR="$home" TOUCHLINE_NCAA_DIVISION="$d" TOUCHLINE_GENDER="$g" \
      TOUCHLINE_SEASON="$season" TOUCHLINE_CONTRACTS_DIR="$CONTRACTS" \
      TOUCHLINE_GENDERS=men,women TOUCHLINE_NCAA_DIVISIONS="$(csv "$DIVISIONS")" \
      bun scripts/figures.ts >"$file" 2>"$work/figures-$d-$g.err") || {
      cat "$work/figures-$d-$g.err" >&2
      echo "::error::touchline-ui could not print the figures for $d $g" >&2
      exit 1
    }
    figures="$figures $file"
  done
done

node "$here/desk-figures.mjs" "$DESK" "$INDEX/touchline.duckdb" >"$work/desk.json"
# shellcheck disable=SC2086
python3 -I "$here/agree.py" "$work/desk.json" $figures >"$OUT"
