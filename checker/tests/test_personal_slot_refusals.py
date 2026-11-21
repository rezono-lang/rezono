"""The checker refuses a definition that reads a personal slot, independently of the compiler's R054
(decisions/personal-data-handling.md, section 3): no rule head, body (negated or not) or aggregate, no functional
domain and no calculation binding may reference a table of a slot the schema bundle marks `personal: true`: its own
table or its state table (`<table>_state`). The parameter tables of its bounds, constant and cardinalities hold
values that are the same for everyone, so a rule may read them (the owner, 21-11). check_epoch holds it whenever it
is handed the bundle, as the publisher does for the complete epoch, and check_role for each role.

A refusal is a registered code with named arguments (decisions/checker-refusal-register.md), and each argument has
one meaning in all of them: `rule` is the id of the rule that reads, `relation` the table it reads, `field` the
personal slot (`<kind>.<slot>`) of the bundle. The tests compare the code and its arguments, never a sentence."""

import pytest

from rezono_checker import check_epoch
from rezono_checker.access import check_role
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
    """A rezono.rules/2 functional derivation `pick` over `domain`, whose rule `pick_r` reads only the other slot."""
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


def personal(findings):
    """The personal-slot refusals among `findings`, each its code and arguments."""
    return [{k: v for k, v in f.items() if k != "severity"} for f in findings if f["reason"] in CODES]


def refusals(ir, bundle=BUNDLE, calc_ir=None):
    """(valid, the personal-slot refusals) of check_epoch over an epoch without rows, handed the bundle."""
    report = check_epoch([], {"id": "m-1", "snapshots": []}, load_rules(ir), lambda uri: b"", derived=set(),
                         bundle=bundle, check_metadata=LOADED, calc_ir=calc_ir)
    return report["valid"], personal(report["findings"])


def in_rule(table, rule="seen"):
    return {"reason": "personal_slot_in_rule", "rule": rule, "relation": table, "field": SLOT}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a rule that "
        "reads the table or the state projection of a personal attribute in a positive or negative body literal or "
        "an aggregate, with personal_slot_in_rule (rule, relation, field). Waits for "
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
], ids=["positive", "negative", "aggregate", "state"])
def test_a_rule_reading_a_personal_slot_is_refused(ir, table):
    assert refusals(ir) == (False, [in_rule(table)])


def test_a_rule_reading_a_parameter_table_of_a_personal_slot_passes():
    """A bound of a personal slot is the same for everyone, so it is not personal (the owner, 21-11)."""
    ir = program(body=[atom("subject__display_name__maximum", "?m")],
                 tables=[relation("subject__display_name__maximum", "v")])
    assert refusals(ir) == (True, [])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch refuses a rule whose head is the table of a "
        "personal attribute, with personal_slot_in_rule (rule, relation, field). Waits for "
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
        "extra: decisions/personal-data-handling.md: check_epoch refuses a functional derivation over the table "
        "of a personal attribute as its domain, with personal_slot_in_functional_domain (rule: a rule that "
        "derives it, relation: the domain table, field). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_functional_derivation_over_a_personal_slot_is_refused():
    """Its rows range over the domain's keys, the personal values among them. (This epoch has no snapshots, so it
    is not valid either way; only the refusals are compared.)"""
    assert refusals(functional("subject__grade"))[1] == []
    assert refusals(functional("subject__display_name"))[1] == [
        {"reason": "personal_slot_in_functional_domain", "rule": "pick_r", "relation": "subject__display_name",
         "field": SLOT}]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch refuses a calculation whose fact reads the table "
        "of a personal attribute, with personal_slot_in_calculation (relation, field). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_calculation_reading_a_personal_slot_is_refused():
    ir = program(body=[atom("subject__grade")])
    assert refusals(ir, calc_ir=calculation("subject__grade"))[1] == []
    assert refusals(ir, calc_ir=calculation("subject__display_name"))[1] == [
        {"reason": "personal_slot_in_calculation", "relation": "subject__display_name", "field": SLOT}]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_role refuses a role's rule IR that reads the table of a "
        "personal attribute, with personal_slot_in_rule (rule, relation, field). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_role_whose_rules_read_a_personal_slot_is_refused():
    """The role check derives the role's reads from the complete snapshots, the bundle and the rule IR; a rule IR
    that reads a personal slot is refused before anything is read. Only the refusals are compared."""
    def found(ir):
        return personal(check_role("reader", {}, {}, None, BUNDLE, ir)[1])

    assert found(program(body=[atom("subject__grade")])) == []
    assert found(program(body=[atom("subject__display_name")])) == [in_rule("subject__display_name")]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: A `personal` flag that is not a boolean is refused with "
        "bundle_personal_flag_invalid (field), never read as not personal. Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_personal_flag_that_is_not_a_boolean_is_refused():
    bundle = {**BUNDLE, "attributes": [{**PERSONAL, "personal": "true"}, OTHER]}
    assert refusals(program(body=[atom("subject__grade")]), bundle) == (
        False, [{"reason": "bundle_personal_flag_invalid", "field": SLOT}])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: A personal attribute whose table is not `<kind>__<name>` is "
        "refused with bundle_personal_table_invalid (field), so the table rules read cannot slip past. Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_personal_attribute_on_another_table_is_refused():
    bundle = {**BUNDLE, "attributes": [{**PERSONAL, "table": "subject__grade"}, OTHER]}
    assert refusals(program(body=[atom("subject__grade")]), bundle) == (
        False, [{"reason": "bundle_personal_table_invalid", "field": SLOT}])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: An arrow marked personal is refused with "
        "bundle_personal_arrow (field): `personal` goes on a scalar attribute (section 2). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_personal_arrow_is_refused():
    arrow = {"id": "subject.mentor", "kind": "subject", "name": "mentor", "table": "subject__mentor",
             "target": "subject", "multivalued": False, "personal": True}
    valid, found = refusals(program(body=[atom("subject__grade")]), {**BUNDLE, "arrows": [arrow]})
    assert (valid, found) == (False, [{"reason": "bundle_personal_arrow", "field": "subject.mentor"}])
