"""The shared extension declares rights, while only a consumer's clauses grant them (S28, O8)."""

import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, REPO
from rezono_compiler import modules, pack
from rezono_compiler import rules as ir


STD = REPO / "packs" / "std-access"


def declarations():
    from rezono_compiler.rules_dl import parse_file
    statements = []
    for f in sorted((STD / "rules").glob("*.dl")):
        statements += parse_file(f.read_text(encoding="utf-8"), f"rules/{f.name}")
    return statements


def test_standard_access_declares_no_grants():
    statements = declarations()
    assert statements and all(s[0] == "decl" for s in statements)    # declarations only, not a single clause
    for s in statements:
        assert s[8] is True and s[9] is None and s[10] is False     # extend, no closes, no fold mark
    read = [s for s in statements if s[1] == "may_read"]
    assert len(read) == 1 and read[0][2] == [
        ("role", "string"), ("kind", "string"), ("element", "string")]


class MissingRightDeclarations(AssertionError):
    """std-access does not declare the rights to propose, review, publish and execute as the decision gives."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRightDeclarations,
    reason="extra: decisions/review-and-rights.md: Declare in packs/std-access/rules/access.dl, beside may_read and "
           "each as // @extend without a clause, may_propose(role: symbol, kind: symbol, element: symbol), "
           "may_review(role: symbol, kind: symbol, element: symbol), may_publish(role: symbol, kind: symbol) and "
           "may_execute(role: symbol, plugin: symbol); then regenerate the std-access row of "
           "compiler/rezono_compiler/standard_packs.py and the std-access pins of the packs that import it. Read "
           "section 1. Waits for compiler/tests/test_std_access_full.py, which changes the same file and pins.",
)
def test_standard_access_declares_the_four_rights():
    got = {s[1]: s[2] for s in declarations() if s[0] == "decl"}
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
