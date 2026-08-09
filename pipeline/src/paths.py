"""Data-root resolution — the single seam between pipeline code and disk.

All durable data (raw HTML cache, parquet, reference artifacts, error
reports) lives in a consumer-owned data directory — never inside this
package. Resolution order:

  1. TOUCHLINE_DATA_DIR environment variable
  2. the current working directory (workflow runs execute with cwd = the
     data repo)

Everything here is a function, not a constant, so a test or caller that
changes the environment sees the change at call time. Code-like config
(config/schools.toml) deliberately stays package-relative — see
src/config.py DEFAULT_CONFIG.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Derived-index DSN. The database is rebuildable from the files under
#: data_root(); it is never the system of record.
FALLBACK_DATABASE_URL = "postgresql://lume@localhost:5432/touchline"


def data_root() -> Path:
    """The consumer-owned data directory."""
    return Path(os.environ.get("TOUCHLINE_DATA_DIR", ".")).resolve()


def raw_html_dir() -> Path:
    return data_root() / "data" / "raw_html"


def structured_root() -> Path:
    return data_root() / "data" / "structured"


def source_urls_path() -> Path:
    return data_root() / "data" / "source_urls.csv"


def reference_dir() -> Path:
    return data_root() / "data" / "reference"


def canon_path() -> Path:
    return reference_dir() / "canon.json"


def membership_path() -> Path:
    return reference_dir() / "membership.json"


def errors_dir() -> Path:
    return data_root() / "data" / "errors"


def default_database_url() -> str:
    """DATABASE_URL env var, else the local touchline database."""
    return os.environ.get("DATABASE_URL", FALLBACK_DATABASE_URL)
