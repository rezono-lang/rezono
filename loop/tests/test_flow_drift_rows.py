"""Compare std-loop output with the independently read synthetic flow recording."""

from pathlib import Path

import pytest
import yaml

from flow_drift_cases import (
    FLOW_COLUMNS, OTHER_SCOPES, POLICY, REPORT_CASES, SCOPE, SWEEP_COLUMNS, SWEEP_REF,
    MissingVerifiedSweepInventory, coverage_rows, expected_rows, flow_rows, tuples,
)
from loop_oracle import evaluate
from wire_fixtures import fixture


def test_recorded_flow_reference():
    """Check the written answer against fixture intentions, raw events and public statuses."""
    keys = tuples()
    allowed = {keys[case["id"]] for case in fixture("network")["cases"] if case["service"] == "allow"}
    raw = flow_rows()
    assert {row[1:5] for row in raw["allowed_flow"]} == allowed
    complete = coverage_rows("complete")
    for case in (*REPORT_CASES, "empty-inventory"):
        data = coverage_rows(case)
        # The verified members decide the population; a recorded node outside them blocks completeness.
        keys = {}
        for _, member, part, value in data["verified_member"]:
            keys.setdefault(member, {})[part] = value
        required = {key[4] for key in keys.values()
                    if (key[0], key[1], key[2], key[3]) == ("sweep-node", *SCOPE)}
        recorded = {node for *scope, node in data["expected_node"] if tuple(scope) == SCOPE}
        covered = {node for *scope, node, first, last, gaps, lost in data["node_report"]
                   if tuple(scope) == SCOPE and first <= 10 and last >= 20 and gaps == lost == 0}
        assert bool(required and required <= covered and recorded <= required) == (case == "complete"), case
    assert complete["sweep_window"] == [(*SCOPE, 10, 20, SWEEP_REF)]
    observed = {}
    for *scope, tick, src, dst, protocol, port, verdict, ref in raw["flow_event"]:
        if tuple(scope) == SCOPE and 10 <= tick < 20:
            observed.setdefault((src, dst, protocol, port), []).append((verdict, ref))
    rule_refs = {row[1:5]: row[-1] for row in raw["allowed_flow"]}
    answers = {
        (True, "forwarded"): ("matched", "valid"), (True, "dropped"): ("blocked", "violated"),
        (False, "forwarded"): ("excess", "violated"), (False, "dropped"): ("prevented", "absent"),
    }
    for certificate in (False, True):
        reference = set()
        for key in allowed | observed.keys():
            prefix = (*SCOPE, *key[:3], str(key[3]))
            for verdict, ref in observed.get(key, []):
                reference.add((*prefix, *answers[key in allowed, verdict], rule_refs.get(key, POLICY), ref))
            if certificate and key in allowed and key not in observed:
                reference.add((*prefix, "unseen", "unknown", rule_refs[key], SWEEP_REF))
        assert reference == expected_rows(certificate)
    contract = Path(__file__).resolve().parents[2] / "contracts" / "view.yaml"
    statuses = yaml.safe_load(contract.read_text(encoding="utf-8"))["enums"]["StatusName"]["permissible_values"]
    assert {row[-3] for row in expected_rows(True)} <= statuses.keys()


def test_flow_drift_rows():
    raw = flow_rows()
    # Exercise the production comparison directly. Wrong scopes cannot certify absence.
    foreign = [(*other, SWEEP_REF) for other in OTHER_SCOPES] + [(*SCOPE, "sweep/unrelated")]
    assert evaluate("flow_drift", FLOW_COLUMNS, dict(raw, complete_sweep=foreign)) == expected_rows(False)

    for case in ("complete", "lost-event"):
        produced = evaluate("complete_sweep", SWEEP_COLUMNS, coverage_rows(case))
        data = dict(raw, complete_sweep=list(produced))
        assert evaluate("flow_drift", FLOW_COLUMNS, data) == expected_rows(case == "complete"), case

    # Distinct policy rows supporting the same tuple remain individually traceable.
    echo = raw["allowed_flow"][0]
    second_ref = "allow/also-echo"
    another = dict(raw, complete_sweep=[], allowed_flow=[*raw["allowed_flow"], (*echo[:-1], second_ref)])
    observed = expected_rows(False)
    extra = {(*row[:-2], second_ref, row[-1]) for row in observed if row[-2] == echo[-1]}
    assert evaluate("flow_drift", FLOW_COLUMNS, another) == observed | extra

    # Rebind the same event recording to a closed empty snapshot. The Hubble
    # events retain their identities and can never create an allowance.
    alternate = "policy/empty"
    variant = dict(raw, bound_policy=[(*SCOPE, alternate)], complete_sweep=[(*SCOPE, SWEEP_REF)])
    changed = set()
    for row in expected_rows(False):
        dropped = row[-4] in {"blocked", "prevented"}
        outcome = ("prevented", "absent") if dropped else ("excess", "violated")
        changed.add((*row[:-4], *outcome, alternate, row[-1]))
    assert evaluate("flow_drift", FLOW_COLUMNS, variant) == changed
    assert evaluate("flow_drift", FLOW_COLUMNS, dict(variant, bound_policy=[])) == set()


@pytest.mark.xfail(
    strict=True,
    raises=MissingVerifiedSweepInventory,
    reason=(
        "M2: decisions/admission-transport.md: section 6, member keys. Without admitted sweep-node members the "
        "complete recorded sweep certifies nothing, so the allowed flow that was not seen stays out of flow_drift. "
        "Waits for loop/tests/test_flow_drift_sweep.py--test_complete_flow_sweep_needs_verified_inventory. Today "
        "complete_sweep follows from the recorded inventory without any receipt."
    ),
)
def test_flow_drift_needs_verified_sweep():
    raw = flow_rows()
    for verified, complete in ((True, True), (False, False)):
        produced = evaluate("complete_sweep", SWEEP_COLUMNS, coverage_rows("complete", verified=verified))
        drift = evaluate("flow_drift", FLOW_COLUMNS, dict(raw, complete_sweep=list(produced)))
        if drift != expected_rows(complete):
            raise MissingVerifiedSweepInventory(f"verified={verified}: {sorted(drift - expected_rows(complete))}")
