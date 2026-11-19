"""A cluster test that skips in a cluster run fails it, instead of passing silently."""

import pytest

from cluster_scenarios import CLUSTER, command, component, plugin_environment


class MissingClusterSkipFailure(AssertionError):
    """The cluster plugin still lets a skipped cluster item pass a cluster run."""


HEADER = """import pytest
pytestmark = pytest.mark.cluster
def test_runs(): pass
@pytest.mark.xfail(strict=True, reason="pending fixture work")
def test_pending(): assert False
"""

SKIPS = {
    "call": "def test_quiet():\n    pytest.skip('no fixture here')\n",
    "mark": "@pytest.mark.skipif(True, reason='no fixture here')\ndef test_quiet(): pass\n",
    "import": "def test_quiet():\n    pytest.importorskip('rezono_absent_module_for_this_test')\n",
}


@pytest.mark.xfail(
    strict=True,
    raises=MissingClusterSkipFailure,
    reason=(
        "M2: decisions/cluster-test-evidence.md: section 1. With --rezono-cluster, the plugin in "
        "loop/rezono_cluster.py reports a cluster item that ends as skipped (pytest.skip, a skipif mark or "
        "pytest.importorskip) as failed, with a failure text that starts with 'Skipped cluster test: '. "
        "A strict xfail that fails stays xfailed, and --rezono-report-cluster still skips. Write in "
        "loop/rezono_cluster.py. Today loop/cluster/select_tests.py exits 0 for a suite whose cluster test skips."
    ),
)
def test_cluster_skip_is_a_failure(tmp_path):
    path = component(tmp_path, "alpha", HEADER)
    env = plugin_environment()
    suite = [CLUSTER / "select_tests.py", "--root", tmp_path]

    clean = command(suite, tmp_path, env)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    for name, body in SKIPS.items():
        path.write_text(HEADER + body, encoding="utf-8")
        run = command(suite, tmp_path, env)
        out = run.stdout + run.stderr
        if run.returncode == 0:
            raise MissingClusterSkipFailure(f"a {name} skip passed the cluster suite:\n{out}")
        if "test_quiet" not in out or "Skipped cluster test: " not in out:
            raise MissingClusterSkipFailure(f"a {name} skip failed without naming the skipped test:\n{out}")
        assert "no fixture here" in out or name == "import", out

    report = command(["-m", "pytest", "-q", "-rA", "--rezono-report-cluster", path], tmp_path, env)
    assert report.returncode == 0, report.stdout + report.stderr
    assert "Skipped cluster test: " not in report.stdout + report.stderr
