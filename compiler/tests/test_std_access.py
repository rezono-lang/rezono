"""The shared extension declares rights, while only a consumer's clauses grant them (S28, O8)."""

import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, REPO
from rezono_compiler import modules, pack
from rezono_compiler import rules as ir


STD = REPO / "packs" / "std-access"


def _imported_std_access_program(tmp_path: Path):
    """Compile a minimal consumer importing live packs/std-access to inspect its declared relations and rules."""
    d = Path(shutil.copytree(FIXTURE, tmp_path / "std-access-probe"))
    f = d / "pack.yaml"
    meta = yaml.safe_load(f.read_text(encoding="utf-8"))
    meta["imports"] = [{"name": "std-access", "path": str(STD), "sha256": modules.pack_hash(STD)}]
    f.write_text(yaml.safe_dump(meta), encoding="utf-8")
    return ir.load(pack.read(d).rules)


def test_standard_access_declares_no_grants(tmp_path):
    prog = _imported_std_access_program(tmp_path)
    assert prog.rules == {}
    declared = {name: rel for name, rel in prog.relations.items() if rel.role != "base"}
    assert "may_read" in declared
    assert all(rel.extend is True and rel.closes is None and rel.explain != "fold" for rel in declared.values())
    assert [(col.name, col.type) for col in declared["may_read"].key] == [
        ("role", "string"), ("kind", "string"), ("element", "string")]


class MissingRightDeclarations(AssertionError):
    """std-access does not declare the rights to propose, review, publish and execute as the decision gives."""


def test_standard_access_declares_the_four_rights(tmp_path):
    prog = _imported_std_access_program(tmp_path)
    got = {
        name: [(col.name, col.type) for col in rel.key]
        for name, rel in prog.relations.items()
        if rel.role != "base"
    }
    want = {
        "may_propose": [("role", "string"), ("kind", "string"), ("element", "string")],
        "may_review": [("role", "string"), ("kind", "string"), ("element", "string")],
        "may_publish": [("role", "string"), ("kind", "string")],
        "may_execute": [("role", "string"), ("plugin", "string")],
    }
    wrong = {name: got.get(name) for name, columns in want.items() if got.get(name) != columns}
    if wrong:
        raise MissingRightDeclarations(f"declared otherwise or not at all: {wrong}")


def test_importing_the_standard_pack_grants_nothing(tmp_path):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "consumer"))
    f = d / "pack.yaml"
    meta = yaml.safe_load(f.read_text())
    meta["imports"] = [{"name": "std-access", "path": str(STD), "sha256": modules.pack_hash(STD)}]
    f.write_text(yaml.safe_dump(meta))
    assert ir.load(pack.read(d).rules).rules == {}
    (d / "rules").mkdir()
    (d / "rules" / "access.dl").write_text(
        '.decl may_read(role: symbol, kind: symbol, element: symbol)\n'
        'may_read("reader", "alpha", x) :- alpha(x).\n')
    p = ir.load(pack.read(d).rules)
    assert len(p.rules) == 1
    assert p.rules["may_read"].head.terms == ("reader", "alpha", "?x")
    assert p.rules["may_read"].module == "import_std_access_access"
