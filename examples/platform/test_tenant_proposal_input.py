import pytest

from tenant_proposal_case import load, proposal, query, quota, write


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Depends on test_request_json_enters_compiler_base_tables. Extend request_preview.py and schema/tenant_proposal_input.yaml for catalog dimensions, capacity, zones, provisions, authority and readable quota records. Read decisions/platform-tenant-proposal-relations.md.")
def test_trusted_tenant_proposal_inputs(tmp_path):
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    model["reviewGrants"] = [["reviewer-one", "approve-connection"]]
    model["readableQuotas"] = [quota("elm", 4), quota("reed", 6)]
    write(catalog, model)
    tables = query(teams, catalog, "inputs")
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
