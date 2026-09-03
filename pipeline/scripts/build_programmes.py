"""Rebuild data/reference/programmes.json from schools.toml and the Gazetteer.

    uv run build-programmes          # write the file and the trimmed fixtures
    uv run build-programmes --check  # exit 1 when either differs from a fresh build

The build fails, naming every slug and reason, when a stanza cannot
complete its row (tl-891 ruling: a wrong or ambiguous town never lands).
"""

from __future__ import annotations

import argparse
import sys

from src import gazetteer as gz
from src import paths, programmes
from src.config import load_schools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--check", action="store_true", help="Compare only; write nothing."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Never fetch the full Gazetteer; a town missing from the trimmed fixture fails.",
    )
    args = parser.parse_args(argv)

    gazetteer = gz.Gazetteer.load(fetch_full=not args.offline)
    try:
        result = programmes.build(load_schools(), gazetteer)
    except programmes.ProgrammeError as error:
        print(str(error), file=sys.stderr)
        return 1

    outputs = {
        paths.packaged_programmes_path(): programmes.render(result.document),
        gz.TRIMMED_FIXTURE: gazetteer.trimmed_text(result.used_places),
        gz.TRIMMED_COUSUBS_FIXTURE: gazetteer.trimmed_cousubs_text(result.used_places),
    }
    changed = []
    for path, text in outputs.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != text:
            changed.append(path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    count = len(result.document["programmes"])  # type: ignore[arg-type]
    if args.check:
        if changed:
            for path in changed:
                print(f"stale: {path} differs from a fresh build", file=sys.stderr)
            return 1
        print(f"programmes reference is current: {count} rows")
        return 0
    for path in changed:
        print(f"wrote {path}")
    if not changed:
        print(f"programmes reference unchanged: {count} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
