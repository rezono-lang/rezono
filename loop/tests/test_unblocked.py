"""Independent relational oracle for unblocked, the eligibility that ready used to mean."""

import pytest

from loop_oracle import evaluate


@pytest.mark.xfail(
    strict=True,
    raises=FileNotFoundError,
    reason=(
        "Read decisions/loop-certificate-admission.md section 1 and decisions/safe-step-rounds.md section 1. "
        "Add packs/std-loop/rules/unblocked.dl with unblocked(run, step, reason): each eligibility witness of an "
        "unfinished step with no waiting row in the same run, which is what ready.dl derives today. Leave "
        "ready.dl unchanged; a later task gives ready its certified meaning. Write in packs/std-loop."
    ),
)
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
