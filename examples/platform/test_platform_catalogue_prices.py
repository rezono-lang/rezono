"""Catalogue prices follow a pricing policy that a decision sets (decisions/platform-facts-not-conclusions.md,
section 9).

The expected prices are those tenant-catalog.json held at b77fd2a, which section 9 records as the transitional price
decision; the expected tenant costs are the independent rows of tenant-rows.json. Each price is also recomputed
here from the pricing parameters the preview reads, by the rounding rules section 9 defines.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from request_preview_case import copy_requests, preview

PLATFORM = Path(__file__).resolve().parent
PRICES_AT_B77FD2A = {"cluster/small": 2495, "cluster/medium": 4995, "database/medium": 2510}
DIMENSIONS = ("cores", "memory_gib", "storage_gib")


def _rounded(cents: int, rule: str) -> int:
    if rule == "none":
        return cents
    if rule == "up_to_95":
        return cents + (95 - cents % 100) % 100
    raise AssertionError(f"unknown rounding {rule!r}")


def _by_id(inputs: dict, table: str) -> dict:
    return {key: value for key, value in inputs.get(table, [])}


def _priced(inputs: dict, sizes: dict) -> dict:
    """Each offer's price from the pricing parameters among the preview's inputs, as section 9 defines it."""
    item, dimension, rate = (_by_id(inputs, f"pricing_rate__{slot}")
                             for slot in ("item", "dimension", "cents_per_unit"))
    rates = {(item[r], dimension[r]): rate[r] for r in rate}
    of, rule = _by_id(inputs, "pricing_rounding__item"), _by_id(inputs, "pricing_rounding__rule")
    rounding = {of[r]: rule[r] for r in rule}
    return {f"{name}/{size}": _rounded(sum(rates[(name, d)] * n for d, n in zip(DIMENSIONS, amounts, strict=True)),
                                       rounding[name])
            for (name, size), amounts in sizes.items()}


def _sizes(catalog: Path) -> dict:
    data = json.loads(catalog.read_text(encoding="utf-8"))
    return {(name, size): amounts
            for name, entry in data["catalog"].items() for size, amounts in entry["sizes"].items()}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/platform-facts-not-conclusions.md, section 9. Derive tenant_catalog_price(offer, cents) from the "
    "PricingRate rows (cents per core, per GiB of memory and per GiB of storage, per item) and the item's "
    "PricingRounding, both bound to the pricing Decision; tenant_monthly_cost reads it, the catalogue sizes hold "
    "cores, memory and storage only, and TenantCatalogOffer has no monthly_cents input. Waits for the owner's "
    "pricing decision and the planner's sources step of section 9."))
def test_catalogue_prices_follow_the_pricing_policy(tmp_path):
    costs = json.loads((PLATFORM / "tenant-rows.json").read_text(encoding="utf-8"))["requested"]["monthlyCost"]
    teams, catalog = copy_requests(tmp_path)
    sizes = _sizes(catalog)
    assert all(len(amounts) == len(DIMENSIONS) for amounts in sizes.values()), "a catalogue size still holds a price"

    inputs = preview(teams, catalog, "inputs")
    assert not inputs.get("tenant_catalog_offer__monthly_cents"), "the monthly price is still an input"
    decisions = {row[0] for row in inputs.get("decision", [])}
    bound = _by_id(inputs, "pricing_rate__decision") | _by_id(inputs, "pricing_rounding__decision")
    assert bound and set(bound.values()) <= decisions, "pricing parameters without a decision"

    prices = dict(map(tuple, preview(teams, catalog, "relation", "tenant_catalog_price")))
    assert prices == PRICES_AT_B77FD2A
    assert prices == _priced(inputs, sizes)
    assert preview(teams, catalog, "relation", "tenant_monthly_cost") == costs

    # The size decides through the policy: one more core in the small cluster is priced by the rates.
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["catalog"]["cluster"]["sizes"]["small"][0] += 1
    catalog.write_text(json.dumps(data), encoding="utf-8")
    inputs = preview(teams, catalog, "inputs")
    prices = dict(map(tuple, preview(teams, catalog, "relation", "tenant_catalog_price")))
    assert prices == _priced(inputs, _sizes(catalog))
    reed = [row for row in preview(teams, catalog, "relation", "tenant_monthly_cost") if row[0] == "reed"]
    assert reed == [["reed", prices["cluster/small"], "EUR-cent"]]
