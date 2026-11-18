"""The dedicated workflow owns one runner-local cluster for the full marked suite."""

import re

import pytest
import yaml

from cluster_scenarios import WORKFLOW


def test_cluster_workflow():
    config = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(config["on"]) == {"workflow_dispatch", "workflow_call"}
    assert config["permissions"] == {"contents": "read"}
    ci = yaml.load(WORKFLOW.with_name("ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    [caller] = [job for job in ci["jobs"].values() if job.get("uses") == "./.github/workflows/disposable-cluster.yml"]
    assert "cluster_mode == 'tasks'" in caller["if"] and "cluster_mode == 'suite'" in caller["if"]
    assert caller["with"]["tasks"] == "${{ needs.discover.outputs.cluster_tasks }}"
    jobs = list(config["jobs"].values())
    owners = [job for job in jobs if any("kind create cluster" in s.get("run", "") for s in job["steps"])]
    assert len(owners) == 1
    job = owners[0]
    assert job["runs-on"].startswith("ubuntu-") and "matrix" not in job.get("strategy", {})
    steps = job["steps"]
    runs = [step.get("run", "") for step in steps]
    def exactly_one(needle):
        matches = [index for index, script in enumerate(runs) if needle in script]
        assert len(matches) == 1, (needle, matches)
        return matches[0]
    create = exactly_one("kind create cluster")
    install = exactly_one("loop/cluster/cilium-values.yaml")
    ready = exactly_one("cilium status --wait")
    select = exactly_one("loop/cluster/select_tests.py")
    delete = exactly_one("kind delete cluster")
    assert create < install <= ready < select < delete
    assert "loop/cluster/kind.yaml" in runs[create]
    assert "rezono-fixture" in runs[create] and "rezono-fixture" in runs[delete]
    assert "--kubeconfig" in runs[create] and "RUNNER_TEMP" in runs[create]
    assert "--version" in runs[install] and "always()" in steps[delete]["if"]
    for step in steps:
        if "uses" in step and not step["uses"].startswith("./"):
            assert re.fullmatch(r".+@[0-9a-f]{40}", step["uses"])
