"""The checker refuses a rule IR that reads a personal slot, independently of the compiler's R054
(decisions/personal-data-handling.md, section 3): no rule head, body (negated or not) or aggregate, and no
functional domain, may reference a table that belongs to an attribute the schema bundle marks `personal: true`.
check_epoch holds it whenever it is handed the bundle, as the publisher does for the complete epoch."""

import pytest

from rezono_checker import check_epoch
from rezono_checker.rules import load_rules

BUNDLE = {
    "format": "rezono.schema-bundle/1", "checks": [],
    "kinds": [{"id": "subject", "table": "subject"}],
    "attributes": [
        {"kind": "subject", "name": "display_name", "table": "subject__display_name", "multivalued": False,
         "personal": True},
        {"kind": "subject", "name": "grade", "table": "subject__grade", "multivalued": False},
    ],
}
LOADED = {t: [] for t in ("rezono__is_a", "rezono__required", "rezono__arrow", "rezono__enum", "rezono__minimum",
                          "rezono__maximum", "rezono__constant", "rezono__minimum_cardinality",
                          "rezono__maximum_cardinality")}
LOADED["rezono__single"] = [("subject", "display_name"), ("subject", "grade")]


def relation(name, *columns, role="base"):
    return {"name": name, "role": role, "key": [{"name": c, "type": "string"} for c in columns]}


def program(body=(), aggregates=()):
    """A rule IR with one rule `seen(s)` over a subject, reading what `body` and `aggregates` add."""
    rule = {"id": "seen", "stratum": 1, "head": {"relation": "seen", "terms": ["?s"]},
            "body": [{"relation": "subject", "terms": ["?s"], "polarity": "positive", "stratum": 0}, *body]}
    if aggregates:
        rule["aggregates"] = list(aggregates)
    return {"format": "rezono.rules/1",
            "relations": [relation("subject", "id"), relation("subject__display_name", "subject", "v"),
                          relation("subject__grade", "subject", "v"), relation("seen", "subject", role="derived")],
            "rules": [rule]}


def atom(table, polarity="positive", value="?v"):
    return {"relation": table, "terms": ["?s", value], "polarity": polarity, "stratum": 0}


def aggregate(table):
    return {"relation": table, "terms": ["?s", "_"], "function": "count", "as": "?n", "stratum": 0}


def findings(ir, bundle=BUNDLE):
    """(valid, [(reason, rule, relation)]) of check_epoch over an epoch without rows, handed the bundle."""
    report = check_epoch([], {"id": "m-1", "snapshots": []}, load_rules(ir), lambda uri: b"", derived=set(),
                         bundle=bundle, check_metadata=LOADED)
    return report["valid"], [(f["reason"], f.get("rule"), f.get("relation")) for f in report["findings"]]


def functional(domain):
    """A rezono.rules/2 functional derivation `pick` over `domain`, whose rule reads only the other slot."""
    return {"format": "rezono.rules/2",
            "relations": [relation("subject", "id"), relation("subject__display_name", "subject", "v"),
                          relation("subject__grade", "subject", "v"),
                          {**relation("pick", "subject", "v", role="functional"), "domain": domain,
                           "value": {"name": "value", "type": "string"}, "conflict_policy": "publish"}],
            "rules": [{"id": "pick_r", "stratum": 1, "head": {"relation": "pick", "terms": ["?s", "?g", "?g"]},
                       "body": [atom("subject__grade", value="?g")]}]}


def with_table(ir, table):
    """The rule IR with one more base table, as the compiler declares the tables its rules read."""
    return {**ir, "relations": [*ir["relations"], relation(table, "v")]}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a rule IR "
        "that references a table belonging to a personal attribute (its own, `_state` or a parameter table) in a "
        "rule head, body or aggregate or as a functional domain, with the registered refusal personal_slot_read "
        "(rule, relation); a personal mark other than true, or on another table than `<kind>__<name>`, is "
        "malformed_bundle. Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("ir, relation_read", [
    (program(body=[atom("subject__display_name")]), "subject__display_name"),
    (program(body=[atom("subject__display_name", "negative", "x")]), "subject__display_name"),
    (program(aggregates=[aggregate("subject__display_name")]), "subject__display_name"),
    (with_table(program(body=[{**atom("subject__display_name_state"), "terms": ["?s", "?st", "?r"]}]),
                "subject__display_name_state"), "subject__display_name_state"),
    (with_table(program(body=[{**atom("subject__display_name__maximum"), "terms": ["?m"]}]),
                "subject__display_name__maximum"), "subject__display_name__maximum"),
], ids=["positive", "negative", "aggregate", "state", "parameter"])
def test_a_rule_reading_a_personal_slot_is_refused(ir, relation_read):
    """Every table that belongs to the personal attribute: its own, its state projection, its parameters."""
    assert findings(ir) == (False, [("personal_slot_read", "seen", relation_read)])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a rule IR "
        "that references a table belonging to a personal attribute (its own, `_state` or a parameter table) in a "
        "rule head, body or aggregate or as a functional domain, with the registered refusal personal_slot_read "
        "(rule, relation); a personal mark other than true, or on another table than `<kind>__<name>`, is "
        "malformed_bundle. Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_rule_writing_a_personal_slot_is_refused():
    ir = program(body=[atom("subject__grade")])
    ir["rules"][0]["head"] = {"relation": "subject__display_name", "terms": ["?s", "?v"]}
    assert findings(ir) == (False, [("personal_slot_read", "seen", "subject__display_name")])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a rule IR "
        "that references a table belonging to a personal attribute (its own, `_state` or a parameter table) in a "
        "rule head, body or aggregate or as a functional domain, with the registered refusal personal_slot_read "
        "(rule, relation); a personal mark other than true, or on another table than `<kind>__<name>`, is "
        "malformed_bundle. Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_a_functional_derivation_over_a_personal_slot_is_refused():
    """Its rows range over the domain's keys, the personal values among them. (This epoch has no snapshots, so
    other findings come too; only the refusal is compared.)"""
    def refused(ir):
        return [f for f in findings(ir)[1] if f[0] == "personal_slot_read"]
    assert refused(functional("subject__grade")) == []
    assert refused(functional("subject__display_name")) == [("personal_slot_read", "pick", "subject__display_name")]


@pytest.mark.parametrize("ir", [
    program(body=[atom("subject__grade")]),
    program(aggregates=[aggregate("subject__grade")]),
], ids=["body", "aggregate"])
def test_a_rule_reading_only_other_slots_passes(ir):
    assert findings(ir) == (True, [])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: check_epoch, handed the schema bundle, refuses a rule IR "
        "that references a table belonging to a personal attribute (its own, `_state` or a parameter table) in a "
        "rule head, body or aggregate or as a functional domain, with the registered refusal personal_slot_read "
        "(rule, relation); a personal mark other than true, or on another table than `<kind>__<name>`, is "
        "malformed_bundle. Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("attribute", [
    {"kind": "subject", "name": "display_name", "table": "subject__display_name", "multivalued": False,
     "personal": "true"},
    {"kind": "subject", "name": "display_name", "table": "subject__display_name", "multivalued": False,
     "personal": False},
    {"kind": "subject", "name": "display_name", "multivalued": False, "personal": True},
    {"kind": "subject", "name": "display_name", "table": "subject__grade", "multivalued": False, "personal": True},
], ids=["text", "false", "no-table", "other-table"])
def test_a_personal_mark_that_is_not_true_on_a_table_is_a_malformed_bundle(attribute):
    """`personal` is true or left out (contracts/bundle.yaml, Attribute): anything else is refused, never read as
    not personal."""
    bundle = BUNDLE | {"attributes": [attribute, BUNDLE["attributes"][1]]}
    assert findings(program(body=[atom("subject__grade")]), bundle) == (False, [("malformed_bundle", None, None)])
