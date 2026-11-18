"""Compare the ordinary loop rules with independently supplied step-check results."""
import json

import pytest

from pack_records import LOOP, evaluate
from rezono_compiler import pack


def test_step_safety_reasons():
    checks = [
        ("safe", "storage", "proved", "variant-valid"),
        ("false", "permit", "refuted", "failed-prerequisite"),
        ("unsafe", "retains-provider", "refuted", "violated-invariant"),
        ("unknown", "consumer-inventory", "unknown", "missing-coverage"),
    ]
    records = {
        "loop_active_run": [{"id": "active"}],
        "loop_sweep_receipt": [{"id": "current", "run": "active", "event_time": 10}],
        "loop_step": [{"id": step} for step, *_ in checks],
        "loop_step_safety_check": [
            {"id": "check-" + step, "run": "active", "step": step, "cut": "current",
             "obligation": obligation, "verdict": verdict, "reason": reason}
            for step, obligation, verdict, reason in checks
        ] + [
            {"id": "stale-success", "run": "prior", "step": "unknown", "cut": "earlier",
             "obligation": "consumer-inventory", "verdict": "proved", "reason": "variant-valid"}
        ],
    }
    model = pack.read(LOOP)
    assert "loop_step_safety_check" in model.kinds, "The loop pack lacks the typed step-check input"
    program, rows, explainer = evaluate(model, records)
    assert {row[:2] for row in rows.get("safe_alone", ())} == {("active", "safe")}
    expected = {
        ("active", "false", "permit", "failed-prerequisite"),
        ("active", "unsafe", "retains-provider", "violated-invariant"),
        ("active", "unknown", "consumer-inventory", "missing-coverage"),
    }
    waiting = {row for row in rows.get("waiting", ()) if row[0] == "active"}
    assert waiting == expected
    for row in waiting:
        proof = explainer.proof("waiting", row, "fixture")
        leaves = {
            json.loads(p["row"]["key"])[0]
            for witness in proof["witnesses"]
            for p in witness["premises"]
            if p["polarity"] == "positive" and p["row"]["relation"] in program.base_used()
        }
        assert "check-" + row[1] in leaves and "stale-success" not in leaves
