"""The default listening transport of Keycloak, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/keycloak/keycloak/26.0.0/docs/guides/server/enabletls.adoc
SHA-256 of the complete response: 1163bd494afd2dced3c4e70e01106094ab8dc370962706ba2ec489943f81e248. The TLS guide states the HTTPS listening port; HTTPS runs over TCP.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("keycloak", "26.0.0", "TCP", 8443,
             "https://raw.githubusercontent.com/keycloak/keycloak/26.0.0/docs/guides/server/enabletls.adoc",
             "1163bd494afd2dced3c4e70e01106094ab8dc370962706ba2ec489943f81e248")]


def test_keycloak_transport():
    check_vendor_transport("keycloak_transport", EXPECTED, revision="26.0.0", line=51,
                           fragment_sha256="581ee2b53cc3cdf69c6b2b7fb6c81016a252b274ee9ead37ba83497400e75867")
