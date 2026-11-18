import pytest

from case_support import exact, reference


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on the common cluster schema and control-host task. Implement the flow relations in examples/platform/rules/cluster_flow.dl and matching module-local metadata. Read decisions/platform-derivation-acceptance.md.')
def test_cluster_flow():
    rows = reference()
    for name in ['cluster_flow', 'cluster_firewall_rule', 'cluster_in_zone_policy']:
        exact(name, rows[name])
