"""Health is an observation of a particular service in a particular run."""

import pytest

from case_support import verified


def inputs():
    return {
        "health_step": [
            {"id": "s1", "service": "api", "run": "now", "token": "check-1"},
            {"id": "s2", "service": "database", "run": "now", "token": "check-2"},
            {"id": "s3", "service": "quiet", "run": "now", "token": "check-3"},
        ],
        "health_probe": [
            {"id": "bad", "service": "api", "run": "now", "token": "check-1", "status": "unhealthy"},
            {"id": "good", "service": "database", "run": "now", "token": "check-2", "status": "healthy"},
            {"id": "other-run", "service": "quiet", "run": "then", "token": "check-3", "status": "healthy"},
            {"id": "other-token", "service": "quiet", "run": "now", "token": "old", "status": "healthy"},
            {"id": "other-service", "service": "cache", "run": "now", "token": "check-3", "status": "healthy"},
        ],
    }


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Implement schema/management_health.yaml and rules/management_health.dl for the platform. "
    "Read decisions/platform-management-health.md for the run, service and observation token."))
def test_management_health():
    from management_probes import compiled

    records = inputs()
    for identified in (False, True):
        if identified:
            records["health_probe"][-1]["service"] = "quiet"
        model, state = compiled(records)
        expected = {("s1", "unhealthy", "bad"), ("s2", "healthy", "good"),
                    ("s3", "healthy", "other-service") if identified else ("s3", "unknown", "s3")}
        assert state.derived.get("managed_health") == expected
        completed = {("s2", "good")} | ({("s3", "other-service")} if identified else set())
        assert state.derived.get("managed_health_complete") == completed
        assert state.derived.get("managed_health_finding") == {("s1", "bad")}
        leaves = verified("managed_health_finding", ("s1", "bad"), state=(model, state))
        assert ("health_probe__status", ("bad", "unhealthy")) in leaves


@pytest.mark.cluster
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Depends on the shared disposable loop recorder and test_management_health. "
    "Exercise the collector, service health and inaccessible cluster per decisions/platform-management-health.md."))
def test_management_health_readback():
    from management_probes import live_events

    events = live_events("health")
    expected = {"bad-service": "unhealthy", "well-service": "healthy", "unreachable-cluster": "unknown"}
    assert {e["subject"]: e["state"] for e in events if e["kind"] == "health"} == expected
    completion, = [e for e in events if e["kind"] == "step-complete"]
    observed, = [e for e in events if e["kind"] == "health" and e["subject"] == "well-service"]
    assert (completion["subject"], completion["token"], completion["source_evidence"]) == (
        observed["subject"], observed["token"], observed["evidence"])
    assert {e["channel"] for e in events if e["kind"] == "collector-delivery"} == {"metrics", "logs", "alerts"}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Derive telemetry flows and crossed-zone firewall needs in rules/management_routes.dl and its schema. "
    "Use the placement and ports in decisions/platform-management-health.md."))
def test_management_observation_routes():
    from management_probes import compiled

    records = {"telemetry_cluster": [{"id": "work", "zone": "work"}, {"id": "ops", "zone": "shared"}],
               "telemetry_endpoint": [{"id": channel, "channel": channel, "zone": "shared", "port": port}
                                      for channel, port in (("metrics", 4317), ("logs", 4318), ("alerts", 9443))]}
    for destination in ("shared", "work"):
        records["telemetry_endpoint"][2]["zone"] = destination
        _, state = compiled(records)
        streams = {(cluster, endpoint, str(port)) for cluster in ("work", "ops")
                   for endpoint, port in (("metrics", 4317), ("logs", 4318), ("alerts", 9443))}
        crossing = {("work", "metrics", "4317"), ("work", "logs", "4318"),
                    ("work" if destination == "shared" else "ops", "alerts", "9443")}
        assert state.derived.get("managed_telemetry_flow") == streams
        assert state.derived.get("managed_telemetry_firewall") == crossing


def test_missing_recorder_is_unavailable(tmp_path, monkeypatch):
    import subprocess
    from management_probes import live_events

    config = tmp_path / "fixture.kubeconfig"
    config.touch()
    for key, value in (("GITHUB_RUN_ID", "17"), ("GITHUB_RUN_ATTEMPT", "2"), ("RUNNER_TEMP", str(tmp_path)),
                       ("REZONO_CLUSTER_KUBECONFIG", str(config))):
        monkeypatch.setenv(key, value)

    def read(command, **kwargs):
        if command[-2:] == ["config", "current-context"]:
            return "kind-rezono-fixture\n"
        assert "record-health-17-2" in command
        if "--ignore-not-found" in command:
            return ""
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "check_output", read)
    with pytest.raises(AssertionError, match="Missing real recorder Job"):
        live_events("health")

    def denied(command, **kwargs):
        if command[-2:] == ["config", "current-context"]:
            return "kind-rezono-fixture\n"
        raise subprocess.CalledProcessError(1, command, stderr="Forbidden")

    monkeypatch.setattr(subprocess, "check_output", denied)
    with pytest.raises(subprocess.CalledProcessError) as refusal:
        live_events("health")
    assert refusal.value.stderr == "Forbidden"

    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "wrong-context\n")
    with pytest.raises(ValueError, match="wrong context"):
        live_events("health")
