"""One recipe per platform: how a programme's pages are found, proven and read.

``collect_programme`` (sidearm_live.py) and the board collector's matches
phase are platform-neutral.  They fetch through the shared conditional seam,
archive the bytes, cache the parse, and record an outcome per layer.  What
differs between platforms is where a season's pages live, how a served page
proves its season, and how its markup is read into the fixture, player and
statistics rows the rest of the pipeline consumes.  A recipe bundles exactly
those, so nothing downstream (collect_board, coverage, data-integrity, the
site) has to know a second platform exists.

``SIDEARM`` is the SideArm path, function for function.  ``PRESTO`` is
PrestoSports (pipeline/src/presto.py), all four layers: the same outcome
states, page cache, raw-page archive, statistics line shapes and match
detail shape, so a PrestoSports programme collects exactly like a SideArm
one.  A platform whose season statistics live at an address the base URL
alone cannot build carries ``locate_stats``.  A platform with no collector
for a layer raises ``NoCollector`` from the member that would start it,
which the collectors record as the ``no-collector`` state for that layer
alone, with a reason naming the platform and the layer.  ``LIVE_COLLECTORS``
maps a stanza's ``live_scraper`` value onto its recipe.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import requests

from src import presto, sidearm_live
from src.config import DEFAULT_LIVE_COLLECTOR, SchoolConfig
from src.sidearm_live import PublishedPage


class NoCollector(NotImplementedError):
    """A recipe has no collector for one of its layers yet.

    Raised by the recipe member that would start the layer (``layer_url`` for
    a season page, ``boxscore_links`` for the matches phase) before any
    request is spent.  ``collect_programme`` and the board collector turn it
    into the ``no-collector`` state for that layer; the layers the recipe
    does implement stand on their own.
    """

    def __init__(self, platform: str, layer: str, *, note: str = "") -> None:
        super().__init__(
            f"no {layer} collector for platform '{platform}'"
            + (f" {note}" if note else "")
        )
        self.platform = platform
        self.layer = layer

    def reason(self, school: SchoolConfig) -> str:
        """The outcome reason in the collector's voice: who, then what."""
        return f"{school.name} {school.gender}: {self}"


@dataclass(frozen=True)
class Recipe:
    """What one platform contributes to a collection.

    Every member is a plain function, so a recipe is a table rather than a
    class hierarchy: ``collect_programme`` reads the table, and a test can
    build one from stand-ins.
    """

    platform: str
    #: The URL of one season layer (schedule, roster, stats) under the
    #: stanza's sport base URL.
    layer_url: Callable[[str, int, str], str]
    #: Refuse a served page that does not prove the requested season (a
    #: silent redirect or fallback to another season).
    assert_served_season: Callable[[PublishedPage, int, str], None]
    #: Read a served schedule page into fixture rows (``page_url``, ``year``,
    #: ``owner_slug``, ``aliases``, ``members`` as keywords).
    parse_schedule: Callable[..., list[dict[str, object]]]
    #: Refuse a freshly served schedule that parsed but cannot be trusted (a
    #: past-season URL rendering the current season; a page with no schedule
    #: shape at all).  Runs on new content only: an archived page proved
    #: itself when it was archived.
    assert_schedule_proven: Callable[..., None]
    #: Read a served roster page into player rows (``page_url`` keyword).
    parse_roster: Callable[..., list[dict[str, str]]]
    #: Read a served statistics page into (players, keepers) season lines.
    parse_stats: Callable[..., tuple[list[dict[str, object]], list[dict[str, object]]]]
    #: Game id to absolute box-score URL, from a schedule page's own links;
    #: the id is the trailing segment of the fixture ids the schedule parse
    #: minted, so the join is exact.
    boxscore_links: Callable[[str, str], dict[str, str]]
    #: Fetch one fixture's box score, prove it is that fixture's, parse it;
    #: with an ``archive`` keyword (``page_state.BoxArchive``), write the
    #: proven page and its parse to the fetch cache.
    collect_match: Callable[..., dict[str, object]]
    #: The proof and parse ``collect_match`` runs over the served page,
    #: over a ``PublishedPage`` read back from the cache: how a parser
    #: change reaches an archived box score without a fetch.
    parse_match: Callable[[PublishedPage, int, dict[str, object]], dict[str, object]]
    #: What identifies the platform's parsers beyond sidearm_live.py's own
    #: source, which is the base of every cached parse's fingerprint: the
    #: digest of the platform module for parsers that live elsewhere, so a
    #: parser change there re-reads the archive; nothing for SideArm.
    parse_identity: tuple[str, ...]
    #: Find the season statistics page when the base URL alone cannot name
    #: it: PrestoSports reveals the team segment in its statistics path by
    #: redirecting ``{base}/{y}-{yy}/teams``, one unfollowed request through
    #: the collection's own session.  ``None`` means ``layer_url`` is the
    #: whole address.
    locate_stats: Callable[[requests.Session, str, int], str] | None = None


def _late(module: ModuleType, name: str) -> Callable[..., Any]:
    """Look ``name`` up on ``module`` at every call.

    A platform module's function names are the seams the collectors' tests
    replace to count or fake a parse (``sidearm_live.parse_schedule_page`` in
    test_page_state.py), and an operator's dry run may do the same.  A table
    that captured the functions at import would carry the originals past
    such a replacement, so the table carries the names.
    """

    def call(*args: Any, **kwargs: Any) -> Any:
        return getattr(module, name)(*args, **kwargs)

    call.__name__ = call.__qualname__ = name
    call.__doc__ = getattr(module, name).__doc__
    return call


def _source_digest(module_file: str | None) -> str:
    return hashlib.sha256(Path(module_file or "").read_bytes()).hexdigest()


SIDEARM = Recipe(
    platform=DEFAULT_LIVE_COLLECTOR,
    layer_url=_late(sidearm_live, "layer_url"),
    assert_served_season=_late(sidearm_live, "assert_served_season"),
    parse_schedule=_late(sidearm_live, "parse_schedule_page"),
    assert_schedule_proven=_late(sidearm_live, "assert_schedule_proven"),
    parse_roster=_late(sidearm_live, "parse_roster_page"),
    parse_stats=_late(sidearm_live, "parse_stats_page"),
    boxscore_links=_late(sidearm_live, "boxscore_links"),
    collect_match=_late(sidearm_live, "collect_match"),
    parse_match=_late(sidearm_live, "parse_match_page"),
    parse_identity=(),
)

PRESTO = Recipe(
    platform=presto.PLATFORM,
    layer_url=_late(presto, "layer_url"),
    assert_served_season=_late(presto, "assert_served_season"),
    parse_schedule=_late(presto, "parse_schedule"),
    assert_schedule_proven=_late(presto, "assert_schedule_proven"),
    parse_roster=_late(presto, "parse_roster"),
    parse_stats=_late(presto, "parse_stats"),
    boxscore_links=_late(presto, "boxscore_links_by_event"),
    collect_match=_late(presto, "collect_match"),
    parse_match=_late(presto, "parse_match_page"),
    parse_identity=(_source_digest(presto.__file__),),
    locate_stats=_late(presto, "locate_stats"),
)

LIVE_COLLECTORS: Mapping[str, Recipe] = {
    SIDEARM.platform: SIDEARM,
    PRESTO.platform: PRESTO,
}


def live_recipe(platform: str) -> Recipe | None:
    """The recipe for a stanza's ``live_scraper`` value, or nothing."""
    return LIVE_COLLECTORS.get(platform)
