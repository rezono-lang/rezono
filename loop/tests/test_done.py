"""Independent relational oracle for done."""

import pytest

from loop_oracle import evaluate


def test_done_evidence():
    columns = {
        "completion": "run step token reason",
        "known": "run token reason",
    }
    facts = {
        "completion": [
            ("r", "a", "x", "decl-a"),
            ("r", "b", "y", "decl-b"),
        ],
        "known": [
            ("old", "y", "old"),
            ("r", "x", "obs-x"),
            ("r", "other", "irrelevant"),
        ],
    }
    expected = {(run, step, witness) for run, step, token, _ in facts["completion"]
                for seen_run, seen_token, witness in facts["known"] if (run, token) == (seen_run, seen_token)}
    assert evaluate("done", columns, facts) == expected
