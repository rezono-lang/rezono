"""A derived property whose type is a kind lowers to a derived relation named as a slot row
(decisions/language-readable-rules.md, section 1, Lowering). The expected relation and clause are written out below
from that decision; the counter-case compiles the same link written as a rule with the forward slot rows."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from expression_packs import ROOT, compile_rules, register
from rezono_compiler import pack
from support import FIXTURE

KINDS = """rezono 0
pack minimal

kind Offer world closed

kind Product world closed
  offers: Offer*

kind Demand world closed
  product: Product
"""
PROPERTY = KINDS + "\nextend Demand\n  derived offers: Offer* = product.offers\n"
RULE = KINDS + "\nrule offers(d: Demand, o: Offer) when d in Demand and Demand.product(d, p) and Product.offers(p, o)\n"


def compiled(tmp_path: Path, source: str) -> dict:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    folder = directory / "rezono"
    folder.mkdir()
    module, form = folder / "demand.rezono", folder / "demand.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    register(directory, {"module": "rezono/demand.rezono", "form": "rezono/demand.json", "layer": "facts"})
    return compile_rules(directory)


def renamed(terms: list[str], names: dict) -> list[str]:
    """Variables renamed in order of first occurrence, so the test fixes no variable name of the lowering."""
    return [names.setdefault(t, f"?v{len(names)}") if t.startswith("?") else t for t in terms]


def clause(program: dict, relation: str) -> tuple:
    [rule] = [rule for rule in program["rules"] if rule["head"]["relation"] == relation]
    names: dict = {}
    head = renamed(rule["head"]["terms"], names)
    body = [(item["polarity"], item["relation"], renamed(item["terms"], names)) for item in rule["body"]]
    return head, body, rule.get("conditions", []), rule.get("aggregates", [])


class MissingDerivedProperty(AssertionError):
    """The compiler refused the derived property, or lowered it otherwise than the decision gives."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingDerivedProperty,
    reason="extra: decisions/language-readable-rules.md: Lower a derived value whose type is a kind (T, T?, T* or "
           "T+) to a derived relation <kind>__<name> with key [id, v] and one clause that reads the subject's "
           "membership and then the premises of the expression, in compiler/rezono_compiler/rezono_module.py "
           "and native_rule_lowering.py, instead of refusing it as a derived value that is not lowered. Read "
           "section 1, Lowering. A property over an inverse slot is not part of this test.",
)
def test_lower_derived_property(tmp_path):
    # Counter-case: the same link written as a rule over the forward slot rows lowers today.
    rule = compiled(tmp_path / "rule", RULE)
    assert clause(rule, "offers") == (
        ["?v0", "?v1"],
        [("positive", "demand", ["?v0"]), ("positive", "demand__product", ["?v0", "?v2"]),
         ("positive", "product__offers", ["?v2", "?v1"])],
        [], [],
    )

    try:
        program = compiled(tmp_path / "property", PROPERTY)
    except pack.CompileError as error:
        raise MissingDerivedProperty(str(error)) from error
    relations = {item["name"]: item for item in program["relations"]}
    found = relations.get("demand__offers")
    expected_relation = {"name": "demand__offers", "role": "derived",
                         "key": [{"name": "id", "type": "string"}, {"name": "v", "type": "string"}]}
    actual_relation = None if found is None else {key: found.get(key) for key in expected_relation}
    expected_clause = (
        ["?v0", "?v1"],
        [("positive", "demand", ["?v0"]), ("positive", "demand__product", ["?v0", "?v2"]),
         ("positive", "product__offers", ["?v2", "?v1"])],
        [], [],
    )
    actual_clause = clause(program, "demand__offers") if found is not None else None
    if actual_relation != expected_relation or actual_clause != expected_clause or "offers" in relations:
        raise MissingDerivedProperty(json.dumps({"relation": actual_relation, "clause": actual_clause,
                                                 "relations": sorted(relations)}, indent=2))
