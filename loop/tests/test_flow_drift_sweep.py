"""Coverage certificates must follow the recorded node inventory and reports."""

import json

import pytest

from flow_drift_cases import REPORT_CASES, SCOPE, SWEEP_COLUMNS, SWEEP_REF, coverage_rows
from loop_oracle import evaluate
from pack_records import LOOP, evaluate as evaluate_pack


def test_complete_flow_sweep():
    for case in (*REPORT_CASES, "empty-inventory"):
        expected = {(*SCOPE, SWEEP_REF)} if case == "complete" else set()
        assert evaluate("complete_sweep", SWEEP_COLUMNS, coverage_rows(case)) == expected, case


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
    certificates = set()
    for window, change, complete in cases:
        scope = dict(run="run-a", collector="hubble", window=window)
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

    _, rows, explainer = evaluate_pack(pack.read(LOOP), records)
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
