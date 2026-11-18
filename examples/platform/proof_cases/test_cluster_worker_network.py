import pytest

from case_support import exact, reference


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on the common cluster schema and control-host task. Implement the worker_network relations in examples/platform/rules/cluster_worker_network.dl and matching module-local metadata. Read decisions/platform-derivation-acceptance.md.')
def test_cluster_worker_network():
    rows = reference()
    for name in ['cluster_worker_host', 'cluster_worker_interface', 'cluster_endpoint_network']:
        exact(name, rows[name])
