"""Independent relational oracle for current observations, including simultaneous evidence."""

import pytest

from loop_oracle import evaluate


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement packs/std-loop/rules/known.dl. Order observations by integer event time within the active run and token. Preserve every supporting evidence reference at an unambiguous latest instant.")
def test_known_evidence():
    columns = {
        "active": "run",
        "expectation": "token value",
        "observed": [
            ("run", "string"), ("token", "string"), ("event_time", "integer"),
            ("event_id", "string"), ("state", "string"), ("value", "string"),
            ("reason", "string"),
        ],
    }
    observations = [
        ("r", "a", 10, "evt-a", "known", "yes", "source/new"),
        ("r", "a", 2, "evt-z", "known", "no", "source/old"),
        ("old", "b", 12, "evt-b", "known", "yes", "source/stale"),
        ("r", "c", 12, "evt-c", "unknown", "", "source/unknown"),
        ("r", "d", 12, "evt-d1", "known", "yes", "source/conflict-1"),
        ("r", "d", 12, "evt-d2", "known", "no", "source/conflict-2"),
        ("r", "e", 2, "evt-e1", "known", "yes", "source/was-matching"),
        ("r", "e", 10, "evt-e2", "known", "no", "source/no-longer-matching"),
        ("r", "f", 12, "evt-f1", "known", "yes", "source/independent-1"),
        ("r", "f", 12, "evt-f2", "known", "yes", "source/independent-2"),
        ("r", "g", 12, "evt-g1", "known", "yes", "source/affirmative"),
        ("r", "g", 12, "evt-g2", "unknown", "", "source/unconfirmed"),
    ]
    facts = {
        "active": [("r",)],
        "expectation": [(token, "yes") for token in "abcdefgh"],
        "observed": observations,
    }
    expected = set()
    for (run,) in facts["active"]:
        for token, desired in facts["expectation"]:
            rows = [row for row in observations if row[:2] == (run, token)]
            if not rows:
                continue
            newest = max(row[2] for row in rows)
            latest = [row for row in rows if row[2] == newest]
            if {(row[4], row[5]) for row in latest} == {("known", desired)}:
                expected.update((run, token, row[6]) for row in latest)
    assert expected == {
        ("r", "a", "source/new"),
        ("r", "f", "source/independent-1"),
        ("r", "f", "source/independent-2"),
    }
    assert evaluate("known", columns, facts) == expected
