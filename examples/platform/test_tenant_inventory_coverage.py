"""Evidence for occupied capacity in the tenant reference calculation."""

import pytest

from tenant_oracle import calculate, load_requests
from tenant_proposal_case import ROOT, load

DRAFT = ["reed", "reed-2"]
LIMITS = [("guest-host", "cores", 9), ("guest-host", "memoryGiB", 18),
          ("storage-pool", "storageGiB", 100)]
LANDED = {"request": "elm/previous", "revision": "ab" * 20, "cores": 9,
          "memoryGiB": 18, "storageGiB": 100}


def evaluate(model):
    requests = load_requests(ROOT / "teams")
    draft = load(ROOT / "tenant-scenarios/third-request.json")
    return calculate(model, [*requests, draft])


def test_example_catalog_records_its_empty_inventory():
    model = load(ROOT / "tenant-catalog.json")
    assert model["landedDeliveries"] == []
    result = evaluate(model)
    assert result["capacity"] == [[pool, dimension, 0, limit] for pool, dimension, limit in LIMITS]
    assert [*DRAFT, "standard"] in result["proposal"]


def test_missing_inventory_keeps_capacity_and_admission_unknown():
    model = load(ROOT / "tenant-catalog.json")
    model.pop("landedDeliveries", None)
    result = evaluate(model)
    assert result["capacity"] == [[pool, dimension, None, limit] for pool, dimension, limit in LIMITS]
    assert [*DRAFT, "unknown"] in result["proposal"]
    assert ["reed", "reed-1", "denied"] in result["proposal"]
    assert ["reed", 4990, "EUR-cent"] in result["monthlyCost"]


def test_pinned_occupancy_blocks_the_same_proposal():
    model = load(ROOT / "tenant-catalog.json")
    model["landedDeliveries"] = [LANDED]
    result = evaluate(model)
    assert result["capacity"] == [[pool, dimension, limit, limit] for pool, dimension, limit in LIMITS]
    assert [*DRAFT, "denied"] in result["proposal"]
    assert ["storage-pool", "storageGiB", 30 + 40] in result["shortages"]


@pytest.mark.parametrize("inventory", [None, {}, ""])
def test_invalid_inventory_cannot_prove_zero_usage(inventory):
    model = load(ROOT / "tenant-catalog.json")
    model["landedDeliveries"] = inventory
    with pytest.raises(ValueError, match="landedDeliveries must be a list"):
        evaluate(model)
