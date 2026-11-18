import pytest

from case_support import exact, reference


def test_cluster_flow():
    rows = reference()
    for name in ['cluster_flow', 'cluster_firewall_rule', 'cluster_in_zone_policy']:
        exact(name, rows[name])
