import os
import shutil
import sys
from pathlib import Path

import pytest

if os.environ.get("GITHUB_ACTIONS") == "true" and shutil.which("souffle") is None:
    raise RuntimeError("The CI oracle requires Souffle; check the pinned installer.")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# The example tests reuse the compiler's test helpers (compile, DuckDB, Feldera client).
sys.path.insert(0, str(ROOT / "compiler" / "tests"))

collect_ignore = []
if (ROOT / "blocked").is_dir():
    for _entry in sorted((ROOT / "blocked").iterdir()):
        if _entry.is_file():
            _target = _entry.read_text(encoding="utf-8").split(":", 1)[0].strip()
            if _target.startswith("examples/"):
                collect_ignore.append(_target[len("examples/"):])
collect_ignore_glob = list(collect_ignore)


@pytest.fixture(scope="session", autouse=True)
def shared_builds_directory(tmp_path_factory):
    """Where examples/shared_builds.py keeps what tests share. In CI the shard's worker processes share one
    directory (scripts/components.py sets it); a run without one gets its own, for this session alone."""
    from shared_builds import SHARED

    if os.environ.get(SHARED):
        yield Path(os.environ[SHARED])
        return
    os.environ[SHARED] = str(tmp_path_factory.mktemp("shared-builds"))
    try:
        yield Path(os.environ[SHARED])
    finally:
        del os.environ[SHARED]
