"""Independent relational oracle for waiting."""

import pytest

from loop_oracle import evaluate


def test_waiting_evidence():
    columns = {
        "needed": "run step token reason",
        "known": "run token reason",
        "done": "run step reason",
    }
    facts = {
        "needed": [
            ("r", "a", "x", "ax"),
            ("r", "a", "y", "ay"),
            ("r", "b", "z", "bz"),
        ],
        "known": [
            ("r", "x", "seen-x"),
            ("old", "y", "old-y"),
        ],
        "done": [
            ("r", "b", "seen-b"),
        ],
    }
    expected = {row for row in facts["needed"]
                if row[:2] not in {d[:2] for d in facts["done"]}
                and (row[0], row[2]) not in {k[:2] for k in facts["known"]}}
    assert evaluate("waiting", columns, facts) == expected
