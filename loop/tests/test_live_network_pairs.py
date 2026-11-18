"""Check the hand-written network matrix against the shared kind fixture."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from wire_fixtures import entry, fixture


def _recorded_network(run, attempt):
    """Read this attempt's native Job and its owning recorder Pod."""
    config_value = os.environ.get("REZONO_CLUSTER_KUBECONFIG")
    admission_value = os.environ.get("REZONO_ADMISSION_TEST_KUBECONFIG")
    temp_value = os.environ.get("RUNNER_TEMP")
    assert config_value and admission_value and temp_value, "Requires the shared admission handoff"
    config = Path(config_value).resolve(strict=True)
    assert config.is_relative_to(Path(temp_value).resolve(strict=True))
    assert config.samefile(admission_value)
    command = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]

    def read(*args):
        return subprocess.check_output([*command, *args], text=True, timeout=25)

    assert read("config", "current-context").strip() == "kind-rezono-fixture"
    command.extend(["--context", "kind-rezono-fixture", "-n", "rezono-probes"])
    name = f"record-network-{run}-{attempt}"
    raw = read("get", "job", name, "--ignore-not-found", "-o", "json")
    assert raw.strip(), f"Missing real recorder Job {name}"
    job = json.loads(raw)
    assert job["status"]["succeeded"] == 1
    uid = job["metadata"]["uid"]
    pods = json.loads(read("get", "pods", "-l", f"job-name={name}", "-o", "json"))["items"]
    completed = [
        pod for pod in pods
        if pod["status"]["phase"] == "Succeeded"
        and any(owner["uid"] == uid and owner["controller"] for owner in pod["metadata"]["ownerReferences"])
    ]
    assert len(completed) == 1, "Expected one successful Pod owned by the native recorder Job"
    events = [
        json.loads(line)
        for line in read("logs", completed[0]["metadata"]["name"], "-c", "recorder").splitlines()
    ]
    nodes = {item["metadata"]["name"] for item in json.loads(read("get", "nodes", "-o", "json"))["items"]}
    return events, nodes


def _window(rows, nodes):
    """Require one closed Hubble sweep with final coverage for every fixture node."""
    windows = [row for row in rows if row["kind"] == "window"]
    assert len(windows) == 1
    window = windows[0]
    start, stop = window["start"], window["stop"]
    assert type(start) is int and type(stop) is int and start < stop
    assert window["collector"] and window["window"]
    assert all((row["collector"], row["window"]) == (window["collector"], window["window"]) for row in rows)

    reports = [row for row in rows if row["kind"] == "node"]
    assert nodes and len(reports) == len(nodes) and {row["node"] for row in reports} == nodes
    for row in reports:
        assert all(type(row[key]) is int for key in ("first", "last", "gaps", "lost"))
        assert row["first"] <= start < stop <= row["last"] and row["gaps"] == row["lost"] == 0
    return window


def _witnesses(rows, window, nodes, cases, run, changed, assess):
    """Check the socket probe, nftables verdict and destination-side Hubble verdict."""
    by_case = {case["id"]: case for case in cases}
    observed = [row for row in rows if row["kind"] in {"router", "probe", "hubble"}]
    for row in observed:
        assert row["id"] in by_case
        case = by_case[row["id"]]
        assert all(row[key] == case[key] for key in ("source", "destination", "protocol", "port"))
        assert type(row["tick"]) is int and window["start"] <= row["tick"] < window["stop"]

    result = []
    for case in cases:
        case_id = case["id"]
        pair = [row for row in observed if row["id"] == case_id]
        router, probe, hubble = ([row for row in pair if row["kind"] == kind] for kind in ("router", "probe", "hubble"))
        assert len(probe) == 1, case_id
        expected = "deny" if changed and case_id == "echo" else case["service"]
        assert probe[0]["outcome"] == expected, case_id
        if case["router"] == "inapplicable":
            assert not router, case_id
        else:
            assert len(router) == 1 and router[0]["outcome"] == case["router"], case_id
            result.append({"case": case_id, "layer": "router", "verdict": router[0]["outcome"], "ref": router[0]["evidence"]})

        # Router drops never enter Cilium. A completed sweep makes that absence check meaningful.
        if case["router"] == "deny":
            assert not hubble, case_id
            continue

        assert len(hubble) == 1 and hubble[0]["outcome"] == expected and hubble[0]["node"] in nodes, case_id
        scope = {**case, "run": run, "expected": case["service"]}
        service = [{**row, "witness": row["kind"], "ref": row["evidence"]} for row in (probe[0], hubble[0])]
        state = "disagreement" if changed and case_id == "echo" else "confirmed"
        assert assess(scope, service) == (state, (probe[0]["evidence"], hubble[0]["evidence"])), case_id
        result.append({"case": case_id, "layer": "service", "verdict": hubble[0]["outcome"], "ref": hubble[0]["evidence"]})
    return result


@pytest.mark.cluster
def test_live_network_pairs(monkeypatch):
    """Use network.json expectations and the existing recorder and Hubble window contracts."""
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    assert run.isdecimal() and attempt.isdecimal(), "Requires the real disposable workflow run"
    events, nodes = _recorded_network(run, attempt)
    cases = fixture("network")["cases"]
    assess = entry(monkeypatch, "flow_evidence", "assess")
    findings = entry(monkeypatch, "isolation_findings", "findings")

    assert events and all(
        row["run"] == run and row["attempt"] == attempt and row["feature"] == "network"
        and row["evidence"] and row["observed_at"]
        and row["kind"] in {"window", "node", "policy", "router", "probe", "hubble"}
        for row in events
    )
    assert len({row["evidence"] for row in events}) == len(events)
    assert {row["phase"] for row in events} == {"baseline", "changed"}
    service_grants = {case["id"] for case in cases if case["service"] == "allow"}
    # A router-blocked case has no service-layer witness in this topology.
    comparable = [
        {**case, "service": "inapplicable"} if case["router"] == "deny" else case
        for case in cases
    ]

    windows, policies = [], []
    for phase in ("baseline", "changed"):
        changed = phase == "changed"
        rows = [row for row in events if row["phase"] == phase]
        window = _window(rows, nodes)
        windows.append(window)
        policy = [row for row in rows if row["kind"] == "policy"]
        assert len(policy) == 1
        policy = policy[0]
        assert policy["uid"] and type(policy["generation"]) is int and policy["generation"] > 0
        assert type(policy["tick"]) is int and policy["tick"] <= window["start"]
        assert set(policy["allowed"]) == (service_grants - {"echo"} if changed else service_grants)
        policies.append(policy)

        witnesses = _witnesses(rows, window, nodes, cases, run, changed, assess)
        expected = []
        if changed:
            echo = next(row for row in witnesses if row["case"] == "echo" and row["layer"] == "service")
            expected = [{"case": "echo", "layer": "service", "expected": "allow",
                         "observed": "deny", "evidence": echo["ref"]}]
        assert findings(comparable, witnesses) == expected

    baseline, changed = windows
    assert baseline["window"] != changed["window"] and baseline["stop"] <= changed["start"]
    before, after = policies
    assert before["uid"] == after["uid"] and before["generation"] < after["generation"]
    assert baseline["stop"] <= after["tick"]
