"""Independent relational oracle for the eligibility that ready means today.

decisions/loop-certificate-admission.md section 1 moves this meaning from ready to unblocked. Until
packs/std-loop/rules/unblocked.dl exists, ready.dl carries it and this oracle checks ready; from then on it
checks unblocked, so ready can take its certified meaning while the eligibility stays checked.
"""

from loop_oracle import evaluate, has_relation


def test_eligibility_evidence():
    relation = "unblocked" if has_relation("unblocked") else "ready"
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
    assert evaluate(relation, columns, facts) == expected
