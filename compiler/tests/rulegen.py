"""Generated rule programs and facts, by construction, for the M2 probe.

Nothing comes from an example pack. A program is drawn from a seed and a size: base relations, then
derived relations, each built from earlier ones with one of a fixed set of rule shapes. Every shape
the Datalog subset allows occurs: joins, constants, unions, stratified negation, linear recursion,
count/sum/min/max with a group key and without one (a body of aggregates only), comparisons and bounded
arithmetic. Sizes stay bounded: a join
only grows a relation by the average degree of a base relation, and recursion only runs over a forest.

    python rulegen.py SEED N_DERIVED > program.json
"""

import json
import random
import sys

from rezono_compiler.rules import with_strata

SHAPES = ("join", "filter", "constant", "union", "negation", "recursion", "count", "sum", "minmax",
          "threshold", "arithmetic")
# Also an aggregate over a key column (sum, min or max of a column the aggregate ranges over), and integer
# division with negative operands. Separate, so that the probe's programs (SHAPES) stay the ones it measured.
# And a body of aggregates only (`total`): a count, sum, min or max over a whole relation, without a group key.
ALL_SHAPES = SHAPES + ("keysum", "division", "total")
STR, INT = "string", "integer"


def _cols(types):
    return [{"name": f"c{i}", "type": t} for i, t in enumerate(types)]


def program(seed, n_derived, module_size=8, domain=1000, shapes=SHAPES):
    """A rule program with n_derived derived relations, in modules of module_size relations."""
    rnd = random.Random(seed)
    rels, rules = [], []
    sig = {}       # relation -> key types
    est = {}       # relation -> rough size, in multiples of the facts per base relation
    base_n = max(4, n_derived // 4)
    for i in range(base_n):
        kind = ("node", "edge", "forest", "weighted", "scored")[i % 5]
        name = f"b{i}"
        types = {"node": [STR], "edge": [STR, STR], "forest": [STR, STR], "weighted": [STR, STR],
                 "scored": [STR, INT]}[kind]
        rel = {"name": name, "role": "base", "key": _cols(types)}
        if kind == "weighted":
            rel["values"] = [{"name": "w", "type": INT}]
        rels.append(rel)
        sig[name] = types
        est[name] = 1.0
    kinds = {r["name"]: ("node", "edge", "forest", "weighted", "scored")[i % 5] for i, r in enumerate(rels)}

    def pick(types, exclude=(), limit=None, recent=True):
        cands = [n for n, t in sig.items() if t == types and n not in exclude and (limit is None or est[n] <= limit)]
        if not cands:
            return None
        if recent and len(cands) > 3 and rnd.random() < 0.7:
            cands = cands[-max(3, len(cands) // 4):]   # prefer recent relations: deeper programs
        return rnd.choice(cands)

    def base(kind):
        return rnd.choice([n for n, k in kinds.items() if k == kind])

    def lit(rel, terms, neg=False):
        return {"relation": rel, "terms": terms, "polarity": "negative" if neg else "positive"}

    def const(n):
        return f"e{rnd.randrange(domain)}" if n is None else n

    for i in range(n_derived):
        module = f"m{i // module_size}"
        name = f"d{i}"
        line = (i % module_size) * 4 + 1
        made = None
        for _ in range(20):
            shape = rnd.choice(shapes)
            made = _shape(shape, name, pick, base, lit, const, est, rnd)
            if made:
                break
        if not made:
            made = ([STR], [{"head": ["?x"], "body": [lit(base("node"), ["?x"])]}], 1.0)
        types, bodies, size = made
        rels.append({"name": name, "role": "derived", "key": _cols(types), "module": module,
                     "explain": "materialize" if i % 2 == 0 else "on_demand"})
        sig[name] = types
        est[name] = size
        for j, b in enumerate(bodies):
            rule = {"id": f"{name}_r{j}", "module": module, "head": {"relation": name, "terms": b["head"]},
                    "body": b["body"], "origin": {"file": f"rules/{module}.dl", "line": str(line + j)}}
            for k in ("aggregates", "conditions", "assignments"):
                if b.get(k):
                    rule[k] = b[k]
            rules.append(rule)
    doc = {"format": "rezono.rules/1", "pack": f"generated-{seed}-{n_derived}",
           "relations": sorted(rels, key=lambda r: r["name"]), "rules": sorted(rules, key=lambda r: r["id"])}
    return with_strata(doc)


def _shape(shape, name, pick, base, lit, const, est, rnd):
    """One derived relation: (key types, rule bodies, size estimate), or None if no operands fit."""
    if shape == "join":
        a = pick([STR, STR], limit=4.0)
        if a is None:
            return None
        b = base("edge")
        return [STR, STR], [{"head": ["?x", "?z"], "body": [lit(a, ["?x", "?y"]), lit(b, ["?y", "?z"])]}], est[a] * 1.0
    if shape == "filter":
        a, u = pick([STR, STR]), pick([STR])
        if a is None or u is None:
            return None
        return [STR, STR], [{"head": ["?x", "?y"], "body": [lit(a, ["?x", "?y"]), lit(u, ["?y"])]}], est[a]
    if shape == "constant":
        a = pick([STR, STR])
        if a is None:
            return None
        return [STR], [{"head": ["?x"], "body": [lit(a, ["?x", "?y"])],
                        "conditions": [{"op": "ne", "left": "?y", "right": const(None)}]}], est[a]
    if shape == "union":
        a, b = pick([STR]), pick([STR], recent=False)
        if a is None or b is None:
            return None
        return [STR], [{"head": ["?x"], "body": [lit(a, ["?x"])]},
                       {"head": ["?x"], "body": [lit(b, ["?x"])]}], est[a] + est[b]
    if shape == "negation":
        a, u = pick([STR, STR]), pick([STR])
        if a is None or u is None:
            return None
        return [STR, STR], [{"head": ["?x", "?y"], "body": [lit(a, ["?x", "?y"]), lit(u, ["?y"], neg=True)]}], est[a]
    if shape == "recursion":
        f = base("forest")
        return [STR, STR], [{"head": ["?x", "?y"], "body": [lit(f, ["?x", "?y"])]},
                            {"head": ["?x", "?z"], "body": [lit(name, ["?x", "?y"]), lit(f, ["?y", "?z"])]}], 4.0
    if shape in ("count", "sum", "minmax", "threshold"):
        u = pick([STR])
        if u is None:
            return None
        if shape in ("count", "threshold"):
            e = pick([STR, STR], recent=False)
            if e is None:
                return None
            agg = {"relation": e, "terms": ["?x", "_"], "function": "count", "as": "?n"}
        else:
            e = base("weighted")
            fn = "sum" if shape == "sum" else rnd.choice(["min", "max"])
            agg = {"relation": e, "terms": ["?x", "_"], "function": fn, "over": "w", "as": "?n"}
        if shape == "threshold":
            return [STR], [{"head": ["?x"], "body": [lit(u, ["?x"])], "aggregates": [agg],
                            "conditions": [{"op": "ge", "left": "?n", "right": str(rnd.randrange(1, 3))}]}], est[u]
        return [STR, INT], [{"head": ["?x", "?n"], "body": [lit(u, ["?x"])], "aggregates": [agg]}], est[u]
    if shape == "keysum":
        u, s = pick([STR]), pick([STR, INT], recent=False)
        if u is None or s is None:
            return None
        fn = rnd.choice(["sum", "min", "max"])
        agg = {"relation": s, "terms": ["?x", "_"], "function": fn, "over": "c1", "as": "?n"}
        return [STR, INT], [{"head": ["?x", "?n"], "body": [lit(u, ["?x"])], "aggregates": [agg]}], est[u]
    if shape == "arithmetic":
        s = pick([STR, INT])
        if s is None:
            return None
        k = str(rnd.randrange(1, 10))
        return [STR, INT], [{"head": ["?x", "?m"], "body": [lit(s, ["?x", "?n"])],
                             "assignments": [{"var": "?m", "op": "add", "left": "?n", "right": k}],
                             "conditions": [{"op": "lt", "left": "?n", "right": "50"}]}], est[s]
    if shape == "division":
        # The facts are 0..59, so ?d is negative for half of them; the divisor is a non-zero constant of
        # either sign, and the quotient truncates toward zero (docs/compiler.md, rules).
        s = pick([STR, INT])
        if s is None:
            return None
        k = str(rnd.choice([-7, -3, -2, -1, 1, 2, 3, 7, 60]))
        return [STR, INT], [{"head": ["?x", "?m"], "body": [lit(s, ["?x", "?n"])],
                             "assignments": [{"var": "?d", "op": "sub", "left": "?n", "right": "30"},
                                             {"var": "?m", "op": "div", "left": "?d", "right": k}]}], est[s]
    if shape == "total":
        # No literal, so no group key: one row at most. The first column of the aggregated atom is free or a
        # constant; most constants match no row, which gives a count and a sum of 0 and no min or max.
        first = rnd.choice(["_", const(None)])
        e = pick([STR, STR], recent=False)
        w = base("weighted")
        count = {"relation": e, "terms": [first, "_"], "function": "count", "as": "?n"}
        fn = rnd.choice(["sum", "min", "max"])
        fold = {"relation": w, "terms": [first, "_"], "function": fn, "over": "w", "as": "?t"}
        form = rnd.choice(["count", "fold", "both", "arithmetic"])
        if e is None or form == "fold":
            return [INT], [{"head": ["?t"], "body": [], "aggregates": [fold]}], 0.01
        if form == "count":
            return [INT], [{"head": ["?n"], "body": [], "aggregates": [count]}], 0.01
        if form == "both":
            return [INT, INT], [{"head": ["?n", "?t"], "body": [], "aggregates": [count, fold]}], 0.01
        return [INT, INT], [{"head": ["?n", "?m"], "body": [], "aggregates": [count, fold],
                             "assignments": [{"var": "?m", "op": "add", "left": "?n", "right": "?t"}],
                             "conditions": [{"op": "ge", "left": "?t", "right": "0"}]}], 0.01
    raise ValueError(shape)


def facts(doc, seed, rows, domain=None):
    """Facts for every base relation: {relation: sorted list of rows}, rows as lists of str/int.

    The domain defaults to the number of rows, so a base relation has average degree 1 and a join
    with it does not grow.
    """
    domain = domain or rows
    rnd = random.Random(seed * 7919 + 1)
    out = {}
    for rel in doc["relations"]:
        if rel["role"] != "base":
            continue
        types = [c["type"] for c in rel["key"]] + [c["type"] for c in rel.get("values", [])]
        keyed = {}
        if len(rel["key"]) == 2 and rel["name"] in _forests(doc):
            for x in range(1, min(rows, domain)):      # a forest: every node points to a lower one
                keyed[(f"e{x}", f"e{rnd.randrange(x)}")] = None
        else:
            for _ in range(rows):
                row = [f"e{rnd.randrange(domain)}" if t == STR else rnd.randrange(0, 60) for t in types]
                keyed.setdefault(tuple(row[:len(rel["key"])]), row[len(rel["key"]):])
        out[rel["name"]] = sorted([list(k) + (v or []) for k, v in keyed.items()], key=lambda r: [str(x) for x in r])
    return out


def _forests(doc):
    """Base relations that recursion runs over: the third of every five, by construction."""
    base = [r["name"] for r in doc["relations"] if r["role"] == "base"]
    return {n for n in base if int(n[1:]) % 5 == 2}


def change(doc, data, seed, domain):
    """One single-fact change, as a What-if sends it: (relation, row, 'insert'|'delete').

    Deletes and inserts alternate; the relation is drawn from the base relations that rules read.
    """
    rnd = random.Random(seed)
    read = sorted({b["relation"] for r in doc["rules"] for b in r["body"] + r.get("aggregates", [])
                   if b["relation"] in data})
    rel = rnd.choice(read)
    if rnd.random() < 0.5 and data[rel]:
        return rel, rnd.choice(data[rel]), "delete"
    spec = next(r for r in doc["relations"] if r["name"] == rel)
    types = [c["type"] for c in spec["key"]] + [c["type"] for c in spec.get("values", [])]
    while True:
        row = [f"e{rnd.randrange(domain)}" if t == STR else rnd.randrange(0, 60) for t in types]
        if rel in _forests(doc):
            row[1] = f"e{rnd.randrange(int(row[0][1:]) or 1)}" if row[0] != "e0" else row[1]
        if all(r[:len(spec['key'])] != row[:len(spec['key'])] for r in data[rel]):
            return rel, row, "insert"


if __name__ == "__main__":
    json.dump(program(int(sys.argv[1]), int(sys.argv[2])), sys.stdout, indent=1)


def days_program():
    """One rule with the reading `days`, as a view makes it (RV-C27): f(x, n) :- e(x), p(x, d), n = days(d).
    No rule file can write the operator, so the document is written here."""
    def atom(relation, *terms):
        return {"relation": relation, "terms": list(terms)}
    return with_strata({"format": "rezono.rules/1", "pack": "days", "relations": [
        {"name": "e", "role": "base", "key": _cols([STR])}, {"name": "p", "role": "base", "key": _cols([STR, STR])},
        {"name": "f", "role": "derived", "module": "days", "explain": "materialize", "key": _cols([STR, INT])}],
        "rules": [{"id": "f", "module": "days", "head": atom("f", "?x", "?n"),
                   "body": [dict(atom("e", "?x"), polarity="positive"), dict(atom("p", "?x", "?d"), polarity="positive")],
                   "assignments": [{"var": "?n", "op": "days", "left": "?d", "right": "1970-01-01"}],
                   "origin": {"file": "days", "line": "0"}}]})


def drift_program():
    """Observation against expectation, as rules (contracts/observation.yaml):
    an observation is (subject, value, event time, source position); drift is expected != observed."""
    s, i = STR, INT
    rels = [
        {"name": "desired", "role": "base", "key": _cols([s, s])},
        {"name": "observed", "role": "base", "key": [{"name": "subject", "type": s}, {"name": "v", "type": s},
                                                       {"name": "event_time", "type": i}, {"name": "source", "type": s}]},
        {"name": "seen", "role": "derived", "key": _cols([s]), "module": "drift", "explain": "on_demand"},
        {"name": "drift", "role": "derived", "key": _cols([s, s, s]), "module": "drift", "explain": "materialize"},
        {"name": "unobserved", "role": "derived", "key": _cols([s]), "module": "drift", "explain": "materialize"},
    ]
    lit = lambda r, t, neg=False: {"relation": r, "terms": t, "polarity": "negative" if neg else "positive"}  # noqa: E731
    obs = ["?x", "?o", "?t", "?src"]
    rules = [
        {"id": "seen", "module": "drift", "head": {"relation": "seen", "terms": ["?x"]}, "body": [lit("observed", obs)],
         "origin": {"file": "rules/drift.dl", "line": "1"}},
        {"id": "drift", "module": "drift", "head": {"relation": "drift", "terms": ["?x", "?e", "?o"]},
         "body": [lit("desired", ["?x", "?e"]), lit("observed", obs)],
         "conditions": [{"op": "ne", "left": "?e", "right": "?o"}], "origin": {"file": "rules/drift.dl", "line": "2"}},
        {"id": "unobserved", "module": "drift", "head": {"relation": "unobserved", "terms": ["?x"]},
         "body": [lit("desired", ["?x", "?e"]), lit("seen", ["?x"], neg=True)],
         "origin": {"file": "rules/drift.dl", "line": "3"}},
    ]
    return with_strata({"format": "rezono.rules/1", "pack": "generated-drift", "relations": rels, "rules": rules})


def drift_facts(n, seed=1):
    """n subjects with an expected value; 99 % observed equal, 1 % different, the rest unobserved."""
    rnd = random.Random(seed)
    desired, observed = [], []
    for k in range(n):
        v = f"v{rnd.randrange(4)}"
        desired.append([f"s{k}", v])
        r = rnd.random()
        if r < 0.98:
            observed.append([f"s{k}", v, k, f"src:{k}"])
        elif r < 0.99:
            observed.append([f"s{k}", v + "x", k, f"src:{k}"])
    return {"desired": desired, "observed": observed}


def observation(data, seed):
    """One new observation for a subject: (old row or None, new row). It flips drift on or off."""
    rnd = random.Random(seed)
    old = rnd.choice(data["observed"])
    new = [old[0], old[1][:-1] if old[1].endswith("x") else old[1] + "x", old[2] + 1_000_000, f"src:{old[2]}+1"]
    return old, new
