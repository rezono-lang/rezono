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
        "pass. Call it in .github/workflows/disposable-cluster.yml on pull requests, after the candidate's "
        "cluster run, on the base with the pull request's protected paths laid over it. Waits for "
        "test_cluster_skip_is_a_failure, whose skip report this check must not count as the base failing. "
        "Blocked on planner review: .github/workflows/disposable-cluster.yml is in POLICY in scripts/red_guard.py, "
        "so a worker PR cannot edit it and red_guard.py forbids lifting a red mark alongside a POLICY change; "
        "a planner PR must update .github/workflows/disposable-cluster.yml first."
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
