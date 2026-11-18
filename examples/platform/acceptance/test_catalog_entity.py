import pytest

from query_fixture import portal_template


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Render each normalized tenant catalog row into a Backstage Component descriptor. Read decisions/platform-query-results.md. Write examples/platform/portal/catalog_entity.py.")
def test_catalog_entity():
    render = portal_template("catalog_entity").render
    for tenant, service, profile in (("elm", "ledger", "production"), ("reed", "studio", "development"),
                                     ("fir", "reports", "staging")):
        assert render(tenant, service, profile) == {
            "apiVersion": "backstage.io/v1alpha1", "kind": "Component",
            "metadata": {"namespace": tenant, "name": service},
            "spec": {"type": "service", "lifecycle": profile, "owner": f"group:{tenant}/{tenant}"},
        }
