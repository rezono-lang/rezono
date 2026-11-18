"""Offline evidence for the host trial's launcher identity checks."""
import copy
import runpy
from pathlib import Path

import pytest

launcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / "probes/flatcar/launcher.py"))["launcher"]
VM = "00000000-0000-4000-8000-000000000001"
POD = "00000000-0000-4000-8000-000000000002"
NODE = "proof-worker"
VMI = {"metadata": {"uid": VM, "name": "host-probe", "namespace": "default"},
       "status": {"nodeName": NODE, "phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
                  "activePods": {POD: NODE}}}
LAUNCHER = {"metadata": {"uid": POD, "name": "virt-launcher-host-probe-abcde", "namespace": "default",
                        "ownerReferences": [{"kind": "VirtualMachineInstance", "apiVersion": "kubevirt.io/v1",
                                             "name": "host-probe", "uid": VM, "controller": True}]},
            "spec": {"nodeName": NODE, "containers": [{"name": "compute"}],
                     "initContainers": [{"name": "guest-console-log", "restartPolicy": "Always"}]},
            "status": {"phase": "Running", "containerStatuses": [
                {"name": "compute", "containerID": "containerd://abc", "state": {"running": {}}}]}}


def test_current_launcher_with_stale_predecessor():
    old = copy.deepcopy(LAUNCHER)
    old["metadata"]["uid"] = "old"
    assert launcher(VMI, {"items": [old, LAUNCHER]}, VM, NODE) == (LAUNCHER["metadata"]["name"], POD, "containerd://abc")


@pytest.mark.parametrize("case", ["empty", "wrong_owner", "old_uid", "wrong_node", "terminating",
                                  "no_console", "no_compute_id", "two_active", "wrong_vmi", "not_ready", "not_running"])
def test_unconfirmed_launcher_is_rejected(case):
    vm, pod = copy.deepcopy(VMI), copy.deepcopy(LAUNCHER)
    if case == "wrong_owner":
        pod["metadata"]["ownerReferences"][0]["uid"] = "other"
    elif case == "old_uid":
        pod["metadata"]["uid"] = "old"
    elif case == "wrong_node":
        pod["spec"]["nodeName"] = "other"
    elif case == "terminating":
        pod["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    elif case == "no_console":
        pod["spec"]["initContainers"] = []
    elif case == "no_compute_id":
        pod["status"]["containerStatuses"][0].pop("containerID")
    elif case == "two_active":
        vm["status"]["activePods"]["other"] = NODE
    elif case == "wrong_vmi":
        vm["metadata"]["uid"] = "replacement"
    elif case == "not_ready":
        vm["status"]["conditions"][0]["status"] = "False"
    elif case == "not_running":
        vm["status"]["phase"] = "Failed"
    with pytest.raises(ValueError):
        launcher(vm, {"items": [] if case == "empty" else [pod]}, VM, NODE)
