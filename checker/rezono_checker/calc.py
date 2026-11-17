"""Calculation witnesses, recomputed on their own: Python fractions over ir/calc.json and
the complete snapshots. Nothing here comes from the compiler; the meaning is docs/compiler.md
("Calculation rules", "Design M3: calculation witnesses") and docs/formal.md §6.

Every step is checked locally, against the recorded steps of its own arguments, so each error gives its
own finding: a wrong version `calc_version`, a missing, extra or untaken step `calc_path` (a wrong
branch), a leaf that differs from the snapshots `calc_leaf`, an operator step that differs from its
arguments `calc_step` (a wrong rounding, an unknown taken as zero), a step that names another node
than the program `calc_node`, and a definition or result that differs `calc_result`.
"""

import json
from fractions import Fraction
from graphlib import CycleError, TopologicalSorter

from .canon import encode_key, number, number_text

BOUND = 2**63 - 1  # W8: every numerator and denominator, in lowest terms


def beyond(op: str) -> "Val":
    """W8 (arbiter, 11-11-2026): a step whose exact result exceeds the bound has a value Rezono cannot hold,
    so it is unknown, with a reason that names the bound and the operator; invalid is for a result that
    cannot exist."""
    return Val("unknown", None, f"beyond the bound of W8 in {op}")
SEVERITY = {"known": 0, "not_applicable": 1, "unknown": 2, "invalid": 3}  # W9: the order is the precedence
CONSTANTS = ("integer", "boolean")


class Val(tuple):
    """(state, value, reason): value is a Fraction or a bool when known, else None."""

    def __new__(cls, state, value=None, reason=""):
        return super().__new__(cls, (state, value, reason))

    state = property(lambda self: self[0])
    value = property(lambda self: self[1])
    reason = property(lambda self: self[2])


def known(v) -> Val:
    return Val("known", v, "")


def same(a: Val | None, b: Val | None) -> bool:
    """Equal values of the same type: a tuple compare takes True for Fraction(1), a boolean for a number."""
    return a is not None and b is not None and a == b and type(a.value) is type(b.value)


def boolean(v: Val) -> bool:
    if v.state == "known" and not isinstance(v.value, bool):
        raise TypeError("a number where a boolean goes")
    return v.value


def numbers(vals: list[Val]) -> list[Fraction]:
    if any(isinstance(v.value, bool) for v in vals):
        raise TypeError("a boolean where a number goes")
    return [v.value for v in vals]


def fits(x: Fraction) -> bool:
    return abs(x.numerator) <= BOUND and x.denominator <= BOUND


def text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return number_text(v)


def recorded(state, value_text, reason) -> Val | None:
    """A value as a witness writes it; None when it is not canonical text."""
    if state not in SEVERITY or not isinstance(value_text, str) or not isinstance(reason, str):
        return None
    if state != "known":
        return Val(state, None, reason) if value_text == "" else None
    if value_text in ("true", "false"):
        v = value_text == "true"
    else:
        try:
            v = number(value_text)
        except ValueError:
            return None
    return Val("known", v, reason) if text(v) == value_text and reason == "" else None


def node_kind(e: dict) -> str:
    return e["op"] if e.get("op") else next(k for k in ("integer", "boolean", "fact", "parameter", "rule") if k in e)


def constant(e: dict) -> Val:
    return known(Fraction(int(e["integer"]))) if "integer" in e else known(bool(e["boolean"]))


# --- the semantics (W8, W9) -----------------------------------------------------------------------

def logic(op: str, vals: list[Val]) -> Val:
    """and: false as soon as one argument is a known false; or: true as soon as one is a known true.
    Invalid comes first; then unknown, then not_applicable, each with the first argument's reason."""
    worst = worst_of(vals)
    if worst and worst.state == "invalid":
        return worst
    decisive = op == "or"
    if any(v.state == "known" and v.value is decisive for v in vals):
        return known(decisive)
    return worst or known(not decisive)


def worst_of(vals: list[Val]) -> Val | None:
    """The most severe state that is not known, with the reason of the first argument that has it."""
    top = max((SEVERITY[v.state] for v in vals), default=0)
    return next((Val(v.state, None, v.reason) for v in vals if SEVERITY[v.state] == top), None) if top else None


def apply(op: str, args: list[Val]) -> Val:
    """One operator over its arguments' values."""
    if op == "if":
        c = args[0]
        return Val(c.state, None, c.reason) if c.state != "known" else args[1 if boolean(c) else 2]
    if op in ("and", "or"):
        for a in args:
            boolean(a)
        return logic(op, args)
    worst = worst_of(args)
    if worst:
        return worst
    if op == "eq" and all(isinstance(a.value, bool) for a in args):
        return known(args[0].value == args[1].value)
    xs = numbers(args)
    if op in ("add", "sub"):
        acc = xs[0]
        for x in xs[1:]:  # folds from the left; every step must fit
            acc = acc + x if op == "add" else acc - x
            if not fits(acc):
                return beyond(op)
        return known(acc)
    if op in ("min", "max"):
        return known(min(xs) if op == "min" else max(xs))
    if op == "ratio":
        x, n, d = xs
        if d == 0:
            return Val("invalid", None, "division by zero in ratio")
        if not fits(x * n) or not fits(x * n / d):
            return beyond("ratio")
        return known(x * n / d)
    if op in ("floor", "ceil", "round"):
        x = xs[0]
        if op == "floor":
            return known(Fraction(x.numerator // x.denominator))
        if op == "ceil":
            return known(Fraction(-(-x.numerator // x.denominator)))
        r = (2 * abs(x.numerator) + x.denominator) // (2 * x.denominator)  # half away from zero (W4)
        return known(Fraction(-r if x < 0 else r))
    if op == "pow":
        b, e = xs
        if e.denominator != 1 or e < 0:
            return Val("invalid", None, "exponent of pow is not a natural number")
        if e >= 64:  # only 0, 1 and -1 fit then; never raise a large base that far
            if b in (0, 1, -1):
                return known(Fraction(-1 if b == -1 and e.numerator % 2 else 0 if b == 0 else 1))
            return beyond("pow")
        r = b ** e.numerator
        return known(r) if fits(r) else beyond("pow")
    a, b = xs
    return known({"eq": a == b, "lt": a < b, "lte": a <= b, "gte": a >= b}[op])


def safe(op: str, args: list[Val]) -> Val | None:
    """apply, or None when the recorded arguments do not fit the operator (a boolean where a number goes)."""
    try:
        return apply(op, args)
    except (TypeError, ValueError, AttributeError, ZeroDivisionError):
        return None


def lookup(values: set, number_type: bool, missing: Val, what: str) -> Val:
    if not values:
        return missing
    if len(values) > 1:
        return Val("invalid", None, f"{what} has more than one value")
    (v,) = values
    if not number_type:
        return known(v == "true")
    if int(v) < -BOUND:
        return Val("invalid", None, f"{what} does not fit 64 bits")
    return known(Fraction(int(v)))


# --- the program and the snapshots ----------------------------------------------------------------

class Program:
    def __init__(self, ir: dict, rows):
        """`rows(relation)` gives the complete snapshot of a relation: {key: (parts, values)}."""
        self.ir, self.rows = ir, rows
        self.facts = {f["id"]: f for f in ir.get("facts", [])}
        self.versions = {v["id"]: v for v in ir.get("versions", [])}
        self.rules = {r["rule"]: r for r in ir.get("rules", [])}
        self.views = {r["view"]: ("rule", r["rule"]) for r in self.rules.values()}
        self.views.update({v["view"]: ("version", v["id"]) for v in self.versions.values()})
        # RV-K08: each table is read once, into an index by its first column and one by the rest of the key, and
        # a parameter or a rule's version is chosen once; a witness then costs what it reads, not a whole table.
        self._first: dict[str, dict] = {}
        self._rest: dict[str, dict] = {}
        self._parameters: dict[str, tuple] = {}
        self._selected: dict[str, tuple] = {}

    def of(self, table: str, subject: str) -> list:
        """The rows of a table whose first column is the subject, as (key, parts), in the table's order."""
        if table not in self._first:
            index: dict = {}
            for key, (parts, _) in self.rows(table).items():
                if parts:
                    index.setdefault(parts[0], []).append((key, parts))
            self._first[table] = index
        return self._first[table].get(subject, [])

    def column(self, table: str, subject: str, index: int) -> set:
        return {parts[index] for _, parts in self.of(table, subject) if len(parts) > index}

    def fact(self, fid: str, subject: str) -> Val:
        f = self.facts[fid]
        if f["reads"] == "presence":
            return known(bool(self.of(f["table"], subject)))
        if f["reads"] == "input":
            t = self.ir["inputs"]
            ids = self.column_ids(t["subject"], subject) & self.column_ids(t["fact"], fid)
            table = t["integer" if f["type"] == "number" else "boolean"]
            values = {parts[1] for i in sorted(ids) for _, parts in self.of(table, i)}
        else:
            values = self.column(f["table"], subject, f.get("index", 1))
        missing = (Val("not_applicable", None, f"fact {fid} does not apply") if f["reads"] == "optional"
                   else Val("unknown", None, f"fact {fid} is missing"))
        return lookup(values, f["type"] == "number", missing, f"fact {fid}")

    def column_ids(self, table: str, value: str) -> set:
        if table not in self._rest:
            index: dict = {}
            for parts, _ in self.rows(table).values():
                index.setdefault(tuple(parts[1:]), set()).add(parts[0])
            self._rest[table] = index
        return set(self._rest[table].get((value,), ()))

    def parameter(self, pid: str) -> tuple[Val, str]:
        """(the value of a parameter leaf, the element it reads or ""). With `parameter_choice` the leaf
        gives a name: of its rows valid on valid_at and known by known_at, the latest known_from, then
        the latest valid_from; two values there are invalid, of equal rows the smallest id is named.
        Chosen once per program: the snapshots do not change while it checks."""
        if pid not in self._parameters:
            self._parameters[pid] = self._parameter(pid)
        return self._parameters[pid]

    def _parameter(self, pid: str) -> tuple[Val, str]:
        what = f"parameter {pid}"
        choice = self.ir.get("parameter_choice")
        if not choice:
            values = self.column(self.ir["parameters"], pid, 1)
            return lookup(values, True, Val("unknown", None, f"{what} is missing"), what), pid if values else ""

        def by_id(table: str) -> dict:
            out: dict = {}
            for parts, _ in self.rows(table).values():
                out.setdefault(parts[0], set()).add(parts[1])
            return out

        value, col = by_id(self.ir["parameters"]), {role: by_id(t) for role, t in choice.items()}
        rows = [(e, x, f, u) for e, names in col["name"].items() if pid in names for x in value.get(e, ())
                for f in col["valid_from"].get(e, ()) for u in col["valid_until"].get(e, ())]
        if "known_from" in col:
            rows = [(*r, k) for r in rows for k in col["known_from"].get(r[0], ())]
        if not rows:
            return Val("unknown", None, f"{what} is missing"), ""
        dates = [parts for parts, _ in self.rows(self.ir["as_of"]).values() if parts[0] == "as_of"]
        valid_at, known_at = {p[1] for p in dates}, {p[2] for p in dates}
        if not dates:
            return Val("unknown", None, "no evaluation date (as_of)"), ""
        if len(valid_at) + len(known_at) > 2:
            return Val("invalid", None, "more than one evaluation date (as_of)"), ""
        (va,), (ka,) = valid_at, known_at
        valid = [r for r in rows if r[2] <= va < r[3]]
        if not valid:
            return Val("unknown", None, f"{what} has no row valid on the evaluation date"), ""
        usable = [r for r in valid if r[4] <= ka] if "known_from" in col else valid
        if not usable:
            return Val("unknown", None, f"{what} is not known on the evaluation date"), ""
        rank = (lambda r: (r[4], r[2])) if "known_from" in col else (lambda r: (r[2],))
        top = max(map(rank, usable))
        best = [r for r in usable if rank(r) == top]
        if len({r[1] for r in best}) > 1:
            return Val("invalid", None, f"{what} has more than one value"), ""
        return lookup({best[0][1]}, True, None, what), min(r[0] for r in best)

    def view_of(self, e: dict) -> str:
        name, _, version = e["rule"].partition("@")
        return self.versions[e["rule"]]["view"] if version else self.rules[name]["view"]

    def select(self, rule: str) -> tuple:
        """W10: (the chosen version id, or None with the state of the rule, and the evaluation date); chosen
        once per program."""
        if rule not in self._selected:
            self._selected[rule] = self._select(rule)
        return self._selected[rule]

    def _select(self, rule: str) -> tuple:
        dates = [parts for parts, _ in self.rows(self.ir["as_of"]).values() if parts[0] == "as_of"]
        valid_at, known_at = {p[1] for p in dates}, {p[2] for p in dates}
        if not dates:
            return None, Val("unknown", None, "no evaluation date (as_of)"), ("", "")
        if len(valid_at) + len(known_at) > 2:
            return None, Val("invalid", None, "more than one evaluation date (as_of)"), ("", "")
        (va,), (ka,) = valid_at, known_at
        vs = [self.versions[v] for v in self.rules[rule]["versions"]]
        valid = [v for v in vs if v["valid_from"] <= va < v["valid_until"]]
        if not valid:
            return None, Val("not_applicable", None, f"no version of {rule} is valid on the evaluation date"), ("", "")
        known_ = [v for v in valid if v["known_from"] <= ka]
        if not known_:
            return None, Val("unknown", None, f"no version of {rule} is known on the evaluation date"), ("", "")
        best = max(known_, key=lambda v: (v["known_from"], v["valid_from"], v["version"]))
        return best["id"], None, (va, ka)


def reads(ir: dict, vid: str | None) -> set[str]:
    """Every relation an evaluation of a version reads, absences included (a missing fact is unknown, a
    missing row of `fact: <relation>` is false): a role must read each in full to see its result.
    Without a version, only the evaluation date."""
    out = {ir["as_of"]}
    versions = {v["id"]: v for v in ir.get("versions", [])}
    facts = {f["id"]: f for f in ir.get("facts", [])}
    if vid is None:
        return out

    def walk(e: dict) -> None:
        if "fact" in e:
            f = facts[e["fact"]]
            if f["reads"] == "input":
                t = ir["inputs"]
                out.update({t["subject"], t["fact"], t["integer" if f["type"] == "number" else "boolean"]})
            else:
                out.add(f["table"])
        elif "parameter" in e:
            out.add(ir["parameters"])
            out.update(ir.get("parameter_choice", {}).values())
        for a in e.get("args") or []:
            walk(a)

    for d in versions[vid]["definitions"]:
        walk(d["when"])
        walk(d["value"])
    return out


def published_views(ir: dict) -> set[str]:
    """The calculation views a publication holds: every rule's, and every version's named as rule@version."""
    pinned = set()

    def walk(e: dict) -> None:
        if "@" in (e.get("rule") or ""):
            pinned.add(e["rule"])
        for a in e.get("args") or []:
            walk(a)

    for v in ir.get("versions", []):
        for d in v["definitions"]:
            walk(d["when"])
            walk(d["value"])
    versions = {v["id"]: v["view"] for v in ir.get("versions", [])}
    return {r["view"] for r in ir.get("rules", [])} | {versions[v] for v in pinned}


def sources(ir: dict) -> dict[str, set[str] | None]:
    """Per published view, what it rests on besides its subject kind (O8, RV-S26): the relations the versions
    behind it read (`reads`, absences included) and the views those versions name as a premise. Behind a rule's
    view are all versions of the rule, behind a version's view that version. None: the program does not hold
    what the view names (the rule's versions, a version, a premise), so the view is not accounted for."""
    by_id = {v["id"]: v for v in ir.get("versions", [])}
    behind = {r["view"]: r.get("versions") for r in ir.get("rules", [])}
    for v in by_id.values():
        behind.setdefault(v["view"], [v["id"]])
    view_of_rule = {r.get("rule"): r["view"] for r in ir.get("rules", [])}

    def premises(e: dict, into: set) -> bool:
        name = e.get("rule")
        if name:
            view = by_id[name]["view"] if name in by_id else view_of_rule.get(name)
            if view is None:
                return False
            into.add(view)
        return all([premises(a, into) for a in e.get("args") or []])

    out: dict[str, set[str] | None] = {}
    for view in published_views(ir):
        ids, found = behind.get(view), reads(ir, None)
        known = ids is not None and all(i in by_id for i in ids)
        for i in ids if known else ():
            found |= reads(ir, i)
            known = known and all([premises(e, found) for d in by_id[i]["definitions"] for e in (d["when"], d["value"])])
        out[view] = found if known else None
    return out


def version_of(ir: dict, w: dict) -> str | None:
    """The version a witness evaluated: the chosen one of a rule, or the version of a version's view."""
    for v in ir.get("versions", []):
        if v["view"] == w["conclusion"]["relation"]:
            return v["id"]
    return f"{w['rule']}@{w['version']}" if w.get("version") else None


def _text(v) -> bool:
    return isinstance(v, str)


def _ref(r) -> bool:
    return isinstance(r, dict) and _text(r.get("relation")) and _text(r.get("key"))


def shaped(w) -> bool:
    """A calculation witness as contracts/proof.yaml has it: the fields the checks read, with their types."""
    if not (isinstance(w, dict) and _ref(w.get("conclusion")) and _text(w.get("rule")) and _text(w.get("state"))):
        return False
    if not all(_text(w.get(f, "")) for f in ("version", "valid_at", "known_at", "definition", "value", "reason")):
        return False
    premises, steps, read = w.get("premises", []), w.get("steps", []), w.get("reads")
    return (isinstance(premises, list) and isinstance(steps, list) and all(_ref(p) for p in premises)
            and isinstance(read, list) and all(_text(r) for r in read)
            and all(isinstance(s, dict) and _text(s.get("path")) and _text(s.get("state"))
                    and _text(s.get("value", "")) and _text(s.get("reason", "")) for s in steps))


# --- one witness ----------------------------------------------------------------------------------

def check(witnesses: list, ir: dict, rows) -> list[dict]:
    """The findings for every calculation witness of a set, in the form of check.py (reason, witness,
    relation, key, detail). `rows` as in Program."""
    p = Program(ir, rows)
    results, keys, findings = {}, {}, []
    for i, w in enumerate(witnesses):  # by view and subject: what a rule leaf reads
        ref = (w["conclusion"]["relation"], subject_of(w["conclusion"]["key"]))
        if ref in results:
            findings.append({"reason": "duplicate_witness", "witness": i, "relation": ref[0], "key": w["conclusion"]["key"]})
        results.setdefault(ref, recorded(w.get("state"), w.get("value", ""), w.get("reason", "")))
        keys.setdefault(ref, w["conclusion"]["key"])
    for i, w in enumerate(witnesses):
        ref = w["conclusion"]
        for reason, detail in Witness(p, w, results, keys).check():
            findings.append({"reason": reason, "witness": i, "relation": ref["relation"], "key": ref["key"], "detail": detail})
    # The calculation witnesses as a graph over their premises: acyclic, as the program's dependency order.
    graph = {(w["conclusion"]["relation"], w["conclusion"]["key"]): sorted({(x["relation"], x["key"]) for x in w.get("premises", [])})
             for w in witnesses}
    try:
        TopologicalSorter({k: [x for x in v if x in graph] for k, v in sorted(graph.items())}).prepare()
    except CycleError as e:
        findings.append({"reason": "cycle", "rows": [{"relation": r, "key": k} for r, k in sorted(set(e.args[1]))]})
    return findings


def total(ir: dict, rows) -> list[dict]:
    """Every published calculation view gives every element of the subject kind exactly one row with a
    state, in the complete snapshots (`rows` as in Program). No such row is `calc_row_missing`: there is no
    witness to refuse then, and the value would be absent without a word. A second one is
    `calc_row_duplicate`. Not for a role: it may read a subject and not see its calculated row."""
    views = sorted(published_views(ir))
    subjects = sorted({parts[0] for parts, _ in rows(ir["subject_table"]).values()}) if views else []
    findings = []
    for view in views:
        given: dict[str, list[str]] = {}
        for key, (parts, _) in rows(view).items():
            if len(parts) == 4 and parts[2] in SEVERITY:
                given.setdefault(parts[0], []).append(key)
        for subject in subjects:
            keys = sorted(given.get(subject, ()))
            if not keys:
                findings.append({"reason": "calc_row_missing", "relation": view, "key": encode_key([subject])})
            findings += [{"reason": "calc_row_duplicate", "relation": view, "key": key} for key in keys[1:]]
    return findings


def subject_of(key) -> str | None:
    """The subject of a calculation row (subject, value, state, reason); None for any other key."""
    try:
        parts = json.loads(key)
    except (TypeError, ValueError):
        return None
    return parts[0] if isinstance(parts, list) and len(parts) == 4 and all(isinstance(x, str) for x in parts) else None


class Witness:
    def __init__(self, p: Program, w: dict, results: dict, keys: dict):
        self.p, self.w, self.results, self.keys = p, w, results, keys
        self.nodes: dict[str, dict] = {}
        self.findings: list[tuple[str, str]] = []
        self.steps: dict[str, dict] = {}
        self.expected: list[str] = []

    def find(self, reason: str, detail: str) -> None:
        self.findings.append((reason, detail))

    def check(self) -> list[tuple[str, str]]:
        p, w = self.p, self.w
        relation, key = w["conclusion"]["relation"], w["conclusion"]["key"]
        kind, name = p.views.get(relation, (None, None))
        self.subject = subject_of(key)
        if kind is None or self.subject is None:
            self.find("calc_result", f"{relation} is no calculation view, or its key no calculation row")
            return self.findings
        if not p.of(p.ir["subject_table"], self.subject):
            self.find("calc_result", f"the subject is no element of {p.ir['subject']}")
            return self.findings
        rule = name if kind == "rule" else p.versions[name]["rule"]
        if w.get("rule") != rule:
            self.find("calc_result", f"rule {w.get('rule')} instead of {rule}")
        if kind == "rule":
            vid, fixed, dates = p.select(rule)
        else:
            vid, fixed, dates = name, None, ("", "")
        version = p.versions[vid]["version"] if vid else ""
        if sorted(w.get("reads", [])) != sorted(reads(p.ir, vid)):
            self.find("calc_reads", "the relations it reads differ")
        if (w.get("version", ""), w.get("valid_at", ""), w.get("known_at", "")) != (version, *dates):
            self.find("calc_version", f"version {version!r} on {dates}")
        for s in w.get("steps", []):
            if s.get("path") in self.steps:
                self.find("calc_path", f"{s.get('path')} twice")
            self.steps.setdefault(s.get("path"), s)
        if vid is None:
            if self.steps:
                self.find("calc_path", "steps without a version")
            self.result(fixed, "")
        else:
            self.version(p.versions[vid])
        self.premises()
        return self.findings

    def premises(self) -> None:
        """Exactly the conclusions its evaluated leaves read: the witness of a rule leaf, the rows of a
        derived relation for the subject. A premise more or less is `calc_premise`."""
        want = set()
        for path in self.expected:
            e = self.nodes[path]
            if "rule" in e:
                ref = (self.p.view_of(e), self.subject)
                if ref in self.keys:
                    want.add((ref[0], self.keys[ref]))
            elif "fact" in e and self.p.facts[e["fact"]]["reads"] in ("column", "presence"):
                table = self.p.facts[e["fact"]]["table"]
                want |= {(table, k) for k, _ in self.p.of(table, self.subject)}
        got = {(x["relation"], x["key"]) for x in self.w.get("premises", [])}
        for relation, key in sorted(got ^ want):
            self.find("calc_premise", f"{relation} {key}")

    # values of nodes: constants from the program, the rest as recorded
    def at(self, e: dict, path: str) -> Val | None:
        if node_kind(e) in CONSTANTS:
            return constant(e)
        s = self.steps.get(path)
        return None if s is None else recorded(s.get("state"), s.get("value", ""), s.get("reason", ""))

    def walk(self, e: dict, path: str) -> None:
        """The paths evaluation visits, a node before its arguments; an if only its chosen branch."""
        if node_kind(e) in CONSTANTS:
            return
        self.expected.append(path)
        self.nodes[path] = e
        args = e.get("args") or []
        if node_kind(e) != "if":
            for k, a in enumerate(args):
                self.walk(a, f"{path}/{k}")
            return
        self.walk(args[0], f"{path}/0")
        c = self.at(args[0], f"{path}/0")
        if c is not None and c.state == "known" and isinstance(c.value, bool):
            k = 1 if c.value else 2
            self.walk(args[k], f"{path}/{k}")

    def version(self, v: dict) -> None:
        defs = v["definitions"]
        for d in defs:
            self.walk(d["when"], f"{d['name']}/when")
        whens = [self.at(d["when"], f"{d['name']}/when") for d in defs]
        bad = [d["name"] for d, x in zip(defs, whens) if x is None or (x.state == "known" and not isinstance(x.value, bool))]
        if bad:  # a condition that is missing or no boolean decides nothing: never a silent pass
            self.paths()
            for d in defs:
                self.local(d["when"], f"{d['name']}/when")
            self.find("calc_result", f"no definition can be chosen: the condition of {', '.join(bad)} is unreadable")
            return
        memo: dict[str, Val] = {}

        def app(k: int) -> Val:
            if k not in memo:
                over = [j for j, o in enumerate(defs) if defs[k]["name"] in (o.get("before") or [])]
                negs = [a if a.state != "known" else known(not a.value) for a in (app(j) for j in over)]
                memo[k] = logic("and", [whens[k]] + negs) if over else whens[k]
            return memo[k]

        apps = [app(k) for k in range(len(defs))]
        hits = [k for k, a in enumerate(apps) if a.state == "known" and a.value is True]
        first = {st: next((a for a in apps if a.state == st), None) for st in ("invalid", "unknown", "not_applicable")}
        pick = None
        if first["invalid"]:
            want = first["invalid"]
        elif len(hits) > 1:
            want = Val("invalid", None, f"more than one definition of {v['id']} applies")
        elif first["unknown"]:
            want = first["unknown"]
        elif hits:
            pick = defs[hits[0]]
            self.walk(pick["value"], f"{pick['name']}/value")
            want = self.at(pick["value"], f"{pick['name']}/value")
        elif first["not_applicable"]:
            want = first["not_applicable"]
        else:
            want = Val("not_applicable", None, f"no definition of {v['id']} applies")
        self.paths()
        for d in defs:
            self.local(d["when"], f"{d['name']}/when")
        if pick is not None:
            self.local(pick["value"], f"{pick['name']}/value")
        if want is not None:
            self.result(want, pick["name"] if pick is not None else "")

    def paths(self) -> None:
        got = [s.get("path") for s in self.w.get("steps", [])]
        missing, extra = set(self.expected) - set(got), set(got) - set(self.expected)
        for path in sorted(missing):
            self.find("calc_path", f"{path} is missing")
        for path in sorted(extra):
            self.find("calc_path", f"{path} was not evaluated")
        if not missing and not extra and got != self.expected:
            self.find("calc_path", "the steps are not in evaluation order")

    def local(self, e: dict, path: str) -> None:
        """Every recorded step of a subtree against its arguments (or, for a leaf, the snapshots)."""
        kind = node_kind(e)
        if kind in CONSTANTS or path not in self.steps:
            return
        got = self.at(e, path)
        args = e.get("args") or []
        self.uses(e, kind, path)
        if got is None:
            self.find("calc_step", f"{path}: no canonical value")
        elif kind in ("fact", "parameter", "rule"):
            want = self.leaf(e, kind)
            if want is not None and not same(want, got):
                self.find("calc_leaf", f"{path}: {kind} {e[kind]}")
            if kind == "parameter" and self.steps[path].get("element", "") != self.p.parameter(e["parameter"])[1]:
                self.find("calc_leaf", f"{path}: parameter {e['parameter']} names another row")
        else:
            vals = [self.at(a, f"{path}/{k}") for k, a in enumerate(args)]
            if kind == "if" and vals[0] is not None:  # an untaken branch was not evaluated and does not count
                c = vals[0]
                vals = [c] + ([vals[1], known(False)] if c.value is True else [known(False), vals[2]]
                              if c.state == "known" else [known(False), known(False)])
            if all(x is not None for x in vals) and not same(safe(kind, vals), got):
                self.find("calc_step", f"{path}: {kind}")
        for k, a in enumerate(args):
            self.local(a, f"{path}/{k}")

    def uses(self, e: dict, kind: str, path: str) -> None:
        """A step names its node as the program has it: the operator, or the fact, parameter or rule
        and the relation it is read from. Another name is `calc_node`: an explanation would link the
        wrong row."""
        want = {"op": kind}
        if kind == "fact":
            want |= {"ref": e["fact"]} | ({"relation": self.p.facts[e["fact"]]["table"]} if self.p.facts[e["fact"]].get("table") else {})
        elif kind == "parameter":
            want |= {"ref": e["parameter"], "relation": self.p.ir["parameters"]}
        elif kind == "rule":
            want |= {"ref": e["rule"], "relation": self.p.view_of(e)}
        got = {k: self.steps[path][k] for k in ("op", "ref", "relation") if self.steps[path].get(k)}
        if got != want:
            self.find("calc_node", f"{path}: names {got.get('op')} {got.get('ref', '')} instead of {kind} {want.get('ref', '')}")

    def leaf(self, e: dict, kind: str) -> Val | None:
        if kind == "fact":
            return self.p.fact(e["fact"], self.subject)
        if kind == "parameter":
            return self.p.parameter(e["parameter"])[0]
        ref = (self.p.view_of(e), self.subject)
        if ref not in self.results:
            self.find("unproven_premise", f"{ref[0]} has no witness")
            return None
        return self.results[ref]

    def result(self, want: Val, definition: str) -> None:
        w = self.w
        got = recorded(w.get("state"), w.get("value", ""), w.get("reason", ""))
        if not same(got, want) or w.get("definition", "") != definition:
            self.find("calc_result", f"definition {definition!r}")
        key = w["conclusion"]["key"]
        if key != encode_key([self.subject, text(want.value), want.state, want.reason]):
            self.find("calc_result", "the row it concludes differs")
        if key not in self.p.rows(w["conclusion"]["relation"]):
            self.find("calc_result", "the row it concludes is not published")
