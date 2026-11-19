"""The build pack in the root is source: Git must not ignore a new file in it."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ignored(path):
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT)
    assert result.returncode in (0, 1), result
    return result.returncode == 0


def test_a_new_file_in_the_root_build_pack_is_not_ignored():
    assert (ROOT / "build" / "pack.yaml").is_file()
    assert not ignored("build/schema/new-kind.yaml")
    assert not ignored("build/rules/new.dl")


def test_build_output_elsewhere_stays_ignored():
    assert ignored("compiler/build/lib/out.py")
    assert ignored("viewer/build/index.html")
