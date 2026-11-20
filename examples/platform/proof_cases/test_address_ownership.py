import json

import pytest

from case_support import ROOT, exact, reference


def test_address_ownership():
    inputs = json.loads((ROOT / "firewall-inputs.json").read_text())
    networks = dict(reference()["cluster_endpoint_network"])
    expected = {(endpoint, network, inputs["endpoint_addresses"][endpoint], *inputs["node_ranges"][network])
                for endpoint, network in networks.items()}
    assert all(lo <= addr <= hi for _, _, addr, lo, hi in expected)
    exact("endpoint_address_bounds", expected)
