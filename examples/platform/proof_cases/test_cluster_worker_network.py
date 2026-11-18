import pytest

from case_support import exact, reference


def test_cluster_worker_network():
    rows = reference()
    for name in ['cluster_worker_host', 'cluster_worker_interface', 'cluster_endpoint_network']:
        exact(name, rows[name])
