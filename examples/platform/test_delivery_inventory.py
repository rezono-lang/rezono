import json

import pytest

from delivery_inventory_support import add_service, delivery_id, exact, expected
from request_preview_case import copy_requests


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Depends on test_file_delivery_numbers and test_trusted_tenant_proposal_inputs. "
    "Join request items, components and provisions in rules/tenant_delivery_inventory.dl. "
    "Read decisions/platform-delivery-inventory.md."
))
def test_file_delivery_inventory(tmp_path):
    teams, catalog = copy_requests(tmp_path)

    def check():
        oracle = expected(teams, catalog)
        for relation, source in (("tenant_delivery_item", "deliveries"),
                                 ("tenant_delivery_placement", "placements")):
            exact(teams, catalog, relation,
                  [[owner, delivery_id(key)[1], *fields] for owner, key, *fields in oracle[source]])

    check()
    add_service(teams)
    check()
    model = json.loads(catalog.read_text())
    model["catalog"]["database"]["provisions"].append("database-backup")
    catalog.write_text(json.dumps(model))
    check()
