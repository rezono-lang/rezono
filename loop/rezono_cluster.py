"""Select disposable-cluster tests and report them safely on ordinary CI runners."""

import pytest


CLUSTER_SKIP_REASON = "Requires the dedicated disposable cluster"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--rezono-cluster", action="store_true", help="Enable tests marked cluster")
    parser.addoption("--rezono-report-cluster", action="store_true",
                     help="Include cluster tests as explicit skips without running their fixtures")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "cluster: requires the disposable cluster fixture")
    if config.getoption("--rezono-cluster") and config.getoption("--rezono-report-cluster"):
        raise pytest.UsageError("Choose either live cluster execution or reporting")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--rezono-cluster"):
        return

    if config.getoption("--rezono-report-cluster"):
        for item in items:
            if item.get_closest_marker("cluster") is not None:
                item.add_marker(pytest.mark.skipif(True, reason=CLUSTER_SKIP_REASON), append=False)
        return

    ordinary, cluster = [], []
    for item in items:
        (cluster if item.get_closest_marker("cluster") is not None else ordinary).append(item)
    if cluster:
        items[:] = ordinary
        config.hook.pytest_deselected(items=cluster)
