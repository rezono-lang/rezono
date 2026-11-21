"""The checker refuses a definition that reads a personal slot, independently of the compiler's R054
(decisions/personal-data-handling.md, section 3): no rule head, body (negated or not) or aggregate, no functional
domain and no calculation binding may reference a table that belongs to an attribute the schema bundle marks
`personal: true`: its own table, its state projection (`<table>_state`) and the parameter tables of its bounds,
constant and cardinalities. check_epoch holds it whenever it is handed the bundle, as the publisher does for the
complete epoch. A refusal is a registered code with named arguments (decisions/checker-refusal-register.md); the
tests compare those, never a sentence."""

import pytest

from rezono_checker import check_epoch
from rezono_checker.rules import load_rules

SLOT = "subject.display_name"
PERSONAL = {"id": SLOT, "kind": "subject", "name": "display_name", "table": "subject__display_name",
            "multivalued": False, "personal": True}
OTHER = {"id": "subject.grade", "kind": "subject", "name": "grade", "table": "subject__grade", "multivalued": False}
BUNDLE = {"format": "rezono.schema-bundle/1", "checks": [], "kinds": [{"id": "subject", "table": "subject"}],
          "attributes": [PERSONAL, OTHER]}
LOADED = {t: [] for t in ("rezono__is_a", "rezono__required", "rezono__arrow", "rezono__enum", "rezono__minimum",
                          "rezono__maximum", "rezono__constant", "rezono__minimum_cardinality",
                          "rezono__maximum_cardinality")}
LOADED["rezono__single"] = [("subject", "display_name"), ("subject", "grade")]
CODES = {"personal_slot_in_rule", "personal_slot_in_functional_domain", "personal_slot_in_calculation",
         "bundle_personal_arrow", "bundle_personal_flag_invalid", "bundle_personal_table_invalid"}


def relation(name, *columns, role="base"):
    return {"name": name, "role": role, "key": [{"name": c, "type": "string"} for c in columns]}


def program(body=(), aggregates=(), tables=()):
    """A rule IR with one rule `seen(s)` over a subject, reading what `body` and `aggregates` add; `tables` are
    more base tables, as the compiler declares the tables its rules read."""
    rule = {"id": "seen", "stratum": 1, "head": {"relation": "seen", "terms": ["?s"]},
            "body": [{"relation": "subject", "terms": ["?s"], "polarity": "positive", "stratum": 0}, *body]}
    if aggregates:
        rule["aggregates"] = list(aggregates)
    return {"format": "rezono.rules/1",
            "relations": [relation("subject", "id"), relation("subject__display_name", "subject", "v"),
                          relation("subject__grade", "subject", "v"), *tables,
                          relation("seen", "subject", role="derived")],
            "rules": [rule]}


def atom(table, *terms, polarity="positive"):
    return {"relation": table, "terms": list(terms or ("?s", "?v")), "polarity": polarity, "stratum": 0}


def aggregate(table):
    return {"relation": table, "terms": ["?s", "_"], "function": "count", "as": "?n", "stratum": 0}


def functional(domain):
    """A rezono.rules/2 functional derivation `pick` over `domain`, whose rule reads only the other slot."""
    return {"format": "rezono.rules/2",
            "relations": [relation("subject", "id"), relation("subject__display_name", "subject", "v"),
                          relation("subject__grade", "subject", "v"),
                          {**relation("pick", "subject", "v", role="functional"), "domain": domain,
                           "value": {"name": "value", "type": "string"}, "conflict_policy": "publish"}],
            "rules": [{"id": "pick_r", "stratum": 1, "head": {"relation": "pick", "terms": ["?s", "?g", "?g"]},
                       "body": [atom("subject__grade", "?s", "?g")]}]}


def calculation(table):
    """A calculation program whose one fact reads `table`."""
    date = "2026-11-01"
    value = {"op": "ratio", "args": [{"fact": "amount"}, {"integer": 1}, {"integer": 1}]}
    return {"subject": "Subject", "subject_table": "subject", "as_of": "calc__as_of",
            "facts": [{"id": "amount", "type": "number", "reads": "column", "table": table, "index": 1}],
            "rules": [{"rule": "share", "view": "calc__share", "type": "number", "versions": ["share@v1"]}],
            "versions": [{"id": "share@v1", "version": "v1", "view": "calc__share__v1", "rule": "share",
                          "valid_from": date, "valid_until": "2026-12-01", "known_from": date,
                          "definitions": [{"name": "share", "when": {"boolean": True}, "value": value}]}]}


def refusals(ir, bundle=BUNDLE, calc_ir=None):
    """(valid, the personal-slot refusals with their arguments) of check_epoch over an epoch without rows, handed
    the bundle."""
    report = check_epoch([], {"id": "m-1", "snapshots": []}, load_rules(ir), lambda uri: b"", derived=set(),
                         bundle=bundle, check_metadata=LOADED, calc_ir=calc_ir)
    return report["valid"], [{k: v for k, v in f.items() if k != "severity"} for f in report["findings"]
                             if f["reason"] in CODES]


def in_rule(table):
    return {"reason": "personal_slot_in_rule", "rule": "seen", "relation": table, "field": SLOT}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a definition "
        "that references a table belonging to a personal attribute (its own, `<table>_state` or a parameter "
        "table) in a rule head, body or aggregate (personal_slot_in_rule), as a functional domain "
        "(personal_slot_in_functional_domain) or in a calculation binding (personal_slot_in_calculation), and a "
        "personal mark the bundle cannot carry (bundle_personal_flag_invalid, bundle_personal_table_invalid, "
        "bundle_personal_arrow). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("ir, table", [
    (program(body=[atom("subject__display_name")]), "subject__display_name"),
    (program(body=[atom("subject__display_name", "?s", "x", polarity="negative")]), "subject__display_name"),
    (program(aggregates=[aggregate("subject__display_name")]), "subject__display_name"),
    (program(body=[atom("subject__display_name_state", "?s", "?st", "?r")],
             tables=[relation("subject__display_name_state", "subject", "state", "reason")]),
     "subject__display_name_state"),
    (program(body=[atom("subject__display_name__maximum", "?m")],
             tables=[relation("subject__display_name__maximum", "v")]), "subject__display_name__maximum"),
], ids=["positive", "negative", "aggregate", "state", "parameter"])
def test_a_rule_reading_a_table_of_a_personal_slot_is_refused(ir, table):
    assert refusals(ir) == (False, [in_rule(table)])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a definition "
        "that references a table belonging to a personal attribute (its own, `<table>_state` or a parameter "
        "table) in a rule head, body or aggregate (personal_slot_in_rule), as a functional domain "
        "(personal_slot_in_functional_domain) or in a calculation binding (personal_slot_in_calculation), and a "
        "personal mark the bundle cannot carry (bundle_personal_flag_invalid, bundle_personal_table_invalid, "
        "bundle_personal_arrow). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_rule_writing_a_personal_slot_is_refused():
    ir = program(body=[atom("subject__grade")])
    ir["rules"][0]["head"] = {"relation": "subject__display_name", "terms": ["?s", "?v"]}
    assert refusals(ir) == (False, [in_rule("subject__display_name")])


@pytest.mark.parametrize("ir", [
    program(body=[atom("subject__grade")]),
    program(aggregates=[aggregate("subject__grade")]),
], ids=["body", "aggregate"])
def test_a_rule_reading_only_other_slots_passes(ir):
    assert refusals(ir) == (True, [])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a definition "
        "that references a table belonging to a personal attribute (its own, `<table>_state` or a parameter "
        "table) in a rule head, body or aggregate (personal_slot_in_rule), as a functional domain "
        "(personal_slot_in_functional_domain) or in a calculation binding (personal_slot_in_calculation), and a "
        "personal mark the bundle cannot carry (bundle_personal_flag_invalid, bundle_personal_table_invalid, "
        "bundle_personal_arrow). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_functional_derivation_over_a_personal_slot_is_refused():
    """Its rows range over the domain's keys, the personal values among them. (This epoch has no snapshots, so it
    is not valid either way; only the refusals are compared.)"""
    assert refusals(functional("subject__grade"))[1] == []
    assert refusals(functional("subject__display_name"))[1] == [
        {"reason": "personal_slot_in_functional_domain", "relation": "pick", "field": SLOT}]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a definition "
        "that references a table belonging to a personal attribute (its own, `<table>_state` or a parameter "
        "table) in a rule head, body or aggregate (personal_slot_in_rule), as a functional domain "
        "(personal_slot_in_functional_domain) or in a calculation binding (personal_slot_in_calculation), and a "
        "personal mark the bundle cannot carry (bundle_personal_flag_invalid, bundle_personal_table_invalid, "
        "bundle_personal_arrow). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_calculation_reading_a_personal_slot_is_refused():
    ir = program(body=[atom("subject__grade")])
    assert refusals(ir, calc_ir=calculation("subject__grade"))[1] == []
    assert refusals(ir, calc_ir=calculation("subject__display_name"))[1] == [
        {"reason": "personal_slot_in_calculation", "field": "facts.amount", "relation": "subject__display_name"}]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a definition "
        "that references a table belonging to a personal attribute (its own, `<table>_state` or a parameter "
        "table) in a rule head, body or aggregate (personal_slot_in_rule), as a functional domain "
        "(personal_slot_in_functional_domain) or in a calculation binding (personal_slot_in_calculation), and a "
        "personal mark the bundle cannot carry (bundle_personal_flag_invalid, bundle_personal_table_invalid, "
        "bundle_personal_arrow). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("bundle, refusal", [
    ({**BUNDLE, "attributes": [{**PERSONAL, "personal": "true"}, OTHER]},
     {"reason": "bundle_personal_flag_invalid", "relation": SLOT}),
    ({**BUNDLE, "attributes": [{**PERSONAL, "table": "subject__grade"}, OTHER]},
     {"reason": "bundle_personal_table_invalid", "relation": SLOT}),
    ({**BUNDLE, "arrows": [{"id": "subject.mentor", "kind": "subject", "name": "mentor", "table": "subject__mentor",
                            "target": "subject", "multivalued": False, "personal": True}]},
     {"reason": "bundle_personal_arrow", "relation": "subject.mentor"}),
], ids=["flag-text", "other-table", "arrow"])
def test_a_personal_mark_the_bundle_cannot_carry_is_refused(bundle, refusal):
    """`personal` is a boolean on an attribute whose table is `<kind>__<name>` (contracts/bundle.yaml, section 2 of
    the decision): anything else is refused, never read as not personal."""
    valid, found = refusals(program(body=[atom("subject__grade")]), bundle)
    assert (valid, found) == (False, [refusal])
