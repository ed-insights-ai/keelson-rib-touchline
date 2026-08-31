# Touchline Pipeline

Data-collection pipeline for the Touchline rib. Collects published college
soccer schedules, rosters, season statistics, and box scores into the JSON
data home — the system of record.

## Setup

```bash
cd pipeline
uv sync
```

## Usage

```bash
# Collect one conference season into the data home
TOUCHLINE_DATA_DIR=/path/to/data-home uv run collect-board \
  --season 2025 --gender men --conference GAC --programmes harding,...

# Probe a new site before onboarding it
uv run probe --url https://example.edu/sports/mens-soccer --conference GAC

# Validate the membership reference
uv run check-membership

# Run tests
uv run pytest
```

See `docs/src/content/docs/reference/pipeline-cli.md` for the full command
reference.

## Related

The [`sports-data-pipeline`](https://github.com/ed-insights-ai/sports-data-pipeline) repo is a **frozen tutorial/reference** — it is not actively developed. This package is the production pipeline.
