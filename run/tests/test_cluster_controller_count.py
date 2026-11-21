"""Exact-1 controller requirement and undecided-inventory check in run/packs/cluster-shape and run/k0s_config.py.

Per decisions/code-does-not-decide.md and decisions/run-cluster-shape.md, a bounded run has exactly one
controller. The pack `run/packs/cluster-shape` must reject 0 controllers (including a controller order
line with quantity 0) and 2 controllers (whether from quantity 2 on one line or two controller lines),
and must report `unknown` with an explicit reason when a missing inventory row leaves the controller
count undecided, queried before `run/k0s_config.py:render()` is invoked.
"""

import json
from runpy import run_path

import pytest

from offline_cases import PLAN_HASH, RUN, relation

CLUSTER = "run-one"
OTHER_PLAN = "b" * 64


def _disk(name):
    return f"/dev/disk/by-id/wwn-0x5000000000000{name}"


def _machine(identifier, sku, address, plan=PLAN_HASH):
    return {
        "id": identifier,
        "plan_hash": [plan],
        "sku": [] if sku is None else [sku],
        "address": [address],
        "boot_disk": [_disk(f"{identifier[-1]}01")],
        "data_disk": [_disk(f"{identifier[-1]}02")],
    }


def _facts(observed, demand):
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
    for line in demand:
        rows["line"].append((line["id"],))
        rows["line__cluster"].append((line["id"], CLUSTER))
        for slot in ("sku", "role", "quantity"):
            if slot in line:
                rows[f"line__{slot}"].append((line["id"], line[slot]))
    for record in observed:
        rows["machine"].append((record["id"],))
        for slot in ("plan_hash", "sku", "address", "boot_disk", "data_disk"):
            rows[f"machine__{slot}"].extend((record["id"], value) for value in record[slot])
    return rows


def _shape(data):
    return {
        name: relation("cluster-shape", data, name)
        for name in ("member", "ceph_device", "api_address", "shape_problem")
    }


def _pack_reads(monkeypatch):
    """Record `(pack, relation, rows)` read through `rezono_compiler.batch.read`."""
    from rezono_compiler import batch

    reads = []
    original = batch.read

    def spy(connection, program, names=None):
        rows = original(connection, program, names)
        for name, values in rows.items():
            reads.append((program.pack, name, set(values)))
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return reads


def _latest_rows(reads, pack_name, relation_name):
    matches = [rows for pack, rel, rows in reads if (pack, rel) == (pack_name, relation_name)]
    assert matches, f"expected {(pack_name, relation_name)!r} to be read from batch.read; saw {reads!r}"
    return matches[-1]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/code-does-not-decide.md: Enforce the exact-1 controller requirement inside "
        "run/packs/cluster-shape/rules/cluster_shape.dl (per decisions/run-cluster-shape.md) rather than "
        "accepting quantity 0 or multiple controllers until run/k0s_config.py:render() fails. Reject 0 "
        "controllers (including a quantity-0 controller line) with shape_problem no_controller and 2 "
        "controllers with shape_problem multiple_controllers; export controller_count_status(cluster, "
        "status, reason) distinguishing ready/rejected/unknown when a missing inventory row leaves the "
        "controller count undecided; and expose controller_readiness(cluster, cluster_facts) in "
        "run/k0s_config.py querying controller_count_status before rendering."
    ),
)
def test_exact_one_controller_and_undecided_inventory_before_render(monkeypatch):
    from rezono_compiler import pack, rules

    workers = [
        _machine("m-a", "sku-small", "192.0.2.11"),
        _machine("m-b", "sku-small", "192.0.2.12"),
        _machine("m-x", "sku-small", "192.0.2.99", OTHER_PLAN),
    ]
    ctrl_one = _machine("m-c", "sku-large", "192.0.2.13")
    ctrl_two = _machine("m-d", "sku-large", "192.0.2.14")
    ctrl_alt = _machine("m-e", "sku-large-b", "192.0.2.15")

    # 1. Zero controllers with complete inventory: a quantity-0 controller line must NOT satisfy has_controller.
    zero_ctrl_facts = _facts(
        workers,
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 0},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    zero_shape = _shape(zero_ctrl_facts)
    assert zero_shape["shape_problem"] == {(CLUSTER, "no_controller")}
    assert zero_shape["member"] == zero_shape["ceph_device"] == zero_shape["api_address"] == set()

    # 2. One controller with complete inventory: valid cluster shape with a single controller.
    one_ctrl_facts = _facts(
        workers + [ctrl_one],
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    one_shape = _shape(one_ctrl_facts)
    assert one_shape["shape_problem"] == set()
    assert one_shape["member"] == {
        (CLUSTER, "m-a", "worker"),
        (CLUSTER, "m-b", "worker"),
        (CLUSTER, "m-c", "controller"),
    }
    assert one_shape["api_address"] == {(CLUSTER, "192.0.2.13")}

    # 3. Two controllers with complete inventory: rejected both for a single quantity-2 line and for two lines.
    two_ctrl_single_line = _facts(
        workers + [ctrl_one, ctrl_two],
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 2},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    two_ctrl_split_lines = _facts(
        workers + [ctrl_one, ctrl_alt],
        [
            {"id": "control-a", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "control-b", "sku": "sku-large-b", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    for label, data in (("quantity-2", two_ctrl_single_line), ("two-controller-lines", two_ctrl_split_lines)):
        two_shape = _shape(data)
        assert two_shape["shape_problem"] == {(CLUSTER, "multiple_controllers")}, label
        assert two_shape["member"] == two_shape["ceph_device"] == two_shape["api_address"] == set(), label

    # 4. Pre-render status relation and undecided missing-inventory-row cases.
    program = rules.load(pack.read(RUN / "packs" / "cluster-shape").rules)
    assert "controller_count_status" in program.derived(), (
        "run/packs/cluster-shape must derive controller_count_status(cluster, status, reason)"
    )

    module = run_path(str(RUN / "k0s_config.py"))
    assert "controller_readiness" in module, (
        "run/k0s_config.py must expose controller_readiness(cluster, cluster_facts) queried before render()"
    )
    controller_readiness = module["controller_readiness"]
    render = module["render"]

    reads = _pack_reads(monkeypatch)

    # Complete 1-controller inventory is ready and renders the canonical ClusterConfig.
    reads.clear()
    ready = controller_readiness(CLUSTER, one_ctrl_facts)
    assert ready == {
        "status": "ready",
        "reason": "exact_one",
        "controllers": [(CLUSTER, "m-c", "192.0.2.13")],
    }
    assert _latest_rows(reads, "cluster-shape", "controller_count_status") == {(CLUSTER, "ready", "exact_one")}
    rendered = json.loads(render(CLUSTER, ready["controllers"]))
    assert rendered["spec"]["api"] == {"address": "192.0.2.13", "sans": ["192.0.2.13"]}

    # Complete 0-controller and 2-controller inventories are explicitly rejected (known count != 1) before render.
    for expected_reason, data in (
        ("no_controller", zero_ctrl_facts),
        ("multiple_controllers", two_ctrl_single_line),
        ("multiple_controllers", two_ctrl_split_lines),
    ):
        reads.clear()
        rejected = controller_readiness(CLUSTER, data)
        assert rejected == {"status": "rejected", "reason": expected_reason, "controllers": []}
        assert _latest_rows(reads, "cluster-shape", "controller_count_status") == {
            (CLUSTER, "rejected", expected_reason)
        }

    # Missing inventory rows leave the controller count undecided (unknown with explicit reason) before render:
    # (a) the ordered controller machine row is absent from observed machines;
    missing_controller_machine = _facts(
        workers,
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    # (b) an observed plan machine is missing its machine__sku row so its role cannot be determined.
    missing_machine_sku = _facts(
        workers + [ctrl_one, _machine("m-u", None, "192.0.2.16")],
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    for label, data in (
        ("missing-controller-machine", missing_controller_machine),
        ("missing-machine-sku", missing_machine_sku),
    ):
        reads.clear()
        undecided = controller_readiness(CLUSTER, data)
        assert undecided["status"] == "unknown", (label, undecided)
        assert isinstance(undecided["reason"], str) and undecided["reason"].strip(), (label, undecided)
        assert undecided["controllers"] == [], (label, undecided)
        status_rows = _latest_rows(reads, "cluster-shape", "controller_count_status")
        assert {(cluster, status) for cluster, status, _ in status_rows} == {(CLUSTER, "unknown")}, (label, status_rows)
        assert undecided["reason"] in {reason for _, _, reason in status_rows}, (label, undecided, status_rows)
        assert _shape(data)["member"] == set(), label
        assert _shape(data)["api_address"] == set(), label
