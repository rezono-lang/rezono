"""Check committed evidence and compare implemented rule relations with the independent reference."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent


def compare_relations(expected, actual):
    for name in sorted(expected.keys() | actual.keys()):
        assert name in expected and name in actual, f"First differing relation: {name} (absent)"
        assert expected[name] == actual[name], f"First differing relation: {name}"


def test_reference_rows_are_current():
    result = subprocess.run([sys.executable, "-c",
                             "import json, oracle; print(json.dumps({k: oracle.rows(v) for k,v in oracle.RELATIONS.items()}))"],
                            cwd=HERE, check=True, capture_output=True, text=True)
    compare_relations(json.loads((HERE / "oracle-rows.json").read_text()), json.loads(result.stdout))


def test_rule_results_match_independent_platform_rows():
    from rules_support import states

    expected = json.loads((HERE / "oracle-rows.json").read_text())
    names = sorted(k for k in expected if not k.startswith("cluster_"))
    assert len(names) == 20
    want = {k: {tuple(map(str, row)) for row in expected[k]} for k in names}
    _, _, fact_states = states(HERE)
    state, = fact_states
    compare_relations(want, {k: state.derived[k] for k in names if k in state.derived})


def test_catalog_reference_rows_are_current():
    result = subprocess.run([sys.executable, str(HERE / "tenant_oracle.py")], check=True,
                            capture_output=True, text=True)
    expected = json.loads((HERE / "tenant-rows.json").read_text())
    actual = json.loads(result.stdout)
    assert expected.keys() == actual.keys()
    for scenario in sorted(expected):
        compare_relations(expected[scenario], actual[scenario])


def test_tenant_publication_contains_only_owned_rows():
    from tenant_oracle import scenarios, tenant_publication

    results = scenarios()["requested"]
    for owner in ("elm", "reed"):
        visible = tenant_publication(results, owner)
        assert all(row[0] == owner for relation in visible.values() for row in relation)
        entity, = [row[2] for row in visible["catalog"]]
        assert entity["metadata"]["namespace"] == owner
        assert entity["spec"]["owner"] == f"group:{owner}/{owner}"


def test_tenant_decision_examples():
    rows = json.loads((HERE / "tenant-rows.json").read_text())
    assert rows["requested"]["monthlyCost"] == [["elm", 7505, "EUR-cent"], ["reed", 2495, "EUR-cent"]]
    assert rows["requested"]["proposal"] == [["elm", "elm-1", "review"], ["reed", "reed-1", "denied"]]
    assert rows["requested"]["shortages"] == []
    assert rows["third"]["shortages"] == [["guest-host", "cores", 1], ["guest-host", "memoryGiB", 2],
                                          ["storage-pool", "storageGiB", 10]]
    assert ["reed", "reed-2", "denied"] in rows["third"]["proposal"]


@pytest.mark.xfail(strict=True, reason="Implement cluster control-host placement in examples/platform/schema, facts and rules. Read decisions/platform-clusters.md and compare the complete independent rows.")
def test_control_host_is_derived_by_the_pack():
    from rules_support import states

    expected = json.loads((HERE / "oracle-rows.json").read_text())["cluster_control_host"]
    _, _, fact_states = states(HERE)
    assert fact_states[0].derived.get("cluster_control_host") == set(map(tuple, expected))

@pytest.mark.xfail(strict=True, reason="Implement file-based tenant request ingestion and exact monthly cost in the platform pack. Read decisions/platform-tenants.md. Write examples/platform/schema/tenant.yaml, facts/tenant.yaml, and the tenant calculation or rule module.")
def test_monthly_cost_is_derived_by_the_pack():
    from rules_support import states

    expected = json.loads((HERE / "tenant-rows.json").read_text())["requested"]["monthlyCost"]
    _, _, fact_states = states(HERE)
    actual = fact_states[0].derived.get("tenant_monthly_cost")
    assert actual == {tuple(map(str, row)) for row in expected}
