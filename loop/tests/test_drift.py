"""A completed sweep can witness absence; an unobserved desired row alone cannot."""

import pytest

from loop_oracle import evaluate


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement packs/std-loop/rules/drift.dl to derive findings with both evidence references.")
def test_drift_witnesses():
    columns = {"desired": "run token value reason", "current": "run token state value reason"}
    facts = {
        "desired": [("r", token, "allow", "case-" + token) for token in ("a", "b", "c", "d", "e")],
        "current": [
            ("r", "a", "known", "deny", "probe-a"),
            ("r", "b", "known", "allow", "probe-b"),
            ("r", "c", "absent", "", "sweep-c"),
            ("old", "d", "known", "deny", "stale"),
            ("r", "e", "unknown", "", "uncertain"),
        ],
    }
    expected = {
        (run, token, desired_ref, obs_ref)
        for run, token, value, desired_ref in facts["desired"]
        for observed_run, observed_token, state, observed_value, obs_ref in facts["current"]
        if (run, token) == (observed_run, observed_token)
        and (state == "absent" or (state == "known" and value != observed_value))
    }
    assert evaluate("drift", columns, facts) == expected
