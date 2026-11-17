"""Explainer core: from witness rows (θ per rule) to a Proof (contracts/proof.yaml).

Engine-neutral: the input is plain data, as the batch backend or Feldera gives it. Relations are sets of
tuples of canonical text (an integer as decimal text); a base relation's tuple is its key columns, then
its value columns. A witness row is θ in the order of rule.variables.

Why picks one acyclic proof per conclusion: the shortest derivation first (the fewest rule steps on the
longest path), then the smallest witness in a fixed order (rule id, then bindings). That is the rank of
formal.md §3, computed when asked, not stored in the engine. Each chosen witness only uses premises of a
strictly lower rank, so the proof graph is acyclic by construction.

Aggregates carry their evidence: count, the contributors hash and the result. The hash is computed here,
not in the engine: SHA-256 over the compact JSON of the sorted [key, value] of every row in
the group (only [key] for count), the same as the checker.
"""

from __future__ import annotations

import json

from rezono_canon import canonical_json, canonical_sha256

from . import rank
from .rules import is_var


def key_text(parts) -> str:
    """Canonical row key: the canonical JSON of the array of key parts as text."""
    return canonical_json([str(p) for p in parts])


def contribution(prog, aggregate, row) -> str | None:
    """What one row of a group gives an aggregate, as value text: `known:<cell>` of the column a `sum`, `min`
    or `max` ranges over, or None for a `count`, which reads no cell. One source for the two places that state
    it: the contributors hash of the witness and the row's `contributes` edge in the proof graph (trace.steps).
    A cell given as None is not known: it has no such text, and is refused, never written as known."""
    if aggregate.function == "count":
        return None
    rel = prog.relations[aggregate.atom.relation]
    cell = row[[c.name for c in rel.key + rel.values].index(aggregate.over)]
    if cell is None:
        raise NoProof(f"{rel.name}.{aggregate.over}: a cell that is not known contributes no known value")
    return f"known:{cell}"


class NoProof(ValueError):
    pass


class Explainer:
    def __init__(self, prog, rows: dict, witnesses: dict):
        self.prog = prog
        self.rows = {n: set(rs) for n, rs in rows.items()}
        self.witnesses = witnesses
        self._chosen = None

    # One rule instance -------------------------------------------------------------------------
    def _subst(self, terms, theta):
        return tuple(theta[t] if is_var(t) else t for t in terms)

    def _nkey(self, relation):
        return len(self.prog.relations[relation].key)

    def instance(self, rule, theta: dict) -> dict:
        """The witness of one substitution: conclusion, bindings, premises and aggregate evidence."""
        head = self._subst(rule.head.terms, theta)
        w = {"conclusion": {"relation": rule.head.relation, "key": key_text(head)}, "rule_id": rule.id}
        if rule.variables:
            w["bindings"] = [{"variable": v, "value": theta[v]} for v in rule.variables]
        w["premises"] = [{"row": {"relation": b.atom.relation, "key": key_text(self._subst(b.atom.terms, theta))},
                          "polarity": b.polarity, "stratum": b.stratum} for b in rule.body]
        if rule.aggregates:
            w["aggregates"] = [self._aggregate(i, a, theta) for i, a in enumerate(rule.aggregates)]
        return w

    def _aggregate(self, position, a, theta) -> dict:
        rel = self.prog.relations[a.atom.relation]
        nk = len(rel.key)
        fixed = [(i, theta[t] if is_var(t) else t) for i, t in enumerate(a.atom.terms) if t != "_"]
        members = sorted((key_text(r[:nk]), r) for r in self.rows.get(rel.name, ())
                         if all(r[i] == v for i, v in fixed))
        group = key_text(v for _, v in fixed)
        if a.function == "count":
            contributors, result = [[k] for k, _ in members], str(len(members))
        else:
            contributors = [[k, contribution(self.prog, a, r)] for k, r in members]
            numbers = [int(v.removeprefix("known:")) for _, v in contributors]
            result = str({"sum": sum, "min": min, "max": max}[a.function](numbers)) if numbers or a.function == "sum" else None
            if result is None:
                raise NoProof(f"{a.function} over an empty group has no conclusion")
        return {"relation": rel.name, "position": position, "group_key": group, "count": len(members),
                "contributors_sha256": canonical_sha256(contributors), "result": f"known:{result}"}

    # Choice --------------------------------------------------------------------------------------
    def _choose(self):
        """For every derived row its chosen witness: least rank, then least (rule id, bindings) (rank.py)."""
        derived = {n for n, r in self.prog.relations.items() if r.role == "derived"}
        inst = []
        for rid in sorted(self.witnesses):
            rule = self.prog.rules[rid]
            for row in sorted(set(self.witnesses[rid])):
                theta = dict(zip(rule.variables, row))
                head = (rule.head.relation, self._subst(rule.head.terms, theta))
                needs = {(b.atom.relation, self._subst(b.atom.terms, theta)) for b in rule.body
                         if b.polarity == "positive" and b.atom.relation in derived}
                inst.append((head, rule, theta, needs, (rid, json.dumps([theta[v] for v in rule.variables]))))
        chosen = rank.choose([(head, needs, order) for head, _, _, needs, order in inst])
        self._inst, self._chosen = inst, chosen

    def chosen(self) -> list[dict]:
        """The chosen witness of every derived row, sorted by conclusion: the whole proof graph (R10)."""
        if self._chosen is None:
            self._choose()
        out = [self.instance(self._inst[i][1], self._inst[i][2]) for _, i in self._chosen.values()]
        return sorted(out, key=lambda w: (w["conclusion"]["relation"], w["conclusion"]["key"]))

    def proof(self, relation: str, key: tuple, manifest_id: str) -> dict:
        """The chosen proof of one derived row."""
        if self._chosen is None:
            self._choose()
        root = (relation, tuple(key))
        if root not in self._chosen:
            raise NoProof(f"{relation}{key_text(key)} has no witness")
        out, todo, seen = [], [root], set()
        while todo:
            ref = todo.pop()
            if ref in seen:
                continue
            seen.add(ref)
            _, rule, theta, needs, _ = self._inst[self._chosen[ref][1]]
            out.append(self.instance(rule, theta))
            todo.extend(sorted(needs - seen))
        out.sort(key=lambda w: (w["conclusion"]["relation"], w["conclusion"]["key"]))
        return {"root": {"relation": relation, "key": key_text(key)}, "manifest_id": manifest_id, "witnesses": out}

    # Snapshots -----------------------------------------------------------------------------------
    def snapshot(self, relation: str, given=None) -> str:
        """A complete snapshot in the checker's JSON form: [{"key": [...], "values": {...}}], sorted by key. Of
        the rows the rules read, or of `given` (a calculation selection as a publication holds it)."""
        rel = self.prog.relations[relation]
        nk = len(rel.key)
        rows = []
        for r in sorted(self.rows.get(relation, ()) if given is None else given, key=lambda r: key_text(r[:nk])):
            row = {"key": [str(x) for x in r[:nk]]}
            if rel.values:
                row["values"] = {c.name: {"state": "known", "value": str(v)} for c, v in zip(rel.values, r[nk:])}
            rows.append(row)
        return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                                  for r in rows) + ("\n" if rows else "") + "]\n"


def with_calculation(proof: dict, calc_witnesses: list[dict]) -> dict:
    """The proof with the calculation witnesses of its graph (`calc_witnesses` of a Proof): the
    witness of every calculated row a premise names, and of every row those name, in the order given. A proof
    that reaches none is returned as it is."""
    by_row = {(w["conclusion"]["relation"], w["conclusion"]["key"]): w for w in calc_witnesses}
    todo = [(p["row"]["relation"], p["row"]["key"]) for w in proof["witnesses"] for p in w.get("premises", [])]
    reached = set()
    while todo:
        ref = todo.pop()
        if ref in by_row and ref not in reached:
            reached.add(ref)
            todo += [(p["relation"], p["key"]) for p in by_row[ref].get("premises", [])]
    if not reached:
        return proof
    return proof | {"calc_witnesses": [w for ref, w in by_row.items() if ref in reached]}


def relations_of(proof: dict) -> list[str]:
    """Every relation a proof refers to: its conclusions, premises and aggregates."""
    out = {proof["root"]["relation"]}
    for w in proof["witnesses"]:
        out.add(w["conclusion"]["relation"])
        out |= {p["row"]["relation"] for p in w.get("premises", [])}
        out |= {a["relation"] for a in w.get("aggregates", [])}
    return sorted(out)
