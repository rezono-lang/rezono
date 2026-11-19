import pytest

from tenant_proposal_case import load, proposal, query, quota, write


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="extra: Depends on test_trusted_tenant_proposal_inputs and the std-access role/read-grant binding. Implement tenant-visible delivery and quota evidence in rules/tenant_delivery_visibility.dl. Read decisions/platform-tenant-proposal-relations.md. Waits for test_file_delivery_numbers and tenant-scoped completeness for the numbering aggregate. A checked publication exposes both ordinals to the complete checker but withholds each ordinal from its tenant even when that tenant can read its own request.")
def test_real_proposal_delivery_and_quota_evidence_stay_with_owner(tmp_path):
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    model["readableQuotas"] = [quota("elm", 7), quota("reed", 5)]
    write(catalog, model)
    def parts():
        expected = []
        for path in sorted(teams.glob("*/*/request.json")):
            team, service = path.parent.parent.name, path.parent.name
            for item in load(path)["items"]:
                product = model["catalog"][item]
                expected += [[team, team + "-1", part, product["component"], f"{team}/{service}/{item}"]
                             for part in product["provisions"]]
        assert query(teams, catalog, "relation", "tenant_delivery_component_evidence") == sorted(expected)
    def quotas():
        return query(teams, catalog, "relation", "tenant_quota_evidence")
    parts()
    elm = [["elm", "elm/ledger/cluster", "elm-cpu", 4, 7],
           ["elm", "elm/ledger/database", "elm-cpu", 2, 7]]
    assert quotas() == elm + [["reed", "reed/studio/cluster", "reed-cpu", 2, 5]]
    model["readableQuotas"][1]["amount"] = 17
    write(catalog, model)
    assert quotas() == elm + [["reed", "reed/studio/cluster", "reed-cpu", 2, 17]]
    model["readableQuotas"] = [model["readableQuotas"][1]]
    write(catalog, model)
    assert quotas() == [["reed", "reed/studio/cluster", "reed-cpu", 2, 17]]
    request = teams / "elm/ledger/request.json"
    data = load(request)
    del data["items"]["database"]
    write(request, data)
    parts()
