"""Rewrite every research JSON file in the canonical human-readable shape.

Research files are written free-hand by workflow agents, so their JSON
formatting drifts per run. The canonical shape keeps top-level scalars and
objects pretty-printed while each list item (a finding, a dropped claim,
an unswept surface) sits on one compact row — a scannable line-per-fact
layout. Idempotent and content-preserving: the rewritten document parses
back to exactly the same data or the file is left untouched.
"""

from __future__ import annotations

import json
import sys

from src import paths


def _one_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def canonical(doc: dict) -> str:
    lines = ["{"]
    top = list(doc.items())
    for index, (key, value) in enumerate(top):
        comma = "," if index < len(top) - 1 else ""
        if isinstance(value, list) and value:
            lines.append(f'  "{key}": [')
            for j, item in enumerate(value):
                item_comma = "," if j < len(value) - 1 else ""
                lines.append(f"    {_one_line(item)}{item_comma}")
            lines.append(f"  ]{comma}")
        elif isinstance(value, dict) and value:
            lines.append(f'  "{key}": {{')
            entries = list(value.items())
            for j, (inner_key, inner_value) in enumerate(entries):
                entry_comma = "," if j < len(entries) - 1 else ""
                lines.append(
                    f"    {_one_line(inner_key)}: {_one_line(inner_value)}{entry_comma}"
                )
            lines.append(f"  }}{comma}")
        else:
            lines.append(f'  "{key}": {_one_line(value)}{comma}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    root = paths.data_root() / "data" / "research"
    if not root.is_dir():
        print(f"no research directory at {root} — nothing to normalize")
        return 0
    rewritten = skipped = 0
    for path in sorted(root.rglob("*.json")):
        original = path.read_text(encoding="utf-8")
        try:
            doc = json.loads(original)
        except json.JSONDecodeError as exc:
            print(f"SKIP {path}: not valid JSON ({exc})", file=sys.stderr)
            skipped += 1
            continue
        if not isinstance(doc, dict):
            print(f"SKIP {path}: top level is not an object", file=sys.stderr)
            skipped += 1
            continue
        text = canonical(doc)
        if json.loads(text) != doc:
            print(f"SKIP {path}: canonical form failed round-trip", file=sys.stderr)
            skipped += 1
            continue
        if text != original:
            path.write_text(text, encoding="utf-8")
            rewritten += 1
    print(f"normalized {rewritten} file(s), skipped {skipped}, under {root}")
    return 1 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
