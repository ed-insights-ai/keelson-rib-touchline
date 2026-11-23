#!/usr/bin/env bash
# Temporary: run the real collector for the thread's programmes into temp homes.
set -u
cd pipeline
run() { # conf gender programmes
  home="$GITHUB_WORKSPACE/.probe/collect/$1-$2"; mkdir -p "$home"
  TOUCHLINE_DATA_DIR="$home" timeout 900 uv run --frozen --no-dev python -m scripts.collect_board \
    --season 2026 --gender "$2" --conference "$1" --programmes "$3" >"$home/collect.log" 2>&1
  echo "$1 $2 exit $?"
}
run SEC women oklahoma &
run B1G women maryland &
wait
