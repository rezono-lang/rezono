"""Check committed evidence and compare implemented rule relations with the independent reference."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from request_preview_case import copy_requests, preview


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
    # A floor, not an exact count: dropping an oracle relation is red, while two changes that each add one
    # still agree once they are merged.
    assert len(names) >= 20
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


def test_oracle_self_check_tenant_publication_keeps_owned_rows():
    # Checks the standalone tenant oracle against itself; no pack rule is evaluated.
    from tenant_oracle import scenarios, tenant_publication

    results = scenarios()["requested"]
    for owner in ("elm", "reed"):
        visible = tenant_publication(results, owner)
        assert all(row[0] == owner for relation in visible.values() for row in relation)
        entity, = [row[2] for row in visible["catalog"]]
        assert entity["metadata"]["namespace"] == owner
        assert entity["spec"]["owner"] == f"group:{owner}/{owner}"


def test_oracle_self_check_tenant_decision_examples():
    # Checks the committed oracle rows against themselves; no pack rule is evaluated.
    rows = json.loads((HERE / "tenant-rows.json").read_text())
    assert rows["requested"]["monthlyCost"] == [["elm", 7505, "EUR-cent"], ["reed", 2495, "EUR-cent"]]
    assert rows["requested"]["proposal"] == [["elm", "elm-1", "review"], ["reed", "reed-1", "denied"]]
    assert rows["requested"]["shortages"] == []
    assert all(used == 0 for _, _, used, _ in rows["requested"]["capacity"])
    assert rows["third"]["capacity"] == rows["requested"]["capacity"]
    assert rows["third"]["shortages"] == []
    assert ["reed", "reed-2", "standard"] in rows["third"]["proposal"]


def test_control_host_is_derived_by_the_pack():
    from rules_support import states

    expected = json.loads((HERE / "oracle-rows.json").read_text())["cluster_control_host"]
    _, _, fact_states = states(HERE)
    assert fact_states[0].derived.get("cluster_control_host") == set(map(tuple, expected))

def test_monthly_cost_is_derived_by_the_pack(tmp_path):
    from request_preview_case import copy_requests, preview

    teams, catalog = copy_requests(tmp_path)
    expected = json.loads((HERE / "tenant-rows.json").read_text())["requested"]["monthlyCost"]
    def costs():
        return preview(teams, catalog, "relation", "tenant_monthly_cost")
    assert costs() == expected
    request = teams / "elm/ledger/request.json"
    changed = json.loads(request.read_text())
    del changed["items"]["database"]
    request.write_text(json.dumps(changed))
    assert costs() == [["elm", 4995, "EUR-cent"], ["reed", 2495, "EUR-cent"]]
    prices = json.loads(catalog.read_text())
    prices["catalog"]["cluster"]["sizes"]["small"][3] += 1
    catalog.write_text(json.dumps(prices))
    assert costs() == [["elm", 4995, "EUR-cent"], ["reed", 2496, "EUR-cent"]]


class MonthlyCostCountsMissingOffer(AssertionError):
    pass


def _monthly(teams, catalog, relation):
    try:
        return preview(teams, catalog, "relation", relation)
    except AssertionError as error:
        if "unknown derived relation 'tenant_monthly_cost_unknown'" in str(error) or "unknown catalog offer" in str(error):
            raise MonthlyCostCountsMissingOffer(str(error)) from error
        raise


def test_missing_offer_makes_the_monthly_cost_unknown(tmp_path):
    teams, catalog = copy_requests(tmp_path)
    expected = json.loads((HERE / "tenant-rows.json").read_text())["requested"]["monthlyCost"]
    assert _monthly(teams, catalog, "tenant_monthly_cost_unknown") == []
    assert _monthly(teams, catalog, "tenant_monthly_cost") == expected
    elm, reed = expected

    # The catalog offers database only in size medium.
    request = teams / "reed/studio/request.json"
    original = request.read_text()
    changed = json.loads(original)
    changed["items"]["database"] = "small"
    request.write_text(json.dumps(changed))
    assert _monthly(teams, catalog, "tenant_monthly_cost_unknown") == [["reed", "reed/studio/database", "offer-missing"]]
    assert _monthly(teams, catalog, "tenant_monthly_cost") == [elm]

    # Withdrawing the catalog offer that elm requests makes elm's total unknown instead.
    request.write_text(original)
    prices = json.loads(catalog.read_text())
    del prices["catalog"]["database"]["sizes"]["medium"]
    catalog.write_text(json.dumps(prices))
    assert _monthly(teams, catalog, "tenant_monthly_cost_unknown") == [["elm", "elm/ledger/database", "offer-missing"]]
    assert _monthly(teams, catalog, "tenant_monthly_cost") == [reed]
