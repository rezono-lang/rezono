"""Every file that defines a pack has the Git attribute `pack-definition` (.gitattributes).

The compiler hashes the bytes of the files in `modules.DEFINITION`, so a checkout that converts their line
endings would give the pack another hash. The attribute pins them to LF on every platform.
"""

import subprocess
from pathlib import Path

from rezono_compiler import modules

ROOT = Path(__file__).resolve().parents[2]
BASES = ("packs", "examples", "run/packs", "build")


def pack_dirs():
    return sorted({manifest.parent for base in BASES for manifest in (ROOT / base).rglob("pack.yaml")})


def test_every_pack_definition_file_has_the_attribute():
    dirs = pack_dirs()
    assert ROOT / "build" in dirs and ROOT / "run/packs/invoice-drift" in dirs
    files = sorted({path.relative_to(ROOT).as_posix() for folder in dirs for path in modules.definition_files(folder)})
    output = subprocess.run(["git", "check-attr", "pack-definition", "--", *files], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    values = dict(line.rsplit(": pack-definition: ", 1) for line in output.splitlines())
    assert set(values) == set(files)
    assert [path for path, value in values.items() if value != "set"] == []
