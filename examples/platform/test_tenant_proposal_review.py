import pytest

from tenant_proposal_case import load, proposal, query, write


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Depends on test_trusted_tenant_proposal_inputs and test_file_delivery_numbers. The platform compiler needs the shared tenant and delivery ordinal, with that identity bound to the legacy display key, before joining matrix eligibility, reciprocal requests and authorized reviewer decisions in rules/tenant_connection_review.dl. Read decisions/platform-tenant-proposal-relations.md.")
def test_real_proposal_requires_both_teams_and_authorized_decision(tmp_path):
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    target = "elm-1/managed-database"
    def decision():
        return query(teams, catalog, "relation", "tenant_connection_review")
    def reed(rows):
        return [row[4:] for row in rows if row[:4] == ["reed", "reed-1", target, 5432]]
    rows = decision()
    assert ["elm", "elm-1", "partner", 443, "review", "profile"] in rows
    assert reed(rows) == [["denied", "isolation"]]
    model["zoneMatrix"].append(["sandbox", "stable", 5432])
    approval = {"reviewer": "operator", "sourceDelivery": "reed-1", "target": target, "port": 5432}
    model["decisionsByReviewer"] = [approval]
    model["reviewGrants"] = [["operator", "approve-connection"]]
    write(catalog, model)
    assert reed(decision()) == [["denied", "isolation"]]
    elm = teams / "elm/ledger/request.json"
    request = load(elm)
    request["connections"].append({"peer": "reed", "targetZone": "sandbox",
                                   "target": "reed-1/guest-cluster", "port": 5432})
    write(elm, request)
    assert reed(decision()) == [["standard", "matrix"]]
    approval["port"] = 5433
    write(catalog, model)
    assert reed(decision()) == [["denied", "isolation"]]
    approval["port"] = 5432
    model["reviewGrants"] = [["someone-else", "approve-connection"]]
    write(catalog, model)
    assert reed(decision()) == [["denied", "isolation"]]
