"""Two synthetic test components for exercising the shared selector in isolation."""

import os
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[2]
CLUSTER = ROOT / "loop" / "cluster"
WORKFLOW = ROOT / ".github" / "workflows" / "disposable-cluster.yml"


def component(root, name, source):
    area = root / name / "tests"
    area.mkdir(parents=True)
    (area / "test_shared.py").write_text(source, encoding="utf-8")
    return area / "test_shared.py"


def plugin_environment():
    project = tomllib.loads((ROOT / "loop" / "pyproject.toml").read_text(encoding="utf-8"))
    plugin = project["project"]["entry-points"]["pytest11"]["rezono_cluster"]
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS=f"-p {plugin}")
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "loop"), env.get("PYTHONPATH", "")])
    return env


def command(args, root, env):
    return subprocess.run([sys.executable, *map(str, args)], cwd=root, env=env, text=True,
                          capture_output=True, timeout=60)
