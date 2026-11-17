"""S28: one typed rule program over pinned imports, with explicit extension and no implicit grants."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE
from rezono_compiler import emit, modules, pack, rules_sql
from rezono_compiler import rules as ir


def write_rules(at, text, module="core"):
    (at / "rules").mkdir(exist_ok=True)
    (at / "rules" / f"{module}.dl").write_text(text, encoding="utf-8")


def pin(at, *dependencies):
    f = at / "pack.yaml"
    doc = yaml.safe_load(f.read_text())
    doc["imports"] = [{"name": yaml.safe_load((d / "pack.yaml").read_text())["name"],
                       "path": "../" + d.name, "sha256": modules.pack_hash(d)} for d in dependencies]
    f.write_text(yaml.safe_dump(doc), encoding="utf-8")


@pytest.fixture
def imported(tmp_path):
    owner = Path(shutil.copytree(FIXTURE.parent / "shared", tmp_path / "owner"))
    consumer = Path(shutil.copytree(FIXTURE, tmp_path / "consumer"))
    write_rules(owner, ".decl registered(x: symbol)\nregistered(x) :- party(x).\n")
    pin(consumer, owner)
    return owner, consumer


def program(at):
    return ir.load(pack.read(at).rules)


def test_import_without_local_rules_compiles_once_and_is_deterministic(imported):
    _, consumer = imported
    model = pack.read(consumer)
    p = ir.load(model.rules)
    assert p.rules["registered"].body[0].atom.relation == "party"
    assert p.rules["registered"].origin == ("shared-terms:rules/core.dl", 2)
    assert p.rules["registered"].module == "import_shared_terms_core"
    assert emit.compile_pack(model) == emit.compile_pack(pack.read(consumer))


def test_local_rules_read_imported_rules_and_stratify_the_union(imported):
    _, consumer = imported
    write_rules(consumer, ".decl missing(x: symbol)\nmissing(x) :- alpha(x), !registered(x).\n")
    p = program(consumer)
    assert p.strata["missing"] > p.strata["registered"]


@pytest.mark.parametrize("declaration", ["", ".decl registered(x: symbol)\n", "// @extend\n.decl registered(x: symbol)\n"])
def test_consumer_cannot_reopen_a_relation(imported, declaration):
    _, consumer = imported
    write_rules(consumer, declaration + "registered(x) :- alpha(x).\n")
    with pytest.raises(pack.CompileError, match="@extend"):
        pack.read(consumer)


def test_only_an_owner_can_open_an_extension_and_no_grant_is_invented(imported):
    owner, consumer = imported
    write_rules(owner, "// @extend\n.decl granted(r: symbol, k: symbol, x: symbol)\n")
    pin(consumer, owner)
    p = program(consumer)
    assert p.relations["granted"].extend and p.rules_for("granted") == []
    assert "WHERE FALSE" in rules_sql.feldera(p)
    assert "WHERE FALSE" in rules_sql.duckdb_relation(p, "granted")[0]
    assert ir.load(ir.to_doc(p)).relations["granted"].extend
    bundle = json.loads(emit.compile_pack(pack.read(consumer))["bundle/schema-bundle.json"])
    assert bundle["relations"][0]["extend"] is True
    write_rules(consumer, '.decl granted(r: symbol, k: symbol, x: symbol)\ngranted("reader", "alpha", x) :- alpha(x).\n')
    p = program(consumer)
    assert len(p.rules_for("granted")) == 1
    assert p.rules_for("granted")[0].origin[0] == "rules/core.dl"


def test_compiled_declaration_only_extension_reaches_the_independent_epoch_checker(imported):
    import hashlib
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations, load_rules

    owner, consumer = imported
    write_rules(owner, "// @extend\n.decl granted(r: symbol, k: symbol, x: symbol)\n")
    pin(consumer, owner)
    files = emit.compile_pack(pack.read(consumer))
    doc = json.loads(files["ir/rules.json"])
    rules = load_rules(doc)
    derived = derived_relations(doc, rules)
    assert derived == {"granted"}
    for rows, valid in (([], True), ([{"key": ["reader", "alpha", "x"]}], False)):
        data = json.dumps(rows).encode()
        manifest = {"id": "m-1", "snapshots": [{"relation": "granted", "role": "all", "complete": True,
                    "uri": "granted.json", "format": "json", "sha256": hashlib.sha256(data).hexdigest()}]}
        report = check_epoch([], manifest, rules, lambda uri: data, derived=derived)
        assert report["valid"] is valid, report["findings"]
        assert [f["reason"] for f in report["findings"]] == ([] if valid else ["unproven_row"])


@pytest.mark.parametrize("decl", [".decl registered(x: number)", ".decl registered(y: symbol)",
                                   "// @absence\n.decl registered(x: symbol)"])
def test_extension_signature_and_semantics_must_match(imported, decl):
    owner, consumer = imported
    write_rules(owner, "// @extend\n.decl registered(x: symbol)\nregistered(x) :- party(x).\n")
    pin(consumer, owner)
    write_rules(consumer, decl + "\nregistered(x) :- alpha(x).\n")
    with pytest.raises(pack.CompileError, match="must match"):
        pack.read(consumer)


def test_diamond_imports_keep_one_copy_of_the_rules(imported, tmp_path):
    owner, consumer = imported
    middle = tmp_path / "middle"
    (middle / "schema").mkdir(parents=True)
    (middle / "pack.yaml").write_text("name: middle\nversion: 0.1.0\ndefault_language: nl\n")
    (middle / "schema" / "empty.yaml").write_text(
        "id: https://rezono.example/empty\nname: empty\nimports: [linkml:types]\n")
    pin(middle, owner)
    pin(consumer, middle, owner)
    assert list(program(consumer).rules) == ["registered"]


def test_imported_rules_cannot_read_consumer_tables(imported):
    owner, consumer = imported
    write_rules(owner, ".decl registered(x: symbol)\nregistered(x) :- alpha(x).\n")
    pin(consumer, owner)
    with pytest.raises(pack.CompileError, match="not a table visible"):
        pack.read(consumer)


def test_imported_tables_and_access_kind_constants_follow_schema_names(imported):
    owner, consumer = imported
    f = consumer / "schema" / "minimal.yaml"
    doc = yaml.safe_load(f.read_text())
    doc["classes"]["Party"] = {"attributes": {"id": {"identifier": True}}}
    f.write_text(yaml.safe_dump(doc))
    write_rules(owner, '// @extend\n.decl may_read(r: symbol, k: symbol, x: symbol)\n'
                       'may_read("reader", "party", x) :- party__grade(x, "plain").\n')
    pin(consumer, owner)
    p = program(consumer)
    rule = p.rules["may_read"]
    assert rule.head.terms[1] == "shared_terms_terms_party"
    assert rule.body[0].atom.relation == "shared_terms_terms_party__grade"


def test_extension_cannot_mark_a_base_table(imported):
    _, consumer = imported
    write_rules(consumer, "// @extend\n.decl alpha(id: symbol)\n")
    with pytest.raises(pack.CompileError, match="derived relations"):
        pack.read(consumer)


def test_access_kind_comparisons_follow_the_same_binding(imported):
    from rezono_compiler.rules_dl import parse_file, remap_statement
    text = ('may_read("reader", k, x) :- party__grade(x, k), k = "party".\n')
    statement = parse_file(text, "rules/access.dl")[0]
    mapped = remap_statement(statement, {"party": "terms_party"})
    assert mapped[2][-1][3] == ("const", "terms_party", "string")
    assert mapped[2][0][-1][0] == "terms_party__grade"


def test_unmarked_declaration_without_rules_still_fails(imported):
    _, consumer = imported
    write_rules(consumer, ".decl unused(x: symbol)\n")
    with pytest.raises(pack.CompileError, match="no_rules"):
        pack.read(consumer)


def test_imported_rules_keep_open_world_semantics(imported):
    owner, consumer = imported
    f = owner / "schema" / "terms.yaml"
    doc = yaml.safe_load(f.read_text())
    doc["classes"]["Party"]["annotations"] = {"world": "open"}
    f.write_text(yaml.safe_dump(doc))
    pin(consumer, owner)
    write_rules(consumer, ".decl missing(x: symbol)\nmissing(x) :- alpha(x), !registered(x).\n")
    with pytest.raises(pack.CompileError, match="negation_over_open"):
        pack.read(consumer)
    write_rules(consumer, "// @absence\n.decl missing(x: symbol)\nmissing(x) :- alpha(x), !registered(x).\n")
    p = program(consumer)
    assert p.relations["registered"].world == "open"
    assert p.relations["missing"].world == "closed"


@pytest.mark.parametrize("value,role", [("true", "derived"), (1, "derived"), (True, "base")])
def test_rule_ir_checks_the_extension_marker(value, role):
    doc = {"format": ir.FORMAT, "pack": "example", "relations": [
        {"name": "granted", "role": role, "module": "access", "extend": value,
         "key": [{"name": "subject", "type": "string"}]}], "rules": []}
    with pytest.raises(ir.IRError, match="bad_extend"):
        ir.load(doc)


def test_import_pin_covers_rules(imported):
    owner, consumer = imported
    write_rules(owner, ".decl registered(x: symbol)\nregistered(x) :- party__grade(x, \"fine\").\n")
    with pytest.raises(pack.CompileError, match="not the pinned"):
        pack.read(consumer)


def test_union_matches_independent_souffle(imported):
    """Runs in CI, where Souffle is installed; uses source rules independently of the import binder."""
    from souffle import run
    if not shutil.which("souffle"):
        pytest.skip("Souffle runs in CI")
    _, consumer = imported
    write_rules(consumer, ".decl missing(x: symbol)\nmissing(x) :- alpha(x), !registered(x).\n")
    p = program(consumer)
    rows = {"party": [("a",)], "alpha": [("a",), ("b",)]}
    text = (".decl party(id:symbol)\n.input party\n.decl alpha(id:symbol)\n.input alpha\n"
            ".decl registered(x:symbol)\nregistered(x) :- party(x).\n.output registered\n"
            ".decl missing(x:symbol)\nmissing(x) :- alpha(x), !registered(x).\n.output missing\n")
    expected = {"registered": {("a",)}, "missing": {("b",)}}
    assert run(p, rows, program_text=text) == expected
    import duckdb
    db = duckdb.connect()
    for sql in rules_sql.duckdb_tables(p):
        db.execute(sql)
    for name, rs in rows.items():
        db.executemany(f'INSERT INTO "{name}" VALUES (?)', rs)
    for sql in rules_sql.duckdb_program(p):
        db.execute(sql)
    assert {n: set(db.execute(f'SELECT * FROM "{n}"').fetchall()) for n in expected} == expected
