"""One rule program as several Feldera pipelines that read each other's output.

The compiler cuts the program itself, within the budget of the deploy profile: an estimated build memory,
each view weighed by its kind, or a number of views (derived relations, materialized witnesses and
outcome checks). The indivisible unit is a recursive core,
a strongly connected component of the rule graph; modules are for the author and do not bind the cut.
Cores are placed in dependency order: into the part, or a new one, that keeps the chain of parts
shortest (every step costs latency); at equal depth one that does not deepen a part that later cores
read, then the one that adds the fewest relations between parts, then the lowest part. A part
only reads earlier parts. Given the previous partition, a core stays in its previous part whenever
that still fits and keeps the order, so a small rule change moves few views and Feldera's cache keeps
working. Only a recursive core that is on its own above the budget blocks. One relation that is not
recursive and costs more than the budget gets a part of its own: the budget is exceeded there, and the
compile warns (`over_budget`).

A derived relation that a later part reads is exported. Every part has one export view: a tagged union
of its exported relations (every column as text) plus an epoch marker. One stream per part keeps the
order of steps, so when the relay sees marker e, it has seen every change before it. That is the
processing barrier between pipelines; no clock, no polling of views (formal/Epochs.tla).

The seal's relations (`k__refused`, `k__accepted`) are base relations for the rules but views
of the `integrity` pipeline: computed there once and forwarded like an exported relation, so `integrity`
is the first producer of the chain and every part reads the same accepted rows (docs/compiler.md).
"""

from . import rules_sql as sql
from .sqltext import q

EXPORT = "export__out"
EPOCH = "epoch__in"


class TooBig(ValueError):
    """A recursive core that does not fit in one pipeline of the profile."""


def cores(prog):
    """Recursive cores of the derived relations, in dependency order; each core in evaluation order."""
    order = prog.derived()
    rank = {n: i for i, n in enumerate(order)}
    deps = {n: sorted((d for d in prog.deps(n) if d in rank), key=rank.get) for n in order}
    index, low, stack, on, comps = {}, {}, [], set(), []

    def visit(n):
        index[n] = low[n] = len(index)
        stack.append(n)
        on.add(n)
        for d in deps[n]:
            if d not in index:
                visit(d)
                low[n] = min(low[n], low[d])
            elif d in on:
                low[n] = min(low[n], index[d])
        if low[n] == index[n]:
            comp = []
            while True:
                d = stack.pop()
                on.discard(d)
                comp.append(d)
                if d == n:
                    break
            comps.append(sorted(comp, key=rank.get))

    for n in order:
        if n not in index:
            visit(n)
    return comps  # Tarjan yields a component after every component it reads


def views_by_kind(prog, name):
    """The engine views one derived relation costs, by kind: itself, its materialized witnesses and its
    checks, of an outcome or of a bound (rules_sql.views is their sum)."""
    return {"relation": 1, "witness": sum(1 for r in prog.rules_for(name) if sql.wants_witness(prog, r, "materialize")),
            "outcome": len(sql.checks(prog, name))}


def partition(prog, budget, previous=None, cost=None, whole=None, unit="views", *, relations=None):
    """Parts as lists of derived relations (see the module docstring). `previous` is the partition of an
    earlier compile (lists of relation names, by part place; an empty list for a place without a part).
    A part's place is stable: an empty part in the middle stays as an empty list. `cost` weighs a derived
    relation (default: its views), `budget` bounds a part and `whole` the program in one pipeline, which
    also holds what is not a rule (default: `budget`). `relations` can restrict this partition to one
    evaluation phase, provided it contains every member of each recursive core it touches. Raises TooBig
    for a recursive core above the budget; a relation above it that is not recursive gets a part of its own."""
    cost = cost or (lambda n: sql.views(prog, n))
    whole = budget if whole is None else whole
    comps = cores(prog)
    order = prog.derived()
    if relations is not None:
        selected = set(relations)
        order = [name for name in order if name in selected]
        comps = [core for core in comps if selected.intersection(core)]
        if any(not selected.issuperset(core) for core in comps):
            raise ValueError("a phase cannot split a recursive core")
    size = {i: sum(cost(n) for n in c) for i, c in enumerate(comps)}
    alone = set()  # one relation above the budget that is not recursive: a part of its own
    for i, c in enumerate(comps):
        if size[i] <= budget:
            continue
        if len(c) == 1 and (not prog.recursive(c[0]) or c[0] in prog.bounds):   # a bound is unrolled: no recursion
            alone.add(i)
        else:
            raise TooBig(f"the recursive core {', '.join(c)} costs {size[i]} {unit} (derived relations, "
                         f"materialized witnesses and outcome checks), more than the budget of {budget} per "
                         "pipeline; it cannot be split, so split its recursion or explain some relations on demand")
    if sum(size.values()) <= whole:
        return [order] if comps else []
    owner_of = {n: i for i, c in enumerate(comps) for n in c}

    def fits(i, content):
        """Within the budget, or the relation of `alone` in a part that is still empty."""
        return content["size"] + size[i] <= budget or (i in alone and not content["cores"])

    reads ={i: sorted({owner_of[d] for n in c for d in prog.deps(n) if d in owner_of} - {i})
             for i, c in enumerate(comps)}
    readers = {i: {k for k in reads if i in reads[k]} for i in reads}
    before = {n: p for p, names in enumerate(previous or []) for n in names}
    slots = len(previous or [])
    parts = [{"cores": [], "size": 0, "depth": 0} for _ in range(slots)]
    placed = {}

    def put(i, p):
        while len(parts) <= p:
            parts.append({"cores": [], "size": 0, "depth": 0})
        parts[p]["cores"].append(i)
        parts[p]["size"] += size[i]
        parts[p]["depth"] = max(parts[p]["depth"], 1, *(1 + parts[placed[j]]["depth"] for j in reads[i]
                                                         if placed[j] != p))
        placed[i] = p

    # 1. Stay: a core whose relations were all in one earlier part, and whose cores it reads stay too.
    stay = set()
    for i, c in enumerate(comps):
        p = {before.get(n) for n in c}
        if len(p) == 1 and None not in p and all(j in stay for j in reads[i]):
            p = p.pop()
            if fits(i, parts[p]) and all(placed[j] <= p for j in reads[i]):
                put(i, p)
                stay.add(i)
    # 2. The others, in dependency order: shortest chain, then fewest relations between parts.
    for i, c in enumerate(comps):
        if i in placed:
            continue
        lowest = max((placed[j] for j in reads[i]), default=0)
        best = None
        # every part from the lowest allowed, and a new empty part: it may keep the chain shorter
        for p in range(lowest, len(parts) + 1):
            content = parts[p] if p < len(parts) else {"cores": [], "size": 0, "depth": 0}
            if not fits(i, content):
                continue
            depth = max(content["depth"], 1, *(1 + parts[placed[j]]["depth"] for j in reads[i] if placed[j] != p))
            crossing = sum(1 for j in reads[i] if placed[j] != p)
            # at equal depth, do not deepen a part that cores still to come will read: they would be
            # pushed further down the chain
            raises = 0 < content["depth"] < depth and p < len(parts) and any(
                r not in placed for k in parts[p]["cores"] for r in readers[k])
            key = (depth, raises, crossing, p)
            if best is None or key < best[0]:
                best = (key, p)
        put(i, best[1])
    # A part keeps its place (and so its pipeline name) when an earlier one empties; only trailing
    # empty parts go. Without a previous partition no part is empty.
    out = [[n for i in sorted(part["cores"]) for n in comps[i]] for part in parts]
    while out and not out[-1]:
        out.pop()
    owner = {n: k for k, p in enumerate(out) for n in p}
    for k, p in enumerate(out):
        for n in p:
            for dep in prog.deps(n):
                if dep in owner and owner[dep] > k:
                    raise AssertionError(f"{n} in part {k} reads {dep} from a later part {owner[dep]}")
    return out


def over_budget(prog, parts, budget, cost=None):
    """The parts of a partition above the budget, as (relation, cost): each holds one relation that is
    not recursive (see `partition`). The compiler warns for each."""
    cost = cost or (lambda n: sql.views(prog, n))
    return [(p[0], sum(cost(n) for n in p)) for p in parts if sum(cost(n) for n in p) > budget]


def plan(prog, parts, upstream=frozenset()):
    """Per part: its views, the base tables and imported relations it reads, and what it exports.
    `upstream` names relations that another pipeline computes, such as the seal's relations or a
    calc selection: a part imports them instead of reading them as facts."""
    owner = {n: i for i, p in enumerate(parts) for n in p}
    out = []
    for i, p in enumerate(parts):
        reads = set().union(*(prog.deps(n) for n in p)) - set(p)
        imports = sorted(r for r in reads if r in owner or r in upstream)
        bases = sorted(r for r in reads if r not in owner and r not in upstream)
        out.append({"views": p, "imports": imports, "bases": bases, "exports": []})
    for i, part in enumerate(out):
        for r in part["imports"]:
            if r in owner and r not in out[owner[r]]["exports"]:
                out[owner[r]]["exports"].append(r)
    for part in out:
        part["exports"].sort()
    return out


def export_select(prog, part):
    """The export of a part: one row per exported row, tagged with its relation, every column as text
    (a0, a1, …), plus a row '#epoch' per epoch marker. The relay reads it as one ordered stream."""
    width = max(len(prog.relations[r].key) for r in part["exports"])
    sel = []
    for r in part["exports"]:
        rel = prog.relations[r]
        cols = [f"CAST({q(c.name)} AS VARCHAR)" for c in rel.key]
        cols += ["CAST('' AS VARCHAR)"] * (width - len(cols))
        columns = ", ".join(f"{c} AS a{j}" for j, c in enumerate(cols))
        sel.append(f"SELECT CAST('{r}' AS VARCHAR) AS rel, {columns} FROM {q(sql.relation_source(rel))}")
    sel.append("SELECT CAST('#epoch' AS VARCHAR) AS rel, CAST(e AS VARCHAR) AS a0"
               + "".join(f", CAST('' AS VARCHAR) AS a{j}" for j in range(1, width))
               + f" FROM {q(EPOCH)}")
    return "\nUNION ALL\n".join(sel)


def decode(prog, relation, cells):
    """An exported row back in the types of its relation: the text columns a0, a1, … in key order."""
    return tuple(int(v) if c.type == "integer" else v for c, v in zip(prog.relations[relation].key, cells))


def export_sql(prog, exports):
    """The epoch table and the export view of a producing pipeline."""
    return f"CREATE TABLE {q(EPOCH)} (e BIGINT NOT NULL);\n\nCREATE VIEW {q(EXPORT)} AS\n" \
        + export_select(prog, {"exports": exports}) + ";\n"


def part_sql(prog, part, witnesses="materialize"):
    # A seal import is declared with the base tables; other imports need explicit input declarations.
    inputs = [r for r in part["imports"] if prog.relations[r].role != "base"]
    code = sql.feldera(prog, witnesses=witnesses, relations=part["views"], inputs=inputs)
    if not part["exports"]:
        return code
    return code + "\n" + export_sql(prog, part["exports"])
