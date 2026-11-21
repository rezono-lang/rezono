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
import re

from .canon import INTEGER, CalcColumnType
from .refusals import Refusal, RefusalError

FORMATS = ("rezono.rules/1", "rezono.rules/2")
FUNCTIONS = ("count", "sum", "min", "max")
COMPARISONS = ("eq", "ne", "lt", "le", "gt", "ge")
COMPARE_AS = ("binary_text", "utc_instant")  # Condition.compare_as: how two bound text operands are ordered
OPERATORS = ("add", "sub", "mul", "div", "days")  # days: a view's reading of an ISO date (evaluate._arith)
VALUE_TYPES = ("string", "integer", "rational", "boolean")
CONFLICT_POLICIES = ("publish", "block")
EMPTY_STATES = ("unknown", "not_applicable")
ACCESS_RELATIONS = ("may_read", "may_read_full")
REASON_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class FunctionalSpec:
    """A rezono.rules/2 functional derivation over a finite closed domain."""
    name: str
    key_arity: int
    domain: str
    value_name: str
    value_type: str
    conflict_policy: str
    empty_state: str = "unknown"
    empty_reason: str | None = None


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
    format: str = "rezono.rules/2"  # program format: strict four-state unless rezono.rules/1
    state_key: int | None = None  # functional IR: the state column position when `over` reads a functional value


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
    format: str = "rezono.rules/1"

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
    `invariants`, the relations that must be empty, `outcomes`, each outcome relation with its kind,
    `functionals`, each rezono.rules/2 functional derivation spec, and `format`."""
    invariants: frozenset = frozenset()
    outcomes: dict = {}
    functionals: dict[str, FunctionalSpec] = {}
    format: str = "rezono.rules/1"


def _obligations(doc: dict) -> tuple[frozenset, dict, dict[str, FunctionalSpec]]:
    """The invariant, outcome and functional relations of a rule IR. An outcome's kind is a declared base
    relation with one key column of the outcome's element type; a functional relation requires rezono.rules/2,
    a finite closed base or derived domain whose key types match, a typed value column and a conflict policy.
    Raises ValueError."""
    fmt = doc.get("format")
    invariants, outcomes, functionals = set(), {}, {}
    declared = {r.get("name"): r for r in doc.get("relations", [])}
    for r in doc.get("relations", []):
        name = r["name"]
        role = r.get("role")
        derived = role == "derived"
        functional = role == "functional"
        if functional and fmt != "rezono.rules/2":
            raise ValueError(f"{name}: role 'functional' requires format rezono.rules/2")
        if r.get("invariant", False) not in (True, False) or (r.get("invariant") and not derived):
            raise ValueError(f"{name}: invariant is true or false, on a derived relation")
        if r.get("invariant"):
            invariants.add(name)
        if "outcome" in r:
            if not (derived and isinstance(r["outcome"], str) and len(r.get("key", [])) == 3
                    and [c.get("name") for c in r["key"][1:]] == ["state", "reason"]):
                raise ValueError(f"{name}: an outcome is derived, with the element, state and reason")
            kind = declared.get(r["outcome"], {})
            if not (kind.get("role") == "base" and len(kind.get("key", [])) == 1
                    and kind["key"][0].get("type") == r["key"][0].get("type")):
                raise ValueError(f"{name}: {r['outcome']} is not a kind: a base relation with one key column "
                                 f"of the element's type")
            outcomes[name] = r["outcome"]
        if functional:
            if sum(other.get("name") == name for other in doc.get("relations", [])) != 1:
                raise ValueError(f"{name}: duplicate relation declaration")
            if r.get("world") == "open":
                raise ValueError(f"{name}: a functional derivation is always closed")
            key = r.get("key", [])
            if not isinstance(key, list) or not key:
                raise ValueError(f"{name}: a functional derivation needs at least one key column")
            domain = r.get("domain")
            dom = declared.get(domain) if isinstance(domain, str) else None
            if dom is None or dom.get("role") not in ("base", "derived") or domain == name:
                raise ValueError(f"{name}: functional domain {domain!r} must name a declared base or derived relation")
            if [c.get("type") for c in dom.get("key", [])] != [c.get("type") for c in key]:
                raise ValueError(f"{name}: functional domain {domain} key columns must match exactly")
            val = r.get("value")
            if not isinstance(val, dict) or not isinstance(val.get("name"), str) or val.get("type") not in VALUE_TYPES:
                raise ValueError(f"{name}: a functional derivation requires a typed value column")
            key_names = {c.get("name") for c in key}
            if "state" in key_names or "reason" in key_names or val["name"] in {"state", "reason"} | key_names:
                raise ValueError(f"{name}: key/value columns conflict with co-located (state, reason, value)")
            policy = r.get("conflict_policy")
            if policy not in CONFLICT_POLICIES:
                raise ValueError(f"{name}: conflict_policy must be one of {CONFLICT_POLICIES}")
            empty_state = r.get("empty_state")
            if empty_state is not None and empty_state not in EMPTY_STATES:
                raise ValueError(f"{name}: empty_state must be one of {EMPTY_STATES}")
            empty_reason = r.get("empty_reason")
            if empty_reason is not None and (not isinstance(empty_reason, str) or not REASON_CODE.fullmatch(empty_reason)):
                raise ValueError(f"{name}: empty_reason must be a snake_case reason code")
            functionals[name] = FunctionalSpec(
                name=name,
                key_arity=len(key),
                domain=domain,
                value_name=val["name"],
                value_type=val["type"],
                conflict_policy=policy,
                empty_state=empty_state or "unknown",
                empty_reason=empty_reason,
            )
        elif any(r.get(f) is not None for f in ("domain", "value", "conflict_policy", "empty_state", "empty_reason")):
            raise ValueError(f"{name}: domain/value/conflict_policy are only allowed on functional relations")
    return frozenset(invariants), outcomes, functionals


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
        if r.get("role") != "derived":
            raise ValueError(f"{r['name']}: closes is only allowed on a derived relation")
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


def _state_key(a: dict, functionals: dict[str, FunctionalSpec],
               relations: dict[str, dict] | None = None,
               fmt: str = "rezono.rules/1",
               head_is_functional: bool = False) -> int | None:
    func = functionals.get(a["relation"])
    if func is not None:
        pos = func.key_arity
        if head_is_functional:
            return pos if pos < len(a["terms"]) and a["terms"][pos] == "_" else None
        return pos if a.get("over") == func.value_name else None
    if head_is_functional and fmt == "rezono.rules/2" and relations is not None:
        rel = relations.get(a["relation"])
        if rel is not None:
            for pos, col in enumerate(rel.get("key", ())):
                if col.get("name") == "state" and col.get("type") == "string":
                    return pos if pos < len(a["terms"]) and a["terms"][pos] == "_" else None
    return None


SEAL_KEYS = ("kind", "period", "row_sha256", "tables", "closed_until", "covers", "element", "sha256", "refused",
             "accepted")


PART_KEYS = ("kind", "arrow", "owner", "tables", "accepted")


def _names(value, keys) -> bool:
    return (isinstance(value, dict) and set(value) == set(keys)
            and all(isinstance(value[k], str) and value[k] for k in keys if k != "tables")
            and isinstance(value["tables"], list) and all(isinstance(t, str) and t for t in value["tables"]))


def load_seals(doc: dict) -> list[dict]:
    """The sealed kind of a rule IR: the tables to recompute row hashes and refused and accepted
    input from, and its parts (`parts`, optional): each with the arrow to its owner, the sealed kind or an
    earlier part. Raises ValueError on bad input."""
    raw = doc.get("seals", [])
    if not isinstance(raw, list):
        raise ValueError(f"seals must be a list: {raw!r}")
    out = []
    seen_tables: set[str] = set()
    for s in raw:
        parts = s.get("parts") if isinstance(s, dict) else None
        if not _names({k: v for k, v in s.items() if k != "parts"} if isinstance(s, dict) else s, SEAL_KEYS):
            raise ValueError(f"a seal names the tables {', '.join(SEAL_KEYS)}: {s!r}")
        for table in (s["refused"], s["accepted"], s["row_sha256"]):
            if table in seen_tables:
                raise ValueError(f"duplicate seal table {table!r}")
            seen_tables.add(table)
        if "parts" in s:
            placed = {s["kind"]}
            if not isinstance(parts, list) or not parts:
                raise ValueError(f"the parts of a seal are a list that is not empty: {parts!r}")
            for p in parts:
                if not _names(p, PART_KEYS) or p["owner"] not in placed or p["kind"] in placed:
                    raise ValueError(f"a part names {', '.join(PART_KEYS)}, with an owner before it: {p!r}")
                if p["accepted"] in seen_tables:
                    raise ValueError(f"duplicate seal table {p['accepted']!r}")
                seen_tables.add(p["accepted"])
                placed.add(p["kind"])
        out.append(dict(s))
    return out


def _rational_keys(relations: Sequence[dict], fmt: str | None = "rezono.rules/1") -> dict[str, tuple[bool, ...]]:
    """Rational columns in rezono.rules/1 are selection values and derived key columns;
    in rezono.rules/2 base and functional relations also carry exact rational columns."""
    result = {}
    for r in relations:
        columns = tuple(c.get("type") == "rational" for c in r.get("key", ()))
        if any(c.get("type") == "rational" for c in r.get("values") or ()):
            raise ValueError(f"{r['name']}: a rational column is part of the key")
        if not any(columns):
            continue
        if fmt == "rezono.rules/2":
            if r.get("role") == "calc" and (columns != (False, True, False, False)
                                            or sum(other["name"] == r["name"] for other in relations) != 1):
                raise ValueError(f"{r['name']}: expected a rational selection value")
            if r.get("role") == "calc":
                result[r["name"]] = columns
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


def _check_access_boundary(rules: Rules) -> None:
    """Neither may_read nor may_read_full may depend (directly or transitively) on a functional derivation."""
    if not rules.functionals:
        return
    consumers: dict[str, set[str]] = {}
    for func in rules.functionals.values():
        consumers.setdefault(func.domain, set()).add(func.name)
    for rule in rules.values():
        for premise in (*rule.body, *rule.aggregates):
            consumers.setdefault(premise.atom.relation, set()).add(rule.head.relation)
    after, todo = set(rules.functionals), sorted(rules.functionals)
    while todo:
        new = consumers.get(todo.pop(), set()) - after
        after.update(new)
        todo.extend(sorted(new))
    for rel in ACCESS_RELATIONS:
        if rel in after:
            raise ValueError(f"{rel} cannot depend on a functional derivation")


def personal_tables(bundle: dict) -> dict[str, str]:
    """The attribute tables marked `personal: true` in a schema bundle (`{table: slot_id}`).

    Independent defense in depth (decisions/personal-data-handling.md §3): fails closed with
    registered checker refusals (`RefusalError`) on malformed bundle sections, non-boolean
    `personal` flags, personal arrows, or personal attributes without a consistent table name.
    """
    if not isinstance(bundle, dict):
        raise RefusalError(Refusal("malformed_bundle"))
    raw_kinds = bundle.get("kinds")
    if raw_kinds is not None and not isinstance(raw_kinds, list):
        raise RefusalError(Refusal("bundle_section_malformed", field="kinds"))
    kind_tables: dict[str, str] = {}
    for entry in raw_kinds or ():
        if not isinstance(entry, dict):
            raise RefusalError(Refusal("bundle_section_malformed", field="kinds"))
        kid = entry.get("id")
        if isinstance(kid, str) and kid:
            ktable = entry.get("table", kid)
            if not isinstance(ktable, str) or not ktable:
                raise RefusalError(Refusal("bundle_section_malformed", field="kinds"))
            kind_tables[kid] = ktable

    raw_arrows = bundle.get("arrows")
    if raw_arrows is not None and not isinstance(raw_arrows, list):
        raise RefusalError(Refusal("bundle_section_malformed", field="arrows"))
    non_personal_tables: set[str] = set()
    for entry in raw_arrows or ():
        if not isinstance(entry, dict):
            raise RefusalError(Refusal("bundle_section_malformed", field="arrows"))
        arrow_name = str(entry.get("id") or entry.get("table") or "arrow")
        if "personal" in entry:
            if type(entry["personal"]) is not bool:
                raise RefusalError(Refusal("bundle_personal_flag_invalid", relation=arrow_name))
            if entry["personal"]:
                raise RefusalError(Refusal("bundle_personal_arrow", relation=arrow_name))
        if isinstance(entry.get("table"), str) and entry["table"]:
            non_personal_tables.add(entry["table"])

    raw_attrs = bundle.get("attributes")
    if raw_attrs is not None and not isinstance(raw_attrs, list):
        raise RefusalError(Refusal("bundle_section_malformed", field="attributes"))
    tables: dict[str, str] = {}
    for entry in raw_attrs or ():
        if not isinstance(entry, dict):
            raise RefusalError(Refusal("bundle_section_malformed", field="attributes"))
        attr_name = str(entry.get("id") or entry.get("table") or "attribute")
        has_personal = "personal" in entry
        if has_personal and type(entry["personal"]) is not bool:
            raise RefusalError(Refusal("bundle_personal_flag_invalid", relation=attr_name))
        raw_table = entry.get("table")
        kind = entry.get("kind")
        name = entry.get("name")
        derived_table = (
            f"{kind_tables.get(kind, kind)}__{name}"
            if isinstance(kind, str) and kind and isinstance(name, str) and name
            else None
        )
        if not (has_personal and entry["personal"]):
            if isinstance(raw_table, str) and raw_table:
                non_personal_tables.add(raw_table)
            elif derived_table:
                non_personal_tables.add(derived_table)
            continue
        if "table" in entry:
            if not isinstance(raw_table, str) or not raw_table:
                raise RefusalError(Refusal("bundle_personal_table_invalid", relation=attr_name))
            if derived_table is not None and raw_table != derived_table:
                raise RefusalError(Refusal("bundle_personal_table_invalid", relation=attr_name))
            table = raw_table
        elif derived_table is not None:
            table = derived_table
        else:
            raise RefusalError(Refusal("bundle_personal_table_invalid", relation=attr_name))
        label = (
            entry["id"]
            if isinstance(entry.get("id"), str) and entry["id"]
            else (f"{kind}.{name}" if isinstance(kind, str) and kind and isinstance(name, str) and name else table)
        )
        tables[table] = label

    for table, label in list(tables.items()):
        state_table = f"{table}_state"
        if state_table not in non_personal_tables:
            tables.setdefault(state_table, label)
    return tables


def check_personal_slots(rules: dict, bundle: dict) -> None:
    """Refuse any loaded rule whose head, body, aggregate, or functional domain references a personal
    attribute table from `bundle` (`bundle/schema-bundle.json`, decisions/personal-data-handling.md §3).
    Raises RefusalError."""
    personal = personal_tables(bundle)
    if not personal:
        return
    for func in sorted(getattr(rules, "functionals", {}).values(), key=lambda f: f.name):
        if func.domain in personal:
            raise RefusalError(
                Refusal("personal_slot_in_functional_domain", relation=func.name, field=personal[func.domain])
            )
    for rule in sorted(rules.values(), key=lambda r: r.id):
        if rule.head.relation in personal:
            raise RefusalError(
                Refusal("personal_slot_in_rule", rule=rule.id, relation=rule.head.relation,
                        field=personal[rule.head.relation])
            )
        for b in rule.body:
            if b.atom.relation in personal:
                raise RefusalError(
                    Refusal("personal_slot_in_rule", rule=rule.id, relation=b.atom.relation,
                            field=personal[b.atom.relation])
                )
        for a in rule.aggregates:
            if a.atom.relation in personal:
                raise RefusalError(
                    Refusal("personal_slot_in_rule", rule=rule.id, relation=a.atom.relation,
                            field=personal[a.atom.relation])
                )


def check_doc_personal_slots(doc: dict, bundle: dict) -> None:
    """Refuse any raw rule IR document whose rules or functional domains reference a personal attribute
    table from `bundle` (`bundle/schema-bundle.json`). Works on both full and minimal rule documents,
    independently of `load_rules`. Raises RefusalError."""
    personal = personal_tables(bundle)
    if not isinstance(doc, dict):
        raise RefusalError(Refusal("rule_ir_malformed", field="document"))
    raw_relations = doc.get("relations", ())
    if raw_relations is not None and not isinstance(raw_relations, (list, tuple)):
        raise RefusalError(Refusal("rule_ir_malformed", field="relations"))
    raw_rules = doc.get("rules", ())
    if raw_rules is not None and not isinstance(raw_rules, (list, tuple)):
        raise RefusalError(Refusal("rule_ir_malformed", field="rules"))
    if not personal:
        return
    for rel in raw_relations or ():
        if not isinstance(rel, dict):
            raise RefusalError(Refusal("rule_ir_malformed", field="relations"))
        if rel.get("role") == "functional":
            domain = rel.get("domain")
            if isinstance(domain, str) and domain in personal:
                rname = str(rel.get("name") or "functional")
                raise RefusalError(
                    Refusal("personal_slot_in_functional_domain", relation=rname, field=personal[domain])
                )
    for rule in raw_rules or ():
        if not isinstance(rule, dict):
            raise RefusalError(Refusal("rule_ir_malformed", field="rules"))
        rid = str(rule.get("id") or "rule")
        head = rule.get("head")
        if isinstance(head, dict):
            hrel = head.get("relation")
            if isinstance(hrel, str) and hrel in personal:
                raise RefusalError(
                    Refusal("personal_slot_in_rule", rule=rid, relation=hrel, field=personal[hrel])
                )
        for section in ("body", "aggregates"):
            atoms = rule.get(section, ())
            if atoms is not None and not isinstance(atoms, (list, tuple)):
                raise RefusalError(Refusal("rule_ir_malformed", field=section))
            for atom in atoms or ():
                if not isinstance(atom, dict):
                    raise RefusalError(Refusal("rule_ir_malformed", field=section))
                rel = atom.get("relation")
                if isinstance(rel, str) and rel in personal:
                    raise RefusalError(
                        Refusal("personal_slot_in_rule", rule=rid, relation=rel, field=personal[rel])
                    )


def check_calc_personal_slots(calculation: dict, bundle: dict) -> None:
    """Refuse any calculation IR (`ir/calc.json`) whose bindings (`facts`, `inputs`, `parameters`,
    `parameter_choice`, or `subject_table`) reference a personal attribute table from `bundle`
    (`bundle/schema-bundle.json`, decisions/personal-data-handling.md §3). Raises RefusalError."""
    personal = personal_tables(bundle)
    if not isinstance(calculation, dict):
        raise RefusalError(Refusal("calc_ir_malformed", field="calculation"))
    for field_name in ("subject_table", "parameters"):
        value = calculation.get(field_name)
        if value is not None and not isinstance(value, str):
            raise RefusalError(Refusal("calc_ir_malformed", field=field_name))
        if isinstance(value, str) and value in personal:
            raise RefusalError(Refusal("personal_slot_in_calculation", field=field_name, relation=value))
    for mapping_name in ("parameter_choice", "inputs"):
        mapping = calculation.get(mapping_name)
        if mapping is None:
            continue
        if not isinstance(mapping, dict):
            raise RefusalError(Refusal("calc_ir_malformed", field=mapping_name))
        for role, table in sorted(mapping.items(), key=lambda kv: str(kv[0])):
            if not isinstance(role, str) or (table is not None and not isinstance(table, str)):
                raise RefusalError(Refusal("calc_ir_malformed", field=mapping_name))
            if isinstance(table, str) and table in personal:
                raise RefusalError(
                    Refusal("personal_slot_in_calculation", field=f"{mapping_name}.{role}", relation=table)
                )
    raw_facts = calculation.get("facts")
    if raw_facts is not None:
        if not isinstance(raw_facts, list):
            raise RefusalError(Refusal("calc_ir_malformed", field="facts"))
        for fact in raw_facts:
            if not isinstance(fact, dict):
                raise RefusalError(Refusal("calc_ir_malformed", field="facts"))
            table = fact.get("table")
            if table is not None and not isinstance(table, str):
                raise RefusalError(Refusal("calc_ir_malformed", field="facts"))
            if isinstance(table, str) and table in personal:
                fid = fact.get("id") if isinstance(fact.get("id"), str) and fact.get("id") else table
                raise RefusalError(
                    Refusal("personal_slot_in_calculation", field=f"facts.{fid}", relation=table)
                )


def load_rules(doc: dict, *, bundle: dict | None = None) -> dict:
    """Read rule definitions and check their stratification. When `bundle` (`bundle/schema-bundle.json`)
    is given, also refuse any rule referencing an attribute marked `personal: true`.
    Raises ValueError (or RefusalError) on bad input."""
    fmt = doc.get("format")
    ir = fmt is not None
    if ir and fmt not in FORMATS:
        raise ValueError(f"unknown rule format {fmt}")
    effective_format = fmt or "rezono.rules/1"
    relations = doc.get("relations", ()) if ir else ()
    calc_relations = {r["name"] for r in relations if r.get("role") == "calc"}
    rational_keys = _rational_keys(relations, fmt)
    for r in relations:
        if r.get("role") in ("derived", "functional") and r.get("values"):  # a witness proves a key; nothing would prove a value
            raise ValueError(f"{r['name']}: a {r['role']} relation is a set, without value columns")
        if "release" in r:  # a release has proof obligations this checker does not verify yet
            raise ValueError(f"{r['name']}: release is not supported yet: a role reads a negation or an aggregate only over relations it reads in full (docs/architecture.md, delimited release)")
    rules = Rules()
    rules.format = effective_format
    rules.invariants, rules.outcomes, rules.functionals = (
        _obligations(doc) if ir else (frozenset(), {}, {})
    )
    if ir:
        _closes(doc, rules.invariants)
    keys = {}
    relations_by_name = {r["name"]: r for r in relations}
    for r in relations:
        col_names = [c["name"] for c in r.get("key", [])]
        if r.get("role") == "functional" and r["name"] in rules.functionals:
            col_names = [*col_names, "state", "reason", rules.functionals[r["name"]].value_name]
        keys[r["name"]] = col_names
    for r in doc.get("rules", []):
        head_is_functional = r["head"]["relation"] in rules.functionals
        rule = Rule(
            id=r["id"],
            stratum=int(r["stratum"]),
            head=_atom(r["head"]),
            body=tuple(BodyAtom(_atom(b), b["polarity"], int(b["stratum"])) for b in r.get("body", [])),
            aggregates=tuple(
                AggregateSpec(_atom(a), a["function"], a.get("over"), a.get("as"), int(a["stratum"]),
                              _over_key(a, keys), effective_format,
                              _state_key(a, rules.functionals, relations_by_name, effective_format, head_is_functional))
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
            format=effective_format,
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
        if rule.head.relation in rules.functionals:
            func = rules.functionals[rule.head.relation]
            if len(rule.head.terms) != func.key_arity + 1:
                raise ValueError(f"{rule.id}: functional head {rule.head.relation} needs {func.key_arity + 1} terms")
        if "_" in rule.head.terms or any("_" in b.atom.terms for b in rule.body):
            raise ValueError(f"{rule.id}: '_' is only allowed in aggregates")
        for b in rule.body:
            if b.polarity not in ("positive", "negative"):
                raise ValueError(f"{rule.id}: unknown polarity {b.polarity}")
            if b.atom.relation in rule.calc_inputs and (b.polarity != "positive" or b.atom.terms[2:] != ("known", "")):
                raise ValueError(f"{rule.id}: calculation inputs must be positive with selections known")
            if (bf := rules.functionals.get(b.atom.relation)) is not None and len(b.atom.terms) != bf.key_arity + 3:
                raise ValueError(f"{rule.id}: functional premise {b.atom.relation} needs {bf.key_arity + 3} terms")
        for a in rule.aggregates:
            if a.atom.relation in calc_relations:
                raise ValueError(f"{rule.id}: an aggregate cannot read a calculation selection")
            if (af := rules.functionals.get(a.atom.relation)) is not None and len(a.atom.terms) != af.key_arity + 3:
                raise ValueError(f"{rule.id}: functional aggregate {a.atom.relation} needs {af.key_arity + 3} terms")
            if a.function not in FUNCTIONS or (a.function != "count" and not a.over):
                raise ValueError(f"{rule.id}: bad aggregate {a}")
            if a.var is not None and not a.var.startswith("?"):
                raise ValueError(f"{rule.id}: aggregate result {a.var} is not a variable")
        _check_safety(rule)
        if rational_keys and fmt != "rezono.rules/2":
            _check_rational_uses(rule, rational_keys)
        rules[rule.id] = rule

    strata = {}
    for rule in rules.values():
        if strata.setdefault(rule.head.relation, rule.stratum) != rule.stratum:
            raise ValueError(f"{rule.id}: {rule.head.relation} is derived in two strata")
    for func in rules.functionals.values():
        if func.name in strata and strata.get(func.domain, 0) >= strata[func.name]:
            raise ValueError(f"{func.name}: functional stratum {strata[func.name]} must exceed domain {func.domain}")
    for rule in rules.values():
        is_func = rule.head.relation in rules.functionals
        uses = [(b.atom.relation, b.stratum, b.polarity == "positive" and not is_func) for b in rule.body]
        uses += [(a.atom.relation, a.stratum, False) for a in rule.aggregates]
        for relation, declared, allow_equal in uses:
            actual = strata.get(relation, 0)
            if declared != actual:
                raise ValueError(f"{rule.id}: {relation} is in stratum {actual}, declared {declared}")
            if actual > rule.stratum or (not allow_equal and actual == rule.stratum):
                raise ValueError(f"{rule.id}: {relation} breaks stratification")
    if ir:
        check_worlds(doc, rules)
        _check_access_boundary(rules)
    if bundle is not None:
        check_personal_slots(rules, bundle)
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

    opened = {n for n, r in declared.items() if r.get("role") not in ("derived", "functional") and r.get("world") == "open"}
    changed = True
    while changed:  # least fixpoint: open spreads along positive literals only
        changed = False
        for rule in rules.values():
            head = rule.head.relation
            if (head not in opened and not absence(head)
                    and declared.get(head, {}).get("role") != "functional"
                    and any(b.polarity == "positive" and b.atom.relation in opened for b in rule.body)):
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
        if r.get("role") == "functional" and worlds.get(r.get("domain")) != "closed":
            raise ValueError(f"{name}: functional domain {r.get('domain')} must be closed")
    return worlds


def check_calc_bindings(doc: dict, rules: dict, calculation: dict | None, *, bundle: dict | None = None) -> None:
    """Verify the rule-to-calculation boundary from both IRs, independently of the compiler.
    When `bundle` (`bundle/schema-bundle.json`) is given, also refuse any calculation binding
    referencing an attribute marked `personal: true`."""
    if bundle is not None:
        if calculation is not None:
            check_calc_personal_slots(calculation, bundle)
        else:
            personal_tables(bundle)
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
    for rel in ("may_read", "may_read_full"):
        if rel in after:
            raise ValueError(f"{rel} cannot depend on a calculation selection")
    if cycle := after.intersection(f["table"] for f in program.get("facts", ())):
        raise ValueError(f"calculation reads its downstream relations: {', '.join(sorted(cycle))}")
    for rule in rules.values():
        for premise in rule.body:
            if premise.atom.relation in after and premise.polarity != "positive":
                raise ValueError(f"{rule.id}: calculation-dependent premises must be positive")
        if any(aggregate.atom.relation in after for aggregate in rule.aggregates):
            raise ValueError(f"{rule.id}: an aggregate cannot read a calculation-dependent relation")


def derived_relations(doc: dict, rules: dict) -> set:
    """Every derived and functional relation the definitions declare: the relation catalogue of the rule IR
    (role `derived` or `functional`), or the rule heads in the minimal form. Only an explicit `extend: true`
    on a derived relation may have no rule. It stays in this catalogue: check_epoch then requires its snapshot
    and refuses every row without a valid witness. With no rules, no such witness exists, so the snapshot must
    independently be empty. Unmarked declarations without rules and undeclared heads are refused. Raises ValueError."""
    heads = {r.head.relation for r in rules.values()}
    if doc.get("format") is None:
        return heads
    declared = {r["name"] for r in doc.get("relations", []) if r.get("role") in ("derived", "functional")}
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
