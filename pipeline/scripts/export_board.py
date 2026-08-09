"""Export a season's fixtures as board JSON.

The Touchline rib's board reads plain JSON from the consumer's own data
directory — no database. This command is the writer for that contract:
it projects the merged parquet archive into

    data/fixtures/<season>-<gender>.json

matching ``touchline.fixtures/1``.

Two things this deliberately does NOT do:

* It never invents an unplayed fixture. The archive only holds games with a
  box score, so every row it emits has ``status: final``. A season with no
  forward fixtures is reported as such rather than padded.
* It never guesses a programme. Team names are matched to membership slugs
  through an explicit slugifier, and any name that fails to match is reported
  by name in the run summary instead of being silently dropped.

Exit codes: 0 complete; 1 the season produced no rows, or names went
unmatched; 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import paths
from src.config import DEFAULT_CONFIG, load_schools

FIXTURES_SCHEMA = "touchline.fixtures/1"


def slugify(name: str) -> str:
    """Programme display name -> membership slug.

    'Oklahoma Christian' -> 'oklahoma-christian'. Punctuation is dropped
    rather than transliterated so 'St. Mary's' and 'St Marys' converge.

    This is the FALLBACK only. Team strings in the archive drift ('Fort Hays
    State' vs 'Fort Hays St.' vs '#16 Fort Hays St.'), and no slugifier can
    reconcile those — that is what the adjudicated identity map is for.
    """
    cleaned = re.sub(r"[^\w\s-]", "", str(name).strip().lower())
    return re.sub(r"[\s_]+", "-", cleaned)


def load_identity_map() -> dict[str, str | None]:
    """canon.json's `opponents` table: every distinct team string seen in the
    archive, mapped to an institution slug (or None for a non-member).

    Returning an empty map when the artifact is absent is deliberate — the
    caller then falls back to slugify and REPORTS what failed to match, rather
    than silently attributing a drifted name to the wrong programme.
    """
    canon = paths.canon_path()
    if not canon.exists():
        return {}
    try:
        data = json.loads(canon.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str | None] = {}
    for raw, entry in (data.get("opponents") or {}).items():
        if isinstance(entry, dict):
            out[str(raw)] = entry.get("institution_slug")
    return out


def normalize_date(raw: object) -> str | None:
    """The archive stores two formats: ISO from StatCrew, M/D/YYYY from
    SideArm, plus the literal 'Unknown'. Return ISO or None — never a guess."""
    text = str(raw).strip()
    if not text or text.lower() in {"unknown", "nan", "none"}:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def gender_of_ordinal(config_path: Path) -> dict[int, str]:
    """game_id // 1_000_000 is the school ordinal; schools.toml carries the
    gender. This is the only reliable gender axis — the parquet has none."""
    return {s.ordinal: s.gender for s in load_schools(config_path)}


def build(
    season: int,
    gender: str,
    conference: str,
    wanted: list[str],
    config_path: Path,
) -> tuple[dict, list[str]]:
    archive = paths.structured_root() / "all" / "games.parquet"
    if not archive.exists():
        raise SystemExit(f"no merged archive at {archive} — run reparse first")

    games = pd.read_parquet(archive)
    by_ordinal = gender_of_ordinal(config_path)
    games["ordinal"] = games["game_id"] // 1_000_000
    games["gender"] = games["ordinal"].map(by_ordinal)

    season_rows = games[(games["season_year"] == season) & (games["gender"] == gender)]

    identity = load_identity_map()

    def resolve(raw: object) -> str:
        """Team string -> slug. The adjudicated map wins; slugify is the
        fallback for a string the map has never seen."""
        text = str(raw)
        if text in identity:
            mapped = identity[text]
            # A string classified as a non-member resolves to its own stable
            # slug so two different non-members never collapse into one.
            return mapped if mapped else slugify(text)
        return slugify(text)

    wanted_set = set(wanted)
    fixtures: list[dict] = []
    unmatched: set[str] = set()
    seen_slugs: set[str] = set()

    for row in season_rows.itertuples(index=False):
        home = resolve(row.home_team)
        away = resolve(row.away_team)
        for slug, raw in ((home, row.home_team), (away, row.away_team)):
            if slug not in wanted_set:
                unmatched.add(str(raw))
        # A fixture belongs to this board when at least one side is a member;
        # dropping non-member opponents entirely would hide real games.
        if home not in wanted_set and away not in wanted_set:
            continue
        date = normalize_date(row.date)
        if date is None:
            continue
        seen_slugs.update({home, away} & wanted_set)
        conf_flag = row.is_conference_game
        fixtures.append(
            {
                "id": str(row.game_id),
                "date": date,
                "home": home,
                "away": away,
                **({"venue": str(row.venue)} if pd.notna(row.venue) else {}),
                "status": "final",
                "home_score": int(row.home_score),
                "away_score": int(row.away_score),
                **(
                    {"conference_game": bool(conf_flag)}
                    if conf_flag is not None and pd.notna(conf_flag)
                    else {}
                ),
                **({"source_url": str(row.source_url)} if pd.notna(row.source_url) else {}),
            }
        )

    # The archive stores one row per SCRAPING SCHOOL, so a match between two
    # collected programmes appears twice under different game_ids (Harding's
    # 1202507 and Rogers State's 6202507 are the same 2025-09-25 fixture).
    # Collapse on the match itself — date plus the unordered pair — keeping the
    # lowest game_id so the choice is deterministic across runs.
    deduped: dict[tuple[str, str, str], dict] = {}
    duplicates = 0
    for fx in fixtures:
        pair = tuple(sorted((fx["home"], fx["away"])))
        key = (fx["date"], pair[0], pair[1])
        prior = deduped.get(key)
        if prior is None:
            deduped[key] = fx
            continue
        duplicates += 1
        if int(fx["id"]) < int(prior["id"]):
            deduped[key] = fx
    fixtures = sorted(deduped.values(), key=lambda f: (f["date"], f["id"]))

    # `is_conference_game` is NULL for every row in the archive, so a table
    # built on it would count non-conference friendlies. Derive it instead:
    # a fixture is a conference game when BOTH sides are members this season.
    # This is a derivation, not a citation, and the file says so.
    for fx in fixtures:
        fx["conference_game"] = fx["home"] in wanted_set and fx["away"] in wanted_set

    # Programme display names, taken from the archive where a member actually
    # appeared so the board shows the published name rather than a slug.
    display: dict[str, str] = {}
    for row in season_rows.itertuples(index=False):
        for slug, raw in (
            (resolve(row.home_team), row.home_team),
            (resolve(row.away_team), row.away_team),
        ):
            # Prefer the longest seen spelling: 'Fort Hays State' reads better
            # than 'Fort Hays St.', and a ranked '#16 …' prefix is never a name.
            if slug in wanted_set:
                text = str(raw).lstrip("#0123456789 ").strip()
                if len(text) > len(display.get(slug, "")):
                    display[slug] = text

    programmes = [
        {"slug": slug, "name": display.get(slug, slug.replace("-", " ").title())}
        for slug in sorted(wanted_set)
    ]
    missing = sorted(wanted_set - seen_slugs)

    payload = {
        "schema": FIXTURES_SCHEMA,
        "season": season,
        "gender": gender,
        "conference": conference,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conference_game_source": "derived:both-members",
        "programmes": programmes,
        "fixtures": fixtures,
    }
    if missing:
        payload["missing"] = missing
    return payload, sorted(unmatched), duplicates


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export a season's board JSON from the merged parquet archive.",
        epilog="Exit codes: 0 complete; 1 empty season or unmatched names; 2 usage error.",
    )
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--gender", choices=["men", "women"], required=True)
    ap.add_argument("--conference", required=True)
    ap.add_argument(
        "--programmes",
        required=True,
        help="Comma-separated membership slugs the caller resolved.",
    )
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    wanted = [s.strip() for s in args.programmes.split(",") if s.strip()]
    if not wanted:
        print("--programmes resolved to an empty list", file=sys.stderr)
        return 2

    payload, unmatched, duplicates = build(
        args.season, args.gender, args.conference, wanted, Path(args.config)
    )

    out_dir = paths.data_root() / "data" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.season}-{args.gender}.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    played = len(payload["fixtures"])
    conf = sum(1 for f in payload["fixtures"] if f["conference_game"])
    print(
        f"wrote {out_path} — {len(payload['programmes'])} programmes, "
        f"{played} fixtures ({played} played, 0 upcoming), {conf} conference"
    )
    if duplicates:
        print(
            f"collapsed {duplicates} duplicate row(s): the archive stores one row per "
            "scraping school, so a match between two collected programmes appears twice"
        )
    print(
        "conference flag DERIVED as both-sides-are-members — the archive's own "
        "is_conference_game is NULL for every row"
    )
    if payload.get("missing"):
        print(f"no fixtures found for: {', '.join(payload['missing'])}")
    if unmatched:
        print(
            "opponent names outside the member list (not an error, reported for "
            f"transparency): {', '.join(unmatched[:12])}"
            + (f" … and {len(unmatched) - 12} more" if len(unmatched) > 12 else "")
        )
    print(
        "NOTE: the archive holds only games with a box score, so every fixture "
        "above is already played. Forward fixtures require live schedule "
        "collection, which is not built yet."
    )
    return 0 if played else 1


if __name__ == "__main__":
    raise SystemExit(main())
