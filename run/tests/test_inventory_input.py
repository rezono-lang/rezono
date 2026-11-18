import pytest

from input_contract_cases import DIGEST, verify


@pytest.mark.xfail(strict=True, reason="Implement run/schemas/inventory-page.json from decisions/run-external-evidence.md.")
def test_inventory_page_shape():
    resource = {"id": "disk-a", "plan_hash": DIGEST}
    base = dict(sweep_id="s", page_id="first", next_page_id=None, resources=[resource])
    bad = [
        dict(sweep_id=""), dict(page_id=""), dict(next_page_id=""), dict(extra=1),
        dict(resources=[resource, resource]), dict(resources=[{"id": "disk-a"}]),
        dict(resources=[resource | {"extra": 1}]), dict(resources=[resource | {"id": ""}]),
        dict(resources=[resource | {"plan_hash": "x" * 64}]),
        dict(resources=[resource | {"plan_hash": DIGEST + "\n"}]),
    ]
    verify("inventory-page.json", [base, base | dict(next_page_id="more", resources=[]),
           base | dict(resources=[resource | {"plan_hash": None}])],
           [base | patch for patch in bad])
