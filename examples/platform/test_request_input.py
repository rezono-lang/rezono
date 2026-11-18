import json

import pytest

from request_preview_case import ROOT, copy_requests, preview


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement the public request preview adapter and typed input schema in examples/platform/request_preview.py and schema/request_input.yaml. Read decisions/platform-request-input.md.")
def test_request_json_enters_compiler_base_tables(tmp_path):
    teams, catalog = copy_requests(tmp_path)
    baseline = preview(teams, catalog, "inputs")
    expected_flow = json.loads((ROOT / "oracle-rows.json").read_text())["flow"]
    assert preview(teams, catalog, "relation", "flow") == expected_flow
    sizes = {("elm/ledger/cluster", "medium"), ("elm/ledger/database", "medium"),
             ("reed/studio/cluster", "small")}
    assert set(map(tuple, baseline["tenant_request_item__size"])) == sizes
    assert ["database/medium", 2510] in baseline["tenant_catalog_offer__monthly_cents"]
    request = teams / "elm/ledger/request.json"
    changed = json.loads(request.read_text())
    del changed["items"]["database"]
    request.write_text(json.dumps(changed))
    edited = preview(teams, catalog, "inputs")
    assert set(map(tuple, edited["tenant_request_item__size"])) == sizes - {("elm/ledger/database", "medium")}
    assert edited["tenant_catalog_offer__monthly_cents"] == baseline["tenant_catalog_offer__monthly_cents"]
