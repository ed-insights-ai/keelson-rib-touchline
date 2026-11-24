"""robots.txt, refusals and the backfill profile (src/fetch_pool.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.fetch_pool import (
    BACKFILL_HOST_SPACING,
    HostGate,
    HostStopped,
    PacingPolicy,
    RobotsDisallowed,
)
from src.sidearm_live import user_agent


class _Time:
    def __init__(self) -> None:
        self.value = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.value += seconds


def _gate(**policy) -> tuple[HostGate, _Time, list[str]]:
    t = _Time()
    log: list[str] = []
    gate = HostGate(
        policy=PacingPolicy(**policy), clock=t.clock, sleep=t.sleep, log=log.append
    )
    return gate, t, log


def _robots(text: str, status: int = 200):
    calls: list[str] = []

    def fetch(url: str):
        calls.append(url)
        return SimpleNamespace(status_code=status, text=text)

    return fetch, calls


RULES = "User-agent: *\nDisallow: /private/\n\nUser-agent: Touchline\nDisallow: /api/\nCrawl-delay: 9\n"


def test_backfill_profile_spaces_hosts_enforces_robots_and_stops_on_refusal() -> None:
    policy = PacingPolicy.from_env({"TOUCHLINE_FETCH_PROFILE": "backfill"}.get)
    assert policy.spacing == BACKFILL_HOST_SPACING
    assert policy.robots == "enforce"
    assert policy.stop_on_refusal is True
    daily = PacingPolicy.from_env(lambda _name: None)
    assert (daily.spacing, daily.robots, daily.stop_on_refusal) == (0.2, "off", False)
    overridden = PacingPolicy.from_env(
        {
            "TOUCHLINE_FETCH_PROFILE": "backfill",
            "TOUCHLINE_ROBOTS": "report",
            "TOUCHLINE_STOP_ON_REFUSAL": "false",
            "TOUCHLINE_HOST_SPACING": "2",
        }.get
    )
    assert (overridden.spacing, overridden.robots, overridden.stop_on_refusal) == (
        2.0,
        "report",
        False,
    )


def test_an_unknown_profile_or_robots_mode_is_refused() -> None:
    with pytest.raises(ValueError):
        PacingPolicy.from_env({"TOUCHLINE_FETCH_PROFILE": "fast"}.get)
    with pytest.raises(ValueError):
        PacingPolicy.from_env({"TOUCHLINE_ROBOTS": "ignore"}.get)


def test_enforce_refuses_a_disallowed_url_and_reads_robots_once_per_host() -> None:
    gate, _t, _log = _gate(robots="enforce")
    fetch, calls = _robots(RULES)
    gate.robots_check("https://school.edu/sports/mens-soccer/schedule/2026", fetch)
    with pytest.raises(RobotsDisallowed, match="disallowed by robots.txt"):
        gate.robots_check("https://school.edu/api/v2/Schedule/1", fetch)
    # The Touchline group replaces the * group, so /private/ is ours to read.
    gate.robots_check("https://school.edu/private/x", fetch)
    assert calls == ["https://school.edu/robots.txt"]


def test_enforce_honours_crawl_delay_in_the_host_spacing() -> None:
    gate, t, _log = _gate(robots="enforce", spacing=0.2)
    fetch, _calls = _robots(RULES)
    gate.robots_check("https://school.edu/sports/x", fetch)
    with gate.slot("school.edu"):
        pass
    assert t.sleeps[-1] == pytest.approx(9.0)


def test_report_logs_a_disallow_without_refusing() -> None:
    gate, _t, log = _gate(robots="report")
    fetch, _calls = _robots(RULES)
    gate.robots_check("https://school.edu/api/v2/Schedule/1", fetch)
    assert any("disallows /api/v2/Schedule/1 (report only)" in line for line in log)


def test_missing_robots_means_no_rules_and_a_server_error_means_stay_out() -> None:
    gate, _t, _log = _gate(robots="enforce")
    missing, _ = _robots("", status=404)
    gate.robots_check("https://a.edu/anything", missing)
    broken, _ = _robots("", status=503)
    with pytest.raises(RobotsDisallowed, match="HTTP 503"):
        gate.robots_check("https://b.edu/anything", broken)


def test_off_never_reads_robots() -> None:
    gate, _t, _log = _gate(robots="off")
    fetch, calls = _robots(RULES)
    gate.robots_check("https://school.edu/api/x", fetch)
    assert calls == []


def test_a_refusal_stops_the_host_for_the_run_only_when_asked() -> None:
    gate, _t, log = _gate(stop_on_refusal=True)
    gate.observe_status("school.edu", 403)
    with pytest.raises(HostStopped, match="stopped after HTTP 403"):
        with gate.slot("school.edu"):
            pass
    with gate.slot("other.edu"):
        pass
    assert gate.stopped_hosts() == {"school.edu": 403}
    lenient, _t2, _log2 = _gate()
    lenient.observe_status("school.edu", 429)
    with lenient.slot("school.edu"):
        pass


def test_user_agent_names_a_contact_when_one_is_set() -> None:
    assert user_agent("") == "Mozilla/5.0 (Touchline educational/research collector)"
    assert user_agent("https://example.org/touchline") == (
        "Mozilla/5.0 (Touchline educational/research collector; +https://example.org/touchline)"
    )


def test_an_unknown_refusal_flag_fails_loudly() -> None:
    with pytest.raises(ValueError):
        PacingPolicy.from_env({"TOUCHLINE_STOP_ON_REFUSAL": "treu"}.get)
    off = PacingPolicy.from_env(
        {"TOUCHLINE_FETCH_PROFILE": "backfill", "TOUCHLINE_STOP_ON_REFUSAL": "off"}.get
    )
    assert off.stop_on_refusal is False


def test_a_refused_robots_txt_stops_the_host() -> None:
    gate, _t, _log = _gate(robots="enforce", stop_on_refusal=True)
    fetch, _calls = _robots("", status=403)
    gate.robots_check("https://a.example/sports/x", fetch)
    assert gate.stopped_hosts() == {"a.example": 403}
    with pytest.raises(HostStopped):
        with gate.slot("a.example"):
            pass


class _Hop:
    def __init__(self, url: str, status: int = 200, location: str = "") -> None:
        self.url = url
        self.status_code = status
        self.headers = {"location": location} if location else {}
        self.is_redirect = bool(location)
        self.text = ""
        self.content = b""


def test_each_redirect_hop_is_judged_by_robots(monkeypatch) -> None:
    import requests

    from src.fetch_pool import GatedSession

    gate, _t, _log = _gate(robots="enforce")
    gate._robots["a.example"] = None
    gate._robots["b.example"] = "robots.txt answered HTTP 503"
    asked: list[str] = []

    def send(self, method, url, *args, **kwargs):
        asked.append(url)
        assert kwargs.get("allow_redirects") is False
        if url.startswith("https://a.example"):
            return _Hop(url, 302, "https://b.example/page")
        return _Hop(url)

    monkeypatch.setattr(requests.Session, "request", send)
    session = GatedSession(gate)
    with pytest.raises(RobotsDisallowed):
        session.get("https://a.example/start")
    assert asked == ["https://a.example/start"]


def test_a_robots_redirect_is_asked_in_the_target_hosts_slot() -> None:
    gate, _t, _log = _gate(robots="enforce", stop_on_refusal=True)
    asked: list[str] = []

    def fetch(url: str):
        asked.append(url)
        if url.startswith("https://a.example"):
            return _Hop(url, 301, "https://b.example/robots.txt")
        return _Hop(url, 403)

    gate.robots_check("https://a.example/sports/x", fetch)
    assert asked == ["https://a.example/robots.txt", "https://b.example/robots.txt"]
    # The refusal is the target's, not the origin's.
    assert gate.stopped_hosts() == {"b.example": 403}
    # A robots.txt that redirects to a stopped host is not asked, and reads as
    # "could not say", which enforce treats as do not crawl.
    with pytest.raises(RobotsDisallowed):
        gate.robots_check(
            "https://c.example/x", lambda url: _Hop(url, 302, "https://b.example/r")
        )


def test_a_challenge_retry_waits_at_least_the_crawl_delay() -> None:
    gate, t, _log = _gate(robots="enforce", backoff=(1.0,))
    gate._delay["a.example"] = 9.0
    before = t.clock()
    assert gate.backoff_wait("a.example", 0)
    assert t.clock() - before >= 9.0


def test_robots_rules_read_wildcards_anchors_and_the_longest_match() -> None:
    from src.fetch_pool import RobotRules

    rules = RobotRules(
        "User-agent: *\nAllow: /\nDisallow: /sports/*/schedule/\nDisallow: /*.pdf$\n"
        "Allow: /sports/msoc/schedule/print/\n\nUser-agent: Other\nDisallow: /\n",
        "Touchline",
    )
    assert not rules.can_fetch("https://a.example/sports/msoc/schedule/2025")
    assert rules.can_fetch("https://a.example/sports/msoc/schedule/print/2025")
    assert not rules.can_fetch("https://a.example/files/x.pdf")
    assert rules.can_fetch("https://a.example/files/x.pdf?v=1")
    assert rules.can_fetch("https://a.example/sports/msoc/roster")
    named = RobotRules(
        "User-agent: *\nDisallow: /\n\nUser-agent: touchline\nDisallow: /api/\nCrawl-delay: 9\n",
        "Touchline",
    )
    assert named.can_fetch("https://a.example/sports/msoc")
    assert not named.can_fetch("https://a.example/api/x")
    assert named.crawl_delay == 9.0


def test_robots_check_enforces_a_wildcard_disallow() -> None:
    gate, _t, _log = _gate(robots="enforce")
    fetch, _calls = _robots("User-agent: *\nDisallow: /sports/*/schedule/\n")
    with pytest.raises(RobotsDisallowed):
        gate.robots_check("https://a.example/sports/msoc/schedule/2025", fetch)
    gate.robots_check("https://a.example/sports/msoc/roster/2025", fetch)


def test_a_refusing_session_never_retries_a_429() -> None:
    from src.fetch_pool import GatedSession
    from src.sidearm_live import build_session

    gate, _t, _log = _gate(stop_on_refusal=True)
    strict = (
        build_session(GatedSession(gate)).get_adapter("https://a.example").max_retries
    )
    assert not strict.is_retry("GET", 429, has_retry_after=True)
    assert strict.is_retry("GET", 503, has_retry_after=True)
    daily = (
        build_session(GatedSession(_gate()[0]))
        .get_adapter("https://a.example")
        .max_retries
    )
    assert daily.is_retry("GET", 429, has_retry_after=True)
