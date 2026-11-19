"""Render the k0s cluster configuration for the single controller of a bounded run."""

import ipaddress
import json


def render(cluster, controllers):
    """Return the canonical JSON ClusterConfig for `(cluster, machine, address)` rows."""
    rows = set()
    for row in controllers:
        row_cluster, machine, address = row
        if row_cluster != cluster:
            raise ValueError("controller row belongs to another cluster")
        if not isinstance(machine, str) or not isinstance(address, str):
            raise ValueError("controller row needs a machine ID and an address")
        rows.add((machine, str(ipaddress.ip_address(address))))
    if len(rows) != 1:
        raise ValueError("a bounded run has exactly one controller")
    ((_, address),) = rows
    document = {
        "apiVersion": "k0s.k0sproject.io/v1beta1",
        "kind": "ClusterConfig",
        "metadata": {"name": cluster},
        "spec": {"api": {"address": address, "sans": [address]}, "network": {"provider": "custom"}},
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
