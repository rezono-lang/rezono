"""Independent relational oracle for stuck."""

import pytest

from loop_oracle import evaluate


def test_stuck_evidence():
    columns = {
        "declared": "run step reason",
        "order_cycle": "element",
        "fixed_point": "run sweep step token requirement",
        "refusal": "run step reason",
    }
    facts = {
        "declared": [
            ("r", "a", "decl-a"),
            ("r", "b", "decl-b"),
            ("r", "c", "decl-c"),
        ],
        "order_cycle": [
            ("a",),
            ("outside",),
        ],
        "fixed_point": [("r", "scan", "c", "permit", "permit-rule")],
        "refusal": [
            ("r", "b", "ref-b"),
            ("old", "c", "ref-old"),
        ],
    }
    expected = {(run, step, reason) for run, step, reason in facts["declared"]
                if (step,) in facts["order_cycle"]}
    expected.update(row for row in facts["refusal"] if row[:2] in {d[:2] for d in facts["declared"]})
    expected.add(("r", "c", "scan"))
    assert evaluate("stuck", columns, facts) == expected
