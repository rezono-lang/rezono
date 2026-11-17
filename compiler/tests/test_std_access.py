"""The shared extension declares rights, while only a consumer's clauses grant them (S28, O8)."""

import shutil
from pathlib import Path

import yaml

from support import FIXTURE, REPO
from rezono_compiler import modules, pack
from rezono_compiler import rules as ir


STD = REPO / "packs" / "std-access"


def test_standard_access_declares_no_grants():
    from rezono_compiler.rules_dl import parse_file
    statements = parse_file((STD / "rules/access.dl").read_text(encoding="utf-8"), "rules/access.dl")
    assert len(statements) == 1 and statements[0][0:2] == ("decl", "may_read")
    assert statements[0][8] is True and statements[0][9] is None and statements[0][10] is False   # extend, no closes, no fold mark
    assert statements[0][2] == [
        ("role", "string"), ("kind", "string"), ("element", "string")]


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
