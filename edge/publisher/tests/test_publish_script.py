"""deploy/profiles/edge/publish.sh: which commands it runs per pack.

The script runs in this checkout with a `python` on PATH that records every `-m` call and answers 0; a
`-c` call goes to the real interpreter. So this checks the script's own steps, not the publisher."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deploy/profiles/edge/publish.sh"
SH = shutil.which("sh")
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    SH is None or GIT is None or not (ROOT / ".git").exists(), reason="needs a POSIX shell and a Git checkout")

STUB = """#!/bin/sh
if [ "$1" = -m ]; then
  shift
  echo "$*" >> "$REDE_TEST_CALLS"
  exit 0
fi
exec "$REDE_TEST_PYTHON" "$@"
"""


def run(tmp_path: Path, **env: str) -> list[list[str]]:
    """The `python -m` calls of one run of publish.sh for one pack named `toy`, each as its arguments."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    stub = stubs / "python"
    stub.write_text(STUB, encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.yaml").write_text("name: toy\n", encoding="utf-8", newline="\n")
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    environment = {k: v for k, v in os.environ.items() if not k.startswith("REDE_")} | {
        "PATH": str(stubs) + os.pathsep + os.environ["PATH"],
        "REDE_TEST_CALLS": calls.as_posix(), "REDE_TEST_PYTHON": Path(sys.executable).as_posix(),
        "REDE_STORE": "file:///nowhere"} | env
    subprocess.run([SH, SCRIPT.as_posix(), pack.as_posix()], cwd=ROOT, env=environment, check=True,
                   capture_output=True, text=True)
    return [line.split() for line in calls.read_text(encoding="utf-8").splitlines()]


def test_an_ordinary_publish_runs_no_backfill(tmp_path):
    # RV-M15: the backfill reads every manifest of the pack, so its time grows with every epoch.
    calls = run(tmp_path)
    assert [c[0] for c in calls] == ["rede_publisher"]
    assert "--views" in calls[0] and calls[0][calls[0].index("--store") + 1] == "file:///nowhere"
    # RV-K16 revised: the forms follow the publication (job `forms`); here the build only names their library.
    assert "--forms-after" in calls[0] and "--forms" not in calls[0]


def test_the_publish_path_has_no_backfill(tmp_path):
    # RV-M10: the backfill is a tool, never a step of a publication, whatever the environment says.
    assert [c[0] for c in run(tmp_path, REDE_BACKFILL="1")] == ["rede_publisher"]
