"""Season-aware conference-membership reference data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from src import paths
from src.config import SchoolConfig, load_schools

#: The top-level key naming, per conference code, where a conference with no
#: per-season records pages keeps its member lists instead.
STANDINGS_ARCHIVES = "standings_archives"


def load_membership(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the authored membership document.

    With no explicit ``path``, the rib's packaged copy is preferred — it is
    the source of record — and the data home's mirrored copy is only the
    fallback for an install that ships no packaged data tree. Collect keeps
    the mirror fresh (scripts/collect_board.py) and the data-integrity
    workflow's membership-sync check reports any divergence, so the two
    surfaces can never quietly resolve different member lists.
    """
    if path is not None:
        membership_path = Path(path)
        if not membership_path.exists():
            raise FileNotFoundError(f"Membership file not found: {membership_path}")
    else:
        packaged = paths.packaged_membership_path()
        membership_path = packaged if packaged.exists() else paths.membership_path()
        if not membership_path.exists():
            raise FileNotFoundError(
                "Membership file not found: no packaged copy at "
                f"{packaged} and no data home copy at {membership_path}"
            )

    with membership_path.open(encoding="utf-8") as membership_file:
        document = json.load(membership_file)

    if not isinstance(document, dict):
        raise ValueError("membership.json root must be a JSON object")
    return document


def conference_for(
    slug: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """Return the programme's conference for one season, if declared."""
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return None

    genders = memberships.get(slug)
    if not isinstance(genders, dict):
        return None
    return _window_conference(genders.get(gender), season_year)


def members_of(
    conference: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> set[str]:
    """Return every slug whose window for one season names the conference.

    The inverse of ``conference_for``, and the reason the windows exist: a
    programme can change conference inside the authored span (Trevecca played
    G-MAC men's soccer in 2022 and 2023 and GSC from 2024), so "who was in this
    conference" has a different answer per season. A schools.toml stanza
    carries one conference, the current one; only the windows can answer for
    an earlier season.
    """
    membership_document = document if document is not None else load_membership()
    memberships = membership_document.get("memberships")
    if not isinstance(memberships, dict):
        return set()

    members: set[str] = set()
    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not isinstance(genders, dict):
            continue
        if _window_conference(genders.get(gender), season_year) == conference:
            members.add(slug)
    return members


def _window_conference(windows: object, season_year: int) -> str | None:
    """Walk one programme's windows for the conference covering a season."""
    if not isinstance(windows, list):
        return None

    for window in windows:
        if not isinstance(window, dict):
            continue
        from_season = window.get("from_season")
        to_season = window.get("to_season")
        conference = window.get("conference")
        if (
            _is_year(from_season)
            and _is_year(to_season)
            and from_season <= season_year <= to_season
            and isinstance(conference, str)
        ):
            return conference
    return None


def is_conference_member(
    slug: str,
    gender: str,
    season_year: int,
    conference: str,
    *,
    document: dict[str, Any] | None = None,
) -> bool:
    """Return whether a programme belongs to a conference for one season."""
    return (
        conference_for(
            slug,
            gender,
            season_year,
            document=document,
        )
        == conference
    )


def covered_programmes(document: dict[str, Any]) -> set[tuple[str, str]]:
    """Return every slug and gender pair represented by the document."""
    memberships = document.get("memberships")
    if not isinstance(memberships, dict):
        return set()

    covered: set[tuple[str, str]] = set()
    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not isinstance(genders, dict):
            continue
        for gender in genders:
            if isinstance(gender, str):
                covered.add((slug, gender))
    return covered


def _is_year(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _season_span(
    document: dict[str, Any],
    errors: list[str],
) -> tuple[int, int] | None:
    seasons = document.get("seasons")
    if not isinstance(seasons, dict):
        errors.append("seasons must be an object with integer 'from' and 'to'")
        return None

    from_season = seasons.get("from")
    to_season = seasons.get("to")
    if not _is_year(from_season) or not _is_year(to_season):
        errors.append("seasons 'from' and 'to' must be integers")
        return None
    if from_season > to_season:
        errors.append(
            f"seasons 'from' must not exceed 'to' ({from_season} > {to_season})"
        )
        return None
    return from_season, to_season


def _declared_conferences(
    document: dict[str, Any],
    errors: list[str],
) -> set[str] | None:
    conferences = document.get("conferences")
    if not isinstance(conferences, list) or not all(
        isinstance(conference, str) for conference in conferences
    ):
        errors.append("conferences must be a list of strings")
        return None

    declared = set(conferences)
    if len(conferences) != len(declared):
        errors.append("conferences must not contain duplicate codes")

    missing_structural = sorted({"independent", "non_member"} - declared)
    if missing_structural:
        errors.append(
            f"conferences must declare structural codes: {missing_structural}"
        )
    return declared


def _validate_standings_archives(
    document: dict[str, Any],
    errors: list[str],
    *,
    span: tuple[int, int] | None,
) -> None:
    """Check the optional per-conference standings-archive map.

    The map is evidence, not membership: it says where a conference-season's
    member list was read when the conference publishes no records page. Its
    key need not be a declared conference yet, because the archive is
    authored ahead of the windows it will support (the batch 4 SAC prep
    landed the ids before the windows); ``check-membership --standings``
    resolves the code at verification time and refuses one it cannot find.
    """
    archives = document.get(STANDINGS_ARCHIVES)
    if archives is None:
        return
    if not isinstance(archives, dict):
        errors.append(f"{STANDINGS_ARCHIVES} must be a JSON object keyed by code")
        return

    for conference, archive in archives.items():
        label = f"{STANDINGS_ARCHIVES}[{conference!r}]"
        if not isinstance(conference, str) or not conference:
            errors.append(f"{STANDINGS_ARCHIVES} has invalid conference key")
            continue
        if not isinstance(archive, dict):
            errors.append(f"{label} must be a JSON object")
            continue

        template = archive.get("url_template")
        if not isinstance(template, str) or "{id}" not in template:
            errors.append(f"{label} url_template must be a URL carrying '{{id}}'")

        seasons = archive.get("seasons")
        if not isinstance(seasons, dict) or not seasons:
            errors.append(f"{label} seasons must be a non-empty object")
            continue
        for season, page_id in seasons.items():
            if not isinstance(season, str) or not re.fullmatch(r"\d{4}", season):
                errors.append(f"{label} season key {season!r} must be a 4-digit year")
                continue
            if not isinstance(page_id, str) or not page_id.strip():
                errors.append(f"{label} season {season} id must be a non-empty string")
            if span is not None and not (span[0] <= int(season) <= span[1]):
                errors.append(
                    f"{label} season {season} falls outside {span[0]}-{span[1]}"
                )


def _validate_windows(
    programme: str,
    windows: list[object],
    errors: list[str],
    *,
    span: tuple[int, int] | None,
    declared: set[str] | None,
) -> None:
    if not windows:
        errors.append(f"{programme} must declare at least one membership window")
        return

    valid_ranges: list[tuple[int, int]] = []
    for index, window in enumerate(windows):
        label = f"{programme} window {index}"
        if not isinstance(window, dict):
            errors.append(f"{label} must be a JSON object")
            continue

        conference = window.get("conference")
        if declared is not None and conference not in declared:
            errors.append(f"{label} has unknown conference code {conference!r}")

        source = window.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"{label} must have a non-empty source citation")

        from_season = window.get("from_season")
        to_season = window.get("to_season")
        if not _is_year(from_season):
            errors.append(f"{label} from_season must be an integer")
        if not _is_year(to_season):
            errors.append(f"{label} to_season must be an integer")
        if not _is_year(from_season) or not _is_year(to_season):
            continue
        if from_season > to_season:
            errors.append(
                f"{label} has from_season greater than to_season "
                f"({from_season} > {to_season})"
            )
            continue

        valid_ranges.append((from_season, to_season))
        if span is not None and (from_season < span[0] or to_season > span[1]):
            errors.append(
                f"{label} falls outside {span[0]}-{span[1]}: {from_season}-{to_season}"
            )

    if valid_ranges:
        authored_from = min(from_season for from_season, _ in valid_ranges)
        authored_to = max(to_season for _, to_season in valid_ranges)
        authored_counts = {year: 0 for year in range(authored_from, authored_to + 1)}
        for from_season, to_season in valid_ranges:
            for year in range(from_season, to_season + 1):
                authored_counts[year] += 1

        gaps = [year for year, count in authored_counts.items() if count == 0]
        if gaps:
            errors.append(
                f"{programme} has membership gaps at seasons {gaps}; "
                "cover them explicitly with an independent or non_member window"
            )

    if span is not None:
        season_counts = {year: 0 for year in range(span[0], span[1] + 1)}
        for from_season, to_season in valid_ranges:
            for year in range(
                max(from_season, span[0]),
                min(to_season, span[1]) + 1,
            ):
                season_counts[year] += 1

        overlaps = [year for year, count in season_counts.items() if count > 1]
        if overlaps:
            errors.append(f"{programme} has overlapping windows at seasons {overlaps}")


def validate(
    document: dict[str, Any],
    *,
    schools: list[SchoolConfig] | None = None,
) -> list[str]:
    """Return every membership contract violation in a document."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["membership document root must be a JSON object"]

    if document.get("version") != 1:
        errors.append("version must be 1")

    span = _season_span(document, errors)
    declared = _declared_conferences(document, errors)
    _validate_standings_archives(document, errors, span=span)

    if schools is None:
        schools = load_schools()
    from src.sidearm_live import identity_collisions, programme_slug

    # Identity is gender-wide and last-stanza-wins, so a spelling two stanzas
    # claim is refused here rather than resolved silently at collect time.
    for gender, key, claimants in identity_collisions(schools):
        named = " and ".join(f"{slug} ({label})" for slug, label in claimants)
        errors.append(
            f"identity collision ({gender}): {key!r} is claimed by {named}; "
            "drop the alias or set abbreviation_resolves = false on the "
            "stanzas that share the initialism"
        )

    configured_programmes = {
        (programme_slug(school.name), school.gender) for school in schools
    }
    configured_slugs = {programme_slug(school.name) for school in schools}
    memberships = document.get("memberships")
    if not isinstance(memberships, dict):
        errors.append("memberships must be a JSON object")
        errors.append(f"missing configured programmes: {sorted(configured_programmes)}")
        return errors

    for slug, genders in memberships.items():
        if not isinstance(slug, str) or not slug:
            errors.append(f"invalid institution slug key: {slug!r}")
            continue
        if slug not in configured_slugs:
            errors.append(f"unknown institution slug: {slug!r}")
        if not isinstance(genders, dict):
            errors.append(f"{slug} memberships must be a JSON object")
            continue

        for gender, windows in genders.items():
            programme = f"{slug}:{gender}"
            if not isinstance(gender, str) or not gender:
                errors.append(f"{slug} has invalid gender key: {gender!r}")
                continue
            if not isinstance(windows, list):
                errors.append(f"{programme} windows must be a JSON array")
                continue
            _validate_windows(
                programme,
                windows,
                errors,
                span=span,
                declared=declared,
            )

    covered = covered_programmes(document)
    missing = sorted(configured_programmes - covered)
    if missing:
        errors.append(f"missing configured programmes: {missing}")

    return errors


# ── standings-archive evidence ───────────────────────────────────────────────
#
# check-membership never fetches: the windows are authored, each ``source``
# sentence names the page that proves it, and the script validates the file
# against schools.toml. For a conference whose site publishes per-season
# records pages (``stats.aspx?path=msoc&year=Y&conf=true``) that sentence is
# the whole method. The SAC publishes none (every year answers "no
# statistics available"); its member list per season lives in a standings
# archive addressed by an opaque id, and the id-to-season map is data below,
# so the same ``source`` sentence can name the page and the same offline
# check can read a captured copy of it back.


def standings_archive_url(
    conference: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """The archived standings page for one conference-season, if declared."""
    membership_document = document if document is not None else load_membership()
    archives = membership_document.get(STANDINGS_ARCHIVES)
    if not isinstance(archives, dict):
        return None
    archive = archives.get(conference)
    if not isinstance(archive, dict):
        return None
    template = archive.get("url_template")
    seasons = archive.get("seasons")
    if not isinstance(template, str) or not isinstance(seasons, dict):
        return None
    page_id = seasons.get(str(season_year))
    if not isinstance(page_id, str):
        return None
    return template.replace("{id}", page_id)


@dataclass(frozen=True)
class StandingsPage:
    """What a SideArm ``standings.aspx`` page says about itself."""

    season: int | None
    gender: str | None
    names: list[str]


_STANDINGS_HEADING = re.compile(
    r"(?P<season>\d{4})\s+(?P<gender>Men|Women)'s\s+Soccer\s+Standings"
)


def parse_standings_page(html: str) -> StandingsPage:
    """Read the team names off a SideArm ``standings.aspx`` page.

    The skin prints each row's school twice, in a wide cell and a narrow one
    (and the live 2026 skin prints the narrow one first), so the name is the
    first cell's link text, or the cell's own text on a skin that prints
    plain names. The season and gender come from the table's caption or the
    page heading ("2022 Men's Soccer Standings"); a page served for another
    season is refused by the caller rather than counted.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.sidearm-standings-table") or soup.select_one(
        "table.standings"
    )
    names: list[str] = []
    if table is not None:
        for row in table.select("tbody tr"):
            cell = row.find("td")
            if cell is None:
                continue
            link = cell.find("a")
            text = (link or cell).get_text(" ", strip=True)
            if text:
                names.append(text)

    heading_texts = []
    if table is not None and table.caption is not None:
        heading_texts.append(table.caption.get_text(" ", strip=True))
    heading_texts.extend(
        element.get_text(" ", strip=True) for element in soup.find_all(["h1", "h2"])
    )
    if soup.title is not None:
        heading_texts.append(soup.title.get_text(" ", strip=True))
    season: int | None = None
    gender: str | None = None
    for text in heading_texts:
        match = _STANDINGS_HEADING.search(text)
        if match:
            season = int(match.group("season"))
            gender = match.group("gender").lower()
            break
    return StandingsPage(season=season, gender=gender, names=names)


@dataclass(frozen=True)
class StandingsVerdict:
    """A captured standings page held against the authored windows."""

    url: str | None
    page: StandingsPage
    slugs: dict[str, str]
    expected: set[str]

    @property
    def read(self) -> set[str]:
        return set(self.slugs.values())

    @property
    def missing(self) -> set[str]:
        """Authored members the page does not list."""
        return self.expected - self.read

    @property
    def strangers(self) -> set[str]:
        """Names the page lists that no window claims for the conference."""
        return self.read - self.expected

    @property
    def agrees(self) -> bool:
        return not self.missing and not self.strangers


def verify_standings(
    html: str,
    conference: str,
    gender: str,
    season_year: int,
    *,
    document: dict[str, Any] | None = None,
    schools: list[SchoolConfig] | None = None,
) -> StandingsVerdict:
    """Compare a standings page's team names with the resolved members.

    Names are minted the way opponent text is at collect time: through the
    gender's identity map (every spelling a stanza claims), falling back to
    ``programme_slug`` for a school no stanza knows yet, so the verdict for a
    conference not yet in schools.toml still reads as the slugs its stanzas
    will mint.

    Raises ``ValueError`` when the page names another season or gender than
    the one asked about, so a wrong archive id cannot pass as agreement.
    """
    from src.sidearm_live import identity_aliases, opponent_slug

    membership_document = document if document is not None else load_membership()
    page = parse_standings_page(html)
    if page.season is not None and page.season != season_year:
        raise ValueError(
            f"standings page is the {page.season} season, not {season_year}"
        )
    if page.gender is not None and page.gender != gender:
        raise ValueError(f"standings page is {page.gender}'s soccer, not {gender}'s")
    if not page.names:
        raise ValueError("standings page carries no team rows")

    aliases = identity_aliases(
        schools if schools is not None else load_schools(), gender
    )
    slugs = {name: opponent_slug(name, aliases) for name in page.names}
    expected = members_of(conference, gender, season_year, document=membership_document)
    return StandingsVerdict(
        url=standings_archive_url(
            conference, season_year, document=membership_document
        ),
        page=page,
        slugs=slugs,
        expected=expected,
    )
