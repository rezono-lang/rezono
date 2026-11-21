"""Check that complete snapshots contain every row required by the rules (docs/formal.md §3).

The other checks of an epoch prove support: every row of a derived relation has a valid witness, and the witness
graph is acyclic. So a snapshot holds no row the model lacks. It is the model only when it is also closed: every
rule instance that holds on the snapshots has its head row. Where nothing reads the absence of a row, a missing
row hides a conclusion and makes no other one false. Where something does, a missing row makes a wrong conclusion
"valid": `allowed(x) :- request(x), !blocked(x)` passes for every `blocked` row the engine failed to derive.

So the pass covers every derived relation whose absence of a row is read (`covered`), and every derived relation
their rules read in turn. For each rule of a covered relation it enumerates the instances that hold on the
snapshots and requires the head row (`underived_row`). With support, a covered snapshot is then exactly the
least fixpoint of its rules over the relations below it.

An instance holds exactly when the check of one witness (check._check_witness) would accept it, with the same
arithmetic (evaluate.py): each positive premise is a row, each negative premise is not, each aggregate has a
result a binding can carry, each assignment computes, each condition holds.

Set at a time: a rule is one pipeline of sort-merge joins. Each relation is sorted by key once, and each atom reads
it in one sequential pass; nothing looks a row up by key. A later version can therefore run the same pipeline over
only the key-range pieces that changed.
"""

from dataclasses import replace
from itertools import groupby
from operator import itemgetter

from .canon import INTEGER, CalcColumnType, calc_value, encode_key
from .evaluate import _arith, _fits, _fold, _holds, cells
from .rules import Calculation


def covered(rules, read=()) -> set:
    """The derived relations the pass covers: those a rule negates or aggregates over, those the rule IR marks as
    an invariant, an outcome or a functional derivation (together with every functional domain and candidate/guard
    input), those in `read` (what the calculation reads, where a missing row is false or unknown), and every
    derived relation a rule of a covered relation reads."""
    functionals = getattr(rules, "functionals", {})
    todo = set(read) | set(getattr(rules, "invariants", ())) | set(getattr(rules, "outcomes", ())) | set(functionals)
    for func in functionals.values():
        todo.add(func.domain)
    for rule in rules.values():
        todo |= {b.atom.relation for b in rule.body if b.polarity != "positive"}
        todo |= {a.atom.relation for a in rule.aggregates}
    return dependencies(rules, todo)


def dependencies(rules, relations) -> set:
    """The derived relations that determine the contents of the given relations."""
    by_head = {}
    for rule in rules.values():
        by_head.setdefault(rule.head.relation, []).append(rule)
    functionals = getattr(rules, "functionals", {})
    out, todo = set(), sorted(set(relations) & by_head.keys())
    while todo:
        relation = todo.pop()
        if relation not in out:
            out.add(relation)
            if relation in functionals and functionals[relation].domain in by_head:
                todo.append(functionals[relation].domain)
            for rule in by_head[relation]:
                todo.extend(item.atom.relation for item in (*rule.body, *rule.aggregates)
                            if item.atom.relation in by_head)
    return out


def check(rules, rows, read=(), *, domains=None) -> list:
    """One `underived_row` for each head row a rule of a covered relation derives from the snapshots and the head
    relation's snapshot lacks, with the rule and the least substitution that derives it. `rows(relation)` gives a
    complete snapshot as {key: (key parts, values)}. Raises ValueError for a rule whose instances cannot be
    enumerated: a variable that no positive premise, aggregate or assignment binds.
    With `domains`, check just the derived aggregate domains of a standalone proof and their dependencies."""
    ordered = {}

    def table(relation):
        if relation not in ordered:  # sorted once; every atom over it is one pass in this order
            ordered[relation] = sorted(rows(relation).values(), key=itemgetter(0))
        return ordered[relation]

    scope = covered(rules, read) if domains is None else dependencies(rules, domains)
    functionals = getattr(rules, "functionals", {})
    findings = []
    for rule in sorted(rules.values(), key=lambda r: r.id):
        if rule.head.relation not in scope or rule.head.relation in functionals:
            continue
        variables, found = instances(rule, table)
        head = _subst(rule.head.terms, variables)
        for run, present in _merge(sorted(found, key=head), head, table(rule.head.relation), itemgetter(0)):
            if not present:
                least = min(run)
                findings.append({"reason": "underived_row", "relation": rule.head.relation,
                                 "key": encode_key(head(least)), "rule": rule.id,
                                 "bindings": [{"variable": v, "value": x} for v, x in sorted(zip(variables, least))]})
    return findings


def exhausted(rules, rows) -> list:
    """One `bound_reached` for each counter that reached its bound on the complete snapshots:
    the relation was cut off where its count stopped, which is an error and never a meaning.

    The counter is found here from the rule's shape (`counter`), not taken from the compiler. The rows the rule
    would add beyond its bound are its instances with the conditions that bound the counter replaced by
    `counter > last`, over the snapshots as they are: any one of them means the count went on past what the
    relation holds. A count that ends at its bound with nothing left to add has no such instance. The finding
    names the relation, the rule, the bound, how many rows the rule would add, the least of them and the
    substitution that adds it. `rows` is as for `check`."""
    ordered, findings = {}, []

    def table(relation):
        if relation not in ordered:
            ordered[relation] = sorted(rows(relation).values(), key=itemgetter(0))
        return ordered[relation]

    for rule in sorted(rules.values(), key=lambda r: r.id):
        found = counter(rule, rules)
        if found is None:
            continue
        var, last = found
        beyond = replace(rule, conditions=tuple(c for c in rule.conditions if upper(c, var) is None)
                         + (Calculation("gt", var, str(last)),))
        variables, added = instances(beyond, table)
        if added:
            head, least = _subst(rule.head.terms, variables), min(added)
            findings.append({"reason": "bound_reached", "relation": rule.head.relation, "rule": rule.id,
                             "bound": f"{var} <= {last}", "count": len({head(row) for row in added}),
                             "key": encode_key(head(least)),
                             "bindings": [{"variable": v, "value": x} for v, x in sorted(zip(variables, least))]})
    return findings


def counter(rule, rules):
    """(the counter variable, the last value it is read at) of a counter with an explicit bound, else None.
    The shape: the rule reads its own relation once, positively; an assignment adds a positive integer constant
    to the variable at one column of that premise and puts the sum at the same column of the head; a condition
    bounds that variable above by an integer constant (the least such bound is the last value); and every other
    rule of the head's relation puts a constant at that column, where the count starts. A column that fails one
    of these is passed over for the next, so a rule that steps two columns is held to the bound of the one that
    counts, not to a guard on the other. `rules` is every rule of the program, by id."""
    own = [b for b in rule.body if b.atom.relation == rule.head.relation]
    if len(own) != 1 or own[0].polarity != "positive":
        return None
    start = [r for r in rules.values() if r.head.relation == rule.head.relation and r.id != rule.id]
    for j, (n, m) in enumerate(zip(own[0].atom.terms, rule.head.terms)):
        if not n.startswith("?"):
            continue
        steps = [c.right if c.left == n else c.left for c in rule.assignments
                 if c.var == m and c.op == "add" and (c.left == n) != (c.right == n)]
        if not steps or not INTEGER.fullmatch(steps[0]) or int(steps[0]) <= 0:
            continue
        lasts = [u for u in (upper(c, n) for c in rule.conditions) if u is not None]
        if lasts and not any(r.head.terms[j].startswith("?") for r in start):
            return n, min(lasts)
    return None


def upper(condition, var):
    """The greatest value `var` may have under a condition that bounds it above by an integer constant, else None."""
    c = condition
    if c.compare_as is not None:  # a typed comparison orders text, never an integer counter
        return None
    if c.left == var and c.op in ("lt", "le") and INTEGER.fullmatch(c.right):
        return int(c.right) - (c.op == "lt")
    if c.right == var and c.op in ("gt", "ge") and INTEGER.fullmatch(c.left):
        return int(c.left) - (c.op == "gt")
    return None


def instances(rule, table):
    """Every substitution under which the body of the rule holds: (the variables, a row of values for each).
    `table(relation)` gives the rows of a complete snapshot as (key parts, values), sorted by key parts."""
    current = ((), [()])  # the empty substitution
    todo = [b.atom for b in rule.body if b.polarity == "positive"]
    # Filters before what binds, so that less is carried along.
    steps = [(_variables(b.atom.terms), _absent, b.atom) for b in rule.body if b.polarity != "positive"]
    steps += [(_variables((c.left, c.right)), _condition, c) for c in rule.conditions]
    steps += [(_variables(t for t in a.atom.terms if t != "_"), _aggregate, a) for a in rule.aggregates]
    steps += [(_variables((c.left, c.right)), _assignment, c) for c in rule.assignments]
    while True:
        bound = set(current[0])
        ready = next((s for s in steps if s[0] <= bound), None)
        if ready is not None:  # each step as soon as its variables are bound, so before the next join
            steps.remove(ready)
            _, apply, what = ready
            current = apply(current, what, table, rule)
        elif todo:  # the next atom that shares a variable with what is bound, or else the next: a product
            atom = next((a for a in todo if bound & set(a.terms)), todo[0])
            todo.remove(atom)
            current = _join(current, _scan(atom, table(atom.relation), rule.calc_input_type(atom.relation)))
        else:
            break
    unbound = sorted(rule.variables - set(current[0]))  # every step left over waits for one of these
    if unbound:
        raise ValueError(f"{rule.id}: {', '.join(unbound)} is not bound by a positive premise, an aggregate or an "
                         "assignment, so the rule's instances cannot be enumerated")
    return current


def _variables(terms) -> set:
    return {t for t in terms if t.startswith("?")}


def _key(indexes):
    return lambda row: tuple(row[i] for i in indexes)


def _subst(terms, variables):
    """A function from a row of values to the terms under that substitution; a constant stays as it is."""
    index = {v: i for i, v in enumerate(variables)}
    places = [(index.get(t), t) for t in terms]
    return lambda row: tuple(t if i is None else row[i] for i, t in places)


def _merge(left, left_key, right, right_key):
    """Walk two lists that are sorted on their keys, once. For each key of `left`: its rows, and the rows of
    `right` with that key (none: an empty list)."""
    end = object()
    runs = ((k, list(g)) for k, g in groupby(right, right_key))
    run = next(runs, end)
    for k, group in groupby(left, left_key):
        while run is not end and run[0] < k:
            run = next(runs, end)
        yield list(group), (run[1] if run is not end and run[0] == k else [])


def _scan(atom, ordered, calc_type: CalcColumnType | None):
    """The rows a positive atom matches, as a table over its variables: one pass over the relation in key order.
    A calculation selection only supplies values of its declared type (check._check_graph, `bad_calc_premise`)."""
    terms = atom.terms
    variables = tuple(dict.fromkeys(t for t in terms if t.startswith("?")))
    first = [terms.index(v) for v in variables]
    again = [(i, terms.index(t)) for i, t in enumerate(terms) if t.startswith("?") and terms.index(t) != i]
    constants = [(i, t) for i, t in enumerate(terms) if not t.startswith("?")]
    out = []
    for parts, _ in ordered:
        if (len(parts) == len(terms) and all(parts[i] == t for i, t in constants)
                and all(parts[i] == parts[j] for i, j in again)
                and (calc_type is None or calc_value(parts[1], calc_type))):
            out.append(tuple(parts[i] for i in first))
    return variables, out


def _join(left, right):
    """The natural join of two tables: a sort-merge on their shared variables (none: the product)."""
    (left_vars, left_rows), (right_vars, right_rows) = left, right
    shared = [v for v in right_vars if v in left_vars]
    left_key, right_key = _key([left_vars.index(v) for v in shared]), _key([right_vars.index(v) for v in shared])
    rest = _key([i for i, v in enumerate(right_vars) if v not in left_vars])
    out = []
    for run, matches in _merge(sorted(left_rows, key=left_key), left_key, sorted(right_rows, key=right_key), right_key):
        tails = [rest(m) for m in matches]
        out.extend(row + tail for row in run for tail in tails)
    return left_vars + tuple(v for v in right_vars if v not in left_vars), out


def _absent(current, atom, table, rule):
    """The rows for which a negated atom has no row: an anti-join, in key order."""
    variables, found = current
    key = _subst(atom.terms, variables)
    return variables, [row for run, present in _merge(sorted(found, key=key), key, table(atom.relation), itemgetter(0))
                       if not present for row in run]


def _condition(current, c, table, rule):
    variables, found = current
    left, right = _subst((c.left,), variables), _subst((c.right,), variables)
    return variables, [row for row in found if _holds(c.op, left(row)[0], right(row)[0], c.compare_as)]


def _aggregate(current, spec, table, rule):
    """The rows with the result of an aggregate over their group. No instance holds where no witness would: the
    aggregate reads invalid input (`invalid_value`), and in the rule IR, where a binding is a bare integer, the
    result is not known (an empty `min` or `max`, an unknown contributor) or lies outside BIGINT."""
    variables, found = current
    terms = spec.atom.terms
    fixed = [i for i, t in enumerate(terms) if t != "_"]
    group, member = _subst([terms[i] for i in fixed], variables), lambda m: tuple(m[0][i] for i in fixed)
    members = sorted((m for m in table(spec.atom.relation) if len(m[0]) == len(terms)), key=member)
    out = []
    for run, group_rows in _merge(sorted(found, key=group), group, members, member):
        if spec.function == "count" and (spec.format == "rezono.rules/1"
                                         or (spec.over is None and getattr(spec, "state_key", None) is None)):
            result = f"known:{len(group_rows)}"
        else:
            result = _fold(spec.function, cells(spec, group_rows), spec.format)
        if result == "invalid":
            continue
        if rule.bare_values:
            known = result.startswith("known:")
            if (known and not _fits(result.removeprefix("known:"))) or (spec.var and not known):
                continue
            result = result.removeprefix("known:")
        out.extend(_bind(variables, run, spec.var, lambda row: result))
    return _bound(variables, spec.var), out


STATE_PRIORITY = {"known": 0, "not_applicable": 1, "unknown": 2, "invalid": 3}


def _worse_state(a: str, b: str) -> str:
    return a if STATE_PRIORITY[a] >= STATE_PRIORITY[b] else b


def functional_instances(rule, table):
    """Every firing substitution of a functional rule, tracking propagated non-known aggregate states
    (`invalid > unknown > not_applicable > known`) instead of dropping non-known aggregate results.

    Returns `(variables, [(row_values, row_state), ...])`, where a variable bound by a non-known
    aggregate (or an assignment derived from one) carries `None` in `row_values`."""
    current = ((), [((), "known")])
    todo = [b.atom for b in rule.body if b.polarity == "positive"]
    steps = [(_variables(b.atom.terms), _absent_st, b.atom) for b in rule.body if b.polarity != "positive"]
    steps += [(_variables((c.left, c.right)), _condition_st, c) for c in rule.conditions]
    steps += [(_variables(t for t in a.atom.terms if t != "_"), _aggregate_st, a) for a in rule.aggregates]
    steps += [(_variables((c.left, c.right)), _assignment_st, c) for c in rule.assignments]
    while True:
        bound = set(current[0])
        ready = next((s for s in steps if s[0] <= bound), None)
        if ready is not None:
            steps.remove(ready)
            _, apply, what = ready
            current = apply(current, what, table, rule)
        elif todo:
            atom = next((a for a in todo if bound & set(a.terms)), todo[0])
            todo.remove(atom)
            current = _join_st(current, _scan(atom, table(atom.relation), rule.calc_input_type(atom.relation)))
        else:
            break
    unbound = sorted(rule.variables - set(current[0]))
    if unbound:
        raise ValueError(f"{rule.id}: {', '.join(unbound)} is not bound by a positive premise, an aggregate or an "
                         "assignment, so the rule's instances cannot be enumerated")
    return current


def _join_st(left, right):
    (left_vars, left_rows), (right_vars, right_rows) = left, right
    shared = [v for v in right_vars if v in left_vars]
    left_idx = [left_vars.index(v) for v in shared]
    left_key = lambda item: tuple(item[0][i] for i in left_idx)
    right_key = _key([right_vars.index(v) for v in shared])
    new_right = [i for i, v in enumerate(right_vars) if v not in left_vars]
    rest = _key(new_right)
    concrete, non_concrete = [], []
    for item in left_rows:
        if any(item[0][i] is None for i in left_idx):
            non_concrete.append(item)
        else:
            concrete.append(item)
    out = []
    for run, matches in _merge(sorted(concrete, key=left_key), left_key, sorted(right_rows, key=right_key), right_key):
        tails = [rest(m) for m in matches]
        out.extend((vals + tail, st) for vals, st in run for tail in tails)
    null_tail = (None,) * len(new_right)
    out.extend((vals + null_tail, st) for vals, st in non_concrete)
    return left_vars + tuple(v for v in right_vars if v not in left_vars), out


def _absent_st(current, atom, table, rule):
    variables, found = current
    key = _subst(atom.terms, variables)
    concrete, non_concrete = [], []
    for item in found:
        if any(v is None for v in key(item[0])):
            non_concrete.append(item)
        else:
            concrete.append(item)
    item_key = lambda item: key(item[0])
    out = [item for run, present in _merge(sorted(concrete, key=item_key), item_key, table(atom.relation), itemgetter(0))
           if not present for item in run]
    out.extend(non_concrete)
    return variables, out


def _condition_st(current, c, table, rule):
    variables, found = current
    left, right = _subst((c.left,), variables), _subst((c.right,), variables)
    out = []
    for vals, st in found:
        a, b = left(vals)[0], right(vals)[0]
        if a is None or b is None or _holds(c.op, a, b, c.compare_as):
            out.append((vals, st))
    return variables, out


def _aggregate_st(current, spec, table, rule):
    variables, found = current
    terms = spec.atom.terms
    fixed = [i for i, t in enumerate(terms) if t != "_"]
    group, member = _subst([terms[i] for i in fixed], variables), lambda m: tuple(m[0][i] for i in fixed)
    members = sorted((m for m in table(spec.atom.relation) if len(m[0]) == len(terms)), key=member)
    idx = variables.index(spec.var) if spec.var in variables else None
    concrete, non_concrete = [], []
    for item in found:
        if any(v is None for v in group(item[0])):
            non_concrete.append(item)
        else:
            concrete.append(item)
    item_group = lambda item: group(item[0])
    out = []
    for run, group_rows in _merge(sorted(concrete, key=item_group), item_group, members, member):
        if spec.function == "count" and (spec.format == "rezono.rules/1"
                                         or (spec.over is None and getattr(spec, "state_key", None) is None)):
            result = f"known:{len(group_rows)}"
        else:
            result = _fold(spec.function, cells(spec, group_rows), spec.format)
        if result.startswith("known:"):
            raw = result.removeprefix("known:")
            if rule.bare_values and not _fits(raw):
                continue
            bound_val = raw if rule.bare_values else result
            for vals, st in run:
                if spec.var is None:
                    out.append((vals, st))
                elif idx is not None:
                    if vals[idx] is None or vals[idx] == bound_val:
                        out.append((vals, st))
                else:
                    out.append(((*vals, bound_val), st))
        else:
            if result == "not_applicable" and not group_rows and getattr(spec, "state_key", None) is None:
                continue
            prop = result if result in STATE_PRIORITY else "invalid"
            for vals, st in run:
                new_st = _worse_state(st, prop)
                if spec.var is None or idx is not None:
                    out.append((vals, new_st))
                else:
                    out.append(((*vals, None), new_st))
    for vals, st in non_concrete:
        if spec.var is None or idx is not None:
            out.append((vals, st))
        else:
            out.append(((*vals, None), st))
    return _bound(variables, spec.var), out


def _assignment_st(current, c, table, rule):
    variables, found = current
    left, right = _subst((c.left,), variables), _subst((c.right,), variables)
    idx = variables.index(c.var) if c.var in variables else None
    out = []
    for vals, st in found:
        a, b = left(vals)[0], right(vals)[0]
        if a is None or b is None:
            out.append((vals, st) if idx is not None else ((*vals, None), st))
            continue
        got = _arith(c.op, a, b)
        if got is None or not all(_fits(v) for v in (a, b, got)):
            continue
        if idx is None:
            out.append(((*vals, got), st))
        elif vals[idx] is None or vals[idx] == got:
            out.append((vals, st))
    return _bound(variables, c.var), out


def _assignment(current, c, table, rule):
    """The rows with `var = left op right`: none where an operand is no integer, or an operand or the result lies
    outside BIGINT (`assignment_mismatch`, `arithmetic_overflow`)."""
    variables, found = current
    left, right = _subst((c.left,), variables), _subst((c.right,), variables)

    def value(row):
        a, b = left(row)[0], right(row)[0]
        got = _arith(c.op, a, b)
        return got if got is not None and all(_fits(v) for v in (a, b, got)) else None

    return _bound(variables, c.var), list(_bind(variables, found, c.var, value))


def _bound(variables, var):
    return variables if var is None or var in variables else (*variables, var)


def _bind(variables, found, var, value):
    """Each row with `var` bound to its value; a row whose value is None, or that already binds `var` to another
    value, drops out. Without a variable the rows stay as they are."""
    index = variables.index(var) if var in variables else None
    for row in found:
        v = value(row)
        if v is None or var is None:
            if v is not None:
                yield row
        elif index is None:
            yield (*row, v)
        elif row[index] == v:
            yield row
