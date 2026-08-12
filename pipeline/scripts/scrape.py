"""CLI entry point: discover → fetch → parse → save for config-driven soccer scraping.

Exit 0 means every discovered game completed, exit 1 means a partial or rejected
run, and exit 2 means an invalid school argument.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from rich.console import Console
from rich.progress import Progress

from src.config import DEFAULT_CONFIG, SchoolConfig, load_schools
from src.discovery import discover_season_games
from src.errors import DiscoveryError
from src.fetcher import GameFetcher
from src.parser import log_parse_error, parse_game
from src.sidearm_discovery import discover_sidearm_season
from src.sidearm_parser import parse_sidearm_game
from src.storage import merge_all_schools, merge_all_seasons, save_season

console = Console()
logger = logging.getLogger(__name__)


@dataclass
class _ScrapeResult:
    parsed: list[dict]
    discovered: int
    failed_game_ids: list[int]
    rejection: str | None = None


def _scrape_season(
    year: int,
    school: SchoolConfig,
    fetcher: GameFetcher,
    *,
    use_cache: bool = True,
    progress: Progress,
) -> _ScrapeResult:
    """Scrape one school season and report whether every discovered game completed."""
    # Refuse before discovery, which always hits the network. Ordinal 0 means
    # unassigned; building a game_id from it would collide with every other
    # unassigned school rather than namespacing this one.
    if not school.ordinal:
        return _ScrapeResult(
            parsed=[],
            discovered=0,
            failed_game_ids=[],
            rejection=(
                f"School '{school.name}' ({school.abbreviation}) has no ordinal, "
                f"so stable game_ids cannot be built for it; assign a unique "
                f"ordinal in schools.toml to scrape it through this lineage"
            ),
        )
    try:
        if school.scraper == "sidearm":
            urls = discover_sidearm_season(year, base_url=school.base_url)
        else:
            urls = discover_season_games(
                year,
                base_url_template=school.base_url,
                prefix=school.prefix,
            )
    except DiscoveryError as exc:
        return _ScrapeResult(
            parsed=[],
            discovered=0,
            failed_game_ids=[],
            rejection=str(exc),
        )

    task = progress.add_task(f"[cyan]{school.abbreviation} {year}", total=len(urls))
    parsed: list[dict] = []
    failed_game_ids: list[int] = []

    for gu in urls:
        game_id = school.ordinal * 1_000_000 + year * 100 + gu.game_num
        html: str | None = None
        try:
            html = fetcher.fetch(
                gu.url,
                year,
                gu.game_num,
                use_cache=use_cache,
                school_abbrev=school.abbreviation,
            )
            if school.scraper == "sidearm":
                result = parse_sidearm_game(
                    html,
                    game_id,
                    gu.url,
                    year,
                    school_abbrev=school.abbreviation,
                    school_name=school.name,
                )
            else:
                result = parse_game(html, game_id, gu.url, year, school_name=school.name)
            parsed.append(result)
        except Exception as exc:  # noqa: BLE001
            failed_game_ids.append(game_id)
            logger.warning("Error parsing game %s: %s", game_id, exc)
            log_parse_error(game_id, year, exc, html)
        progress.advance(task)

    return _ScrapeResult(
        parsed=parsed,
        discovered=len(urls),
        failed_game_ids=failed_game_ids,
    )


def main() -> None:
    """Entry point for ``uv run scrape``."""
    parser = argparse.ArgumentParser(
        description="Scrape men's soccer stats",
        epilog="Exit codes: 0 complete; 1 partial or rejected; 2 unknown school.",
    )
    parser.add_argument("--year", type=int, default=None, help="Single season year (default: all)")
    parser.add_argument("--no-cache", action="store_true", help="Bypass HTML cache")
    parser.add_argument("--school", type=str, default=None, help="School abbreviation (e.g. HU)")
    parser.add_argument(
        "--config", type=str, default=str(DEFAULT_CONFIG), help="Path to schools.toml"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    schools = load_schools(args.config)
    enabled = [s for s in schools if s.enabled]

    if args.school:
        enabled = [s for s in enabled if s.abbreviation.upper() == args.school.upper()]
        if not enabled:
            console.print(f"[red]No enabled school found with abbreviation '{args.school}'")
            raise SystemExit(2)

    fetcher = GameFetcher()
    problems: list[str] = []

    with Progress(console=console) as progress:
        for school in enabled:
            years = [args.year] if args.year else school.years
            console.rule(f"[bold blue]{school.name}")
            for year in years:
                result = _scrape_season(
                    year, school, fetcher, use_cache=not args.no_cache, progress=progress
                )
                if result.rejection:
                    problems.append(
                        f"{school.abbreviation} {year}: discovery rejected — "
                        f"{result.rejection}"
                    )
                elif result.failed_game_ids:
                    failed_ids = ", ".join(str(game_id) for game_id in result.failed_game_ids)
                    problems.append(
                        f"{school.abbreviation} {year}: "
                        f"{len(result.failed_game_ids)}/{result.discovered} games failed: "
                        f"{failed_ids}"
                    )

                if result.parsed:
                    save_season(result.parsed, year, school_abbrev=school.abbreviation)
                    console.print(f"  [green]Saved {len(result.parsed)} games for {year}")
                else:
                    console.print(f"  [yellow]No games found for {year}")

            merge_all_seasons(years, school_abbrev=school.abbreviation)
            console.print(f"[bold green]Merged {school.name} seasons.")

    # Final cross-school merge
    if len(enabled) > 1:
        merge_all_schools(config=args.config)
        console.print("[bold green]Merged all schools into data/structured/all/")

    if problems:
        console.print("[bold red]Scrape incomplete:")
        for problem in problems:
            console.print(f"[red]- {problem}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
