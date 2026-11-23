#!/bin/sh
# Build, sign and verify the published dataset: one touchline-desk publish
# folder per scope, made by the desk's packages/data at the pinned commit.
#
#   scope `all`      every home, both genders (what the desk reads in the pilot)
#   scope <d>-<g>    one division's home, one gender (d2-men, d1-women, ...)
#
# For each scope: build the index from the homes, take the folder's current
# state (latest.json, its manifest and base) from the bucket when BUCKET is
# set, verify that state with the public key, publish the next snapshot (base,
# delta from the current one, signed manifest, latest.json), verify it again
# through the desk's own fetch (by delta and from the base alone), and upload
# every new file with a write that refuses to replace an existing object.
# latest.json is NOT uploaded here: it is staged in $WORK/release for
# snapshot/release.sh, which moves it only after the site smoke check passes.
#
# Without BUCKET the folder lives only in $WORK, so running this twice
# publishes a first snapshot and then a second one by delta (pull requests).
#
# Environment:
#   DESK_CLI     packages/data/dist/cli.js of the pinned desk
#   HOMES_DIR    folder holding <division>-soccer for every division
#   DIVISIONS    the division list, e.g. "d2 d1"
#   SOURCE       data or samples (the bucket folder snapshots/<source>/)
#   WORK         scratch folder, kept between two runs
#   SIGN         "kms:<key id or alias>" or "key:<private key PEM file>"
#   PUBLIC_KEY   PEM file every signature is verified with
#   ENGINE       the DuckDB engine the manifest must name (snapshot/duckdb.env)
#   PROVENANCE   the data homes' commits, e.g. "d2-soccer=<sha> d1-soccer=<sha>"
#   DESK_SHA     the desk commit
#   RUN_URL      this run, for the manifest (optional)
#   BUCKET       the data bucket (optional; unset keeps everything local)
#   ALLOW_SHRINK why rows may fall this time (optional; else a fall stops it)
#   DAY          the snapshot day, YYYY-MM-DD (default: today, UTC)
set -eu

: "${DESK_CLI:?}" "${HOMES_DIR:?}" "${DIVISIONS:?}" "${SOURCE:?}" "${WORK:?}"
: "${SIGN:?}" "${PUBLIC_KEY:?}" "${ENGINE:?}" "${PROVENANCE:?}" "${DESK_SHA:?}"
BUCKET=${BUCKET:-}
DAY=${DAY:-$(date -u +%Y-%m-%d)}
RUN_URL=${RUN_URL:-}
ALLOW_SHRINK=${ALLOW_SHRINK:-}

case "$SOURCE" in data | samples) ;; *) echo "SOURCE is data or samples, not '$SOURCE'" >&2; exit 2 ;; esac
case "$DAY" in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;; *) echo "DAY is YYYY-MM-DD" >&2; exit 2 ;; esac
case "$SIGN" in
  kms:?*) sign_flag=--kms-key; sign_value=${SIGN#kms:} ;;
  key:?*) sign_flag=--key; sign_value=${SIGN#key:} ;;
  *) echo "SIGN is kms:<key> or key:<file>" >&2; exit 2 ;;
esac

# The desk's progress lines go to a log, shown when a step fails.
desk() {
  node "$DESK_CLI" "$@" 2>"$WORK/desk.log" || {
    tr '\r' '\n' <"$WORK/desk.log" | grep -v '^ *$' | tail -n 40 >&2
    return 1
  }
}
fail() { echo "::error::$*" >&2; exit 1; }

release="$WORK/release"
mkdir -p "$release"
summary="$WORK/summary.md"
[ -f "$summary" ] || printf '| scope | snapshot | games | base | delta | via |\n| --- | --- | --- | --- | --- | --- |\n' >"$summary"

# Every division's home must be there: a missing one is a broken checkout,
# never a smaller dataset.
all_homes=""
for d in $DIVISIONS; do
  [ -f "$HOMES_DIR/$d-soccer/touchline-data.yaml" ] || fail "no data home for $d at $HOMES_DIR/$d-soccer"
  all_homes="$all_homes${all_homes:+:}$HOMES_DIR/$d-soccer"
done

scopes="all"
for d in $DIVISIONS; do scopes="$scopes $d-men $d-women"; done

content_type() {
  case "$1" in
    *.json) echo application/json ;;
    *.zst) echo application/zstd ;;
    *) echo text/plain ;;
  esac
}

# Read one object of the folder into $out; returns 1 when it does not exist.
fetch_object() { # key file
  if aws s3api get-object --bucket "$BUCKET" --key "$1" "$2" >"$WORK/get.json" 2>"$WORK/get.err"; then
    return 0
  fi
  if grep -q 'NoSuchKey' "$WORK/get.err"; then return 1; fi
  cat "$WORK/get.err" >&2
  fail "could not read s3://$BUCKET/$1"
}

for scope in $scopes; do
  echo "::group::$scope"
  prefix="snapshots/$SOURCE/$scope"
  index="$WORK/index/$scope"
  out="$WORK/publish/$scope"
  mkdir -p "$out"

  # 1. Build. A scope with no games is a broken home, not an empty scope.
  case "$scope" in
    all) desk build --homes "$all_homes" --index "$index" --full >"$WORK/build.json" ;;
    *)
      division=${scope%-*}
      gender=${scope#*-}
      desk build --homes "$HOMES_DIR/$division-soccer" --index "$index" --full --gender "$gender" >"$WORK/build.json"
      ;;
  esac
  games=$(jq -r '.result.rows.games // .result.index.rows.games // 0' "$WORK/build.json")
  skipped=$(jq -r '(.result.skipped // .result.index.skipped // []) | length' "$WORK/build.json")
  [ "$games" -gt 0 ] || fail "$scope: the index holds no games"
  [ "$skipped" -eq 0 ] || {
    jq '.result.skipped // .result.index.skipped' "$WORK/build.json" >&2
    fail "$scope: $skipped season file(s) could not be read"
  }

  # 2. The folder's current state: the bucket's, or what an earlier local run left.
  etag=none
  if [ -n "$BUCKET" ]; then
    rm -rf "$out" && mkdir -p "$out"
    if fetch_object "$prefix/latest.json" "$out/latest.json"; then
      etag=$(jq -r .ETag "$WORK/get.json")
      manifest=$(jq -r .manifest "$out/latest.json")
      mkdir -p "$out/manifests" "$out/base"
      fetch_object "$prefix/$manifest" "$out/$manifest" || fail "$scope: latest.json names $manifest, which is not there"
      base=$(jq -r .base.url "$out/$manifest")
      fetch_object "$prefix/$base" "$out/$base" || fail "$scope: the manifest names $base, which is not there"
    fi
    taken=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$prefix/manifests/$DAY." \
      --query 'Contents[].Key' --output json | jq '[.[]? | select(endswith(".json"))] | length')
  else
    [ -f "$out/latest.json" ] && etag=local
    taken=$(find "$out/manifests" -name "$DAY.*.json" 2>/dev/null | wc -l | tr -d ' ')
  fi
  id="$DAY.$((taken + 1))"

  # 3. Verify what is served now, through the desk's own fetch, so the next
  #    snapshot's delta is checked from a state the app would accept.
  verify="$WORK/verify/$scope"
  rm -rf "$verify"
  if [ "$etag" != none ]; then
    TOUCHLINE_SNAPSHOT_PUBLIC_KEY="$PUBLIC_KEY" desk fetch "$out" --index "$verify" >"$WORK/fetch.json" ||
      fail "$scope: the snapshot served now does not verify"
  fi

  # 4. Publish the next snapshot.
  find "$out" -type f | sort >"$WORK/before.txt"
  set -- publish --out "$out" --index "$index" --snapshot "$id" --no-oracle \
    "$sign_flag" "$sign_value" --collector "$PROVENANCE" --app "touchline-desk@$DESK_SHA"
  [ -n "$RUN_URL" ] && set -- "$@" --run "$RUN_URL"
  [ -n "$ALLOW_SHRINK" ] && set -- "$@" --allow-shrink "$ALLOW_SHRINK"
  desk "$@" >"$WORK/publish.json" || fail "$scope: not published"
  engine=$(jq -r .result.engine "$WORK/publish.json")
  [ "$engine" = "$ENGINE" ] || fail "$scope: written by DuckDB $engine, but the pin is $ENGINE"

  # 5. Verify it as an app would: by delta from the served one, and from the
  #    base alone, each with only the public key.
  TOUCHLINE_SNAPSHOT_PUBLIC_KEY="$PUBLIC_KEY" desk fetch "$out" --index "$verify" >"$WORK/fetch.json" ||
    fail "$scope: the new snapshot does not verify"
  got=$(jq -r .result.installed.snapshot "$WORK/fetch.json")
  via=$(jq -r .result.via "$WORK/fetch.json")
  [ "$got" = "$id" ] || fail "$scope: fetch installed $got, not $id"
  if [ "$etag" != none ] && [ "$via" != deltas ]; then fail "$scope: the delta was not used ($via)"; fi
  rm -rf "$WORK/verify-base/$scope"
  TOUCHLINE_SNAPSHOT_PUBLIC_KEY="$PUBLIC_KEY" desk fetch "$out" --index "$WORK/verify-base/$scope" >"$WORK/fetch-base.json" ||
    fail "$scope: the new base does not verify"
  [ "$(jq -r .result.via "$WORK/fetch-base.json")" = base ] || fail "$scope: the base fetch did not use the base"

  # 6. Upload what is new, never replacing an object; stage latest.json.
  find "$out" -type f | sort >"$WORK/after.txt"
  comm -13 "$WORK/before.txt" "$WORK/after.txt" | grep -v '/latest\.json$' >"$WORK/new.txt" || true
  [ -s "$WORK/new.txt" ] || fail "$scope: publish wrote no files"
  if [ -n "$BUCKET" ]; then
    while IFS= read -r file; do
      key="$prefix/${file#"$out"/}"
      aws s3api put-object --bucket "$BUCKET" --key "$key" --body "$file" \
        --content-type "$(content_type "$file")" --if-none-match '*' >/dev/null ||
        fail "$scope: could not write s3://$BUCKET/$key (it may already exist)"
      echo "uploaded $key"
    done <"$WORK/new.txt"
  fi
  cp "$out/latest.json" "$release/$scope.latest.json"
  printf '%s\n' "$etag" >"$release/$scope.etag"

  base_bytes=$(jq -r .result.base.bytes "$WORK/publish.json")
  deltas=$(jq -r .result.deltas "$WORK/publish.json")
  printf '| %s | %s | %s | %s bytes | %s | %s |\n' "$scope" "$id" "$games" "$base_bytes" \
    "$([ "$etag" = none ] && echo none || echo "1 of $deltas")" "$via" >>"$summary"
  echo "$scope: $id published and verified ($games games, via $via)"
  echo "::endgroup::"
done
