"""Added cluster tests run on the base source in the cluster workflow, like other added tests."""

import pytest

from cluster_scenarios import CLUSTER, WORKFLOW, command, component, plugin_environment


class MissingClusterBaseCheck(AssertionError):
    """No cluster step runs a pull request's added cluster tests on the base source."""


TESTS = """import pytest
def test_ordinary(): pass
@pytest.mark.cluster
def test_fails(): assert False
@pytest.mark.cluster
def test_passes(): pass
@pytest.mark.cluster
def test_skips():
    pytest.skip('no fixture here')
"""

CASES = [
    ([], 0),
    (["test_ordinary"], 0),
    (["test_fails"], 0),
    (["test_fails", "test_passes"], 0),
    (["test_passes"], 1),
    (["test_skips"], 1),
    (["test_fails", "test_skips"], 1),
    (["test_ordinary", "test_passes"], 1),
]


@pytest.mark.xfail(
    strict=True,
    raises=MissingClusterBaseCheck,
    reason=(
        "extra: decisions/cluster-test-evidence.md: section 2. Add loop/cluster/base_check.py [--root ROOT] "
        "SELECTION, which runs the cluster items of a selection file (one pytest node id per line, as "
        "scripts/red_before.py prepare writes it) with --rezono-cluster -m cluster and reads each outcome from "
        "a JUnit report: 0 without a cluster item or when one fails and none skips, 1 when one skips or all "
        "pass (counting a Skipped cluster test: report from loop/rezono_cluster.py as a skip, not as the base "
        "failing). .github/workflows/disposable-cluster.yml already calls loop/cluster/base_check.py on pull "
        "requests once it exists, so write only in loop/cluster/base_check.py."
    ),
)
def test_cluster_base_check(tmp_path):
    script = CLUSTER / "base_check.py"
    if not script.is_file():
        raise MissingClusterBaseCheck(f"{script.relative_to(CLUSTER.parents[1]).as_posix()} does not exist")
    if script.name not in WORKFLOW.read_text(encoding="utf-8"):
        raise MissingClusterBaseCheck("the cluster workflow does not run the base check")

    path = component(tmp_path, "alpha", TESTS)
    node = path.relative_to(tmp_path).as_posix()
    env = plugin_environment()
    selection = tmp_path / "selection.txt"
    for names, status in CASES:
        selection.write_text("".join(f"{node}::{name}\n" for name in names), encoding="utf-8")
        run = command([script, "--root", tmp_path, selection], tmp_path, env)
        assert run.returncode == status, (names, run.stdout + run.stderr)
