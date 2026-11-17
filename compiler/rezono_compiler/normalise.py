"""The semantic normal form of the rule IR, and its hash (D08; #351 P10.3, #394 A5).

Two rules that say the same thing in other words get one normal form, so one semantic hash. This hash answers
another question than the hashes of the sources: the definition hash (`modules.pack_hash`) pins the bytes of a
pack's files, and a rule's stable id (`emit.rule_id`) is the rule as the bundle gives it, its variable names
and its source order included. Neither changes here; the semantic hash stands beside them.

What the normal form leaves out, each a rewrite that keeps every conclusion of the rule:
- what is not meaning: the rule's id, module and origin, its strata and its witness (both derived from the
  rest), and the order its body was written in;
- variable names (alpha-equivalence): every variable of a rule is local to it, so the normal form names them
  `?v0`, `?v1`, ... in the order of a canonical reading;
- the order of the body: a body is a conjunction, and all of its literals hold on one binding;
- the orientation of a comparison: `eq` and `ne` are symmetric, `gt(a, b)` is `lt(b, a)`, `ge(a, b)` is `le(b, a)`;
- the operand order of `add` and `mul`: commutative on the engines' integers, overflow included (`a + b` is out
  of range exactly when `b + a` is);
- a literal written twice: a body is a set.

What it keeps: relation names, the order of a head's terms and of an atom's, constants as written (an integer
is canonical in the IR already; text is compared as bytes, so no Unicode normalisation), polarity, an
aggregate's function and the column it folds, and the operand order of `sub`, `div` and `days`.

The normal form is exact on what it covers: it is the least reading of the rule (`canonical`), so two rules that
differ only by those rewrites get the same form, and a form determines the rule up to them. It does not decide
equivalence in general (a variable that `eq` equates with another, a literal that another implies): equal hashes
mean equal meaning, not the converse. The form is versioned (`VERSION`); a change to it is a new version.
"""

from __future__ import annotations

from rezono_canon import canonical_sha256

from . import rules as ir

VERSION = "rezono.normal-rule/1"
PROGRAM = "rezono.normal-program/1"
CONVERSE = {"gt": "lt", "ge": "le"}
SYMMETRIC = ("eq", "ne")
COMMUTATIVE = ("add", "mul")
# The rank of each kind of literal, first in its key: atoms come first, so they name most variables.
POSITIVE, NEGATIVE, AGGREGATE, ASSIGNMENT, CONDITION = "0", "1", "2", "3", "4"


def readings(rule: ir.Rule) -> list[list[tuple[tuple[str, ...], tuple[str, ...]]]]:
    """Each literal of the body as its readings: a fixed part (rank and what is not a term) and its terms in
    order. A comparison or a commutative assignment has two readings, any other literal one. Literals written
    twice are read once."""
    out = []
    for b in rule.body:
        out.append([((POSITIVE if b.polarity == "positive" else NEGATIVE, b.atom.relation), b.atom.terms)])
    for a in rule.aggregates:
        out.append([((AGGREGATE, a.atom.relation, a.function, a.over or ""), (*a.atom.terms, a.var))])
    for s in rule.assignments:
        ways = [(s.var, s.left, s.right)] + ([(s.var, s.right, s.left)] if s.op in COMMUTATIVE else [])
        out.append([((ASSIGNMENT, s.op), t) for t in ways])
    for c in rule.conditions:
        if c.op in CONVERSE:
            out.append([((CONDITION, CONVERSE[c.op]), (c.right, c.left))])
        else:
            ways = [(c.left, c.right)] + ([(c.right, c.left)] if c.op in SYMMETRIC else [])
            out.append([((CONDITION, c.op), t) for t in ways])
    seen, unique = set(), []
    for lit in out:
        if not seen & set(lit):
            unique.append(lit)
        seen |= set(lit)
    return unique


def named(terms: tuple[str, ...], names: dict[str, int]) -> tuple[tuple[str, ...], dict[str, int]]:
    """Terms with every variable renamed `?v<n>`: a named one by its number, a fresh one by the next number, in
    the order the terms give. Returns the terms and the fresh names."""
    fresh: dict[str, int] = {}
    out = []
    for t in terms:
        if ir.is_var(t):
            n = names.get(t)
            if n is None:
                n = fresh.setdefault(t, len(names) + len(fresh))
            out.append(f"?v{n}")
        else:
            out.append(t)
    return tuple(out), fresh


def ranked(values: list) -> list[int]:
    """Each value as its place among the distinct values, sorted: a name for it that no spelling decides."""
    order = {v: n for n, v in enumerate(sorted(set(values)))}
    return [order[v] for v in values]


def colours(head: tuple[str, ...], lits: list) -> list[int]:
    """A colour per literal that no variable name and no body order decides (colour refinement): a variable
    starts with its places in the head, a literal with its readings in its variables' colours, and each round
    a variable takes in the colours of its literals and its places in them, until the classes stop splitting.
    Two literals of one colour can still differ; the colour only orders the walk of `canonical`, so that it
    rarely meets a tie."""
    variables = sorted({t for lit in lits for _, terms in lit for t in terms if ir.is_var(t)} | {
        t for t in head if ir.is_var(t)})
    var = dict(zip(variables, ranked([tuple(n for n, t in enumerate(head) if t == v) for v in variables])))
    classes = -1
    while True:
        lit = ranked([tuple(sorted((fixed, tuple(("v", str(var[t])) if ir.is_var(t) else ("c", t) for t in terms))
                                   for fixed, terms in each)) for each in lits])
        seen = {v: [] for v in variables}
        for colour, each in zip(lit, lits):
            for v in {t for _, terms in each for t in terms if ir.is_var(t)}:
                seen[v].append((colour, tuple(sorted(tuple(n for n, t in enumerate(terms) if t == v)
                                                     for _, terms in each))))
        refined = dict(zip(variables, ranked([(var[v], tuple(sorted(seen[v]))) for v in variables])))
        if len(set(refined.values())) == classes:
            return lit
        classes, var = len(set(refined.values())), refined


def canonical(rule: ir.Rule) -> tuple[tuple[str, ...], tuple]:
    """The least reading of a rule: its head, then its body as the least sequence of literal keys over every
    order of the body and every reading of each literal, the variables named in the order they are met (head
    first). A key is the literal's colour (`colours`), its fixed part and its renamed terms, so the result
    depends on the rule only up to the rewrites of this module, and determines it up to them.

    Found by a greedy walk that branches only on ties, which is exact because sequences compare by their first
    key first. Two pruning rules keep ties cheap without changing the result: among tied literals whose fresh
    variables occur in no other remaining literal, one stands for all (swapping them is a symmetry), and a state
    reached twice (the same literals left, the same names on their variables) is solved once."""
    names: dict[str, int] = {}
    head, fresh = named(rule.head.terms, names)
    names |= fresh
    lits = readings(rule)
    colour = colours(rule.head.terms, lits)
    variables = [{t for _, terms in lit for t in terms if ir.is_var(t)} for lit in lits]
    memo: dict[tuple, tuple] = {}

    def best(left: frozenset[int], names: dict[str, int]) -> tuple:
        if not left:
            return ()
        state = (left, tuple(sorted((v, n) for i in left for v in variables[i] if (n := names.get(v)) is not None)),
                 len(names))
        if state in memo:
            return memo[state]
        tied: list[tuple[int, dict[str, int]]] = []
        least = None
        for i in sorted(left):
            for fixed, terms in lits[i]:
                renamed, fresh = named(terms, names)
                key = (fixed[0], colour[i], fixed, renamed)
                if least is None or key < least:
                    least, tied = key, [(i, fresh)]
                elif key == least:
                    tied.append((i, fresh))
        others = {i: set().union(*(variables[j] for j in left if j != i)) for i, _ in tied}
        branches, stood_for = [], False
        for i, fresh in tied:
            private = not (set(fresh) & others[i])
            if private and stood_for:
                continue
            stood_for |= private
            branches.append((i, fresh))
        found = min((least, *best(left - {i}, names | fresh)) for i, fresh in branches)
        memo[state] = found
        return found

    return head, best(frozenset(range(len(lits))), names)


def rule_doc(rule: ir.Rule) -> dict:
    """The normal form of a rule, in the shape of the rule IR (contracts/rules.yaml) without what is not meaning:
    a head, the atoms, aggregates, conditions and assignments, each list in canonical order. Assignments keep
    an order in which each reads only results of earlier ones, so the form is itself a valid rule."""
    head, keys = canonical(rule)
    doc: dict = {"normal": VERSION, "head": {"relation": rule.head.relation, "terms": list(head)},
                 "body": [], "aggregates": [], "conditions": [], "assignments": []}
    assignments = []
    for _, _, fixed, terms in keys:
        rank = fixed[0]
        if rank in (POSITIVE, NEGATIVE):
            doc["body"].append({"relation": fixed[1], "terms": list(terms),
                                "polarity": "positive" if rank == POSITIVE else "negative"})
        elif rank == AGGREGATE:
            doc["aggregates"].append({"relation": fixed[1], "terms": list(terms[:-1]), "function": fixed[2],
                                      **({"over": fixed[3]} if fixed[3] else {}), "as": terms[-1]})
        elif rank == ASSIGNMENT:
            assignments.append({"var": terms[0], "op": fixed[1], "left": terms[1], "right": terms[2]})
        else:
            doc["conditions"].append({"op": fixed[1], "left": terms[0], "right": terms[1]})
    results = {s["var"] for s in assignments}
    placed: set[str] = set()
    while assignments:  # canonical order, each after the assignments it reads (acyclic in a valid rule)
        s = next((s for s in assignments if not ({s["left"], s["right"]} & results) - placed), assignments[0])
        assignments.remove(s)
        doc["assignments"].append(s)
        placed.add(s["var"])
    return doc


def rule_sha256(rule: ir.Rule) -> str:
    """The semantic hash of a rule: the canonical hash of its normal form."""
    return canonical_sha256(rule_doc(rule))


def relation_doc(r: ir.Relation) -> dict:
    """What a relation declares that rules depend on; its module and explain mode are not meaning."""
    def cols(cs):
        return [{"name": c.name, "type": c.type} for c in cs]

    return {"name": r.name, "role": r.role, "key": cols(r.key), "values": cols(r.values), "world": r.world,
            "invariant": r.invariant, "absence": r.absence, "extend": r.extend,
            **({"outcome": r.outcome} if r.outcome else {}), **({"closes": r.closes} if r.closes else {})}


def program_doc(prog: ir.Program | None) -> dict:
    """The normal form of a rule program: its relations by name and the semantic hashes of its rules, as a set.
    A rule's id, its file and its place in that file are not in it, so moving or renumbering rules keeps it."""
    if prog is None:
        return {"normal": PROGRAM, "relations": [], "rules": [], "seals": []}
    return {"normal": PROGRAM, "relations": [relation_doc(r) for _, r in sorted(prog.relations.items())],
            "rules": sorted({rule_sha256(r) for r in prog.rules.values()}),
            "seals": sorted(prog.seals, key=canonical_sha256)}


def program_sha256(prog: ir.Program | None) -> str:
    """The semantic hash of a rule program: equal for two programs that differ only by the rewrites of this
    module, rule by rule, and by where their rules are written."""
    return canonical_sha256(program_doc(prog))
