"""The default listening transport of the Kubernetes API server, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/reference/networking/ports-and-protocols.md
SHA-256 of the complete response: ec090906b455a9e638b8ae56d1a204539bafdc1ed2326a1e454bf7754a4659e3. The 1.32 ports page lists the API server's protocol and port in one table row.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("kube-control", "1.32", "TCP", 6443,
             "https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/reference/networking/ports-and-protocols.md",
             "ec090906b455a9e638b8ae56d1a204539bafdc1ed2326a1e454bf7754a4659e3")]


def test_kube_control_transport():
    check_vendor_transport("kube_control_transport", EXPECTED, revision="release-1.32", line=16,
                           fragment_sha256="74bd31966edb891128c4e7cd6dbcc6799d1250c8eb919a18042e1876e78607f2")
