import pytest

from case_support import exact, reference


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on the common cluster schema and control-host task. Implement the placement relations in examples/platform/rules/cluster_placement.dl and matching module-local metadata. Read decisions/platform-derivation-acceptance.md.')
def test_cluster_placement():
    rows = reference()
    for name in ['cluster_service_placement', 'cluster_endpoint_host', 'cluster_endpoint_zone']:
        exact(name, rows[name])
