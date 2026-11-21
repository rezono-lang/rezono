"""Access per role, on the server (docs/architecture.md, access and privacy).

`may_read(role, kind, id)` is a relation of the pack, derived by its rules like any other (std-access).
An element is typed: (kind, id). Equal ids in two kinds are two elements. A right on a kind also holds
for its subkinds, along the parent chain of the schema (is_a). A role without rows reads nothing.

Non-interference: what a role gets depends only on what it may read, never on a row it may not.
- A base row is readable if every column that holds an element (`columns`: the kind per column, from the
  schema) holds one the role may read. A column without a kind (an attribute value) decides nothing.
- A role in a program that declares `may_read_full(role, kind)` reads a kind in full only with an evaluated
  coverage row and its rule witness. Coverage grants no element rights. For older programs, a kind is
  full for a role if a rule grants every element of the kind without a condition. With the role as a constant
  and only `K(x)` in the body, that is the configured role of that name. With
  `may_read(r, "K", x) :- role(r), K(x).` it is every role the pack's facts name, as the rule says: for a
  configured role without its own `role` row the rule derives nothing, so it gives that role nothing in
  full either. No other `role` row counts: which other roles exist changes nothing for a role.
  Roles in two layers (B19): with `may_read(r, "K", x) :- role__capability(r, "c"), K(x).` it is every role
  the pack maps to capability `c` (std-access), so a configured role with the row (role, c) of that mapping.
  Each grant has its evidence (`Full.evidence`): the rule and the one row it rests on, if any (`role` or
  `role__capability`), which the checker derives again on its own and compares. Subkinds follow. Then every element of K must be readable in the data, or the publication is red. A base
  relation is full if each of its kind columns is; a derived relation if every base relation it depends on is.
  A calculation view has sources too: its subject kind, every relation that any version of its rule
  reads (absences included) and every calculation view a version takes as a premise. It is full only if all
  of them are, so only for a role that sees every row of it; a view the program does not account for, and a
  calculation that a rule reads, are never full. No row decides it.
- A derived row is visible if it is derivable from what the role reads: among all witness instances of
  the engine, keep those whose positive base premises the role reads and whose negations and aggregates
  range over relations it reads in full; derived premises need a kept proof themselves (least fixpoint).
  The proof of each row is then chosen among those instances, per role, with the explainer's rank. A row
  without such a proof is gone. So a hidden row never adds or removes a row, a witness or a byte.
- Whether an instance may rely on the absence or the whole group of a relation is decided in one place,
  `Scope.closes`. A delimited release (`release` in the rule IR: a role reads a result without its rows) would
  extend it there; it is not supported yet and refused (docs/architecture.md, access and privacy).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from decimal import Decimal
from math import gcd

from rezono_canon import canonical_json
from rezono_compiler import rank
from rezono_compiler.rules import INT

from . import calc_scope

_POSITIVE = re.compile(r"^[1-9][0-9]*$")

ACCESS = "may_read"
READ_FULL = "may_read_full"
ROLE = "role"  # the kind of the roles (std-access): `role(r)` in a read rule means every role the pack names
# The mapping of a role to a generic capability (std-access, the multivalued slot `capability` of Role): in a
# read rule, `role__capability(r, "c")` means every role the pack maps to capability `c` (roles in two layers).
CAPABILITY = "role__capability"
COMPLETE = "complete"  # a server-side role (the checker) that reads every row, unfiltered
FILTERED = "may_read"


class Uncovered(Exception):
    """A full kind with an element the role may not read: the read rules and the data disagree."""


class Full(frozenset):
    """The relations a role reads in full, with the evidence for each kind it reads in full (B19).

    Each evidence entry has `{"kind", "rule", "ground"}`. In explicit programs the ground is the witnessed
    `[may_read_full, role, kind]` row. In older programs it is the row the unconditional read rule rests on
    (`role` or `role__capability`), or `[]` for a rule that names the role as a constant. A total, an absence
    or a seal over a kind counts as complete for the role only while every element is readable (`Uncovered`)."""

    evidence: tuple = ()


def key_text(row) -> str:
    return canonical_json([str(p) for p in row])


def ref(w: dict) -> tuple[str, str]:
    return w["conclusion"]["relation"], w["conclusion"]["key"]


def order(w: dict):
    return (w["conclusion"]["relation"], w["conclusion"]["key"], w["rule_id"],
            json.dumps(w.get("bindings", []), sort_keys=True))


def ancestors(kinds, parents: dict) -> dict[str, list[str]]:
    """Every kind with itself and its parents up to the root. A parent that is no kind, or a cycle, is refused."""
    out = {}
    for k in sorted(kinds):
        chain, cur = [k], parents.get(k)
        while cur is not None:
            if cur not in kinds:
                raise ValueError(f"kind {k}: parent {cur} is not a kind")
            if cur in chain:
                raise ValueError(f"kind {k}: a cycle in the parent chain")
            chain.append(cur)
            cur = parents.get(cur)
        out[k] = chain
    return out


def choose(instances, derived) -> dict[tuple[str, str], dict]:
    """For every derivable row one witness: least rank, then least (rule id, binding values).

    The one selector of the explainer (rezono_compiler.rank, formal.md §3), over witness instances as the
    engine gives them. An instance whose derived premise has no chosen proof is never chosen.
    """
    instances = list(instances)
    inst = [(ref(w), {(p["row"]["relation"], p["row"]["key"]) for p in w.get("premises", ())
                      if p["polarity"] == "positive" and p["row"]["relation"] in derived},
             (w["rule_id"], json.dumps([b["value"] for b in w.get("bindings", ())])))
            for w in instances]
    return {head: instances[i] for head, (_, i) in rank.choose(inst).items()}


def _calc_value_valid(text: str, column_type: str) -> bool:
    """Whether a calculation selection value has canonical syntax for its declared column type."""
    if not isinstance(text, str):
        return False
    if column_type == "integer":
        return INT.fullmatch(text) is not None
    if column_type != "rational":
        return False
    num, slash, den = text.partition("/")
    if not INT.fullmatch(num):
        return False
    if not slash:
        return True
    # Decimal decodes decimal digits without a string-to-int digit limit.
    return bool(den != "1" and _POSITIVE.fullmatch(den) and gcd(int(Decimal(num)), int(Decimal(den))) == 1)


def _calc_input_types(rules: dict) -> dict[str, str]:
    """Per declared calc-input relation, its numeric value column type (`rational` or `integer`)."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for rel in rules.get("relations", ()):
        if isinstance(rel, dict) and rel.get("role") == "calc" and isinstance(rel.get("name"), str):
            grouped[rel["name"]].append(rel)
    out: dict[str, str] = {}
    for name, decls in grouped.items():
        key = decls[0].get("key", ()) if len(decls) == 1 else ()
        if (isinstance(key, (list, tuple)) and len(key) == 4
                and isinstance(key[1], dict) and key[1].get("type") == "rational"):
            out[name] = "rational"
        else:
            out[name] = "integer"
    return out


class Scope:
    """What one filtered role may read in an epoch, decided before any derived row is looked at."""

    def __init__(self, rows: dict, kinds, parents: dict, columns: dict, rules: dict, role: str, witnesses=()):
        grants = rows.get(ACCESS, ())
        if any(len(r) != 3 for r in grants):
            raise ValueError(f"{ACCESS} has three columns (role, kind, id): an element is typed")
        self.allowed = {(r[1], r[2]) for r in grants if r[0] == role}
        self.chains = ancestors(kinds, parents)
        self.columns = columns
        self.derived = {r["name"] for r in rules.get("relations", ()) if r.get("role") == "derived"}
        self.calc_input_types = _calc_input_types(rules)
        self.calc_inputs = set(self.calc_input_types)
        for r in rules.get("relations", ()):
            if "release" in r:
                raise ValueError(f"relation {r['name']}: release is not supported yet (negation and aggregates "
                                 "only over relations the role reads in full)")
        for rel in sorted(set(rows) - self.derived - set(columns)):
            raise ValueError(f"relation {rel}: no kind per column, so no right can be read from it")
        for rel in sorted(set(rows) - self.derived):
            expected = len(self.columns[rel])
            if any(len(r) != expected for r in rows[rel]):
                raise ValueError(f"relation {rel}: row arity must match schema ({expected} columns)")
        self.named = any(len(r) == 1 and r[0] == role for r in rows.get(ROLE, ()))  # the pack's facts name this role
        # The capabilities the pack's facts map this role to (roles in two layers).
        self.capabilities = {r[1] for r in rows.get(CAPABILITY, ()) if len(r) == 2 and r[0] == role}
        if any(r["name"] == READ_FULL for r in rules.get("relations", ())):
            self.grants = self._witnessed_grants(rows.get(READ_FULL, ()), rules, witnesses, role)
        else:
            self.grants = self._grants(rules, role)
        self.full_kinds = {k for k, chain in self.chains.items() if {g["kind"] for g in self.grants}.intersection(chain)}
        for k in sorted(self.full_kinds):
            for r in rows.get(k, ()):
                if len(r) != 1 or not self.reads(k, r[0]):
                    raise Uncovered(f"role {role}: the read rules give kind {k} in full, but not every element")
        self.withheld = self._withheld_seals(rules) | self._withheld_admission(rules)
        # What each calculation view rests on, as `with_calc` gave it; without a program there is none.
        self.calc_sources = getattr(columns, "calc_sources", {})
        self.full = Full(self._full_relations(rules, rows))
        self.full.evidence = tuple(self.grants)

    def reads(self, kind: str, id_: str) -> bool:
        return any((a, id_) in self.allowed for a in self.chains[kind])

    def readable(self, rel: str, row) -> bool:
        """A base row: every element in it is one the role may read, in a relation not withheld."""
        cols = self.columns[rel]
        if len(row) != len(cols):
            raise ValueError(f"relation {rel}: row has {len(row)} columns, expected {len(cols)}")
        return rel not in self.withheld and all(k is None or self.reads(k, v) for k, v in zip(cols, row, strict=True))

    def _withheld_seals(self, rules: dict) -> frozenset[str]:
        """The relations of a seal with parts (docs/compiler.md#parts) for a role that does not read every part
        kind in full. Whether an element is refused or accepted, and so whether each of its parts counts, depends
        on all its parts: a part the role may not read could decide it. So the role gets none of them, decided
        from the read rules alone, and nothing that rests on them."""
        out = set()
        for s in rules.get("seals", ()):
            parts = s.get("parts", ())
            if parts and not all(p["kind"] in self.full_kinds for p in parts):
                out |= {s["refused"], s["accepted"], s["row_sha256"], *(p["accepted"] for p in parts)}
        return frozenset(out)

    @staticmethod
    def _withheld_admission(rules: dict) -> frozenset[str]:
        """Every protected admission input (decisions/admission-transport.md, section 6), whatever the rule IR `rules`
        declares, as the checker withholds them. They expose the trusted inventory of a receipt or round, member
        keys included, and no decision gives them a read rule or element columns yet: a role gets none of their
        rows, and nothing that rests on them."""
        from rezono_compiler.rules_dl import PROTECTED

        return frozenset(PROTECTED)

    def _witnessed_grants(self, rows, rules: dict, witnesses, role: str) -> list[dict]:
        """Match evaluated coverage rows to the rule substitutions that derived them."""
        if any(len(row) != 2 for row in rows):
            raise Uncovered(f"{READ_FULL} has two columns (role, kind)")
        coverage = {key_text(row): row[1] for row in rows if row[0] == role}
        if not coverage:
            return []
        heads = {r["id"]: r["head"]["terms"] for r in rules.get("rules", ())
                 if r["head"]["relation"] == READ_FULL}
        proven = defaultdict(set)
        for w in witnesses:
            relation, key = ref(w)
            rule_id = w["rule_id"]
            if relation != READ_FULL or key not in coverage or rule_id not in heads:
                continue
            bindings = {b["variable"]: b["value"] for b in w.get("bindings", ())}
            terms = heads[rule_id]
            if any(t.startswith("?") and t not in bindings for t in terms):
                continue
            if key_text(bindings[t] if t.startswith("?") else t for t in terms) == key:
                proven[key].add(rule_id)
        granted = []
        for key, kind in sorted(coverage.items(), key=lambda item: item[1]):
            if kind not in self.chains or key not in proven:
                raise Uncovered(f"role {role}: no matching coverage witness for kind {kind}")
            granted.extend({"kind": kind, "rule": rule_id, "ground": [READ_FULL, role, kind]}
                           for rule_id in sorted(proven[key]))
        return granted

    def _grants(self, rules: dict, role: str) -> list[dict]:
        """Each read rule that gives this role a kind without a condition, with the row it rests on. A rule over
        every role, `role(r)`, gives a kind only to a role the pack names (`self.named`), and a rule over a
        capability, `role__capability(r, "c")`, only to a role the pack maps to `c`: for any other role it derives
        no row. A rule with the role as a constant rests on no row."""
        granted = []
        for r in rules.get("rules", ()):
            head = r["head"]
            if (head["relation"] != ACCESS or len(head["terms"]) != 3
                    or any(r.get(f) for f in ("aggregates", "conditions", "assignments"))
                    or any(b["polarity"] != "positive" for b in r["body"])):
                continue
            who, kind, x = head["terms"]
            if kind.startswith("?") or kind not in self.chains or not x.startswith("?") or who == x:
                continue
            body = {(b["relation"], tuple(b["terms"])) for b in r["body"]}
            ground = None
            if who.startswith("?"):
                if self.named and body == {(kind, (x,)), (ROLE, (who,))}:
                    ground = [ROLE, role]
                else:
                    held = [t[1] for rel, t in body if rel == CAPABILITY and len(t) == 2 and t[0] == who]
                    if (len(held) == 1 and not held[0].startswith("?") and held[0] in self.capabilities
                            and body == {(kind, (x,)), (CAPABILITY, (who, held[0]))}):
                        ground = [CAPABILITY, role, held[0]]
            elif body == {(kind, (x,))} and who == role:
                ground = []
            if ground is not None:
                granted.append({"kind": kind, "rule": r["id"], "ground": ground})
        return sorted(granted, key=lambda g: (g["kind"], g["rule"], g["ground"]))

    def _full_relations(self, rules: dict, rows: dict) -> frozenset[str]:
        whole = {rel for rel in self.columns if rel not in self.withheld and rel not in self.calc_inputs
                 and all(k is None or k in self.full_kinds for k in self.columns[rel])}
        base = whole - set(self.calc_sources)  # a calculation view is no base relation: it has sources
        deps = defaultdict(set)
        for r in rules.get("rules", ()):
            deps[r["head"]["relation"]] |= {b["relation"] for b in r["body"]}
            deps[r["head"]["relation"]] |= {a["relation"] for a in r.get("aggregates", ())}

        def full(rel, seen) -> bool:
            if rel not in self.derived:
                return rel in base
            if rel in seen:
                return True  # recursion adds no base relation
            seen.add(rel)
            return all(full(d, seen) for d in sorted(deps[rel]))

        # A calculation view: its subject kind (`whole`), every relation a version of its rule reads
        # and every view a version takes as a premise. Least fixpoint over the views, so a view that rests on
        # itself, or on a view the program does not account for, is not full.
        views: set[str] = set()
        changed = True
        while changed:
            changed = False
            for view, sources in sorted(self.calc_sources.items()):
                if (view not in views and view in whole and sources is not None
                        and all(s in views if s in self.calc_sources else full(s, set()) for s in sorted(sources))):
                    views.add(view)
                    changed = True
        return frozenset(rel for rel in set(rows) | self.derived
                         if (rel in views if rel in self.calc_sources else full(rel, set())))

    def closes(self, rel: str, w: dict) -> bool:
        """May instance `w` rely on the absence of rows of `rel`, or on its whole group, for this role?

        Today only when the role reads `rel` in full. A delimited release would add the instances whose
        conclusion a pack releases to this role, per relation; that, and its obligations for the checker,
        are designed but refused (docs/architecture.md, access and privacy)."""
        return rel in self.full

    def usable(self, w: dict, readable: dict) -> bool:
        """A witness instance the role could check itself: readable base premises, negation and aggregates
        only where `closes` allows. Derived positive premises are left to `choose`."""
        for p in w.get("premises", ()):
            rel = p["row"]["relation"]
            if p["polarity"] != "positive":
                if not self.closes(rel, w):
                    return False
            elif rel not in self.derived and p["row"]["key"] not in readable.get(rel, ()):
                return False
        return all(self.closes(a["relation"], w) for a in w.get("aggregates", ()))


def without_rights(rows: dict, roles: dict[str, str]) -> list[str]:
    """The filtered roles of the configuration that no `may_read` row names: each reads no element. So a
    publication can say it (the command line does), where a profile and a pack disagree about the roles."""
    named = {r[0] for r in rows.get(ACCESS, ()) if len(r) == 3}
    return sorted(role for role, mode in roles.items() if mode == FILTERED and role not in named)


class Columns(dict):
    """The kind per column of an epoch with calculation rules, and what each calculation view rests on."""

    calc_sources: dict


def with_calc(columns: dict, calc_ir: dict | None) -> dict:
    """The kind per column, with the relations of the calculation rules: a calculated row names its
    subject; the evaluation date names no element. With them goes what each calculation view rests on
    (`calc_scope.view_sources`), which decides whether a role reads the view in full. The one place
    every scope over an epoch gets them, so a publication and a sweep judge the same relations (no relation
    is let through by name)."""
    if calc_ir is None:
        return columns
    out = Columns(columns | {v: (calc_ir["subject"], None, None, None) for v in calc_scope.published_views(calc_ir)})
    out[calc_ir["as_of"]] = (None, None, None)
    out.calc_sources = calc_scope.view_sources(calc_ir)
    return out


def for_role(rows: dict, kinds, parents: dict, columns: dict, rules: dict, witnesses: list, role: str,
             calc_ir: dict | None = None, calc_witnesses=()):
    """The rows, the witness set and the relations read in full of one filtered role.

    `witnesses` are all witness instances of the epoch; `rules` is the rule IR (for the derived relations,
    the read rules and the dependencies). With calculation rules (`calc_ir`, ir/calc.json), a calculated
    row and its witness are the role's only as `calc_visible` says.
    """
    scope = Scope(rows, kinds, parents, with_calc(columns, calc_ir), rules, role, witnesses)
    nkey = {r["name"]: len(r["key"]) for r in rules.get("relations", ())}
    readable = {rel: [r for r in rs if scope.readable(rel, r)] for rel, rs in rows.items()
                if rel not in scope.derived and rel not in scope.calc_inputs}
    keys = {rel: {key_text(r[:nkey.get(rel, len(r))]) for r in rs} for rel, rs in readable.items()}
    chosen = choose([w for w in witnesses if scope.usable(w, keys)], scope.derived)
    if calc_ir is not None:
        visible = calc_visible(scope, calc_ir, calc_witnesses, set(chosen))
        for rel in sorted(calc_scope.published_views(calc_ir)):
            readable[rel] = [r for r in rows.get(rel, ()) if (rel, key_text(r)) in visible]
        if scope.calc_inputs:
            # A readable subject does not make its calculated value usable as a proof premise.
            for rel in sorted(scope.calc_inputs):
                column_type = scope.calc_input_types[rel]
                keys[rel] = {key_text(row) for row in readable.get(rel, ()) if len(row) == 4
                             and row[2] == "known" and row[3] == ""
                             and _calc_value_valid(row[1], column_type)}
            chosen = choose([w for w in witnesses if scope.usable(w, keys)], scope.derived)
    for rel, rs in rows.items():
        if rel in scope.derived:
            readable[rel] = [r for r in rs if (rel, key_text(r)) in chosen]
    sees = {"witnesses": sorted(chosen.values(), key=order), "hidden": []}
    if calc_ir is not None:
        sees["calc_witnesses"] = sorted(visible.values(), key=ref)
    return readable, sees, scope.full


def calc_visible(scope: Scope, ir: dict, witnesses, derived_rows: set) -> dict[tuple[str, str], dict]:
    """The calculation witnesses a role may see: the subject is an element it reads,
    it reads in full every relation the evaluation reads (an absence decides a state there), and every
    premise is visible to it: a derived row with a chosen proof, or a calculated row seen the same way.
    Least fixpoint, so a hidden row never makes another one visible."""
    views = calc_scope.published_views(ir)
    visible: dict[tuple[str, str], dict] = {}
    changed = True
    while changed:
        changed = False
        for w in witnesses:
            r = ref(w)
            if r in visible:
                continue
            subject = calc_scope.subject_of(r[1])
            premises = [(p["relation"], p["key"]) for p in w.get("premises", ())]
            if (subject is not None and scope.reads(ir["subject"], subject)
                    and calc_scope.reads(ir, calc_scope.version_of(ir, w)) <= scope.full
                    and all(p in visible if p[0] in views else p in derived_rows for p in premises)):
                visible[r] = w
                changed = True
    return visible
