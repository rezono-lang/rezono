"""The exact reference for calculation rules, for tests only: Python fractions, evaluated per subject.

It reads the CalcProgram as written (its own template filling, version choice and default logic) and
the engine rows, and knows nothing of the SQL. Only the type of an input concept (number or boolean)
comes from the compiler, since that follows from use. The semantics are those of
docs/m2-pipelines-and-rule-ir.md ("Toestanden") and docs/compiler.md ("Rekenen").
"""

from __future__ import annotations

import datetime
from fractions import Fraction

BOUND = 2**63 - 1
STATES = ("invalid", "unknown", "not_applicable")


class Val(tuple):
    """(state, value, reason): value is a Fraction or bool when known, else None."""

    def __new__(cls, state, value=None, reason=""):
        return super().__new__(cls, (state, value, reason))

    state = property(lambda self: self[0])
    value = property(lambda self: self[1])
    reason = property(lambda self: self[2])


def known(v) -> Val:
    return Val("known", v, "")


def beyond(op: str) -> Val:
    """W8: a step beyond the bound has a value Rezono cannot hold: unknown, naming the bound and the operator."""
    return Val("unknown", None, f"beyond the bound of W8 in {op}")


def fits(x: Fraction) -> bool:
    return abs(x.numerator) <= BOUND and x.denominator <= BOUND


def iso(d) -> str:
    return d.isoformat() if isinstance(d, datetime.date) else str(d)


def substitute(e, env):
    if isinstance(e, dict) and "arg" in e and e["arg"] is not None:
        return env[e["arg"]]
    if isinstance(e, dict) and "op" in e:
        return {"op": e["op"], "args": [substitute(a, env) for a in e["args"]]}
    return e


class Oracle:
    def __init__(self, pack, doc: dict, rows: dict[str, list[tuple]], concept_types: dict[str, str]):
        self.pack, self.doc, self.types = pack, doc, concept_types
        self.rows = rows
        self.derived = {r["name"]: [c["name"] for c in r["key"]] for r in (pack.rules or {}).get("relations", [])
                        if r["role"] == "derived"}
        subject = doc["subject"]
        self.subject = subject
        self.subjects = sorted({r[0] for r in rows.get(subject, [])}, key=repr)
        self.columns: dict[str, dict] = {}
        for table, rs in rows.items():
            col: dict = {}
            for r in rs:
                if len(r) == 2:
                    col.setdefault(r[0], set()).add(r[1])
            self.columns[table] = col
        templates = {t["id"]: t for t in doc.get("templates") or []}
        self.versions = {}
        for r in doc.get("rules") or []:
            defs = r.get("definitions")
            if defs is None:
                t = templates[r["template"]["template"]]
                env = {b["arg"]: b["value"] for b in r["template"]["bindings"]}
                defs = []
                for d in t["definitions"]:
                    overrides = [{"definition": f"{r['id']}#{o['definition'].split('#', 1)[1]}"
                                  if o["definition"].startswith(f"{t['id']}#") else o["definition"]}
                                 for o in d.get("overrides") or []]
                    defs.append({"name": d["name"], "when": substitute(d["when"], env),
                                 "value": substitute(d["value"], env), "overrides": overrides})
            self.versions[r["id"]] = dict(r, definitions=defs)
        self.by_rule: dict[str, list[str]] = {}
        for vid, r in sorted(self.versions.items()):
            self.by_rule.setdefault(r["rule"], []).append(vid)
        as_of = [r for r in rows.get("calc__as_of", []) if r[0] == "as_of"]
        self.as_of = ({iso(r[1]) for r in as_of}, {iso(r[2]) for r in as_of}) if as_of else None
        inputs = doc.get("inputs")
        self.inputs: dict[tuple, set] = {}
        if inputs:
            kind = inputs["kind"]

            def col(slot):
                return self.columns.get(pack.slot(kind, slot).table, {}) if slot else {}

            subj, fact = col(inputs["subject"]), col(inputs["fact"])
            for typ in ("integer", "boolean"):
                values = col(inputs.get(typ))
                for eid, vs in values.items():
                    for s in subj.get(eid, ()):
                        for f in fact.get(eid, ()):
                            self.inputs.setdefault((typ, s, f), set()).update(vs)
        self.memo: dict = {}

    # --- leaves
    def lookup(self, values: set | None, number: bool, missing: Val, what: str) -> Val:
        if not values:
            return missing
        if len(values) > 1:
            return Val("invalid", None, f"{what} has more than one value")
        (v,) = values
        if number:
            if v < -BOUND:
                return Val("invalid", None, f"{what} does not fit 64 bits")
            return known(Fraction(v))
        return known(bool(v))

    def fact(self, fid: str, s) -> Val:
        relation, _, column = fid.partition(".")
        if relation in self.derived:  # a derived relation whose first column is the subject
            rs = [r for r in self.rows.get(relation, []) if r[0] == s]
            if not column:
                return known(bool(rs))
            values = {r[self.derived[relation].index(column)] for r in rs}
            return self.lookup(values, True, Val("unknown", None, f"fact {fid} is missing"), f"fact {fid}")
        kind, _, name = fid.partition(".")
        slot = self.pack.slot(kind, name) if kind in self.pack.kinds else None
        if slot is not None and kind in self.pack.ancestors(self.subject):
            number = slot.sql_type == "BIGINT"
            missing = (Val("not_applicable", None, f"fact {fid} does not apply") if not slot.required
                       else Val("unknown", None, f"fact {fid} is missing"))
            return self.lookup(self.columns.get(slot.table, {}).get(s), number, missing, f"fact {fid}")
        number = self.types[fid] == "number"
        values = self.inputs.get(("integer" if number else "boolean", s, fid))
        return self.lookup(values, number, Val("unknown", None, f"fact {fid} is missing"), f"fact {fid}")

    def parameter(self, pid: str) -> Val:
        return self.parameter_row(pid)[0]

    def parameter_row(self, pid: str) -> tuple[Val, str]:
        """(the value, the element it was read from, or "")."""
        kind, _, name = self.doc["parameters"].partition(".")
        values = self.columns.get(self.pack.slot(kind, name).table, {})
        choice = self.doc.get("parameter_choice")
        what = f"parameter {pid}"
        if not choice:
            v = self.lookup(values.get(pid), True, Val("unknown", None, f"{what} is missing"), what)
            return v, pid if values.get(pid) else ""
        if set(choice) == {"name"}:
            choice = dict(choice)
            for role in ("valid_from", "valid_until", "known_from"):
                slots = [s for s in self.pack.all_slots(kind) if s.role == role]
                if len(slots) == 1:
                    choice[role] = slots[0].name
        # By name: the rows valid on valid_at and known by known_at, the latest knowledge date first,
        # then the latest validity; each slot read by element.
        col = {role: self.columns.get(self.pack.slot(kind, slot).table, {}) for role, slot in choice.items()}
        rows = [(e, x, iso(f), iso(u)) for e, names in col["name"].items() if pid in names
                for x in values.get(e, ()) for f in col["valid_from"].get(e, ()) for u in col["valid_until"].get(e, ())]
        if "known_from" in col:
            rows = [(*r, iso(k)) for r in rows for k in col["known_from"].get(r[0], ())]
        if not rows:
            return Val("unknown", None, f"{what} is missing"), ""
        if self.as_of is None:
            return Val("unknown", None, "no evaluation date (as_of)"), ""
        if len(self.as_of[0]) + len(self.as_of[1]) > 2:
            return Val("invalid", None, "more than one evaluation date (as_of)"), ""
        (va,), (ka,) = self.as_of
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
        return self.lookup({best[0][1]}, True, None, what), min(r[0] for r in best)

    # --- expressions
    def eval(self, e: dict, s, path: str | None = None, steps: list | None = None) -> Val:
        """The value of an expression; with a path, every evaluated node that is no constant is also a
        step (path, value text, state, reason) in `steps`, a node before its arguments."""
        if path is None or e.get("integer") is not None or e.get("boolean") is not None:
            return self._eval(e, s, path, steps)
        k = len(steps)
        steps.append(None)
        v = self._eval(e, s, path, steps)
        steps[k] = (path, text(v.value) if v.state == "known" else "", v.state, "" if v.state == "known" else v.reason)
        if e.get("parameter") is not None and self.parameter_row(e["parameter"])[1]:
            steps[k] += (self.parameter_row(e["parameter"])[1],)
        return v

    def _eval(self, e: dict, s, path, steps) -> Val:
        def sub(k):
            return None if path is None else f"{path}/{k}"

        if "op" not in e or e.get("op") is None:
            (k, v), = [(k, v) for k, v in e.items() if v is not None]
            if k == "integer":
                return known(Fraction(int(v)))
            if k == "boolean":
                return known(bool(v))
            if k == "fact":
                return self.fact(v, s)
            if k == "parameter":
                return self.parameter(v)
            name, _, version = v.partition("@")
            return self.version(v, s)[0] if version else self.rule(name, s)[0]
        op, args = e["op"], e["args"]
        if op == "if":
            c = self.eval(args[0], s, sub(0), steps)
            if c.state != "known":
                return c
            return self.eval(args[1], s, sub(1), steps) if c.value else self.eval(args[2], s, sub(2), steps)
        vals = [self.eval(a, s, sub(k), steps) for k, a in enumerate(args)]
        if op in ("and", "or"):
            return logic(op, vals)
        for st in STATES:
            for v in vals:
                if v.state == st:
                    return Val(st, None, v.reason)
        xs = [v.value for v in vals]
        if op in ("add", "sub"):
            acc = xs[0]
            for x in xs[1:]:
                acc = acc + x if op == "add" else acc - x
                if not fits(acc):
                    return beyond(op)
            return known(acc)
        if op == "min":
            return known(min(xs))
        if op == "max":
            return known(max(xs))
        if op == "ratio":
            x, n, d = xs
            if d == 0:
                return Val("invalid", None, "division by zero in ratio")
            m = x * n
            if not fits(m) or not fits(m / d):
                return beyond("ratio")
            return known(m / d)
        if op == "floor":
            return known(Fraction(xs[0].numerator // xs[0].denominator))
        if op == "ceil":
            return known(Fraction(-((-xs[0].numerator) // xs[0].denominator)))
        if op == "round":
            x = xs[0]
            r = (2 * abs(x.numerator) + x.denominator) // (2 * x.denominator)
            return known(Fraction(-r if x < 0 else r))
        if op == "pow":
            b, ex = xs
            if ex.denominator != 1 or ex < 0:
                return Val("invalid", None, "exponent of pow is not a natural number")
            n = ex.numerator
            if n >= 64:
                if b == 0:
                    return known(Fraction(0))
                if b in (1, -1):
                    return known(Fraction(-1 if b == -1 and n % 2 else 1))
                return beyond("pow")
            r = b ** n
            return known(r) if fits(r) else beyond("pow")
        a, b = xs
        return known({"eq": a == b, "lt": a < b, "lte": a <= b, "gte": a >= b}[op])

    # --- rules
    def version(self, vid: str, s) -> tuple[Val, str]:
        key = ("version", vid, s)
        if key not in self.memo:
            self.memo[key] = self._version(vid, s)
        return self.memo[key]

    def _version(self, vid: str, s) -> tuple[Val, str]:
        defs = self.versions[vid]["definitions"]
        ids = [f"{vid}#{d['name']}" for d in defs]
        overriders = {i: [ids[k] for k, o in enumerate(defs) if i in [x["definition"] for x in o.get("overrides") or []]]
                      for i in ids}
        memo: dict[str, Val] = {}

        def app(i: str) -> Val:
            if i not in memo:
                when = self.eval(defs[ids.index(i)]["when"], s)
                if overriders[i]:
                    negs = [Val(v.state, (not v.value) if v.state == "known" else None, v.reason)
                            for v in (app(o) for o in overriders[i])]
                    memo[i] = logic("and", [when] + negs)
                else:
                    memo[i] = when
            return memo[i]

        apps = [app(i) for i in ids]
        hits = [k for k, a in enumerate(apps) if a.state == "known" and a.value]
        for a in apps:
            if a.state == "invalid":
                return Val("invalid", None, a.reason), ""
        if len(hits) > 1:
            return Val("invalid", None, f"more than one definition of {vid} applies"), ""
        for a in apps:
            if a.state == "unknown":
                return Val("unknown", None, a.reason), ""
        if hits:
            d = defs[hits[0]]
            return self.eval(d["value"], s), d["name"]
        for a in apps:
            if a.state == "not_applicable":
                return Val("not_applicable", None, a.reason), ""
        return Val("not_applicable", None, f"no definition of {vid} applies"), ""

    def rule(self, name: str, s) -> tuple[Val, str, str]:
        """(value, definition, version) of a rule: the version valid on the evaluation date and known
        by then, latest knowledge first."""
        if self.as_of is None:
            return Val("unknown", None, "no evaluation date (as_of)"), "", ""
        valid_at, known_at = self.as_of
        if len(valid_at) + len(known_at) > 2:
            return Val("invalid", None, "more than one evaluation date (as_of)"), "", ""
        (va,), (ka,) = valid_at, known_at
        vs = [self.versions[v] for v in self.by_rule[name]]
        valid = [v for v in vs if iso(v["valid_from"]) <= va < iso(v["valid_until"])]
        if not valid:
            return Val("not_applicable", None, f"no version of {name} is valid on the evaluation date"), "", ""
        known_ = [v for v in valid if iso(v["known_from"]) <= ka]
        if not known_:
            return Val("unknown", None, f"no version of {name} is known on the evaluation date"), "", ""
        best = max(known_, key=lambda v: (iso(v["known_from"]), iso(v["valid_from"]), str(v["version"])))
        val, d = self.version(best["id"], s)
        return val, d, str(best["version"])

    def steps(self, vid: str, s) -> tuple:
        """The evaluated nodes of a version for a subject: every condition, then the value of the
        definition that applies."""
        out: list = []
        defs = self.versions[vid]["definitions"]
        for d in defs:
            self.eval(d["when"], s, f"{d['name']}/when", out)
        _, name = self.version(vid, s)
        for d in defs:
            if d["name"] == name:
                self.eval(d["value"], s, f"{name}/value", out)
        return tuple(out)

    def witnesses(self) -> dict[str, dict]:
        """Per rule (and per version named as rule@version) and subject: (version, definition, steps)."""
        out: dict[str, dict] = {}
        for name in sorted(self.by_rule):
            for s in self.subjects:
                _, d, version = self.rule(name, s)
                out.setdefault(name, {})[str(s)] = (version, d, self.steps(f"{name}@{version}", s) if version else ())
        pinned = {e["rule"] for v in self.versions.values() for d in v["definitions"]
                  for e in walk(d["when"]) + walk(d["value"]) if "@" in (e.get("rule") or "")}
        for vid in sorted(pinned):
            for s in self.subjects:
                out.setdefault(vid, {})[str(s)] = (str(self.versions[vid]["version"]), self.version(vid, s)[1], self.steps(vid, s))
        return out

    def results(self) -> dict[str, dict]:
        """Per rule and subject: (state, value text, reason, definition, version)."""
        return {name: {s: (lambda r: (r[0].state, text(r[0].value), r[0].reason, r[1], r[2]))(self.rule(name, s))
                       for s in self.subjects}
                for name in sorted(self.by_rule)}


def walk(e: dict) -> list[dict]:
    """Every expression in e, e first."""
    return [e] + [x for a in (e.get("args") or []) if "op" in e and e["op"] for x in walk(a)]


def logic(op: str, vals: list[Val]) -> Val:
    for v in vals:
        if v.state == "invalid":
            return v
    decisive = op == "or"  # and: a known False decides; or: a known True decides
    if any(v.state == "known" and v.value == decisive for v in vals):
        return known(decisive)
    for st in ("unknown", "not_applicable"):
        for v in vals:
            if v.state == st:
                return Val(st, None, v.reason)
    return known(not decisive)


def text(v) -> str:
    """The canonical text of a value: "7", "-7/2", "true"; empty when not known."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v.numerator) if v.denominator == 1 else f"{v.numerator}/{v.denominator}"
