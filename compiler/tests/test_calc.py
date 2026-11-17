"""Calculation rules (calc.py, calc_sql.py): DuckDB gives exactly what the exact reference gives, on
hand-written cases and on random programs; the compiler refuses what is wrong, with a stable code; and
on a running Feldera (FELDERA_URL) the engine gives the same as DuckDB."""

from __future__ import annotations

import copy
import datetime
import json
import os
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings

import calcgen
from calcsupport import connect, results, run, run_both
from rezono_compiler import calc, calc_sql, emit, facts, pack
from rezono_compiler import rules as rule_ir, rules_dl, rules_split, rules_sql
from rezono_compiler.__main__ import main
from rezono_compiler.pack import CompileError
from support import REPO, run_split, typed

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "calc"
PACK = pack.read(FIXTURE)
BINDINGS = {"format": "rezono.calc/1", "pack": "calc", "subject": "item", "parameters": "setting.value",
            "inputs": {"kind": "entry", "subject": "item", "fact": "name", "integer": "number", "boolean": "truth"}}


def program(*rules, templates=()) -> dict:
    return dict(BINDINGS, rules=list(rules), templates=list(templates))


def rule(name, *defs, version="v1", valid=("2026-01-01", "2027-01-01"), known="2025-12-01", **extra) -> dict:
    out = {"id": f"{name}@{version}", "rule": name, "version": version, "output": f"{name}.value", "unit": "x",
           "valid_from": valid[0], "valid_until": valid[1], "known_from": known}
    if defs:
        out["definitions"] = list(defs)
    return out | extra


def d(name, value, when=None, overrides=()) -> dict:
    out = {"name": name, "when": when or {"boolean": True}, "value": value}
    if overrides:
        out["overrides"] = [{"definition": o, "reason": "voorrang"} for o in overrides]
    return out


def i(n) -> dict:
    return {"integer": str(n)}


def op(o, *args) -> dict:
    return {"op": o, "args": list(args)}


F = lambda x: {"fact": x}  # noqa: E731
P = lambda x: {"parameter": x}  # noqa: E731
R = lambda x: {"rule": x}  # noqa: E731


def item_rows() -> dict[str, list[tuple]]:
    return {
        "item": [("i0",), ("i1",), ("i2",)],
        "item__amount": [("i0", 7), ("i2", 1), ("i2", 2)],
        "item__extra": [("i1", 3)],
        "item__flag": [("i0", True), ("i1", False), ("i2", True)],
        "entry": [("e0",), ("e1",)],
        "entry__item": [("e0", "i0"), ("e1", "i0")],
        "entry__name": [("e0", "x0"), ("e1", "y0")],
        "entry__number": [("e0", 5)],
        "entry__truth": [("e1", True)],
        "setting": [("s0",)],
        "setting__value": [("s0", 3)],
        "calc__as_of": [("as_of", "2026-03-01", "2026-10-01")],
    }


def both(doc: dict, rows: dict) -> tuple[dict, dict]:
    return run_both(PACK, calc.build(PACK, doc), doc, rows)


SEMANTICS = program(
    rule("half", d("base", op("round", op("ratio", F("item.amount"), i(1), i(2))))),
    rule("negative_half", d("base", op("round", op("ratio", i(-1), i(1), i(2))))),
    rule("exact", d("base", op("ratio", F("item.amount"), i(1), i(3)))),
    rule("optional", d("base", op("add", F("item.extra"), i(1)))),
    rule("lazy", d("base", op("if", F("item.flag"), i(1), op("ratio", i(1), i(1), i(0))))),
    rule("short", d("base", op("and", F("item.flag"), F("item.note")))),
    rule("overflow", d("base", op("add", i(2**63 - 1), i(1)))),
    rule("eighth", d("base", op("pow", op("ratio", i(1), i(1), i(2)), i(3)))),
    rule("too_big", d("base", op("pow", i(2), i(64)))),
    rule("big_ratio", d("base", op("ratio", i(2**62), i(4), i(1)))),
    rule("after_overflow", d("base", op("add", R("overflow"), i(1)))),
    rule("guarded", d("base", i(1)), d("special", i(2), op("gte", R("too_big"), i(0)), ["guarded@v1#base"])),
    rule("odd", d("base", op("pow", i(-1), i(65)))),
    rule("parameters", d("base", op("add", P("s0"), P("s1")))),
    rule("concept", d("base", op("add", F("x0"), i(1)))),
    rule("prefer", d("base", i(1)), d("special", i(2), F("item.flag"), ["prefer@v1#base"])),
    rule("clash", d("a", i(1)), d("b", i(2), F("item.flag"))),
    rule("nothing", d("a", i(1), {"boolean": False})),
    rule("rate", d("base", i(10)), version="v1", valid=("2025-01-01", "2026-01-01"), known="2024-12-01"),
    rule("rate", d("base", i(20)), version="v2", known="2025-12-01"),
    rule("rate", d("base", i(30)), version="v3", known="2026-11-01"),
    rule("future", d("base", i(1)), valid=("2028-01-01", "2029-01-01")),
    rule("uses", d("base", op("add", R("rate"), R("rate@v1")))),
    rule("ops", d("base", op("if", op("or", op("eq", F("item.amount"), i(7)), op("lte", i(3), i(2))),
                             op("sub", op("min", i(5), F("x0"), i(9)), op("max", op("floor", op("ratio", i(-7), i(1), i(2))),
                                                                          op("ceil", op("ratio", i(-7), i(1), i(2))))),
                             i(0)))),
    rule("derived", d("base", op("add", F("entry_total.total"), i(1)), F("has_entry"), ["derived@v1#none"]),
         d("none", i(0), op("or", F("has_entry"), {"boolean": True}))),
    rule("share", template={"template": "share", "bindings": [{"arg": "base", "value": F("item.amount")},
                                                               {"arg": "rate", "value": i(50)}]}),
    templates=[calcgen.TEMPLATE],
)


def test_semantics_on_hand_written_cases():
    got, want = both(SEMANTICS, item_rows())
    assert got == want
    v = {r: {s: x[:2] if x[0] == "known" else (x[0], x[2]) for s, x in subj.items()} for r, subj in got.items()}
    assert v["half"] == {"i0": ("known", "4"), "i1": ("unknown", "fact item.amount is missing"),
                         "i2": ("invalid", "fact item.amount has more than one value")}
    assert v["negative_half"]["i0"] == ("known", "-1")  # half away from zero
    assert v["exact"]["i0"] == ("known", "7/3")
    assert v["optional"] == {"i0": ("not_applicable", "fact item.extra does not apply"), "i1": ("known", "4"),
                             "i2": ("not_applicable", "fact item.extra does not apply")}
    assert v["lazy"]["i0"] == ("known", "1") and v["lazy"]["i1"] == ("invalid", "division by zero in ratio")
    assert v["short"]["i0"] == ("not_applicable", "fact item.note does not apply")
    assert v["short"]["i1"] == ("known", "false")  # a known false decides an and
    # W8 (RV-K12): a step beyond the bound has a value Rezono cannot hold: unknown, naming the bound and the
    # operator; a division by zero stays invalid (lazy). What rests on such a step is unknown too, and no
    # definition is chosen on a condition that went beyond the bound.
    assert v["overflow"]["i0"] == ("unknown", "beyond the bound of W8 in add")
    assert v["big_ratio"]["i0"] == ("unknown", "beyond the bound of W8 in ratio")
    assert v["after_overflow"]["i0"] == ("unknown", "beyond the bound of W8 in add")
    assert v["guarded"]["i0"] == ("unknown", "beyond the bound of W8 in pow")
    assert v["eighth"]["i0"] == ("known", "1/8")
    assert v["too_big"]["i0"] == ("unknown", "beyond the bound of W8 in pow")
    assert v["odd"]["i0"] == ("known", "-1")
    assert v["parameters"]["i0"] == ("unknown", "parameter s1 is missing")
    assert v["concept"] == {"i0": ("known", "6"), "i1": ("unknown", "fact x0 is missing"),
                            "i2": ("unknown", "fact x0 is missing")}
    assert got["prefer"]["i0"][:4] == ("known", "2", "", "special") and got["prefer"]["i1"][:4] == ("known", "1", "", "base")
    assert v["clash"]["i0"] == ("invalid", "more than one definition of clash@v1 applies") and v["clash"]["i1"] == ("known", "1")
    assert v["nothing"]["i0"] == ("not_applicable", "no definition of nothing@v1 applies")
    assert got["rate"]["i0"] == ("known", "20", "", "base", "v2")  # v3 is valid but known only later
    assert v["future"]["i0"] == ("not_applicable", "no version of future is valid on the evaluation date")
    assert v["uses"]["i0"] == ("known", "30")
    assert got["share"]["i0"][:4] == ("known", "0", "", "small")  # 7 < 10 goes before the 50 % share
    assert v["ops"]["i0"] == ("known", "8")  # min(5, 5, 9) - max(floor(-7/2), ceil(-7/2)) = 5 - (-3)
    assert v["ops"]["i1"] == ("unknown", "fact item.amount is missing")
    assert got["derived"]["i0"][:4] == ("known", "3", "", "base")  # a count from a rule of M2 (2), plus one
    assert got["derived"]["i1"][:4] == ("known", "0", "", "none")  # i1 has no entries: has_entry is false


def test_a_witness_holds_the_path_taken():
    """W12: one witness per evaluation, with the version, the definition and one step per evaluated node;
    an `if` only with its chosen branch, a constant without a step, the other conclusions as premises."""
    prog = calc.build(PACK, SEMANTICS)
    ws = {(w["conclusion"]["relation"], json.loads(w["conclusion"]["key"])[0]): w
          for w in calc_sql.witnesses(connect(PACK, prog, item_rows()), prog)}

    def steps(relation, subject):
        return [(s["path"], s["value"], s["state"], s["reason"]) for s in ws[relation, subject]["steps"]]

    assert steps("calc__lazy", "i0") == [("base/value", "1", "known", ""), ("base/value/0", "true", "known", "")]
    assert steps("calc__lazy", "i1") == [("base/value", "", "invalid", "division by zero in ratio"),
                                         ("base/value/0", "false", "known", ""),
                                         ("base/value/2", "", "invalid", "division by zero in ratio")]
    uses = ws["calc__uses", "i0"]
    assert (uses["version"], uses["definition"], uses["value"], uses["valid_at"]) == ("v1", "base", "30", "2026-03-01")
    assert steps("calc__uses", "i0") == [("base/value", "30", "known", ""), ("base/value/0", "20", "known", ""),
                                         ("base/value/1", "10", "known", "")]
    assert uses["conclusion"] == {"relation": "calc__uses", "key": '["i0","30","known",""]'}
    assert uses["premises"] == [{"relation": "calc__rate", "key": '["i0","20","known",""]'},
                                {"relation": "calc__rate__v1", "key": '["i0","10","known",""]'}]
    pinned = ws["calc__rate__v1", "i0"]
    assert (pinned["rule"], pinned["version"], pinned["value"], pinned["valid_at"]) == ("rate", "v1", "10", "")
    derived = ws["calc__derived", "i0"]
    assert derived["definition"] == "base" and [s["path"] for s in derived["steps"]] == [
        "base/when", "none/when", "none/when/0", "base/value", "base/value/0"]
    assert derived["premises"] == [{"relation": "entry_total", "key": '["i0","2"]'}, {"relation": "has_entry", "key": '["i0"]'}]
    # Each step names its node and, for a leaf, what it reads, so an explanation can link it.
    assert [(s["op"], s.get("ref"), s.get("relation")) for s in uses["steps"]] == [
        ("add", None, None), ("rule", "rate", "calc__rate"), ("rule", "rate@v1", "calc__rate__v1")]
    assert [(s["op"], s.get("ref"), s.get("relation")) for s in derived["steps"]][-1] == ("fact", "entry_total.total", "entry_total")
    nothing = ws["calc__nothing", "i0"]  # a constant condition that is false: no step, no value
    assert (nothing["definition"], nothing["state"], nothing["steps"]) == ("", "not_applicable", [])


CHOICE = {"name": "name", "valid_from": "valid_from", "valid_until": "valid_until", "known_from": "known_from"}


def parameter_rows(rows: list[tuple]) -> dict[str, list[tuple]]:
    """Setting rows (element, name, value, valid_from, valid_until, known_from) as tables."""
    out = {t: [] for t in ("setting", "setting__name", "setting__value", "setting__valid_from",
                           "setting__valid_until", "setting__known_from")}
    for e, name, v, vf, vu, kf in rows:
        out["setting"].append((e,))
        for slot, x in (("name", name), ("value", v), ("valid_from", vf), ("valid_until", vu), ("known_from", kf)):
            out[f"setting__{slot}"].append((e, x))
    return out


def test_a_parameter_is_chosen_by_validity_and_knowledge():
    """With parameter_choice a leaf names a parameter, and its row is the one valid on valid_at and known
    by known_at, the latest knowledge first: a correction wins, a rate known later is unknown, never 0."""
    doc, rows = choice_case()
    got, want = both(doc, rows)
    assert got == want
    v = {r: subj["i0"][:3] for r, subj in got.items()}
    assert v == {"rate": ("known", "21", ""), "late": ("unknown", "", "parameter late is not known on the evaluation date"),
                 "gone": ("unknown", "", "parameter gone has no row valid on the evaluation date"),
                 "tie": ("invalid", "", "parameter tie has more than one value"),
                 "absent": ("unknown", "", "parameter absent is missing")}
    prog = calc.build(PACK, doc)
    ws = {w["conclusion"]["relation"]: w for w in calc_sql.witnesses(connect(PACK, prog, rows), prog)
          if json.loads(w["conclusion"]["key"])[0] == "i0"}
    assert ws["calc__rate"]["steps"] == [{"path": "base/value", "op": "parameter", "ref": "rate", "relation": "setting__value",
                                          "value": "21", "state": "known", "reason": "", "element": "rate-2026-fix"}]
    assert "element" not in ws["calc__late"]["steps"][0]
    assert set(ws["calc__rate"]["reads"]) >= {"setting__name", "setting__value", "setting__known_from"}
    # A What-if on the knowledge date: before the correction the first 2026 row applies.
    earlier = rows | {"calc__as_of": [("as_of", "2026-03-01", "2026-01-15")]}
    got, want = both(doc, earlier)
    assert got == want and got["rate"]["i0"][:2] == ("known", "20")


def choice_case() -> tuple[dict, dict]:
    """A program whose leaves name parameters (parameter_choice), and rows for every outcome of the choice."""
    doc = dict(program(*[rule(n, d("base", P(n))) for n in ("rate", "late", "gone", "tie", "absent")]),
               parameter_choice=CHOICE)
    return doc, item_rows() | parameter_rows([
        ("rate-2025", "rate", 10, "2025-01-01", "2026-01-01", "2024-12-01"),
        ("rate-2026", "rate", 20, "2026-01-01", "2027-01-01", "2025-12-01"),
        ("rate-2026-fix", "rate", 21, "2026-01-01", "2027-01-01", "2026-06-01"),  # a correction, known later
        ("rate-2026-next", "rate", 99, "2026-01-01", "2027-01-01", "2026-12-01"),  # not yet known
        ("late", "late", 5, "2026-01-01", "2027-01-01", "2026-12-01"),
        ("gone", "gone", 5, "2020-01-01", "2021-01-01", "2019-12-01"),
        ("tie-a", "tie", 1, "2026-01-01", "2027-01-01", "2025-12-01"),
        ("tie-b", "tie", 2, "2026-01-01", "2027-01-01", "2025-12-01"),
    ])


def test_the_parameter_choice_binding_is_checked():
    for choice, message in (({"name": "name", "valid_from": "valid_from"}, "give exactly"),
                            (dict(CHOICE, name="value"), "name: 'value' is not a text attribute"),
                            (dict(CHOICE, known_from="name"), "known_from: 'name' is not a date attribute")):
        with pytest.raises(CompileError, match=f"calc.binding: parameter_choice: {message}"):
            calc.build(PACK, dict(program(rule("r", d("base", P("rate")))), parameter_choice=choice))


CHECKER_FIXTURE = REPO / "checker" / "tests" / "fixtures" / "calc"


def frozen() -> dict[str, object]:
    """SEMANTICS as the checker's own tests read it: ir/calc.json, the database as complete snapshots and the
    witnesses of every evaluation."""
    from calcsupport import snapshots

    prog = calc.build(PACK, SEMANTICS)
    db = connect(PACK, prog, item_rows())
    return {"calc.json": json.loads(json.dumps(calc.to_doc(prog))),
            "snapshots.json": {name: sorted(map(list, rows)) for name, rows in snapshots(db, prog).items()},
            "witnesses.json": calc_sql.witnesses(db, prog)}


def as_lines(value) -> str:
    """JSON with one entry per line (a relation, a witness, a rule), so a change shows as the entries it touched."""
    def flat(v):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)

    if isinstance(value, list):
        return "[\n" + ",\n".join(flat(v) for v in value) + "\n]\n"
    entries = [f"{flat(k)}: {as_lines(v).rstrip() if isinstance(v, list) and v and isinstance(v[0], dict) else flat(v)}"
               for k, v in sorted(value.items())]
    return "{\n" + ",\n".join(entries) + "\n}\n"


def test_the_checkers_frozen_example_is_what_the_compiler_gives():
    """The planted-fault tests of the calculation check run with the checker, on this example frozen as data
    (checker/tests/test_calc.py, RV-K04): they do not import the compiler. Here the example is compiled again
    and held against those files, so they cannot go stale unseen. `REZONO_WRITE_CHECKER_FIXTURE=1` writes them."""
    for name, want in frozen().items():
        if os.environ.get("REZONO_WRITE_CHECKER_FIXTURE"):
            (CHECKER_FIXTURE / name).write_text(as_lines(want), encoding="utf-8", newline="\n")
        assert json.loads((CHECKER_FIXTURE / name).read_text(encoding="utf-8")) == json.loads(json.dumps(want)), (
            f"checker/tests/fixtures/calc/{name} is not what the compiler gives: write it again with "
            "REZONO_WRITE_CHECKER_FIXTURE=1 and review the difference")


def test_the_evaluation_date_is_a_fact():
    rows = item_rows()
    for as_of, want in (([], ("unknown", "", "no evaluation date (as_of)", "", "")),
                        ([("as_of", "2025-06-01", "2026-10-01")], ("known", "10", "", "base", "v1")),
                        ([("as_of", "2026-03-01", "2026-12-01")], ("known", "30", "", "base", "v3")),
                        ([("as_of", "2026-03-01", "2025-01-01")],
                         ("unknown", "", "no version of rate is known on the evaluation date", "", "")),
                        ([("as_of", "2026-03-01", "2026-12-01"), ("as_of", "2025-03-01", "2026-12-01")],
                         ("invalid", "", "more than one evaluation date (as_of)", "", ""))):
        got, oracle = both(SEMANTICS, rows | {"calc__as_of": as_of})
        assert got == oracle
        assert got["rate"]["i0"] == want, as_of


def test_the_bundle_names_the_calculation_views_a_publication_holds():
    """Every rule's view and every version named as rule@version is a derived relation of the bundle (W12),
    so the viewer explains its rows; exactly the views the checker counts as published."""
    from rezono_checker.calc import published_views

    doc = program(rule("base", d("a", i(1))), rule("pinned", d("a", {"rule": "base@v1"})))
    prog = calc.build(PACK, doc)
    got = emit.calc_relations(prog)
    assert {r["id"] for r in got} == published_views(calc.to_doc(prog)) == {prog.engine["base"], prog.engine["pinned"], prog.versions["base@v1"].engine}
    assert {r["calc"] for r in got} == {"base", "pinned", "base@v1"}
    assert all(r["module"] == "calc" and [c["name"] for c in r["columns"]] == ["subject", "value", "state", "reason"] for r in got)
    assert emit.calc_relations(None) == []


def test_braces_in_ids_stay_braces():
    """An id is data: `rate{a}` must not become `ratej0` (an alias), and `rate{year}` must not fail."""
    doc = program(rule("braces", d("base", op("add", P("rate{a}"), P("rate{year}"), F("x{0}")))))
    rows = item_rows() | {
        "setting": [("s0",), ("rate{a}",), ("rate{year}",), ("ratej0",)],
        "setting__value": [("s0", 3), ("rate{a}", 100), ("rate{year}", 7), ("ratej0", 1)],
        "entry": item_rows()["entry"] + [("e2",)],
        "entry__item": item_rows()["entry__item"] + [("e2", "i0")],
        "entry__name": item_rows()["entry__name"] + [("e2", "x{0}")],
        "entry__number": item_rows()["entry__number"] + [("e2", 4)],
    }
    got, want = both(doc, rows)
    assert got == want
    assert got["braces"]["i0"][:2] == ("known", "111")  # 100 + 7 + 4


def test_rounding_cases_of_the_contract():
    cases = yaml.safe_load((REPO / "contracts" / "fixtures" / "calc" / "rounding" / "cases.yaml").read_text())["cases"]
    rules = [rule(f"c{k}", d("base", op(c["op"], op("ratio", i(c["n"]), i(1), i(c["d"]))))) for k, c in enumerate(cases)]
    got, want = both(program(*rules), item_rows())
    assert got == want
    for k, c in enumerate(cases):
        assert got[f"c{k}"]["i0"][1] == c["want"], c


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(calcgen.program(), calcgen.rows())
def test_random_programs_give_what_the_reference_gives(doc, rows):
    got, want = both(doc, rows)
    assert got == want


def test_the_contract_fixtures_are_programs():
    """The valid contract fixtures compile once the names they use exist; the shapes are all known."""
    for path in sorted((REPO / "contracts" / "fixtures" / "calc" / "CalcProgram" / "valid").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        assert {r["id"] for r in doc["rules"]}  # parsed; the fixtures name kinds of another pack
        for r in doc["rules"]:
            for d_ in r.get("definitions") or []:
                calc.parse(d_["when"], path.name)
                calc.parse(d_["value"], path.name)


ERRORS = [
    ("calc.operator", program(rule("a", d("x", op("mod", i(1), i(2)))))),
    ("calc.arity", program(rule("a", d("x", op("add", i(1)))))),
    ("calc.arity", program(rule("a", d("x", op("ratio", i(1), i(2)))))),
    ("calc.type", program(rule("a", d("x", op("add", {"boolean": True}, i(1)))))),
    ("calc.type", program(rule("a", d("x", i(1), when=i(1))))),
    ("calc.type", program(rule("a", d("x", i(1))), rule("b", d("x", op("and", R("a"), {"boolean": True}))))),
    ("calc.cycle", program(rule("a", d("x", R("b"))), rule("b", d("x", R("a"))))),
    ("calc.override", program(rule("a", d("x", i(1), overrides=["a@v1#y"]), d("y", i(2), overrides=["a@v1#x"])))),
    ("calc.override", program(rule("a", d("x", i(1), overrides=["a@v1#z"])))),
    ("calc.reference", program(rule("a", d("x", R("b"))))),
    ("calc.reference", program(rule("a", d("x", R("a@v9"))))),
    ("calc.integer", program(rule("a", d("x", {"integer": "007"})))),
    ("calc.integer", program(rule("a", d("x", {"integer": str(2**63)})))),
    ("calc.expression", program(rule("a", d("x", {"integer": "1", "boolean": True})))),
    ("calc.binding", program(rule("a", d("x", F("item.missing_slot")))) | {"inputs": None}),
    ("calc.binding", program(rule("a", d("x", F("entry.number"))))),
    ("calc.binding", program(rule("a", d("x", P("s0")))) | {"parameters": None}),
    ("calc.binding", program() | {"subject": "nothing"}),
    ("calc.template", program(rule("a", template={"template": "share", "bindings": [{"arg": "base", "value": i(1)}]}),
                              templates=[calcgen.TEMPLATE])),
    ("calc.name", program(rule("a.b", d("x", i(1))), rule("a_b", d("x", i(1))))),
    ("calc.date", program(rule("a", d("x", i(1)), valid=("2027-01-01", "2026-01-01")))),
    ("calc.date", program(rule("a", d("x", i(1)), valid=(datetime.datetime(2026, 1, 1, 12), "2027-01-01")))),
    ("calc.binding", program(rule("a", d("x", F("entry_total"))))),
    ("calc.binding", program(rule("a", d("x", F("entry_total.nothing"))))),
    ("calc.rule", program(rule("a", d("x", i(1))), rule("a", d("x", i(2))))),
]


@pytest.mark.parametrize("code, doc", ERRORS, ids=[f"{c}-{k}" for k, (c, _) in enumerate(ERRORS)])
def test_the_compiler_refuses_with_a_stable_code(code, doc):
    with pytest.raises(CompileError) as e:
        calc.build(PACK, doc)
    assert code in str(e.value)


def test_two_compiles_give_identical_bytes():
    a, b = calc.build(PACK, SEMANTICS), calc.build(PACK, copy.deepcopy(SEMANTICS))
    assert calc_sql.feldera(a) == calc_sql.feldera(b) and calc_sql.duckdb(a) == calc_sql.duckdb(b)
    assert "FLOAT" not in calc_sql.feldera(a) and "DOUBLE" not in calc_sql.duckdb(a)


def test_a_change_is_recomputed_exactly():
    """Change a fact and compute again: the same as computing from the changed rows at once."""
    prog = calc.build(PACK, SEMANTICS)
    rows = item_rows()
    db = connect(PACK, prog, rows)
    db.execute('DELETE FROM "item__amount" WHERE id = \'i0\'')
    db.execute('INSERT INTO "item__amount" VALUES (\'i0\', -9)')
    db.execute(calc_sql.duckdb_body(prog))
    changed = rows | {"item__amount": [("i0", -9), ("i2", 1), ("i2", 2)]}
    from calcsupport import results
    assert results(db, prog) == run(PACK, prog, changed)


# --- The compile path: pack.read, emit and the command line -------------------------------------

def test_rule_phases_keep_the_calc_dependencies_before_its_consumers():
    doc = rules_dl.read_program(
        '.decl input_exists(item: symbol)\n'
        'input_exists(x) :- item(x).\n'
        '.decl over_budget(item: symbol)\n'
        'over_budget(x) :- calc__total(x, value, "known", ""), value > 10.\n'
        '.decl alert(item: symbol)\n'
        'alert(x) :- over_budget(x).\n',
        "test.dl",
        {"item": [("item", "string")],
         "calc__total": [("subject", "string"), ("value", "integer"), ("state", "string"), ("reason", "string")]},
        "test",
    )
    for relation in doc["relations"]:
        if relation["name"] == "calc__total":
            relation.update(role="calc", world="open")
        elif relation["role"] == "derived":
            relation.pop("world", None)
    rules = rule_ir.load(doc)

    assert rules.base_used() == ["item"]
    assert rules.relations["alert"].world == "open"
    before, after = rules.partition_at_calc({"calc__total"}, {"input_exists"})
    assert (before, after) == (["input_exists"], ["over_budget", "alert"])
    early_parts = rules_split.partition(rules, 2, relations=before)
    late_parts = rules_split.partition(rules, 2, relations=after)
    assert early_parts == [["input_exists"]]
    assert late_parts == [["over_budget"], ["alert"]]
    early_part, calc_consumer, alert_part = rules_split.plan(
        rules, early_parts + late_parts, upstream={"calc__total"}
    )
    assert early_part["bases"] == ["item"]
    assert calc_consumer["bases"] == []
    assert calc_consumer["imports"] == ["calc__total"]
    assert calc_consumer["exports"] == alert_part["imports"] == ["over_budget"]
    consumer_sql = rules_split.part_sql(rules, calc_consumer)
    assert 'CREATE TABLE "calc__total" ("subject" VARCHAR NOT NULL, "value" BIGINT NOT NULL' in consumer_sql
    export_sql = rules_split.export_sql(rules, ["calc__total"])
    assert "CAST('calc__total' AS VARCHAR) AS rel" in export_sql
    assert 'FROM "rule_calc_input__total"' in export_sql
    assert rules_split.decode(rules, "calc__total", ("row", "9007199254740993", "known", "")) == (
        "row", 9007199254740993, "known", ""
    )
    for early, late, input_name in (
        (rules_sql.feldera(rules, relations=before, tables=False),
         rules_sql.feldera(rules, relations=after, tables=False), "calc__total"),
        ("\n".join(rules_sql.duckdb_program(rules, relations=before)),
         "\n".join(rules_sql.duckdb_program(rules, relations=after)), "rule_calc_input__total"),
    ):
        assert f'"{input_name}"' not in early
        assert f'FROM "{input_name}"' in late
        assert late.index('"over_budget"') < late.index('"alert"')
    with pytest.raises(rule_ir.IRError, match="rule_calc_cycle: .*alert"):
        rules.partition_at_calc({"calc__total"}, {"alert"})

    alert = rules.rules["alert"]
    rules.rules["alert"] = replace(alert, body=(replace(alert.body[0], polarity="negative"),))
    with pytest.raises(rule_ir.IRError, match="calc_not_known_positive: alert"):
        rules.partition_at_calc({"calc__total"}, {"input_exists"})

    known_read = next(rule for rule in doc["rules"] if rule["id"] == "over_budget")["body"][0]
    known_read["terms"][2] = "unknown"
    with pytest.raises(rule_ir.IRError, match="calc_not_known_positive"):
        rule_ir.load(doc)
    known_read["terms"][2] = "known"
    known_read["polarity"] = "negative"
    with pytest.raises(rule_ir.IRError, match="calc_not_known_positive"):
        rule_ir.load(doc)


def test_rule_reads_the_known_integer_of_a_calc_selection(tmp_path):
    import hashlib

    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations, load_rules
    from rezono_compiler import batch, checks, explain, operate, scenarios, seal
    from rezono_publisher import publish

    directory = tmp_path / "calc"
    shutil.copytree(FIXTURE, directory)
    (directory / "rules" / "budget.dl").write_text(
        '.decl over_budget(item: symbol, cents: number)\n'
        'over_budget(x, cents) :- calc__total(x, cents, "known", ""), cents > 10.\n',
        encoding="utf-8",
    )

    model = pack.read(directory)
    program = rule_ir.load(model.rules)
    relations = program.relations
    assert relations["over_budget"].world == "open"
    assert relations["calc__total"].role == "calc"
    assert relations["calc__total"].key[1] == rule_ir.Column("value", "integer")
    table, select = calc_sql.rule_input_view("calc__total")
    assert select == ('SELECT subject, n AS value, state, reason FROM "calc__total" '
                      "WHERE state = 'known' AND d = 1 AND reason = ''")
    rule = program.rules["over_budget"]
    for dialect, input_name in (("feldera", "calc__total"), ("duckdb", table)):
        assert f'FROM "{input_name}" AS t0' in rules_sql.rule_select(program, rule, dialect=dialect)
        assert f'FROM "{input_name}" AS t0' in rules_sql.witness_select(program, rule, dialect=dialect)

    files = emit.compile_pack(model)
    plan = json.loads(files["engine/pipelines.json"])
    integrity, early, calculation, late = plan["pipelines"]
    assert [pipe["name"] for pipe in (integrity, early, calculation, late)] == [
        "integrity", "rules-1", "calc", "rules-2"
    ]
    assert early["exports"] == calculation["imports"] == ["entry_total", "has_entry"]
    assert calculation["exports"] == late["imports"] == ["calc__total"]
    assert calculation["sql"][-2:] == ["engine/calc.sql", "engine/calc-export.sql"]
    assert {"relation": "calc__total", "producer": "calc", "consumers": ["rules-2"]} in plan["forward"]
    assert f'CREATE VIEW "{table}" AS\n{select};' in files["engine/calc-export.sql"]
    assert 'CREATE TABLE "calc__total"' in files["engine/rules-2.sql"]
    early_batch, late_batch = files["batch/rules.sql"], files["batch/rules-late.sql"]
    assert '"entry_total"' in early_batch and '"over_budget"' not in early_batch
    assert f'CREATE OR REPLACE TABLE "{table}" AS\n{select};' in late_batch
    assert late_batch.index(f'CREATE OR REPLACE TABLE "{table}"') < late_batch.index('"over_budget"')

    previous = [["has_entry"], [], ["entry_total"], ["over_budget"]]
    split = emit.compile_pack(model, 2, previous=previous)
    split_plan = json.loads(split["engine/pipelines.json"])
    assert emit.previous_parts(split_plan) == previous
    assert [p["name"] for p in split_plan["pipelines"]] == ["integrity", "rules-1", "rules-3", "calc", "rules-4"]

    # `explain` runs the calculation in its phase (batch.phases): the proof of the consuming rule has the
    # selection as its premise and the calculation witness of that row (W12), and the selection is a snapshot
    # as a publication holds it (batch.calculate).
    (directory / "facts").mkdir()
    (directory / "facts" / "state.yaml").write_text(
        "item: [{id: i0, amount: 7, flag: true}, {id: i1, amount: 20, flag: false}, {id: i2, amount: 4, flag: true}]\n"
        "entry: [{id: e0, item: i0, name: x0}]\nsetting: [{id: s0, value: 3}]\n", encoding="utf-8", newline="\n")
    assert main(["explain", str(directory), str(tmp_path / "proof")]) == 0
    [state] = [p.parent for p in (tmp_path / "proof").rglob("proofs.json")]
    [proof] = [p for p in json.loads((state / "proofs.json").read_text(encoding="utf-8"))
               if p["root"]["relation"] == "over_budget"]
    premise = {"relation": "calc__total", "key": explain.key_text(["i0", "11", "known", ""])}  # 7 + 1 entry + 3
    assert proof["root"]["key"] == explain.key_text(["i0", "11"])
    assert [p["row"] for w in proof["witnesses"] for p in w["premises"]] == [premise]
    snapshot = json.loads((state / "snapshots" / "calc__total.json").read_text(encoding="utf-8"))
    assert snapshot == [{"key": [i, v, "known", ""]} for i, v in (("i0", "11"), ("i1", "20"), ("i2", "4"))]
    [(_, rows)] = scenarios.states(model, directory)
    calculation = calc.build(model, model.calc)
    con, calc_witnesses, calculated = batch.run(model, program, rows, calculation)
    assert proof["calc_witnesses"] == [w for w in calc_witnesses if w["conclusion"] == premise]
    assert proof["calc_witnesses"][0]["rule"] == "total" and proof["calc_witnesses"][0]["value"] == "11"

    # The checker accepts the proof of the consuming rule with its calculation premise: the epoch check, which
    # recomputes each calculation witness from the snapshots a publication holds (the base tables and the
    # calculation's views); a calculation premise without its witness is refused.
    derived = batch.read(con, program)
    ex = explain.Explainer(program, batch.read(con, program, program.base_used() + program.calc_inputs()) | derived,
                           batch.witnesses(con, program))
    db = batch.database(model, rows)
    names = [r[0] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_type = "
                                      "'BASE TABLE' ORDER BY table_name").fetchall() if not r[0].startswith(checks.P)]
    tables = {t: [tuple(seal.text(v) for v in r) for r in db.execute(f'SELECT * FROM "{t}"').fetchall()]
              for t in names} | calculated
    snaps = {r: ex.snapshot(r).encode() for r in program.relations if r not in tables}
    snaps |= {t: publish.snapshot(rs) for t, rs in tables.items()}
    manifest = {"id": "m", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                          "sha256": hashlib.sha256(b).hexdigest()} for r, b in sorted(snaps.items())]}
    rules = load_rules(model.rules)

    def epoch(calc_witnesses):
        return check_epoch(ex.chosen(), manifest, rules, snaps.__getitem__, derived=derived_relations(model.rules, rules),
                           calc_witnesses=calc_witnesses, calc_ir=calc.to_doc(calculation))

    report = epoch(calc_witnesses)
    assert report["valid"] and not report["findings"], report["findings"]
    without = epoch([w for w in calc_witnesses if w["conclusion"] != premise])
    assert ("unproven_premise", "calc__total") in {(f["reason"], f.get("relation")) for f in without["findings"]}
    with pytest.raises(operate.OperationError, match="schema operations with calculation inputs"):
        operate.guarded(model, {})


def test_compile_writes_the_calculation(tmp_path):
    """`rezono_compiler compile` writes the calculation next to the tables and the rules, and the batch
    script it writes gives what the reference gives."""
    assert main(["compile", str(FIXTURE), str(tmp_path)]) == 0
    files = {str(p.relative_to(tmp_path)): p.read_text() for p in tmp_path.rglob("*") if p.is_file()}
    assert {"engine/calc.sql", "batch/calc.sql", "engine/calc.json"} <= set(files)
    plan = yaml.safe_load(files["engine/pipelines.json"])
    assert plan["pipelines"][0]["sql"][-1] == "engine/calc.sql"
    assert '"calc__as_of": [' in files["engine/calc.json"] and "2026-03-01" in files["engine/calc.json"]
    db = connect(PACK, calc.build(PACK, PACK.calc), item_rows())
    db.execute(files["batch/calc.sql"])  # the written script, again on the same rows
    prog = calc.build(PACK, PACK.calc)
    got, want = run_both(PACK, prog, PACK.calc, item_rows())
    assert results(db, prog) == got == want
    assert got["total"]["i0"][:4] == ("known", "12", "", "with_entries")  # 7 + 2 entries + 3


def test_above_the_budget_the_calculation_gets_the_last_pipeline():
    """Split, the calculation is the last pipeline: it imports the derived relations it reads
    from the parts and gets the tables it reads, and on what the parts export it gives what it gives in one
    pipeline."""
    import duckdb
    from rezono_compiler import rules as ir
    from rezono_compiler import rules_sql
    rules = ir.load(PACK.rules)
    files = emit.compile_pack(PACK, max_views=max(rules_sql.views(rules, n) for n in rules.derived()))
    plan = json.loads(files["engine/pipelines.json"])
    names = [p["name"] for p in plan["pipelines"]]
    assert names[0] == "integrity" and names[-1] == "calc" and len(names) >= 4
    pipe = plan["pipelines"][-1]
    assert pipe["imports"] == ["entry_total", "has_entry"]
    assert pipe["sql"] == ["engine/tables.sql", "engine/calc-imports.sql", "engine/calc.sql"]
    assert all("calc" in f["consumers"] for f in plan["forward"] if f["relation"] in pipe["imports"])
    for f in plan["forward"]:
        assert f["relation"] in next(p for p in plan["pipelines"] if p["name"] == f["producer"])["exports"]
    prog = calc.build(PACK, PACK.calc)
    own = {n for n, _, _ in calc_sql.relations(prog)}
    read = set(re.findall(r'(?:FROM|JOIN) "([^"]+)"', files["engine/calc.sql"]))
    assert read and read <= set(pipe["tables"]) | set(pipe["imports"]) | own   # nothing it reads is left out
    derived, _ = run_split(PACK, files, item_rows())
    db = duckdb.connect()
    db.execute(files["engine/tables.sql"])
    db.execute(files["engine/calc-imports.sql"])
    db.execute(calc_sql.duckdb_prelude())
    params = {t: [tuple(r.values()) for r in rs] for t, rs in emit.parameters(PACK).items()}
    sent = {t: rs for t, rs in (params | item_rows()).items() if t in pipe["tables"]}
    sent |= {r: typed(rules, r, sorted(derived[r])) for r in pipe["imports"]}
    for table, rs in sorted(sent.items()):
        if rs:
            db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", [list(r) for r in rs])
    db.execute(calc_sql.duckdb_body(prog))
    assert results(db, prog) == results(connect(PACK, prog, item_rows()), prog)


def broken(tmp_path, schema_extra: str = "", calc_text: str | None = None) -> Path:
    d = tmp_path / "pack"
    shutil.copytree(FIXTURE, d)
    if schema_extra:
        (d / "schema" / "calc.yaml").write_text((d / "schema" / "calc.yaml").read_text() + schema_extra)
    if calc_text is not None:
        (d / "calc" / "example.yaml").write_text(calc_text)
    return d


def test_check_reports_a_wrong_calculation(tmp_path, capsys):
    text = (FIXTURE / "calc" / "example.yaml").read_text().replace("{fact: item.amount}", "{op: add, args: [{integer: \"1\"}]}")
    assert main(["check", str(broken(tmp_path, calc_text=text))]) == 1
    assert "calc.arity" in capsys.readouterr().err


def test_check_reports_a_day_that_does_not_exist(tmp_path, capsys):
    text = (FIXTURE / "calc" / "example.yaml").read_text().replace('valid_from: "2026-01-01"', 'valid_from: "2026-02-30"')
    assert main(["check", str(broken(tmp_path, calc_text=text))]) == 1
    assert "calc.date" in capsys.readouterr().err


def test_a_generated_name_may_not_meet_a_table(tmp_path):
    """A kind `calc` with a slot `as_of` would be created twice as table calc__as_of."""
    extra = "  Calc:\n    attributes:\n      id: {identifier: true}\n      as_of: {range: integer}\n"
    with pytest.raises(CompileError, match="calc.name: engine name 'calc__as_of'"):
        pack.read(broken(tmp_path, schema_extra=extra))


def test_presence_of_an_open_relation_is_refused(tmp_path):
    """W1/W6: a missing row of an open relation is unknown, so `does it hold` cannot be a known false."""
    extra = "  Mark:\n    annotations: {world: open}\n    attributes:\n      id: {identifier: true}\n      item: {range: Item, required: true}\n"
    text = (FIXTURE / "calc" / "example.yaml").read_text().replace("when: {fact: has_entry}", "when: {fact: marked}", 1)
    d = broken(tmp_path, schema_extra=extra, calc_text=text)
    (d / "rules" / "marks.dl").write_text(".decl marked(item: symbol)\nmarked(i) :- mark__item(_, i).\n")
    with pytest.raises(CompileError, match="fact marked: relation marked is open"):
        pack.read(d)


# --- Feldera: the same program on the engine, with the Rust UDF -------------------------------------

def full_program() -> dict:
    """Every operator, overflow, negative halves and the rounding cases of the contract."""
    cases = yaml.safe_load((REPO / "contracts" / "fixtures" / "calc" / "rounding" / "cases.yaml").read_text())["cases"]
    extra = [rule(f"c{k}", d("base", op(c["op"], op("ratio", i(c["n"]), i(1), i(c["d"]))))) for k, c in enumerate(cases)]
    return SEMANTICS | {"rules": SEMANTICS["rules"] + extra}


def test_the_full_program_uses_every_operator():
    used = {n["op"] for r in full_program()["rules"] for d_ in r.get("definitions", []) for n in walk(d_["when"]) + walk(d_["value"])
            if "op" in n}
    assert used | {"gte", "lt"} == set(calc.ARITY)  # gte and lt come from the template


def walk(e: dict) -> list[dict]:
    return [e] + [x for a in e.get("args", []) for x in walk(a)]


@pytest.mark.parametrize("case", ["full", "choice"])
def test_feldera_gives_what_duckdb_gives(case):
    from feldera import URL, deploy, processed, push, query, stop
    if not URL:
        pytest.skip("set FELDERA_URL to a running Feldera")
    doc, rows = (full_program(), item_rows()) if case == "full" else choice_case()
    prog = calc.build(PACK, doc)
    name = f"rezono-calc-{case}"
    udf = REPO / "udf"
    compiled = emit.compile_pack(PACK)
    deploy(name, compiled["engine/tables.sql"] + compiled["engine/rules.sql"] + calc_sql.feldera(prog),
           udf_rust=(udf / "udf.rs").read_text(), udf_toml=(udf / "udf.toml").read_text())
    pack_rows = {t: rs for t, rs in rows.items() if t != "calc__as_of"}
    updates = facts.ingress(PACK, pack_rows)
    updates["calc__as_of"] = [{"insert": {"id": a, "valid_at": b, "known_at": c}} for a, b, c in rows["calc__as_of"]]
    processed(name, push(name, updates))
    from calcsupport import value_text
    got = {}
    for r in prog.rules:
        got[r] = {x["subject"]: (x["state"], value_text(prog.types[r], x["state"], x["n"], x["d"], x["b"]), x["reason"],
                                 x["definition"], x["version"])
                  for x in query(name, f'SELECT * FROM "{prog.engine[r]}"')}
    stop(name)
    assert got == run(PACK, prog, rows)
