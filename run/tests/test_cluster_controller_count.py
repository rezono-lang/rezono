"""Exact-1 controller requirement and incomplete-inventory undecided check in run/packs/cluster-shape.

Per decisions/run-cluster-shape.md and decisions/code-does-not-decide.md, `run/k0s_config.py:render()`
is a pure converter over derived controller rows, and a bounded run has exactly one controller.
The pack `run/packs/cluster-shape` itself must:
- reject 0 controllers (including a `controller` order line with `quantity: 0`) via `shape_problem(..., "no_controller")`,
- accept 1 controller with complete inventory (producing one `api_address` row ready for `k0s_config.render()`),
- reject 2 controllers (whether from `quantity: 2` on one line or two `controller` lines) via `shape_problem`,
- leave the controller count undecided (`unknown` with explicit reason, never rendering or falsely claiming
  0 or 2 controllers) when an incomplete inventory observation leaves a plan machine's role undetermined.
"""

from __future__ import annotations

import json

import pytest

from offline_cases import PLAN_HASH, RUN, implementation, relation

CLUSTER = "run-one"
OTHER_PLAN = "b" * 64


def _disk(name: str) -> str:
    return f"/dev/disk/by-id/wwn-0x5000000000000{name}"


def _machine(identifier: str, sku: str | None, address: str, plan: str = PLAN_HASH) -> dict[str, object]:
    return {
        "id": identifier,
        "plan_hash": [plan],
        "sku": [] if sku is None else [sku],
        "address": [address],
        "boot_disk": [_disk(f"{identifier[-1]}01")],
        "data_disk": [_disk(f"{identifier[-1]}02")],
    }


def _facts(observed: list[dict[str, object]], demand: list[dict[str, object]]) -> dict[str, list[tuple]]:
    rows: dict[str, list[tuple]] = {
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


def _all_outputs(data: dict[str, list[tuple]]) -> dict[str, set[tuple[str, ...]]]:
    from rezono_compiler import batch, pack, rules

    program = rules.load(pack.read(RUN / "packs" / "cluster-shape").rules)
    connection = batch.connect(program, data)
    try:
        batch.compute(connection, program)
        return {name: set(rows) for name, rows in batch.read(connection, program).items()}
    finally:
        connection.close()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/code-does-not-decide.md: Enforce the exact-1 controller requirement inside "
        "run/packs/cluster-shape/rules/cluster_shape.dl (per decisions/run-cluster-shape.md) instead of "
        "accepting quantity 0 or multiple controllers until run/k0s_config.py:render() fails. Reject 0 "
        "controllers (including a quantity-0 controller line) with shape_problem no_controller and 2 "
        "controllers with a shape_problem (empty member and api_address), and derive an explicit "
        "unknown/undecided controller-count reason when an incomplete machine inventory observation "
        "leaves the controller count undetermined before rendering."
    ),
)
def test_exact_one_controller_and_undecided_inventory_before_render():
    render = implementation("k0s_config.py", "render")

    workers = [
        _machine("m-a", "sku-small", "192.0.2.11"),
        _machine("m-b", "sku-small", "192.0.2.12"),
        _machine("m-x", "sku-small", "192.0.2.99", OTHER_PLAN),
    ]
    ctrl_one = _machine("m-c", "sku-large", "192.0.2.13")
    ctrl_two = _machine("m-d", "sku-large", "192.0.2.14")
    ctrl_alt = _machine("m-e", "sku-large-b", "192.0.2.15")

    # 1. Zero controllers with complete inventory: a quantity-0 controller line must trigger no_controller.
    zero_ctrl_facts = _facts(
        workers,
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 0},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    zero_out = _all_outputs(zero_ctrl_facts)
    assert (CLUSTER, "no_controller") in zero_out["shape_problem"], zero_out["shape_problem"]
    assert zero_out["member"] == zero_out["ceph_device"] == zero_out["api_address"] == set()

    # 2. One controller with complete inventory: succeeds cleanly and feeds k0s_config.render().
    one_ctrl_facts = _facts(
        workers + [ctrl_one],
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    one_out = _all_outputs(one_ctrl_facts)
    assert one_out["shape_problem"] == set()
    assert one_out["member"] == {
        (CLUSTER, "m-a", "worker"),
        (CLUSTER, "m-b", "worker"),
        (CLUSTER, "m-c", "controller"),
    }
    assert one_out["api_address"] == {(CLUSTER, "192.0.2.13")}
    controllers = [
        (cluster, machine_id, address)
        for cluster, machine_id, role in sorted(one_out["member"])
        if role == "controller"
        for addr_cluster, address in sorted(one_out["api_address"])
        if addr_cluster == cluster
    ]
    rendered = json.loads(render(CLUSTER, controllers))
    assert rendered["spec"]["api"] == {"address": "192.0.2.13", "sans": ["192.0.2.13"]}

    # 3. Two controllers with complete inventory: rejected in cluster-shape before render().
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
        two_out = _all_outputs(data)
        problems = two_out["shape_problem"]
        assert problems, f"{label}: 2 controllers must produce a shape_problem, got empty set"
        assert (CLUSTER, "no_controller") not in problems, (label, problems)
        assert two_out["member"] == two_out["ceph_device"] == two_out["api_address"] == set(), label

    # 4. Incomplete inventory observation: an observed plan machine `m-u` is missing its `machine__sku`
    #    row alongside 1 known controller and 2 workers, so its role (second controller vs worker) is
    #    genuinely undetermined. Before render(), cluster-shape must withhold member/api_address, must
    #    not falsely claim 0 or 2 controllers, and must emit an explicit unknown/undecided reason.
    undecided_facts = _facts(
        workers + [ctrl_one, _machine("m-u", None, "192.0.2.16")],
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    undecided_out = _all_outputs(undecided_facts)
    assert undecided_out["member"] == set()
    assert undecided_out["api_address"] == set()
    assert (CLUSTER, "no_controller") not in undecided_out["shape_problem"]
    assert not any("multiple" in reason.lower() for _, reason in undecided_out["shape_problem"])

    # Contrast with a bad disk on a known worker (where controller count IS decided as 1):
    bad_worker_disk_facts = _facts(
        [
            _machine("m-a", "sku-small", "192.0.2.11"),
            dict(_machine("m-b", "sku-small", "192.0.2.12"), data_disk=[]),
            ctrl_one,
        ],
        [
            {"id": "control", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2},
        ],
    )
    bad_disk_out = _all_outputs(bad_worker_disk_facts)

    undecided_reasons = {
        cell
        for rel_name, rows in undecided_out.items()
        if rel_name not in {"member", "ceph_device", "api_address", "ceph_monitor_count"}
        for row in rows
        if CLUSTER in row
        for cell in row
        if isinstance(cell, str) and any(tok in cell.lower() for tok in ("unknown", "undecided", "incomplete"))
    }
    bad_disk_undecided_reasons = {
        cell
        for rel_name, rows in bad_disk_out.items()
        if rel_name not in {"member", "ceph_device", "api_address", "ceph_monitor_count"}
        for row in rows
        if CLUSTER in row
        for cell in row
        if isinstance(cell, str) and any(tok in cell.lower() for tok in ("unknown", "undecided", "incomplete"))
    }
    assert undecided_reasons, (
        f"incomplete machine inventory (missing machine__sku) must derive an explicit unknown/undecided "
        f"controller-count reason before render(); got {undecided_out!r}"
    )
    assert undecided_reasons != bad_disk_undecided_reasons, (
        "missing machine__sku (undecided controller count) must be distinguished from a bad disk on a known worker"
    )
    assert relation("cluster-shape", undecided_facts, "api_address") == set()
