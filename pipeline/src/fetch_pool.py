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

Sessions are never shared between threads (``requests`` makes no
thread-safety promise); the gate is the one object every worker's session
shares, and it is safe by construction.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

import requests

#: The historical politeness interval: the sequential collector never sent a
#: host two requests closer together than this.
DEFAULT_HOST_SPACING = 0.2


def host_of(url: str) -> str:
    """The politeness unit — one site, however many pages we read from it."""
    return urlparse(str(url)).netloc.lower()


class HostGate:
    """At most one in-flight request per host, politely spaced.

    Thread-safe.  Locks are minted per host on first use, so the gate needs
    no knowledge of the fleet up front and never hardcodes a host list.
    """

    def __init__(
        self,
        spacing: float = DEFAULT_HOST_SPACING,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._spacing = spacing
        self._clock = clock
        self._sleep = sleep
        self._registry = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}

    def _lock_for(self, host: str) -> threading.Lock:
        with self._registry:
            lock = self._locks.get(host)
            if lock is None:
                lock = self._locks[host] = threading.Lock()
            return lock

    @contextmanager
    def slot(self, host: str) -> Iterator[None]:
        """Hold the host's single slot, spaced politely after the last request."""
        with self._lock_for(host):
            last = self._last.get(host)
            if last is not None:
                wait = self._spacing - (self._clock() - last)
                if wait > 0:
                    self._sleep(wait)
            try:
                yield
            finally:
                self._last[host] = self._clock()


class GatedSession(requests.Session):
    """A session whose every request holds its host's gate slot.

    Gating at ``request`` level rather than per ``get`` covers redirects
    resolved inside the call: the slot is held for the whole exchange, so a
    redirect chain never interleaves with another worker's request to the
    same origin host.  (A cross-host redirect rides the origin's slot —
    rare, and the conservative direction: it can only over-serialize a
    host, never under-serialize one.)
    """

    def __init__(self, gate: HostGate) -> None:
        super().__init__()
        self._gate = gate

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        with self._gate.slot(host_of(url)):
            return super().request(method, url, *args, **kwargs)
