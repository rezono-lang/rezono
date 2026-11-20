"""Boolean columns and `TRUE`/`FALSE` literals in the Soufflé test oracle helper."""

import json
import re
import shutil
from contextlib import closing

import pytest
import yaml

import souffle
from rezono_compiler import batch, emit, facts, pack, rules, rules_dl
from support import FIXTURE


def _lower_decls(text: str) -> list[str]:
    return re.findall(r"^\s*\.decl\s+([a-z0-9_]+)", text, flags=re.M)


RULES_DL = """\
// comment keeping TRUE, FALSE and : boolean untouched
.decl observed_flag(item: symbol, value: boolean)
observed_flag(item, value) :- alpha(item), alpha__flag(item, value).

.decl direct_true(item: symbol)
direct_true(item) :- alpha__flag(item, TRUE).

.decl confirmed(item: symbol)
confirmed(item) :- observed_flag(item, value), value = TRUE.

.decl incomplete(item: symbol)
incomplete(item) :- observed_flag(item, value), value = FALSE.

.decl not_false(item: symbol)
not_false(item) :- alpha(item), !alpha__flag(item, FALSE).

.decl labeled(item: symbol, tag: symbol, ok: boolean)
labeled(item, "TRUE", TRUE) :- alpha__flag(item, value), value != FALSE.
labeled(item, "FALSE", FALSE) :- alpha__flag(item, FALSE).

.decl true_total(total: number)
true_total(n) :- n = count : { alpha__flag(_, TRUE) }.
"""

TABLES = {
    "alpha": [("id", "string")],
    "alpha__flag": [("id", "string"), ("value", "boolean")],
}


def _boolean_pack(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    schema = folder / "schema/minimal.yaml"
    document = yaml.safe_load(schema.read_bytes())
    document["classes"]["Alpha"]["attributes"]["flag"] = {"range": "boolean"}
    schema.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (folder / "rules").mkdir()
    (folder / "rules/flags.dl").write_text(RULES_DL, encoding="utf-8")
    return folder


def test_program_and_source_lower_boolean_columns_and_literals(tmp_path):
    doc = rules_dl.read_program(RULES_DL, "flags", TABLES, "flags_pack")
    prog = rules.load(doc)
    p_text = souffle.program(prog)
    s_text = souffle.source(prog, [RULES_DL])

    for text in (p_text, s_text):
        code_only = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
        assert ": boolean" not in code_only and ":boolean" not in code_only
        assert re.search(r'(?<!")(?<![A-Za-z0-9_])(TRUE|FALSE)(?![A-Za-z0-9_])(?!")', code_only) is None
        assert sorted(_lower_decls(text)) == sorted(prog.relations)

    assert ".decl alpha__flag(id:symbol, value:symbol)" in p_text
    assert ".decl observed_flag(item:symbol, value:symbol)" in p_text
    assert 'alpha__flag(V_item, "true")' in p_text
    assert 'V_value = "true"' in p_text
    assert 'V_value = "false"' in p_text
    assert 'V_value != "false"' in p_text
    assert '!alpha__flag(V_item, "false")' in p_text
    assert 'labeled(V_item, "TRUE", "true")' in p_text
    assert 'labeled(V_item, "FALSE", "false")' in p_text
    assert 'count : { alpha__flag(_, "true") }' in p_text

    assert "// comment keeping TRUE, FALSE and : boolean untouched" in s_text
    assert ".decl observed_flag(item: symbol, value: symbol)" in s_text
    assert 'alpha__flag(item, "true")' in s_text
    assert 'value = "true"' in s_text
    assert 'value = "false"' in s_text
    assert 'value != "false"' in s_text
    assert '!alpha__flag(item, "false")' in s_text
    assert 'labeled(item, "TRUE", "true")' in s_text
    assert 'labeled(item, "FALSE", "false")' in s_text
    assert 'count : { alpha__flag(_, "true") }' in s_text

    # Pack-level pack_source over a schema with a `range: boolean` attribute.
    folder = _boolean_pack(tmp_path)
    model = pack.read(folder)
    pack_prog = rules.load(json.loads(emit.compile_pack(model)["ir/rules.json"]))
    packed = souffle.pack_source(pack_prog, folder)
    assert sorted(_lower_decls(packed)) == sorted(pack_prog.relations)
    code_only = "\n".join(line for line in packed.splitlines() if not line.lstrip().startswith("//"))
    assert ": boolean" not in code_only
    assert 'value = "true"' in code_only and 'alpha__flag(item, "false")' in code_only


def test_source_rewrites_trailing_boolean_literal_and_preserves_word_boundaries():
    raw = '.decl hit(item: symbol, tag: symbol)\nhit(item, "TRUE") :- alpha__flag(item, TRUE).\n'
    doc = rules_dl.read_program(raw, "edge", TABLES, "edge_pack")
    prog = rules.load(doc)
    text = souffle.source(prog, [raw])
    assert 'hit(item, "TRUE") :- alpha__flag(item, "true").' in text


def test_boolean_term_and_fact_cell_are_canonical():
    assert souffle._term("true", "boolean") == '"true"'
    assert souffle._term("false", "boolean") == '"false"'
    assert souffle._term("TRUE", "boolean") == '"true"'
    assert souffle._term("FALSE", "boolean") == '"false"'
    assert souffle._term(True, "boolean") == '"true"'
    assert souffle._term(False, "boolean") == '"false"'
    assert souffle._term("?flag", "boolean") == "V_flag"
    assert souffle._term("_", "boolean") == "_"

    assert souffle._fact_cell(True, "boolean") == "true"
    assert souffle._fact_cell(False, "boolean") == "false"
    assert souffle._fact_cell("TRUE", "boolean") == "true"
    assert souffle._fact_cell("FALSE", "boolean") == "false"
    assert souffle._fact_cell("true", "boolean") == "true"
    assert souffle._fact_cell("false", "boolean") == "false"
    assert souffle._fact_cell("TRUE", "string") == "TRUE"
    assert souffle._fact_cell(42, "integer") == "42"


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_souffle_program_and_pack_source_evaluate_boolean_columns_and_literals(tmp_path):
    folder = _boolean_pack(tmp_path)
    model = pack.read(folder)
    prog = rules.load(json.loads(emit.compile_pack(model)["ir/rules.json"]))
    records = {"alpha": [
        {"id": "a", "title": "one", "flag": True},
        {"id": "b", "title": "two", "flag": False},
        {"id": "c", "title": "three"},
    ]}
    data = facts.rows_of(model, records)
    assert all(type(v) is bool for _, v in data["alpha__flag"])

    want = {
        "observed_flag": {("a", "true"), ("b", "false")},
        "direct_true": {("a",)},
        "confirmed": {("a",)},
        "incomplete": {("b",)},
        "not_false": {("a",), ("c",)},
        "labeled": {("a", "TRUE", "true"), ("b", "FALSE", "false")},
        "true_total": {("1",)},
    }
    with closing(batch.connect(prog, data)) as db:
        batch.compute(db, prog)
        derived = batch.read(db, prog)
    assert derived == want
    assert souffle.run(prog, data, tmp_path) == want
    packed = souffle.pack_source(prog, folder)
    assert souffle.run(prog, data, tmp_path, program_text=packed) == want

    # String-encoded boolean facts ("true"/"false") yield the same derived rows.
    text_data = {**data, "alpha__flag": [("a", "true"), ("b", "false")]}
    assert souffle.run(prog, text_data, tmp_path, program_text=packed) == want
