import pytest

from case_support import exact, reference


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on the common cluster schema and control-host task. Implement the network_layer relations in examples/platform/rules/cluster_network_layer.dl and matching module-local metadata. Read decisions/platform-derivation-acceptance.md.')
def test_cluster_network_layer():
    rows = reference()
    for name in ['cluster_network_stack', 'cluster_machine_stack']:
        exact(name, rows[name])
