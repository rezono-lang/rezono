"""The default listening transport of Argo CD, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/argoproj/argo-cd/v3.0.0/docs/operator-manual/server-commands/argocd-server.md
SHA-256 of the complete response: 3f2c88ccfdaf6beed6c9f52600f05f0073b8f715b23d57600b3a44e8242ac385. The argocd-server reference states the default of its listening port; the server speaks HTTP and gRPC over TCP.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("argocd", "3.0.0", "TCP", 8080,
             "https://raw.githubusercontent.com/argoproj/argo-cd/v3.0.0/docs/operator-manual/server-commands/argocd-server.md",
             "3f2c88ccfdaf6beed6c9f52600f05f0073b8f715b23d57600b3a44e8242ac385")]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Add facts/argocd_transport_source.yaml with one vendor_default_transport_source row id argocd-3.0.0-transport-source "
    "holding the expected values. "
    "Give the source file a sidecar facts/argocd_transport_source.sources.yaml whose default is a tool source named "
    "'Vendor transport inspection' with the revision, position, url and fragment_sha256 this test states. "
    "Write only those two files. Read decisions/platform-vendor-transport-evidence.md."))
def test_argocd_transport():
    check_vendor_transport("argocd_transport", EXPECTED, revision="v3.0.0", line=74,
                           fragment_sha256="cac5ee8e4d65f9f2701e39a940db73aa8ba07100665780db00752324dc4969b9")
