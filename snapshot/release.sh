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
# Environment: BUCKET, SOURCE (data or samples), RELEASE (build.sh's
# $WORK/release, holding <scope>.latest.json and <scope>.etag).
set -eu
: "${BUCKET:?}" "${SOURCE:?}" "${RELEASE:?}"
case "$SOURCE" in data | samples) ;; *) echo "SOURCE is data or samples" >&2; exit 2 ;; esac

scopes=$(find "$RELEASE" -maxdepth 1 -name "*.latest.json" | sed "s|.*/||; s/\.latest\.json$//" | sort)
[ -n "$scopes" ] || { echo "::error::nothing staged in $RELEASE"; exit 1; }
if echo "$scopes" | grep -qx all; then scopes="all $(echo "$scopes" | grep -vx all)"; fi

failed=""
for scope in $scopes; do
  prefix="snapshots/$SOURCE/$scope"
  file="$RELEASE/$scope.latest.json"
  etag=$(cat "$RELEASE/$scope.etag")
  snapshot=$(jq -r .snapshot "$file")
  manifest=$(jq -r .manifest "$file")
  if ! aws s3api head-object --bucket "$BUCKET" --key "$prefix/$manifest" >/dev/null 2>&1; then
    echo "::error::$scope: $prefix/$manifest is not in the bucket; latest.json not moved"
    failed="$failed $scope"
    continue
  fi
  case "$etag" in
    none) set -- --if-none-match '*' ;;
    local) echo "::error::$scope was built without the bucket; not released"; failed="$failed $scope"; continue ;;
    *) set -- --if-match "$etag" ;;
  esac
  if aws s3api put-object --bucket "$BUCKET" --key "$prefix/latest.json" --body "$file" \
    --content-type application/json --cache-control no-cache "$@" >/dev/null 2>"$RELEASE/put.err"; then
    echo "$scope: latest.json now names $snapshot"
  else
    cat "$RELEASE/put.err" >&2
    if grep -q PreconditionFailed "$RELEASE/put.err"; then
      echo "::error::$scope: latest.json changed since this run read it; not moved"
    else
      echo "::error::$scope: latest.json could not be written"
    fi
    failed="$failed $scope"
  fi
done

if [ -n "$failed" ]; then
  echo "::error::not released:$failed"
  exit 1
fi
