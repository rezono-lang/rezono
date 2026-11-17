"""A theory is a fact-free definition, checked with the ordinary compiler."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rede_compiler import emit, modules, pack, rules

FIXTURE = Path(__file__).parent / "fixtures" / "minimal"
SHARED = FIXTURE.parent / "shared"


def write_yaml(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


@pytest.fixture
def theory(tmp_path):
    target = Path(shutil.copytree(FIXTURE, tmp_path / "main"))
    meta = yaml.safe_load((target / "pack.yaml").read_text(encoding="utf-8"))
    write_yaml(target / "pack.yaml", meta | {"theory": True})
    return target


def set_flag(target, flag):
    path = target / "pack.yaml"
    meta = yaml.safe_load(path.read_text(encoding="utf-8"))
    write_yaml(path, meta | {"theory": flag})


def test_fact_free_theory_compiles_deterministically(theory):
    model = pack.read(theory)
    assert model.meta["theory"] is True
    compiled = emit.compile_pack(model)
    assert "engine/integrity.sql" in compiled
    assert compiled == emit.compile_pack(pack.read(theory))
    # The flag is trusted producer context, not new public instance metadata.
    assert "theory" not in json.loads(compiled["bundle/schema-bundle.json"])["pack"]
    assert not (theory / "facts").exists()


def test_ordinary_default_and_false_keep_existing_compilation(theory):
    baseline = emit.compile_pack(pack.read(FIXTURE))
    assert pack.read(FIXTURE).meta["theory"] is False
    set_flag(theory, False)
    assert pack.read(theory).meta["theory"] is False
    assert emit.compile_pack(pack.read(theory)) == baseline


@pytest.mark.parametrize("flag", ["true", "false", None, 0, 1, [], {}])
def test_non_boolean_theory_flag_is_refused(theory, flag):
    set_flag(theory, flag)
    with pytest.raises(pack.CompileError, match=r"pack.yaml: theory must be a boolean"):
        pack.read(theory)


@pytest.mark.parametrize("relative", ["one.yaml", "nested/two.yaml", "unparsed.txt"])
def test_theory_fact_files_are_refused_before_parsing(theory, relative):
    target = theory / "facts" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not: [valid", encoding="utf-8")
    with pytest.raises(pack.CompileError, match="a theory pack cannot contain fact files"):
        pack.read(theory)


def test_empty_facts_directory_has_no_instance(theory):
    (theory / "facts").mkdir()
    assert pack.read(theory).meta["theory"] is True


def test_existing_schema_axioms_stay_checks(theory):
    path = theory / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    alpha = schema["classes"]["Alpha"]
    alpha["attributes"].update(first={"range": "Alpha"}, second={"range": "Alpha"})
    alpha["annotations"] = {"path_equations": {"value": [{"name": "same_end", "left": "first", "right": "second"}]}}
    alpha["rules"] = [{"preconditions": {"slot_conditions": {"size": {"value_presence": "PRESENT"}}},
                       "postconditions": {"slot_conditions": {"size": {"minimum_value": 1}}}}]
    write_yaml(path, schema)
    compiled = emit.compile_pack(pack.read(theory))
    checks = {check["view"]: check["check"] for check in json.loads(compiled["bundle/schema-bundle.json"])["checks"]}
    assert checks["alpha__same_end__path_equation"] == "path_equation"
    assert checks["alpha__rule_1__rule"] == "rule"


def imported(theory, tmp_path, *, flag=True):
    shared = Path(shutil.copytree(SHARED, tmp_path / "shared"))
    set_flag(shared, flag)
    set_flag(theory, False)
    meta = yaml.safe_load((theory / "pack.yaml").read_text(encoding="utf-8"))
    meta["imports"] = [{"name": "shared-terms", "path": "../shared", "sha256": modules.pack_hash(shared)}]
    write_yaml(theory / "pack.yaml", meta)
    return shared


def test_domain_can_import_a_fact_free_pinned_theory(theory, tmp_path):
    shared = imported(theory, tmp_path)
    model = pack.read(theory)
    assert model.meta["theory"] is False
    assert model.imports[0]["sha256"] == modules.pack_hash(shared)
    assert emit.compile_pack(model)


def test_theory_facts_cannot_hide_in_an_import(theory, tmp_path):
    shared = imported(theory, tmp_path)
    (shared / "facts").mkdir()
    (shared / "facts" / "one.yaml").write_text("party: [{id: hidden}]", encoding="utf-8")
    # Facts do not change the import's definition pin, so pin verification alone cannot enforce this.
    with pytest.raises(pack.CompileError, match="a theory pack cannot contain fact files"):
        pack.read(theory)


def test_imported_theory_metadata_is_also_strict(theory, tmp_path):
    imported(theory, tmp_path, flag="true")
    with pytest.raises(pack.CompileError, match="theory must be a boolean"):
        pack.read(theory)


def test_domain_imports_fact_free_theory_rules_through_the_pinned_s28_program(theory, tmp_path):
    shared = imported(theory, tmp_path)
    # The shared fixture normally inherits these messages from its consumer; this
    # case also admits the theory on its own through the ordinary reader.
    shutil.copytree(FIXTURE / "messages", shared / "messages")
    (shared / "rules").mkdir()
    (shared / "rules" / "one.dl").write_text(
        ".decl registered(x: symbol)\nregistered(x) :- party(x).\n", encoding="utf-8")
    meta = yaml.safe_load((theory / "pack.yaml").read_text(encoding="utf-8"))
    meta["imports"][0]["sha256"] = modules.pack_hash(shared)
    write_yaml(theory / "pack.yaml", meta)
    model = pack.read(theory)
    prog = rules.load(model.rules)
    assert model.meta["theory"] is False
    theory_model = pack.read(shared)
    assert theory_model.meta["theory"] is True
    assert "engine/rules.sql" in emit.compile_pack(theory_model)
    assert model.imports[0]["sha256"] == modules.pack_hash(shared)
    assert list(prog.rules) == ["registered"]
    assert prog.rules["registered"].origin == ("shared-terms:rules/one.dl", 2)
    assert prog.rules["registered"].body[0].atom.relation == "party"
    assert emit.compile_pack(model) == emit.compile_pack(pack.read(theory))

    # A theory marker grants no authority to reopen its unmarked relation.
    (theory / "rules").mkdir()
    (theory / "rules" / "consumer.dl").write_text(
        "registered(x) :- alpha(x).\n", encoding="utf-8")
    with pytest.raises(pack.CompileError, match="only its owner can mark it @extend"):
        pack.read(theory)


def test_theory_flag_is_covered_by_existing_definition_hash(theory):
    theory_hash = modules.pack_hash(theory)
    set_flag(theory, False)
    assert modules.pack_hash(theory) != theory_hash
