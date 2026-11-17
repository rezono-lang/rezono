"""Units and dimension checks (P10.3, ticket D04): a pack declares its units on LinkML types, an attribute has the
unit of its type, and calc and the rules check dimensions. The three cases of P10.3's done-when that are units
(`GiB + Cents`, `> 384` against GiB without a unit) fail with the place where they are written; the example packs,
which declare no unit, compile as before (test_types, the goldens)."""

from __future__ import annotations

import json
import re
import shutil
from fractions import Fraction
from pathlib import Path

import pytest
import yaml

from rezono_compiler import calc, emit, pack, types
from rezono_compiler.pack import CompileError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "calc"
# Units as a pack declares them: neutral names, no domain. The schema states them; the compiler knows none.
UNITS = {
    "B": {"typeof": "integer", "annotations": {"dimension": "data"}},
    "GiB": {"typeof": "integer", "annotations": {"unit": "2^30 B"}},
    "MiB": {"typeof": "integer", "annotations": {"unit": "1024 KiB"}},  # defined by a unit declared after it
    "KiB": {"typeof": "integer", "annotations": {"unit": "1024 B"}},
    "s": {"typeof": "integer", "annotations": {"dimension": "time"}},
    "h": {"typeof": "integer", "annotations": {"unit": "3600 s"}},
    "Cents": {"typeof": "integer", "annotations": {"currency": "EUR"}},
    "CentsPerHour": {"typeof": "integer", "annotations": {"unit": "Cents per h"}},
    "Memory": {"typeof": "GiB"},  # a type of a unit type has its unit
}


def unit_pack(tmp_path: Path, rules: list[dict] | None = None, dl: str | None = None, units: dict | None = None) -> Path:
    """The calc fixture with the units above, quantity attributes on the subject, and the given calc rules
    (calc/units.yaml) or rule file (rules/units.dl)."""
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    f = d / "schema" / "calc.yaml"
    s = yaml.safe_load(f.read_text(encoding="utf-8"))
    s["types"] = units if units is not None else UNITS
    s["classes"]["Item"]["attributes"] |= {
        "memory": {"range": "Memory", "required": True}, "cache": {"range": "MiB", "required": True},
        "price": {"range": "Cents", "required": True}, "runtime": {"range": "h", "required": True},
        "rate": {"range": "CentsPerHour", "required": True}}
    f.write_text(yaml.safe_dump(s, sort_keys=False), encoding="utf-8", newline="\n")
    if rules is not None:
        (d / "calc" / "units.yaml").write_text(yaml.safe_dump(
            {"format": "rezono.calc/1", "pack": "calc", "subject": "item", "rules": rules}, sort_keys=False),
            encoding="utf-8", newline="\n")
    if dl is not None:
        (d / "rules" / "units.dl").write_text(dl, encoding="utf-8", newline="\n")
    return d


def rule(name: str, value: dict, unit: str = "x", when: dict | None = None) -> dict:
    return {"id": f"{name}@1", "rule": name, "version": "1", "output": f"{name}.value", "unit": unit,
            "valid_from": "2026-01-01", "valid_until": "2027-01-01", "known_from": "2025-12-01",
            "definitions": [{"name": "base", "when": when or {"boolean": True}, "value": value}]}


def refused(d: Path) -> str:
    with pytest.raises(CompileError) as e:
        pack.read(d)
    return str(e.value)


def line_of(path: Path, text: str) -> int:
    """The line (from 1) of the first line of a file that holds `text`."""
    return next(i for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if text in line)


def test_a_pack_declares_its_units_and_an_attribute_has_the_unit_of_its_type(tmp_path):
    model = pack.read(unit_pack(tmp_path))
    u = model.units
    assert (u["GiB"].factor, u["GiB"].dimension) == (Fraction(2**30), (("data", 1),))
    assert u["MiB"] == types.Unit("other name", Fraction(2**20), (("data", 1),))  # the name is no part of a unit
    assert (u["h"].factor, u["h"].text) == (3600, "time")
    assert (u["Cents"].currency, u["Cents"].text) == ("EUR", "money EUR")
    assert (u["CentsPerHour"].factor, u["CentsPerHour"].text) == (Fraction(1, 3600), "money EUR/time")
    assert "Memory" not in u  # it has a unit, and declares none
    memory = model.slot("item", "memory")
    assert (memory.unit, memory.type.case, memory.type.sql) == ("GiB", "quantity", "BIGINT")
    assert memory.type.semantic == {"case": "quantity", "base": "integer", "range": "Memory", "unit": "GiB"}
    price = model.slot("item", "price")  # money stays money: its currency, no unit beside it
    assert (price.unit, price.currency, price.type.case) == ("Cents", "EUR", "money")
    bundle = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])
    attribute = next(a for a in bundle["attributes"] if a["id"] == "item.cache")
    assert attribute["semantic"] == {"case": "quantity", "base": "integer", "range": "MiB", "unit": "MiB"}


BAD_UNITS = {
    "an-unknown-unit": ({"GiB": {"typeof": "integer", "annotations": {"unit": "2^30 B"}}},
                        "type GiB: unit '2^30 B': B is no unit the pack declares"),
    "a-cycle": ({"P": {"typeof": "integer", "annotations": {"unit": "2 Q"}},
                 "Q": {"typeof": "integer", "annotations": {"unit": "2 P"}}},
                "type P: unit '2 Q' names a unit that is not declared, or the definitions form a cycle"),
    "two-bases-of-one-dimension": ({"B": {"typeof": "integer", "annotations": {"dimension": "data"}},
                                    "Byte": {"typeof": "integer", "annotations": {"dimension": "data"}}},
                                   "type Byte: dimension data has two base units, B and Byte"),
    "a-unit-of-text": ({"Tag": {"typeof": "string", "annotations": {"dimension": "tag"}}},
                       "type Tag: a unit is a type of whole numbers"),
    "a-unit-of-fractions": ({"Ratio": {"typeof": "decimal", "annotations": {"dimension": "ratio"}}},
                            "type Ratio: a unit is a type of whole numbers"),
    "no-dimension-name": ({"B": {"typeof": "integer", "annotations": {"dimension": "Data"}}},
                          "type B: dimension 'Data' is no name of a dimension"),
    "two-ways": ({"B": {"typeof": "integer", "annotations": {"dimension": "data", "currency": "EUR"}}},
                 "type B: a unit is declared by one of dimension, unit, currency, not by dimension and currency"),
    "no-definition": ({"B": {"typeof": "integer", "annotations": {"dimension": "data"}},
                       "K": {"typeof": "integer", "annotations": {"unit": "B times 2"}}},
                      "type K: unit 'B times 2' is no unit definition"),
}


@pytest.mark.parametrize("case", sorted(BAD_UNITS))
def test_a_wrong_unit_declaration_is_refused_where_it_is_written(tmp_path, case):
    declared, message = BAD_UNITS[case]
    d = unit_pack(tmp_path, units=declared | {"Memory": {"typeof": "integer"}, "MiB": {"typeof": "integer"},
                                               "Cents": {"typeof": "integer"}, "h": {"typeof": "integer"},
                                               "CentsPerHour": {"typeof": "integer"}})
    name = message.split(":")[0].split()[-1]
    at = line_of(d / "schema" / "calc.yaml", f"  {name}:") + 3  # typeof, annotations, then the annotation
    assert re.search(rf"schema/calc\.yaml:{at}:7: " + re.escape(message), refused(d)), refused(d)


# calc: the done-when of P10.3, and what the checks allow.
GIB_PLUS_CENTS = rule("both", {"op": "add", "args": [{"fact": "item.memory"}, {"fact": "item.price"}]})
BARE_384 = rule("big", {"integer": "1"}, when={"op": "gte", "args": [{"fact": "item.memory"}, {"integer": "384"}]})


def test_gib_plus_cents_is_an_error_where_it_is_written(tmp_path):
    d = unit_pack(tmp_path, [GIB_PLUS_CENTS])
    at = line_of(d / "calc" / "units.yaml", "fact: item.price")
    assert refused(d) == (f"calc.unit: calc/units.yaml:{at}:9: both@1#base.value/1: GiB + Cents: dimensions differ "
                          "(data, money EUR) (R003)")
    with pytest.raises(calc.UnitError) as e:  # the same as a diagnostic (D15): code, place, span, hint
        calc.build(pack.read(unit_pack(tmp_path / "without")), yaml.safe_load((d / "calc" / "units.yaml").read_text(
            encoding="utf-8")), files=calc.files_of(d, "calc", {}))
    p, = e.value.problems
    assert (p.code, p.version, p.path) == ("R003", "both@1", (0, "value", 1))
    assert e.value.spans == [("calc/units.yaml", at, 9)]


def test_a_number_without_a_unit_against_gib_is_an_error_where_it_is_written(tmp_path):
    d = unit_pack(tmp_path, [BARE_384])
    at = line_of(d / "calc" / "units.yaml", "integer: '384'")
    assert refused(d) == (
        f"calc.unit: calc/units.yaml:{at}:9: big@1#base.when/1: GiB >= 384: 384 has no unit and GiB is data (R003); "
        "write the constant with its unit: {integer: \"384\", unit: GiB}")


def test_a_constant_with_its_unit_and_zero_meet_a_quantity(tmp_path):
    d = unit_pack(tmp_path, [
        rule("big", {"integer": "1"}, when={"op": "gte", "args": [{"fact": "item.memory"}, {"integer": "384", "unit": "GiB"}]}),
        rule("zero", {"op": "max", "args": [{"fact": "item.memory"}, {"integer": "0"}]}, unit="GiB"),
        # a rate times a time is money; a quantity times a plain number keeps its unit, and a rounding too
        rule("cost", {"op": "round", "args": [{"op": "ratio", "args": [{"fact": "item.rate"}, {"fact": "item.runtime"}, {"integer": "3600"}]}]}),
        rule("budget", {"op": "sub", "args": [{"rule": "cost"}, {"fact": "item.price"}]}, unit="Cents"),
        rule("square", {"op": "pow", "args": [{"fact": "item.memory"}, {"integer": "2"}]}),
        rule("larger", {"op": "if", "args": [{"op": "lt", "args": [{"fact": "item.memory"}, {"rule": "zero"}]},
                                             {"rule": "zero"}, {"fact": "item.memory"}]}, unit="GiB"),
    ])
    model = pack.read(d)
    prog = calc.build(model, model.calc)
    assert prog.versions["big@1"].definitions[0].when.args[1] == calc.Node("integer", value=384, unit="GiB")
    # the unit is checked, not converted: the program the engine and the checker read has the number as written
    assert {"integer": "384"} in calc.to_doc(prog)["versions"][0]["definitions"][0]["when"]["args"]


CALC_ERRORS = {
    "two-units-of-one-dimension": (
        rule("both", {"op": "add", "args": [{"fact": "item.memory"}, {"fact": "item.cache"}]}),
        "both@1#base.value/1: GiB + MiB: one dimension (data), but the units differ by a factor, and calc converts "
        "nothing yet (R003); state both in one unit"),
    "a-rate-without-its-time": (
        rule("cost", {"op": "add", "args": [{"fact": "item.rate"}, {"fact": "item.price"}]}),
        "cost@1#base.value/1: CentsPerHour + Cents: dimensions differ (money EUR/time, money EUR) (R003)"),
    "a-value-in-another-unit-than-its-rule-states": (
        rule("memory", {"fact": "item.price"}, unit="GiB"),
        "memory@1#base.value: Cents as the value of memory, which states GiB: dimensions differ (money EUR, data) (R003)"),
    "a-bare-value-for-a-rule-with-a-unit": (
        rule("memory", {"integer": "5"}, unit="GiB"),
        "memory@1#base.value: 5 as the value of memory, which states GiB: 5 has no unit and GiB is data (R003)"),
    "if-branches-in-two-dimensions": (
        rule("pick", {"op": "if", "args": [{"boolean": True}, {"fact": "item.memory"}, {"fact": "item.runtime"}]}),
        "pick@1#base.value/2: if(GiB, h): dimensions differ (data, time) (R003)"),
    "an-unknown-unit": (
        rule("big", {"integer": "1"}, when={"op": "gte", "args": [{"fact": "item.memory"}, {"integer": "384", "unit": "GB"}]}),
        "big@1#base.when/1: unit GB is no unit the pack declares (R001)"),
    "a-power-by-a-fact": (
        rule("power", {"op": "pow", "args": [{"fact": "item.memory"}, {"fact": "item.amount"}]}),
        "power@1#base.value: a power of GiB needs a constant exponent (R003)"),
    "a-rule-read-in-another-unit": (
        [rule("zero", {"integer": "0"}, unit="GiB"),
         rule("sum", {"op": "add", "args": [{"rule": "zero"}, {"fact": "item.runtime"}]})],
        "sum@1#base.value/1: GiB + h: dimensions differ (data, time) (R003)"),
}


@pytest.mark.parametrize("case", sorted(CALC_ERRORS))
def test_calc_refuses_what_does_not_meet_in_dimension_and_unit(tmp_path, case):
    rules, message = CALC_ERRORS[case]
    got = refused(unit_pack(tmp_path, rules if isinstance(rules, list) else [rules]))
    assert re.match(r"calc\.unit: calc/units\.yaml:\d+:\d+: " + re.escape(message) + "($|; )", got), got


def test_a_unit_goes_with_an_integer_constant_only(tmp_path):
    got = refused(unit_pack(tmp_path, [rule("flag", {"boolean": True, "unit": "GiB"})]))
    assert got == "calc.unit: flag@1#base.value: a unit goes with an integer constant, not with boolean"


def test_what_the_compiler_does_not_know_the_unit_of_is_not_checked(tmp_path):
    # a parameter, an input concept, a derived relation's column and a rule whose unit is no declared unit
    model = pack.read(unit_pack(tmp_path, [
        rule("free", {"op": "add", "args": [{"fact": "item.memory"}, {"fact": "entry_total.total"}, {"fact": "visits"}]}),
        rule("loose", {"op": "add", "args": [{"rule": "free"}, {"fact": "item.price"}]}, unit="cents"),
    ]))
    assert model.calc is not None


# rules: the same two cases in a rule file, at the line of the rule.
@pytest.mark.parametrize("body, message", [
    ("t = m + c", "t in both joins EUR and GiB: dimensions differ (data, money EUR), two units in one variable"),
    ("m > 384", "m > 384 in both: 384 has no unit and GiB is data; compare with a fact or a parameter in GiB"),
    ("384 <= m", "384 <= m in both: 384 has no unit and GiB is data"),
    ("t = m - 1", "t = m - 1 in both: 1 has no unit and GiB is data"),
    ("m > k", "m > k in both: GiB and MiB: two units of one dimension (data), which the rules do not convert"),
])
def test_a_rule_that_mixes_units_is_an_error_at_its_line(tmp_path, body, message):
    dl = (".decl both(i: symbol, t: number)\n"
          f"both(i, t) :- item__memory(i, m), item__price(i, c), item__cache(i, k), {body}, t = m + 0.\n")
    if "t =" in body:
        dl = dl.replace(", t = m + 0.", ".")
    got = refused(unit_pack(tmp_path, dl=dl))
    assert f"rules/units.dl:2: {message}" in got, got


def test_a_rule_compares_a_quantity_with_zero_and_with_its_own_unit(tmp_path):
    dl = (".decl fits(i: symbol, m: number)\n"
          "fits(i, m) :- item__memory(i, m), item__memory(j, n), m > 0, m >= n, i != j.\n")
    model = pack.read(unit_pack(tmp_path, dl=dl))
    assert any(r["id"] == "fits" for r in model.rules["rules"])
