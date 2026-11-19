import pytest

from case_support import exact, reference
from stack_support import assert_host_witness, rebound


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Build on the cluster_worker_host rows and machine identities of the green test_cluster_worker_network. "
    "Implement rules/cluster_machine_stack.dl, schema/cluster_machine_stack.yaml and "
    "facts/cluster_machine_stack.yaml. Read decisions/platform-derivation-acceptance.md."
))
def test_cluster_machine_stack():
    name = "cluster_machine_stack"
    rows = reference()[name]
    exact(name, rows)
    for row in rows:
        assert_host_witness(name, row, "cluster_worker_host", row[1:3])

    changed = rebound(name, "machine_stack_choice", os="alternate-os", distribution="alternate-kubernetes")
    assert changed == {(node, owner, host, "alternate-os", "alternate-kubernetes", bootstrap)
                       for node, owner, host, _, _, bootstrap in rows}
