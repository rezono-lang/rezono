"""Reading rules/*.dl on the minimal, domain-free fixture pack: what is accepted, what is refused, and
what the compiler emits for it. Light: no engine, no oracle."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE
from rezono_compiler import emit, fold, modules, pack, rules_dl, rules_sql, view_rules
from rezono_compiler import rules as ir

PROGRAM = """
// A neutral program over the fixture's tables: alpha(id), alpha__size(id, v), beta__alpha(id, v).
.decl pair(a: symbol, b: symbol)
pair(a, b) :- beta__alpha(b, a).

.decl sized(a: symbol, n: number)
sized(a, n) :- alpha(a), n = count : { beta__alpha(_, a) }.

.decl big(a: symbol)
big(a) :- alpha__size(a, s), s >= 5, alpha__size__maximum(m), s <= m.

.decl total(a: symbol, t: number)
total(a, t) :- alpha(a), t = sum s : { alpha__size(a, s) }.

// @explain on_demand
.decl paired(a: symbol)
paired(a) :- pair(a, _).

.decl lonely(a: symbol)
lonely(a) :- alpha(a), !paired(a).

.decl reach(a: symbol, b: symbol)
reach(a, b) :- pair(a, b).
reach(a, c) :- reach(a, b), pair(b, c).
"""


@pytest.fixture
def fixture(tmp_path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def with_rules(d: Path, **files: str) -> Path:
    (d / "rules").mkdir(exist_ok=True)
    for name, text in files.items():
        (d / "rules" / f"{name}.dl").write_text(text)
    return d


def test_a_legacy_rule_can_extend_an_authored_import(fixture, tmp_path):
    model = pack.read(fixture)
    directory = tmp_path / "foundation"
    directory.mkdir()
    foundation = modules.Imported("foundation", "0", modules.pack_hash(directory), directory, {}, [])
    authored = rules_dl.Embedded(
        "foundation", "access", "rezono/access.rezono", "\n// @extend\n.decl allowed(item: symbol)\n"
    )
    with_rules(fixture, extension=".decl allowed(item: symbol)\nallowed(x) :- alpha(x).\n")

    document, _ = rules_dl.read(model, fixture, {"foundation": foundation}, embedded=(authored,))

    [rule] = document["rules"]
    assert rule["id"] == "allowed"
    assert rule["module"] == "import_foundation_access"
    assert rule["origin"] == {"file": "rules/extension.dl", "line": "2"}


def test_a_program_becomes_the_rule_ir(fixture):
    model = pack.read(with_rules(fixture, core=PROGRAM))
    prog = ir.load(model.rules)
    assert sorted(prog.rules) == ["big", "lonely", "pair", "paired", "reach_1", "reach_2", "sized", "total"]
    assert prog.strata["lonely"] > prog.strata["paired"] > 0
    # a wildcard in a positive literal is an anonymous variable; a rule that projects one away is
    # explained on demand, the others are materialized
    assert prog.rules["paired"].body[0].atom.terms == ("?a", "?anon_1")
    assert {n: r.explain for n, r in prog.relations.items() if r.role == "derived"} == {
        "big": "on_demand", "lonely": "materialize", "pair": "materialize", "paired": "on_demand",
        "reach": "on_demand", "sized": "materialize", "total": "materialize"}
    # an aggregate over a key column: the local variable becomes '_', and 'over' names the column
    total = prog.rules["total"].aggregates[0]
    assert (total.atom.terms, total.over) == (("?a", "_"), "v")
    assert prog.relations["alpha__size"].key[1].type == "integer"
    assert prog.rules["big"].origin == ("rules/core.dl", 10)


def test_outputs_for_rules(fixture):
    files = emit.compile_pack(pack.read(with_rules(fixture, core=PROGRAM)))
    assert {"ir/rules.json", "engine/rules.sql", "batch/rules.sql", "engine/pipelines.json"} <= set(files)
    assert not [f for f in files if f.startswith("explain/")]   # no query file per rule: nothing reads one
    engine = files["engine/rules.sql"]
    assert "CREATE TABLE" not in engine            # the tables are in engine/tables.sql
    assert 'DECLARE RECURSIVE VIEW "reach"' in engine
    assert '"lonely__witness"' in engine and '"paired__witness"' not in engine   # only materialize
    plan = json.loads(files["engine/pipelines.json"])
    assert [p["name"] for p in plan["pipelines"]] == ["main"] and plan["max_views"] == "64"
    bundle = json.loads(files["bundle/schema-bundle.json"])
    big = dict(bundle["rules"][0])
    assert big.pop("stable_id") == emit.rule_id(big["head"], big["body"])   # MOD2, test_stable_ids.py
    assert big.pop("span") == {"file": "rules/core.dl", "line": "10", "column": "1"}
    assert big == {"id": "big", "relation": "big", "module": "core", "message": "rule.big",
                                  "variables": [{"name": "?a", "type": "string"}, {"name": "?m", "type": "integer"},
                                                {"name": "?s", "type": "integer"}],
                                  "head": {"relation": "big", "terms": [var("?a", "string")]},
                                  "body": [{"kind": "atom", "position": 1, "polarity": "positive",
                                            "relation": "alpha__size", "terms": [var("?a", "string"), var("?s")]},
                                           {"kind": "comparison", "position": 2, "polarity": "positive", "op": "ge",
                                            "terms": [var("?s"), const("5")]},
                                           {"kind": "atom", "position": 3, "polarity": "positive",
                                            "relation": "alpha__size__maximum", "terms": [var("?m")]},
                                           {"kind": "comparison", "position": 4, "polarity": "positive", "op": "le",
                                            "terms": [var("?s"), var("?m")]}],
                                  "origin": {"file": "rules/core.dl", "line": "10"}}
    assert [r["id"] for r in bundle["relations"]] == ["big", "lonely", "pair", "paired", "reach", "sized", "total"]


def var(name, type_="integer"):
    return {"kind": "variable", "value": name, "type": type_}


def const(value, type_="integer"):
    return {"kind": "constant", "value": value, "type": type_}


MIXED = """
.decl gone(a: symbol)
gone(a) :- beta__alpha(_, a).

.decl scaled(a: symbol, d: number, n: number)
scaled(a, d, n) :- alpha__size(a, s), s > 1, d = s * 2, n = count : { beta__alpha(_, a) }, !gone(a), "x" != a.
"""


def test_the_bundle_gives_a_rule_body_in_source_order(fixture):
    """MOD14: the rule IR keeps atoms, aggregates, assignments and comparisons apart; the bundle gives one body
    in the order written, every term typed, and the IR itself stays as it was."""
    model = pack.read(with_rules(fixture, core=MIXED))
    files = emit.compile_pack(model)
    rules = {r["id"]: r for r in json.loads(files["bundle/schema-bundle.json"])["rules"]}
    assert model.rule_bodies == {"gone": ("atom",),
                                 "scaled": ("atom", "comparison", "assignment", "aggregate", "atom", "comparison")}
    assert rules["scaled"]["head"] == {"relation": "scaled", "terms": [var("?a", "string"), var("?d"), var("?n")]}
    assert rules["scaled"]["body"] == [
        {"kind": "atom", "position": 1, "polarity": "positive", "relation": "alpha__size",
         "terms": [var("?a", "string"), var("?s")]},
        {"kind": "comparison", "position": 2, "polarity": "positive", "op": "gt", "terms": [var("?s"), const("1")]},
        {"kind": "assignment", "position": 3, "polarity": "positive", "op": "mul", "terms": [var("?s"), const("2")],
         "result": var("?d")},
        {"kind": "aggregate", "position": 4, "polarity": "positive", "relation": "beta__alpha",
         "terms": [{"kind": "wildcard", "value": "_", "type": "string"}, var("?a", "string")], "function": "count",
         "result": var("?n"), "aggregate_position": 0},
        {"kind": "atom", "position": 5, "polarity": "negative", "relation": "gone", "terms": [var("?a", "string")]},
        # a constant compared with a variable has that variable's type
        {"kind": "comparison", "position": 6, "polarity": "positive", "op": "ne",
         "terms": [const("x", "string"), var("?a", "string")]}]
    # a '_' in a positive atom is a variable of its own, as in the rule IR
    assert rules["gone"]["body"][0]["terms"] == [var("?anon_1", "string"), var("?a", "string")]
    assert json.loads(files["ir/rules.json"]) == ir.to_doc(ir.load(model.rules))   # nothing new in the IR
    # Without a source order (a rule a view generates): atoms, aggregates, assignments, comparisons.
    prog = ir.load(model.rules)
    assert [x["kind"] for x in emit.rule_body(prog, prog.rules["scaled"], None)[1]] == [
        "atom", "atom", "aggregate", "assignment", "comparison", "comparison"]
    with pytest.raises(ValueError, match="does not match the rule IR"):
        emit.rule_body(prog, prog.rules["scaled"], ("atom",))


def test_no_rules_no_rule_outputs():
    files = emit.compile_pack(pack.read(FIXTURE))
    assert not [f for f in files if f.startswith(("ir/", "batch/", "explain/")) or "rules" in f or "pipelines" in f]
    bundle = json.loads(files["bundle/schema-bundle.json"])
    assert bundle["rules"] == [] and bundle["relations"] == []


SPLIT = {"a_first": """
.decl pair(a: symbol, b: symbol)
pair(a, b) :- beta__alpha(b, a).
.decl sized(a: symbol, n: number)
sized(a, n) :- alpha(a), n = count : { beta__alpha(_, a) }.
""", "b_second": """
.decl lonely(a: symbol)
lonely(a) :- alpha(a), !paired(a).
.decl paired(a: symbol)
paired(a) :- pair(a, b).
"""}


def test_above_the_budget_the_compiler_cuts_by_recursive_core(fixture):
    """Modules do not bind the cut; few parts in a row, then few relations between parts."""
    files = emit.compile_pack(pack.read(with_rules(fixture, **SPLIT)), max_views=4)
    plan = json.loads(files["engine/pipelines.json"])
    assert [p["name"] for p in plan["pipelines"]] == ["integrity", "rules-1", "rules-2"]
    # pair (a_first) and paired (b_second) share a part; sized runs beside them, lonely reads paired
    assert [p["views"] for p in plan["pipelines"][1:]] == [["pair", "paired"], ["sized", "lonely"]]
    assert plan["forward"] == [{"relation": "paired", "producer": "rules-1", "consumers": ["rules-2"]}]
    assert '"export__out"' in files["engine/rules-1.sql"] and '"epoch__in"' in files["engine/rules-1.sql"]
    assert 'CREATE TABLE "paired"' in files["engine/rules-2.sql"]     # an import is an input table there


def test_the_previous_cut_is_kept(fixture):
    """With the earlier engine/pipelines.json, a new relation that nothing reads moves no other view."""
    first = json.loads(emit.compile_pack(pack.read(with_rules(fixture, **SPLIT)), max_views=4)["engine/pipelines.json"])
    with_rules(fixture, b_second=SPLIT["b_second"] + ".decl copy(a: symbol)\ncopy(a) :- lonely(a).\n")
    files = emit.compile_pack(pack.read(fixture), max_views=4, previous=emit.previous_parts(first))
    second = json.loads(files["engine/pipelines.json"])
    assert [set(p["views"]) - {"copy"} for p in second["pipelines"][1:] if p["views"] != ["copy"]] == \
        [set(p["views"]) for p in first["pipelines"][1:]]


def test_a_recursive_core_above_the_budget_blocks(fixture):
    """Only a recursive core that is on its own too big for the profile stops the compile;
    one relation that reads itself is such a core."""
    with_rules(fixture, core="""
// @explain materialize
.decl reach(a: symbol, b: symbol)
reach(a, b) :- beta__alpha(a, b).
reach(a, c) :- reach(a, b), beta__alpha(b, c).
""")
    with pytest.raises(pack.CompileError, match=r"the recursive core reach costs 3 views .* more than the budget of 2"):
        emit.compile_pack(pack.read(fixture), max_views=2)


WIDE = """
// @explain on_demand
.decl first(a: symbol)
first(a) :- alpha(a).
// @explain materialize
.decl wide(a: symbol, b: symbol)
wide(a, b) :- beta__alpha(a, b).
wide(a, b) :- beta__alpha(b, a).
wide(a, b) :- first(a), beta(b).
// @explain on_demand
.decl reader(a: symbol)
reader(a) :- wide(a, _).
// @explain on_demand
.decl other(a: symbol)
other(a) :- beta(a).
"""


def test_a_relation_above_the_budget_that_is_not_recursive_gets_a_part_of_its_own(fixture, capsys):
    """Exceeding the budget is a warning. `wide` costs 4 views (itself and a witness per
    rule) against a budget of 2: no other relation shares its part, and the compile says so."""
    model = pack.read(with_rules(fixture, core=WIDE))
    capsys.readouterr()
    files = emit.compile_pack(model, max_views=2)
    assert capsys.readouterr().err == ("warning: rules: wide costs 4 views, more than the budget of 2 per pipeline; "
                                       "it is not recursive, so it gets a pipeline of its own\n")
    plan = json.loads(files["engine/pipelines.json"])
    parts = {p["name"]: p for p in plan["pipelines"][1:]}
    [own] = [p for p in parts.values() if "wide" in p["views"]]
    assert own["views"] == ["wide"] and own["imports"] == ["first"] and own["exports"] == ["wide"]
    assert sorted(v for p in parts.values() for v in p["views"]) == ["first", "other", "reader", "wide"]
    prog = ir.load(model.rules)
    for p in parts.values():   # every other part is within the budget
        assert p is own or sum(rules_sql.views(prog, v) for v in p["views"]) <= 2
    # stable: with the previous cut nothing moves, also when a relation that nothing reads is added
    again = emit.compile_pack(model, max_views=2, previous=emit.previous_parts(plan))
    assert again["engine/pipelines.json"] == files["engine/pipelines.json"]
    with_rules(fixture, core=WIDE + "// @explain on_demand\n.decl leaf(a: symbol)\nleaf(a) :- reader(a).\n")
    grown = json.loads(emit.compile_pack(pack.read(fixture), max_views=2, previous=emit.previous_parts(plan))[
        "engine/pipelines.json"])
    kept = {v: p["name"] for p in grown["pipelines"][1:] for v in p["views"] if v != "leaf"}
    assert kept == {v: name for name, p in parts.items() for v in p["views"]}
    # within the budget nothing warns
    model = pack.read(fixture)
    capsys.readouterr()
    emit.compile_pack(model, max_views=4)
    assert capsys.readouterr().err == ""


def test_a_recursive_core_blocks_beside_a_relation_that_gets_its_own_part(fixture):
    """The exception is for a relation that is not recursive only: a recursive core above the budget
    in the same program still stops the compile."""
    with_rules(fixture, core=WIDE + """
// @explain materialize
.decl reach(a: symbol, b: symbol)
reach(a, b) :- beta__alpha(a, b).
reach(a, c) :- reach(a, b), beta__alpha(b, c).
""")
    with pytest.raises(pack.CompileError, match=r"the recursive core reach costs 3 views .* more than the budget of 2"):
        emit.compile_pack(pack.read(fixture), max_views=2)


def test_the_budget_comes_from_the_deploy_profile():
    from pathlib import Path as P

    import yaml
    for f in sorted((P(__file__).resolve().parents[2] / "deploy" / "profiles").glob("*.yaml")):
        budget = emit.view_budget(yaml.safe_load(f.read_text()))
        assert (budget.build_mb if isinstance(budget, emit.Memory) else budget) >= 1, f.name
    with pytest.raises(pack.CompileError, match="view_budget"):
        emit.view_budget({"profile": "x", "engine": {"view_budget": "64"}})
    with pytest.raises(pack.CompileError, match="view_cost_mb"):
        emit.view_budget({"profile": "x", "engine": {"build_memory_mb": 6000, "view_cost_mb": {"base": 900}}})


def memory(build_mb, **cost):
    """A build-memory budget: every kind of view free unless given."""
    return emit.Memory(build_mb, tuple((k, cost.get(k, 0)) for k in emit.VIEW_KINDS))


def test_a_build_memory_weighs_every_kind_of_view(fixture, capsys):
    """Weighed in build memory, main also holds the integrity checks; the plan records the
    estimate per pipeline, and every rule part stays within the memory."""
    model = pack.read(with_rules(fixture, **SPLIT))
    rules = sum(rules_sql.views(ir.load(model.rules), n) for n in ir.load(model.rules).derived())
    # rule views cost 10 MB each, all of them fit in one pipeline beside a base of 100 MB
    roomy = json.loads(emit.compile_pack(model, memory(100 + 10 * rules, base=100, relation=10, witness=10))[
        "engine/pipelines.json"])
    assert [p["name"] for p in roomy["pipelines"]] == ["main"] and "max_views" not in roomy
    assert roomy["build_memory_mb"] == str(100 + 10 * rules) and roomy["pipelines"][0]["build_mb"] == str(100 + 10 * rules)
    # the same memory, but the checks cost too: main no longer fits, so the rules leave it
    budget = memory(100 + 10 * rules, base=100, relation=10, witness=10, check=1, export=5)
    plan = json.loads(emit.compile_pack(model, budget)["engine/pipelines.json"])
    assert plan["pipelines"][0]["name"] == "integrity" and len(plan["pipelines"]) >= 2
    integrity = emit.compile_pack(model)["engine/integrity.sql"]
    # one view per check kind, the union and the local relations they read
    checks = integrity.count("CREATE MATERIALIZED VIEW") + integrity.count("CREATE LOCAL VIEW")
    assert plan["pipelines"][0]["build_mb"] == str(100 + checks)
    for p in plan["pipelines"][1:]:
        assert int(p["build_mb"]) <= budget.build_mb
        assert int(p["build_mb"]) == 100 + 10 * sum(rules_sql.views(ir.load(model.rules), n) for n in p["views"]) \
            + (5 if p["exports"] else 0)
    # a part holds 10 MB here: a relation with a witness (20 MB) is above it and none is recursive, so
    # each gets a part of its own with a warning
    capsys.readouterr()
    tight = json.loads(emit.compile_pack(model, memory(100, base=90, relation=10, witness=10))["engine/pipelines.json"])
    warned = capsys.readouterr().err
    heavy = [p["views"] for p in tight["pipelines"][1:] if int(p["build_mb"]) > 100]
    assert heavy and all(len(views) == 1 for views in heavy)
    for [name] in heavy:
        assert f"warning: rules: {name} costs 20 MB, more than the budget of 10 per pipeline" in warned


REFUSED = {
    "no-decl": ("p(x) :- alpha(x).", "p has no .decl"),
    "fact": (".decl p(x: symbol)\np(\"a\").", "a fact in a rule file"),
    "negated-wildcard": (".decl p(x: symbol)\np(x) :- alpha(x), !beta__alpha(_, x).", "a negation needs every column"),
    "unknown": (".decl p(x: symbol)\np(x) :- gamma(x).", "gamma is neither a table"),
    "table-decl": (".decl alpha__size(id: symbol, v: symbol)\n", "does not match its table"),
    "disjunction": (".decl p(x: symbol)\np(x) :- alpha(x); beta(x).", "disjunction"),
    "upper-case": (".decl p(x: symbol)\np(X) :- alpha(X).", "lower snake case"),
    "two-atoms": (".decl p(x: symbol, n: number)\np(a, n) :- alpha(a), n = count : { alpha(a), beta(a) }.", "one atom"),
    "not-local": (".decl p(x: symbol, n: number)\np(a, t) :- alpha__size(a, v), t = sum v : { alpha__size(a, v) }.",
                  "must be local"),
    "head-is-table": ("alpha(x) :- beta(x).", "it is a table"),
    "unsafe": (".decl p(x: symbol, y: symbol)\np(x, y) :- alpha(x).", "unsafe_variable"),
    "not-stratified": (".decl p(x: symbol)\n.decl q(x: symbol)\np(x) :- alpha(x), !q(x).\nq(x) :- alpha(x), !p(x).",
                       "not_stratified"),
    "explain-mode": ("// @explain sometimes\n.decl p(x: symbol)\np(x) :- alpha(x).", "materialize, on_demand or fold"),
    "type": (".decl p(x: symbol)\np(x) :- alpha__size(_, x).", "type_mismatch"),
    "qualifier": (".decl p(x: symbol) btree\np(x) :- alpha(x).", "qualifiers"),
    "io-args": (".decl p(x: symbol)\np(x) :- alpha(x).\n.input alpha(IO=file)", "facts come from facts/"),
    # a group key computed by arithmetic would silently become local to the aggregate.
    "computed-group-key": (".decl p(a: symbol, m: number)\n"
                           "p(a, m) :- alpha__size(a, n), z = n + 1, m = count : { alpha__size(_, z) }.",
                           "z in the aggregate over alpha__size is not bound by a positive literal"),
    "result-as-group-key": (".decl p(a: symbol, m: number)\n"
                            "p(a, m) :- alpha(a), k = count : { beta__alpha(_, a) }, m = count : { alpha__size(_, k) }.",
                            "k in the aggregate over alpha__size is not bound"),
    # a constant keeps its own type; "2" < "10" is text, not a number.
    "text-order": (".decl p(a: symbol)\np(a) :- alpha(a), \"2\" < \"10\".", "order comparison needs whole numbers"),
    "text-in-integer-column": (".decl p(a: symbol)\np(a) :- alpha__size(a, \"5\").", 'is string, but column 2 of alpha__size'),
    "number-in-text-column": (".decl p(a: symbol)\np(a) :- beta__alpha(a, 5).", "is integer, but column 2 of beta__alpha"),
    "text-arithmetic": (".decl p(a: symbol, n: number)\np(a, n) :- alpha__title(a, t), n = t + 1.",
                        "arithmetic needs whole numbers"),
    "text-equals-number": (".decl p(a: symbol)\np(a) :- alpha__size(a, s), s = \"5\".", "have different types"),
    # '_' in a comparison is a clear error, not a crash.
    "wildcard-in-comparison": (".decl p(x: symbol)\np(x) :- alpha(x), _ < \"x\".", "'_' only inside an aggregate"),
    "wildcard-in-arithmetic": (".decl p(x: symbol, n: number)\np(x, n) :- alpha__size(x, s), n = s + _.",
                               "'_' only inside an aggregate"),
    # Integer division: the divisor is a non-zero constant, so no engine ever divides by zero.
    "division-by-zero": (".decl p(a: symbol, n: number)\np(a, n) :- alpha__size(a, s), n = s / 0.", "division_by_zero"),
    "divisor-not-constant": (".decl p(a: symbol, n: number)\np(a, n) :- alpha__size(a, s), n = 60 / s.",
                             "divisor_not_constant"),
    # a constant outside BIGINT is no value on any engine (SQL casts it to BIGINT).
    "constant-out-of-range": (".decl p(a: symbol, n: number)\np(a, n) :- alpha__size(a, s), n = 9223372036854775808 - 1.",
                              "constant_out_of_range"),
    "constant-out-of-range-in-a-literal": (".decl p(a: symbol)\np(a) :- alpha__size(a, -9223372036854775809).",
                                           "constant_out_of_range"),
    # a relation without columns would give SELECT DISTINCT FROM.
    "no-columns": (".decl p()\np() :- alpha(\"a\").", "at least one column"),
    # A body of aggregates only is a rule; a body of negations only, also beside aggregates, is not.
    "negations-only": (".decl p(x: symbol)\np(\"a\") :- !alpha(\"a\").", "no_positive_literal"),
    "negation-beside-aggregates": (".decl p(n: number)\np(n) :- !alpha(\"a\"), n = count : { alpha(_) }.",
                                   "no_positive_literal"),
    # Without a literal nothing binds a group key, so a variable shared with the head is refused as before.
    "group-key-without-literal": (".decl p(a: symbol, n: number)\np(a, n) :- n = count : { beta__alpha(_, a) }.",
                                  "a in the aggregate over beta__alpha is not bound by a positive literal"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_refused_with_a_clear_error(fixture, case):
    text, message = REFUSED[case]
    with pytest.raises(pack.CompileError, match=message):
        pack.read(with_rules(fixture, core=text))


def test_a_rule_belongs_in_the_module_of_its_relation(fixture):
    with_rules(fixture, one=".decl p(x: symbol)\np(x) :- alpha(x).", two="p(x) :- beta(x).")
    with pytest.raises(pack.CompileError, match=r"belongs in rules/one\.dl"):
        pack.read(fixture)


def test_mutual_recursion_is_refused_by_the_batch_backend_only(fixture, capsys):
    """E10: Feldera takes mutual recursion, DuckDB does not. The refusal is the batch script's alone, and the
    compiler warns of it with a stable code: nobody has to run the script to learn it will fail."""
    model = pack.read(with_rules(fixture, core="""
.decl a(x: symbol)
.decl b(x: symbol)
a(x) :- alpha(x).
a(x) :- b(x).
b(x) :- a(x).
"""))
    capsys.readouterr()
    files = emit.compile_pack(model)
    reason = [f"{n}: the batch backend takes linear recursion with one recursive rule and at least one base rule"
              for n in ir.load(model.rules).derived()[:1]]
    assert 'DECLARE RECURSIVE VIEW "a"' in files["engine/rules.sql"]
    assert files["batch/rules.sql"].splitlines()[1:] == [f"SELECT error('rules: {r}');" for r in reason]
    assert emit.BATCH_REFUSES == "batch_refuses_rules"  # stable: a tool may match on it
    assert capsys.readouterr().err.splitlines() == [
        f"warning: rules: batch_refuses_rules: {r}; batch/rules.sql fails with this reason when it runs"
        for r in reason]


def test_a_program_the_batch_backend_takes_gives_no_such_warning(fixture, capsys):
    """Linear recursion with one recursive rule (`reach`) runs on both engines: no refusal, no warning."""
    model = pack.read(with_rules(fixture, core=PROGRAM))
    capsys.readouterr()
    files = emit.compile_pack(model)
    assert "SELECT error(" not in files["batch/rules.sql"]
    assert emit.BATCH_REFUSES not in capsys.readouterr().err


def test_a_derived_relation_may_carry_a_label(fixture):
    with_rules(fixture, core=".decl lonely(a: symbol)\nlonely(a) :- alpha(a), !beta__alpha(a, a).")
    labels = fixture / "labels" / "nl.yaml"
    labels.write_text(labels.read_text() + "lonely: alleen\n")
    model = pack.read(fixture)
    assert {"element": "lonely", "lang": "nl", "text": "alleen"} in model.labels


def test_modules_that_read_each_other_stay_in_one_part(fixture):
    """No relation is recursive, but module `one` reads `two` and `two` reads `one`: one part, in order."""
    with_rules(fixture, one="""
.decl first(a: symbol)
first(a) :- alpha(a).
.decl third(a: symbol)
third(a) :- second(a).
""", two="""
.decl second(a: symbol)
second(a) :- first(a).
""", zero="""
.decl late(a: symbol)
late(a) :- third(a), beta(a).
""")
    files = emit.compile_pack(pack.read(fixture), max_views=6)
    plan = json.loads(files["engine/pipelines.json"])
    assert [(p["name"], p["modules"]) for p in plan["pipelines"]] == [
        ("integrity", []), ("rules-1", ["one", "two"]), ("rules-2", ["zero"])]


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_the_source_as_written_equals_the_batch_backend_on_souffle(fixture, tmp_path):
    """Soufflé runs the .dl text itself, not the IR the parser made of it: a parser error shows here."""
    import souffle
    from rezono_compiler import batch

    prog = ir.load(pack.read(with_rules(fixture, core=PROGRAM)).rules)
    data = {"alpha": [("a1",), ("a2",), ("a3",)], "alpha__size": [("a1", 7), ("a2", 3), ("a3", 7)],
            "alpha__size__maximum": [(9,)], "beta__alpha": [("b1", "a1"), ("b2", "a1"), ("b3", "a2"), ("a1", "a3")]}
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    text = souffle.source(prog, [(fixture / "rules" / "core.dl").read_text()])
    assert souffle.run(prog, data, tmp_path, program_text=text) == batch.read(con, prog)


DIVISION = """
.decl part(a: symbol, d: number, q: number)
part(a, d, q) :- alpha__size(a, s), d = s - 30, q = d / -7.
"""


def test_division_truncates_toward_zero_on_every_engine(fixture, tmp_path):
    """`div` is Feldera's `/` on BIGINT: truncation toward zero, also with negative operands. Floor division
    would give -1 for 1 / -7 and -5 for 29 / -7. Feldera's SQL divides with `/`, DuckDB's with the macro
    rezono_quotient; Soufflé, where present, reads the text as written."""
    pytest.importorskip("duckdb")
    from rezono_compiler import batch

    files = emit.compile_pack(pack.read(with_rules(fixture, core=DIVISION)))
    assert "/ CAST(-7 AS BIGINT)" in files["engine/rules.sql"] and "rezono_quotient" not in files["engine/rules.sql"]
    assert files["batch/rules.sql"].count("rezono_quotient(") == 2  # the macro and the rule (s is projected: on demand)
    prog = ir.load(pack.read(fixture).rules)
    assert "/ CAST(-7 AS BIGINT)" in rules_sql.witness_select(prog, prog.rules["part"])   # the witness query is engine SQL
    sizes = [0, 23, 29, 30, 31, 37, 59]
    data = {"alpha": [(f"a{s}",) for s in sizes], "alpha__size": [(f"a{s}", s) for s in sizes]}
    con = batch.connect(prog, data)
    batch.compute(con, prog, witnesses=True)
    want = {("a0", "-30", "4"), ("a23", "-7", "1"), ("a29", "-1", "0"), ("a30", "0", "0"), ("a31", "1", "0"),
            ("a37", "7", "-1"), ("a59", "29", "-4")}
    assert batch.read(con, prog)["part"] == want
    assert len(batch.witnesses(con, prog)["part"]) == len(sizes)
    # At the edge of BIGINT: abs(-2^63) fits only because the macro works on 128 bits.
    edge = "SELECT rezono_quotient(CAST(-9223372036854775808 AS BIGINT), CAST(60 AS BIGINT)), " \
           "rezono_quotient(CAST(9223372036854775807 AS BIGINT), CAST(-60 AS BIGINT))"
    assert con.execute(edge).fetchone() == (-153722867280912930, -153722867280912930)
    if shutil.which("souffle"):
        import souffle
        text = souffle.source(prog, [(fixture / "rules" / "core.dl").read_text()])
        assert souffle.run(prog, data, tmp_path, program_text=text) == batch.read(con, prog)


def on_demand(**rules):
    """Relations of one view each (explained on demand), one rule per relation: name=body."""
    return "".join(f"// @explain on_demand\n.decl {n}(x: symbol)\n{n}(x) :- {body}.\n" for n, body in rules.items())


@pytest.mark.parametrize("names", [("a", "b", "c", "d", "e"), ("a", "b", "z", "d", "e")], ids=["c-first", "d-first"])
def test_a_new_part_when_it_keeps_the_chain_shorter(fixture, names):
    """Budget 2, one view each, c reads a and e reads d. Two parts in a row, not three,
    whichever of c and d comes first."""
    a, b, c, d, e = names
    with_rules(fixture, core=on_demand(**{a: "alpha(x)", b: "beta(x)", c: f"{a}(x)", d: "alpha__title(x, _)", e: f"{d}(x)"}))
    plan = json.loads(emit.compile_pack(pack.read(fixture), max_views=2)["engine/pipelines.json"])
    parts = {p["name"]: p for p in plan["pipelines"][1:]}
    owner = {v: p["name"] for p in parts.values() for v in p["views"]}
    depth = {}
    for name, p in parts.items():   # parts read only earlier parts, so one pass gives the chain
        depth[name] = 1 + max((depth[owner[r]] for r in p["imports"]), default=0)
    assert max(depth.values()) == 2, parts


def test_a_part_keeps_its_name_when_an_earlier_part_empties(fixture):
    """Budget 1, parts a, b and c; without b, c stays rules-3 (the cache of its pipeline)."""
    with_rules(fixture, core=on_demand(a="alpha(x)", b="beta(x)", c="alpha__title(x, _)"))
    first = json.loads(emit.compile_pack(pack.read(fixture), max_views=1)["engine/pipelines.json"])
    assert [(p["name"], p["views"]) for p in first["pipelines"][1:]] == [("rules-1", ["a"]), ("rules-2", ["b"]), ("rules-3", ["c"])]
    with_rules(fixture, core=on_demand(a="alpha(x)", c="alpha__title(x, _)"))
    files = emit.compile_pack(pack.read(fixture), max_views=1, previous=emit.previous_parts(first))
    second = json.loads(files["engine/pipelines.json"])
    assert [(p["name"], p["views"]) for p in second["pipelines"][1:]] == [("rules-1", ["a"]), ("rules-3", ["c"])]
    assert "engine/rules-3.sql" in files and "engine/rules-2.sql" not in files
    assert emit.previous_parts(second) == [["a"], [], ["c"]]


# ---- what a missing row means, per relation ----


WORLDS = """
.decl pair(a: symbol, b: symbol)
pair(a, b) :- beta__alpha(b, a).

// @absence
.decl sized(a: symbol, n: number)
sized(a, n) :- alpha(a), n = count : { beta__alpha(_, a) }.

.decl big(a: symbol)
big(a) :- alpha__size(a, s), s >= 5.

.decl paired(a: symbol)
paired(a) :- pair(a, _).

// @absence
.decl unpaired(a: symbol)
unpaired(a) :- alpha(a), !paired(a).

// @absence
.decl unpaired_big(a: symbol)
unpaired_big(a) :- unpaired(a), big(a).

.decl settled(a: symbol)
settled(a) :- alpha(a), !unpaired(a).
"""


def annotate(d: Path, cls: str, world: str, slot: str | None = None, extra: dict | None = None) -> Path:
    """Put `world` on a class (or one of its slots) of the fixture schema."""
    f = d / "schema" / "minimal.yaml"
    s = yaml.safe_load(f.read_text())
    s["classes"].update(extra or {})
    target = s["classes"][cls] if slot is None else s["classes"][cls]["attributes"][slot]
    target.setdefault("annotations", {})["world"] = world
    f.write_text(yaml.safe_dump(s, sort_keys=False))
    return d


def test_without_annotations_every_relation_is_closed(fixture):
    prog = ir.load(pack.read(with_rules(fixture, core=PROGRAM)).rules)
    assert {r.world for r in prog.relations.values()} == {"closed"}


def test_world_follows_the_schema_and_the_rules(fixture):
    model = pack.read(with_rules(annotate(fixture, "Beta", "open"), core=WORLDS))
    assert (model.kinds["beta"].world, model.kinds["alpha"].world) == ("open", "closed")
    assert {s.name: s.world for s in model.kinds["beta"].slots.values()} == {"alpha": "open", "state": "open"}
    prog = ir.load(model.rules)
    assert {n: r.world for n, r in prog.relations.items() if r.role == "derived"} == {
        "pair": "open", "paired": "open",  # read an open relation
        "sized": "closed",  # counts what is recorded: @absence
        "big": "closed", "unpaired": "closed", "unpaired_big": "closed", "settled": "closed"}
    assert prog.relations["beta__alpha"].world == "open" and prog.relations["alpha__size"].world == "closed"
    assert {n for n, r in prog.relations.items() if r.absence} == {"sized", "unpaired", "unpaired_big"}
    # The IR document and the bundle carry the world; the document reads back the same.
    doc = ir.to_doc(prog)
    assert ir.to_doc(ir.load(doc)) == doc
    files = emit.compile_pack(model)
    b = json.loads(files["bundle/schema-bundle.json"])
    assert {k["id"]: k["world"] for k in b["kinds"]} == {"alpha": "closed", "beta": "open"}
    assert {a["id"]: a["world"] for a in b["arrows"]} == {"beta.alpha": "open"}
    rels = {r["id"]: r for r in b["relations"]}
    assert rels["unpaired"]["world"] == "closed" and rels["unpaired"]["absence"] is True
    assert rels["pair"]["world"] == "open" and "absence" not in rels["pair"]


def test_a_slot_can_be_open_on_its_own(fixture):
    model = pack.read(annotate(fixture, "Alpha", "open", slot="size"))
    assert model.kinds["alpha"].world == "closed"
    assert {s.name: s.world for s in model.kinds["alpha"].slots.values()} == {"size": "open", "title": "closed"}


def test_a_subkind_of_an_open_kind_is_open(fixture):
    model = pack.read(annotate(fixture, "Alpha", "open", extra={"Gamma": {"is_a": "Alpha"}}))
    assert model.kinds["gamma"].world == "open"


OPEN_REFUSED = {
    "negation-over-open": (".decl paired(a: symbol)\npaired(a) :- beta__alpha(_, a).\n"
                           ".decl lonely(a: symbol)\nlonely(a) :- alpha(a), !paired(a).", "negation_over_open"),
    "negation-over-open-table": (".decl lonely(a: symbol)\nlonely(a) :- alpha(a), !beta(a).", "negation_over_open"),
    # a count over an open relation is what is recorded; n = 0 is no evidence of none.
    "count-zero-over-open": (".decl alone(a: symbol)\nalone(a) :- alpha(a), n = count : { beta__alpha(_, a) }, n = 0.",
                             "aggregate_over_open"),
    # W6 is the same without a group key: the number of rows recorded is no number of what exists.
    "count-over-open-without-a-literal": (".decl links(n: number)\nlinks(n) :- n = count : { beta__alpha(_, _) }.",
                                          "aggregate_over_open"),
    "absence-without-open": ("// @absence\n.decl small(a: symbol)\nsmall(a) :- alpha(a), !big(a).\n"
                             ".decl big(a: symbol)\nbig(a) :- alpha__size(a, s), s >= 5.", "bad_absence"),
    "absence-on-a-table": ("// @absence\n.decl alpha(id: symbol)\n.decl p(x: symbol)\np(x) :- alpha(x).",
                           "@absence and @outcome are for derived relations"),
}


@pytest.mark.parametrize("case", sorted(OPEN_REFUSED))
def test_open_world_refusals(fixture, case):
    text, message = OPEN_REFUSED[case]
    with pytest.raises(pack.CompileError, match=message):
        pack.read(with_rules(annotate(fixture, "Beta", "open"), core=text))


def test_a_release_is_refused_until_it_is_built(fixture):
    """O8 stays the default: a delimited release (`// @release`) is reserved, not supported yet."""
    with pytest.raises(pack.CompileError, match="@release is not supported yet"):
        pack.read(with_rules(fixture, core="// @release member\n.decl p(x: symbol)\np(x) :- alpha(x)."))


def test_a_world_annotation_is_open_or_closed(fixture):
    with pytest.raises(pack.CompileError, match="world must be one of"):
        pack.read(annotate(fixture, "Beta", "sometimes"))


def schema_with(d: Path, edit) -> Path:
    f = d / "schema" / "minimal.yaml"
    s = yaml.safe_load(f.read_text())
    edit(s)
    f.write_text(yaml.safe_dump(s, sort_keys=False))
    return d


WORLD_PLACES = {
    # an open subkind would share closed tables with its parent.
    "subkind": (lambda s: s["classes"].update(Gamma={"is_a": "Alpha", "annotations": {"world": "open"}}),
                "world goes on the root kind"),
    "identifier": (lambda s: s["classes"]["Alpha"]["attributes"]["id"].update(annotations={"world": "open"}),
                   "not on its identifier"),
    "schema": (lambda s: s["annotations"].update(world="open"), "not on a schema"),
    "closed-slot-of-open-kind": (lambda s: (s["classes"]["Beta"].update(annotations={"world": "open"}),
                                            s["classes"]["Beta"]["attributes"]["alpha"].update(annotations={"world": "closed"})),
                                 "a slot of an open kind is open"),
    "bad-slot-value-of-open-kind": (lambda s: (s["classes"]["Beta"].update(annotations={"world": "open"}),
                                               s["classes"]["Beta"]["attributes"]["alpha"].update(annotations={"world": "x"})),
                                    "world must be one of"),
}


@pytest.mark.parametrize("case", sorted(WORLD_PLACES))
def test_world_only_where_it_means_something(fixture, case):
    edit, message = WORLD_PLACES[case]
    with pytest.raises(pack.CompileError, match=message):
        pack.read(schema_with(fixture, edit))


def test_a_declared_world_must_agree_with_the_rules(fixture):
    doc = ir.to_doc(ir.load(pack.read(with_rules(annotate(fixture, "Beta", "open"), core=WORLDS)).rules))
    for r in doc["relations"]:
        if r["name"] == "pair":
            r["world"] = "closed"
    with pytest.raises(ir.IRError, match="bad_world"):
        ir.load(doc)


# ---- a named outcome, with a state and a reason per element ----

OUTCOME = WORLDS + """
// @absence
.decl has_unpaired(a: symbol)
has_unpaired(a) :- unpaired(a).

// @outcome alpha
.decl pairing(a: symbol, state: symbol, reason: symbol)
pairing(a, "unknown", "unpaired") :- unpaired(a).
pairing(a, "known", "") :- alpha(a), !has_unpaired(a).

.decl partner(a: symbol, b: symbol)
partner(a, b) :- pairing(a, "known", _), beta__alpha(b, a).
"""


def with_reason(d: Path, *reasons: str) -> Path:
    with (d / "messages" / "nl.mf2").open("a", encoding="utf-8") as f:
        f.writelines(f"reason.{r} = {{{{Reden {r}.}}}}\n" for r in reasons)
    return d


def test_an_outcome_has_a_kind_a_state_and_a_reason(fixture):
    model = pack.read(with_reason(with_rules(annotate(fixture, "Beta", "open"), core=OUTCOME), "unpaired"))
    prog = ir.load(model.rules)
    assert prog.relations["pairing"].outcome == "alpha" and prog.relations["pairing"].world == "closed"
    # partner reads an open relation behind the known row of an outcome: complete for known elements only,
    # so it stays open, and only an @absence relation may negate it
    assert prog.relations["partner"].world == "open"
    files = emit.compile_pack(model)
    rel = {r["id"]: r for r in json.loads(files["bundle/schema-bundle.json"])["relations"]}["pairing"]
    assert (rel["outcome"], rel["checks"]) == ("alpha", ["pairing__total", "pairing__state"])
    assert 'CREATE MATERIALIZED VIEW "pairing__total"' in files["engine/rules.sql"]
    assert ir.to_doc(ir.load(ir.to_doc(prog))) == ir.to_doc(prog)


def test_an_outcome_reason_needs_its_message(fixture):
    with pytest.raises(pack.CompileError, match=r"reason\.unpaired"):
        pack.read(with_rules(annotate(fixture, "Beta", "open"), core=OUTCOME))


OUTCOME_REFUSED = {
    "unknown-kind": ('// @outcome gamma\n.decl o(a: symbol, state: symbol, reason: symbol)\no(a, "known", "") :- alpha(a).',
                     "names a kind of the pack"),
    "columns": ('// @outcome alpha\n.decl o(a: symbol, s: symbol, reason: symbol)\no(a, "known", "") :- alpha(a).',
                "three columns"),
    "state": ('// @outcome alpha\n.decl o(a: symbol, state: symbol, reason: symbol)\no(a, "maybe", "x") :- alpha(a).',
              "the state is a constant"),
    "known-with-reason": ('// @outcome alpha\n.decl o(a: symbol, state: symbol, reason: symbol)\no(a, "known", "x") :- alpha(a).',
                          "the reason is a constant"),
    "variable-reason": ('// @outcome alpha\n.decl o(a: symbol, state: symbol, reason: symbol)\n'
                        'o(a, "unknown", r) :- alpha__title(a, r).', "the reason is a constant"),
    "open": ('// @outcome alpha\n.decl o(a: symbol, state: symbol, reason: symbol)\n'
             'o(a, "known", "") :- beta__alpha(_, a).', "must be closed"),
    # the known row of a1 says nothing about a2; seen(x) stays open, so !seen(x) is refused.
    # d is complete only where pairing is known; for an unknown element d is missing because
    # the guard failed, so !d(v) would conclude too much.
    "negation-over-a-guarded-relation": (OUTCOME + '.decl d(v: symbol)\nd(v) :- pairing(v, "known", _), beta__alpha(_, v).\n'
                                         '.decl r(v: symbol)\nr(v) :- alpha(v), !d(v).', "negation_over_open"),
    "known-row-of-another-element": (OUTCOME + '.decl seen(x: symbol)\nseen(x) :- pairing(a, "known", _), beta__alpha(_, x).\n'
                                     '.decl absent(x: symbol)\nabsent(x) :- alpha(x), !seen(x).', "negation_over_open"),
}


@pytest.mark.parametrize("case", sorted(OUTCOME_REFUSED))
def test_outcome_refusals(fixture, case):
    text, message = OUTCOME_REFUSED[case]
    with pytest.raises(pack.CompileError, match=message):
        pack.read(with_reason(with_rules(annotate(fixture, "Beta", "open"), core=text), "unpaired"))


def test_the_outcome_checks_find_a_missing_row_and_two_states(fixture):
    pytest.importorskip("duckdb")
    from rezono_compiler import batch

    with_reason(fixture, "small")

    def run(text):
        prog = ir.load(pack.read(with_rules(fixture, core=text)).rules)
        con = batch.connect(prog, {"alpha": [("a1",), ("a2",)], "alpha__size": [("a1", 1), ("a2", 3)]})
        batch.compute(con, prog)
        return {v: sorted(r[0] for r in con.execute(f'SELECT * FROM "{v}"').fetchall())
                for v in ("sizing__total", "sizing__state")}

    head = '// @outcome alpha\n.decl sizing(a: symbol, state: symbol, reason: symbol)\n'
    small = 'sizing(a, "unknown", "small") :- alpha__size(a, s), s < 2.\n'
    known = 'sizing(a, "known", "") :- alpha__size(a, s), s >= 2.\n'
    spare = 'sizing(a, "not_applicable", "small") :- alpha__size(a, s), s < 2.\n'
    assert run(head + small + known) == {"sizing__total": [], "sizing__state": []}
    assert run(head + small) == {"sizing__total": ["a2"], "sizing__state": []}
    assert run(head + small + known + spare) == {"sizing__total": [], "sizing__state": ["a1"]}
    # a row for an element that is not there is caught too.
    ghost = 'sizing("ghost", "unknown", "small") :- alpha(a).\n'
    assert run(head + small + known + ghost) == {"sizing__total": ["ghost"], "sizing__state": []}


# A body of aggregates only: a count, a sum, a minimum or a maximum over a whole relation. No literal,
# so no group key, and each relation has one row at most.
WHOLE = """
.decl sizes(n: number, t: number)
sizes(n, t) :- n = count : { alpha__size(_, _) }, t = sum s : { alpha__size(_, s) }.

.decl largest(m: number)
largest(m) :- m = max s : { alpha__size(_, s) }.

.decl span(d: number)
span(d) :- hi = max s : { alpha__size(_, s) }, lo = min s : { alpha__size(_, s) }, d = hi - lo.

.decl sevens(n: number)
sevens(n) :- n = count : { alpha__size(_, 7) }.

.decl crowded(flag: symbol)
crowded("yes") :- n = count : { alpha(_) }, n >= 3.

// A relation that reads the absence of one of them, so the checker's closure pass covers it.
.decl calm(a: symbol)
calm(a) :- alpha(a), !crowded("yes").

// Over a derived relation, one stratum up.
.decl calm_ones(n: number)
calm_ones(n) :- n = count : { calm(_) }.
"""
NOTHING = {"alpha": [], "alpha__size": []}
TWO = {"alpha": [("a1",), ("a2",)], "alpha__size": [("a1", 7)]}
THREE = {"alpha": [("a1",), ("a2",), ("a3",)], "alpha__size": [("a1", 7), ("a2", 3), ("a3", 7)]}
WHOLE_WANT = {
    # Over nothing: a count and a sum are 0, a minimum and a maximum give no row (as the grouped form, and Soufflé).
    "nothing": (NOTHING, {"sizes": {("0", "0")}, "largest": set(), "span": set(), "sevens": {("0",)},
                          "crowded": set(), "calm": set(), "calm_ones": {("0",)}}),
    "two": (TWO, {"sizes": {("1", "7")}, "largest": {("7",)}, "span": {("0",)}, "sevens": {("1",)},
                  "crowded": set(), "calm": {("a1",), ("a2",)}, "calm_ones": {("2",)}}),
    "three": (THREE, {"sizes": {("3", "17")}, "largest": {("7",)}, "span": {("4",)}, "sevens": {("2",)},
                      "crowded": {("yes",)}, "calm": set(), "calm_ones": {("0",)}}),
}


def test_a_body_of_aggregates_only_becomes_the_rule_ir(fixture):
    model = pack.read(with_rules(fixture, core=WHOLE))
    prog = ir.load(model.rules)
    sizes = prog.rules["sizes"]
    assert sizes.body == () and sizes.variables == ("?n", "?t")
    assert [(a.function, a.atom.terms, a.over) for a in sizes.aggregates] == [
        ("count", ("_", "_"), None), ("sum", ("_", "_"), "v")]
    assert prog.rules["sevens"].aggregates[0].atom.terms == ("_", "7")
    assert prog.rules["crowded"].head.terms == ("yes",) and prog.rules["crowded"].variables == ("?n",)
    assert prog.strata["calm_ones"] > prog.strata["calm"] > prog.strata["crowded"] > 0
    # No variable of a literal is projected away, so every witness is materialised: one row per conclusion.
    whole = ("sizes", "largest", "span", "sevens", "crowded", "calm_ones")
    assert {n: prog.relations[n].explain for n in whole} == dict.fromkeys(whole, "materialize")
    doc = ir.to_doc(prog)
    assert ir.to_doc(ir.load(doc)) == doc and next(r for r in doc["rules"] if r["id"] == "sizes")["body"] == []


def test_a_body_of_aggregates_only_compiles_for_both_backends(fixture):
    """The first subquery is the FROM, without a GROUP BY; a later one joins it as before. The same text for
    Feldera and for the batch backend (no division here), in the relation and its witness."""
    model = pack.read(with_rules(fixture, core=WHOLE))
    files = emit.compile_pack(model)
    assert files == emit.compile_pack(pack.read(fixture))   # the same input gives the same bytes
    prog = ir.load(model.rules)
    count = '(SELECT CAST(COUNT(*) AS BIGINT) AS r FROM "alpha__size") AS g0'
    total = 'LEFT JOIN (SELECT CAST(SUM("v") AS BIGINT) AS r FROM "alpha__size") AS g1 ON TRUE'
    results = 'COALESCE(g0.r, CAST(0 AS BIGINT)) AS "{}", COALESCE(g1.r, CAST(0 AS BIGINT)) AS "{}"'
    select = f"SELECT DISTINCT {results.format('n', 't')} FROM {count} {total}"
    assert rules_sql.rule_select(prog, prog.rules["sizes"]) == select
    assert rules_sql.rule_select(prog, prog.rules["sizes"], dialect="duckdb") == select
    witness = f"SELECT DISTINCT {results.format('v_n', 'v_t')} FROM {count} {total}"
    assert rules_sql.witness_select(prog, prog.rules["sizes"]) == witness
    for name in ("engine/rules.sql", "batch/rules.sql"):
        assert select in files[name] and witness in files[name], name
    # A minimum or maximum over nothing is no row: the subquery keeps a row only when there is one to fold.
    assert rules_sql.rule_select(prog, prog.rules["largest"]) == (
        'SELECT DISTINCT g0.r AS "m" FROM (SELECT CAST(MAX("v") AS BIGINT) AS r FROM "alpha__size" '
        "HAVING COUNT(*) > 0) AS g0")
    # A filter on a constant stays in the subquery; a condition on a result is the WHERE.
    assert rules_sql.rule_select(prog, prog.rules["sevens"]).endswith(
        'FROM "alpha__size" WHERE "v" = CAST(7 AS BIGINT)) AS g0')
    assert rules_sql.rule_select(prog, prog.rules["crowded"]).endswith(
        "AS g0 WHERE COALESCE(g0.r, CAST(0 AS BIGINT)) >= CAST(3 AS BIGINT)")
    bundle = json.loads(files["bundle/schema-bundle.json"])
    assert next(r for r in bundle["rules"] if r["id"] == "sizes")["variables"] == [
        {"name": "?n", "type": "integer"}, {"name": "?t", "type": "integer"}]


@pytest.mark.parametrize("case", sorted(WHOLE_WANT))
def test_a_body_of_aggregates_only_on_the_batch_backend_the_checker_and_souffle(fixture, tmp_path, case):
    """What the form derives, also over an empty relation; one witness per row, which the independent checker
    accepts, alone and as an epoch (so the closure pass enumerates the rule too); a changed result, and a row the
    engine left out, are refused. Soufflé, where it is installed, reads the IR and the text as written."""
    pytest.importorskip("duckdb")
    import hashlib

    from rezono_checker.check import check, check_epoch
    from rezono_checker.rules import derived_relations, load_rules
    from rezono_compiler import batch, explain

    data, want = WHOLE_WANT[case]
    model = pack.read(with_rules(fixture, core=WHOLE))
    prog = ir.load(model.rules)
    con = batch.connect(prog, data)
    batch.compute(con, prog, witnesses=True)
    derived = batch.read(con, prog)
    assert derived == want
    for rule in prog.rules.values():   # the witness tables: sound and complete, one substitution per conclusion
        rows = con.execute(f'SELECT * FROM "{rule.witness_relation}"').fetchall()
        heads = [tuple(dict(zip(rule.variables, map(str, r))).get(t, t) for t in rule.head.terms) for r in rows]
        assert sorted(heads) == sorted(want[rule.head.relation]), rule.id
    if shutil.which("souffle"):
        import souffle
        assert souffle.run(prog, data, tmp_path) == derived
        text = souffle.source(prog, [(fixture / "rules" / "core.dl").read_text()])
        assert souffle.run(prog, data, tmp_path, program_text=text) == derived

    base = [n for n, r in prog.relations.items() if r.role == "base"]
    ex = explain.Explainer(prog, batch.read(con, prog, base) | derived, batch.witnesses(con, prog))
    snaps = {r: ex.snapshot(r).encode() for r in prog.relations}

    def manifest(snaps):
        return {"id": "m", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                          "sha256": hashlib.sha256(b).hexdigest()} for r, b in sorted(snaps.items())]}

    rules = load_rules(model.rules)
    for rel in ("sizes", "largest", "span", "sevens", "crowded", "calm_ones"):
        for key in derived[rel]:
            proof = ex.proof(rel, key, "m")
            (w,) = [w for w in proof["witnesses"] if w["conclusion"]["relation"] == rel]
            assert w["premises"] == [] and {a["group_key"] for a in w["aggregates"]} <= {"[]", '["7"]'}
            report = check(proof, manifest(snaps), rules, snaps.__getitem__)
            assert report["valid"] and not report["findings"], (rel, report["findings"])
            w["aggregates"][0]["result"] = "known:99"   # a planted fault: the proof names another result
            report = check(proof, manifest(snaps), rules, snaps.__getitem__)
            assert not report["valid"] and "aggregate_result" in {f["reason"] for f in report["findings"]}

    def epoch(snaps):
        return check_epoch(ex.chosen(), manifest(snaps), rules, snaps.__getitem__,
                           derived=derived_relations(model.rules, rules))

    report = epoch(snaps)
    assert report["valid"] and not report["findings"], report["findings"]
    if case == "three":   # crowded("yes") left out: nothing else then fails to check, only the closure pass
        missing = snaps | {"crowded": b"[\n]\n"}
        found = {(f["reason"], f.get("relation")) for f in epoch(missing)["findings"] if f["severity"] == "error"}
        assert ("underived_row", "crowded") in found


def test_an_absence_relation_may_count_an_open_relation_without_a_literal(fixture):
    """W6 as it was: over an open relation only in an @absence relation, and the result is what is recorded."""
    text = "// @absence\n.decl links(n: number)\nlinks(n) :- n = count : { beta__alpha(_, _) }."
    prog = ir.load(pack.read(with_rules(annotate(fixture, "Beta", "open"), core=text)).rules)
    assert (prog.relations["links"].world, prog.relations["links"].absence) == ("closed", True)


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
@pytest.mark.parametrize("seed", range(12))
def test_generated_bodies_of_aggregates_only_equal_souffle_as_sets(seed, tmp_path):
    """The bounded oracle check of the form, per pull request: small generated programs in which a body of
    aggregates only stands beside grouped aggregates, negation and unions, over generated facts (a constant in
    an aggregated atom mostly matches nothing: a count of 0, no minimum). The properties over every shape are
    in test_rules_properties.py (`compiler` / `full`, and nightly on main)."""
    pytest.importorskip("duckdb")
    import rulegen
    import souffle
    from rezono_compiler import batch

    doc = rulegen.program(seed, 6, shapes=("total", "count", "sum", "negation", "union"))
    prog = ir.load(doc)
    data = rulegen.facts(doc, seed, 40, domain=20)
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    assert batch.read(con, prog) == souffle.run(prog, data, tmp_path)


# A counter with an explicit bound: the shape of a depth from seeds along steps. What it computes,
# against a reference and Soufflé, is in test_bound.py.
COUNTER = """
.decl step(a: symbol, b: symbol)
step(a, b) :- beta__alpha(a, b).

.decl depth(a: symbol, n: number)
depth(a, 0) :- alpha(a).
depth(b, m) :- depth(a, n), n < 3, step(a, b), !alpha(b), m = n + 1.
"""


def test_a_counter_with_an_explicit_bound_is_unrolled_and_gets_a_check(fixture):
    model = pack.read(with_rules(fixture, core=COUNTER))
    prog = ir.load(model.rules)
    # read while n is at most 2, from 0 by 1: the rule fires three times at most
    assert prog.bounds == {"depth": ir.Bound("depth_2", 1, "?n", 0, 1, 2, 3)}
    assert prog.recursive("depth") and ir.to_doc(ir.load(ir.to_doc(prog))) == ir.to_doc(prog)
    files = emit.compile_pack(model)
    for name in ("engine/rules.sql", "batch/rules.sql"):
        assert "RECURSIVE" not in files[name], name
        assert [f'"depth__{i}" AS (' in files[name] for i in range(5)] == [True] * 4 + [False], name
        assert '"depth__exhausted"' in files[name], name
    rel = {r["id"]: r for r in json.loads(files["bundle/schema-bundle.json"])["relations"]}["depth"]
    assert rel["checks"] == ["depth__exhausted"]
    # the check is the counting rule with its bound turned round, over the final relation
    (view, select), = rules_sql.bound_checks(prog, "depth")
    assert view == "depth__exhausted" and "> CAST(2 AS BIGINT)" in select and "< CAST(3 AS BIGINT)" not in select


def counter(recursive: str, start: str = "depth(a, 0) :- alpha(a).") -> str:
    return (".decl step(a: symbol, b: symbol)\nstep(a, b) :- beta__alpha(a, b).\n"
            f".decl depth(a: symbol, n: number)\n{start}\n{recursive}\n")


COUNTER_REFUSED = {
    "no-bound": (counter("depth(b, m) :- depth(a, n), step(a, b), m = n + 1."), "no condition bounds"),
    "bound-on-the-sum": (counter("depth(b, m) :- depth(a, n), step(a, b), m = n + 1, m < 3."), "no condition bounds"),
    "bound-is-a-variable": (counter("depth(b, m) :- depth(a, n), step(a, b), alpha__size(a, s), n < s, m = n + 1."),
                            "no condition bounds"),
    "bound-from-below": (counter("depth(b, m) :- depth(a, n), n > 3, step(a, b), m = n + 1."), "no condition bounds"),
    "step-of-zero": (counter("depth(b, m) :- depth(a, n), n < 3, step(a, b), m = n + 0."), "adds a positive constant"),
    "counts-down": (counter("depth(b, m) :- depth(a, n), n < 3, step(a, b), m = n - 1."), "adds a positive constant"),
    "multiplies": (counter("depth(b, m) :- depth(a, n), n < 3, step(a, b), m = n * 2."), "adds a positive constant"),
    "adds-itself": (counter("depth(b, m) :- depth(a, n), n < 3, step(a, b), m = n + n."), "adds a positive constant"),
    "starts-at-a-variable": (counter("depth(b, m) :- depth(a, n), n < 3, step(a, b), m = n + 1.",
                                     "depth(a, s) :- alpha__size(a, s)."), "does not start m at a constant"),
    "starts-nowhere": (counter("depth(b, m) :- depth(a, n), n < 3, step(a, b), m = n + 1.", ""), "the count starts nowhere"),
    "reads-itself-twice": (counter("depth(b, m) :- depth(a, n), depth(b, n), n < 3, m = n + 1."), "exactly once"),
    "another-recursive-rule": (counter("depth(b, m) :- depth(a, n), n < 3, step(a, b), m = n + 1.\n"
                                       "depth(b, n) :- depth(a, n), step(a, b)."), "the count starts nowhere"),
    "through-another-relation": (counter(".decl seen(a: symbol, n: number)\nseen(a, n) :- depth(a, n).\n"
                                         "depth(b, m) :- seen(a, n), n < 3, step(a, b), m = n + 1."), "exactly once"),
    "too-deep": (counter("depth(b, m) :- depth(a, n), n < 1000, step(a, b), m = n + 1."), "takes 1000 strata"),
}


@pytest.mark.parametrize("case", sorted(COUNTER_REFUSED))
def test_arithmetic_in_recursion_is_refused_unless_it_is_a_bounded_counter(fixture, case):
    text, message = COUNTER_REFUSED[case]
    with pytest.raises(pack.CompileError, match=f"recursive_assignment.*{message}"):
        pack.read(with_rules(fixture, core=text))


# Fold marks: display only, and only on a helper.
MARK = "// @explain fold\n"
FOLDED = """
// ends: the join between an alpha and a state; `opposite` alone reads it.
// @explain on_demand
// @explain fold
.decl ends(a: symbol, s: symbol)
ends(a, s) :- beta__alpha(b, a), beta__state(b, s).

.decl opposite(a: symbol, b: symbol)
opposite(a, b) :- ends(a, "low"), ends(b, "high").

.decl sized(a: symbol)
sized(a) :- alpha__size(a, s), s >= 5.
"""
UNMARKED = FOLDED.replace(MARK, "// no mark\n")  # the same lines, so the same origins


def explaining(d: Path, classes=(), value="fold", named=None) -> Path:
    """Put `explain: <value>` on classes of the fixture schema, and a name slot on `named`. The file is written
    again either way, so a pack with and one without marks differ in the marks alone."""
    f = d / "schema" / "minimal.yaml"
    s = yaml.safe_load(f.read_text())
    for cls in classes:
        s["classes"][cls]["annotations"] = {"explain": value}
    if named:
        s["prefixes"] = {"linkml": "https://w3id.org/linkml/", "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}
        s["classes"][named]["attributes"]["title"] = {"slot_uri": "rdfs:label"}
    f.write_text(yaml.safe_dump(s, sort_keys=False))
    return d


def test_a_fold_mark_goes_into_the_bundle_and_nowhere_else(fixture):
    plain = emit.compile_pack(pack.read(with_rules(explaining(fixture), core=UNMARKED)))
    marked = emit.compile_pack(pack.read(with_rules(explaining(fixture, ["Beta"]), core=FOLDED)))
    # The rule IR, the engine files and the witness queries are the same bytes: the mark is display only.
    assert set(marked) == set(plain) and "ir/rules.json" in marked
    assert [f for f in marked if marked[f] != plain[f]] == ["bundle/schema-bundle.json"]
    before, after = (json.loads(files["bundle/schema-bundle.json"]) for files in (plain, marked))
    ends = next(r for r in after["relations"] if r["id"] == "ends")
    assert (ends["explain"], ends["fold"]) == ("on_demand", True)  # how its witnesses are kept is apart from it
    assert [k["id"] for k in after["kinds"] if k.get("fold")] == ["beta"]
    assert not [x for x in (*before["relations"], *before["kinds"]) if "fold" in x]  # left out, never false
    for x in (*after["relations"], *after["kinds"]):
        x.pop("fold", None)
    assert after == before


def test_the_explanation_lint_and_the_compiler_fold_the_same(fixture, tmp_path):
    """What the lint's class B asks to fold is what the compiler lets a pack fold, and with those marks both
    read the same folded set: the lint from the sources, the compiler in its bundle."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "explain_lint", Path(__file__).resolve().parents[2] / "tools" / "explain-lint" / "explain_lint.py")
    lint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lint)

    def class_b(model) -> list[str]:
        """The lint's class B findings on the compiler's own output, as the lint reads a committed compile."""
        for name, text in emit.compile_pack(model).items():
            if name in ("bundle/schema-bundle.json", "ir/rules.json"):
                (fixture / "expected" / "compiled" / name).parent.mkdir(parents=True, exist_ok=True)
                (fixture / "expected" / "compiled" / name).write_text(text, encoding="utf-8")
        return sorted(f.what for f in lint.lint(fixture, tmp_path, set()).findings if f.cls == "B")

    model = pack.read(with_rules(explaining(fixture), core=UNMARKED))
    assert class_b(model) == ["helper relation ends is not folded (explain: fold)",
                              "kind beta is only reached through joins and is not folded (explain: fold)"]
    helpers, reaches = fold.helpers(model)
    assert helpers == {"ends"} and reaches == {"alpha"}
    model = pack.read(with_rules(explaining(fixture, ["Beta"]), core=FOLDED))
    assert class_b(model) == []
    bundle = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])
    assert lint.folded(fixture) == ({r["id"] for r in bundle["relations"] if r.get("fold")}
                                    | {k["class"] for k in bundle["kinds"] if k.get("fold")}) == {"ends", "Beta"}


FOLD_REFUSED = {
    # (rules, classes marked, the mark's value, the kind given a name, the error)
    "nothing-reads-it": (MARK + ".decl p(x: symbol)\np(x) :- alpha(x).", [], "fold", None,
                         r"rules/core\.dl:2: @explain fold is for a helper relation, and p is none"),
    "an-invariant": ("// @invariant\n" + MARK + ".decl p(x: symbol)\np(x) :- alpha__size(x, s), s > 9.\n"
                     ".decl q(x: symbol)\nq(x) :- p(x).", [], "fold", None, "and p is none"),
    "a-mode-below-the-mark": (MARK + "// @explain on_demand\n.decl p(x: symbol)\np(x) :- alpha(x).", [], "fold", None,
                              r"p: @explain fold goes on the line right above the \.decl"),
    "a-blank-line-below-the-mark": (MARK + "\n.decl p(x: symbol)\np(x) :- alpha(x).", [], "fold", None,
                                    r"right above the \.decl"),
    "a-table": (MARK + ".decl alpha(id: symbol)\n", [], "fold", None,
                "@explain fold is for derived relations, not the table alpha"),
    "a-kind-whose-id-reaches-a-head": (FOLDED, ["Alpha"], "fold", None,
                                       "class Alpha: explain: fold is for a helper kind, and alpha is none"),
    "a-kind-with-a-name": (FOLDED, ["Beta"], "fold", "Beta", "class Beta: explain: fold is for a helper kind"),
    "another-value": (FOLDED, ["Beta"], "sometimes", None, "class Beta: explain is fold, not 'sometimes'"),
}


@pytest.mark.parametrize("case", sorted(FOLD_REFUSED))
def test_a_fold_mark_on_anything_but_a_helper_is_refused(fixture, case):
    text, classes, value, named, message = FOLD_REFUSED[case]
    with pytest.raises(pack.CompileError, match=message):
        pack.read(with_rules(explaining(fixture, classes, value, named), core=text))


def test_a_relation_that_a_channel_names_is_no_helper(fixture):
    """Bound in a channel, a question or a check: someone sees it, so it is no mechanics."""
    model = pack.read(with_rules(explaining(fixture, ["Beta"]), core=FOLDED))
    model.channels = model.channels | {"flows": [{"edges": [{"relation": "ends"}]}]}
    errors = []
    fold.check(model, errors)
    assert len(errors) == 1 and "and ends is none" in errors[0]


# A folded kind read through a view: the relation the view makes to hold the kind's table is the kind
# under another name, and only the clause the compiler lowered for it is that.
THEORY_RULES = """
// joined: the two points a link joins; the link itself is the join between them.
.decl joined(a: symbol, b: symbol)
joined(a, b) :- link__a(l, a), link__b(l, b).
"""
VIEWED = {"theory": "tiny",
          "kinds": [{"name": "link", "union": [{"populated_from": "edge"}]},
                    {"name": "point", "union": [{"populated_from": "spot"}]}],
          "arrows": [{"name": n, "of": "link", "paths": [{"populated_from": "edge", "steps": [{"slot": s}]}]}
                     for n, s in (("a", "src"), ("b", "dst"))]}
NOT_A_HELPER = "class Link: explain: fold is for a helper kind, and link is none"


def viewed(tmp: Path, view: bool = True, **files: str) -> Path:
    """A theory `tiny` whose helper kind Link is folded, and a pack that imports it and, with `view`, reads it
    through a view; `files` are the pack's own rule files."""
    def write(path, value):
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")

    def schema(name, classes):
        return {"id": f"https://rezono.example/{name}", "name": name, "imports": ["linkml:types"],
                "default_range": "string", "annotations": {"layer": "facts"}, "classes": classes}

    theory, domain = (Path(shutil.copytree(FIXTURE, tmp / n)) for n in ("theory", "domain"))
    ident = {"id": {"identifier": True}}
    write(theory / "schema" / "minimal.yaml", schema("tiny", {
        "Link": {"annotations": {"explain": "fold"},
                 "attributes": {**ident, "a": {"range": "Point"}, "b": {"range": "Point"}}},
        "Point": {"attributes": ident}}))
    write(theory / "pack.yaml", {"name": "tiny", "version": "0", "default_language": "nl", "theory": True})
    write(theory / "channels.yaml", {"kinds": [{"kind": k, "shape": "rect"} for k in ("link", "point")],
                                     "arrows": [{"arrow": a, "dash": "none"} for a in ("link.a", "link.b")]})
    write(theory / "labels" / "nl.yaml", {})
    with_rules(theory, tiny=THEORY_RULES)
    write(domain / "schema" / "minimal.yaml", schema("domain", {
        "Edge": {"attributes": {**ident, "src": {"range": "Spot"}, "dst": {"range": "Spot"}}},
        "Spot": {"attributes": ident}}))
    write(domain / "pack.yaml", {"name": "domain", "version": "0", "default_language": "nl",
                                 "imports": [{"name": "tiny", "path": "../theory", "sha256": modules.pack_hash(theory)}]})
    write(domain / "channels.yaml", {"kinds": [{"kind": k, "shape": "rect"} for k in ("edge", "spot")],
                                     "arrows": [{"arrow": a, "dash": "none"} for a in ("edge.src", "edge.dst")]})
    write(domain / "labels" / "nl.yaml", {})
    if files:
        with_rules(domain, **files)
    if view:
        write(domain / "views.yaml", {"format": "rezono.views/1", "views": [VIEWED]})
    return domain


def test_a_folded_kind_read_through_a_view_compiles_and_keeps_its_mark(tmp_path):
    """No rule reads the relation that holds link's table, so it is no helper; it is link itself, and the
    clause that fills it from the table concludes nothing."""
    model = pack.read(viewed(tmp_path))
    through = [r for r in model.rules["rules"] if [a["relation"] for a in r["body"]] == ["link"]]
    assert [(r["head"]["relation"], r["head"]["terms"], r["body"][0]["terms"], r["origin"]["file"])
            for r in through] == [("tiny_link", ["?v0"], ["?v0"], view_rules.SOURCE)]
    assert "link" not in fold.helpers(model)[1]
    bundle = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])
    assert [k["id"] for k in bundle["kinds"] if k.get("fold")] == ["link"]
    # The same clause with the origin of a rule file is an author's rule: judged as one, and refused.
    through[0]["origin"] = {"file": "rules/view_tiny.dl", "line": "1"}
    errors = []
    fold.check(model, errors)
    assert len(errors) == 1 and errors[0].startswith(NOT_A_HELPER)


def test_the_pass_through_written_in_a_rule_file_is_refused(tmp_path):
    """The shape of the lowered clause, module and relation name included, written by hand: not exempt."""
    clause = ".decl tiny_link(id: symbol)\ntiny_link(v) :- link(v).\n"
    with pytest.raises(pack.CompileError, match=NOT_A_HELPER):
        pack.read(viewed(tmp_path, view=False, view_tiny=clause))


def test_a_rule_that_reads_the_kind_through_the_view_is_judged_as_reading_the_kind(tmp_path):
    """A rule of the pack that reads link is bound to the view's relation; the id still reaches its head."""
    with pytest.raises(pack.CompileError, match=NOT_A_HELPER):
        pack.read(viewed(tmp_path, own=".decl seen(id: symbol)\nseen(l) :- link(l).\n"))
