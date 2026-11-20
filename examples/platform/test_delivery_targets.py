import json

import pytest

from delivery_inventory_support import add_service, delivery_id, exact, expected
from request_preview_case import copy_requests, preview


def test_file_delivery_project_targets(tmp_path):
    teams, catalog = copy_requests(tmp_path)

    def check():
        oracle = expected(teams, catalog)
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


class ScopeKindHiddenInNumber(AssertionError):
    pass


def scope_rows(teams, catalog, relation):
    try:
        return preview(teams, catalog, "relation", relation)
    except AssertionError as error:
        if f"unknown derived relation {relation!r}" in str(error):
            raise ScopeKindHiddenInNumber(f"the preview lacks {relation}") from error
        raise


def test_delivery_scope_kind_is_a_column(tmp_path):
    teams, catalog = copy_requests(tmp_path)
    declarations = json.loads(catalog.read_text())
    declarations["bindings"]["secret-policy"] = "delivery"
    catalog.write_text(json.dumps(declarations))

    def check():
        bindings = json.loads(catalog.read_text())["bindings"]
        kinds, numbers = set(), []
        for team, artifact, owner in expected(teams, catalog)["scope"]:
            kinds.add((team, artifact, bindings[artifact]))
            if bindings[artifact] == "delivery":
                key_owner, number = delivery_id(owner)
                assert key_owner == team
                numbers.append([team, artifact, number])
        assert scope_rows(teams, catalog, "tenant_artifact_scope") == sorted(map(list, kinds))
        actual = scope_rows(teams, catalog, "tenant_delivery_scope")
        if actual != sorted(numbers):
            raise ScopeKindHiddenInNumber(f"tenant_delivery_scope is not the rule's delivery rows: {actual}")

    check()
    add_service(teams)
    check()
    declarations = json.loads(catalog.read_text())
    del declarations["bindings"]["registry-project"]
    declarations["bindings"]["gitops-project"] = "delivery"
    catalog.write_text(json.dumps(declarations))
    check()
    (teams / "reed/studio/request.json").unlink()
    check()
