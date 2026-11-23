#!/bin/sh
# Hold the pinned desk to its oracle on the sample homes.
#
# The desk's fixtures/oracle/facts.json are figures counted by hand from the
# 2026 Great American Conference sample files (invented names), which the
# rib's samples/d2-soccer carries byte for byte. This builds the `all` index of the sample homes with
# the desk at the snapshot's pin and publishes it into a scratch folder with a
# throwaway key and `--oracle`, so publish refuses if any team or player fact
# does not hold. The oracle's fold cases are left out: they need the stand-in
# second conference the desk's tests build, which no real home has.
#
# The real homes are not held to it: their GAC files keep growing after the
# sample was frozen. Nothing here is uploaded.
#
# Environment:
#   DESK        touchline-desk checkout at the snapshot's pin, built
#   SAMPLES     the rib's samples/ (holding <division>-soccer)
#   DIVISIONS   e.g. "d2 d1"
set -eu

: "${DESK:?}" "${SAMPLES:?}" "${DIVISIONS:?}"
cli="$DESK/packages/data/dist/cli.js"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

homes=""
for d in $DIVISIONS; do
  [ -f "$SAMPLES/$d-soccer/touchline-data.yaml" ] || { echo "::error::no sample home for $d" >&2; exit 1; }
  homes="$homes${homes:+:}$SAMPLES/$d-soccer"
done

jq '.fold_cases = []' "$DESK/fixtures/oracle/facts.json" >"$work/facts.json"
teams=$(jq '[.teams[] | select(.recounted or .record_when_scoring_first)] | length' "$work/facts.json")
players=$(jq '[.players[] | select(.recounted)] | length' "$work/facts.json")

node "$cli" keygen "$work/throwaway" >/dev/null
node "$cli" build --homes "$homes" --index "$work/index" --full >/dev/null 2>"$work/build.log" || {
  tail -n 40 "$work/build.log" >&2
  echo "::error::the sample homes did not build" >&2
  exit 1
}
TOUCHLINE_SNAPSHOT_PUBLIC_KEY="$work/throwaway.pub" node "$cli" publish --out "$work/out" \
  --index "$work/index" --key "$work/throwaway.key" --oracle "$work/facts.json" \
  >/dev/null 2>"$work/publish.log" || {
  tr '\r' '\n' <"$work/publish.log" | grep -v '^ *$' | tail -n 40 >&2
  echo "::error::the pinned desk does not reproduce its oracle on the sample homes" >&2
  exit 1
}
echo "The pinned desk reproduces the oracle on the sample homes ($teams team and $players player facts)."
