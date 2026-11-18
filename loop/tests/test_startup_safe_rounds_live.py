"""Require independently read live startup boundaries on the runner-local fixture."""
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.cluster
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/safe-step-rounds.md. Run the startup through the shared disposable cluster's "
        "normal recorded path and compare live scoped readback after every visible transition. Waits for "
        "test_startup_transition_cases and the platform startup bindings, test_certified_round_replay, "
        "scoped policy/readback and the live recorder. "
        "Use the existing admission handoff and recorder, including the assigned worker workflow path."
    ),
)
def test_startup_safe_rounds_live():
    assert find_spec("loop.startup_rounds") is not None, "The live certified startup entry point is not wired"
    from loop.startup_rounds import run_startup

    kubeconfig = Path(os.environ["REZONO_CLUSTER_KUBECONFIG"]).resolve(strict=True)
    assert kubeconfig.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve(strict=True))
    assert kubeconfig.samefile(os.environ["REZONO_ADMISSION_TEST_KUBECONFIG"])
    command = ["kubectl", "--kubeconfig", str(kubeconfig), "--request-timeout=15s"]
    assert subprocess.check_output([*command, "config", "current-context"], text=True).strip() == "kind-rezono-fixture"
    command += ["--context", "kind-rezono-fixture"]
    run = f"safe-start-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"

    def namespace_names():
        raw = subprocess.check_output(
            [*command, "get", "namespaces", "-l", f"rezono.org/safe-start-run={run}", "-o", "json"],
            text=True, timeout=25,
        )
        return {item["metadata"]["name"] for item in json.loads(raw)["items"]}

    def read_boundary(reference):
        recorder = [*command, "-n", reference["namespace"]]
        job = json.loads(subprocess.check_output(
            [*recorder, "get", "job", reference["job"], "-o", "json"], text=True, timeout=25,
        ))
        uid = job["metadata"]["uid"]
        assert uid == reference["uid"] and job["status"]["succeeded"] == 1
        pods = json.loads(subprocess.check_output(
            [*recorder, "get", "pods", "-l", f"job-name={reference['job']}", "-o", "json"],
            text=True, timeout=25,
        ))["items"]
        name, = [pod["metadata"]["name"] for pod in pods if pod["status"]["phase"] == "Succeeded"
                 and any(owner["uid"] == uid and owner.get("controller")
                         for owner in pod["metadata"]["ownerReferences"])]
        lines = subprocess.check_output(
            [*recorder, "logs", name, "-c", "recorder"], text=True, timeout=25,
        ).splitlines()
        event, = [json.loads(line) for line in lines]
        assert event["receipt"] == reference["receipt"] and event["run"] == run
        return event

    assert not namespace_names()
    result = run_startup(kubeconfig, run)
    assert result["run"] == run and result["outcome"] == "success"
    assert set(result["managed_namespaces"]) == namespace_names() and namespace_names()
    references = result["boundaries"]
    jobs = json.loads(subprocess.check_output(
        [*command, "get", "jobs", "-A", "-l",
         f"rezono.org/safe-start-run={run},rezono.org/role=boundary-recorder", "-o", "json"],
        text=True, timeout=25,
    ))["items"]
    assert {reference["uid"] for reference in references} == {job["metadata"]["uid"] for job in jobs}
    observations = [read_boundary(reference) for reference in references]
    assert len(observations) > 1
    assert observations[0]["inventory_complete"] and observations[0]["managed_namespaces"] == []
    assert len({row["receipt"] for row in observations}) == len(observations)
    for visible in observations:
        assert visible["run"] == run and visible["inventory_complete"]
        assert set(visible["exposed_endpoints"]) <= set(visible["protected_endpoints"])
        assert visible["kind"] == "live_readback" and visible["certificate"]
    findings = {row["reason"] for row in result["findings"]}
    assert findings == {"prohibited-recovery-flow", "unsigned-component"}
    assert result["network_cases"] and all(case["probe"] and case["hubble_receipt"]
                                           for case in result["network_cases"])
