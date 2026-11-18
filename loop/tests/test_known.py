"""Independent relational oracle for known."""

import pytest

from loop_oracle import evaluate


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement packs/std-loop/rules/known.dl. Match desired values to the latest unambiguous known observation in the active run.")
def test_known_evidence():
    columns = {
        "active": "run",
        "expectation": "token value",
        "observed": "run token event state value reason",
    }
    facts = {
        "active": [
            ("r",),
        ],
        "expectation": [
            ("a", "yes"),
            ("b", "yes"),
            ("c", "yes"),
            ("d", "yes"),
            ("e", "yes"),
        ],
        "observed": [
            ("r", "a", "01", "known", "no", "early"),
            ("r", "a", "02", "known", "yes", "a2"),
            ("old", "b", "03", "known", "yes", "stale"),
            ("r", "c", "02", "unknown", "", "unknown"),
            ("r", "d", "02", "known", "yes", "tie-a"),
            ("r", "d", "02", "known", "no", "tie-b"),
            ("r", "e", "01", "known", "yes", "e1"),
            ("r", "e", "02", "known", "no", "e2"),
        ],
    }
    expected = set()
    for (run,) in facts["active"]:
        for token, desired in facts["expectation"]:
            rows = [row for row in facts["observed"] if row[:2] == (run, token)]
            latest = [row for row in rows if row[2] == max(item[2] for item in rows)]
            if {(row[3], row[4]) for row in latest} == {("known", desired)}:
                expected.update((run, token, row[5]) for row in latest)
    assert evaluate("known", columns, facts) == expected
