"""The default listening transport of Keycloak, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/keycloak/keycloak/26.0.0/docs/guides/server/enabletls.adoc
SHA-256 of the complete response: 1163bd494afd2dced3c4e70e01106094ab8dc370962706ba2ec489943f81e248. The TLS guide states the HTTPS listening port; HTTPS runs over TCP.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("keycloak", "26.0.0", "TCP", 8443,
             "https://raw.githubusercontent.com/keycloak/keycloak/26.0.0/docs/guides/server/enabletls.adoc",
             "1163bd494afd2dced3c4e70e01106094ab8dc370962706ba2ec489943f81e248")]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Add facts/keycloak_transport.yaml with one vendor_default_transport row id keycloak-26.0.0-transport and facts/keycloak_transport_source.yaml "
    "with one vendor_default_transport_source row id keycloak-26.0.0-transport-source, both holding the expected values. "
    "Give the source file a sidecar facts/keycloak_transport_source.sources.yaml whose default is a tool source named "
    "'Vendor transport inspection' with the revision, position, url and fragment_sha256 this test states. "
    "Write only those three files. Read decisions/platform-vendor-transport-evidence.md."))
def test_keycloak_transport():
    check_vendor_transport("keycloak_transport", EXPECTED, revision="26.0.0", line=51,
                           fragment_sha256="581ee2b53cc3cdf69c6b2b7fb6c81016a252b274ee9ead37ba83497400e75867")
