import shutil

import pytest

from delivery_inventory_support import add_service, delivery_id, exact, expected
from request_preview_case import copy_requests


def test_file_delivery_numbers(tmp_path):
    teams, catalog = copy_requests(tmp_path)

    def check():
        rows = expected(teams, catalog)["catalog"]
        exact(teams, catalog, "tenant_delivery_number",
              [[owner, entity["metadata"]["name"], delivery_id(key)[1]] for owner, key, entity in rows])

    check()
    add_service(teams)
    check()
    # A simultaneous submission uses the service name as its tie breaker.
    shutil.copyfile(teams / "elm/ledger/request.json", teams / "elm/archive/request.json")
    check()


class AdapterKeyDecidesDeliveryNumber(AssertionError):
    pass


# Per-tenant rank keys that the adapter computes from the whole request set; they are not source values.
ADAPTER_KEYS = {
    "tenant_service_request__submitted_at_key": {"elm/ledger": "elm/archive", "elm/archive": "elm/ledger"},
    "tenant_service_request__service_key": {"elm/cache": "elm/ledger", "elm/ledger": "elm/cache"},
}


@pytest.mark.xfail(strict=True, raises=AdapterKeyDecidesDeliveryNumber, reason=(
    "M2: decisions/ordered-rule-scalars.md: Waits for examples/platform/test_global_request_order.py"
    "--test_adapter_rank_keys_do_not_decide_the_global_request_order. Then number deliveries in "
    "examples/platform/rules/tenant_delivery_number.dl on the source submission instant and the service within the "
    "tenant (decisions/platform-delivery-inventory.md), not on the adapter keys "
    "tenant_service_request__submitted_at_key and tenant_service_request__service_key."))
def test_delivery_numbers_ignore_adapter_rank_keys(tmp_path):
    from rezono_compiler import pack
    from request_preview import preview_inputs, relation_rows
    from request_preview_case import ROOT

    teams, catalog = copy_requests(tmp_path)
    add_service(teams)
    # A simultaneous submission uses the service name as its tie breaker.
    (teams / "elm/cache").mkdir()
    shutil.copyfile(teams / "elm/ledger/request.json", teams / "elm/cache/request.json")
    want = sorted((owner, entity["metadata"]["name"], delivery_id(key)[1])
                  for owner, key, entity in expected(teams, catalog)["catalog"])
    model = pack.read(ROOT)
    inputs = preview_inputs(model, ROOT, teams, catalog)
    assert relation_rows(model, inputs, "tenant_delivery_number") == want

    # Each case changes only adapter keys; every submission instant, tenant and service stays as submitted.
    cases = {}
    for relation, swap in ADAPTER_KEYS.items():
        if not inputs.get(relation):
            continue
        keys = {row[0]: row[1] for row in inputs[relation]}
        mutated = [(request, keys[swap.get(request, request)]) for request, _ in inputs[relation]]
        assert sorted(mutated) != sorted(map(tuple, inputs[relation])), relation
        cases[f"swapped {relation}"] = inputs | {relation: mutated}
    cases["without adapter keys"] = {name: rows for name, rows in inputs.items() if name not in ADAPTER_KEYS}
    changed = {}
    for case, rows in cases.items():
        numbers = relation_rows(model, rows, "tenant_delivery_number")
        if numbers != want:
            changed[case] = numbers
    if changed:
        raise AdapterKeyDecidesDeliveryNumber(f"adapter keys changed the delivery numbers: {changed}")
