"""Render the Rook CephCluster from derived Ceph devices, from decisions/run-cluster-shape.md."""

from functools import cache
import json
from pathlib import Path
import re

from rezono_compiler import batch, pack, rules

_NODE_NAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_IMAGE = re.compile(r".+@sha256:[0-9a-f]{64}")
_DISK_DIR = "/dev/disk/by-id/"
_POSITIVE_DECIMAL = re.compile(r"[1-9][0-9]*")
_CLUSTER_SHAPE_PACK = Path(__file__).resolve().parent / "packs" / "cluster-shape"


def _name(value, what):
    if not isinstance(value, str) or not _NODE_NAME.fullmatch(value):
        raise ValueError(f"{what} must be a DNS-1123 label")
    return value


@cache
def _cluster_shape_program():
    return rules.load(pack.read(_CLUSTER_SHAPE_PACK).rules)


def _derive_monitors(cluster, rows):
    facts = {
        "cluster": [(cluster,)],
        "cluster__plan_hash": [(cluster, "plan")],
        "line": [],
        "line__cluster": [],
        "line__sku": [],
        "line__role": [],
        "line__quantity": [],
        "machine": [],
        "machine__plan_hash": [],
        "machine__sku": [],
        "machine__address": [],
        "machine__boot_disk": [],
        "machine__data_disk": [],
    }
    for machine, disk in sorted(rows):
        facts["line"].append((machine,))
        facts["line__cluster"].append((machine, cluster))
        facts["line__sku"].append((machine, machine))
        facts["line__role"].append((machine, "controller"))
        facts["line__quantity"].append((machine, 1))
        facts["machine"].append((machine,))
        facts["machine__plan_hash"].append((machine, "plan"))
        facts["machine__sku"].append((machine, machine))
        facts["machine__address"].append((machine, machine))
        facts["machine__boot_disk"].append((machine, f"/dev/boot/{machine}"))
        facts["machine__data_disk"].append((machine, disk))
    program = _cluster_shape_program()
    connection = batch.connect(program, facts)
    try:
        batch.compute(connection, program)
        return batch.read(connection, program, ["ceph_monitor_count"])["ceph_monitor_count"]
    finally:
        connection.close()


def _parse_positive_count(value):
    if type(value) is int:
        if value > 0:
            return value
    elif isinstance(value, str) and _POSITIVE_DECIMAL.fullmatch(value):
        return int(value)
    raise ValueError("monitor count must be a positive integer")


def _monitor_count(cluster, monitors):
    if isinstance(monitors, (str, bytes)):
        raise ValueError("monitors must be a sequence of (cluster, count) rows")
    counts = set()
    for row in monitors:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError("monitor row must be a (cluster, count) pair")
        row_cluster, count = row
        if row_cluster != cluster:
            raise ValueError("monitor row belongs to another cluster")
        counts.add(_parse_positive_count(count))
    if len(counts) != 1:
        raise ValueError("cluster must have exactly one monitor count")
    return next(iter(counts))


def render(cluster, namespace, image, devices, monitors=None):
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
    derived_monitors = _derive_monitors(cluster, rows) if monitors is None else monitors
    count = _monitor_count(cluster, derived_monitors)
    document = {
        "apiVersion": "ceph.rook.io/v1",
        "kind": "CephCluster",
        "metadata": {"name": cluster, "namespace": namespace},
        "spec": {
            "cephVersion": {"image": image},
            "dataDirHostPath": "/var/lib/rook",
            "mon": {"count": count, "allowMultiplePerNode": False},
            "storage": {
                "useAllNodes": False,
                "useAllDevices": False,
                "nodes": [{"name": machine, "devices": [{"name": disk}]} for machine, disk in sorted(rows)],
            },
        },
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
