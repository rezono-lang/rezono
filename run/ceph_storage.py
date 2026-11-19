"""Render the Rook CephCluster from derived Ceph devices, from decisions/run-cluster-shape.md."""

import json
import re

_NODE_NAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_IMAGE = re.compile(r".+@sha256:[0-9a-f]{64}")
_DISK_DIR = "/dev/disk/by-id/"


def _name(value, what):
    if not isinstance(value, str) or not _NODE_NAME.fullmatch(value):
        raise ValueError(f"{what} must be a DNS-1123 label")
    return value


def render(cluster, namespace, image, devices):
    """Return the canonical JSON CephCluster for `(cluster, machine, disk)` rows."""
    _name(cluster, "cluster")
    _name(namespace, "namespace")
    if not isinstance(image, str) or not _IMAGE.fullmatch(image):
        raise ValueError("the image must be pinned by @sha256: and 64 lowercase hexadecimal characters")
    rows = set()
    for row in devices:
        row_cluster, machine, disk = row
        if row_cluster != cluster:
            raise ValueError("device row belongs to another cluster")
        _name(machine, "node name")
        if not isinstance(disk, str) or not disk.startswith(_DISK_DIR) or len(disk) == len(_DISK_DIR):
            raise ValueError("a device must be a path under /dev/disk/by-id/")
        rows.add((machine, disk))
    if not rows:
        raise ValueError("at least one device is needed")
    nodes = [machine for machine, _ in rows]
    disks = [disk for _, disk in rows]
    if len(set(nodes)) != len(nodes):
        raise ValueError("a node has exactly one device")
    if len(set(disks)) != len(disks):
        raise ValueError("a device belongs to exactly one node")
    document = {
        "apiVersion": "ceph.rook.io/v1",
        "kind": "CephCluster",
        "metadata": {"name": cluster, "namespace": namespace},
        "spec": {
            "cephVersion": {"image": image},
            "dataDirHostPath": "/var/lib/rook",
            "mon": {"count": 3 if len(rows) >= 3 else 1, "allowMultiplePerNode": False},
            "storage": {
                "useAllNodes": False,
                "useAllDevices": False,
                "nodes": [{"name": machine, "devices": [{"name": disk}]} for machine, disk in sorted(rows)],
            },
        },
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
