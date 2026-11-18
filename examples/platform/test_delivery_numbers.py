import json
import shutil

import pytest

from delivery_inventory_support import add_service, delivery_id, exact, expected
from request_preview_case import copy_requests, preview


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


def test_file_delivery_numbers_preserve_fractional_utc_order(tmp_path):
    teams, catalog = copy_requests(tmp_path)
    request = teams / "elm/ledger/request.json"
    proposal = json.loads(request.read_text(encoding="utf-8"))
    request.unlink()
    for service, timestamp in (
        ("z-first", "2026-01-01T00:00:00.0000000000000000001Z"),
        ("a-tie", "2026-01-01T00:00:00.0000000000000000002Z"),
        ("b-tie", "2026-01-01T00:00:00.000000000000000000200Z"),
    ):
        request = teams / "elm" / service / "request.json"
        request.parent.mkdir()
        request.write_text(json.dumps(proposal | {"submittedAt": timestamp}), encoding="utf-8")
    assert preview(teams, catalog, "relation", "tenant_delivery_number") == [
        ["elm", "a-tie", 2], ["elm", "b-tie", 3], ["elm", "z-first", 1], ["reed", "studio", 1],
    ]
