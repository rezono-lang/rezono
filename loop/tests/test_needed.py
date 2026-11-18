"""Independent relational oracle for needed."""

import pytest

from loop_oracle import evaluate


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
