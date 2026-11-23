#!/usr/bin/env bash
# Temporary: run the real collector for the thread's programmes into temp homes.
set -u
cd pipeline
run() { # season conf gender programmes
  home="$GITHUB_WORKSPACE/.probe/collect/$1-$2-$3"; mkdir -p "$home"
  TOUCHLINE_DATA_DIR="$home" timeout 900 uv run --frozen --no-dev python -m scripts.collect_board \
    --season "$1" --gender "$3" --conference "$2" --programmes "$4" --layers schedule >"$home/collect.log" 2>&1
  echo "$1 $2 $3 exit $?"
}
run 2026 BIG12 women arizona-state &
run 2025 ACC women clemson &
wait
rm -rf "$GITHUB_WORKSPACE"/.probe/collect/*/data/raw_html
