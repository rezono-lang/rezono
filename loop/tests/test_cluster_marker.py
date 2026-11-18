"""Marker registration and the opt-in work through normal pytest collection."""

import pytest

from cluster_scenarios import command, component, plugin_environment


def test_cluster_marker(tmp_path):
    path = component(tmp_path, "alpha", """import pytest
def test_ordinary(): pass
@pytest.mark.cluster
def test_fixture_api(): pass
""")
    (path.parents[1] / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = plugin_environment()
    args = ["-m", "pytest", "--strict-markers", "--collect-only", "-q", path]
    ordinary = command(args, tmp_path, env)
    assert ordinary.returncode == 0, ordinary.stderr
    assert "::test_ordinary" in ordinary.stdout and "::test_fixture_api" not in ordinary.stdout
    live = command([*args, "--rezono-cluster", "-m", "cluster"], tmp_path, env)
    assert live.returncode == 0, live.stderr
    assert "::test_fixture_api" in live.stdout and "::test_ordinary" not in live.stdout
    path.write_text("""import pytest
@pytest.mark.clustre
def test_typo(): pass
""", encoding="utf-8")
    typo = command(args, tmp_path, env)
    assert typo.returncode != 0 and "clustre" in (typo.stdout + typo.stderr)
