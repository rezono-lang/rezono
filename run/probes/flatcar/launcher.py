"""Identify a single active launcher from KubeVirt and Kubernetes API objects."""
import json
import sys


def launcher(vmi, pods, uid, node):
    vm = vmi["metadata"]
    status = vmi["status"]
    if (vm["uid"] != uid or vm.get("deletionTimestamp") or status.get("nodeName") != node
            or status.get("phase") != "Running" or not any(
                item["type"] == "Ready" and item["status"] == "True"
                for item in status.get("conditions", []))):
        raise ValueError("expected the original Ready VMI on the trial node")
    # KubeVirt can report multiple active launchers during migration.
    active = [key for key, value in status.get("activePods", {}).items() if value == node]
    if len(active) != 1:
        raise ValueError(f"expected one active pod on the trial node, found {len(active)}")
    matches = []
    for pod in pods["items"]:
        meta, spec = pod["metadata"], pod["spec"]
        owners = meta.get("ownerReferences", [])
        if (meta["uid"] != active[0] or meta["namespace"] != vm["namespace"]
                or meta.get("deletionTimestamp") or spec.get("nodeName") != node
                or pod["status"].get("phase") != "Running" or not any(
                    owner.get("controller") is True and owner["uid"] == uid
                    and owner["name"] == vm["name"] and owner["kind"] == "VirtualMachineInstance"
                    and owner["apiVersion"] == "kubevirt.io/v1" for owner in owners)):
            continue
        containers = {item["name"] for item in spec["containers"]}
        sidecars = {item["name"] for item in spec.get("initContainers", [])
                    if item.get("restartPolicy") == "Always"}
        if "compute" in containers and "guest-console-log" in containers | sidecars:
            matches.append((meta["name"], meta["uid"]))
    if len(matches) != 1:
        raise ValueError(f"expected one matching running launcher, found {len(matches)}")
    return matches[0]


if __name__ == "__main__":
    with open(sys.argv[1]) as vmi_file, open(sys.argv[2]) as pod_file:
        try:
            print(*launcher(json.load(vmi_file), json.load(pod_file), *sys.argv[3:]))
        except ValueError as exc:
            sys.exit(str(exc))
