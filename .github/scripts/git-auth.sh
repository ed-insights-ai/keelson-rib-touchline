#!/usr/bin/env bash
# Point a checkout's GitHub auth at a (fresh) GitHub App token.
#
#   git-auth.sh <checkout> <token>
#
# App tokens last an hour and a division's collect can run longer, so the
# collect jobs check out with persist-credentials off, call this before their
# first fetch, and call it again with a newly minted token right before they
# push. The header value is masked in the log.
set -euo pipefail
dir=${1:?checkout}
token=${2:?token}
header=$(printf 'x-access-token:%s' "$token" | base64 | tr -d '\n')
echo "::add-mask::$header"
git -C "$dir" config --local http.https://github.com/.extraheader "AUTHORIZATION: basic $header"
