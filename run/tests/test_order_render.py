import pytest

from offline_cases import implementation, FIXTURE, PLAN_HASH


def test_order_render():
    render = implementation("order_render.py", "render")
    raw = (FIXTURE / "plan.json").read_bytes()
    expected = [{"sku": "vbm-4c-32gb", "quantity": 2, "plan_hash": PLAN_HASH},
                {"sku": "vbm-8c-132gb", "quantity": 1, "plan_hash": PLAN_HASH}]
    assert render(raw, PLAN_HASH) == {"idempotency_key": PLAN_HASH, "items": expected}
    with pytest.raises(ValueError):
        render(raw + b" ", PLAN_HASH)
