import pytest

from case_support import exact, reference
from stack_support import assert_host_witness, rebound


def test_cluster_machine_stack():
    name = "cluster_machine_stack"
    rows = reference()[name]
    exact(name, rows)
    for row in rows:
        assert_host_witness(name, row, "cluster_worker_host", row[1:3])

    changed = rebound(name, "machine_stack_choice", os="alternate-os", distribution="alternate-kubernetes")
    assert changed == {(node, owner, host, "alternate-os", "alternate-kubernetes", bootstrap)
                       for node, owner, host, _, _, bootstrap in rows}
