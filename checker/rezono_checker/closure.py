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
    an invariant or an outcome (the checker reads their absence itself: an invariant is empty, an outcome gives one
    state), those in `read` (what the calculation reads, where a missing row is false or unknown), and every
    derived relation a rule of a covered relation reads."""
    todo = set(read) | set(getattr(rules, "invariants", ())) | set(getattr(rules, "outcomes", ()))
    for rule in rules.values():
        todo |= {b.atom.relation for b in rule.body if b.polarity != "positive"}
        todo |= {a.atom.relation for a in rule.aggregates}
    return dependencies(rules, todo)


def dependencies(rules, relations) -> set:
    """The derived relations that determine the contents of the given relations."""
    by_head = {}
    for rule in rules.values():
        by_head.setdefault(rule.head.relation, []).append(rule)
    out, todo = set(), sorted(set(relations) & by_head.keys())
    while todo:
        relation = todo.pop()
        if relation not in out:
            out.add(relation)
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
    findings = []
    for rule in sorted(rules.values(), key=lambda r: r.id):
        if rule.head.relation not in scope:
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
        if spec.function == "count":
            result = f"known:{len(group_rows)}"
        else:
            result = _fold(spec.function, cells(spec, group_rows))
        if result == "invalid":
            continue
        if rule.bare_values:
            known = result.startswith("known:")
            if (known and not _fits(result.removeprefix("known:"))) or (spec.var and not known):
                continue
            result = result.removeprefix("known:")
        out.extend(_bind(variables, run, spec.var, lambda row: result))
    return _bound(variables, spec.var), out


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
