"""The native rule form is a closed contract with independently authored places."""

from copy import deepcopy
import json
from pathlib import Path

from linkml.validator import validate
import pytest

from rezono_canon import canonical_bytes
from rezono_compiler.rezono_module import valid_places


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "contracts/rezono-module.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NATIVE = FIXTURES / "native-rule-form-contract"
LEGACY = ROOT / "contracts/fixtures/rezono-module/ModuleForm/valid/every-member.yaml"
RECORDING = FIXTURES / "listed/eligibility.json"
RECORDED_BYTES = (
    b'{"format":"rezono.module/2","module":{"decls":[{"lines":[".decl listed(item: symbol)",'
    b'"listed(x) :- alpha(x).",".output listed"],"rules":"eligibility"}],"pack":"minimal",'
    b'"rezono":"0","use":[]},"spans":[{"at":"/decls/0","end":"39","line":"3","start":"28"}]}'
)


def contract_errors(document):
    return [result.message for result in validate(document, str(SCHEMA), "ModuleForm").results]


def test_legacy_rule_form_contract():
    for fixture, version, recorded_bytes in (
        (LEGACY, "rezono.module/1", LEGACY.read_bytes()),
        (RECORDING, "rezono.module/2", RECORDED_BYTES),
    ):
        form = json.loads(fixture.read_bytes())
        assert form["format"] == version
        assert contract_errors(form) == []
        assert valid_places(form["module"], form["spans"])
        assert canonical_bytes(form) == recorded_bytes


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Validate native module/3 rule nodes in contracts/rezono-module.yaml. "
    "Read decisions/language-native-rules.md and the authored form beside this test.",
)
def test_native_rule_form_contract():
    fixture = (NATIVE / "rules.json").read_bytes()
    form = json.loads(fixture)
    assert canonical_bytes(form) == fixture

    module, spans = form["module"], form["spans"]
    assert valid_places(module, spans)
    source = (NATIVE / "rules.rezono").read_text(encoding="utf-8")
    fragments = (
        "marked", "item", "explain on_demand", "explain fold", "marked", "x", "y",
        "Marker.near(_, y) and y.near = x", "Marker.near(_, y)", "_", "y", "y.near = x",
        "y.near", "x",
    )
    for span, fragment in zip(spans, fragments, strict=True):
        start, end = int(span["start"]), int(span["end"])
        assert source[start:end] == fragment, span["at"]
        assert span["line"] == str(source.count("\n", 0, start) + 1), span["at"]

    # An independently supplied form carries its own positions. Only the authored fixture is
    # compared with source text. The form alone permits shifted positions and equal offsets.
    shifted = [{**span, "line": "19", "start": "1000", "end": "1000"} for span in spans]
    assert valid_places(module, shifted)
    for malformed in (
        [spans[1], spans[0], *spans[2:]],
        [spans[0], *spans[:-1]],
        spans[:-1],
        [{**spans[0], "at": "/decls/0/unknown"}, *spans[1:]],
        [{**spans[0], "start": 22}, *spans[1:]],
        [{**spans[0], "start": "022"}, *spans[1:]],
        [{**spans[0], "line": "0"}, *spans[1:]],
        [{**spans[0], "end": "21"}, *spans[1:]],
    ):
        assert not valid_places(module, malformed)

    assert contract_errors(form) == []
    assert contract_errors({**form, "spans": shifted}) == []
    for version in ("rezono.module/1", "rezono.module/2"):
        assert contract_errors({**form, "format": version}), version

    signature, clause = module["decls"]
    broken_call = deepcopy(clause)
    broken_call["when"]["and"][0]["call"][1][0]["wildcard"] = False
    malformed_rules = {
        "both heads": (0, {**signature, "args": clause["args"]}),
        "neither head": (0, {"rule": signature["rule"]}),
        "empty signature": (0, {**signature, "columns": []}),
        "empty positional head": (1, {**clause, "args": []}),
        "positional head without a guard": (1, {"rule": clause["rule"], "args": clause["args"]}),
        "positional head with options": (1, {**clause, "options": signature["options"]}),
        "unknown rule member": (0, {**signature, "inferred": True}),
        "unknown column member": (0, {**signature, "columns": [{"name": "item", "type": "Marker", "extra": True}]}),
        "null locals": (1, {**clause, "locals": None}),
        "duplicate option": (0, {**signature, "options": [{"explain": "on_demand"}] * 2}),
        "incompatible storage modes": (0, {**signature, "options": [{"explain": "on_demand"},
                                                                  {"explain": "materialize"}]}),
        "non-wildcard flag": (1, broken_call),
    }
    for case, (position, bad_rule) in malformed_rules.items():
        declarations = module["decls"].copy()
        declarations[position] = bad_rule
        broken_form = {**form, "module": {**module, "decls": declarations}}
        assert contract_errors(broken_form), case
