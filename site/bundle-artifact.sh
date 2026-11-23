#!/bin/sh
# The site bundle as a workflow artifact, between the jobs of publish-site.
#
#   bundle-artifact.sh pack   <bundle dir> <artifact dir>
#   bundle-artifact.sh unpack <artifact dir> <bundle dir>
#
# An artifact can be downloaded by anyone who can read the repository, and by
# any signed-in GitHub user while the repository is public. A bundle cut from
# the private data homes (SOURCE=data) is the dataset, so it is stored
# encrypted: AES-256 under a key made from a secret only the `production`
# environment holds (BUNDLE_KEY_SOURCE) and this run's id. A sample bundle
# (SOURCE=samples) is already public in samples/ and is stored as it is, so
# pull requests, which have no secrets, still build.
#
# Fails closed: a data bundle is never packed without the secret, and an
# unencrypted artifact is never accepted as a data bundle.
set -eu

mode=${1:-}
[ $# -eq 3 ] || { echo "usage: bundle-artifact.sh pack|unpack <from> <to>" >&2; exit 2; }
from=$2
to=$3
: "${SOURCE:?SOURCE is samples or data}"

derive_key() {
  if [ -z "${BUNDLE_KEY_SOURCE:-}" ]; then
    echo "::error::a data bundle needs the production environment's secret to be stored; refusing to store or read it in the clear." >&2
    exit 1
  fi
  BUNDLE_KEY=$(python3 -c '
import hashlib, hmac, os
secret = os.environ["BUNDLE_KEY_SOURCE"].encode()
label = ("touchline site-bundle " + os.environ["GITHUB_RUN_ID"]).encode()
print(hmac.new(secret, label, hashlib.sha256).hexdigest())')
  export BUNDLE_KEY
}

case "$mode" in
  pack)
    [ -d "$from" ] || { echo "::error::no bundle at $from" >&2; exit 1; }
    mkdir -p "$to"
    case "$SOURCE" in
      data)
        derive_key
        tmp="$to/.bundle.tar.gz"
        tar -C "$from" -czf "$tmp" .
        openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BUNDLE_KEY -in "$tmp" -out "$to/bundle.tar.gz.enc"
        rm -f "$tmp"
        echo "packed the data bundle, encrypted"
        ;;
      samples)
        tar -C "$from" -czf "$to/bundle.tar.gz" .
        echo "packed the sample bundle"
        ;;
      *) echo "::error::source is samples or data, not '$SOURCE'" >&2; exit 1 ;;
    esac
    ;;
  unpack)
    mkdir -p "$to"
    case "$SOURCE" in
      data)
        [ -f "$from/bundle.tar.gz.enc" ] || { echo "::error::the data bundle artifact is not encrypted; refusing it." >&2; exit 1; }
        derive_key
        tmp="$from/.bundle.tar.gz"
        openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BUNDLE_KEY -in "$from/bundle.tar.gz.enc" -out "$tmp"
        tar -C "$to" -xzf "$tmp"
        rm -f "$tmp"
        ;;
      samples)
        [ -f "$from/bundle.tar.gz" ] || { echo "::error::no sample bundle in the artifact" >&2; exit 1; }
        tar -C "$to" -xzf "$from/bundle.tar.gz"
        ;;
      *) echo "::error::source is samples or data, not '$SOURCE'" >&2; exit 1 ;;
    esac
    ;;
  *) echo "usage: bundle-artifact.sh pack|unpack <from> <to>" >&2; exit 2 ;;
esac
