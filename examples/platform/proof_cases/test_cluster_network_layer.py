import pytest

from case_support import exact, reference
from stack_support import assert_host_witness, rebound


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Use the landed cluster_control_host relation in rules/cluster_network_stack.dl, with "
    "schema/cluster_network_stack.yaml and facts/cluster_network_stack.yaml. "
    "Read decisions/platform-derivation-acceptance.md."
))
def test_cluster_network_layer():
    name = "cluster_network_stack"
    rows = reference()
    exact(name, rows[name])
    hosts = dict(rows["cluster_control_host"])
    for row in rows[name]:
        assert_host_witness(name, row, "cluster_control_host", [row[0], hosts[row[0]]])

    changed = rebound(name, "network_stack_choice", policy="alternate-policy",
                      observation="alternate-observer")
    assert changed == {(cluster, "alternate-policy", "alternate-observer") for cluster in hosts}
