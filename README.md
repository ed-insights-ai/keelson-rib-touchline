# Touchline

Touchline collects the published college-soccer schedule, roster, player
season statistics, and a box score for every played match — current season
and archive back to 2016 — then renders those files as a living season board.
Standings tables, Postgres, parquet, and generated reports remain outside the
first-contact flow.

`/touchline <folder-name>` creates an ordinary data directory under Keelson's
default workspace and registers it for UI/workflow scope. It is not initialized
as a Git repository, and Git is not required.

Conference scope is configuration, not identity: the first deployment covers
the GAC, and schools/conferences are defined per data home.

## Migrating existing data homes

Season files are conference-sharded. Before using this version with a data home
that still has legacy names such as `data/fixtures/2026-men.json`, run:

```bash
TOUCHLINE_DATA_DIR=/path/to/data-home uv run --project pipeline migrate-shard --conference GAC
```

The migration updates fixture files to `touchline.fixtures/2`, adds each
programme's conference, renames all four season layers, and removes the legacy
files. It is idempotent and refuses to overwrite a differing shard. The reader
does not fall back to legacy filenames.

The original product and implementation contract lives in the
[Touchline rib specification](https://github.com/ed-insights-ai/ed-insights-platform/blob/main/docs/specs/touchline-rib.md).
