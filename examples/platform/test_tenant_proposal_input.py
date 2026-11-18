import pytest

from tenant_proposal_case import load, proposal, query, quota, write


def test_trusted_tenant_proposal_inputs(tmp_path):
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    model["reviewGrants"] = [["reviewer-one", "approve-connection"]]
    model["landedDeliveries"] = [{"request": "elm/ledger", "revision": "de" * 20, "cores": 6,
                                   "memoryGiB": 12, "storageGiB": 70}]
    model["readableQuotas"] = [quota("elm", 4), quota("reed", 6)]
    write(catalog, model)
    tables = query(teams, catalog, "inputs")
    assert ["elm/ledger", "de" * 20] in tables.get("tenant_landed_delivery__revision", [])
    assert ["elm/ledger", 6] in tables.get("tenant_landed_delivery__cores", [])
    assert ["elm-cpu", 4] in tables.get("tenant_quota__amount", [])
    assert ["elm-cpu", "elm"] in tables.get("tenant_quota__owner", [])
    assert ["reviewer-one", "approve-connection"] in tables.get("tenant_reviewer__action", [])
    model["readableQuotas"][0]["amount"] += 2
    model["reviewGrants"] = []
    write(catalog, model)
    updated = query(teams, catalog, "inputs")
    assert ["elm-cpu", 6] in updated.get("tenant_quota__amount", [])
    assert ["elm-cpu", 4] not in updated.get("tenant_quota__amount", [])
    assert not updated.get("tenant_reviewer__action", [])
