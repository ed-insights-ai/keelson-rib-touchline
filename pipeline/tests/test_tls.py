"""Tests for OS-trust-store TLS adapters."""

from __future__ import annotations

import os

import pytest
import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.sidearm_live import build_session
from src.tls import TruststoreHTTPAdapter

DBU_MENS_SOCCER_URL = "https://dbupatriots.com/sports/mens-soccer"


def _assert_truststore_adapter(session) -> None:
    assert isinstance(
        session.get_adapter("https://example.test"),
        TruststoreHTTPAdapter,
    )
    assert isinstance(
        session.get_adapter("http://example.test"),
        TruststoreHTTPAdapter,
    )


def test_session_builder_mounts_truststore_adapter() -> None:
    session = build_session()
    try:
        _assert_truststore_adapter(session)
    finally:
        session.close()


def test_adapter_injects_truststore_context_and_preserves_retries() -> None:
    retry = Retry(total=2)
    adapter = TruststoreHTTPAdapter(max_retries=retry)

    assert isinstance(adapter, HTTPAdapter)
    assert isinstance(
        adapter.poolmanager.connection_pool_kw["ssl_context"],
        truststore.SSLContext,
    )
    assert adapter.max_retries is retry


@pytest.mark.skipif(
    not os.environ.get("TOUCHLINE_LIVE_TLS"),
    reason="TOUCHLINE_LIVE_TLS is not set",
)
def test_dbu_live_tls_verification() -> None:
    session = build_session()
    try:
        response = session.get(DBU_MENS_SOCCER_URL, timeout=20)
        response.raise_for_status()
        assert response.status_code == 200
    finally:
        session.close()
