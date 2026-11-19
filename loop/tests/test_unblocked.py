"""Independent relational oracle for unblocked, the eligibility that ready used to mean."""

import pytest

from loop_oracle import evaluate


def test_unblocked_evidence():
    columns = {
        "eligible": "run step reason",
        "waiting": "run step token reason",
        "done": "run step reason",
    }
    facts = {
        "eligible": [
            ("r", "a", "decl-a"),
            ("r", "b", "decl-b"),
            ("r", "c", "decl-c"),
        ],
        "waiting": [
            ("r", "b", "x", "need-x"),
            ("old", "a", "x", "old"),
        ],
        "done": [
            ("r", "c", "seen-c"),
        ],
    }
    expected = {row for row in facts["eligible"]
                if row[:2] not in {item[:2] for item in facts["done"] + facts["waiting"]}}
    assert evaluate("unblocked", columns, facts) == expected
