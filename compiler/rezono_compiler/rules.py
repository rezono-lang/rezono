"""Rule IR (contracts/rules.yaml): load, check and analyse a rule program.

The IR is what the compiler hands to the translator, the checker and the explainer. Every check here
has a stable error code; docs/archive/m2-pipelines-and-rule-ir.md lists them.

Terms are strings: '?name' is a variable, '_' ranges over a group (aggregates only), anything else is
a constant, typed by its column. Integers are decimal text everywhere, also in strata and lines.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

from .names import ISO_DATE, NAME

FORMAT = "rezono.rules/1"
FORMAT_V2 = "rezono.rules/2"
FORMATS = (FORMAT, FORMAT_V2)
FUNCTIONS = ("count", "sum", "min", "max")
COMPARISONS = ("eq", "ne", "lt", "le", "gt", "ge")
# A condition's declared comparison type (decisions/ordered-rule-scalars.md): both operands are text
# variables bound by positive literals. binary_text orders the UTF-8 bytes; utc_instant validates
# YYYY-MM-DDTHH:mm:ss[.digits]Z and orders the exact instant. A malformed instant satisfies no operator.
COMPARE_AS = ("binary_text", "utc_instant")
ARITHMETIC = ("add", "sub", "mul", "div")
# `days`: the whole number of days from the ISO date `right` (a constant) to the ISO date `left` (a text
# variable), in the proleptic Gregorian calendar. Only a view's reading makes it: no rule file can
# write it, so hand-written rules still read text and whole numbers (R4).
DAYS = "days"
TYPES = ("string", "integer", "rational", "boolean", "date")
BOOLEAN = {"true": True, "false": False}
WORLDS = ("closed", "open")
CONFLICT_POLICIES = ("publish", "block")
EMPTY_STATES = ("unknown", "not_applicable")
ACCESS_RELATIONS = ("may_read", "may_read_full")
# The states of a named outcome; invalid comes from the violation views.
STATES = ("known", "unknown", "not_applicable")
REL_NAME = re.compile(r"^[a-z][a-z0-9]*((_|__)[a-z0-9]+)*$")  # base relations may be M1 tables `kind__slot`
VAR = re.compile(r"^\?[a-z][a-z0-9_]*$")
INT = re.compile(r"^(0|-?[1-9][0-9]*)$")   # canonical: no leading zeros, no "-0"
RATIONAL = re.compile(r"^(0|-?[1-9][0-9]*)(/[1-9][0-9]*)?$")
NAT = re.compile(r"^(0|[1-9][0-9]*)$")
BIGINT = (-2**63, 2**63 - 1)   # the engines' integer: a constant outside it is no value on any engine
BOUND = 2**63 - 1              # rezono.rules/2 symmetric 64-bit exact-number bound
SYMMETRIC_BOUND = (-BOUND, BOUND)
MAX_LEVELS = 64   # a counter is unrolled into at most this many strata: each one is a join more on every engine


def integer_bounds(fmt: str = FORMAT_V2) -> tuple[int, int]:
    """Return the signed constant bounds for `fmt` (`rezono.rules/2` symmetric, `rezono.rules/1` legacy)."""
    return SYMMETRIC_BOUND if fmt == FORMAT_V2 else BIGINT


def is_rational(t: str, *, bounds: tuple[int, int] = SYMMETRIC_BOUND) -> bool:
    """True if `t` is canonical exact rational text: an integer or reduced fraction `n/d` with d > 1."""
    if not RATIONAL.match(t):
        return False
    num_s, sep, den_s = t.partition("/")
    num = int(num_s)
    if not (bounds[0] <= num <= bounds[1]):
        return False
    if not sep:
        return True
    den = int(den_s)
    return 1 < den <= bounds[1] and math.gcd(abs(num), den) == 1


class IRError(ValueError):
    """A rule program the compiler must reject. `code` is stable; the message is for people."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code


def const_type(t):
    """The type of a constant compared with another constant: its own form decides."""
    return "integer" if INT.match(t) else "string"


def is_var(t):
    return t.startswith("?")


def untyped_conditions(rule, where):
    """The conditions of a rule, for a translation that has no lowering of compare_as yet: it refuses one
    rather than compare the raw text (decisions/ordered-rule-scalars.md)."""
    for c in rule.conditions:
        if c.compare_as is not None:
            raise IRError("compare_as_unsupported", f"{rule.id}: {where} has no lowering of compare_as {c.compare_as}")
    return rule.conditions


def closes_check(closing, closed):
    """The name of the invariant the compiler generates for `// @closes`: the keys that hold
    in the closing relation and in the relation it closes."""
    return f"{closing}_closes_{closed}"


def iso_date(text):
    """Whether a text is a calendar day written YYYY-MM-DD."""
    import datetime
    try:
        return bool(ISO_DATE.match(text)) and datetime.date.fromisoformat(text) is not None
    except ValueError:
        return False


def days(left, right):
    """The whole number of days from the ISO date `right` to the ISO date `left`; None if either is no day."""
    import datetime
    if not (iso_date(left) and iso_date(right)):
        return None
    return datetime.date.fromisoformat(left).toordinal() - datetime.date.fromisoformat(right).toordinal()


def calc_input_table(selection):
    """The engine's typed input view of a published calculation selection."""
    return f"rule_calc_input__{selection.removeprefix('calc__')}"


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Relation:
    name: str
    role: str
    key: tuple
    values: tuple = ()
    module: str | None = None
    explain: str | None = None
    invariant: bool = False  # must be empty at the end of an epoch
    world: str = "closed"  # a missing row is not true (closed) or unknown (open)
    absence: bool = False  # @absence: about what is recorded, so closed; may negate an open relation
    outcome: str | None = None  # @outcome <kind>: one state and reason per element of that kind
    extend: bool = False  # consumers may add rules; without any, this relation is the empty set
    closes: str | None = None  # @closes <relation>: a row says that no row of that relation holds at its key
    domain: str | None = None  # functional: mandatory closed finite domain relation
    value: Column | None = None  # functional: single typed value column co-located with state and reason
    conflict_policy: str | None = None  # functional: "publish" or "block"
    empty_state: str | None = None  # functional: "unknown" (default) or "not_applicable"
    empty_reason: str | None = None  # functional: reason code when zero candidates match

    @property
    def head_columns(self) -> tuple:
        """Columns produced by a rule whose head is this relation."""
        if self.role == "functional":
            return self.key + (self.value,)
        return self.key

    @property
    def row_columns(self) -> tuple:
        """Columns exposed when another rule reads this relation."""
        if self.role == "functional":
            return self.key + (Column("state", "string"), Column("reason", "string"), self.value)
        return self.key


@dataclass(frozen=True)
class Atom:
    relation: str
    terms: tuple


@dataclass(frozen=True)
class Literal:
    atom: Atom
    polarity: str
    stratum: int


@dataclass(frozen=True)
class Aggregate:
    atom: Atom
    function: str
    over: str | None
    var: str
    stratum: int


@dataclass(frozen=True)
class Condition:
    op: str
    left: str
    right: str
    compare_as: str | None = None


@dataclass(frozen=True)
class Assignment:
    var: str
    op: str
    left: str
    right: str


@dataclass(frozen=True)
class Rule:
    id: str
    module: str
    stratum: int
    head: Atom
    body: tuple
    aggregates: tuple = ()
    conditions: tuple = ()
    assignments: tuple = ()
    origin: tuple = ("", 0)

    @property
    def variables(self):
        """Every variable of the rule, sorted: the columns of its witness relation."""
        atoms = (self.head, *(b.atom for b in self.body), *(a.atom for a in self.aggregates))
        vs = {t for a in atoms for t in a.terms if is_var(t)}
        vs |= {a.var for a in self.aggregates} | {s.var for s in self.assignments}
        vs |= {t for c in self.conditions for t in (c.left, c.right) if is_var(t)}
        return tuple(sorted(vs))

    @property
    def witness_relation(self):
        return f"{self.id}__witness"

    @property
    def projects(self):
        """True if a variable of a positive literal is not in the head: one conclusion may then have as
        many witnesses as source rows (the degree), so its witnesses are better found on demand."""
        head = {t for t in self.head.terms if is_var(t)}
        return any(is_var(t) and t not in head for b in self.body if b.polarity == "positive" for t in b.atom.terms)


@dataclass(frozen=True)
class Bound:
    """A recursive rule that counts to an explicit bound. The rule reads its own relation once,
    adds `step` to the counter in key column `column` and fires while the counter it reads is at most `last`;
    every other rule of the relation starts the counter at a constant, `start` the least. So the rule is
    applied `levels` times at most, on every input, and the recursion unrolls into that many strata."""
    rule: str
    column: int
    counter: str
    start: int
    step: int
    last: int
    levels: int


@dataclass
class Program:
    pack: str
    relations: dict
    rules: dict
    strata: dict = field(default_factory=dict)
    seals: list = field(default_factory=list)  # the sealed kinds and the tables of the seal
    bounds: dict = field(default_factory=dict)  # relation -> Bound: a counter the translator unrolls (P6.2)
    format: str = FORMAT

    def rules_for(self, relation):
        return [r for r in self.rules.values() if r.head.relation == relation]

    def derived(self):
        """Derived and functional relations in evaluation order: by stratum, then by dependency, then by name."""
        order, seen = [], set()

        def visit(name, path=()):
            if name in seen or self.relations[name].role not in ("derived", "functional"):
                return
            for dep in sorted(self.deps(name)):
                if dep != name and dep not in path:
                    visit(dep, path + (name,))
            if name not in seen:
                seen.add(name)
                order.append(name)

        for name in sorted(self.relations, key=lambda n: (self.strata.get(n, 0), n)):
            visit(name)
        return order

    def deps(self, relation):
        out = set()
        for r in self.rules_for(relation):
            out |= {b.atom.relation for b in r.body} | {a.atom.relation for a in r.aggregates}
        rel = self.relations[relation]
        if rel.outcome:  # its checks read every element of the kind
            out.add(rel.outcome)
        if rel.domain:  # a functional derivation always depends on its closed domain
            out.add(rel.domain)
        return out

    def recursive(self, relation):
        """True if the relation depends on itself, directly or through other relations."""
        return any(self.reaches(relation, d) for d in self.deps(relation))

    def module_groups(self):
        """Rule modules in dependency order, as groups that depend on each other (one group per cycle).

        Ties go to the module whose first relation comes first in evaluation order, then by name.
        """
        order = self.derived()
        first = {}
        for i, n in enumerate(order):
            first.setdefault(self.relations[n].module, i)
        uses = {m: set() for m in first}
        for n in order:
            m = self.relations[n].module
            uses[m] |= {self.relations[d].module for d in self.deps(n)
                        if self.relations[d].role in ("derived", "functional") and self.relations[d].module != m}
        # strongly connected components (Tarjan), then their dependency order
        index, low, stack, on, comps = {}, {}, [], set(), []

        def visit(m):
            index[m] = low[m] = len(index)
            stack.append(m)
            on.add(m)
            for u in sorted(uses[m]):
                if u not in index:
                    visit(u)
                    low[m] = min(low[m], low[u])
                elif u in on:
                    low[m] = min(low[m], index[u])
            if low[m] == index[m]:
                comp = []
                while True:
                    u = stack.pop()
                    on.discard(u)
                    comp.append(u)
                    if u == m:
                        break
                comps.append(sorted(comp, key=lambda x: (first[x], x)))

        for m in sorted(first, key=lambda x: (first[x], x)):
            if m not in index:
                visit(m)
        of = {m: i for i, c in enumerate(comps) for m in c}
        needs = {i: {of[u] for m in c for u in uses[m]} - {i} for i, c in enumerate(comps)}
        done, out = set(), []
        while len(out) < len(comps):
            ready = [i for i in range(len(comps)) if i not in done and needs[i] <= done]
            i = min(ready, key=lambda i: (first[comps[i][0]], comps[i][0]))
            done.add(i)
            out.append(comps[i])
        return out

    def modules(self):
        """Rule modules in dependency order."""
        return [m for group in self.module_groups() for m in group]

    def base_used(self):
        """Base relations that some rule or functional domain reads, sorted."""
        return sorted({x.atom.relation for r in self.rules.values() for x in (*r.body, *r.aggregates)
                       if self.relations[x.atom.relation].role == "base"}
                      | {r.outcome for r in self.relations.values() if r.outcome}
                      | {r.domain for r in self.relations.values()
                         if r.domain and self.relations[r.domain].role == "base"})

    def reaches(self, start, target):
        """True if `target` depends on `start` (directly or through other rules), or they are equal."""
        seen, todo = set(), [target]
        while todo:
            n = todo.pop()
            if n == start:
                return True
            if n not in seen:
                seen.add(n)
                todo.extend(self.deps(n))
        return False

    def downstream(self, changed):
        """Derived and functional relations that can change when the relations in `changed` change."""
        out, todo = set(), set(changed)
        while todo:
            n = todo.pop()
            for d in self.relations:
                if d not in out and self.relations[d].role in ("derived", "functional") and n in self.deps(d):
                    out.add(d)
                    todo.add(d)
        return out

    def partition_at_calc(self, outputs, reads):
        """Order rule relations on each side of one calculation phase."""
        after = self.downstream(outputs)
        if cycle := after.intersection(reads):
            raise IRError("rule_calc_cycle", f"calculation reads its downstream relations: {', '.join(sorted(cycle))}")
        for rule in sorted(self.rules.values(), key=lambda rule: rule.id):
            if any(literal.polarity == "negative" and literal.atom.relation in after for literal in rule.body) or any(
                aggregate.atom.relation in after for aggregate in rule.aggregates
            ):
                raise IRError("calc_not_known_positive", f"{rule.id}: a calculation-dependent relation is read positively")
        order = self.derived()
        return [name for name in order if name not in after], [name for name in order if name in after]

    def calc_inputs(self):
        """Calculation selections used as typed rule inputs, in stable name order."""
        return sorted(r.name for r in self.relations.values() if r.role == "calc")


def _nat(doc, where):
    s = doc if isinstance(doc, str) else None
    if s is None or not NAT.match(s):
        raise IRError("not_decimal_text", f"{where}: integers are decimal text, got {doc!r}")
    return int(s)


def _atom(doc, where):
    terms = doc.get("terms", [])
    if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
        raise IRError("bad_term", f"{where}: terms are strings")
    for t in terms:
        if t.startswith("?") and not VAR.match(t):
            raise IRError("bad_variable", f"{where}: {t}")
    return Atom(doc["relation"], tuple(terms))


def load(doc, require_witness=True):
    """Read and check a rule program (a dict from YAML or JSON). Raises IRError."""
    fmt = doc.get("format")
    if fmt not in FORMATS:
        raise IRError("bad_format", f"format must be one of {', '.join(FORMATS)}")
    relations, declared = {}, {}
    for r in doc.get("relations", []):
        name = r["name"]
        role = r["role"]
        if not REL_NAME.match(name) or (role in ("derived", "functional") and not NAME.match(name)):
            raise IRError("bad_name", name)
        if name in relations:
            raise IRError("duplicate_relation", name)
        cols = tuple(Column(c["name"], c["type"]) for c in r.get("key", []))
        vals = tuple(Column(c["name"], c["type"]) for c in r.get("values", []))
        for c in cols + vals:
            if c.type not in TYPES or not NAME.match(c.name):
                raise IRError("bad_column", f"{name}.{c.name}")
        if len({c.name for c in cols + vals}) != len(cols + vals):
            raise IRError("bad_column", f"{name}: duplicate column")
        if role not in ("base", "calc", "derived", "functional"):
            raise IRError("bad_role", name)
        if role == "functional" and fmt != FORMAT_V2:
            raise IRError("bad_role", f"{name}: role 'functional' requires format {FORMAT_V2}")
        if not cols:
            raise IRError("no_columns", f"{name}: a relation needs at least one key column")
        if role == "calc":
            subject_type = cols[0].type
            expected = (Column("subject", subject_type), Column("value", "integer"),
                        Column("state", "string"), Column("reason", "string"))
            if (not name.startswith("calc__") or "__" in name.removeprefix("calc__")
                    or cols != expected or vals or r.get("world") != "open" or r.get("module") or r.get("explain")):
                raise IRError("bad_calc_input", f"{name}: a calculation selection has open subject, integer value, state and reason")
        if role in ("derived", "functional") and vals:
            raise IRError("derived_values", f"{name}: a {role} relation has no base value columns")
        invariant = r.get("invariant", False)
        if invariant not in (True, False) or (invariant and role != "derived"):
            raise IRError("bad_invariant", f"{name}: invariant is true or false, on a derived relation")
        absence = r.get("absence", False)
        if absence not in (True, False) or (absence and role != "derived"):
            raise IRError("bad_absence", f"{name}: absence is true or false, on a derived relation")
        if "release" in r:
            raise IRError("release_unsupported", f"{name}: release is not supported yet: a role reads a negation or an aggregate only over relations it reads in full (docs/formal.md, section 3; decisions/language-native-rules.md: delimited release stays reserved)")
        if r.get("world", "closed") not in WORLDS:
            raise IRError("bad_world", f"{name}: world is one of {WORLDS}")
        outcome = r.get("outcome")
        if outcome is not None and (role != "derived" or len(cols) != 3 or [c.name for c in cols[1:]] != ["state", "reason"]
                                    or any(c.type != "string" for c in cols[1:])):
            raise IRError("bad_outcome", f"{name}: an outcome is derived, with three columns: the element, "
                                         "state and reason (text)")
        extend = r.get("extend", False)
        if type(extend) is not bool or (extend and role != "derived"):
            raise IRError("bad_extend", f"{name}: extend is a boolean on a derived relation")
        closes = r.get("closes")
        if closes is not None and (not isinstance(closes, str) or role != "derived" or invariant
                                   or outcome is not None or closes == name):
            raise IRError("bad_closes", f"{name}: closes names another derived relation, on a derived relation "
                                        "that is no invariant and no outcome")
        domain = r.get("domain")
        raw_value = r.get("value")
        conflict_policy = r.get("conflict_policy")
        empty_state = r.get("empty_state")
        empty_reason = r.get("empty_reason")
        value_col = None
        if role == "functional":
            if r.get("world") == "open":
                raise IRError("functional_open_domain", f"{name}: a functional derivation is always closed")
            if not isinstance(domain, str) or not REL_NAME.match(domain):
                raise IRError("bad_domain", f"{name}: a functional derivation requires a finite closed domain relation")
            if not isinstance(raw_value, dict) or not isinstance(raw_value.get("name"), str) or not isinstance(raw_value.get("type"), str):
                raise IRError("bad_column", f"{name}: a functional derivation requires a typed value column")
            value_col = Column(raw_value["name"], raw_value["type"])
            if value_col.type not in TYPES or not NAME.match(value_col.name):
                raise IRError("bad_column", f"{name}.{value_col.name}")
            reserved = {"state", "reason"}
            if any(c.name in reserved for c in cols) or value_col.name in reserved or value_col.name in {c.name for c in cols}:
                raise IRError("bad_column", f"{name}: key/value columns conflict with co-located (state, reason, value)")
            if conflict_policy not in CONFLICT_POLICIES:
                raise IRError("bad_conflict_policy", f"{name}: conflict_policy must be one of {CONFLICT_POLICIES}")
            if empty_state is not None and empty_state not in EMPTY_STATES:
                raise IRError("bad_empty_state", f"{name}: empty_state must be one of {EMPTY_STATES}")
            if empty_reason is not None and (not isinstance(empty_reason, str) or not NAME.match(empty_reason)):
                raise IRError("bad_empty_reason", f"{name}: empty_reason must be a snake_case reason code")
        elif any(x is not None for x in (domain, raw_value, conflict_policy, empty_state, empty_reason)):
            raise IRError("bad_functional_field", f"{name}: domain/value/conflict_policy are only allowed on functional relations")
        declared[name] = r.get("world")
        relations[name] = Relation(name, role, cols, vals, r.get("module"), r.get("explain"), invariant,
                                   r.get("world") or "closed", absence, outcome, extend, closes,
                                   domain, value_col, conflict_policy, empty_state, empty_reason)
    for name, rel in relations.items():
        if rel.closes is not None:
            closed = relations.get(rel.closes)
            if closed is None or closed.role != "derived":
                raise IRError("bad_closes", f"{name}: {rel.closes} is not a derived relation")
            if [c.type for c in closed.key[:len(rel.key)]] != [c.type for c in rel.key]:
                raise IRError("bad_closes", f"{name}: its columns are, by position and type, a prefix of those of "
                                            f"{rel.closes}")
        if rel.role == "functional":
            dom = relations.get(rel.domain)
            if dom is None or dom.role not in ("base", "derived") or dom.name == name:
                raise IRError("bad_domain", f"{name}: domain {rel.domain!r} must name a base or derived relation")
            if [c.type for c in dom.key] != [c.type for c in rel.key]:
                raise IRError("bad_domain", f"{name}: domain {rel.domain} key columns must match functional key exactly")

    rules = {}
    for d in doc.get("rules", []):
        rid = d["id"]
        if not NAME.match(rid):
            raise IRError("bad_name", rid)
        if rid in rules:
            raise IRError("duplicate_rule", rid)
        rule = Rule(
            id=rid,
            module=d["module"],
            stratum=_nat(d["stratum"], rid),
            head=_atom(d["head"], rid),
            body=tuple(Literal(_atom(b, rid), b["polarity"], _nat(b["stratum"], rid)) for b in d.get("body", [])),
            aggregates=tuple(Aggregate(_atom(a, rid), a["function"], a.get("over"), a["as"], _nat(a["stratum"], rid))
                             for a in d.get("aggregates", [])),
            conditions=tuple(Condition(c["op"], c["left"], c["right"], c.get("compare_as"))
                             for c in d.get("conditions", [])),
            assignments=tuple(Assignment(s["var"], s["op"], s["left"], s["right"]) for s in d.get("assignments", [])),
            origin=(d["origin"]["file"], _nat(d["origin"]["line"], rid)),
        )
        _check_rule(rule, relations, fmt=fmt)
        rules[rid] = rule
        w = d.get("witness")
        if w is None and require_witness:
            raise IRError("missing_witness", rid)
        if w is not None and (w.get("relation") != rule.witness_relation or tuple(w.get("variables", ())) != rule.variables):
            raise IRError("bad_witness", f"{rid}: witness is {rule.witness_relation}{list(rule.variables)}")

    prog = Program(doc.get("pack", ""), relations, rules, seals=[dict(s) for s in doc.get("seals", [])], format=fmt)
    for name, rel in relations.items():
        if rel.role in ("derived", "functional") and not rel.extend and not prog.rules_for(name):
            raise IRError("no_rules", name)
    prog.strata = _stratify(prog)
    prog.relations = _worlds(prog, declared)
    _check_access_boundary(prog)
    _check_outcomes(prog)
    _check_closes(prog)
    return prog


def _check_access_boundary(prog):
    """Neither may_read nor may_read_full may depend (directly or transitively) on a functional derivation
    or a calculation selection (decisions/language-rezono-1.md, section 4)."""
    calc_rels = {n for n, r in prog.relations.items() if r.role == "calc"}
    if calc_rels:
        after_calc = prog.downstream(calc_rels)
        for access_rel in ACCESS_RELATIONS:
            if access_rel in after_calc:
                raise IRError("access_depends_on_calc",
                              f"{access_rel} cannot depend on a calculation selection")
    func_rels = {n for n, r in prog.relations.items() if r.role == "functional"}
    if func_rels:
        after_func = prog.downstream(func_rels)
        for access_rel in ACCESS_RELATIONS:
            if access_rel in after_func:
                raise IRError("access_depends_on_functional",
                              f"{access_rel} cannot depend on a functional derivation")


def _check_closes(prog):
    """A relation that closes another has its generated invariant, `closes_check`, with exactly
    one rule: the closing row and a row of the closed relation at the same key, its other columns free. So a
    program that says `closes` cannot leave out the check that the two never hold together, or weaken it."""
    for name, rel in sorted(prog.relations.items()):
        if rel.closes is None:
            continue
        check = closes_check(name, rel.closes)
        found, rules = prog.relations.get(check), prog.rules_for(check)
        ok = (found is not None and found.invariant and len(rules) == 1
              and [c.type for c in found.key] == [c.type for c in rel.key])
        if ok:
            (rule,), n = rules, len(rel.key)
            lits = {b.atom.relation: b.atom.terms for b in rule.body if b.polarity == "positive"}
            head, rest = rule.head.terms, lits.get(rel.closes, ())[n:]
            ok = (len(rule.body) == 2 and set(lits) == {name, rel.closes}
                  and not (rule.aggregates or rule.conditions or rule.assignments)
                  and all(is_var(t) for t in head + rest) and len(set(head + rest)) == len(head + rest)
                  and lits[name] == head and lits[rel.closes][:n] == head)
        if not ok:
            raise IRError("bad_closes", f"{name}: closes {rel.closes} needs the invariant {check} with one rule: "
                                        f"a row of {name} and a row of {rel.closes} at the same key")


def _check_outcomes(prog):
    """An outcome reads its kind's elements, states are constants, a known row has the reason
    "", and the outcome is closed (its totality is checked, so it cannot leave anything unknown by omission)."""
    for name, rel in sorted(prog.relations.items()):
        if rel.outcome is None:
            continue
        kind = prog.relations.get(rel.outcome)
        if kind is None or kind.role != "base" or len(kind.key) != 1 or kind.key[0].type != rel.key[0].type:
            raise IRError("bad_outcome", f"{name}: {rel.outcome} is not a kind whose id type is that of {rel.key[0].name}")
        if rel.world != "closed":
            raise IRError("bad_outcome", f"{name}: an outcome must be closed; a rule reads an open relation positively")
        for r in prog.rules_for(name):
            _, state, reason = r.head.terms
            if is_var(state) or state not in STATES:
                raise IRError("bad_outcome", f"{r.id}: the state is a constant, one of {', '.join(STATES)}")
            if is_var(reason) or (state == "known") != (reason == "") or (reason and not NAME.match(reason)):
                raise IRError("bad_outcome", f"{r.id}: the reason is a constant: \"\" for known, otherwise a name "
                                             "in lower snake case (its message is reason.<reason>)")


def _check_rule(rule, relations, *, fmt=FORMAT):
    bounds = integer_bounds(fmt)

    def rel(atom, *, is_head=False):
        r = relations.get(atom.relation)
        if r is None:
            raise IRError("unknown_relation", f"{rule.id}: {atom.relation}")
        cols = r.head_columns if is_head else r.row_columns
        if len(atom.terms) != len(cols):
            raise IRError("arity", f"{rule.id}: {atom.relation} has {len(cols)} columns")
        return r

    def check_const(t, col):
        if t == "_" or is_var(t):
            return
        if col.type == "integer" and not INT.match(t):
            raise IRError("bad_constant", f"{rule.id}: {t!r} is not an integer")
        if col.type == "integer":
            fits(t)
        if col.type == "rational" and not is_rational(t, bounds=bounds):
            raise IRError("bad_constant", f"{rule.id}: {t!r} is not a canonical rational")
        if col.type == "boolean" and t not in BOOLEAN:
            raise IRError("bad_constant", f"{rule.id}: {t!r} is not a boolean")
        if col.type == "date":
            raise IRError("bad_constant", f"{rule.id}: {t!r} is not allowed in a date column")

    def fits(t):
        if not bounds[0] <= int(t) <= bounds[1]:
            limit = f"symmetric 64-bit bound (+/-{BOUND})" if fmt == FORMAT_V2 else "a BIGINT"
            raise IRError("constant_out_of_range", f"{rule.id}: {t} does not fit {limit}")

    head = rel(rule.head, is_head=True)
    if head.role not in ("derived", "functional"):
        raise IRError("head_is_base", f"{rule.id}: {rule.head.relation}")
    if head.module != rule.module:
        raise IRError("module_mismatch", f"{rule.id}: {rule.head.relation} belongs to module {head.module}")
    types = {}

    def bind(t, col):
        if is_var(t):
            if types.setdefault(t, col.type) != col.type:
                raise IRError("type_mismatch", f"{rule.id}: {t} is {types[t]} and {col.type}")

    for b in rule.body:
        r = rel(b.atom)
        if b.polarity not in ("positive", "negative"):
            raise IRError("bad_polarity", f"{rule.id}: {b.polarity}")
        if r.role == "calc" and (b.polarity != "positive" or b.atom.terms[2:] != ("known", "")):
            raise IRError("calc_not_known_positive", f"{rule.id}: read {r.name} positively with state 'known' and empty reason")
        for t, c in zip(b.atom.terms, r.row_columns):
            if t == "_":
                raise IRError("wildcard_outside_aggregate", rule.id)
            check_const(t, c)
            if b.polarity == "positive":
                bind(t, c)
    positive = set(types)   # safety: negation and aggregate keys may only use these
    bound = set(positive)   # plus aggregate results and assignments, for conditions, assignments and the head
    # A body of aggregates only is a rule: a count or a sum over a whole relation has no group key,
    # so nothing has to bind one. An empty body, and a body of negations only, has nothing to range over.
    if not (rule.aggregates if not rule.body else any(b.polarity == "positive" for b in rule.body)):
        raise IRError("no_positive_literal", f"{rule.id}: a body has a positive literal, or only aggregates")
    for a in rule.aggregates:
        r = rel(a.atom)
        if r.role == "calc":
            raise IRError("calc_aggregate", f"{rule.id}: cannot aggregate over {r.name}")
        if a.function not in FUNCTIONS:
            raise IRError("bad_aggregate", f"{rule.id}: {a.function}")
        if a.function == "count" and a.over is not None:
            raise IRError("bad_aggregate", f"{rule.id}: count has no 'over'")
        if a.function != "count":
            col = next((c for c in r.values if c.name == a.over), None)
            if col is None:   # or a key/row column the aggregate ranges over
                col = next((c for c, t in zip(r.row_columns, a.atom.terms) if c.name == a.over and t == "_"), None)
            if col is None or col.type != "integer":
                raise IRError("bad_aggregate", f"{rule.id}: 'over' must name an integer value column of {r.name}, "
                                               "or an integer key column whose term is '_'")
        for t, c in zip(a.atom.terms, r.row_columns):
            check_const(t, c)
            if is_var(t):
                if t not in positive:
                    raise IRError("unsafe_variable", f"{rule.id}: {t} in an aggregate is not bound by a positive literal")
                if types[t] != c.type:
                    raise IRError("type_mismatch", f"{rule.id}: {t} is {types[t]}, {r.name}.{c.name} is {c.type}")
        if not VAR.match(a.var) or a.var in bound:
            raise IRError("bad_aggregate", f"{rule.id}: result {a.var} must be a fresh variable")
        bound.add(a.var)
        types[a.var] = "integer"
    for s in rule.assignments:
        if s.op == DAYS:
            if s.var in bound or not VAR.match(s.var) or s.left not in positive or types[s.left] != "string" \
                    or not iso_date(s.right):
                raise IRError("bad_assignment", f"{rule.id}: {s}: days reads a text variable of a positive literal "
                                                "and counts from a constant ISO date")
            bound.add(s.var)
            types[s.var] = "integer"
            continue
        if s.op not in ARITHMETIC or s.var in bound or not VAR.match(s.var):
            raise IRError("bad_assignment", f"{rule.id}: {s}")
        for t in (s.left, s.right):
            if (is_var(t) and (t not in bound or types[t] != "integer")) or (not is_var(t) and not INT.match(t)):
                raise IRError("bad_assignment", f"{rule.id}: {t} is not a bound integer")
            if not is_var(t):
                fits(t)
        if s.op == "div" and is_var(s.right):
            raise IRError("divisor_not_constant", f"{rule.id}: {s.var} = {s.left} / {s.right}: the divisor is an integer "
                                                  "constant, so that no engine ever divides by zero")
        if s.op == "div" and int(s.right) == 0:
            raise IRError("division_by_zero", f"{rule.id}: {s.var} = {s.left} / 0")
        bound.add(s.var)
        types[s.var] = "integer"
    for c in rule.conditions:
        if c.op not in COMPARISONS:
            raise IRError("bad_condition", f"{rule.id}: {c.op}")
        for t in (c.left, c.right):
            if is_var(t) and t not in bound:
                raise IRError("unsafe_variable", f"{rule.id}: {t} in a condition is not bound")
        if c.compare_as is not None:
            if c.compare_as not in COMPARE_AS:
                raise IRError("bad_condition", f"{rule.id}: compare_as {c.compare_as!r}")
            for t in (c.left, c.right):
                if not is_var(t) or t not in positive or types[t] != "string":
                    raise IRError("bad_condition", f"{rule.id}: {c.compare_as} compares two text variables "
                                                   f"bound by positive literals, not {t}")
            continue
        kinds = {types[t] for t in (c.left, c.right) if is_var(t)}
        if not kinds:  # two constants: typed by their own form
            kinds = {const_type(t) for t in (c.left, c.right)}
        if c.op not in ("eq", "ne") and kinds not in ({"integer"}, {"rational"}):
            raise IRError("bad_condition", f"{rule.id}: order comparisons need integers or rationals")
        if len(kinds) > 1:
            raise IRError("type_mismatch", f"{rule.id}: {c.left} and {c.right} have different types")
        for t in (c.left, c.right):
            if not is_var(t) and kinds == {"boolean"} and t not in BOOLEAN:
                raise IRError("bad_constant", f"{rule.id}: {t!r} is compared with a boolean")
            if not is_var(t) and kinds == {"date"}:
                raise IRError("bad_constant", f"{rule.id}: {t!r} is compared with a date")
            if not is_var(t) and kinds == {"integer"} and not INT.match(t):
                raise IRError("bad_constant", f"{rule.id}: {t!r} is compared with an integer")
            if not is_var(t) and kinds == {"integer"}:
                fits(t)
            if not is_var(t) and kinds == {"rational"} and not is_rational(t, bounds=bounds):
                raise IRError("bad_constant", f"{rule.id}: {t!r} is compared with a rational")
    for b in rule.body:
        if b.polarity == "negative":
            for t, c in zip(b.atom.terms, relations[b.atom.relation].row_columns):
                if is_var(t):
                    if t not in positive:
                        raise IRError("unsafe_variable", f"{rule.id}: {t} in a negation is not bound by a positive literal")
                    if types[t] != c.type:
                        raise IRError("type_mismatch", f"{rule.id}: {t} is {types[t]}, {b.atom.relation}.{c.name} is {c.type}")
    for t, c in zip(rule.head.terms, head.head_columns):
        if t == "_":
            raise IRError("wildcard_outside_aggregate", rule.id)
        check_const(t, c)
        if is_var(t):
            if t not in bound:
                raise IRError("unsafe_variable", f"{rule.id}: head variable {t} is not bound")
            if types[t] != c.type:
                raise IRError("type_mismatch", f"{rule.id}: {t} is {types[t]}, {head.name}.{c.name} is {c.type}")


def _stratify(prog):
    """Least strata: positive edges >=, negative, aggregate, and functional-head/domain edges >.
    Declared strata must agree (exact least strata in rezono.rules/1; valid consistent stratification
    in rezono.rules/2).

    A cycle through negation, aggregation, or a functional derivation has no solution: not stratified.
    """
    strata = {n: 0 for n in prog.relations}
    limit = len(prog.relations)   # a stratified program never needs more strata than relations
    changed = True
    while changed:                # until a fixpoint; a cycle through negation/functional grows without bound
        changed = False
        for n, rel in prog.relations.items():
            if rel.role == "functional":
                need = max(strata[rel.domain] + 1, 1)
                if strata[n] < need:
                    strata[n] = need
                    changed = True
                    if need > limit:
                        raise IRError("not_stratified", f"{n}: cycle through functional derivation")
        for r in prog.rules.values():
            h = r.head.relation
            is_func = prog.relations[h].role == "functional"
            need = max(
                [strata[b.atom.relation] + (1 if is_func or b.polarity == "negative" else 0) for b in r.body]
                + [strata[a.atom.relation] + 1 for a in r.aggregates]
                + ([strata[prog.relations[h].domain] + 1] if is_func else [])
                + [1]
            )
            if strata[h] < need:
                strata[h] = need
                changed = True
                if need > limit:
                    raise IRError("not_stratified", f"{h}: negation, aggregation, or functional derivation through recursion")
    for r in prog.rules.values():
        if r.assignments and any(prog.reaches(r.head.relation, b.atom.relation) for b in r.body):
            prog.bounds[r.head.relation] = _bound(prog, r)
    if prog.format == FORMAT:
        for r in prog.rules.values():
            if r.stratum != strata[r.head.relation]:
                raise IRError("wrong_stratum", f"{r.id}: stratum {r.stratum}, derived {strata[r.head.relation]}")
            for b in r.body:
                if b.stratum != strata[b.atom.relation]:
                    raise IRError("wrong_stratum", f"{r.id}: {b.atom.relation} is in stratum {strata[b.atom.relation]}")
            for a in r.aggregates:
                if a.stratum != strata[a.atom.relation]:
                    raise IRError("wrong_stratum", f"{r.id}: {a.atom.relation} is in stratum {strata[a.atom.relation]}")
        return strata

    # rezono.rules/2: allow any valid per-derivation stratification consistent with all dependency edges.
    declared = {n: 0 for n, rel in prog.relations.items() if rel.role in ("base", "calc")}
    for r in prog.rules.values():
        h = r.head.relation
        if h in declared and declared[h] != r.stratum:
            raise IRError("wrong_stratum", f"{r.id}: stratum {r.stratum} disagrees with {declared[h]} for {h}")
        declared[h] = r.stratum
    for n in prog.relations:
        declared.setdefault(n, strata[n])
    for n, rel in prog.relations.items():
        if rel.role == "functional" and declared[n] <= declared[rel.domain]:
            raise IRError("wrong_stratum", f"{n}: functional stratum {declared[n]} must exceed domain {rel.domain} ({declared[rel.domain]})")
    for r in prog.rules.values():
        h = r.head.relation
        is_func = prog.relations[h].role == "functional"
        if r.stratum < strata[h]:
            raise IRError("wrong_stratum", f"{r.id}: stratum {r.stratum}, minimum {strata[h]}")
        for b in r.body:
            if b.stratum != declared[b.atom.relation]:
                raise IRError("wrong_stratum", f"{r.id}: {b.atom.relation} is in stratum {declared[b.atom.relation]}")
            min_h = declared[b.atom.relation] + (1 if is_func or b.polarity == "negative" else 0)
            if r.stratum < min_h:
                raise IRError("wrong_stratum", f"{r.id}: stratum {r.stratum} too low for {b.atom.relation} ({declared[b.atom.relation]})")
        for a in r.aggregates:
            if a.stratum != declared[a.atom.relation]:
                raise IRError("wrong_stratum", f"{r.id}: {a.atom.relation} is in stratum {declared[a.atom.relation]}")
            if r.stratum <= declared[a.atom.relation]:
                raise IRError("wrong_stratum", f"{r.id}: stratum {r.stratum} must exceed aggregate {a.atom.relation} ({declared[a.atom.relation]})")
    return declared


def upper(condition, var):
    """The greatest value `var` may have under a condition that bounds it above by a constant, else None."""
    c = condition
    if c.left == var and c.op in ("lt", "le") and INT.match(c.right):
        return int(c.right) - (c.op == "lt")
    if c.right == var and c.op in ("gt", "ge") and INT.match(c.left):
        return int(c.left) - (c.op == "gt")
    return None


def _bound(prog, r):
    """The bound of a recursive rule with arithmetic. Arithmetic in recursion need not terminate,
    so one shape only is taken: a counter. The rule reads its own relation once and nothing else that depends
    on it; one key column of that row is a variable the rule adds a positive constant to, the sum is the same
    column of the head, and a condition bounds what is read from above by a constant; every other rule of the
    relation puts a constant in that column and does not depend on the relation. Then the count is finite on
    every input, and known here. Anything else is refused as before."""
    h = r.head.relation

    def refused(why):
        return IRError("recursive_assignment", f"{r.id}: arithmetic in a recursive rule need not terminate; only a "
                                               f"counter with an explicit bound is unrolled, and {why}")

    own = [b for b in r.body if b.atom.relation == h]
    if len(own) != 1 or own[0].polarity != "positive" or any(
            b.atom.relation != h and prog.reaches(h, b.atom.relation) for b in r.body):
        raise refused(f"this rule does not read {h} exactly once, with nothing else that depends on {h}")
    start = [x for x in prog.rules_for(h) if x is not r]
    if not start or any(prog.reaches(h, b.atom.relation) for x in start for b in x.body):
        raise refused(f"{h} has no other rule, or one that depends on {h} too: the count starts nowhere")
    why = f"no key column of {h} is a variable here that the rule adds a positive constant to for the head"
    for j, (n, m) in enumerate(zip(own[0].atom.terms, r.head.terms)):
        steps = [s.right if s.left == n else s.left for s in r.assignments
                 if s.var == m and s.op == "add" and is_var(n) and (s.left == n) != (s.right == n)]
        if not steps or is_var(steps[0]) or int(steps[0]) <= 0:
            continue
        lasts = [u for u in (upper(c, n) for c in r.conditions) if u is not None]
        if not lasts:
            why = f"no condition bounds {n} from above by a constant (write {n[1:]} < 12)"
            continue
        if any(is_var(x.head.terms[j]) for x in start):
            why = f"another rule of {h} does not start {m[1:]} at a constant"
            continue
        first, step, last = min(int(x.head.terms[j]) for x in start), int(steps[0]), min(lasts)
        levels = (last - first) // step + 1 if last >= first else 0
        if levels > MAX_LEVELS:
            raise refused(f"counting from {first} to {last} by {step} takes {levels} strata, more than the "
                          f"{MAX_LEVELS} a rule is unrolled into")
        return Bound(r.id, j, n, first, step, last, levels)
    raise refused(why)


def _worlds(prog, declared):
    """A base relation has the world the schema gives it. A derived relation is open if a rule
    reads an open relation positively; an @absence relation is closed. Negation over an open relation, and an
    aggregate over one (a count of what is recorded), is an error, except in an @absence relation; a rule of an
    @absence relation must negate an open relation, aggregate over one, or read another @absence relation.
    A declared world of a derived relation must agree."""
    rels = prog.relations
    opened = {n for n, r in rels.items() if r.role not in ("derived", "functional") and r.world == "open"}
    changed = True
    while changed:
        changed = False
        for r in prog.rules.values():
            h = r.head.relation
            if h in opened or rels[h].absence or rels[h].role == "functional":
                continue
            reads = [b.atom.relation for b in r.body if b.polarity == "positive"]
            if any(x in opened for x in reads):
                opened.add(h)
                changed = True
    for r in sorted(prog.rules.values(), key=lambda r: r.id):
        h = rels[r.head.relation]
        for b in r.body:
            if b.polarity == "negative" and b.atom.relation in opened and not h.absence:
                raise IRError("negation_over_open", f"{r.id}: {b.atom.relation} is open, so a missing row is unknown, "
                                                    "not false; negate it only in a relation marked @absence")
            if b.polarity == "positive" and b.atom.relation in opened and h.role == "functional":
                raise IRError("functional_reads_open", f"{r.id}: {b.atom.relation} is open, so its missing values are "
                                                       "unknown; a functional derivation cannot read it positively")
        for a in r.aggregates:
            if a.atom.relation in opened and not h.absence:
                raise IRError("aggregate_over_open", f"{r.id}: {a.atom.relation} is open, so its count or sum is only "
                                                     "what is recorded; aggregate over it only in a relation marked @absence")
        if h.absence and not any((b.polarity == "negative" and b.atom.relation in opened)
                                 or (b.polarity == "positive" and b.atom.relation != h.name and rels[b.atom.relation].absence)
                                 for b in r.body) and not any(a.atom.relation in opened for a in r.aggregates):
            raise IRError("bad_absence", f"{r.id}: a rule of an @absence relation negates an open relation "
                                         "or reads another @absence relation")
    out = {}
    for n, rel in rels.items():
        w = "open" if n in opened else "closed"
        if rel.role == "derived" and declared.get(n) not in (None, w):
            raise IRError("bad_world", f"{n}: declared {declared[n]}, but its rules make it {w}")
        out[n] = replace(rel, world=w)
    for n, rel in out.items():
        if rel.role == "functional" and out[rel.domain].world != "closed":
            raise IRError("functional_open_domain", f"{n}: functional domain {rel.domain} must have world 'closed'")
    return out


def to_doc(prog):
    """The IR document of a program (contracts/rules.yaml): relations by name, rules by id."""
    def cols(cs):
        return [{"name": c.name, "type": c.type} for c in cs]

    def atom(a):
        return {"relation": a.relation, "terms": list(a.terms)}

    rels = []
    for r in sorted(prog.relations.values(), key=lambda r: r.name):
        d = {"name": r.name, "role": r.role, "key": cols(r.key)}
        if r.values:
            d["values"] = cols(r.values)
        if r.module:
            d["module"] = r.module
        if r.explain:
            d["explain"] = r.explain
        if r.invariant:
            d["invariant"] = True
        if r.absence:
            d["absence"] = True
        if r.outcome:
            d["outcome"] = r.outcome
        if r.extend:
            d["extend"] = True
        if r.closes:
            d["closes"] = r.closes
        if r.role == "functional":
            d["domain"] = r.domain
            d["value"] = {"name": r.value.name, "type": r.value.type}
            d["conflict_policy"] = r.conflict_policy
            if r.empty_state is not None:
                d["empty_state"] = r.empty_state
            if r.empty_reason is not None:
                d["empty_reason"] = r.empty_reason
        d["world"] = r.world
        rels.append(d)
    rules = []
    for r in sorted(prog.rules.values(), key=lambda r: r.id):
        d = {"id": r.id, "module": r.module, "stratum": str(r.stratum), "head": atom(r.head),
             "body": [dict(atom(b.atom), polarity=b.polarity, stratum=str(b.stratum)) for b in r.body]}
        if r.aggregates:
            d["aggregates"] = [{k: v for k, v in (*atom(a.atom).items(), ("function", a.function), ("over", a.over),
                                                  ("as", a.var), ("stratum", str(a.stratum))) if v is not None}
                               for a in r.aggregates]
        if r.conditions:
            d["conditions"] = [{"op": c.op, "left": c.left, "right": c.right,
                                **({"compare_as": c.compare_as} if c.compare_as else {})} for c in r.conditions]
        if r.assignments:
            d["assignments"] = [{"var": s.var, "op": s.op, "left": s.left, "right": s.right} for s in r.assignments]
        d["witness"] = {"relation": r.witness_relation, "variables": list(r.variables)}
        d["origin"] = {"file": r.origin[0], "line": str(r.origin[1])}
        rules.append(d)
    fmt = FORMAT_V2 if prog.format == FORMAT_V2 or any(r.role == "functional" for r in prog.relations.values()) else FORMAT
    doc = {"format": fmt, "pack": prog.pack, "relations": rels, "rules": rules}
    if prog.seals:
        doc["seals"] = prog.seals
    return doc


def with_strata(doc):
    """Fill in the strata of a rule program whose strata are left out (as the generator does)."""
    import copy

    doc = copy.deepcopy(doc)
    for r in doc["rules"]:
        r["stratum"] = "0"
        for x in r.get("body", []) + r.get("aggregates", []):
            x["stratum"] = "0"
    relations = {r["name"]: r for r in doc["relations"]}
    strata = {n: 0 for n in relations}
    for _ in range(len(relations) + 2):   # enough for a stratified program; load() rejects the rest
        changed = False
        for n, rel in relations.items():
            if rel.get("role") == "functional" and rel.get("domain") in strata:
                need = max(strata[rel["domain"]] + 1, 1)
                if strata[n] < need:
                    strata[n] = need
                    changed = True
        for r in doc["rules"]:
            h = r["head"]["relation"]
            is_func = relations[h].get("role") == "functional"
            need = max(
                [strata[b["relation"]] + (1 if is_func or b["polarity"] == "negative" else 0) for b in r.get("body", [])]
                + [strata[a["relation"]] + 1 for a in r.get("aggregates", [])]
                + ([strata[relations[h]["domain"]] + 1] if is_func and relations[h].get("domain") in strata else [])
                + [1]
            )
            if strata[h] < need:
                strata[h] = need
                changed = True
        if not changed:
            break
    for r in doc["rules"]:
        r["stratum"] = str(strata[r["head"]["relation"]])
        for x in r.get("body", []) + r.get("aggregates", []):
            x["stratum"] = str(strata[x["relation"]])
    prog = load(doc, require_witness=False)
    for r in doc["rules"]:
        rule = prog.rules[r["id"]]
        r["witness"] = {"relation": rule.witness_relation, "variables": list(rule.variables)}
    return doc
