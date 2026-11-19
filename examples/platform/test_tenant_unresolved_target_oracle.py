"""The independent tenant calculation and the pack rule agree on a target that resolves to no delivery."""

import pytest

from tenant_oracle import calculate, load_requests
from tenant_proposal_case import load, proposal, query, write


@pytest.mark.parametrize("target, zone", [
    ("unlisted-database", "stable"),
    ("unlisted-database", "sandbox"),
    ("elm-1/no-such-component", "shared"),
    ("elm-9/managed-database", "stable"),
    ("partner", "external"),
])
def test_oracle_and_rule_agree_on_a_target_without_a_delivery(tmp_path, target, zone):
    # The matrix would admit each of these on 5432, so only the owner resolution can refuse them.
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    model["zoneMatrix"] += [["sandbox", "stable", 5432], ["sandbox", "sandbox", 5432],
                            ["sandbox", "shared", 5432], ["sandbox", "external", 5432]]
    write(catalog, model)
    path = next(teams.glob("reed/*/request.json"))
    request = load(path)
    request["connections"] = [{"targetZone": zone, "target": target, "port": 5432}]
    write(path, request)

    oracle = calculate(load(catalog), load_requests(teams))["connections"]
    rule = query(teams, catalog, "relation", "tenant_connection_review")
    assert rule == oracle
    reed, = [row[4:] for row in oracle if row[:4] == ["reed", "reed-1", target, 5432]]
    # Written from decisions/platform-tenants.md, not from either calculation.
    refused = zone in ("stable", "sandbox") or target.startswith("elm-")
    assert reed == (["denied", "unresolved-owner"] if refused else ["standard", "matrix"])
