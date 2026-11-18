"""The module format owns the shape of embedded, ordered relational rule lines."""

from pathlib import Path

import pytest
from linkml.validator import validate

SCHEMA = str(Path(__file__).resolve().parents[2] / "rezono-module.yaml")
BLOCK = {"rules": "inventory", "lines": [".decl ready(x: symbol)", "", "// Public inventory",
                                         "ready(x) :- shelf(x).", ".output ready"]}


def form(version, declarations):
    return {"format": f"rezono.module/{version}", "module": {"pack": "sample", "use": [], "decls": declarations},
            "spans": [{"at": f"/decls/{i}", "line": str(i + 2), "start": "18", "end": "27"}
                      for i in range(len(declarations))]}


def errors(document):
    return [item.message for item in validate(document, SCHEMA, "ModuleForm").results]


def test_version_one_preserves_the_original_module_shape():
    assert errors(form(1, [])) == []
    assert errors(form(1, [BLOCK]))


def test_version_two_accepts_only_the_typed_rules_declaration():
    assert errors(form(2, [BLOCK])) == []
    for invalid in ({"rules": "inventory"}, {"lines": BLOCK["lines"]},
                    {**BLOCK, "extra": "unused"}, {**BLOCK, "lines": "ready(x)."},
                    {**BLOCK, "lines": [42]}, {**BLOCK, "rules": ["inventory"]}):
        assert errors(form(2, [invalid])), invalid
    assert errors(form(3, [BLOCK]))


@pytest.mark.parametrize("line_break", ["\n", "\r"], ids=["lf", "cr"])
@pytest.mark.parametrize("suffix", ["ready(x) :- shelf(x).", ""], ids=["embedded", "trailing"])
def test_rule_lines_reject_line_breaks_within_an_element(line_break, suffix):
    declaration = {**BLOCK, "lines": ["", ".decl ready(x: symbol)" + line_break + suffix]}
    assert errors(form(2, [declaration]))
