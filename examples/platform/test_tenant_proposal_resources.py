import pytest

from tenant_oracle import calculate, load_requests
from tenant_proposal_case import ROOT, load, proposal, query, write


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Depends on test_trusted_tenant_proposal_inputs. Implement tenant_resource_capacity and tenant_resource_shortage with pack aggregation under rules/tenant_resources.dl and its own calc/tenant_resources module. Read decisions/platform-tenant-proposal-relations.md.")
def test_real_proposal_capacity_and_three_resource_shortages(tmp_path):
    teams, catalog = proposal(tmp_path)
    def check():
        expected = calculate(load(catalog), load_requests(teams))
        for relation, key in (("tenant_resource_capacity", "capacity"), ("tenant_resource_shortage", "shortages")):
            assert query(teams, catalog, "relation", relation) == expected[key]
        return expected["shortages"]
    assert check() == []
    extra = load(ROOT / "tenant-scenarios/third-request.json")
    team, service = extra.pop("team"), extra.pop("service")
    write(teams / team / service / "request.json", extra)
    assert check() == [["guest-host", "cores", 1], ["guest-host", "memoryGiB", 2], ["storage-pool", "storageGiB", 10]]
    model = load(catalog)
    model["capacity"]["guest-host"]["cores"] += 1
    write(catalog, model)
    assert check() == [["guest-host", "memoryGiB", 2], ["storage-pool", "storageGiB", 10]]
