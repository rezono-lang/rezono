"""The standard pack table is the standard packs of this revision (decisions/standard-pack-names.md).

The table in rezono_compiler.standard_packs is generated from `packs/`. This test recomputes every pack hash
from the files, so a change to a `std-*` pack without a regenerated table fails here, and so does a standard
pack that was added or removed without one.
"""

import shutil
from pathlib import Path

from rezono_compiler import modules, standard_packs

ROOT = Path(__file__).resolve().parents[2]


def recomputed(root: Path) -> dict[str, str]:
    return {p.name: modules.pack_hash(p) for p in sorted((root / "packs").glob("std-*"))
            if (p / "pack.yaml").is_file()}


def test_the_table_is_the_standard_packs_of_this_revision():
    assert standard_packs.TABLE == recomputed(ROOT), (
        "Regenerate TABLE with: python -m rezono_compiler.standard_packs <repository root>")


def test_a_changed_standard_pack_no_longer_matches_the_table(tmp_path):
    shutil.copytree(ROOT / "packs" / "std-time", tmp_path / "packs" / "std-time")
    assert recomputed(tmp_path)["std-time"] == standard_packs.TABLE["std-time"]  # control: the copy is the pack
    pack_yaml = tmp_path / "packs" / "std-time" / "pack.yaml"
    pack_yaml.write_bytes(pack_yaml.read_bytes() + b"# one more line\n")
    assert recomputed(tmp_path)["std-time"] != standard_packs.TABLE["std-time"]
