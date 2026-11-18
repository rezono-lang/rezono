import json

import pytest

from delivery_inventory_support import add_service, delivery_id, exact, expected
from request_preview_case import copy_requests


def test_file_delivery_project_targets(tmp_path):
    teams, catalog = copy_requests(tmp_path)

    def check():
        oracle = expected(teams, catalog)
        exact(teams, catalog, "tenant_delivery_scope", oracle["scope"])
        exact(teams, catalog, "tenant_apply_target",
              [[owner, *delivery_id(target)] for owner, target in oracle["applicationTargets"]])

    check()
    add_service(teams)
    check()
    declarations = json.loads(catalog.read_text())
    del declarations["bindings"]["registry-project"]
    catalog.write_text(json.dumps(declarations))
    check()
    (teams / "reed/studio/request.json").unlink()
    check()
