"""The default listening transport of the Kubernetes API server, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/reference/networking/ports-and-protocols.md
SHA-256 of the complete response: ec090906b455a9e638b8ae56d1a204539bafdc1ed2326a1e454bf7754a4659e3. The 1.32 ports page lists the API server's protocol and port in one table row.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("kube-control", "1.32", "TCP", 6443,
             "https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/reference/networking/ports-and-protocols.md",
             "ec090906b455a9e638b8ae56d1a204539bafdc1ed2326a1e454bf7754a4659e3")]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Add facts/kube_control_transport.yaml with one vendor_default_transport row id kube-control-1.32-transport and facts/kube_control_transport_source.yaml "
    "with one vendor_default_transport_source row id kube-control-1.32-transport-source, both holding the expected values. "
    "Give the source file a sidecar facts/kube_control_transport_source.sources.yaml whose default is a tool source named "
    "'Vendor transport inspection' with the revision, position, url and fragment_sha256 this test states. "
    "Write only those three files. Read decisions/platform-vendor-transport-evidence.md."))
def test_kube_control_transport():
    check_vendor_transport("kube_control_transport", EXPECTED, revision="release-1.32", line=16,
                           fragment_sha256="74bd31966edb891128c4e7cd6dbcc6799d1250c8eb919a18042e1876e78607f2")
