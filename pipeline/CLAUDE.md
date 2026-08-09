# Pipeline — Component Rules

- Use `uv` for dependency management and running scripts.
- All Python code uses `snake_case`.
- Durable data never lives in this package. Every data path resolves through
  `src/paths.py`: `TOUCHLINE_DATA_DIR` env var, else the current working
  directory — workflow runs execute with cwd = the consumer-owned data repo
  (e.g. `soccer-data`). Parquets are ignored build output; rebuild them
  offline with `uv run reparse` from the data repo's committed
  `data/raw_html/` archive and `data/source_urls.csv`.
- `uv run scrape` is NOT offline even with the cache warm — discovery always
  hits the network. Any backfill uses `reparse`, never `scrape`.
- The database (`postgresql://lume@localhost:5432/touchline` by default,
  override with `DATABASE_URL`) is a rebuildable derived index, never the
  system of record.
- Do **not** modify `config/schools.toml` without explicit instruction.
  Conference scope is configuration, not identity — never hardcode a
  conference in logic.
- `sports-data-pipeline` (github.com/ed-insights-ai/sports-data-pipeline) is a
  **read-only frozen reference**. Do not modify or depend on it at runtime.
