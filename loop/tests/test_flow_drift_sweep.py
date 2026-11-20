"""Coverage certificates must follow the verified node inventory and the recorded reports."""

import json

import pytest

from flow_drift_cases import (
    NODES, OTHER_SCOPES, REPORT_CASES, SCOPE, SWEEP_COLUMNS, SWEEP_REF, MissingVerifiedSweepInventory,
    coverage_rows, verified_sweep,
)
from loop_oracle import evaluate
from pack_records import LOOP, evaluate as evaluate_pack


def test_complete_flow_sweep():
    for case in (*REPORT_CASES, "empty-inventory"):
        expected = {(*SCOPE, SWEEP_REF)} if case == "complete" else set()
        assert evaluate("complete_sweep", SWEEP_COLUMNS, coverage_rows(case)) == expected, case


def test_complete_flow_sweep_needs_verified_inventory():
    records = coverage_rows("complete", verified=False)
    cases = {
        "verified": (verified_sweep(), True),
        "verified-without-recorded-inventory": (verified_sweep(), True, {"expected_node": []}),
        "no-receipt": ({}, False),
        "recorded-node-outside-receipt": (verified_sweep(NODES[:1]), False),
        "unreported-member": (verified_sweep((*NODES, "node-c")), False),
        "other-tag": (verified_sweep(tag="path-reader"), False),
    }
    for index, other in enumerate(OTHER_SCOPES):
        cases[f"other-scope-{index}"] = (verified_sweep(scope=other), False)
    for name, (verified, complete, *change) in cases.items():
        data = {**records, **verified, **(change[0] if change else {})}
        produced = evaluate("complete_sweep", SWEEP_COLUMNS, data)
        if produced != ({(*SCOPE, SWEEP_REF)} if complete else set()):
            raise MissingVerifiedSweepInventory(f"{name}: {produced}")


@pytest.mark.parametrize("reverse", [False, True], ids=["recorded-order", "reversed-order"])
def test_conflicting_final_reports(reverse):
    from rezono_canon import canonical_json, canonical_sha256
    from rezono_compiler import pack

    # Each window starts with a complete final report. A second, separately identified
    # observation changes one field or comes from an unrelated scope.
    cases = [
        ("single", None, True),
        ("agreement", {}, True),
        ("lost", {"lost": 7}, False),
        ("gap", {"gaps": 1}, False),
        ("late", {"first": 11}, False),
        ("early", {"last": 19}, False),
        ("disputed-start", {"first": 9}, False),
        ("other-run", {"run": "prior", "lost": 7}, True),
        ("other-collector", {"collector": "other", "gaps": 1}, True),
        ("other-window", {"window": "elsewhere", "lost": 7}, True),
        ("other-node", {"node": "unlisted", "lost": 7}, True),
    ]
    records = {"flow_sweep_window": [], "flow_expected_node": [], "flow_node_report": []}
    verified = {"verified_receipt": [], "verified_member": []}
    certificates = set()
    for window, change, complete in cases:
        scope = dict(run="run-a", collector="hubble", window=window)
        for relation, rows in verified_sweep(("node-b",), tuple(scope.values()), f"receipt/{window}").items():
            verified[relation].extend(rows)
        ref = f"sweep/{window}"
        records["flow_sweep_window"].append(dict(scope, id=ref, start=10, stop=20))
        records["flow_expected_node"].append(dict(scope, id=f"inventory/{window}", node="node-b"))
        final = dict(scope, id=f"first/{window}", node="node-b", first=8, last=25, gaps=0, lost=0)
        records["flow_node_report"].append(final)
        if change is not None:
            records["flow_node_report"].append(dict(final | change, id=f"second/{window}"))
        if complete:
            certificates.add(("run-a", "hubble", window, ref))
    if reverse:
        records["flow_node_report"].reverse()

    _, rows, explainer = evaluate_pack(pack.read(LOOP), records, verified)
    assert rows["complete_sweep"] == certificates

    # The disputed node's count commits to both distinct report tuples. Each
    # tuple leads back to the corresponding independent report at the input.
    group = ("run-a", "hubble", "lost", "node-b")
    tuples = [(*group, "8", "25", "0", lost) for lost in ("0", "7")]
    proof = explainer.proof("sweep_node_report_count", (*group, "2"), "fixture")
    witness, = (w for w in proof["witnesses"] if w["conclusion"] == proof["root"])
    aggregate, = witness["aggregates"]
    assert aggregate["relation"] == "node_report" and aggregate["count"] == 2
    assert aggregate["contributors_sha256"] == canonical_sha256([[canonical_json(row)] for row in tuples])
    for row, source in zip(tuples, ["first/lost", "second/lost"], strict=True):
        proof = explainer.proof("node_report", row, "fixture")
        assert any(p["row"]["relation"] == "flow_node_report__lost"
                   and json.loads(p["row"]["key"]) == [source, row[-1]]
                   for w in proof["witnesses"] for p in w["premises"])
