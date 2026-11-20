"""The shared extension declares rights, while only a consumer's clauses grant them (S28, O8)."""

import shutil
from pathlib import Path

import yaml

from support import FIXTURE, REPO
from rezono_compiler import modules, pack
from rezono_compiler import rules as ir


STD = REPO / "packs" / "std-access"


def test_standard_access_declares_no_grants():
    import souffle
    from rezono_compiler.rules_dl import parse_file

    texts = souffle.closure(STD)
    assert texts
    statements = [stmt for i, text in enumerate(texts) for stmt in parse_file(text, f"std-access:{i}")]
    assert all(stmt[0] == "decl" for stmt in statements)
    by_name = {stmt[1]: stmt for stmt in statements}
    assert "may_read" in by_name
    assert all(stmt[8] is True and stmt[9] is None and stmt[10] is False for stmt in statements)
    assert by_name["may_read"][2] == [
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
