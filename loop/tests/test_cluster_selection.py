"""Discover real pytest items across directories with independent local imports."""

import pytest

from cluster_scenarios import CLUSTER, command, component, plugin_environment


@pytest.mark.xfail(strict=True, reason="Read decisions/shared-disposable-cluster.md. Waits for test_cluster_marker. Implement loop/cluster/select_tests.py and discover test components across the supplied root. Preserve collection errors and reject globally empty selections.")
def test_cluster_selection(tmp_path):
    a = component(tmp_path, "alpha", """import pytest
pytestmark = pytest.mark.cluster
def test_alpha(): pass
""")
    b = component(tmp_path, "nested/beta", """import pytest
@pytest.mark.parametrize("value", [pytest.param(1, marks=pytest.mark.cluster, id="wanted"), pytest.param(2, id="ordinary")])
def test_beta(value): pass
""")
    component(tmp_path, "plain", "def test_other(): pass\n")
    env = plugin_environment()
    args = [CLUSTER / "select_tests.py", "--root", tmp_path, "--collect-only"]
    both = command(args, tmp_path, env)
    assert both.returncode == 0, both.stdout + both.stderr
    assert "::test_alpha" in both.stdout and "::test_beta[wanted]" in both.stdout
    assert "::test_other" not in both.stdout and "::test_beta[ordinary]" not in both.stdout
    a.write_text("broken = )\n", encoding="utf-8")
    broken = command(args, tmp_path, env)
    assert broken.returncode != 0
    assert "SyntaxError" in broken.stdout + broken.stderr
    a.unlink()
    b.write_text("def test_plain(): pass\n", encoding="utf-8")
    assert command(args, tmp_path, env).returncode != 0
