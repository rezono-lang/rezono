"""Keep cluster fixture tests out of ordinary pytest runs."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--rezono-cluster", action="store_true", help="Enable tests marked cluster")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "cluster: requires the disposable cluster fixture")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--rezono-cluster"):
        return

    ordinary, cluster = [], []
    for item in items:
        (cluster if item.get_closest_marker("cluster") is not None else ordinary).append(item)
    if cluster:
        items[:] = ordinary
        config.hook.pytest_deselected(items=cluster)
