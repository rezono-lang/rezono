"""Cluster members, roles and Ceph devices from observed machines, from decisions/run-cluster-shape.md."""


from offline_cases import PLAN_HASH, relation

CLUSTER = "run-one"
OTHER_PLAN = "b" * 64


def disk(name):
    return f"/dev/disk/by-id/wwn-0x5000000000000{name}"


def machine(identifier, sku, address, plan=PLAN_HASH):
    return {"id": identifier, "plan_hash": [plan], "sku": [sku], "address": [address],
            "boot_disk": [disk(f"{identifier[-1]}01")], "data_disk": [disk(f"{identifier[-1]}02")]}


def machines():
    return [machine("m-a", "sku-small", "192.0.2.11"), machine("m-b", "sku-small", "192.0.2.12"),
            machine("m-c", "sku-large", "192.0.2.13"), machine("m-x", "sku-small", "192.0.2.99", OTHER_PLAN)]


def lines():
    return [{"id": "control", "sku": "sku-large", "role": "controller", "quantity": 1},
            {"id": "storage", "sku": "sku-small", "role": "worker", "quantity": 2}]


def facts(observed, demand):
    rows = {"cluster": [(CLUSTER,)], "cluster__plan_hash": [(CLUSTER, PLAN_HASH)],
            "line": [], "line__cluster": [], "line__sku": [], "line__role": [], "line__quantity": [],
            "machine": [], "machine__plan_hash": [], "machine__sku": [], "machine__address": [],
            "machine__boot_disk": [], "machine__data_disk": []}
    for line in demand:
        rows["line"].append((line["id"],))
        rows["line__cluster"].append((line["id"], CLUSTER))
        for slot in ("sku", "role", "quantity"):
            rows[f"line__{slot}"].append((line["id"], line[slot]))
    for record in observed:
        rows["machine"].append((record["id"],))
        for slot in ("plan_hash", "sku", "address", "boot_disk", "data_disk"):
            rows[f"machine__{slot}"].extend((record["id"], value) for value in record[slot])
    return rows


def shape(observed, demand):
    data = facts(observed, demand)
    return {name: relation("cluster-shape", data, name)
            for name in ("member", "ceph_device", "api_address", "shape_problem")}


def without(name):
    return [record for record in machines() if record["id"] != name]


def edited(name, **slots):
    return [dict(record, **slots) if record["id"] == name else record for record in machines()]


COUNTER_CASES = {
    "missing-worker": (without("m-b"), lines(), {"count"}),
    "missing-data-disk": (edited("m-b", data_disk=[]), lines(), {"invalid_machine", "count"}),
    "boot-is-data": (edited("m-b", data_disk=[disk("b01")]), lines(), {"invalid_machine", "count"}),
    "two-addresses": (edited("m-b", address=["192.0.2.12", "192.0.2.21"]), lines(), {"invalid_machine", "count"}),
    "shared-data-disk": (edited("m-b", data_disk=[disk("a02")]), lines(), {"invalid_machine", "count"}),
    "unassigned": (machines() + [machine("m-d", "sku-medium", "192.0.2.14")], lines(), {"unassigned"}),
    "surplus": (machines() + [machine("m-e", "sku-small", "192.0.2.15")], lines(), {"count"}),
    "ambiguous-line": (machines(), lines() + [{"id": "spare", "sku": "sku-small", "role": "worker", "quantity": 2}],
                       {"ambiguous_line"}),
    "no-controller": (machines(), [dict(line, role="worker") for line in lines()], {"no_controller"}),
}


def test_cluster_shape():
    result = shape(machines(), lines())
    assert result["member"] == {(CLUSTER, "m-a", "worker"), (CLUSTER, "m-b", "worker"),
                                (CLUSTER, "m-c", "controller")}
    assert result["ceph_device"] == {(CLUSTER, "m-a", disk("a02")), (CLUSTER, "m-b", disk("b02")),
                                     (CLUSTER, "m-c", disk("c02"))}
    assert result["api_address"] == {(CLUSTER, "192.0.2.13")}
    assert result["shape_problem"] == set()

    # Each ground is required: without it the cluster has no shape at all.
    for name, (observed, demand, reasons) in COUNTER_CASES.items():
        result = shape(observed, demand)
        assert result["shape_problem"] == {(CLUSTER, reason) for reason in reasons}, name
        assert result["member"] == result["ceph_device"] == result["api_address"] == set(), name
