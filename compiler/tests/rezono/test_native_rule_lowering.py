"""Native module/2 clauses preserve the independent Datalog rule and its witness."""

import json
from pathlib import Path
import shutil

import pytest

from rezono_compiler import emit, pack, rezono_module, rules
from rezono_compiler.__main__ import explained
from support import FIXTURE
from test_rezono_module import declare


DATALOG = """.decl sized(item: symbol, magnitude: number)
sized(item, magnitude) :- alpha__size(item, magnitude), magnitude > 2.
.output sized
"""
NATIVE = """rezono 0
pack minimal
rules capacity
  sized(item: ?item, magnitude: ?magnitude) if Alpha.size(?item, ?magnitude) and ?magnitude > 2
"""
NATIVE_DECLARATION = {
    "rules": "capacity", "clauses": [{
        "head": {"relation": "sized", "arguments": [
            {"field": "item", "value": {"var": "item"}},
            {"field": "magnitude", "value": {"var": "magnitude"}},
        ]},
        "body": [
            {"atom": {"relation": "Alpha.size", "arguments": [
                {"value": {"var": "item"}}, {"value": {"var": "magnitude"}},
            ]}},
            {"compare": {"left": {"var": "magnitude"}, "op": ">",
                         "right": {"lit": {"type": "integer", "value": "2"}}}},
        ],
    }],
}


def native_form():
    def token(offset, text):
        start = NATIVE.index(text, offset)
        return start, start + len(text)

    block = token(0, "capacity")
    head = token(block[1], "sized")
    field_item = token(head[1], "item")
    head_item = token(field_item[1], "?item")
    field_magnitude = token(head_item[1], "magnitude")
    head_magnitude = token(field_magnitude[1], "?magnitude")
    relation = token(head_magnitude[1], "Alpha.size")
    body_item = token(relation[1], "?item")
    body_magnitude = token(body_item[1], "?magnitude")
    compare_magnitude = token(body_magnitude[1], "?magnitude")
    operator = token(compare_magnitude[1], ">")
    limit = token(operator[1], "2")
    paths = {
        "/decls/0": block,
        "/decls/0/clauses/0": head,
        "/decls/0/clauses/0/head": head,
        "/decls/0/clauses/0/head/relation": head,
        "/decls/0/clauses/0/head/arguments/0": field_item,
        "/decls/0/clauses/0/head/arguments/0/field": field_item,
        "/decls/0/clauses/0/head/arguments/0/value": head_item,
        "/decls/0/clauses/0/head/arguments/1": field_magnitude,
        "/decls/0/clauses/0/head/arguments/1/field": field_magnitude,
        "/decls/0/clauses/0/head/arguments/1/value": head_magnitude,
        "/decls/0/clauses/0/body/0": relation,
        "/decls/0/clauses/0/body/0/atom": relation,
        "/decls/0/clauses/0/body/0/atom/relation": relation,
        "/decls/0/clauses/0/body/0/atom/arguments/0": body_item,
        "/decls/0/clauses/0/body/0/atom/arguments/0/value": body_item,
        "/decls/0/clauses/0/body/0/atom/arguments/1": body_magnitude,
        "/decls/0/clauses/0/body/0/atom/arguments/1/value": body_magnitude,
        "/decls/0/clauses/0/body/1": operator,
        "/decls/0/clauses/0/body/1/compare": operator,
        "/decls/0/clauses/0/body/1/compare/left": compare_magnitude,
        "/decls/0/clauses/0/body/1/compare/op": operator,
        "/decls/0/clauses/0/body/1/compare/right": limit,
        "/decls/0/clauses/0/body/1/compare/right/lit": limit,
    }
    return {
        "format": "rezono.module/2",
        "module": {"rezono": "0", "pack": "minimal", "use": [], "decls": [NATIVE_DECLARATION]},
        "spans": [{"at": pointer, "line": str(NATIVE.count("\n", 0, start) + 1),
                   "start": str(start), "end": str(end)} for pointer, (start, end) in sorted(paths.items())],
    }


def write_pack(tmp_path, representation):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / representation / "minimal"))
    (directory / "facts").mkdir()
    (directory / "facts/case.yaml").write_text(
        "alpha: [{id: above, title: Above, size: 3}, {id: boundary, title: Boundary, size: 2}, "
        "{id: missing, title: Missing}]\n", encoding="utf-8",
    )
    with (directory / "labels/nl.yaml").open("a", encoding="utf-8") as labels:
        labels.write("\nsized: gemeten\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8") as messages:
        messages.write("\nrule.sized = {{De grootte ligt boven de grens.}}\n")
    source = "rules/capacity.dl" if representation == "datalog" else "rezono/capacity.rezono"
    (directory / source).parent.mkdir()
    (directory / source).write_bytes((DATALOG if representation == "datalog" else NATIVE).encode("utf-8"))
    if representation == "native":
        form = "rezono/capacity.json"
        (directory / form).write_text(json.dumps(native_form()), encoding="utf-8")
        declare(directory, [{"module": source, "form": form, "layer": "facts"}])
    return directory, source


def checked_meaning(directory, source):
    model = pack.read(directory)
    program = rules.load(model.rules)
    relation = program.relations["sized"]
    columns = [(column.name, column.type) for column in (*relation.key, *relation.values)]
    assert [name for name, _ in columns] == ["item", "magnitude"]
    files = explained(model, directory)
    rows = json.loads(files["0-case/snapshots/sized.json"])
    assert rows == [{"key": ["above", "3"]}]
    [proof] = json.loads(files["0-case/proofs.json"])
    assert proof["root"] == {"relation": "sized", "key": '["above","3"]'}
    witness, = proof["witnesses"]
    assert witness["rule_id"] == "sized"
    assert witness["premises"] == [{
        "row": {"relation": "alpha__size", "key": '["above","3"]'},
        "polarity": "positive", "stratum": 0,
    }]
    bundle = emit.bundle(model, [], program)
    [rule] = bundle["rules"]
    assert {"element": "sized", "lang": "nl", "text": "gemeten"} in bundle["labels"]
    resources = {entry["lang"]: entry["resource"] for entry in bundle["messages"]}
    assert "rule.sized = {{De grootte ligt boven de grens.}}" in resources["nl"].splitlines()
    lines = (directory / source).read_text(encoding="utf-8").splitlines()
    [(line, column)] = [(i, text.index("sized(") + 1) for i, text in enumerate(lines, 1)
                      if "sized(" in text and not text.startswith(".decl")]
    assert rule["origin"] == {"file": source, "line": str(line)}
    assert rule["span"] == {"file": source, "line": str(line), "column": str(column)}
    meaning = {key: value for key, value in rule.items() if key not in {"origin", "span"}}
    return columns, rows, proof, meaning


def test_datalog_rule_is_a_witnessed_parity_reference(tmp_path):
    checked_meaning(*write_pack(tmp_path, "datalog"))


@pytest.mark.xfail(strict=True, raises=(pack.CompileError, AssertionError), reason=(
    "Lower hand-authored module/2 native clauses to typed rule IR with their authored clause spans. "
    "Read decisions/language-native-rules.md. Write in compiler/rezono_compiler; no source reader is required."
))
def test_native_rule_lowers_with_equivalent_witness(tmp_path, monkeypatch):
    reference = checked_meaning(*write_pack(tmp_path, "datalog"))
    # Supply the hand-authored form at the reader boundary when compiling authored source.
    # Rule lowering, evaluation and witness creation still run independently.
    monkeypatch.setattr(rezono_module, "authored_form", lambda *_: native_form(), raising=False)
    assert checked_meaning(*write_pack(tmp_path, "native")) == reference
