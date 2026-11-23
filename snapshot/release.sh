#!/bin/sh
# Move each scope's latest.json to the snapshot snapshot/build.sh published and
# uploaded. Run only after the site smoke check passed, so the desk never sees
# a snapshot the live site does not show.
#
# Each write is conditional: on the ETag build.sh read (If-Match), or on there
# being no latest.json yet (If-None-Match: *). If anything moved latest.json
# since, S3 refuses and this run leaves that scope alone. Before moving a scope,
# its manifest and base must be in the bucket. Scopes are independent; `all`
# goes first because the desk reads it. Any scope not moved fails the job.
#
# Bases are pruned by tag (infra/main/main.tf): the new base is tagged
# touchline-base=current BEFORE latest.json names it, so the base a latest.json
# names is never one the lifecycle expires; once the move succeeded, the base
# it replaced is tagged superseded. A failed superseded tag only keeps an old
# base longer, so it warns instead of failing.
#
# Environment: BUCKET, SOURCE (data or samples), RELEASE (build.sh's
# $WORK/release, holding <scope>.latest.json, .etag, .base, .previous-base).
set -eu
: "${BUCKET:?}" "${SOURCE:?}" "${RELEASE:?}"
case "$SOURCE" in data | samples) ;; *) echo "SOURCE is data or samples" >&2; exit 2 ;; esac

scopes=$(find "$RELEASE" -maxdepth 1 -name "*.latest.json" | sed "s|.*/||; s/\.latest\.json$//" | sort)
[ -n "$scopes" ] || { echo "::error::nothing staged in $RELEASE"; exit 1; }
if echo "$scopes" | grep -qx all; then scopes="all $(echo "$scopes" | grep -vx all)"; fi

tag() { # key state
  aws s3api put-object-tagging --bucket "$BUCKET" --key "$1" \
    --tagging "TagSet=[{Key=touchline-base,Value=$2}]" >/dev/null 2>"$RELEASE/tag.err"
}

failed=""
for scope in $scopes; do
  prefix="snapshots/$SOURCE/$scope"
  file="$RELEASE/$scope.latest.json"
  etag=$(cat "$RELEASE/$scope.etag")
  snapshot=$(jq -r .snapshot "$file")
  manifest=$(jq -r .manifest "$file")
  base=$(cat "$RELEASE/$scope.base")
  previous=$(cat "$RELEASE/$scope.previous-base")
  if ! aws s3api head-object --bucket "$BUCKET" --key "$prefix/$manifest" >/dev/null 2>&1; then
    echo "::error::$scope: $prefix/$manifest is not in the bucket; latest.json not moved"
    failed="$failed $scope"
    continue
  fi
  case "$base" in base/?*) ;; *) echo "::error::$scope: no base staged; latest.json not moved"; failed="$failed $scope"; continue ;; esac
  case "$etag" in
    none) set -- --if-none-match '*' ;;
    local) echo "::error::$scope was built without the bucket; not released"; failed="$failed $scope"; continue ;;
    *) set -- --if-match "$etag" ;;
  esac
  if ! tag "$prefix/$base" current; then
    cat "$RELEASE/tag.err" >&2
    echo "::error::$scope: could not tag $prefix/$base current; latest.json not moved"
    failed="$failed $scope"
    continue
  fi
  if aws s3api put-object --bucket "$BUCKET" --key "$prefix/latest.json" --body "$file" \
    --content-type application/json --cache-control no-cache "$@" >/dev/null 2>"$RELEASE/put.err"; then
    echo "$scope: latest.json now names $snapshot"
    if [ -n "$previous" ] && [ "$previous" != "$base" ]; then
      tag "$prefix/$previous" superseded ||
        echo "::warning::$scope: could not tag $prefix/$previous superseded; it is kept until tagged by hand"
    fi
  else
    cat "$RELEASE/put.err" >&2
    if grep -q PreconditionFailed "$RELEASE/put.err"; then
      echo "::error::$scope: latest.json changed since this run read it; not moved"
    else
      echo "::error::$scope: latest.json could not be written"
    fi
    # The new base stays tagged current: a write that failed in transit may
    # still have landed, and a base latest.json names must never be pending.
    # A base kept by mistake costs cents; it can be re-tagged by hand.
    failed="$failed $scope"
  fi
done

if [ -n "$failed" ]; then
  echo "::error::not released:$failed"
  exit 1
fi
