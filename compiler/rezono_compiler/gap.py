"""`gap`: what is missing for a row that does not exist (R10, docs/gui.md "gap: what is missing").

The start is a pattern over a derived relation: some key columns bound, the rest free. For each rule of the
relation, in rule id order, the head is bound to the start and the body is tested in one fixed order: the
positive literals in source order, and each condition, assignment, negation and aggregate as soon as its
variables are bound (`schedule`). The first item without a match is the failing premise, with the bindings
so far; a literal with free variables branches over its matches.

The compiler derives three things the gate needs and must not work out again:

- the schedule of every rule for every start pattern that a walk down can reach (magic sets), with the
  bound columns of every lookup (its adornment), so the publisher can write one index per relation and
  pattern and every test is one range read (`plan`);
- per base relation, what an insert or a delete can do to every relation that depends on it: grow, shrink,
  or both through an aggregate (`effects`), so the gate can tell a sufficient candidate from one to test;
- per relation and pattern, the prefix program in Datalog (`prefix_program`): `<rule>__p<i>` holds the
  bindings after the first i items, and `<rule>__fail<i>` those after i - 1 items that item i does not
  extend. That program is what Soufflé runs as the oracle (tests only); `failures` is the same in Python,
  the reference the gate's walker is held to.
"""

from __future__ import annotations

from .rules import Atom, const_type, days, is_var, untyped_conditions

FORMAT = "rezono.gap/1"
KINDS = ("positive", "negative", "condition", "assignment", "aggregate")
OPS = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "add": "+", "sub": "-", "mul": "*", "div": "/"}
TYPE = {"string": "symbol", "integer": "number"}


def _vars(terms) -> set[str]:
    return {t for t in terms if is_var(t)}


def _uses(rule, kind, index) -> set[str]:
    """The variables an item needs bound before it can be tested."""
    if kind == "condition":
        c = rule.conditions[index]
        return _vars((c.left, c.right))
    if kind == "assignment":
        s = rule.assignments[index]
        return _vars((s.left, s.right))
    if kind == "aggregate":
        return _vars(rule.aggregates[index].atom.terms)
    return _vars(rule.body[index].atom.terms) if kind == "negative" else set()


def _binds(rule, kind, index) -> set[str]:
    if kind == "positive":
        return _vars(rule.body[index].atom.terms)
    if kind == "assignment":
        return {rule.assignments[index].var}
    if kind == "aggregate":
        return {rule.aggregates[index].var}
    return set()


def head_vars(rule, bound) -> set[str]:
    return {t for i, t in enumerate(rule.head.terms) if i in bound and is_var(t)}


def schedule(rule, bound) -> list[tuple[str, int]]:
    """The fixed order of a rule's body for a head with these key positions bound: (kind, index) per item.

    Positive literals in source order; before the first and after each, every waiting condition,
    assignment, negation and aggregate whose variables are bound, in that order of kinds, each by index,
    until none is ready. A rule that passed the compiler's safety check always ends with nothing waiting."""
    have = head_vars(rule, set(bound))
    waiting = ([("condition", i) for i in range(len(rule.conditions))]
               + [("assignment", i) for i in range(len(rule.assignments))]
               + [("negative", i) for i, b in enumerate(rule.body) if b.polarity == "negative"]
               + [("aggregate", i) for i in range(len(rule.aggregates))])
    out = []

    def flush():
        ready = True
        while ready:
            ready = False
            for item in waiting:
                if _uses(rule, *item) <= have:
                    out.append(item)
                    have.update(_binds(rule, *item))
                    waiting.remove(item)
                    ready = True
                    break

    flush()
    for i, b in enumerate(rule.body):
        if b.polarity == "positive":
            out.append(("positive", i))
            have.update(_binds(rule, "positive", i))
            flush()
    if waiting:
        raise ValueError(f"rule {rule.id}: {waiting} never bound (the safety check should have refused it)")
    return out


def _atom_of(rule, kind, index) -> Atom | None:
    if kind in ("positive", "negative"):
        return rule.body[index].atom
    return rule.aggregates[index].atom if kind == "aggregate" else None


def adornment(atom, have) -> list[int]:
    """The key positions of an atom that are known at its test: a constant, or a variable already bound.
    `_` (local to an aggregate) is not."""
    return [i for i, t in enumerate(atom.terms) if t != "_" and (not is_var(t) or t in have)]


def steps(prog, relation, bound) -> list[dict]:
    """Per rule of `relation` (id order): its schedule for the start pattern, each item with the variables
    known before it (`have`), and for a lookup its relation and bound positions (`bound`)."""
    out = []
    for rule in sorted(prog.rules_for(relation), key=lambda r: r.id):
        have = head_vars(rule, set(bound))
        items = []
        for kind, index in schedule(rule, bound):
            item = {"kind": kind, "index": index, "have": sorted(have)}
            atom = _atom_of(rule, kind, index)
            if atom is not None:
                item["relation"] = atom.relation
                item["bound"] = adornment(atom, have)
            items.append(item)
            have = have | _binds(rule, kind, index)
        out.append({"rule": rule.id, "items": items})
    return out


def is_prefix(bound) -> bool:
    return list(bound) == list(range(len(bound)))


def plan(prog) -> dict:
    """The gap plan of a program (rezono.gap/1): every start pattern a walk can reach, from a whole key of each
    derived relation down through failing positive literals on derived relations; per relation the bound
    patterns that are not a prefix of its key (each needs an index with those columns first); and the
    effects. Sorted throughout, so the same program gives the same bytes."""
    todo = [(r, tuple(range(len(prog.relations[r].key)))) for r in sorted(prog.derived())]
    starts, seen, patterns = [], set(todo), set()
    while todo:
        relation, bound = todo.pop(0)
        rules = steps(prog, relation, bound)
        starts.append({"relation": relation, "bound": list(bound), "rules": rules})
        for r in rules:
            for item in r["items"]:
                if "relation" not in item:
                    continue
                patterns.add((item["relation"], tuple(item["bound"])))
                at = (item["relation"], tuple(item["bound"]))
                if item["kind"] == "positive" and prog.relations[item["relation"]].role == "derived" and at not in seen:
                    seen.add(at)
                    todo.append(at)
    starts.sort(key=lambda s: (s["relation"], s["bound"]))
    indexes = [{"relation": r, "bound": list(b)} for r, b in sorted(patterns) if not is_prefix(b)]
    return {"format": FORMAT, "starts": starts, "indexes": indexes, "effects": effects(prog)}


def effects(prog) -> dict:
    """Per base relation that a rule reads, what an insert and a delete can do to each relation that depends
    on it: `grow`, `shrink`, or both. A positive literal passes the effect on, a negation turns it round, an
    aggregate can do both. The base relation itself is in the map with the change made to it."""
    users = {}
    for rule in prog.rules.values():
        h = rule.head.relation
        for b in rule.body:
            users.setdefault(b.atom.relation, set()).add((h, "+" if b.polarity == "positive" else "-"))
        for a in rule.aggregates:
            users.setdefault(a.atom.relation, set()).add((h, "±"))
    flip = {"grow": "shrink", "shrink": "grow"}
    out = {}
    for base in sorted(r for r in users if prog.relations[r].role == "base"):
        out[base] = {}
        for change, first in (("insert", "grow"), ("delete", "shrink")):
            eff = {base: {first}}
            todo = [(base, first)]
            while todo:
                rel, e = todo.pop()
                for h, sign in users.get(rel, ()):
                    nxt = {e} if sign == "+" else {flip[e]} if sign == "-" else {"grow", "shrink"}
                    for n in nxt - eff.setdefault(h, set()):
                        eff[h].add(n)
                        todo.append((h, n))
            out[base][change] = {r: sorted(es) for r, es in sorted(eff.items())}
    return out


def at_risk(effect: dict, kind: str, relation: str | None) -> bool:
    """True if a premise that held can stop holding under this effect ({relation: [grow|shrink]})."""
    if relation is None:
        return False
    e = set(effect.get(relation, ()))
    return {"positive": "shrink" in e, "negative": "grow" in e, "aggregate": bool(e)}.get(kind, False)


# --- the prefix program (Datalog text; Soufflé runs it as the oracle, in the tests) ---

def _types(prog, rule) -> dict[str, str]:
    t = {}
    for atom in (rule.head, *(b.atom for b in rule.body), *(a.atom for a in rule.aggregates)):
        for term, col in zip(atom.terms, prog.relations[atom.relation].key):
            if is_var(term):
                t.setdefault(term, col.type)
    for a in rule.aggregates:
        t[a.var] = "integer"
    for s in rule.assignments:
        t[s.var] = "integer"
    return t


def _term(t, typ):
    if is_var(t):
        return "V_" + t[1:]
    return t if typ == "integer" else '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _atom_text(prog, atom, over=None):
    rel = prog.relations[atom.relation]
    terms = ["W_" if over == c.name and t == "_" else "_" if t == "_" else _term(t, c.type) for t, c in zip(atom.terms, rel.key)]
    terms += ["W_" if over == c.name else "_" for c in rel.values]
    return f"{atom.relation}({', '.join(terms)})"


def days_text(text):
    """A Soufflé expression for the day number of an ISO date text: the year starts in March, so the leap day
    is its last day. From the digits of the text; no date library on this side."""
    y, m, d = (f"to_number(substr({text}, {at}, {n}))" for at, n in ((0, 4), (5, 2), (8, 2)))
    shifted = f"({y} - (14 - {m}) / 12)"          # the year, one less in January and February
    month = f"(({m} + 9) % 12)"                    # March is 0
    return f"(365 * {shifted} + {shifted} / 4 - {shifted} / 100 + {shifted} / 400 + (153 * {month} + 2) / 5 + {d})"


def _item_text(prog, rule, kind, index, types):
    if kind in ("positive", "negative"):
        return ("!" if kind == "negative" else "") + _atom_text(prog, rule.body[index].atom)
    if kind == "aggregate":
        a = rule.aggregates[index]
        fn = "count" if a.function == "count" else f"{a.function} W_"
        return f"{_term(a.var, 'integer')} = {fn} : {{ {_atom_text(prog, a.atom, a.over)} }}"
    if kind == "assignment":
        s = rule.assignments[index]
        if s.op == "days":   # a view's reading of a date
            return f"{_term(s.var, 'integer')} = {days_text(_term(s.left, 'string'))} - {days_text(_term(s.right, 'string'))}"
        return f"{_term(s.var, 'integer')} = {_term(s.left, 'integer')} {OPS[s.op]} {_term(s.right, 'integer')}"
    c = untyped_conditions(rule, "gap")[index]
    t = types.get(c.left) or types.get(c.right) or const_type(c.left)
    return f"{_term(c.left, t)} {OPS[c.op]} {_term(c.right, t)}"


def prefix_name(rule_id, i):
    return f"{rule_id}__p{i}"


def fail_name(rule_id, i):
    return f"{rule_id}__fail{i}"


def prefix_program(prog, relation, bound) -> str:
    """The Soufflé text of the prefix relations of `relation` for a start with the key positions `bound`.

    Input `start(<the bound columns>)` and every relation the rules read. Output per rule, with a first
    column `g` (always 0, so no relation is nullary) and then the variables known so far, sorted by name:
    `<rule>__p<i>`, the bindings after the first i items of the schedule (p0: the head bound to the
    start), and `<rule>__fail<i>` (i from 1), the bindings of p(i-1) that item i does not extend."""
    rel = prog.relations[relation]
    cols = [rel.key[i] for i in bound]
    lines = [f".decl start({', '.join(f'{c.name}: {TYPE[c.type]}' for c in cols) or 'g: number'})", ".input start"]
    read = sorted({a.relation for r in prog.rules_for(relation) for a in (*(b.atom for b in r.body), *(x.atom for x in r.aggregates))})
    for name in read:
        r = prog.relations[name]
        lines += [f".decl {name}({', '.join(f'{c.name}: {TYPE[c.type]}' for c in r.key + r.values)})", f".input {name}"]
    for s in steps(prog, relation, bound):
        rule = prog.rules[s["rule"]]
        types = _types(prog, rule)
        decl = lambda name, vs: f".decl {name}({', '.join(['g: number'] + [f'{v[1:]}: {TYPE[types[v]]}' for v in vs])})"  # noqa: E731
        use = lambda name, vs: f"{name}({', '.join(['0'] + [_term(v, types[v]) for v in vs])})"  # noqa: E731
        have = sorted(head_vars(rule, set(bound)))
        start = [_term(rule.head.terms[i], c.type) for i, c in zip(bound, cols)] or ["0"]
        p0 = prefix_name(rule.id, 0)
        lines += [decl(p0, have), f"{use(p0, have)} :- start({', '.join(start)}).", f".output {p0}"]
        for i, item in enumerate(s["items"], 1):
            nxt = sorted(set(item["have"]) | _binds(rule, item["kind"], item["index"]))
            p, q, ok, fail = prefix_name(rule.id, i - 1), prefix_name(rule.id, i), f"{rule.id}__ok{i}", fail_name(rule.id, i)
            text = _item_text(prog, rule, item["kind"], item["index"], types)
            lines += [decl(q, nxt), f"{use(q, nxt)} :- {use(p, item['have'])}, {text}.", f".output {q}",
                      decl(ok, item["have"]), f"{use(ok, item['have'])} :- {use(q, nxt)}.",
                      decl(fail, item["have"]), f"{use(fail, item['have'])} :- {use(p, item['have'])}, !{use(ok, item['have'])}.",
                      f".output {fail}"]
    return "\n".join(lines) + "\n"


# --- the reference: the same answer in plain Python ---

def _value(v, typ):
    return int(v) if typ == "integer" else str(v)


def _typed(prog, rows: dict) -> dict:
    """Rows as tuples of typed values (key columns, then value columns), per relation, as sets."""
    out = {}
    for name, rs in rows.items():
        rel = prog.relations.get(name)
        if rel is None:
            continue
        cols = [c.type for c in rel.key + rel.values]
        out[name] = {tuple(_value(v, t) for v, t in zip(r, cols)) for r in rs}
    return out


def _const(t, typ):
    return _value(t, typ)


def _match(prog, atom, row, theta, types):
    """theta extended so that atom matches the row's key, or None."""
    out = dict(theta)
    for t, v, col in zip(atom.terms, row, prog.relations[atom.relation].key):
        if t == "_":
            continue
        if is_var(t):
            if t in out:
                if out[t] != v:
                    return None
            else:
                out[t] = v
        elif _const(t, col.type) != v:
            return None
    return out


BIGINT = (-2**63, 2**63 - 1)


def _fits(v):
    return BIGINT[0] <= v <= BIGINT[1]


def _calc(op, a, b):
    """`a op b`, or None when an operand or the result lies outside BIGINT: every engine stops there, so the
    rule derives nothing from it."""
    if not (_fits(a) and _fits(b)):
        return None
    if op == "div":   # truncation toward zero, as Feldera and Soufflé; the divisor is a non-zero constant
        q = abs(a) // abs(b)
        v = q if (a < 0) == (b < 0) else -q
    else:
        v = {"add": a + b, "sub": a - b, "mul": a * b}[op]
    return v if _fits(v) else None


def _compare(op, a, b):
    return {"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]


def _extend(prog, rule, kind, index, theta, rows, types):
    def val(t, typ=None):
        return theta[t] if is_var(t) else _const(t, typ or const_type(t))

    if kind == "positive":
        atom = rule.body[index].atom
        out = (_match(prog, atom, r, theta, types) for r in rows.get(atom.relation, ()))
        return [m for m in out if m is not None]
    if kind == "negative":
        atom = rule.body[index].atom
        return [] if any(_match(prog, atom, r, theta, types) is not None for r in rows.get(atom.relation, ())) else [theta]
    if kind == "condition":
        c = untyped_conditions(rule, "gap")[index]
        t = types.get(c.left) or types.get(c.right) or const_type(c.left)
        return [theta] if _compare(c.op, val(c.left, t), val(c.right, t)) else []
    if kind == "assignment":
        s = rule.assignments[index]
        if s.op == "days":   # a view's reading of a date; a text that is no day derives nothing
            v = days(val(s.left, "string"), s.right)
        else:
            v = _calc(s.op, val(s.left, "integer"), val(s.right, "integer"))
        if v is None:
            return []
    else:
        a = rule.aggregates[index]
        rel = prog.relations[a.atom.relation]
        names = [c.name for c in rel.key + rel.values]
        group = [r for r in rows.get(a.atom.relation, ()) if _match(prog, a.atom, r, theta, types) is not None]
        if a.function == "count":
            v = len(group)
        else:
            over = [r[names.index(a.over)] for r in group]
            if a.function == "sum":
                v = sum(over)
                if not _fits(v):   # checked before anything uses it, as the engines stop there
                    return []
            elif not over:
                return []
            else:
                v = min(over) if a.function == "min" else max(over)
        s = a
    if s.var in theta:
        return [theta] if theta[s.var] == v else []
    return [{**theta, s.var: v}]


def failures(prog, rows: dict, relation: str, bound, start) -> tuple[set, set]:
    """The failing premises of an absent start, and the rules that reach their end, in plain Python.

    `rows`: the role's snapshot, {relation: rows of key then value columns}; `start`: the values of the
    bound key positions. Returns ({(rule, i, bindings)}, {rule}) with `i` the item's place in the schedule
    from 1 and `bindings` the sorted (variable, value) pairs known before it: what `<rule>__fail<i>` and the
    last `<rule>__p<n>` hold. No limit cuts anything here."""
    data = _typed(prog, rows)
    key = prog.relations[relation].key
    fails, complete = set(), set()
    for s in steps(prog, relation, bound):
        rule = prog.rules[s["rule"]]
        types = _types(prog, rule)
        theta = {}
        ok = True
        for i, v in zip(bound, start):
            t = rule.head.terms[i]
            v = _value(v, key[i].type)
            if is_var(t):
                if theta.setdefault(t, v) != v:
                    ok = False
            elif _const(t, key[i].type) != v:
                ok = False
        if not ok:
            continue
        states = {tuple(sorted(theta.items()))}
        for n, item in enumerate(s["items"], 1):
            nxt = set()
            for st in states:
                ext = _extend(prog, rule, item["kind"], item["index"], dict(st), data, types)
                if not ext:
                    fails.add((rule.id, n, st))
                nxt |= {tuple(sorted(e.items())) for e in ext}
            states = nxt
        if states:
            complete.add(rule.id)
    return fails, complete
