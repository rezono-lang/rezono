import pytest

from case_support import exact, reference


def test_cluster_fleet():
    rows = reference()
    for name in ['cluster_fleet_member']:
        exact(name, rows[name])
