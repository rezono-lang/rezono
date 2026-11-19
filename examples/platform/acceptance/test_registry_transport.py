"""The default listening transport of the Distribution registry, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/distribution/distribution/v3.0.0/docs/content/about/configuration.md
SHA-256 of the complete response: 195d82641e9d305a0208ce7dd51ec2203d110e512c43f2b065cfe0fcd30c4ff5. The configuration page states the default listening port of the registry's HTTP API, which runs over TCP.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("registry", "3.0.0", "TCP", 5000,
             "https://raw.githubusercontent.com/distribution/distribution/v3.0.0/docs/content/about/configuration.md",
             "195d82641e9d305a0208ce7dd51ec2203d110e512c43f2b065cfe0fcd30c4ff5")]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Add facts/registry_transport_source.yaml with one vendor_default_transport_source row id registry-3.0.0-transport-source "
    "holding the expected values. "
    "Give the source file a sidecar facts/registry_transport_source.sources.yaml whose default is a tool source named "
    "'Vendor transport inspection' with the revision, position, url and fragment_sha256 this test states. "
    "Write only those two files. Read decisions/platform-vendor-transport-evidence.md."))
def test_registry_transport():
    check_vendor_transport("registry_transport", EXPECTED, revision="v3.0.0", line=907,
                           fragment_sha256="d5ba233f3082ac84cad47485eca5e62cd025f8ff0dfc54e322599e11f507a939")
