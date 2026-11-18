"""Independent relational oracle for needed."""

import pytest

from loop_oracle import evaluate


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement packs/std-loop/rules/needed.dl. Combine explicit prerequisites with completion tokens of ordered predecessors.")
def test_needed_evidence():
    columns = {
        "requirement": "run step token reason",
        "completion": "run step token reason",
        "before": "first second",
    }
    facts = {
        "requirement": [
            ("r", "serve", "key", "q"),
        ],
        "completion": [
            ("r", "build", "artifact", "b"),
            ("r", "other", "x", "o"),
        ],
        "before": [
            ("build", "serve"),
        ],
    }
    expected = set(facts["requirement"]) | {
        (run, second, token, reason)
        for first, second in facts["before"]
        for run, step, token, reason in facts["completion"] if step == first
    }
    assert evaluate("needed", columns, facts) == expected
