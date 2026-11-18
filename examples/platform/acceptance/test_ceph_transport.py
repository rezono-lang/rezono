"""The default monitor transports of Ceph, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/ceph/ceph/v19.2.0/doc/rados/configuration/network-config-ref.rst
SHA-256 of the complete response: 371d11209372fa02869d578a29c1c17aa897e00764c1e80d3bcc5e372abac943. The network
reference states both monitor ports as defaults; its firewall example for the monitors opens them as TCP.
"""

import pytest

from transport_support import check_vendor_transport

URL = "https://raw.githubusercontent.com/ceph/ceph/v19.2.0/doc/rados/configuration/network-config-ref.rst"
SHA256 = "371d11209372fa02869d578a29c1c17aa897e00764c1e80d3bcc5e372abac943"
EXPECTED = [("ceph", "19.2.0", "TCP", port, URL, SHA256) for port in (3300, 6789)]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Add facts/ceph_transport.yaml with two vendor_default_transport rows, ids ceph-19.2.0-transport-3300 and "
    "ceph-19.2.0-transport-6789, and facts/ceph_transport_source.yaml with two vendor_default_transport_source rows, "
    "ids ceph-19.2.0-transport-3300-source and ceph-19.2.0-transport-6789-source, holding the expected values. "
    "Give the source file a sidecar facts/ceph_transport_source.sources.yaml whose default is a tool source named "
    "'Vendor transport inspection' with the revision, position, url and fragment_sha256 this test states. "
    "Write only those three files. Read decisions/platform-vendor-transport-evidence.md."))
def test_ceph_transport():
    check_vendor_transport("ceph_transport", EXPECTED, revision="v19.2.0", line=80,
                           fragment_sha256="21121ed1c9220a71af96f62cee89006427725b5eab88327c34dab7b47ef1f188")
