"""Handwritten expectations must agree with packet matching on this finite fixture."""

from wire_fixtures import fixture


def test_network_fixture_witnesses():
    net = fixture("network")
    for case in net["cases"]:
        source = net["endpoints"][case["source"]]
        destination = net["endpoints"][case["destination"]]
        matches = [
            rule for rule in net["rules"]
            if rule["sourceFrom"] <= source["address"] <= rule["sourceTo"]
            and rule["destinationAddress"] == destination["address"]
            and rule["protocol"] == case["protocol"]
            and rule["fromPort"] <= case["port"] <= rule["toPort"]
        ]
        cross_zone = source["zone"] != destination["zone"]
        expected_router = ("allow" if matches else "deny") if cross_zone else "inapplicable"
        assert case["router"] == expected_router, case["id"]
    assert {c["id"] for c in net["cases"] if c["router"] == "allow" and c["service"] == "deny"} == {"overlap"}
