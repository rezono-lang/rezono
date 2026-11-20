"""Explanation as a question over the proof (R8, R10): the proof graph as one relation, and `trace` over it.

The proof graph of a role is one edge relation, the input of every walk:

    step(c_relation, c_key, p_relation, p_key, how, position)

`how` is `positive` or `negative` for a premise of the chosen witness (`position`: the literal's place in the
rule body, from the rule and the bindings) and `contributes` for a row of an aggregated group (`position`: the
aggregate's place in the rule). Keys are canonical key text, as in the snapshots. A `contributes` edge of a
`sum`, `min` or `max` also has a value, what its row gives the aggregate: published with the edge, not a
column of `step` (steps, `valued`).

A `trace` step is a rule program over `step`, `start` and the filters `keep` and `stop` (relation names).
A depth of k is unrolled into k strata, so the distance of a node is its stratum and no arithmetic runs in
recursion; depth `all` is plain linear recursion, without a distance. The program is Soufflé text: the
compiler reads it into the rule IR (rules_dl.read_program) and the batch backend runs it; the tests run
the same text in Soufflé, as the oracle (docs/formal.md, section 11, row Explanation).
"""

from __future__ import annotations

from collections import defaultdict

from . import rules_dl
from .explain import contribution, key_text
from .rules import is_var

STEP = [("c_relation", "string"), ("c_key", "string"), ("p_relation", "string"), ("p_key", "string"),
        ("how", "string"), ("position", "integer")]
INPUTS = {"step": STEP, "start": [("relation", "string"), ("key", "string")],
          "keep": [("relation", "string")], "stop": [("relation", "string")]}
DIRECTIONS = ("back", "forward")


def steps(prog, witnesses, rows: dict, valued: bool = False) -> list[tuple]:
    """The `step` rows of a set of chosen witnesses, sorted: premises from the rule body under the bindings.

    `rows` are the snapshots the witnesses were chosen on ({relation: tuples of canonical text, key columns
    then value columns}); an aggregate's contributors are the rows of its group there, found as the
    explainer finds them: every term of the aggregate atom that is not `_`, under the witness's bindings.

    With `valued`, a `contributes` row of a `sum`, `min` or `max` has a seventh element: what its row gives
    the aggregate, the value text the witness's `contributors_sha256` states for it (explain.contribution).
    So the edges of one aggregate are its contributors, readable: sorted `[p_key, value]`, they hash to it.
    Every other row keeps six: a premise gives no value, and a `count` reads no cell. The value is a function
    of the edge, so the six-column relation `step` that `trace` walks is these rows without it."""
    groups = {}

    def members(relation, fixed):
        at = tuple(i for i, _ in fixed)
        if (relation, at) not in groups:
            nk = len(prog.relations[relation].key)
            by = defaultdict(list)
            for r in rows.get(relation, ()):
                by[tuple(r[i] for i in at)].append((key_text(r[:nk]), r))
            groups[relation, at] = by
        return groups[relation, at].get(tuple(v for _, v in fixed), ())

    out = set()
    for w in witnesses:
        c = (w["conclusion"]["relation"], w["conclusion"]["key"])
        rule = prog.rules[w["rule_id"]]
        theta = {b["variable"]: b["value"] for b in w.get("bindings", ())}
        # Premises from the rule body under the bindings, so a position is the literal's place in the rule,
        # whatever order the witness lists its premises in (the checker accepts any order).
        for i, b in enumerate(rule.body):
            out.add((*c, b.atom.relation, key_text(theta[t] if is_var(t) else t for t in b.atom.terms), b.polarity, i))
        for i, a in enumerate(w.get("aggregates", ())):
            position = a.get("position", i)
            spec = rule.aggregates[position]
            atom = spec.atom
            fixed = [(j, theta[t] if is_var(t) else t) for j, t in enumerate(atom.terms) if t != "_"]
            for k, r in members(atom.relation, fixed):
                value = contribution(prog, spec, r) if valued else None
                out.add((*c, atom.relation, k, "contributes", position, *(() if value is None else (value,))))
    return sorted(out)


def program(direction: str, depth, keep: bool = False, stop: bool = False) -> str:
    """The Soufflé text of one `trace` step. `depth` is a whole number from 1, or "all".

    Output: `node(relation, key, distance)` for a depth, `node(relation, key)` for "all". The start is
    always a node (distance 0); `keep` limits the other nodes to the relations in `keep`; `stop` names
    relations the walk reaches but does not go past (the start is always expanded)."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction is back or forward, not {direction!r}")
    if depth != "all" and (not isinstance(depth, int) or isinstance(depth, bool) or depth < 1):
        raise ValueError(f"depth is a whole number from 1 or 'all', not {depth!r}")
    sym = lambda *names: ", ".join(f"{n}: symbol" for n in names)  # noqa: E731
    lines = [".decl step(c_relation: symbol, c_key: symbol, p_relation: symbol, p_key: symbol, how: symbol, "
             "position: number)", ".input step", f".decl start({sym('relation', 'key')})", ".input start"]
    for name, used in (("keep", keep), ("stop", stop)):
        if used:
            lines += [f".decl {name}(relation: symbol)", f".input {name}"]
    # edge(r, k, s, l): from node (r, k) one step on to (s, l), in the walk's direction.
    lines.append(f".decl edge({sym('from_relation', 'from_key', 'to_relation', 'to_key')})")
    lines.append("edge(r, k, s, l) :- step(r, k, s, l, _, _)." if direction == "back"
                 else "edge(r, k, s, l) :- step(s, l, r, k, _, _).")
    walk = "edge"
    if stop:
        walk = "walk"
        lines += [f".decl walk({sym('from_relation', 'from_key', 'to_relation', 'to_key')})",
                  "walk(r, k, s, l) :- edge(r, k, s, l), !stop(r)."]
    shown = ", keep(r)" if keep else ""
    if depth == "all":
        lines += [f".decl reach({sym('relation', 'key')})",
                  "reach(s, l) :- start(r, k), edge(r, k, s, l).",
                  f"reach(s, l) :- reach(r, k), {walk}(r, k, s, l).",
                  f".decl node({sym('relation', 'key')})",
                  "node(r, k) :- start(r, k).",
                  f"node(r, k) :- reach(r, k){shown}."]
    else:
        lines += [f".decl node({sym('relation', 'key')}, distance: number)",
                  f".decl at_0({sym('relation', 'key')})", "at_0(r, k) :- start(r, k).",
                  f".decl seen_0({sym('relation', 'key')})", "seen_0(r, k) :- at_0(r, k).",
                  "node(r, k, 0) :- at_0(r, k)."]
        for i in range(1, depth + 1):
            via = "edge" if i == 1 else walk
            lines += [f".decl at_{i}({sym('relation', 'key')})",
                      f"at_{i}(s, l) :- at_{i - 1}(r, k), {via}(r, k, s, l), !seen_{i - 1}(s, l).",
                      f"node(r, k, {i}) :- at_{i}(r, k){shown}."]
            if i < depth:
                lines += [f".decl seen_{i}({sym('relation', 'key')})",
                          f"seen_{i}(r, k) :- seen_{i - 1}(r, k).", f"seen_{i}(r, k) :- at_{i}(r, k)."]
    lines += [".output node"]
    return "\n".join(lines) + "\n"


def compile_program(direction: str, depth, keep: bool = False, stop: bool = False) -> tuple[str, dict]:
    """The text of a `trace` step and its rule IR document."""
    text = program(direction, depth, keep, stop)
    inputs = {n: c for n, c in INPUTS.items() if n in ("step", "start") or (n == "keep" and keep) or (n == "stop" and stop)}
    return text, rules_dl.read_program(text, f"trace/{direction}-{depth}", inputs, "trace")


def run(step_rows, start, direction: str, depth, keep=None, stop=None) -> set[tuple]:
    """Answer one `trace` step on the batch backend: the set of `node` rows (canonical text).

    `start` is a list of (relation, key); `keep` and `stop` are relation names, or None for no filter."""
    from . import batch
    from . import rules as ir

    _, doc = compile_program(direction, depth, keep is not None, stop is not None)
    prog = ir.load(doc)
    data = {"step": [list(r) for r in step_rows], "start": [list(s) for s in start]}
    if keep is not None:
        data["keep"] = [[r] for r in keep]
    if stop is not None:
        data["stop"] = [[r] for r in stop]
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    return batch.read(con, prog, ["node"])["node"]
