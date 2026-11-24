#!/bin/sh
# Write the journals of every build whose data changed, with Gemini.
#
#   site/journal/run.sh <touchline-ui checkout> <homes dir> <usage.jsonl>
#
# Run from the workspace. The checkout's journal/ must already hold the
# journals on touchline-ui main: they are each conference's previous journal
# (the writer reads it) and where the new ones are written. For each build
# (division x gender) it asks site/journal/stale.ts which conferences changed
# since their journal, writes those with touchline-ui's own journal CLI
# (generate, then the validator drops what the data cannot back), and then the
# build's national journal, which reads the conference journals. A build with
# nothing changed calls no model.
#
# Environment:
#   JOURNAL_DIVISIONS   default "d2 d1"
#   JOURNAL_GENDERS     default "men women"
#   JOURNAL_ONLY        conference keys to write whatever their stamps (a trial);
#                       empty writes the changed ones
#   JOURNAL_NATIONAL    "false" skips the national journals (default true)
#   JOURNAL_MODEL, JOURNAL_SERVICE_TIER, JOURNAL_THINKING, GEMINI_API_KEY
#                       passed to the model command, site/journal/gemini.ts
#
# Exits 1 when any conference or national journal failed; the ones that
# worked are written either way.
set -u

ui=$(cd "$1" && pwd)
homes=$(cd "$2" && pwd)
usage=$(cd "$(dirname "$3")" && pwd)/$(basename "$3")
here=$(cd "$(dirname "$0")" && pwd)
divisions=${JOURNAL_DIVISIONS:-d2 d1}
genders=${JOURNAL_GENDERS:-men women}
model=${JOURNAL_MODEL:-gemini-4-neon}
season=${TOUCHLINE_SEASON:-$(date -u +%Y)}
export JOURNAL_USAGE_LOG="$usage" TOUCHLINE_SEASON="$season"
: >>"$usage"

failed=0
wrote=""
cd "$ui" || exit 2
for div in $divisions; do
  home="$homes/$div-soccer"
  if [ ! -d "$home/data" ]; then
    echo "::warning::no data home for $div at $home; its journals were not written"
    continue
  fi
  for gender in $genders; do
    export TOUCHLINE_NCAA_DIVISION="$div" TOUCHLINE_GENDER="$gender" TOUCHLINE_DATA_DIR="$home"
    export JOURNAL_SCOPE="$div $gender"
    if ! line=$(bun "$here/stale.ts" --only "${JOURNAL_ONLY:-}"); then
      echo "::error::$div $gender: could not read the build's seasons"
      failed=1
      continue
    fi
    keys=$(printf '%s' "$line" | cut -f2)
    if [ -z "$keys" ]; then
      echo "→ $div $gender: no conference changed; no journal written"
      continue
    fi
    echo "→ $div $gender: $keys"
    if ! bun run journal run --conference "$keys" --write \
      --command "$here/gemini.ts" --model "$model" --concurrency 4; then
      failed=1
    fi
    wrote="$wrote $div-$gender"
    if [ "${JOURNAL_NATIONAL:-true}" != false ]; then
      echo "→ $div $gender: national"
      if ! bun run journal run --national --write --command "$here/gemini.ts" --model "$model"; then
        failed=1
      fi
    fi
  done
done

echo "journal builds written:${wrote:- none}"
exit "$failed"
