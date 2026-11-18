import json

import pytest

from delivery_inventory_support import add_service, delivery_id, exact, expected
from request_preview_case import copy_requests


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
