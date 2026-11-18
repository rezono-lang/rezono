"""Independent relational oracle for stuck."""

import pytest

from loop_oracle import evaluate


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement packs/std-loop/rules/stuck.dl. Carry terminal refusal evidence and report cycles for affected steps in the active run.")
def test_stuck_evidence():
    columns = {
        "declared": "run step reason",
        "order_cycle": "element",
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
        "refusal": [
            ("r", "b", "ref-b"),
            ("old", "c", "ref-old"),
        ],
    }
    expected = {(run, step, reason) for run, step, reason in facts["declared"]
                if (step,) in facts["order_cycle"]}
    expected.update(row for row in facts["refusal"] if row[:2] in {d[:2] for d in facts["declared"]})
    assert evaluate("stuck", columns, facts) == expected
