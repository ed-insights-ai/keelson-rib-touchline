# The cloud journal

The AI journals on the site (one per conference and build, plus a national one
per build) are written by `.github/workflows/journal.yml`. It runs
touchline-ui's own journal CLI (`bun run journal run --write`) and uses
Gemini as its model command. The validator still drops every claim the data
cannot recompute. Until 2026-11-21 the Mac wrote the journals with `claude -p`.

| File | Does |
|---|---|
| `gemini.ts` | The model command. It reads the prompt on stdin, calls `generateContent` on the Flex tier with retries, and prints the answer. It appends one line of token use and estimated cost per call to `JOURNAL_USAGE_LOG`. |
| `stale.ts` | Lists a build's conferences collected since their journal was written: the journal's `data_collected_at` is not the season file's `collected_at`. A collect commits only what changed, so a quiet conference calls no model. |
| `run.sh` | For each division and gender, it writes the stale conferences, then the national journal when any conference was written. |
| `usage.ts` | Sums the usage log into the run summary's cost table. |

## Switches

- **`TOUCHLINE_JOURNALS=on`** (repository variable): Publish site calls the
  journal job before its site job. Unset, Publish site writes no journals.
  A failed journal job never holds back the site or the snapshot release.
- **`GEMINI_API_KEY`**: a secret in the `production` environment.
- **The touchline-publisher App on touchline-ui**: needs Contents read and
  write. The job commits the journals to touchline-ui main as
  `chore(journal): cloud run DATE [keys]`.
- **Optional variables:** `TOUCHLINE_JOURNAL_MODEL` (default `gemini-4-neon`),
  `TOUCHLINE_JOURNAL_TIER` (`flex` default, or `standard`) and
  `TOUCHLINE_JOURNAL_THINKING` (`low`, `medium` default, `high`, `xhigh`).

## Trial

```sh
gh workflow run journal.yml -R ed-insights-ai/keelson-rib-touchline \
  -f conferences=gac,psac -f divisions=d2 -f genders=men -f national=false -f commit=false
```

A trial keeps the journals as the run's `journals` artifact instead of
committing them. The run summary has the token and cost table, and the
`journal-usage` artifact keeps the raw lines for 90 days.

## Cost

Prices are Google's list prices for Gemini 4 Neon as of November 2026, in USD
per million tokens:

| Tier | Input | Cached input | Output, thinking included |
|---|---|---|---|
| Flex | $1.50 | $0.075 | $7.50 |
| Standard | $3 | $0.15 | $15 |

Flex can refuse a request when Google's capacity is short. `gemini.ts` retries
after 10, 30, 90 and 180 seconds, then asks the Standard tier once, and the
summary counts those fallbacks. The figures are estimates; the Google bill is
the record.
