"""Health status and its witness follow the most recent source observation."""

import pytest

from case_support import verified
from management_probes import compiled


def probe(step, identifier, status, when=None, **overrides):
    row = {"id": identifier, "service": step["service"], "run": step["run"],
           "token": step["token"], "status": status, **overrides}
    if when is not None:
        row["event_time"] = when
    return row


def test_health_without_event_times():
    step = {"id": "service-step", "service": "api", "run": "run", "token": "check"}
    readings = [probe(step, "positive", "healthy"), probe(step, "negative", "unhealthy")]
    _, state = compiled({"health_step": [step], "health_probe": readings})
    actual = (state.derived["managed_health"], state.derived["managed_health_complete"],
              state.derived["managed_health_finding"])
    assert actual == ({("service-step", "unknown", "service-step")}, set(), set())


@pytest.mark.parametrize("reverse", [False, True], ids=["recorded-order", "reversed-order"])
def test_current_health_and_witness(reverse):
    schedules = {
        "recovery": [("bad-first", "unhealthy", 2), ("recovered", "healthy", 11)],
        "failure": [("good-first", "healthy", 2), ("failed", "unhealthy", 11)],
        "conflict": [("older", "healthy", 1), ("up", "healthy", 11), ("down", "unhealthy", 11)],
        "untimed": [("timed", "healthy", 11), ("undated", "unhealthy", None)],
        "uncertain": [("previous", "healthy", 2), ("uncertain-probe", "unknown", 11)],
        "agreement": [("first", "healthy", 11), ("second", "healthy", 11)],
        "settled": [("prior-up", "healthy", 2), ("prior-down", "unhealthy", 2), ("resolved", "healthy", 11)],
    }
    steps = [{"id": name, "service": "api", "run": "run", "token": name} for name in schedules]
    readings = [probe(step, identifier, status, when) for step in steps
                for identifier, status, when in schedules[step["id"]]]
    for field in ("service", "run", "token"):
        readings.append(probe(steps[0], "other-" + field, "unhealthy", 20, **{field: "other"}))
    if reverse:
        readings.reverse()
    model, state = compiled({"health_step": steps, "health_probe": readings})
    assert state.derived["managed_health"] == {
        ("recovery", "healthy", "recovered"), ("failure", "unhealthy", "failed"),
        ("conflict", "unknown", "conflict"), ("untimed", "unknown", "untimed"),
        ("uncertain", "unknown", "uncertain-probe"),
        ("agreement", "healthy", "first"), ("agreement", "healthy", "second"),
        ("settled", "healthy", "resolved"),
    }
    assert state.derived["managed_health_complete"] == {
        ("recovery", "recovered"), ("agreement", "first"), ("agreement", "second"), ("settled", "resolved")}
    assert state.derived["managed_health_finding"] == {("failure", "failed")}
    for relation, key, observations in (
        ("managed_health_complete", ("recovery", "recovered"), [("recovered", "healthy")]),
        ("managed_health_finding", ("failure", "failed"), [("failed", "unhealthy")]),
        ("managed_health", ("conflict", "unknown", "conflict"), [("up", "healthy"), ("down", "unhealthy")]),
    ):
        leaves = verified(relation, key, state=(model, state))
        for identifier, status in observations:
            assert ("health_probe__status", (identifier, status)) in leaves
            assert ("health_probe__event_time", (identifier, "11")) in leaves


def test_invalid_source_event_time():
    from rezono_compiler.facts import LoadError

    step = {"id": "service-step", "service": "api", "run": "run", "token": "check"}
    with pytest.raises(LoadError, match=r"health_probe\[1\]\.event_time: is not a BIGINT"):
        compiled({"health_step": [step], "health_probe": [probe(step, "bad-clock", "healthy", "yesterday")]})
