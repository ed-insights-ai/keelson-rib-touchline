#!/usr/bin/env bash
# The presto units' work home and result, as workflow artifacts between the
# hosted jobs and the self-hosted presto runner.
#
#   presto-artifact.sh seal <file>   # writes <file>.enc and removes <file>
#   presto-artifact.sh open <file>   # reads <file>.enc and writes <file>
#
# An artifact can be downloaded by anyone who can read the repository, and by
# any signed-in GitHub user while the repository is public. These two carry
# season files from the private data homes, so they are stored encrypted:
# AES-256 under a key made from the TOUCHLINE_ARTIFACT_KEY secret and this
# run's id. That secret opens nothing else: the presto runner still gets no
# AWS or GitHub App credential.
#
# Fails closed: nothing is sealed without the secret, and a file that is not
# encrypted is never accepted.
set -euo pipefail

mode=${1:-}
file=${2:-}
[ $# -eq 2 ] && [ -n "$file" ] || { echo "usage: presto-artifact.sh seal|open <file>" >&2; exit 2; }

if [ -z "${TOUCHLINE_ARTIFACT_KEY:-}" ]; then
  echo "::error::the TOUCHLINE_ARTIFACT_KEY secret is not set; refusing to store or read the presto work home in the clear." >&2
  exit 1
fi
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is not set}"
RUN_KEY=$(printf 'touchline presto %s' "$GITHUB_RUN_ID" | openssl dgst -sha256 -hmac "$TOUCHLINE_ARTIFACT_KEY" -r | cut -d' ' -f1)
export RUN_KEY

case "$mode" in
  seal)
    [ -f "$file" ] || { echo "::error::nothing to seal at $file" >&2; exit 1; }
    openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:RUN_KEY -in "$file" -out "$file.enc"
    rm -f "$file"
    ;;
  open)
    [ -f "$file.enc" ] || { echo "::error::no encrypted artifact at $file.enc; refusing anything else." >&2; exit 1; }
    openssl enc -d -aes-256-cbc -pbkdf2 -pass env:RUN_KEY -in "$file.enc" -out "$file"
    ;;
  *) echo "usage: presto-artifact.sh seal|open <file>" >&2; exit 2 ;;
esac
