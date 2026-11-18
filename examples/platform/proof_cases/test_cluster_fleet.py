import pytest

from case_support import exact, reference


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on the common cluster schema and control-host task. Implement the fleet relations in examples/platform/rules/cluster_fleet.dl and matching module-local metadata. Read decisions/platform-derivation-acceptance.md.')
def test_cluster_fleet():
    rows = reference()
    for name in ['cluster_fleet_member']:
        exact(name, rows[name])
