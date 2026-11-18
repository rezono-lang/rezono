"""`gap`: the schedule, the adornments, the effects, and the failing premises of an absent start.

The failing premises come from `gap.failures` (plain Python, the reference the gate is held to) and from the
prefix program (`gap.prefix_program`) run by Soufflé, the oracle: equal as sets, on generated programs and
data, for absent and present starts. Without Soufflé only the properties that need no oracle run."""

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import rulegen as gen
from rezono_compiler import batch, gap, rules_dl
from rezono_compiler import rules as ir

SOUFFLE = pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
ORACLE = settings(max_examples=min(settings().max_examples, 60), deadline=None)

TEXT = """
.decl r(x: symbol)
r(x) :- a(x, y), !b(y), c(y, z), z > 3, n = count : { d(x, _) }, n >= 1.
.decl s(x: symbol, y: symbol)
s(x, y) :- a(x, y).
s(x, y) :- r(x), a(x, y).
.decl t(x: symbol)
t(x) :- s(x, y), !b(y), a(z, x).
"""
INPUTS = {"a": [("x", "string"), ("y", "string")], "b": [("y", "string")],
          "c": [("y", "string"), ("z", "integer")], "d": [("x", "string"), ("w", "string")]}


def small():
    return ir.load(rules_dl.read_program(TEXT, "test", INPUTS, "test"))


def test_the_schedule_tests_each_item_as_soon_as_its_variables_are_bound():
    rule = small().rules["r"]
    # head bound: the aggregate's group key x is known at once; the negation waits for y, the condition for z
    assert gap.schedule(rule, [0]) == [("aggregate", 0), ("condition", 1), ("positive", 0), ("negative", 1),
                                       ("positive", 2), ("condition", 0)]
    # nothing bound: the aggregate waits for x too
    assert gap.schedule(rule, []) == [("positive", 0), ("negative", 1), ("aggregate", 0), ("condition", 1),
                                      ("positive", 2), ("condition", 0)]


def test_the_plan_reaches_every_pattern_a_walk_down_can_need_and_names_its_indexes():
    p = gap.plan(small())
    assert p == gap.plan(small())
    starts = {(s["relation"], tuple(s["bound"])) for s in p["starts"]}
    # every derived relation bound fully, and s with only x bound: t reaches it with y still free
    assert starts == {("r", (0,)), ("s", (0, 1)), ("s", (0,)), ("t", (0,))}
    lookups = {(i["relation"], tuple(i["bound"])) for s in p["starts"] for r in s["rules"] for i in r["items"] if "relation" in i}
    assert ("c", (0,)) in lookups and ("d", (0,)) in lookups and ("b", (0,)) in lookups
    assert p["indexes"] == [{"relation": r, "bound": list(b)} for r, b in sorted(lookups) if not gap.is_prefix(b)]
    # a(z, x) with x bound and z free: the second column first, so the test is one range read
    assert p["indexes"] == [{"relation": "a", "bound": [1]}]
    for s in p["starts"]:
        for r in s["rules"]:
            for i in r["items"]:
                if "bound" in i:
                    rule = small().rules[r["rule"]]
                    atom = gap._atom_of(rule, i["kind"], i["index"])
                    assert all(atom.terms[k] in i["have"] or not ir.is_var(atom.terms[k]) for k in i["bound"])


def test_effects_follow_the_signs_of_the_dependency_graph():
    e = gap.effects(small())
    assert e["b"]["insert"]["r"] == ["shrink"] and e["b"]["insert"]["s"] == ["shrink"]
    assert e["a"]["insert"]["s"] == ["grow"] and e["a"]["delete"]["s"] == ["shrink"]
    assert e["d"]["insert"]["r"] == ["grow", "shrink"] and e["d"]["insert"]["t"] == ["grow", "shrink"]
    assert e["b"]["insert"]["t"] == ["shrink"]
    assert gap.at_risk(e["b"]["insert"], "positive", "r") and not gap.at_risk(e["a"]["insert"], "positive", "s")
    assert gap.at_risk(e["a"]["insert"], "negative", "a") and gap.at_risk(e["d"]["delete"], "aggregate", "d")


OVERFLOW = """
.decl o(x: symbol, n: number)
o(x, n) :- e(x), p(x, s), t = s / -1, n = t / 2.
"""


def test_an_assignment_outside_bigint_fails_however_the_rest_goes():
    """-2^63 / -1 is 2^63, outside BIGINT, where every engine stops; t / 2 would fit again.
    The walk fails at that assignment and does not reach the end of the rule. The same holds for +, - and *."""
    prog = ir.load(rules_dl.read_program(OVERFLOW, "test", {"e": [("x", "string")],
                                                             "p": [("x", "string"), ("s", "integer")]}, "test"))
    low = str(-2**63)
    fails, complete = gap.failures(prog, {"e": [["k"]], "p": [["k", low]]}, "o", [0], ["k"])
    assert (fails, complete) == ({("o", 3, (("?s", -2**63), ("?x", "k")))}, set())
    fails, complete = gap.failures(prog, {"e": [["k"]], "p": [["k", "-8"]]}, "o", [0], ["k"])
    assert (fails, complete) == (set(), {"o"})
    assert gap._calc("mul", 2**62, 2) is None and gap._calc("sub", -2**63, 1) is None
    assert gap._calc("add", 2**63 - 2, 1) == 2**63 - 1
    assert gap._calc("sub", 2**63, 1) is None   # an operand outside BIGINT, though the result would fit


DAYS = [("2024-03-01", 19783), ("2000-02-29", 11016), ("1900-03-01", -25508), ("1969-12-31", -1)]


def test_a_day_count_is_followed_and_another_count_fails_at_it():
    prog = ir.load(gen.days_program())
    for text, count in DAYS:
        rows = {"e": [["k"]], "p": [["k", text]]}
        assert gap.failures(prog, rows, "f", [0, 1], ["k", str(count)]) == (set(), {"f"})
        fails, complete = gap.failures(prog, rows, "f", [0, 1], ["k", str(count + 1)])
        assert complete == set() and {(r, i) for r, i, _ in fails} == {("f", 3)}
    # a text that is no calendar day derives nothing: the walk fails at the assignment
    fails, complete = gap.failures(prog, {"e": [["k"]], "p": [["k", "2023-02-29"]]}, "f", [0], ["k"])
    assert complete == set() and {(r, i) for r, i, _ in fails} == {("f", 3)}


SUM = """
.decl c(x: symbol, n: number)
c(x, n) :- e(x), t = sum s : { p(x, s) }, n = t / 2.
"""


def test_a_sum_outside_bigint_fails_before_it_is_used():
    """(2^63 - 1) + (2^63 - 2) lies outside BIGINT; t / 2 would fit again."""
    prog = ir.load(rules_dl.read_program(SUM, "test", {"e": [("x", "string")],
                                                        "p": [("x", "string"), ("s", "integer")]}, "test"))
    big = {"e": [["k"]], "p": [["k", str(2**63 - 1)], ["k", str(2**63 - 2)]]}
    assert gap.failures(prog, big, "c", [0], ["k"]) == ({("c", 1, (("?x", "k"),))}, set())  # x is bound first
    small = {"e": [["k"]], "p": [["k", "3"], ["k", "4"]]}
    assert gap.failures(prog, small, "c", [0], ["k"]) == (set(), {"c"})


def test_failures_name_the_first_item_that_does_not_hold():
    prog = small()
    rows = {"a": [["k", "y1"]], "b": [], "c": [["y1", "2"]], "d": [["k", "w"]]}
    fails, complete = gap.failures(prog, rows, "r", [0], ["k"])
    # a, !b and c hold; z > 3 does not, with everything bound so far
    assert complete == set()
    assert {(r, i) for r, i, _ in fails} == {("r", 6)}
    rows["c"] = [["y1", "5"]]
    assert gap.failures(prog, rows, "r", [0], ["k"]) == (set(), {"r"})


def materialised(prog, data):
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    return {**{k: [list(map(str, r)) for r in v] for k, v in data.items()}, **{k: [list(r) for r in v] for k, v in batch.read(con, prog).items()}}


def starts(prog, rows, relation, rnd, n=4):
    """Starts over `relation`: some present rows and some absent keys made of values seen in the data."""
    rel = prog.relations[relation]
    present = [r[:len(rel.key)] for r in rows.get(relation, [])]
    seen = {"string": sorted({str(v) for rs in rows.values() for r in rs for v in r if not str(v).lstrip("-").isdigit()}) or ["e0"],
            "integer": ["0", "1", "7"]}
    out = rnd.sample(present, min(len(present), n // 2))
    out += [[rnd.choice(seen[c.type]) for c in rel.key] for _ in range(n - len(out))]
    return out


@settings(max_examples=40, deadline=None)
@given(seed=st.integers(0, 10**6), n=st.integers(1, 12))
def test_a_present_start_completes_a_rule_and_an_absent_one_does_not(seed, n):
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    rows = materialised(prog, gen.facts(doc, seed, 40, domain=12))
    rnd = random.Random(seed)
    for relation in prog.derived():
        have = {tuple(r[:len(prog.relations[relation].key)]) for r in rows.get(relation, [])}
        for s in starts(prog, rows, relation, rnd):
            fails, complete = gap.failures(prog, rows, relation, range(len(s)), s)
            assert bool(complete) == (tuple(s) in have), (relation, s)
            if tuple(s) not in have and prog.rules_for(relation):
                # every rule whose head matches the start fails somewhere
                assert fails or all(not _head_matches(r, s) for r in prog.rules_for(relation))


def _head_matches(rule, start):
    theta = {}
    for t, v in zip(rule.head.terms, start):
        if ir.is_var(t):
            if theta.setdefault(t, v) != v:
                return False
        elif t != v:
            return False
    return True


def run_text(text, facts, outputs):
    """Run a Soufflé program: {output: set of tuples of str}."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "facts").mkdir()
        (d / "out").mkdir()
        for name, rs in facts.items():
            (d / "facts" / f"{name}.facts").write_text("".join("\t".join(map(str, r)) + "\n" for r in rs))
        (d / "p.dl").write_text(text)
        subprocess.run(["souffle", "-j", "1", "-F", str(d / "facts"), "-D", str(d / "out"), str(d / "p.dl")],
                       check=True, capture_output=True, text=True)
        return {o: {tuple(line.split("\t")) for line in (d / "out" / f"{o}.csv").read_text().splitlines() if line}
                for o in outputs}


def oracle(prog, rows, relation, bound, start):
    """The failing premises and complete rules from the prefix program, run by Soufflé."""
    text = gap.prefix_program(prog, relation, bound)
    read = {a.relation for r in prog.rules_for(relation) for a in (*(b.atom for b in r.body), *(x.atom for x in r.aggregates))}
    facts = {name: rows.get(name, []) for name in read}
    facts["start"] = [start or ["0"]]
    plan = gap.steps(prog, relation, bound)
    outputs = [gap.fail_name(s["rule"], i) for s in plan for i in range(1, len(s["items"]) + 1)]
    outputs += [gap.prefix_name(s["rule"], len(s["items"])) for s in plan]
    got = run_text(text, facts, outputs)
    fails, complete = set(), set()
    for s in plan:
        for i, item in enumerate(s["items"], 1):
            for row in got[gap.fail_name(s["rule"], i)]:
                fails.add((s["rule"], i, tuple(zip(item["have"], row[1:]))))
        if got[gap.prefix_name(s["rule"], len(s["items"]))]:
            complete.add(s["rule"])
    return fails, complete


def as_text(result):
    fails, complete = result
    return {(r, i, tuple((v, str(x)) for v, x in b)) for r, i, b in fails}, complete


@SOUFFLE
def test_the_prefix_program_on_souffle_gives_the_reference_on_the_small_program():
    prog = small()
    rows = {"a": [["k", "y1"], ["k", "y2"]], "b": [["y2"]], "c": [["y1", "2"]], "d": [["k", "w"]],
            "r": [], "s": [["k", "y1"], ["k", "y2"]], "t": []}
    for relation, bound, start in [("r", [0], ["k"]), ("s", [0, 1], ["k", "y9"]), ("r", [0], ["none"]),
                                   ("s", [0], ["q"]), ("t", [0], ["k"]), ("t", [0], ["y1"])]:
        assert oracle(prog, rows, relation, bound, start) == as_text(gap.failures(prog, rows, relation, bound, start))


@SOUFFLE
def test_the_prefix_program_on_souffle_counts_the_days_as_the_reference():
    prog = ir.load(gen.days_program())
    for text, count in DAYS:
        rows = {"e": [["k"]], "p": [["k", text]], "f": [["k", str(count)]]}
        for start in (["k", str(count)], ["k", str(count + 1)]):
            assert oracle(prog, rows, "f", [0, 1], start) == as_text(gap.failures(prog, rows, "f", [0, 1], start))


@SOUFFLE
@ORACLE
@given(seed=st.integers(0, 10**6), n=st.integers(1, 10))
def test_the_prefix_program_on_souffle_equals_the_reference(seed, n):
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    rows = materialised(prog, gen.facts(doc, seed, 30, domain=10))
    rnd = random.Random(seed)
    for relation in prog.derived():
        for s in starts(prog, rows, relation, rnd, n=3):
            bound = list(range(len(s)))
            assert oracle(prog, rows, relation, bound, s) == as_text(gap.failures(prog, rows, relation, bound, s)), (relation, s)
        # a pattern with the first key column free, where the key has more than one
        if len(prog.relations[relation].key) > 1:
            s = starts(prog, rows, relation, rnd, n=1)[0][1:]
            bound = list(range(1, len(prog.relations[relation].key)))
            assert oracle(prog, rows, relation, bound, s) == as_text(gap.failures(prog, rows, relation, bound, s)), (relation, s)

