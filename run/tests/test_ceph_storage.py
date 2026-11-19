"""The Rook CephCluster from derived Ceph devices, from decisions/run-cluster-shape.md."""

import json

import pytest

from offline_cases import implementation


IMAGE = "quay.io/ceph/ceph@sha256:" + "0123456789abcdef" * 4


def disk(name):
    return f"/dev/disk/by-id/wwn-0x5000000000000{name}"


DEVICES = [("run-one", "m-b", disk("b02")), ("run-one", "m-c", disk("c02")), ("run-one", "m-a", disk("a02"))]


def canonical(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def expected(nodes, monitors):
    return canonical({
        "apiVersion": "ceph.rook.io/v1", "kind": "CephCluster",
        "metadata": {"name": "run-one", "namespace": "rook-ceph"},
        "spec": {
            "cephVersion": {"image": IMAGE},
            "dataDirHostPath": "/var/lib/rook",
            "mon": {"count": monitors, "allowMultiplePerNode": False},
            "storage": {"useAllNodes": False, "useAllDevices": False,
                        "nodes": [{"name": name, "devices": [{"name": disk(f"{name[-1]}02")}]} for name in nodes]},
        },
    })


def test_ceph_storage():
    render = implementation("ceph_storage.py", "render")
    assert render("run-one", "rook-ceph", IMAGE, DEVICES) == expected(["m-a", "m-b", "m-c"], 3)
    assert render("run-one", "rook-ceph", IMAGE, DEVICES + DEVICES[:1]) == expected(["m-a", "m-b", "m-c"], 3)
    assert render("run-one", "rook-ceph", IMAGE, DEVICES[:2]) == expected(["m-b", "m-c"], 1)
    assert render("run-one", "rook-ceph", IMAGE, DEVICES[2:]) == expected(["m-a"], 1)

    rejected = [
        ("quay.io/ceph/ceph:v19", DEVICES),
        (IMAGE, []),
        (IMAGE, DEVICES + [("run-one", "m-a", disk("a03"))]),
        (IMAGE, DEVICES + [("run-one", "m-d", disk("a02"))]),
        (IMAGE, [("run-one", "m-a", "/dev/nvme1n1")]),
        (IMAGE, [("run-two", "m-a", disk("a02"))]),
        (IMAGE, [("run-one", "M_A", disk("a02"))]),
    ]
    for image, rows in rejected:
        with pytest.raises(ValueError):
            render("run-one", "rook-ceph", image, rows)
