# Pipeline — Component Rules

- Use `uv` for dependency management and running scripts.
- All Python code uses `snake_case`.
- Durable data never lives in this package. Every data path resolves through
  `src/paths.py`: `TOUCHLINE_DATA_DIR` env var, else the current working
  directory — workflow runs execute with cwd = the consumer-owned data repo
  (e.g. `soccer-data`).
- The JSON data home is the sole system of record: the season files under
  `data/fixtures`, `data/rosters`, `data/stats`, and `data/matches`, plus the
  raw page archive `write_raw_pages` keeps beside them. A derived SQL index
  could be rebuilt from those files if ever needed; none is maintained. (The
  old Postgres/parquet lineage — scrape, reparse, load-db, and friends — was
  retired in 2026; do not resurrect it.)
- `uv run collect-board` is the one collector. It hits the network; its exit 0
  means the coverage manifest was written, named gaps and all.
- Do **not** modify `config/schools.toml` without explicit instruction.
  Conference scope is configuration, not identity — never hardcode a
  conference in logic.
- `sports-data-pipeline` (github.com/ed-insights-ai/sports-data-pipeline) is a
  **read-only frozen reference**. Do not modify or depend on it at runtime.
