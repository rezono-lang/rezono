import json

import pytest

from case_support import ROOT, exact, reference


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Derive endpoint_address_bounds(endpoint, network, address, first, last) in rules/address.dl from the derived "
    "cluster_endpoint_network (test_cluster_worker_network is green). Declare NodeAddressRange (network, first, "
    "last) and EndpointAddress (endpoint, address) in schema/address.yaml with plain text network and endpoint "
    "slots, and copy the ranges and addresses of firewall-inputs.json into facts/address.yaml; that fragment "
    "is self-contained, so expected/violations/address.json pins zero standalone violations. "
    "Read decisions/platform-derivation-acceptance.md."))
def test_address_ownership():
    inputs = json.loads((ROOT / "firewall-inputs.json").read_text())
    networks = dict(reference()["cluster_endpoint_network"])
    expected = {(endpoint, network, inputs["endpoint_addresses"][endpoint], *inputs["node_ranges"][network])
                for endpoint, network in networks.items()}
    assert all(lo <= addr <= hi for _, _, addr, lo, hi in expected)
    exact("endpoint_address_bounds", expected)
