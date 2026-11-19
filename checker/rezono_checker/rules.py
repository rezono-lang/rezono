"""Adapter for rule definitions. The only module that knows their format.

It reads the rule IR of the compiler (contracts/rules.yaml, `format: rezono.rules/1`): relations with
their key and value columns, and rules with conditions and assignments. In that form a binding is the
bare value of a key column (an integer as decimal text), an aggregate may range over a key column (its
term is '_'), and the checker evaluates the conditions and assignments of each witness.

It also still reads the minimal form the checker started with (no `format`):

    rules:
      - id: <rule id>
        stratum: <int>
        head: {relation: <name>, terms: [<term>, ...]}
        body: [{relation, terms, polarity: positive|negative, stratum}, ...]
        aggregates: [{relation, terms, function: count|sum|min|max, over: <column>, as: <var>, stratum}, ...]

A term is a variable ('?x'), a constant, or '_' (only in aggregates: ranges over the group).
The declared strata are not trusted: each relation's stratum is derived from the rules
(a head relation has the stratum of its rules, any other relation stratum 0) and every
declaration must agree with it. That rejects negation and aggregation through recursion.

Rule safety is not trusted either (`_check_safety`): every variable is bound, so that a witness
cannot choose a value. What the loader does take on trust is in the checker's README, "Trusted base".
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .canon import INTEGER, CalcColumnType

FUNCTIONS = ("count", "sum", "min", "max")
COMPARISONS = ("eq", "ne", "lt", "le", "gt", "ge")
COMPARE_AS = ("binary_text", "utc_instant")  # Condition.compare_as: how two bound text operands are ordered
OPERATORS = ("add", "sub", "mul", "div", "days")  # days: a view's reading of an ISO date (evaluate._arith)


@dataclass(frozen=True)
class Atom:
    relation: str
    terms: tuple


@dataclass(frozen=True)
class BodyAtom:
    atom: Atom
    polarity: str
    stratum: int


@dataclass(frozen=True)
class AggregateSpec:
    atom: Atom
    function: str
    over: str | None
    var: str | None
    stratum: int
    over_key: int | None = None  # rule IR: the key position of `over`, when it is a key column


@dataclass(frozen=True)
class Calculation:
    """A condition (`left op right` must hold) or an assignment (`var = left op right`)."""
    op: str
    left: str
    right: str
    var: str | None = None
    compare_as: str | None = None  # a condition's typed comparison (decisions/ordered-rule-scalars.md)


@dataclass(frozen=True)
class Rule:
    id: str
    stratum: int
    head: Atom
    body: tuple
    aggregates: tuple
    conditions: tuple = ()
    assignments: tuple = ()
    bare_values: bool = False  # rule IR: bindings are bare key values, not '<state>:<payload>'
    calc_inputs: frozenset[str] = frozenset()  # these premises need their own checked W12 witness
    rational_calc_inputs: frozenset[str] = frozenset()  # the subset with exact numbers

    def calc_input_type(self, relation: str) -> CalcColumnType | None:
        if relation in self.rational_calc_inputs:
            return "rational"
        if relation in self.calc_inputs:
            return "integer"
        return None

    @property
    def variables(self) -> frozenset:
        atoms = (self.head, *(b.atom for b in self.body), *(a.atom for a in self.aggregates))
        terms = {t for atom in atoms for t in atom.terms} | {a.var for a in self.aggregates if a.var}
        terms |= {c.var for c in self.assignments} | {t for c in (*self.conditions, *self.assignments)
                                                       for t in (c.left, c.right)}
        return frozenset(t for t in terms if t.startswith("?"))


class Rules(dict):
    """The rules by id, with the epoch's obligations the rule IR declares (empty in the minimal form):
    `invariants`, the relations that must be empty, and `outcomes`, each outcome relation with its kind."""
    invariants: frozenset = frozenset()
    outcomes: dict = {}


def _obligations(doc: dict) -> tuple[frozenset, dict]:
    """The invariant and outcome relations of a rule IR, each on a derived relation. An outcome's kind is a
    declared base relation with one key column, of the type of the outcome's element: any other target,
    such as an empty derived relation, would let the totality check pass vacuously. Raises ValueError."""
    invariants, outcomes = set(), {}
    declared = {r.get("name"): r for r in doc.get("relations", [])}
    for r in doc.get("relations", []):
        derived = r.get("role") == "derived"
        if r.get("invariant", False) not in (True, False) or (r.get("invariant") and not derived):
            raise ValueError(f"{r['name']}: invariant is true or false, on a derived relation")
        if r.get("invariant"):
            invariants.add(r["name"])
        if "outcome" in r:
            if not (derived and isinstance(r["outcome"], str) and len(r.get("key", [])) == 3
                    and [c.get("name") for c in r["key"][1:]] == ["state", "reason"]):
                raise ValueError(f"{r['name']}: an outcome is derived, with the element, state and reason")
            kind = declared.get(r["outcome"], {})
            if not (kind.get("role") == "base" and len(kind.get("key", [])) == 1
                    and kind["key"][0].get("type") == r["key"][0].get("type")):
                raise ValueError(f"{r['name']}: {r['outcome']} is not a kind: a base relation with one key column "
                                 f"of the element's type")
            outcomes[r["name"]] = r["outcome"]
    return frozenset(invariants), outcomes


def _closes(doc: dict, invariants: frozenset) -> None:
    """A relation that closes another (W14, `closes`) states that the two never hold at the same key. The
    checker holds that through an invariant, so the rule IR must carry it whole: the invariant relation
    `<closing>_closes_<closed>` with exactly one rule, a row of each relation at the closing relation's key,
    the other columns of the closed relation free. Without it, or with a rule that reads fewer rows, a key in
    both relations would pass unseen. Raises ValueError."""
    rules = doc.get("rules", [])
    for r in doc.get("relations", []):
        if "closes" not in r:
            continue
        name, closed, n = r["name"], r["closes"], len(r.get("key", []))
        check = f"{name}_closes_{closed}"
        own = [x for x in rules if x["head"]["relation"] == check]
        ok = check in invariants and len(own) == 1 and name != closed
        if ok:
            body = {b["relation"]: list(b["terms"]) for b in own[0].get("body", []) if b["polarity"] == "positive"}
            head, rest = list(own[0]["head"]["terms"]), body.get(closed, [])[n:]
            ok = (len(own[0].get("body", [])) == 2 and set(body) == {name, closed} and len(head) == n
                  and not (own[0].get("aggregates") or own[0].get("conditions") or own[0].get("assignments"))
                  and all(t.startswith("?") for t in head + rest) and len(set(head + rest)) == len(head + rest)
                  and body[name] == head and body[closed][:n] == head)
        if not ok:
            raise ValueError(f"{name}: closes {closed} needs the invariant {check} with one rule, a row of each "
                             f"at the same key")


def _atom(doc) -> Atom:
    terms = tuple(doc["terms"])
    if not all(isinstance(t, str) for t in terms):
        raise ValueError(f"terms must be strings: {doc}")
    return Atom(doc["relation"], terms)


def _over_key(a: dict, keys: dict) -> int | None:
    names = keys.get(a["relation"], [])
    if a.get("over") in names:
        pos = names.index(a["over"])
        if a["terms"][pos] != "_":
            raise ValueError(f"aggregate over key column {a['over']} must range over it ('_')")
        return pos
    return None


SEAL_KEYS = ("kind", "period", "row_sha256", "tables", "closed_until", "covers", "element", "sha256", "refused",
             "accepted")


PART_KEYS = ("kind", "arrow", "owner", "tables", "accepted")


def _names(value, keys) -> bool:
    return (isinstance(value, dict) and set(value) == set(keys)
            and all(isinstance(value[k], str) for k in keys if k != "tables")
            and isinstance(value["tables"], list) and all(isinstance(t, str) for t in value["tables"]))


def load_seals(doc: dict) -> list[dict]:
    """The sealed kind of a rule IR: the tables to recompute row hashes and refused and accepted
    input from, and its parts (`parts`, optional): each with the arrow to its owner, the sealed kind or an
    earlier part. Raises ValueError on bad input."""
    out = []
    for s in doc.get("seals", []):
        parts = s.get("parts") if isinstance(s, dict) else None
        if not _names({k: v for k, v in s.items() if k != "parts"} if isinstance(s, dict) else s, SEAL_KEYS):
            raise ValueError(f"a seal names the tables {', '.join(SEAL_KEYS)}: {s!r}")
        if "parts" in s:
            placed = {s["kind"]}
            if not isinstance(parts, list) or not parts:
                raise ValueError(f"the parts of a seal are a list that is not empty: {parts!r}")
            for p in parts:
                if not _names(p, PART_KEYS) or p["owner"] not in placed or p["kind"] in placed:
                    raise ValueError(f"a part names {', '.join(PART_KEYS)}, with an owner before it: {p!r}")
                placed.add(p["kind"])
        out.append(dict(s))
    return out


def _rational_keys(relations: Sequence[dict]) -> dict[str, tuple[bool, ...]]:
    """Rational columns are selection values and derived key columns."""
    result = {}
    for r in relations:
        columns = tuple(c.get("type") == "rational" for c in r.get("key", ()))
        if any(c.get("type") == "rational" for c in r.get("values") or ()):
            raise ValueError(f"{r['name']}: a rational column is part of the key")
        if not any(columns):
            continue
        if ((r.get("role") != "derived" and (r.get("role") != "calc" or columns != (False, True, False, False)))
                or sum(other["name"] == r["name"] for other in relations) != 1):
            raise ValueError(f"{r['name']}: expected a rational selection value or a derived key column")
        result[r["name"]] = columns
    return result


def _check_rational_uses(rule: Rule, keys: dict[str, tuple[bool, ...]]) -> None:
    """Copy a rational variable without converting it or using it in an operation."""
    rational, other = set(), set()
    atoms = (rule.head, *(b.atom for b in rule.body), *(a.atom for a in rule.aggregates))
    for atom in atoms:
        columns = keys.get(atom.relation)
        if columns is None:
            other.update(t for t in atom.terms if t.startswith("?"))
            continue
        if len(atom.terms) != len(columns):
            raise ValueError(f"{rule.id}: {atom.relation} needs one term for each key column")
        for term, exact in zip(atom.terms, columns):
            if exact and not term.startswith("?"):
                raise ValueError(f"{rule.id}: a rational column must bind or copy a variable")
            if term.startswith("?"):
                (rational if exact else other).add(term)
    if rational & other:
        raise ValueError(f"{rule.id}: a rational variable must use rational columns throughout")
    operations = {term for c in (*rule.conditions, *rule.assignments) for term in (c.left, c.right, c.var)}
    operations |= {a.var for a in rule.aggregates}
    if rational & operations or any(a.atom.relation in keys for a in rule.aggregates):
        raise ValueError(f"{rule.id}: a rational value is only copied")
    if any(b.atom.relation in keys and b.polarity != "positive" for b in rule.body):
        raise ValueError(f"{rule.id}: a rational premise must be positive")


def load_rules(doc: dict) -> dict:
    """Read rule definitions and check their stratification. Raises ValueError on bad input."""
    ir = doc.get("format") is not None
    if ir and doc["format"] != "rezono.rules/1":
        raise ValueError(f"unknown rule format {doc['format']}")
    relations = doc.get("relations", ()) if ir else ()
    keys = {r["name"]: [c["name"] for c in r.get("key", [])] for r in relations}
    calc_relations = {r["name"] for r in relations if r.get("role") == "calc"}
    rational_keys = _rational_keys(relations)
    for r in relations:
        if r.get("role") == "derived" and r.get("values"):  # a witness proves a key; nothing would prove a value
            raise ValueError(f"{r['name']}: a derived relation is a set, without value columns")
        if "release" in r:  # a release has proof obligations this checker does not verify yet
            raise ValueError(f"{r['name']}: release is not supported yet: a role reads a negation or an aggregate only over relations it reads in full (docs/architecture.md, delimited release)")
    rules = Rules()
    if ir:
        rules.invariants, rules.outcomes = _obligations(doc)
        _closes(doc, rules.invariants)
    for r in doc.get("rules", []):
        rule = Rule(
            id=r["id"],
            stratum=int(r["stratum"]),
            head=_atom(r["head"]),
            body=tuple(BodyAtom(_atom(b), b["polarity"], int(b["stratum"])) for b in r.get("body", [])),
            aggregates=tuple(
                AggregateSpec(_atom(a), a["function"], a.get("over"), a.get("as"), int(a["stratum"]), _over_key(a, keys))
                for a in r.get("aggregates", [])
            ),
            conditions=tuple(Calculation(c["op"], c["left"], c["right"], compare_as=c.get("compare_as"))
                             for c in r.get("conditions", [])) if ir else (),
            assignments=tuple(Calculation(c["op"], c["left"], c["right"], c.get("var"))
                              for c in r.get("assignments", [])) if ir else (),
            bare_values=ir,
            calc_inputs=frozenset(b["relation"] for b in r.get("body", ()) if b["relation"] in calc_relations),
            rational_calc_inputs=frozenset(b["relation"] for b in r.get("body", ())
                                           if b["relation"] in calc_relations and b["relation"] in rational_keys),
        )
        for c in rule.assignments:
            if not isinstance(c.var, str):
                raise ValueError(f"{rule.id}: an assignment names its result, a variable: {c}")
        for c in (*rule.conditions, *rule.assignments):
            if not all(isinstance(t, str) for t in (c.op, c.left, c.right)):  # a term is text, never a JSON number
                raise ValueError(f"{rule.id}: an operator and its terms are text: {c}")
            if c.op not in (OPERATORS if c.var else COMPARISONS):
                raise ValueError(f"{rule.id}: unknown operator {c.op}")
            if c.compare_as is not None and c.compare_as not in COMPARE_AS:
                raise ValueError(f"{rule.id}: unknown comparison type {c.compare_as}")
            if c.compare_as is not None and not (c.left.startswith("?") and c.right.startswith("?")):
                raise ValueError(f"{rule.id}: a typed comparison needs two bound operands: {c}")
        if rule.id in rules:
            raise ValueError(f"duplicate rule id {rule.id}")
        if rule.head.relation in calc_relations:
            raise ValueError(f"{rule.id}: a rule cannot produce a calculation selection")
        if "_" in rule.head.terms or any("_" in b.atom.terms for b in rule.body):
            raise ValueError(f"{rule.id}: '_' is only allowed in aggregates")
        for b in rule.body:
            if b.polarity not in ("positive", "negative"):
                raise ValueError(f"{rule.id}: unknown polarity {b.polarity}")
            if b.atom.relation in rule.calc_inputs and (b.polarity != "positive" or b.atom.terms[2:] != ("known", "")):
                raise ValueError(f"{rule.id}: calculation inputs must be positive with selections known")
        for a in rule.aggregates:
            if a.atom.relation in calc_relations:
                raise ValueError(f"{rule.id}: an aggregate cannot read a calculation selection")
            if a.function not in FUNCTIONS or (a.function != "count" and not a.over):
                raise ValueError(f"{rule.id}: bad aggregate {a}")
            if a.var is not None and not a.var.startswith("?"):
                raise ValueError(f"{rule.id}: aggregate result {a.var} is not a variable")
        _check_safety(rule)
        if rational_keys:
            _check_rational_uses(rule, rational_keys)
        rules[rule.id] = rule

    strata = {}
    for rule in rules.values():
        if strata.setdefault(rule.head.relation, rule.stratum) != rule.stratum:
            raise ValueError(f"{rule.id}: {rule.head.relation} is derived in two strata")
    for rule in rules.values():
        uses = [(b.atom.relation, b.stratum, b.polarity == "positive") for b in rule.body]
        uses += [(a.atom.relation, a.stratum, False) for a in rule.aggregates]
        for relation, declared, positive in uses:
            actual = strata.get(relation, 0)
            if declared != actual:
                raise ValueError(f"{rule.id}: {relation} is in stratum {actual}, declared {declared}")
            if actual > rule.stratum or (not positive and actual == rule.stratum):
                raise ValueError(f"{rule.id}: {relation} breaks stratification")
    if ir:
        check_worlds(doc, rules)
    return rules


def _check_safety(rule: Rule) -> None:
    """Range restriction, held here and not taken from the compiler. A witness binds every variable of its rule,
    and each check then reads the binding. So a variable that nothing in the rule determines is one the witness
    may choose: with `lonely(x) :- request(x), !pair(x, y)`, any y that is in no pair proves lonely(x).

    - A variable of a negated premise, and a group variable of an aggregate, is bound by a positive premise: the
      absence, and the group, are those of rows that are there.
    - The operands of an assignment are bound before it: by a positive premise, an aggregate or an earlier
      assignment. Its result is a variable.
    - The operands of a condition and the variables of the head are bound by one of those.
    - A divisor is an integer constant that is not zero (contracts/rules.yaml), so no instance divides by zero.
    - A body has a positive premise, or it has no premise and only aggregates (each over a whole relation).
    The compiler also wants each result to be a fresh variable. The checker does not need that: a result that
    is bound already must equal that binding, in the check of a witness and in the closure pass alike.
    Raises ValueError."""
    def free(terms, bound):
        return sorted({t for t in terms if t.startswith("?")} - bound)

    def refuse(variables, where):
        raise ValueError(f"{rule.id}: unsafe variable {variables[0]}: {where}")

    positive = {t for b in rule.body if b.polarity == "positive" for t in b.atom.terms if t.startswith("?")}
    for b in rule.body:
        if b.polarity != "positive" and free(b.atom.terms, positive):
            refuse(free(b.atom.terms, positive), "a negation reads only what a positive premise binds")
    bound = set(positive)
    for a in rule.aggregates:
        if free(a.atom.terms, positive):
            refuse(free(a.atom.terms, positive), "the group of an aggregate is bound by a positive premise")
        bound |= {a.var} - {None}
    for c in rule.assignments:
        if not c.var.startswith("?"):
            raise ValueError(f"{rule.id}: assignment result {c.var} is not a variable")
        if free((c.left, c.right), bound):
            refuse(free((c.left, c.right), bound), "an operand of an assignment is bound before it")
        if c.op == "div" and (not INTEGER.fullmatch(c.right) or int(c.right) == 0):
            raise ValueError(f"{rule.id}: the divisor {c.right} is not an integer constant other than zero")
        bound.add(c.var)
    for c in rule.conditions:
        if free((c.left, c.right), bound):
            refuse(free((c.left, c.right), bound), "an operand of a condition is bound")
    if free(rule.head.terms, bound):
        refuse(free(rule.head.terms, bound), "a head variable is bound by a positive premise, an aggregate or an "
                                             "assignment")
    # What a body ranges over: a positive premise, or, with no premise at all, its aggregates (each over a whole
    # relation, without a group). An empty body is a fact written as a rule, and a body of negations only holds
    # for whatever is absent.
    if not (rule.aggregates if not rule.body else any(b.polarity == "positive" for b in rule.body)):
        raise ValueError(f"{rule.id}: a body has a positive premise, or only aggregates")


def check_worlds(doc: dict, rules: dict) -> dict:
    """Derived independently from the compiler: a base relation has its declared world (left
    out: closed); a derived relation is open when a rule reads an open relation positively, unless it is marked
    `absence`, which is closed. Negation of an open relation, and an aggregate over one, holds only in an
    `absence` relation: elsewhere a missing row is unknown, not false. A declared world of a derived relation
    and an outcome (W7, always closed) must agree. Returns {relation: world}. Raises ValueError."""
    declared = {r["name"]: r for r in doc.get("relations", [])}
    for name, r in declared.items():
        if r.get("world", "closed") not in ("closed", "open"):
            raise ValueError(f"{name}: world is closed or open")
        if r.get("absence", False) not in (True, False) or (r.get("absence") and r.get("role") != "derived"):
            raise ValueError(f"{name}: absence is true or false, on a derived relation")

    def absence(name):
        return declared.get(name, {}).get("absence") is True

    opened = {n for n, r in declared.items() if r.get("role") != "derived" and r.get("world") == "open"}
    changed = True
    while changed:  # least fixpoint: open spreads along positive literals only
        changed = False
        for rule in rules.values():
            head = rule.head.relation
            if head not in opened and not absence(head) and any(
                    b.polarity == "positive" and b.atom.relation in opened for b in rule.body):
                opened.add(head)
                changed = True
    for rule in sorted(rules.values(), key=lambda r: r.id):
        if absence(rule.head.relation):
            # The label is a claim about the registration: each rule must back it by negating an open relation,
            # aggregating over one, or reading another absence relation. A plain copy of an open relation
            # labelled absence would otherwise be closed, and negating it would pass.
            if not (any(b.polarity == "negative" and b.atom.relation in opened for b in rule.body)
                    or any(a.atom.relation in opened for a in rule.aggregates)
                    or any(b.polarity == "positive" and b.atom.relation != rule.head.relation
                           and absence(b.atom.relation) for b in rule.body)):
                raise ValueError(f"{rule.id}: a rule of an absence relation negates an open relation, aggregates "
                                 "over one, or reads another absence relation")
            continue
        for b in rule.body:
            if b.polarity == "negative" and b.atom.relation in opened:
                raise ValueError(f"{rule.id}: {b.atom.relation} is open, so a missing row is unknown, not false; "
                                 "negate it only in a relation marked absence")
        for a in rule.aggregates:
            if a.atom.relation in opened:
                raise ValueError(f"{rule.id}: {a.atom.relation} is open, so an aggregate over it counts only what is "
                                 "recorded; aggregate over it only in a relation marked absence")
    worlds = {n: "open" if n in opened else "closed" for n in declared.keys() | {r.head.relation for r in rules.values()}}
    for name, r in sorted(declared.items()):
        if r.get("role") == "derived" and r.get("world", worlds[name]) != worlds[name]:
            raise ValueError(f"{name}: declared {r['world']}, but its rules make it {worlds[name]}")
        if r.get("outcome") and worlds[name] != "closed":
            raise ValueError(f"{name}: an outcome is closed, but a rule reads an open relation positively")
    return worlds


def check_calc_bindings(doc: dict, rules: dict, calculation: dict | None) -> None:
    """Verify the rule-to-calculation boundary from both IRs, independently of the compiler."""
    declarations = doc.get("relations", ())
    inputs = {r["name"]: r for r in declarations if r.get("role") == "calc"}
    program = calculation or {}
    if not inputs and not program:
        return
    selections = {r["view"]: r["type"] for r in program.get("rules", ())}
    views = selections.keys() | {v["view"] for v in program.get("versions", ())}
    consumers: dict[str, set[str]] = {}
    for rule in rules.values():
        if rule.head.relation in views or rule.head.relation in inputs:
            raise ValueError(f"{rule.id}: a rule cannot produce a calculation selection")
        for premise in (*rule.body, *rule.aggregates):
            consumers.setdefault(premise.atom.relation, set()).add(rule.head.relation)
    if undeclared := (consumers.keys() & views) - inputs.keys():
        raise ValueError(f"calculation inputs need a calc declaration: {', '.join(sorted(undeclared))}")
    if not inputs:
        return
    for name, declaration in sorted(inputs.items()):
        key = [(c["name"], c["type"]) for c in declaration["key"]]
        if (selections.get(name) != "number" or declaration.get("values") or declaration.get("world", "open") != "open"
                or len(key) != 4 or key[0] not in (("subject", "string"), ("subject", "integer"))
                or key[1] not in (("value", "integer"), ("value", "rational"))
                or key[2:] != [("state", "string"), ("reason", "string")]
                or sum(r["name"] == name for r in declarations) != 1):
            raise ValueError(f"{name}: expected one open, typed input for a numeric calculation selection")
    after, todo = set(inputs), sorted(inputs)
    while todo:
        new = consumers.get(todo.pop(), set()) - after
        after.update(new)
        todo.extend(sorted(new))
    if "may_read" in after:
        raise ValueError("may_read cannot depend on a calculation selection")
    if cycle := after.intersection(f["table"] for f in program.get("facts", ())):
        raise ValueError(f"calculation reads its downstream relations: {', '.join(sorted(cycle))}")
    for rule in rules.values():
        for premise in rule.body:
            if premise.atom.relation in after and premise.polarity != "positive":
                raise ValueError(f"{rule.id}: calculation-dependent premises must be positive")
        if any(aggregate.atom.relation in after for aggregate in rule.aggregates):
            raise ValueError(f"{rule.id}: an aggregate cannot read a calculation-dependent relation")


def derived_relations(doc: dict, rules: dict) -> set:
    """Every derived relation the definitions declare: the relation catalogue of the rule IR (role
    `derived`), or the rule heads in the minimal form. Only an explicit `extend: true` may have no rule.
    It stays in this catalogue: check_epoch then requires its snapshot and refuses every row without a
    valid witness. With no rules, no such witness exists, so the snapshot must independently be empty.
    Unmarked declarations without rules and undeclared heads are refused. Raises ValueError."""
    heads = {r.head.relation for r in rules.values()}
    if doc.get("format") is None:
        return heads
    declared = {r["name"] for r in doc.get("relations", []) if r.get("role") == "derived"}
    extensions = set()
    for r in doc.get("relations", []):
        if "extend" in r:
            if type(r["extend"]) is not bool or (r["extend"] and r.get("role") != "derived"):
                raise ValueError(f"{r['name']}: extend is a boolean on a derived relation")
            if r["extend"]:
                extensions.add(r["name"])
    if declared - heads - extensions:
        raise ValueError(f"derived relations without a rule: {sorted(declared - heads - extensions)}")
    if heads - declared:
        raise ValueError(f"rule heads not declared as derived relations: {sorted(heads - declared)}")
    return declared
