"""The independent migration comparison must run in its own pinned Julia job."""

from pathlib import Path

import pytest
import yaml


@pytest.mark.xfail(strict=True, reason="Wire the locked Catlab comparison into a post-merge GitHub job that also supports manual dispatch")
def test_catlab_workflow_runs_the_real_multiset_comparison():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / ".github/workflows/catlab-oracle.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    assert "main" in workflow["on"]["push"]["branches"]
    assert "workflow_dispatch" in workflow["on"]
    entry = "python compiler/tests/catlab/compare.py"
    assert any(entry in step.get("run", "").splitlines()
               for job in workflow["jobs"].values() for step in job["steps"])
