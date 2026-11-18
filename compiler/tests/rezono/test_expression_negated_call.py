"""Check state linking and the ordinary native lowering boundary against one authored vector."""

from dataclasses import dataclass
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from rezono_compiler import modules, native_rule_lowering, native_rule_signatures, pack, rezono_module, rules_dl


CORPUS = Path(__file__).resolve().parents[3] / "tests/conformance"
OWNER = "gauge-core"
CONSUMER = "gauge-case"


class PartialityMismatch(AssertionError):
    """The ordinary linker did not establish the authored predicate states."""


class NegatedCallMismatch(AssertionError):
    """The ordinary lowerer disagreed with the frozen linked evidence."""


@dataclass(frozen=True)
class SuppliedSignature(native_rule_signatures.Signature):
    """Inject linked evidence at the lowerer boundary, independently of the linker under test."""

    predicate: dict | None = None


@pytest.fixture
def vector():
    case = yaml.safe_load((CORPUS / "expression-negated-call.yaml").read_text(encoding="utf-8"))
    schema = json.loads((CORPUS / "case.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(case)
    return case


def write_meta(directory, **members):
    directory.mkdir(exist_ok=True)
    (directory / "pack.yaml").write_text(yaml.safe_dump({
        "name": directory.name, "version": "1", "default_language": "en", **members,
    }), encoding="utf-8")


def authored(directory, name, text):
    relative = f"rezono/{name}.rezono"
    file = directory / relative
    file.parent.mkdir(exist_ok=True)
    data = text.encode("utf-8")
    file.write_bytes(data)
    declared = rezono_module.Declared(relative, f"rezono/{name}.json", "facts")
    errors = []
    form = rezono_module.authored_form(directory, declared, data, errors)
    assert not errors and form is not None, errors
    (directory / declared.form).write_text(json.dumps(form), encoding="utf-8")
    return (directory.name, relative), form


def registration(name):
    return {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "facts"}


@pytest.fixture
def closure(tmp_path, vector):
    inputs = vector["input"]
    owner = tmp_path / OWNER
    consumer = tmp_path / CONSUMER
    write_meta(owner, rezono=[registration("core")])
    (owner / "schema").mkdir()
    (owner / "schema/gauge.yaml").write_bytes(inputs["schema"].encode("utf-8"))
    owner_form = authored(owner, "core", inputs["owner"])
    write_meta(consumer, rezono=[registration("closure")], imports=[{
        "name": OWNER, "path": f"../{OWNER}", "sha256": modules.pack_hash(owner),
    }])
    forms = dict((owner_form, authored(consumer, "closure", inputs["closure"])))
    expected = vector["expect"]["witness"]
    sources = {
        f"{OWNER}:schema/gauge.yaml": inputs["schema"],
        "rezono/closure.rezono": inputs["closure"],
    }
    for place in expected["related"]:
        line = sources[place["file"]].splitlines()[int(place["line"]) - 1]
        start = int(place["column"]) - 1
        assert line[start:].startswith(place["text"]), place
    return consumer, forms


@pytest.mark.xfail(
    strict=True,
    raises=PartialityMismatch,
    reason="Link and retain possible predicate states and source causes across wrappers, positive recursion "
           "and authorized extensions. Use native_rule_signatures.link and the shared expression-negated-call "
           "vector for decisions/language-expression-semantics.md §2. No consumer or lowering dependency.",
)
def test_expression_link_partiality(closure, vector):
    directory, forms = closure
    linked = native_rule_signatures.link(directory, forms)
    expected = vector["expect"]
    outcomes = expected["value"]
    related = source_places(expected["witness"]["related"])
    partial_states = outcomes["summaries"]["active"]["states"]
    extension = linked.clauses[CONSUMER, "rezono/closure.rezono", "/decls/4"]
    assert (extension.relation, linked.signatures["active"].owner) == ("active", OWNER)
    for relation in [*outcomes["partial"], outcomes["total"]]:
        signature = linked.signatures[relation]
        predicate = getattr(signature, "predicate", None)
        if predicate is None:
            raise PartialityMismatch(f"linked signature {relation!r} has no possible states or source causes")
        if relation in outcomes["partial"]:
            if not set(partial_states) <= set(predicate["states"]) or any(
                place not in predicate["related"] for place in related
            ):
                raise PartialityMismatch(f"{relation!r} loses the reachable partial comparison: {predicate!r}")
        elif predicate["states"] != ["known"] or predicate["related"]:
            raise PartialityMismatch(f"{relation!r} stays decided because false dominates: {predicate!r}")


def supplied(key, case, summaries, related):
    """Supply independently checked evidence at the ordinary native source boundary."""
    expected = summaries[case["relation"]]
    predicate = summaries.get(case.get("summary"))
    if case.get("summary") == "active":
        predicate = predicate | {"related": related}
    owner = expected["owner"]
    stem = "core" if owner == OWNER else "closure"
    signature = SuppliedSignature(
        tuple((col["name"], col["logical"], col["physical"]) for col in expected["columns"]),
        rules_dl.module_of(owner, CONSUMER, stem), owner, f"rezono/{stem}.rezono", predicate=predicate,
    )
    marker = native_rule_signatures.Signature((("g", "gauge", "string"),), "consumer", CONSUMER, key[1])
    call = "/decls/0/when/and/1"
    if case["guard"].startswith("not "):
        call += "/not"
    clause = native_rule_signatures.LinkedClause(
        "marker", "consumer", {call: case["relation"]}, {}, {"/decls/0/when/and/0": "gauge"},
    )
    return native_rule_signatures.Linked(
        {"marker": marker, case["relation"]: signature}, {(*key, "/decls/0"): clause},
    )


def source_places(places):
    return [{key: place[key] for key in ("file", "at", "line", "column")} for place in places]


def position(place):
    return (place["file"], int(place["line"]), int(place["column"]))


@pytest.mark.xfail(
    strict=True,
    raises=NegatedCallMismatch,
    reason="Use the same linked predicate summaries as TypeScript at native_rule_lowering.lower_source. "
           "Require native R047 with source causes before constructing negative IR; a checked total rule "
           "still lowers. The supplied vector avoids a dependency on the linker-state implementation.",
)
def test_expression_python_negated_call(closure, vector):
    directory, _ = closure
    inputs, expected = vector["input"], vector["expect"]
    errors = []
    definitions, _ = modules.load(directory, pack.read_meta(directory), errors)
    assert not errors, errors
    [schema] = [definition for definition in definitions if definition.rel == "schema/gauge.yaml"]
    primary = expected["witness"]["primary"]
    related = source_places(expected["witness"]["related"])
    diagnoses = []
    for case in inputs["cases"]:
        source = inputs["consumer"].replace("GUARD", case["guard"])
        key, form = authored(directory, "consumer", source)
        relation = case["relation"]
        linked = supplied(key, case, expected["value"]["summaries"], related)
        module = modules.Module("consumer", CONSUMER, directory, directory / key[1], schema.sv, form=form)
        try:
            native = native_rule_lowering.lower_source(module, form, CONSUMER, linked)
        except pack.CompileError as error:
            report = [(item.code, item.where, item.span, item.doc().get("related", []))
                      for item in error.diagnostics]
            related_spans = [{"file": file, "line": str(line), "column": str(column)}
                             for file, line, column in map(position, related)] if case["id"] == "partial" else []
            want = ([(case["error"], f"{primary['file']}#{primary['at']}", position(primary), related_spans)]
                    if case.get("error") else [])
            if report != want:
                diagnoses.append(f"{case['id']}: got {report!r}, expected {want!r}")
        else:
            if case.get("error"):
                diagnoses.append(f"{case['id']}: emitted a rule instead of {case['error']}")
                continue
            [body] = [statement[2] for statement in native.statements if statement[0] == "rule"]
            premises = [(entry[1], entry[2][0], entry[2][1]) for entry in body]
            variable = [("var", "g")]
            assert premises == [("positive", "gauge", variable), (case["polarity"], relation, variable)]
    if diagnoses:
        raise NegatedCallMismatch("\n".join(diagnoses))
