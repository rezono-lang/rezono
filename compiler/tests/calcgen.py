"""Random calculation programs and engine rows over the calc fixture pack, for property-based tests.

Programs use all 16 operators, versions with validity and knowledge dates, definitions with
overrides, a template, and references to earlier rules (with and without a version). Rows leave
values out (unknown, not applicable), give two values (invalid), and use numbers near 2**63 so
overflow is reached. The generator knows nothing of the compiler or the oracle.
"""

from __future__ import annotations

from hypothesis import strategies as st

SUBJECTS = ["i0", "i1", "i2"]
NUMBER_FACTS = ["item.amount", "item.extra", "x0", "x1", "x2", "entry_total.total"]
BOOLEAN_FACTS = ["item.flag", "item.note", "y0", "y1", "has_entry"]
PARAMETERS = ["s0", "s1", "s2"]
DATES = ["2025-01-01", "2026-01-01", "2026-07-01", "2027-01-01"]
LARGE = [2**31, 2**62, 2**63 - 1, -(2**63 - 1), 3 * 10**9]

TEMPLATE = {
    "id": "share",
    "arguments": ["base", "rate"],
    "definitions": [
        {"name": "positive", "when": {"op": "gte", "args": [{"arg": "base"}, {"integer": "0"}]},
         "value": {"op": "round", "args": [{"op": "ratio", "args": [{"arg": "base"}, {"arg": "rate"}, {"integer": "100"}]}]}},
        {"name": "small", "when": {"op": "lt", "args": [{"arg": "base"}, {"integer": "10"}]},
         "value": {"integer": "0"},
         "overrides": [{"definition": "share#positive", "reason": "klein"}]},
    ],
}


def numbers():
    return st.one_of(st.integers(-12, 12), st.integers(-12, 12), st.sampled_from(LARGE))


@st.composite
def expression(draw, typ: str, depth: int, rules: list[tuple[str, str, list[str]]]):
    """An expression of type number or boolean; `rules` are the earlier rules (name, type, versions)."""
    refs = [r for r in rules if r[1] == typ]
    if depth <= 0 or draw(st.integers(0, 4)) == 0:
        choice = draw(st.integers(0, 4 if refs else 3))
        if choice == 4:
            name, _, versions = draw(st.sampled_from(refs))
            v = draw(st.sampled_from([None] + versions))
            return {"rule": f"{name}@{v}" if v else name}
        if typ == "number":
            if choice == 0:
                return {"integer": str(draw(numbers()))}
            if choice == 1:
                return {"parameter": draw(st.sampled_from(PARAMETERS))}
            return {"fact": draw(st.sampled_from(NUMBER_FACTS))}
        if choice == 0:
            return {"boolean": draw(st.booleans())}
        return {"fact": draw(st.sampled_from(BOOLEAN_FACTS))}
    sub = lambda t: expression(t, depth - 1, rules)  # noqa: E731
    if typ == "number":
        op = draw(st.sampled_from(["add", "sub", "ratio", "min", "max", "floor", "ceil", "round", "pow", "if"]))
        if op in ("add", "min", "max"):
            return {"op": op, "args": draw(st.lists(sub("number"), min_size=2, max_size=3))}
        if op == "sub":
            return {"op": op, "args": [draw(sub("number")), draw(sub("number"))]}
        if op == "ratio":
            return {"op": op, "args": [draw(sub("number")) for _ in range(3)]}
        if op in ("floor", "ceil", "round"):
            return {"op": op, "args": [draw(sub("number"))]}
        if op == "pow":
            e = draw(st.one_of(st.sampled_from([-1, 0, 1, 2, 3, 5, 63, 64, 65]).map(lambda i: {"integer": str(i)}),
                               sub("number")))
            return {"op": op, "args": [draw(sub("number")), e]}
        return {"op": "if", "args": [draw(sub("boolean")), draw(sub("number")), draw(sub("number"))]}
    op = draw(st.sampled_from(["and", "or", "eq", "lt", "lte", "gte", "if"]))
    if op in ("and", "or"):
        return {"op": op, "args": draw(st.lists(sub("boolean"), min_size=2, max_size=3))}
    if op == "eq":
        t = draw(st.sampled_from(["number", "boolean"]))
        return {"op": op, "args": [draw(sub(t)), draw(sub(t))]}
    if op == "if":
        return {"op": "if", "args": [draw(sub("boolean")), draw(sub("boolean")), draw(sub("boolean"))]}
    return {"op": op, "args": [draw(sub("number")), draw(sub("number"))]}


@st.composite
def program(draw) -> dict:
    rules: list[tuple[str, str, list[str]]] = []
    docs = []
    for k in range(draw(st.integers(1, 4))):
        name, typ = f"r{k}", draw(st.sampled_from(["number", "boolean"]))
        versions = []
        for j in range(draw(st.integers(1, 2))):
            vf, vu = sorted(draw(st.lists(st.sampled_from(DATES), min_size=2, max_size=2, unique=True)))
            version = f"v{j}"
            doc = {"id": f"{name}@{version}", "rule": name, "version": version, "output": f"{name}.value",
                   "unit": "x", "valid_from": vf, "valid_until": vu, "known_from": draw(st.sampled_from(DATES))}
            if typ == "number" and draw(st.integers(0, 4)) == 0:
                doc["template"] = {"template": "share", "bindings": [
                    {"arg": "base", "value": draw(expression("number", 2, rules))},
                    {"arg": "rate", "value": draw(expression("number", 1, rules))}]}
            else:
                defs = []
                for i in range(draw(st.integers(1, 3))):
                    d = {"name": f"d{i}", "when": draw(expression("boolean", 2, rules)),
                         "value": draw(expression(typ, 3, rules))}
                    over = draw(st.lists(st.integers(0, i - 1), unique=True, max_size=i)) if i else []
                    if over:
                        d["overrides"] = [{"definition": f"{name}@{version}#d{o}", "reason": "voorrang"} for o in over]
                    defs.append(d)
                doc["definitions"] = defs
            docs.append(doc)
            versions.append(version)
        rules.append((name, typ, versions))
    out = {"format": "rede.calc/1", "pack": "calc", "subject": "item", "parameters": "setting.value",
           "inputs": {"kind": "entry", "subject": "item", "fact": "name", "integer": "number", "boolean": "truth"},
           "templates": [TEMPLATE], "rules": docs}
    if draw(st.booleans()):  # a parameter by its name, the row chosen by validity and knowledge date
        out["parameter_choice"] = {"name": "name", "valid_from": "valid_from", "valid_until": "valid_until",
                                   "known_from": "known_from"}
    return out


@st.composite
def rows(draw) -> dict[str, list[tuple]]:
    """Engine rows for the calc fixture pack: per table a list of tuples, as the fact loader gives them."""
    out: dict[str, list[tuple]] = {"item": [(s,) for s in SUBJECTS]}

    def values(strategy):
        return draw(st.lists(strategy, max_size=2, unique=True)) if draw(st.integers(0, 3)) else [draw(strategy)]

    for s in SUBJECTS:
        for attr, strategy in (("amount", numbers()), ("extra", numbers()), ("flag", st.booleans()), ("note", st.booleans())):
            out.setdefault(f"item__{attr}", []).extend((s, v) for v in values(strategy))
    n = 0
    for s in SUBJECTS:
        for fact, slot, strategy in ([(f, "number", numbers()) for f in ("x0", "x1", "x2")]
                                     + [(f, "truth", st.booleans()) for f in ("y0", "y1")]):
            for v in values(strategy):
                eid = f"e{n}"
                n += 1
                out.setdefault("entry", []).append((eid,))
                out.setdefault("entry__item", []).append((eid, s))
                out.setdefault("entry__name", []).append((eid, fact))
                out.setdefault(f"entry__{slot}", []).append((eid, v))
    for p in PARAMETERS:
        # Element p is what a leaf names by id; with a choice, p and its siblings are rows of the name p.
        for eid in [p] + [f"{p}~{k}" for k in range(draw(st.integers(0, 2)))]:
            out.setdefault("setting", []).append((eid,))
            for v in values(numbers()):
                out.setdefault("setting__value", []).append((eid, v))
            vf, vu = sorted(draw(st.lists(st.sampled_from(DATES), min_size=2, max_size=2, unique=True)))
            for slot, v in (("name", p), ("valid_from", vf), ("valid_until", vu), ("known_from", draw(st.sampled_from(DATES)))):
                if draw(st.integers(0, 7)):  # sometimes a slot is missing: the row is not a candidate
                    out.setdefault(f"setting__{slot}", []).append((eid, v))
    as_of = draw(st.lists(st.tuples(st.sampled_from(DATES), st.sampled_from(DATES)), max_size=2))
    if draw(st.integers(0, 4)):
        as_of = as_of[:1] or [("2026-03-01", "2026-10-01")]
    out["calc__as_of"] = [("as_of", a, b) for a, b in as_of]
    return {t: sorted(set(rs), key=repr) for t, rs in out.items()}
