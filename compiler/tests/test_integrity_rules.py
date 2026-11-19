"""Integrity checks as invariant rules with witnesses (decisions/integrity-checks-as-rules.md), on the minimal,
domain-free fixture pack with one planted violation per generic check.

The expected rows are worked out by hand from ROWS below. They are also exactly what the SQL check views
(`validation_result`) gave on the same rows when this file was written: the SQL is an independent second
reading of the same checks. Each test runs the compiled rule program on the batch backend with witnesses, holds
the epoch to the independent checker, and, where Soufflé is installed, compares the rows with Soufflé."""

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml

from support import FIXTURE
from rezono_compiler import emit, pack
from rezono_compiler import rules as ir

ROWS = {
    "alpha": [("a1",), ("a2",), ("a3",)],
    "alpha__title": [("a1", "t"), ("a2", "t"), ("a2", "u")],      # a2 has two titles, a3 none
    "alpha__size": [("a1", 3), ("a2", 12), ("a3", -1), ("x9", 5)],  # 0..9; x9 is no alpha
    "alpha__rank": [("a1", 3), ("a2", 4)],                          # the constant 3
    "beta": [("b1",), ("b2",), ("b3",)],
    "beta__alpha": [("b1", "a1"), ("b2", "zz")],                    # zz is no alpha; b3 has none
    "beta__state": [("b1", "low"), ("b2", "mid"), ("x8", "low")],   # mid is no state; x8 is no beta
    "beta__tags": [("b2", "t1"), ("b2", "t2"), ("b2", "t3"), ("b3", "t1")],  # one or two tags
    "beta__mark": [("b1", "m"), ("b2", "n")],                       # the constant m
    "root": [("l2",)],
    "leaf": [("l1",), ("l2",)],                                     # l1 is no root
}


def with_checks(schema: dict) -> None:
    """Every generic check kind on the fixture: a constant per value type, a cardinality range, a subkind."""
    alpha, beta = schema["classes"]["Alpha"]["attributes"], schema["classes"]["Beta"]["attributes"]
    alpha["rank"] = {"range": "integer", "equals_number": 3}
    beta["tags"] = {"multivalued": True, "minimum_cardinality": 1, "maximum_cardinality": 2}
    beta["mark"] = {"equals_string": "m"}
    schema["classes"]["Root"] = {"attributes": {"id": {"identifier": True}}}
    schema["classes"]["Leaf"] = {"is_a": "Root"}


@pytest.fixture
def fixture(tmp_path) -> Path:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    with_checks(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")
    return d


def program(files: dict, names, missing):
    """The compiled rule program, with each named relation a generated invariant in it."""
    doc = json.loads(files["ir/rules.json"]) if "ir/rules.json" in files else None
    prog = ir.load(doc) if doc else None
    absent = [n for n in names if prog is None or n not in prog.relations]
    if absent:
        raise missing(f"the rule IR has no relation {', '.join(absent)}")
    for name in names:
        rel = prog.relations[name]
        assert (rel.role, rel.invariant, rel.absence) == ("derived", True, True), name
    return doc, prog


def data(files: dict) -> dict:
    """The fact rows, and the metadata and enumeration rows the compiled definition gives."""
    params = json.loads(files["engine/parameters.json"])
    return {t: [tuple(r.values()) for r in rs] for t, rs in params.items()} | ROWS


def held(fixture, tmp_path, expected: dict, missing) -> None:
    """The rows of each generated invariant are `expected`, each with a witness the checker accepts and reports
    as a violated invariant, and nothing else is wrong with the epoch."""
    pytest.importorskip("duckdb")
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations, load_rules
    from rezono_compiler import batch, explain

    files = emit.compile_pack(pack.read(fixture))
    doc, prog = program(files, sorted(expected), missing)
    rows = data(files)
    con = batch.connect(prog, rows)
    batch.compute(con, prog, witnesses=True)
    derived = batch.read(con, prog)
    for name, want in expected.items():
        assert {tuple(map(str, r)) for r in derived[name]} == want, name
    base = [n for n, r in prog.relations.items() if r.role == "base"]
    ex = explain.Explainer(prog, batch.read(con, prog, base) | derived, batch.witnesses(con, prog))
    snaps = {r: ex.snapshot(r).encode() for r in prog.relations}
    manifest = {"id": "m", "snapshots": [
        {"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
         "sha256": hashlib.sha256(b).hexdigest()} for r, b in sorted(snaps.items())]}
    rules = load_rules(doc)
    report = check_epoch(ex.chosen(), manifest, rules, snaps.__getitem__, derived=derived_relations(doc, rules))
    errors = [f for f in report["findings"] if f["severity"] == "error"]
    assert [f for f in errors if f["reason"] != "invariant_violated"] == []
    found = Counter(f["relation"] for f in errors)
    assert {n: found[n] for n in expected} == {n: len(want) for n, want in expected.items()}
    if shutil.which("souffle") is not None:  # the oracle; CI has the pinned Soufflé
        import souffle
        oracle = souffle.run(prog, rows, tmp_path)
        assert {n: oracle[n] for n in expected} == {n: {tuple(map(str, r)) for r in derived[n]} for n in expected}


class MissingCardinalityRules(AssertionError):
    """The rule IR has no generated rezono__cardinality_violation."""


class MissingReferenceRules(AssertionError):
    """The rule IR has no generated rezono__reference_violation or rezono__reference_integer_violation."""


class MissingTotalityRules(AssertionError):
    """The rule IR has no generated rezono__totality_violation."""


class MissingFunctionalityRules(AssertionError):
    """The rule IR has no generated rezono__functionality_violation."""


class MissingValueRangeRules(AssertionError):
    """The rule IR has no generated rezono__value_range_violation or rezono__value_range_integer_violation."""


@pytest.mark.xfail(
    strict=True,
    raises=(MissingCardinalityRules, AssertionError),
    reason=(
        "extra: decisions/integrity-checks-as-rules.md: Generate the cardinality check as rules, next to its SQL: "
        "the metadata tables as closed base relations of the rule IR, the structural relations rezono__in_kind, "
        "rezono__text_value, rezono__integer_value and rezono__enum_member, and the invariant "
        "rezono__cardinality_violation(kind, slot, id, n), marked invariant and absence, with the two rules the "
        "decision gives. The pull request states the duration of the checks and the number of witnesses on the "
        "largest example before and after. The SQL of the kind stays until its own task."
    ),
)
def test_cardinality_violations_are_invariant_rows_with_witnesses(fixture, tmp_path):
    held(fixture, tmp_path, {"rezono__cardinality_violation": {("beta", "tags", "b1", "0"), ("beta", "tags", "b2", "3")}},
         MissingCardinalityRules)


@pytest.mark.xfail(
    strict=True,
    raises=(MissingReferenceRules, AssertionError),
    reason=(
        "extra: decisions/integrity-checks-as-rules.md: Waits for compiler/tests/test_integrity_rules.py--"
        "test_cardinality_violations_are_invariant_rows_with_witnesses (the metadata and structural relations). "
        "Then generate the reference check as rules, next to its SQL: rezono__reference_violation(kind, slot, id, "
        "value) with text values and rezono__reference_integer_violation with integer values, for a missing parent "
        "kind, a value of no element and an arrow to no element, as the decision gives."
    ),
)
def test_reference_violations_are_invariant_rows_with_witnesses(fixture, tmp_path):
    held(fixture, tmp_path, {
        "rezono__reference_violation": {("leaf", "is_a", "l1", ""), ("beta", "alpha", "b2", "zz"),
                                        ("beta", "state", "x8", "low")},
        "rezono__reference_integer_violation": {("alpha", "size", "x9", "5")},
    }, MissingReferenceRules)


@pytest.mark.xfail(
    strict=True,
    raises=(MissingTotalityRules, AssertionError),
    reason=(
        "extra: decisions/integrity-checks-as-rules.md: Waits for compiler/tests/test_integrity_rules.py--"
        "test_reference_violations_are_invariant_rows_with_witnesses. Then generate the totality check as rules, "
        "next to its SQL: rezono__totality_violation(kind, slot, id) for an element of a kind with a required slot "
        "and no value in it, as the decision gives."
    ),
)
def test_totality_violations_are_invariant_rows_with_witnesses(fixture, tmp_path):
    held(fixture, tmp_path, {"rezono__totality_violation": {("alpha", "title", "a3"), ("beta", "alpha", "b3")}},
         MissingTotalityRules)


@pytest.mark.xfail(
    strict=True,
    raises=(MissingFunctionalityRules, AssertionError),
    reason=(
        "extra: decisions/integrity-checks-as-rules.md: Waits for compiler/tests/test_integrity_rules.py--"
        "test_totality_violations_are_invariant_rows_with_witnesses. Then generate the functionality check as "
        "rules, next to its SQL: rezono__functionality_violation(kind, slot, id, n) for a single-valued slot with "
        "more than one value, as the decision gives."
    ),
)
def test_functionality_violations_are_invariant_rows_with_witnesses(fixture, tmp_path):
    held(fixture, tmp_path, {"rezono__functionality_violation": {("alpha", "title", "a2", "2")}},
         MissingFunctionalityRules)


@pytest.mark.xfail(
    strict=True,
    raises=(MissingValueRangeRules, AssertionError),
    reason=(
        "extra: decisions/integrity-checks-as-rules.md: Waits for compiler/tests/test_integrity_rules.py--"
        "test_functionality_violations_are_invariant_rows_with_witnesses. Then generate the value range check as "
        "rules, next to its SQL: rezono__value_range_violation(kind, slot, id, value) for text (enumeration, "
        "constant) and rezono__value_range_integer_violation for integers (bounds, constant), with the metadata "
        "table rezono__constant split into rezono__constant and rezono__constant_integer, as the decision gives. "
        "The checker's comparison of the metadata with the bundle learns the new table."
    ),
)
def test_value_range_violations_are_invariant_rows_with_witnesses(fixture, tmp_path):
    held(fixture, tmp_path, {
        "rezono__value_range_violation": {("beta", "state", "b2", "mid"), ("beta", "mark", "b2", "n")},
        "rezono__value_range_integer_violation": {("alpha", "size", "a2", "12"), ("alpha", "size", "a3", "-1"),
                                                  ("alpha", "rank", "a2", "4")},
    }, MissingValueRangeRules)
