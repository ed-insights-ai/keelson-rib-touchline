"""Verify TLS like the browsers these sites target: OS trust store + AIA chasing.

SideArm hosts such as dbupatriots.com serve an incomplete certificate chain
(missing intermediate). certifi cannot fetch the missing cert, so requests fails
with CERTIFICATE_VERIFY_FAILED; the OS verifier AIA-chases it exactly like the
browsers the sites are built for. Verification stays enabled.
"""

from __future__ import annotations

import ssl

import truststore
from requests.adapters import HTTPAdapter


class TruststoreHTTPAdapter(HTTPAdapter):
    """HTTPAdapter that verifies via the OS trust store instead of certifi alone."""

    def _ctx(self) -> ssl.SSLContext:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().proxy_manager_for(*args, **kwargs)
