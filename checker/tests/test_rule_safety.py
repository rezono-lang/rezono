"""RV-K02: the checker holds rule safety itself. Its loader refuses a rule IR the compiler would refuse wherever a
proof could otherwise pass that proves nothing, and the rest is named here as taken on trust (README, "Trusted
base"). The rejected fixtures are the compiler's (contracts/fixtures/rules/rejected); the compiler is not imported."""

import copy
from pathlib import Path

import pytest
import yaml

from rede_checker.rules import derived_relations, load_rules

RULES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "rules"

# The rejected fixtures the checker loads all the same, each with why that is no way past it. A fixture that is not
# listed must be refused; a listed one that the checker starts to refuse must leave this list.
TRUSTED = {
    "bad_aggregate": "typing: a sum over a column that holds no integers is `invalid`, which blocks (invalid_value)",
    "bad_constant": "typing: the checker compares canonical text and orders only integers, so the condition is false",
    "constant_out_of_range": "typing: an operand outside BIGINT is arithmetic_overflow on every witness",
    "type_mismatch": "typing: text equality is the checker's whole comparison of a string and an integer column",
    "bad_witness": "the witness relation is the engine's layout; the checker reads bindings by variable name",
    "recursive_assignment": "termination is the engine's: a published snapshot is finite and checked as it is",
}


def load(doc):
    rules = load_rules(doc)
    derived_relations(doc, rules)
    return rules


@pytest.mark.parametrize("path", sorted(RULES.glob("rejected/*.yaml")), ids=lambda p: p.stem)
def test_the_checker_refuses_what_the_compiler_refuses_or_names_it_as_trusted(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if path.stem in TRUSTED:
        load(doc)
    else:
        with pytest.raises(ValueError):
            load(doc)


def test_every_trusted_fixture_exists():
    assert set(TRUSTED) <= {p.stem for p in RULES.glob("rejected/*.yaml")}


@pytest.mark.parametrize("path", sorted(RULES.glob("RuleProgram/valid/*.yaml")), ids=lambda p: p.stem)
def test_valid_rule_programs_load(path):
    load(yaml.safe_load(path.read_text(encoding="utf-8")))


def column(name, typ="string"):
    return {"name": name, "type": typ}


def literal(relation, *terms, polarity="positive", stratum="0"):
    return {"relation": relation, "terms": list(terms), "polarity": polarity, "stratum": stratum}


BASE = {"format": "rede.rules/1", "pack": "example", "relations": [
    {"name": "request", "role": "base", "key": [column("id")]},
    {"name": "pair", "role": "base", "key": [column("a"), column("b")]},
    {"name": "size", "role": "base", "key": [column("id"), column("n", "integer")]},
    {"name": "out", "role": "derived", "key": [column("id")]},
    {"name": "sized", "role": "derived", "key": [column("id"), column("n", "integer")]},
]}


def program(head, body, **more):
    relation, *terms = head
    stratum = "1" if more.get("aggregates") or any(b["polarity"] == "negative" for b in body) else "0"
    rule = {"id": "r", "stratum": stratum, "head": {"relation": relation, "terms": terms}, "body": body, **more}
    return {**copy.deepcopy(BASE), "rules": [rule]}


COUNT = {"relation": "pair", "terms": ["?x", "_"], "function": "count", "as": "?n", "stratum": "0"}


def test_a_safe_rule_of_every_shape_loads():
    load_rules(program(("out", "?x"), [literal("request", "?x"), literal("pair", "?x", "?x", polarity="negative")]))
    load_rules(program(("sized", "?x", "?n"), [literal("request", "?x")], aggregates=[COUNT]))
    # A body of aggregates only: a count over the whole relation, with no group and so no premise to bind one.
    load_rules(program(("sized", "all", "?n"), [], aggregates=[{**COUNT, "terms": ["_", "_"]}]))
    load_rules(program(("sized", "?x", "?m"), [literal("size", "?x", "?n")],
                 assignments=[{"var": "?h", "op": "div", "left": "?n", "right": "-2"},
                              {"var": "?m", "op": "add", "left": "?h", "right": "1"}],
                 conditions=[{"op": "gt", "left": "?m", "right": "0"}]))


@pytest.mark.parametrize("doc, message", [
    # The example of the ticket: any y that is in no pair would prove lonely(x).
    (program(("out", "?x"), [literal("request", "?x"), literal("pair", "?x", "?y", polarity="negative")]),
     r"unsafe variable \?y: a negation"),
    (program(("out", "?y"), [literal("request", "?x")]), r"unsafe variable \?y: a head variable"),
    (program(("out", "?x"), [literal("pair", "?x", "?x", polarity="negative")]), r"unsafe variable \?x: a negation"),
    (program(("sized", "?y", "?n"), [literal("request", "?x")], aggregates=[{**COUNT, "terms": ["?y", "_"]}]),
     r"unsafe variable \?y: the group of an aggregate"),
    # The result of an aggregate does not bind what a negation reads: the group is fixed before it is counted.
    (program(("out", "?x"), [literal("request", "?x"), literal("size", "?x", "?n", polarity="negative")],
             aggregates=[COUNT]), r"unsafe variable \?n: a negation"),
    (program(("sized", "?x", "?m"), [literal("request", "?x")],
             assignments=[{"var": "?m", "op": "add", "left": "?n", "right": "1"}]),
     r"unsafe variable \?n: an operand of an assignment"),
    (program(("sized", "?x", "?m"), [literal("size", "?x", "?n")],  # ?h is assigned after it is read
             assignments=[{"var": "?m", "op": "add", "left": "?h", "right": "1"},
                          {"var": "?h", "op": "add", "left": "?n", "right": "1"}]),
     r"unsafe variable \?h: an operand of an assignment"),
    (program(("out", "?x"), [literal("request", "?x")], conditions=[{"op": "eq", "left": "?x", "right": "?y"}]),
     r"unsafe variable \?y: an operand of a condition"),
    (program(("sized", "?x", "?m"), [literal("size", "?x", "?n")],
             assignments=[{"var": "m", "op": "add", "left": "?n", "right": "1"}]), "assignment result m is not a variable"),
    (program(("sized", "?x", "?m"), [literal("size", "?x", "?n")],
             assignments=[{"var": "?m", "op": "div", "left": "?n", "right": "0"}]), "the divisor 0"),
    (program(("sized", "?x", "?m"), [literal("size", "?x", "?n")],
             assignments=[{"var": "?m", "op": "div", "left": "10", "right": "?n"}]), r"the divisor \?n"),
    # Nothing to range over: a fact written as a rule, and a body of negations only, also beside an aggregate.
    (program(("out", "a"), []), "a body has a positive premise, or only aggregates"),
    (program(("out", "a"), [literal("pair", "a", "b", polarity="negative")]),
     "a body has a positive premise, or only aggregates"),
    (program(("sized", "all", "?n"), [literal("pair", "a", "b", polarity="negative")],
             aggregates=[{**COUNT, "terms": ["_", "_"]}]), "a body has a positive premise, or only aggregates"),
    # Without a premise nothing binds a group.
    (program(("sized", "?x", "?n"), [], aggregates=[COUNT]), r"unsafe variable \?x: the group of an aggregate"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_an_unsafe_rule_is_refused(doc, message):
    with pytest.raises(ValueError, match=message):
        load_rules(doc)


@pytest.mark.parametrize("part, message", [
    ({"conditions": [{"op": "gt", "left": "?n", "right": 0}]}, "terms are text"),
    ({"conditions": [{"op": "gt", "left": 7, "right": "?n"}]}, "terms are text"),
    ({"assignments": [{"var": "?m", "op": "add", "left": "?n", "right": 1}]}, "terms are text"),
    ({"assignments": [{"op": "add", "left": "?n", "right": "1"}]}, "names its result"),
    ({"assignments": [{"var": 3, "op": "add", "left": "?n", "right": "1"}]}, "names its result"),
])
def test_a_term_that_is_no_text_is_refused_as_bad_input(part, message):
    """Review of #549 (P2): a JSON number as a term, or an assignment without a result, is a ValueError like
    every other refusal, so the publisher reports it as rule definitions the checker refuses."""
    with pytest.raises(ValueError, match=message):
        load_rules(program(("sized", "?x", "?n"), [literal("size", "?x", "?n")], **part))


def test_a_derived_relation_has_no_value_columns():
    """A witness proves a key. A value on a derived row would be read by an aggregate and proven by nothing."""
    doc = program(("out", "?x"), [literal("request", "?x")])
    doc["relations"][3]["values"] = [column("v", "integer")]
    with pytest.raises(ValueError, match="out: a derived relation is a set"):
        load_rules(doc)


def test_the_first_form_is_held_to_range_restriction_too():
    """The form without a relation catalogue (the proof fixtures, the command line) gets the same check."""
    rule = {"id": "lonely", "stratum": 1, "head": {"relation": "lonely", "terms": ["?x"]},
            "body": [literal("request", "?x", stratum=0), literal("pair", "?x", "?y", polarity="negative", stratum=0)]}
    with pytest.raises(ValueError, match=r"lonely: unsafe variable \?y"):
        load_rules({"rules": [rule]})
