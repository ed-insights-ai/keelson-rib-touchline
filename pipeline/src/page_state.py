"""Per-page sidecar state — the memory that makes a collect conditional.

Today every collect re-fetches and re-parses every page unconditionally.  The
politeness mechanism the scale plan depends on is the ability to ask a site
"did this change?" and move on immediately when it did not.  That question
needs memory: the validators the server handed us last time (ETag,
Last-Modified), a hash of the bytes we archived, and the parse output those
bytes produced — so an unchanged page skips the transfer where the server
cooperates (a 304 carries no body) and skips the parse and the write in
every case.

The state lives in a sidecar JSON next to the archived page it describes:

    data/raw_html/{slug}/{season}-{gender}-{kind}.html          the bytes
    data/raw_html/{slug}/{season}-{gender}-{kind}.state.json    what we know

The sidecar is only ever trusted while the archived page it describes is
still on disk, and the cached parse output is only ever trusted while its
``fingerprint`` — the identity of the parse, covering the parser source and
every configured input that shapes its output — still matches.  A stale
fingerprint does not force a re-fetch: HTTP validators stay useful (a 304
still proves the archived bytes are current), and the caller re-parses the
archived bytes instead.

Measured 2026-08-31 against one SideArm site (fhsuathletics.com): the CDN
serves ``Last-Modified`` and honors ``If-Modified-Since`` with a genuine 304
and no body; it serves no ETag.  But the validators only hold within the
CDN's cache window (``max-age`` ~400-600s there): once the cached object
expires the origin re-renders, and the re-render carries a fresh
``Last-Modified`` and different bytes over identical content.  Both tiers
are therefore real — the 304 inside the window, the content signature
across re-renders — and the signature must normalize away render noise or
it would never match day to day.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAGE_STATE_SCHEMA = "touchline.page-state/1"

# What a SideArm re-render changes with no change of content, measured
# 2026-08-31 by diffing two renders of one schedule page (identical length,
# 208 differing regions, every one of the three shapes below):
#
#   5ffe13e2-b5b8-...        per-render component instance UUIDs, in the
#                            embedded payloads and the component tags
#   urlArgs = '6390276349…'  a cache-busting ticks value
#   bmtxykf1w / bilooxr41    a randomized CSS class prefix on the ad-blocker
#                            dialog: 9 chars, lowercase with digits, used in
#                            markup, script, and style
#
# Normalizing these is safe in both directions.  Too little (another theme's
# noise shape) means the signature never matches and the page is re-parsed —
# exactly today's behaviour.  Too much would only hide a change that lives
# ENTIRELY inside a random-looking token, and nothing the parsers read (game
# ids, dates, scores, sidearm-* classes, boxscore links) has that shape.
_RENDER_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_RENDER_URL_ARGS = re.compile(r"(urlArgs = ')\d+(')")
# The nonce: 8-12 lowercase-with-digit chars.  The boundaries are asymmetric
# on purpose — the leading guard refuses a mid-word start ("Harding2019" must
# not lose "arding2019"), while the trailing guard permits the "_" and
# uppercase that follow the nonce in its BEM-style uses ("bmtxykf1w__inner").
# Verified against the two archived renders: this normalization makes them
# byte-identical.
_RENDER_NONCE = re.compile(
    r"(?<![A-Za-z0-9_])[a-z](?=[a-z0-9]*\d)[a-z0-9]{7,11}(?![a-z0-9])"
)


def content_signature(html: str) -> str:
    """The identity of a served page's content, stable across re-renders."""
    text = _RENDER_UUID.sub("", html)
    text = _RENDER_URL_ARGS.sub(r"\1\2", text)
    text = _RENDER_NONCE.sub("", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PageState:
    """What a previous run knew about one archived page."""

    etag: str | None
    last_modified: str | None
    signature: str
    requested_url: str
    final_url: str
    outcome_state: str
    outcome_count: int
    outcome_reason: str | None
    #: The parse output the archived bytes produced, or ``None`` when the
    #: stored fingerprint no longer matches — the page may be unchanged, but
    #: the parse that read it is not, so the bytes must be read again.
    parsed: dict[str, Any] | None
    html_path: Path

    def read_html(self) -> str:
        return self.html_path.read_text(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class PageStateStore:
    """Load and persist sidecar state for one (season, gender) collection."""

    def __init__(self, root: Path, season: int, gender: str) -> None:
        self.root = Path(root)
        self.season = season
        self.gender = gender

    def html_path(self, slug: str, kind: str) -> Path:
        return (
            self.root
            / "data"
            / "raw_html"
            / slug
            / f"{self.season}-{self.gender}-{kind}.html"
        )

    def state_path(self, slug: str, kind: str) -> Path:
        return self.html_path(slug, kind).with_suffix(".state.json")

    def load(self, slug: str, kind: str, fingerprint: str) -> PageState | None:
        """The stored state, or ``None`` when there is nothing safe to reuse.

        The sidecar describes the archived bytes beside it; without those
        bytes on disk it can validate nothing (a 304 would prove currency of
        a page we no longer hold) and it is discarded.
        """
        path = self.state_path(slug, kind)
        html_path = self.html_path(slug, kind)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not html_path.is_file():
            return None
        signature = payload.get("signature")
        final_url = payload.get("final_url")
        if not isinstance(signature, str) or not isinstance(final_url, str):
            return None
        outcome = payload.get("outcome")
        outcome_dict = outcome if isinstance(outcome, dict) else {}
        parsed = payload.get("parsed")
        if payload.get("fingerprint") != fingerprint or not isinstance(parsed, dict):
            parsed = None
        etag = payload.get("etag")
        last_modified = payload.get("last_modified")
        return PageState(
            etag=etag if isinstance(etag, str) else None,
            last_modified=last_modified if isinstance(last_modified, str) else None,
            signature=signature,
            requested_url=str(payload.get("requested_url") or ""),
            final_url=final_url,
            outcome_state=str(outcome_dict.get("state") or ""),
            outcome_count=int(outcome_dict.get("count") or 0),
            outcome_reason=(
                str(outcome_dict["reason"])
                if outcome_dict.get("reason") is not None
                else None
            ),
            parsed=parsed,
            html_path=html_path,
        )

    def save(
        self,
        slug: str,
        kind: str,
        *,
        requested_url: str,
        final_url: str,
        etag: str | None,
        last_modified: str | None,
        signature: str,
        fingerprint: str,
        outcome_state: str,
        outcome_count: int,
        outcome_reason: str | None,
        parsed: dict[str, Any],
    ) -> None:
        now = _now()
        _atomic_write(
            self.state_path(slug, kind),
            {
                "schema": PAGE_STATE_SCHEMA,
                "requested_url": requested_url,
                "final_url": final_url,
                "etag": etag,
                "last_modified": last_modified,
                "signature": signature,
                "fingerprint": fingerprint,
                "fetched_at": now,
                "verified_at": now,
                "outcome": {
                    "state": outcome_state,
                    "count": outcome_count,
                    "reason": outcome_reason,
                },
                "parsed": parsed,
            },
        )

    def mark_verified(
        self,
        slug: str,
        kind: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        fingerprint: str | None = None,
        outcome_state: str | None = None,
        outcome_count: int | None = None,
        outcome_reason: str | None = None,
        parsed: dict[str, Any] | None = None,
    ) -> None:
        """Record that the archived page was verified still current.

        Validators can move even when content does not (a CDN re-render hands
        out a fresh ``Last-Modified`` over identical bytes), so any newly
        served validator replaces the stored one.  When the caller re-parsed
        the archived bytes under a new fingerprint, the fresh parse and its
        outcome replace the stale ones.
        """
        path = self.state_path(slug, kind)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if etag is not None:
            payload["etag"] = etag
        if last_modified is not None:
            payload["last_modified"] = last_modified
        if fingerprint is not None and parsed is not None:
            payload["fingerprint"] = fingerprint
            payload["parsed"] = parsed
            payload["outcome"] = {
                "state": outcome_state,
                "count": outcome_count,
                "reason": outcome_reason,
            }
        payload["verified_at"] = _now()
        _atomic_write(path, payload)

    def invalidate(self, slug: str, kind: str) -> None:
        """Forget a page whose archive is about to stop matching its sidecar.

        A refused page (a season trap, a wrong-season redirect) is still
        archived for offline inspection, overwriting the last good bytes; a
        sidecar describing the previous page would then lie about what sits
        beside it, so it is removed and the next run fetches in full.
        """
        try:
            self.state_path(slug, kind).unlink()
        except OSError:
            pass
