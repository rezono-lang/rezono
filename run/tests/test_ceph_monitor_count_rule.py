"""Ceph monitor quorum count is a cluster-shape row: decisions/code-does-not-decide.md.

The expectation is the behaviour of run/ceph_storage.py under decisions/run-cluster-shape.md:
the monitor count is 3 with three or more nodes and 1 otherwise, and a cluster with a shape
problem derives no monitor count.
"""
import ast
import json

import pytest

from offline_cases import PLAN_HASH, RUN, implementation, relation

CLUSTER = "run-one"
IMAGE = "quay.io/ceph/ceph@sha256:" + "0123456789abcdef" * 4


def disk(name):
    return f"/dev/disk/by-id/wwn-0x5000000000000{name}"


def cluster_facts(node_count, *, with_controller=True):
    rows = {
        "cluster": [(CLUSTER,)],
        "cluster__plan_hash": [(CLUSTER, PLAN_HASH)],
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
    if with_controller:
        rows["line"].append(("control",))
        rows["line__cluster"].append(("control", CLUSTER))
        rows["line__sku"].append(("control", "sku-control"))
        rows["line__role"].append(("control", "controller"))
        rows["line__quantity"].append(("control", 1))
        workers = node_count - 1
    else:
        workers = node_count
    if workers:
        rows["line"].append(("storage",))
        rows["line__cluster"].append(("storage", CLUSTER))
        rows["line__sku"].append(("storage", "sku-worker"))
        rows["line__role"].append(("storage", "worker"))
        rows["line__quantity"].append(("storage", workers))

    for index in range(node_count):
        tag = chr(ord("a") + index)
        machine = f"m-{tag}"
        sku = "sku-control" if with_controller and index == 0 else "sku-worker"
        rows["machine"].append((machine,))
        rows["machine__plan_hash"].append((machine, PLAN_HASH))
        rows["machine__sku"].append((machine, sku))
        rows["machine__address"].append((machine, f"192.0.2.{11 + index}"))
        rows["machine__boot_disk"].append((machine, disk(f"{tag}01")))
        rows["machine__data_disk"].append((machine, disk(f"{tag}02")))
    return rows


def int_literals(name):
    tree = ast.parse((RUN / name).read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is int
    }


def pack_reads(monkeypatch):
    """The (pack, relation) pairs whose derived rows the code reads."""
    from rezono_compiler import batch

    seen = set()
    read = batch.read

    def spy(con, prog, names=None):
        rows = read(con, prog, names)
        seen.update((prog.pack, name) for name in rows)
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return seen


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/code-does-not-decide.md, row run/ceph_storage.py. Derive "
        "ceph_monitor_count(cluster, count) in run/packs/cluster-shape: 3 when a valid cluster has "
        "three or more ceph_device rows, 1 when it has one or two, and no row when the cluster has "
        "a shape_problem (keep candidate/cluster_shape.{rezono,json} in sync so "
        "compiler/tests/rezono/test_whole_run_cluster_shape.py stays green). Update "
        "run/ceph_storage.py:render(cluster, namespace, image, devices, monitors=None) to consume "
        "derived (cluster, count) monitor rows (where count is a positive integer or canonical "
        "decimal text from rezono_compiler.batch.read) without deciding the quorum count in Python, "
        "and when monitors is omitted to read ceph_monitor_count from run/packs/cluster-shape "
        "through rezono_compiler.batch.read. Keep run/tests/test_ceph_storage.py and "
        "run/tests/test_cluster_shape.py green. Today run/packs/cluster-shape does not derive "
        "ceph_monitor_count and run/ceph_storage.py hardcodes 3 in Python (AssertionError)."
    ),
)
def test_ceph_monitor_count_comes_from_cluster_shape(monkeypatch):
    from rezono_compiler import pack, rules

    program = rules.load(pack.read(RUN / "packs" / "cluster-shape").rules)
    assert "ceph_monitor_count" in program.derived(), "run/packs/cluster-shape does not derive ceph_monitor_count"
    assert 3 not in int_literals("ceph_storage.py"), "the quorum threshold 3 is still written in code, not in the pack"

    for node_count, expected_count in [(1, "1"), (2, "1"), (3, "3"), (4, "3")]:
        data = cluster_facts(node_count)
        assert relation("cluster-shape", data, "shape_problem") == set()
        assert relation("cluster-shape", data, "ceph_monitor_count") == {(CLUSTER, expected_count)}

    broken = cluster_facts(3, with_controller=False)
    assert relation("cluster-shape", broken, "shape_problem") == {(CLUSTER, "no_controller")}
    assert relation("cluster-shape", broken, "ceph_monitor_count") == set()

    render = implementation("ceph_storage.py", "render")
    for node_count, expected_count in [(1, 1), (2, 1), (3, 3), (4, 3)]:
        data = cluster_facts(node_count)
        devices = sorted(relation("cluster-shape", data, "ceph_device"))
        monitors = relation("cluster-shape", data, "ceph_monitor_count")
        rendered = json.loads(render(CLUSTER, "rook-ceph", IMAGE, devices, monitors=monitors))
        assert rendered["spec"]["mon"]["count"] == expected_count

    # Supplying derived monitor rows directly must be honoured without recomputing from device count.
    two_devices = sorted(relation("cluster-shape", cluster_facts(2), "ceph_device"))
    rendered = json.loads(render(CLUSTER, "rook-ceph", IMAGE, two_devices, monitors=[(CLUSTER, "5")]))
    assert rendered["spec"]["mon"]["count"] == 5

    for bad_monitors in [[], [("other-cluster", "3")], [(CLUSTER, "1"), (CLUSTER, "3")], [(CLUSTER, "0")]]:
        with pytest.raises(ValueError):
            render(CLUSTER, "rook-ceph", IMAGE, two_devices, monitors=bad_monitors)

    seen = pack_reads(monkeypatch)
    three_devices = sorted(relation("cluster-shape", cluster_facts(3), "ceph_device"))
    assert json.loads(render(CLUSTER, "rook-ceph", IMAGE, three_devices))["spec"]["mon"]["count"] == 3
    assert json.loads(render(CLUSTER, "rook-ceph", IMAGE, two_devices))["spec"]["mon"]["count"] == 1
    assert ("cluster-shape", "ceph_monitor_count") in seen, sorted(seen)
