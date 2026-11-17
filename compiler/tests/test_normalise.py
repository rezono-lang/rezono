"""D08: the semantic normal form of the rule IR and its hash (normalise.py), apart from the source hashes.

Rules that differ only in variable names, the order of their literals, the orientation of a comparison or the
operand order of `+` and `*` hash equal; any change of what a rule says hashes differently. The normal form is
itself a rule that computes the same rows. The definition hash and the stable ids do not move.
"""

import itertools
import json
import random
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import rulegen as gen
from support import FIXTURE, REPO
from rede_compiler import __main__ as cli
from rede_compiler import batch as duck
from rede_compiler import emit, modules, normalise, pack
from rede_compiler import rules as ir

# Small rules over few relations and variables, so that ties and symmetries are common.
VARS = ["?a", "?b", "?c", "?d", "?e"]
CONSTS = ["1", "2", "x"]
ARITY = {"p": 1, "q": 2, "r": 2}


@st.composite
def small_rule(draw, most=5):
    term = st.sampled_from(VARS + CONSTS)
    var = st.sampled_from(VARS)
    body, aggregates, conditions, assignments = [], [], [], []
    for _ in range(draw(st.integers(1, most))):
        kind = draw(st.sampled_from(["atom", "atom", "atom", "aggregate", "condition", "assignment"]))
        relation = draw(st.sampled_from(sorted(ARITY)))
        if kind == "atom":
            terms = tuple(draw(term) for _ in range(ARITY[relation]))
            body.append(ir.Literal(ir.Atom(relation, terms), draw(st.sampled_from(["positive", "negative"])), 0))
        elif kind == "aggregate":
            terms = tuple(draw(st.sampled_from(VARS + CONSTS + ["_"])) for _ in range(ARITY[relation]))
            function = draw(st.sampled_from(["count", "sum"]))
            aggregates.append(ir.Aggregate(ir.Atom(relation, terms), function, None if function == "count" else "c1",
                                           draw(var), 0))
        elif kind == "condition":
            conditions.append(ir.Condition(draw(st.sampled_from(ir.COMPARISONS)), draw(term), draw(term)))
        else:
            assignments.append(ir.Assignment(draw(var), draw(st.sampled_from(ir.ARITHMETIC)), draw(term), draw(term)))
    head = ir.Atom("h", tuple(draw(st.lists(term, max_size=2))))
    return ir.Rule("h", "m", 0, head, tuple(body), tuple(aggregates), tuple(conditions), tuple(assignments))


def variant(rule: ir.Rule, rnd: random.Random) -> ir.Rule:
    """The same rule in other words: variables renamed, each list shuffled, comparisons turned round, the
    operands of + and * swapped, a literal written twice, another id, module and origin."""
    names = sorted(set(rule.variables) | {t for t in rule.head.terms if ir.is_var(t)})
    renamed = dict(zip(names, rnd.sample([f"?w{n}" for n in range(3 * len(names) + 3)], len(names))))

    def t(x):
        return renamed.get(x, x)

    def atom(a):
        return ir.Atom(a.relation, tuple(t(x) for x in a.terms))

    def shuffled(xs):
        xs = list(xs)
        rnd.shuffle(xs)
        return tuple(xs)

    body = [replace(b, atom=atom(b.atom)) for b in rule.body]
    if body and rnd.random() < 0.3:
        body.append(rnd.choice(body))
    aggregates = [replace(a, atom=atom(a.atom), var=t(a.var)) for a in rule.aggregates]
    turned = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le", "eq": "eq", "ne": "ne"}
    conditions = [ir.Condition(turned[c.op], t(c.right), t(c.left)) if rnd.random() < 0.5
                  else ir.Condition(c.op, t(c.left), t(c.right)) for c in rule.conditions]
    assignments = [ir.Assignment(t(s.var), s.op, t(s.right), t(s.left)) if s.op in normalise.COMMUTATIVE
                   and rnd.random() < 0.5 else ir.Assignment(t(s.var), s.op, t(s.left), t(s.right))
                   for s in rule.assignments]
    return ir.Rule("other", "elsewhere", 7, atom(rule.head), shuffled(body), shuffled(aggregates),
                   shuffled(conditions), shuffled(assignments), ("rules/elsewhere.dl", 99))


def brute_force(rule: ir.Rule):
    """The definition of `canonical`, without its pruning: the least key sequence over every order of the
    body and every reading of each literal."""
    names = {}
    head, fresh = normalise.named(rule.head.terms, names)
    names |= fresh
    lits = normalise.readings(rule)
    colour = normalise.colours(rule.head.terms, lits)
    least = None
    for order in itertools.permutations(range(len(lits))):
        for choice in itertools.product(*(lits[i] for i in order)):
            seen, keys = dict(names), []
            for i, (fixed, terms) in zip(order, choice):
                renamed, fresh = normalise.named(terms, seen)
                seen |= fresh
                keys.append((fixed[0], colour[i], fixed, renamed))
            if least is None or tuple(keys) < least:
                least = tuple(keys)
    return head, least or ()


@given(rule=small_rule(most=5))
def test_the_walk_finds_the_least_reading(rule):
    """The pruned walk of `canonical` gives what its definition gives: the least of all readings."""
    assert normalise.canonical(rule) == brute_force(rule)


@given(rule=small_rule(), seed=st.integers(0, 2**32))
def test_the_same_rule_in_other_words_hashes_equal(rule, seed):
    """Reordered conjuncts, renamed variables, turned comparisons and swapped operands: one hash."""
    other = variant(rule, random.Random(seed))
    assert normalise.rule_doc(other) == normalise.rule_doc(rule)
    assert normalise.rule_sha256(other) == normalise.rule_sha256(rule)


def changes(rule: ir.Rule):
    """Rules that say something else: each changes a count or a name that no rewrite of normalise.py changes
    (a relation, a constant, a polarity, an operator, how many variables there are), so none can share the
    normal form of the rule."""
    variables = sorted(set(rule.variables))
    for n, b in enumerate(rule.body):
        others = rule.body[:n] + rule.body[n + 1:]
        yield replace(rule, body=(*others, replace(b, atom=replace(b.atom, relation="s"))))
        flipped = "negative" if b.polarity == "positive" else "positive"
        yield replace(rule, body=(*others, replace(b, polarity=flipped)))
        for k, t in enumerate(b.atom.terms):
            if not ir.is_var(t):
                terms = b.atom.terms[:k] + ("fresh-constant",) + b.atom.terms[k + 1:]
                yield replace(rule, body=(*others, replace(b, atom=replace(b.atom, terms=terms))))
    for n, c in enumerate(rule.conditions):
        other = {"lt": "le", "le": "lt", "gt": "ge", "ge": "gt", "eq": "ne", "ne": "eq"}[c.op]
        yield replace(rule, conditions=(*rule.conditions[:n], replace(c, op=other), *rule.conditions[n + 1:]))
    for n, s in enumerate(rule.assignments):
        other = {"add": "sub", "sub": "add", "mul": "div", "div": "mul", "days": "add"}[s.op]
        yield replace(rule, assignments=(*rule.assignments[:n], replace(s, op=other), *rule.assignments[n + 1:]))
    for n, a in enumerate(rule.aggregates):
        other = {"count": "sum", "sum": "count", "min": "max", "max": "min"}[a.function]
        yield replace(rule, aggregates=(*rule.aggregates[:n], replace(a, function=other), *rule.aggregates[n + 1:]))
    yield replace(rule, head=replace(rule.head, relation="g"))
    yield replace(rule, head=replace(rule.head, terms=(*rule.head.terms, "x")))
    if len(variables) >= 2:  # two variables made one: fewer variables
        a, b = variables[:2]

        def merged(t):
            return a if t == b else t
        yield replace(rule, head=ir.Atom(rule.head.relation, tuple(map(merged, rule.head.terms))),
                      body=tuple(replace(x, atom=replace(x.atom, terms=tuple(map(merged, x.atom.terms))))
                                 for x in rule.body),
                      conditions=tuple(ir.Condition(c.op, merged(c.left), merged(c.right)) for c in rule.conditions),
                      assignments=tuple(ir.Assignment(merged(s.var), s.op, merged(s.left), merged(s.right))
                                        for s in rule.assignments),
                      aggregates=tuple(replace(x, var=merged(x.var), atom=replace(x.atom, terms=tuple(
                          map(merged, x.atom.terms)))) for x in rule.aggregates))


def counts(rule: ir.Rule):
    """What no rewrite of normalise.py changes: the multisets of relations, constants, polarities, operators and
    functions, and the number of variables, with a literal written twice counted once."""
    lits = normalise.readings(rule)
    shapes = sorted(min((fixed, tuple(t if not ir.is_var(t) else "?" for t in terms)) for fixed, terms in lit)
                    for lit in lits)
    variables = {t for lit in lits for _, terms in lit for t in terms if ir.is_var(t)} | {
        t for t in rule.head.terms if ir.is_var(t)}
    return shapes, rule.head.relation, tuple(t if not ir.is_var(t) else "?" for t in rule.head.terms), len(variables)


@given(rule=small_rule())
def test_a_rule_that_says_something_else_hashes_differently(rule):
    for other in changes(rule):
        if counts(other) != counts(rule):  # a change a duplicate absorbs, or a merge of a variable with itself
            assert normalise.rule_sha256(other) != normalise.rule_sha256(rule), other


def test_reordered_conjuncts_and_renamed_variables_hash_equal_by_example():
    def rule(head, body, conditions=(), assignments=()):
        return ir.Rule("r", "m", 1, ir.Atom("reach", head), tuple(ir.Literal(ir.Atom(*b), p, 0) for *b, p in body),
                       (), tuple(ir.Condition(*c) for c in conditions), tuple(ir.Assignment(*s) for s in assignments))

    one = rule(("?x", "?n"), [("edge", ("?x", "?y"), "positive"), ("node", ("?y",), "negative")],
               [("lt", "?k", "12"), ("ne", "?x", "?y")], [("?n", "add", "?k", "1"), ("?k", "mul", "?x", "2")])
    two = rule(("?a", "?m"), [("node", ("?b",), "negative"), ("edge", ("?a", "?b"), "positive")],
               [("ne", "?b", "?a"), ("gt", "12", "?j")], [("?j", "mul", "2", "?a"), ("?m", "add", "1", "?j")])
    assert normalise.rule_sha256(one) == normalise.rule_sha256(two)
    doc = normalise.rule_doc(two)
    assert doc["head"] == {"relation": "reach", "terms": ["?v0", "?v1"]}
    # each assignment after the one it reads, so the normal form is a valid rule again
    assert [s["var"] for s in doc["assignments"]] == ["?v3", "?v1"]
    assert normalise.rule_sha256(replace(one, head=ir.Atom("reach", ("?y", "?n")))) != normalise.rule_sha256(one)


@given(seed=st.integers(0, 10**6), n=st.integers(1, 30), pick=st.integers(0, 2**32))
def test_generated_rules_in_other_words_hash_equal_and_changed_rules_differ(seed, n, pick):
    prog = ir.load(gen.program(seed, n, shapes=gen.ALL_SHAPES))
    rnd = random.Random(pick)
    for r in prog.rules.values():
        h = normalise.rule_sha256(r)
        assert normalise.rule_sha256(variant(r, rnd)) == h
        assert all(normalise.rule_sha256(o) != h for o in changes(r) if counts(o) != counts(r))
    other = ir.load(ir.with_strata(shuffled_program(ir.to_doc(prog), rnd)))
    assert normalise.program_sha256(other) == normalise.program_sha256(prog)


def shuffled_program(doc: dict, rnd: random.Random) -> dict:
    """A program document with its rules renumbered and moved, the bodies of each list shuffled."""
    doc = json.loads(json.dumps(doc))
    for r in doc["rules"]:
        for key in ("body", "aggregates", "conditions"):
            rnd.shuffle(r.get(key, []))
        r["origin"] = {"file": "moved.dl", "line": str(rnd.randrange(1, 999))}
        r.pop("witness")
    ids = [r["id"] for r in doc["rules"]]
    fresh = dict(zip(ids, rnd.sample([f"rule_{n}" for n in range(len(ids))], len(ids))))
    for r in doc["rules"]:
        r["id"] = fresh[r["id"]]
    rnd.shuffle(doc["rules"])
    return doc


def normal_program(doc: dict) -> dict:
    """The program with each rule replaced by its normal form, under its own id, module and origin."""
    prog = ir.load(doc)
    out = json.loads(json.dumps(doc))
    for r in out["rules"]:
        normal = normalise.rule_doc(prog.rules[r["id"]])
        for key in ("head", "body", "aggregates", "conditions", "assignments"):
            r[key] = normal[key]
        r.pop("witness")
    return ir.with_strata(out)


@settings(max_examples=min(settings().max_examples, 50))  # an engine run per example: a quarter of `pr`
@given(seed=st.integers(0, 10**6), n=st.integers(1, 25), rows=st.integers(10, 200))
def test_the_normal_form_is_a_rule_that_computes_the_same_rows(seed, n, rows):
    """Normalising every rule of a program changes no row on the batch backend, and normalising twice is
    normalising once."""
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog, normal = ir.load(doc), ir.load(normal_program(doc))
    for r in normal.rules.values():
        assert normalise.rule_doc(r) == normalise.rule_doc(prog.rules[r.id])
    data = gen.facts(doc, seed, rows, domain=max(1, rows // 3))
    got = []
    for p in (prog, normal):
        con = duck.connect(p, data)
        duck.compute(con, p)
        got.append(duck.read(con, p))
    assert got[0] == got[1]


def packs_with_rules():
    for top in ("packs", "examples"):
        for meta in sorted((REPO / top).rglob("pack.yaml")):
            if "expected" not in meta.parts and (meta.parent / "rules").is_dir():
                yield meta.parent


@pytest.mark.parametrize("d", list(packs_with_rules()), ids=lambda d: d.relative_to(REPO).as_posix())
def test_no_pack_says_one_rule_twice(d):
    """Every rule of every pack in this repository has a semantic hash of its own, so the stronger refusal of
    emit.rule_bundle refuses none of them; normalising is the identity on what they compute (above) and moves
    no source hash, stable id or golden (the code that makes those does not call it)."""
    try:
        model = pack.read(d)
    except pack.CompileError:
        pytest.skip("a pack read only through an importer")
    prog = ir.load(model.rules)
    by_hash = {}
    for r in sorted(prog.rules.values(), key=lambda r: r.id):
        by_hash.setdefault(normalise.rule_sha256(r), []).append(r.id)
    assert [ids for ids in by_hash.values() if len(ids) > 1] == []


RULES = """.decl pair(a: symbol, b: symbol)
pair(a, b) :- beta__alpha(b, a), alpha__size(a, s), s >= 5.
"""


@pytest.fixture
def fixture(tmp_path) -> Path:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "rules").mkdir()
    (d / "rules" / "core.dl").write_text(RULES)
    return d


def semantic(d: Path, capsys) -> str:
    assert cli.main(["hash", "--rules", str(d)]) == 0
    return capsys.readouterr().out.strip()


def test_the_source_hashes_move_and_the_semantic_hash_does_not(fixture, capsys):
    """Renaming variables and reordering a body changes the bytes, so the definition hash and the rule's stable
    id, and not the semantic hash of the program."""
    def stable(d):
        return {r["id"]: r["stable_id"] for r in json.loads(emit.compile_pack(pack.read(d))["bundle/schema-bundle.json"])["rules"]}

    before = (modules.pack_hash(fixture), stable(fixture), semantic(fixture, capsys))
    (fixture / "rules" / "core.dl").write_text(""".decl pair(a: symbol, b: symbol)
pair(x, y) :- 5 <= n, alpha__size(x, n), beta__alpha(y, x).
""")
    after = (modules.pack_hash(fixture), stable(fixture), semantic(fixture, capsys))
    assert before[0] != after[0] and before[1] != after[1]
    assert before[2] == after[2]
    assert len(before[2]) == 64
    (fixture / "rules" / "core.dl").write_text(RULES.replace("s >= 5", "s > 5"))
    assert semantic(fixture, capsys) != before[2]


def test_one_rule_twice_in_other_words_is_refused(fixture):
    (fixture / "rules" / "core.dl").write_text(RULES + "pair(x, y) :- alpha__size(x, n), beta__alpha(y, x), 5 <= n.\n")
    with pytest.raises(pack.CompileError, match="rules pair_1 and pair_2 say the same, up to the names of their variables"):
        emit.compile_pack(pack.read(fixture))
