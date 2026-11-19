"""Standard pack names are reserved, from decisions/standard-pack-names.md.

A name `std-*` stands only for a standard pack of this repository: the bytes under `packs/<name>` at the
compiler's revision, identified by their pack hash. A pack cannot call itself `std-*`, and an import named
`std-*` must pin exactly those bytes. An ordinary name may carry any content.
"""

import shutil
from pathlib import Path

import pytest
import yaml
from rezono_compiler import modules
from rezono_compiler import pack as packs

ROOT = Path(__file__).resolve().parents[2]
MINIMAL = Path(__file__).resolve().parent / "fixtures/minimal"


def domain(tmp_path, name="domain", imports=()):
    root = tmp_path / name
    shutil.copytree(MINIMAL, root)
    meta = yaml.safe_load((root / "pack.yaml").read_text(encoding="utf-8"))
    meta["name"] = name
    meta["imports"] = [{"name": n, "path": f"../packs/{folder}", "sha256": modules.pack_hash(tmp_path / "packs" / folder)}
                       for n, folder in imports]
    (root / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    return root


def standard(tmp_path, name, folder=None, change=None):
    """A copy of the repository's standard pack `name` under tmp_path/packs/<folder>, optionally changed."""
    target = tmp_path / "packs" / (folder or name)
    shutil.copytree(ROOT / "packs" / name, target)
    if change:
        meta = yaml.safe_load((target / "pack.yaml").read_text(encoding="utf-8"))
        meta.update(change)
        (target / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    return target


def refused(root) -> str:
    try:
        packs.read(root)
    except packs.CompileError as error:
        return str(error)
    return ""


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="Reserve std-* pack names for the standard packs of packs/ at the compiler's revision, "
                          "identified by pack hash, as decisions/standard-pack-names.md fixes: refuse a pack that "
                          "calls itself std-*, and an import named std-* whose pin is not that standard pack's hash. "
                          "Compiler only. The protected relations themselves are "
                          "compiler/tests/test_verified_receipt_input.py and test_protected_admission_relations.py.")
def test_std_names_are_reserved_for_the_pinned_standard_packs(tmp_path):
    # Controls: the unchanged standard pack is accepted wherever it lies, and changed content under an
    # ordinary name is an ordinary pack.
    standard(tmp_path / "exact", "std-time")
    assert refused(domain(tmp_path / "exact", imports=[("std-time", "std-time")])) == ""
    standard(tmp_path / "renamed", "std-time", folder="my-time", change={"name": "my-time", "version": "9.9.9"})
    assert refused(domain(tmp_path / "renamed", imports=[("my-time", "my-time")])) == ""

    # A pack that calls itself std-*, also a standard name that does not exist yet.
    claimed = refused(domain(tmp_path / "self", name="std-completeness"))
    assert "std-completeness" in claimed, claimed

    # An import named std-time whose bytes are not the standard pack, pinned to their own hash.
    standard(tmp_path / "changed", "std-time", change={"version": "9.9.9"})
    changed = refused(domain(tmp_path / "changed", imports=[("std-time", "std-time")]))
    assert "std-time" in changed, changed

    # An import of a std-* name the repository does not have.
    standard(tmp_path / "unknown", "std-time", folder="std-fake", change={"name": "std-fake"})
    unknown = refused(domain(tmp_path / "unknown", imports=[("std-fake", "std-fake")]))
    assert "std-fake" in unknown, unknown
