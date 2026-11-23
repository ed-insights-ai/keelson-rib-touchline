#!/bin/sh
# Build every site build from a bundle, gate each one, and write the smoke list.
#
#   site/build.sh <touchline-ui checkout> <bundle dir> <site url> <smoke list out>
#
# The bundle dir holds one cut home per division, <div>-soccer/ (see
# pipeline/scripts/cut_bundle.py). The builds go where they are served:
#   /                root division, men     /women/          root division, women
#   /<div>/          other divisions, men   /<div>/women/    other divisions, women
# (infra/main/site.tf site_build_prefixes). The root build goes first because
# Astro empties its outDir, and the root build's outDir is dist/ itself.
#
# This is touchline-ui's `just build` and `just gate` with the base at the
# domain root, run from the rib so the deploy does not depend on just or on the
# Mac's ~/.keelson config. Environment:
#   SITE_DIVISIONS       divisions to build, root first (default "d2 d1")
#   SITE_GENDERS         default "men women"
#   TOUCHLINE_CONTRACTS_DIR, TOUCHLINE_JOURNAL_DIR   passed through to the UI
#
# The smoke list has one line per build: "<path>\t<stamp>\t<pages>", read by
# the workflow's smoke step (touchline-ui scripts/deployed.ts).
set -eu

ui=$(cd "$1" && pwd)
bundle=$(cd "$2" && pwd)
site_url=${3%/}
smoke=$(cd "$(dirname "$4")" && pwd)/$(basename "$4")
divisions=${SITE_DIVISIONS:-d2 d1}
genders=${SITE_GENDERS:-men women}
root=${divisions%% *}

csv() { printf '%s' "$1" | tr -s ' ' ','; }
published_divisions=$(csv "$divisions")
published_genders=$(csv "$genders")

: >"$smoke"
cd "$ui"
for div in $divisions; do
  home="$bundle/$div-soccer"
  if [ ! -f "$home/data/bundle.json" ]; then
    echo "no bundle for $div at $home" >&2
    exit 1
  fi
  for gender in $genders; do
    seg=""
    [ "$div" = "$root" ] || seg="/$div"
    [ "$gender" = men ] || seg="$seg/$gender"
    echo "→ build $div $gender at ${seg:-/}"
    env TOUCHLINE_NCAA_DIVISION="$div" TOUCHLINE_GENDER="$gender" \
      TOUCHLINE_DATA_DIR="$home" \
      TOUCHLINE_GENDERS="$published_genders" TOUCHLINE_NCAA_DIVISIONS="$published_divisions" \
      TOUCHLINE_STRICT_BASE=1 SITE_BASE="${seg:-/}" SITE_URL="$site_url" \
      TOUCHLINE_OUT_DIR="dist$seg" \
      bun run build
    echo "→ gate $div $gender"
    env TOUCHLINE_NCAA_DIVISION="$div" TOUCHLINE_GENDER="$gender" \
      TOUCHLINE_DATA_DIR="$home" \
      TOUCHLINE_GENDERS="$published_genders" TOUCHLINE_NCAA_DIVISIONS="$published_divisions" \
      bun test ./src ./scripts
    stamp=$(sed -n 's/.*name="touchline-build" content="\([^"]*\)".*/\1/p' "dist$seg/index.html" | head -n1)
    pages=$(env TOUCHLINE_NCAA_DIVISION="$div" TOUCHLINE_GENDER="$gender" TOUCHLINE_DATA_DIR="$home" \
      bun scripts/sample.ts "dist$seg")
    printf '%s\t%s\t%s\n' "${seg:-/}" "$stamp" "$pages" >>"$smoke"
  done
done

echo "→ links"
bun scripts/links.ts dist /
