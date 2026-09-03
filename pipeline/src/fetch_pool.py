"""Polite parallelism primitives: fan out across hosts, never against one.

The ratified politeness contract for multi-conference scale is that
parallelism happens ACROSS hosts — each programme's site is one host, and no
host ever sees more than one Touchline request in flight, with polite
spacing between consecutive requests to the same host.  Sequential
execution used to be the only thing enforcing that contract; these
primitives make it explicit, so a worker pool cannot violate it however the
scheduler interleaves the work.

``HostGate`` is the contract itself: a per-host lock (the cap of one
in-flight request) plus a minimum interval between consecutive requests to
the same host (the spacing — 0.2s, the interval the sequential match loop
always kept).  ``GatedSession`` threads the gate through ``requests`` at
the ``request`` level, so every fetch — retries and redirects resolved
inside the call included — happens while holding its host's slot.

Pacing is per host, not per programme, and the gate is the one object every
worker's session shares within a collect run, so two programmes on the same
host cannot defeat it.  Some hosts (PrestoSports sites behind CloudFront,
measured 2026-09-02 on tampaspartans.com and 2026-09-03 on five more) answer
HTTP 202 with an empty body once a client sends a burst: a WAF challenge, not
the page.  The gate never answers or bypasses a challenge.  It slows down
instead: a host that has ever answered 202 is *paced* (a longer interval
between its requests), a 202 is retried after growing waits, and a host that
still challenges after those enters a *cool-down* during which its requests
are refused at once — with a named reason — rather than spent.  Which hosts
challenge is learned from observed 202s; a host can also be presumed paced
up front (the board collector presumes every PrestoSports host, and
``TOUCHLINE_PACED_HOSTS`` names more), but no host list is the mechanism.

Sessions are never shared between threads (``requests`` makes no
thread-safety promise); the gate is the one object every worker's session
shares, and it is safe by construction.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

#: The historical politeness interval: the sequential collector never sent a
#: host two requests closer together than this.
DEFAULT_HOST_SPACING = 0.2
#: The interval for a host that challenges: five seconds keeps a season unit
#: (schedule, roster, stats and up to twenty box pages) well under the burst
#: rate that earned the 202s, and costs a paced host about two minutes.
DEFAULT_PACED_SPACING = 5.0
#: Waits before each retry of a challenged request: a 202 is retried after
#: 30s, then after a further 90s.  Two retries, growing gaps.
DEFAULT_CHALLENGE_BACKOFF: tuple[float, ...] = (30.0, 90.0)
#: How long a host that kept challenging through the backoff is left alone.
#: Operators measured 12-minute gaps between season units letting every page
#: land; ten minutes is the cool-down, and the collector re-tries what the
#: host refused once after it.
DEFAULT_HOST_COOLDOWN = 600.0

#: The phrase every challenge-shaped reason carries, so a coverage cell or a
#: gap line can be recognised as "the host challenged" without a status code.
CHALLENGE_MARKER = "served a challenge"
COOLDOWN_MARKER = "cooling down after HTTP 202"


def host_of(url: str) -> str:
    """The politeness unit — one site, however many pages we read from it."""
    return urlparse(str(url)).netloc.lower()


def is_challenge(response: requests.Response) -> bool:
    """A 2xx that is not the page: HTTP 202, or any 2xx with nothing in it."""
    status = getattr(response, "status_code", None)
    if not isinstance(status, int) or not 200 <= status < 300:
        return False
    if status != 200:
        return True
    return not (getattr(response, "text", "") or "").strip()


def is_challenge_reason(reason: object) -> bool:
    """Whether a recorded gap reason names a challenge or a cool-down refusal."""
    text = str(reason or "")
    return CHALLENGE_MARKER in text or COOLDOWN_MARKER in text


class HostCoolingDown(requests.RequestException):
    """Refused without a request: the host is cooling down after challenges.

    A ``RequestException`` so every fetch seam files it the way it files any
    failed fetch — as a named gap carrying this message — with no bypass.
    """

    def __init__(self, host: str, remaining: float) -> None:
        self.host = host
        self.remaining = remaining
        super().__init__(
            f"host {host} is {COOLDOWN_MARKER} challenges "
            f"({remaining:.0f}s of cool-down remain)"
        )


@dataclass(frozen=True)
class PacingPolicy:
    """The knobs: how far apart, how long to back off, how long to cool down.

    Everything has a sensible default; ``from_env`` reads the operator's
    overrides.  ``paced_hosts`` is the optional up-front knob — hosts
    presumed to challenge before any 202 is seen — and never the only
    mechanism: observation always adds to it.
    """

    spacing: float = DEFAULT_HOST_SPACING
    paced_spacing: float = DEFAULT_PACED_SPACING
    backoff: tuple[float, ...] = DEFAULT_CHALLENGE_BACKOFF
    cooldown: float = DEFAULT_HOST_COOLDOWN
    paced_hosts: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, environ: Callable[[str], str | None] = os.environ.get):
        def seconds(name: str, default: float) -> float:
            raw = environ(name)
            if raw is None or not raw.strip():
                return default
            return max(0.0, float(raw))

        raw_backoff = environ("TOUCHLINE_CHALLENGE_BACKOFF")
        backoff = (
            tuple(
                max(0.0, float(part)) for part in raw_backoff.split(",") if part.strip()
            )
            if raw_backoff and raw_backoff.strip()
            else DEFAULT_CHALLENGE_BACKOFF
        )
        raw_hosts = environ("TOUCHLINE_PACED_HOSTS") or ""
        return cls(
            spacing=seconds("TOUCHLINE_HOST_SPACING", DEFAULT_HOST_SPACING),
            paced_spacing=seconds("TOUCHLINE_PACED_SPACING", DEFAULT_PACED_SPACING),
            backoff=backoff,
            cooldown=seconds("TOUCHLINE_HOST_COOLDOWN", DEFAULT_HOST_COOLDOWN),
            paced_hosts=frozenset(
                part.strip().lower() for part in raw_hosts.split(",") if part.strip()
            ),
        )


def _log_to_stdout(message: str) -> None:
    print(message, file=sys.stdout, flush=True)


class HostGate:
    """At most one in-flight request per host, politely spaced and paced.

    Thread-safe.  Locks are minted per host on first use, so the gate needs
    no knowledge of the fleet up front and never hardcodes a host list.
    Hosts learn their pace: ``observe`` marks a host paced after its first
    challenge (and once the backoff is exhausted, cooling down), and every
    later slot for that host waits the paced interval instead of the polite
    one.  Every wait longer than the polite spacing is logged so the run log
    shows where the time went.
    """

    def __init__(
        self,
        spacing: float | None = None,
        *,
        policy: PacingPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = _log_to_stdout,
    ) -> None:
        policy = policy if policy is not None else PacingPolicy()
        if spacing is not None:
            policy = PacingPolicy(
                spacing=spacing,
                paced_spacing=max(spacing, policy.paced_spacing),
                backoff=policy.backoff,
                cooldown=policy.cooldown,
                paced_hosts=policy.paced_hosts,
            )
        self.policy = policy
        self._clock = clock
        self._sleep = sleep
        self._log = log
        self._registry = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._paced: set[str] = set(policy.paced_hosts)
        self._challenged: set[str] = set()
        self._cooling: dict[str, float] = {}

    # -- what the gate knows about the fleet -----------------------------

    def presume_paced(self, host: str) -> None:
        """Pace a host before any 202 is seen (a platform known to challenge)."""
        with self._registry:
            self._paced.add(host.lower())

    def is_paced(self, host: str) -> bool:
        with self._registry:
            return host.lower() in self._paced

    def challenged_hosts(self) -> frozenset[str]:
        """Hosts observed answering a challenge during this run."""
        with self._registry:
            return frozenset(self._challenged)

    def cooldown_remaining(self, host: str) -> float:
        """Seconds until the host may be asked again; 0 when it may be now."""
        with self._registry:
            until = self._cooling.get(host.lower())
        return max(0.0, until - self._clock()) if until is not None else 0.0

    def longest_cooldown_remaining(self) -> float:
        with self._registry:
            hosts = list(self._cooling)
        return max((self.cooldown_remaining(host) for host in hosts), default=0.0)

    def wait_out_cooldowns(self) -> float:
        """Sleep until every cooling host may be asked again; returns the wait.

        The main thread calls this before the one retry a challenged page
        gets; the wait is logged so the run log shows the pause.
        """
        wait = self.longest_cooldown_remaining()
        if wait > 0:
            self._log(
                f"pacing: waiting {wait:.0f}s for the cool-down to end before "
                f"retrying what was challenged"
            )
            self._sleep(wait)
        return wait

    def observe_challenge(self, host: str) -> None:
        """Learn that a host challenges: it is paced from now on."""
        host = host.lower()
        with self._registry:
            fresh = host not in self._paced
            self._paced.add(host)
            self._challenged.add(host)
        if fresh:
            self._log(
                f"pacing: {host} answered HTTP 202 (challenge); its requests are "
                f"now {self.policy.paced_spacing:g}s apart"
            )

    def begin_cooldown(self, host: str) -> None:
        host = host.lower()
        with self._registry:
            self._cooling[host] = self._clock() + self.policy.cooldown
        self._log(
            f"pacing: {host} still challenging after "
            f"{len(self.policy.backoff)} retries; cooling down "
            f"{self.policy.cooldown:g}s before it is asked again"
        )

    def _spacing_for(self, host: str) -> float:
        with self._registry:
            paced = host in self._paced
        return self.policy.paced_spacing if paced else self.policy.spacing

    # -- the slot ---------------------------------------------------------

    @contextmanager
    def slot(self, host: str) -> Iterator[None]:
        """Hold the host's single slot, spaced politely after the last request.

        Raises ``HostCoolingDown`` (without waiting) while the host cools.
        """
        host = host.lower()
        with self._lock_for(host):
            remaining = self.cooldown_remaining(host)
            if remaining > 0:
                raise HostCoolingDown(host, remaining)
            last = self._last.get(host)
            if last is not None:
                wait = self._spacing_for(host) - (self._clock() - last)
                if wait > 0:
                    if wait > self.policy.spacing:
                        self._log(f"pacing: waiting {wait:.1f}s before asking {host}")
                    self._sleep(wait)
            try:
                yield
            finally:
                self._last[host] = self._clock()

    def _lock_for(self, host: str) -> threading.Lock:
        with self._registry:
            lock = self._locks.get(host)
            if lock is None:
                lock = self._locks[host] = threading.Lock()
            return lock

    def backoff_wait(self, host: str, attempt: int) -> bool:
        """Wait before retry ``attempt`` (0-based) of a challenged request.

        Returns False when the backoff is exhausted — the host then enters
        its cool-down and the caller stops retrying.
        """
        if attempt >= len(self.policy.backoff):
            self.begin_cooldown(host)
            return False
        wait = self.policy.backoff[attempt]
        self._log(
            f"pacing: {host} answered HTTP 202 (challenge); retrying in {wait:g}s "
            f"(retry {attempt + 1} of {len(self.policy.backoff)})"
        )
        self._sleep(wait)
        return True


class GatedSession(requests.Session):
    """A session whose every request holds its host's gate slot.

    Gating at ``request`` level rather than per ``get`` covers redirects
    resolved inside the call: the slot is held for the whole exchange, so a
    redirect chain never interleaves with another worker's request to the
    same origin host.  (A cross-host redirect rides the origin's slot —
    rare, and the conservative direction: it can only over-serialize a
    host, never under-serialize one.)

    A challenge (HTTP 202, or an empty 2xx) is retried inside the slot after
    the gate's growing waits; once the backoff is exhausted the host cools
    down and the last challenged response is returned as it was, so the
    fetch seam's body check names it honestly.  Nothing is bypassed.
    """

    def __init__(self, gate: HostGate) -> None:
        super().__init__()
        self._gate = gate

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        host = host_of(url)
        with self._gate.slot(host):
            attempt = 0
            while True:
                response = super().request(method, url, *args, **kwargs)
                if not is_challenge(response):
                    return response
                self._gate.observe_challenge(host)
                if not self._gate.backoff_wait(host, attempt):
                    return response
                attempt += 1
