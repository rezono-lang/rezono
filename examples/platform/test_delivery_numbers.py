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
