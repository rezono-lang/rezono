import pytest

from case_support import exact, reference


def test_cluster_placement():
    rows = reference()
    for name in ['cluster_service_placement', 'cluster_endpoint_host', 'cluster_endpoint_zone']:
        exact(name, rows[name])
