"""The migration plan of a schema operation (docs/compiler.md#the-migration-plan).

Every operation says what it does to the rows of a state as a plan: per table of the normal form a query over
the tables before it, in the old engine names, and the same backward, from the tables after it. One evaluator
runs the queries, keeping per row the input rows it came from; what no output came from is lost. The renaming
of tables, enum values and derived ids (operate.migrate) is the last step of every plan, and the rules read the
backward queries as definitions of the old predicates over the new tables (operate.rule_edits).

The queries are few, and their multiplicity is explicit: a row of the normal form is one record's value, and
two equal records give two rows, so a plain bag join is wrong where several sources reach one target.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import quote


def text(v) -> str:
    """A value as text, as the facts give it (an id may be a number, a date has ISO text)."""
    return v.isoformat() if hasattr(v, "isoformat") else ("true" if v is True else "false" if v is False else str(v))


@dataclass(frozen=True)
class Scan:
    """The rows of a table."""
    table: str


@dataclass(frozen=True)
class Keep:
    """The rows of `of` whose element (column 0) is an element of `among` (a semijoin), or with `drop`, is not
    (an antijoin). Each row of `of` stays a row: the rows of `among` only select."""
    of: object
    among: object
    drop: bool = False


@dataclass(frozen=True)
class Where:
    """The rows of `of` whose value (column 1), as text, is `value`."""
    of: object
    value: str


@dataclass(frozen=True)
class Element:
    """(x, ...) -> (x): each row of `of` as a row of a kind."""
    of: object


@dataclass(frozen=True)
class Const:
    """(x) -> (x, value): the rows of a kind table as rows of a slot with one value."""
    of: object
    value: object


@dataclass(frozen=True)
class Swap:
    """(x, v) -> (v, x): an arrow's rows read from its other end."""
    of: object


@dataclass(frozen=True)
class Derived:
    """(x, ...) -> (d, ...), where d is the id an element that x holds inline in the slot with element id
    `element` derives from x (rede_admission's embedded_id); with `pair`, (x) -> (x, d)."""
    of: object
    element: str
    pair: bool = False


@dataclass(frozen=True)
class Union:
    parts: tuple


@dataclass(frozen=True)
class Follow:
    """Values across a single-valued arrow. `link` holds the arrow's rows (source, target); the end `take`
    ("source" or "target") takes the values (rows (e, v) of `values`) of the element at the other end.

    `per` says what an element that several elements reach takes: "each", every reaching element's values
    (each element is reached once: an arrow is single-valued); "shared", the multiset its sources share, once,
    and sources that differ are a conflict; "first", the values of the first element by id. With `single`, an
    arrow source with more than one row is a conflict and brings nothing. Without `through`, the arrow's rows
    are no source of what comes out (they carry an identifier that goes: they are lost)."""
    values: object
    link: object
    take: str
    per: str
    single: bool = False
    what: str = ""  # the arrow and the slot, for the conflicts
    through: bool = True


@dataclass(frozen=True)
class Owned:
    """The elements of kind `seed` (or none), and those they or the slots `holders` own by a derived id
    (rede_admission's embedded_id), recursively; the rows (id,) of those whose root kind is `root`."""
    root: str
    seed: str | None
    seed_root: str | None
    holders: tuple
    owned: tuple  # (table, root of its kind, root of its range, element id of the slot) per owning slot


@dataclass(frozen=True)
class OneValue:
    """A check: an element of `kind` with more than one value in `table` is a conflict."""
    kind: str
    table: str
    slot: str


@dataclass(frozen=True)
class OneSource:
    """A check: an element that more than one element reaches across the arrow in `table` is a conflict."""
    table: str
    what: str


@dataclass(frozen=True)
class Once:
    """A check: an element with more than one row in `table` (two records of it) is a conflict."""
    table: str
    what: str


@dataclass(frozen=True)
class Covered:
    """A check for an abstract kind: every element of `kind` has a value in `table` among `values`."""
    kind: str
    table: str
    slot: str
    values: tuple


@dataclass
class Plan:
    """M and M⁻¹ of one operation, in the old engine names; tables not named stay as they are.

    forward: output table -> query over X; `gone`: input tables that have no output of their own. backward:
    old table -> query over M(X) renamed back, None when the operation is never lossless (a drop). `carry`:
    per check (kind, subject) of X, where its violations land: (kind, a query of element pairs (x, y) or None
    for x itself, whether to swap the pairs, and optionally the subject after when it changes). `access`: per
    output table whose rows reach other readers, the kind the rows are read as before and the kind of a value
    element."""
    forward: dict = field(default_factory=dict)
    gone: set = field(default_factory=set)
    backward: dict | None = None
    back_gone: set = field(default_factory=set)
    checks: list = field(default_factory=list)
    carry: dict = field(default_factory=dict)
    access: list = field(default_factory=list)


class Run:
    """One evaluation over one state: the rows with their lineage, and the conflicts found."""

    def __init__(self, rows: dict[str, list[tuple]]):
        self.rows = rows
        self.conflicts: list[str] = []
        self.memo: dict = {}

    def eval(self, q) -> list[tuple[tuple, frozenset]]:
        if isinstance(q, Scan):
            return [(r, frozenset({(q.table, i)})) for i, r in enumerate(self.rows.get(q.table, []))]
        if isinstance(q, Keep):
            among: dict[str, frozenset] = {}
            for r, src in self.eval(q.among):
                among[text(r[0])] = among.get(text(r[0]), frozenset()) | src
            if q.drop:
                return [(r, s) for r, s in self.eval(q.of) if text(r[0]) not in among]
            return [(r, s | among[text(r[0])]) for r, s in self.eval(q.of) if text(r[0]) in among]
        if isinstance(q, Where):
            return [(r, s) for r, s in self.eval(q.of) if text(r[1]) == q.value]
        if isinstance(q, Const):
            return [((r[0], q.value), s) for r, s in self.eval(q.of)]
        if isinstance(q, Element):
            return [((r[0],), s) for r, s in self.eval(q.of)]
        if isinstance(q, Swap):
            return [((r[1], r[0]), s) for r, s in self.eval(q.of)]
        if isinstance(q, Derived):
            def d(x):
                return f"{quote(text(x), safe='')}/{q.element}"
            return [(((r[0], d(r[0])) if q.pair else (d(r[0]),) + r[1:]), s) for r, s in self.eval(q.of)]
        if isinstance(q, Union):
            return [x for part in q.parts for x in self.eval(part)]
        if isinstance(q, Follow):
            return self.follow(q)
        if isinstance(q, Owned):
            return [((x,), frozenset()) for rt, x in sorted(self.owned(q)) if rt == q.root]
        raise TypeError(q)

    def follow(self, q: Follow) -> list[tuple[tuple, frozenset]]:
        near, far = (1, 0) if q.take == "source" else (0, 1)  # near: the end whose values move
        links: dict[str, list] = {}
        for r, s in self.eval(q.link):
            links.setdefault(text(r[0]), []).append((r, s))
        if q.single:
            for a, ls in sorted(links.items()):
                if len(ls) > 1:
                    self.conflicts.append(f"{a} has {len(ls)} values of {q.what.split(' ')[0]}")
            links = {a: ls for a, ls in links.items() if len(ls) == 1}
        values: dict[str, list] = {}
        for r, s in self.eval(q.values):
            values.setdefault(text(r[0]), []).append((r, s))
        out = []
        if q.per == "each":
            for _, ls in sorted(links.items()):
                for r, s in ls:
                    for (_, v), vs in values.get(text(r[near]), []):
                        out.append(((r[far], v), (s if q.through else frozenset()) | vs))
            return out
        groups: dict[str, list] = {}  # the far end -> its links, by the text of the near end
        for _, ls in sorted(links.items()):
            for r, s in ls:
                groups.setdefault(text(r[far]), []).append((text(r[near]), r, s))
        for ty, members in sorted(groups.items()):
            members.sort(key=lambda m: m[0])
            if q.per == "shared":
                bags = {repr(sorted(repr(v) for (_, v), _ in values.get(tx, []))) for tx, _, _ in members}
                if len(bags) > 1:
                    self.conflicts.append(f"{', '.join(tx for tx, _, _ in members)} share {q.what.split(' ')[0]} "
                                          f"{ty} but differ in {q.what.split(' ')[1]}")
                    continue
                lineage = frozenset().union(*(s | frozenset().union(*(vs for _, vs in values.get(tx, [])))
                                              for tx, _, s in members))
                y = members[0][1][far]
                out += [((y, v), lineage) for (_, v), _ in values.get(members[0][0], [])]
            else:  # first
                tx, r, s = members[0]
                out += [((r[far], v), s | vs) for (_, v), vs in values.get(tx, [])]
        return out

    def owned(self, q: Owned) -> set:
        memo = (q.seed, q.holders)
        if memo in self.memo:
            return self.memo[memo]
        gone: set = set()
        if q.seed is not None:
            gone |= {(q.seed_root, text(r[0])) for r in self.rows.get(q.seed, [])}
        grow = True
        while grow:
            grow = False
            for table, root, rng, element in q.owned:
                for x, v in self.rows.get(table, []):
                    if owner(v, element) != text(x):
                        continue
                    key = (rng, text(v))
                    if key not in gone and (table in q.holders or (root, text(x)) in gone):
                        gone.add(key)
                        grow = True
        self.memo[memo] = gone
        return gone

    def check(self, c) -> None:
        if isinstance(c, OneSource):
            sources: dict[str, set] = {}
            for x, y in self.rows.get(c.table, []):
                sources.setdefault(text(y), set()).add(text(x))
            for y, xs in sorted(sources.items()):
                if len(xs) > 1:
                    self.conflicts.append(f"{y} is reached by {', '.join(sorted(xs))} across {c.what}")
            return
        if isinstance(c, Once):
            for x, n in sorted(Counter(text(r[0]) for r in self.rows.get(c.table, [])).items()):
                if n > 1:
                    self.conflicts.append(f"{c.what} {x} has {n} records")
            return
        values: dict[str, set] = {}
        for x, v in self.rows.get(c.table, []):
            values.setdefault(text(x), set()).add(text(v))
        for (x,) in self.rows.get(c.kind, []):
            vs = sorted(values.get(text(x), set()))
            if isinstance(c, OneValue) and len(vs) > 1:
                self.conflicts.append(f"{x} has {len(vs)} values of {c.slot}")
            elif isinstance(c, Covered) and len(vs) <= 1 and not (vs and vs[0] in c.values):
                self.conflicts.append(f"{x} has {vs[0]!r}, which has no case" if vs else
                                      f"{x} has no {c.slot} and cannot stay in an abstract kind")


def owner(x, element: str) -> str | None:
    """The owner of a derived id made by the slot with element id `element` (rede_admission's embedded_id), or None."""
    from urllib.parse import unquote
    parts = str(x).split("/")
    if len(parts) in (2, 3) and parts[1] == element and (len(parts) == 2 or parts[2].isdigit()):
        return unquote(parts[0])
    return None


def evaluate(queries: dict, gone: set, rows: dict[str, list[tuple]], checks=()) -> tuple[dict, dict, list[str]]:
    """Apply one direction of a plan to one state: (rows after, lost rows, conflicts), in the input's names.
    A table without a query stays; a table in `gone` or with a query is consumed, and its rows that no output
    came from are lost."""
    run = Run(rows)
    for c in checks:
        run.check(c)
    out = {t: list(rs) for t, rs in rows.items() if t not in gone and t not in queries}
    used: set = set()
    for t, q in queries.items():
        got = run.eval(q)
        for r, s in got:
            used |= s
        if got:
            out[t] = [r for r, _ in got]
    lost = {}
    for t in sorted(set(queries) | set(gone)):
        rs = [r for i, r in enumerate(rows.get(t, [])) if (t, i) not in used]
        if rs:
            lost[t] = rs
    return out, lost, run.conflicts


def pairs(q, rows: dict[str, list[tuple]], swap: bool = False) -> dict[str, list[str]]:
    """The element pairs (x, y) a query gives (a row of a kind pairs its element with itself), or (y, x) with
    `swap`, as x -> [y] by text."""
    out: dict[str, list[str]] = {}
    for r, _ in Run(rows).eval(q):
        x, y = (r[0], r[-1]) if not swap else (r[-1], r[0])
        out.setdefault(text(x), []).append(text(y))
    return {x: sorted(ys) for x, ys in out.items()}


# --- The backward queries as definitions over the new tables (the rules) ---------------------------------------

class Var(str):
    """A variable of a definition: X the element, V the value, Y the element across an arrow."""


X, V, Y = Var("X"), Var("V"), Var("Y")


def definition(q, names: dict[str, str]) -> list[tuple[tuple, list]]:
    """The query as Datalog: alternatives (head, atoms), the head (X, V), (X, a constant) or, for a kind, (X,);
    the atoms (predicate, terms) in the new names."""
    if isinstance(q, Scan):
        return [((X, V), [(names.get(q.table, q.table), (X, V))])]
    if isinstance(q, Swap) and isinstance(q.of, Scan):
        return [((X, V), [(names.get(q.of.table, q.of.table), (V, X))])]
    if isinstance(q, Element):
        return [((X,), atoms) for _, atoms in definition(q.of, names)]
    if isinstance(q, Union):
        return [alt for part in q.parts for alt in definition(part, names)]
    if isinstance(q, Const):
        return [((X, q.value), [(names.get(q.of.table, q.of.table), (X,))])]
    if isinstance(q, Follow):
        link = atoms_of(q.link, names)
        if q.take == "target":  # the target end takes the values of the source: link(Y, X), values(Y, V)
            first, guard = (link[0][0], (Y, X)), [(g, (Y,)) for g, _ in link[1:]]
        else:  # the source end takes the values of the target: link(X, Y), values(Y, V)
            first, guard = (link[0][0], (X, Y)), [(g, (X,)) for g, _ in link[1:]]
        return [((X, V), [first] + guard + [(names.get(q.values.table, q.values.table), (Y, V))])]
    raise TypeError(q)


def atoms_of(q, names: dict[str, str]) -> list[tuple[str, tuple]]:
    """A link: an arrow's table, and the kinds its source must be in (Keep)."""
    if isinstance(q, Scan):
        return [(names.get(q.table, q.table), ())]
    if isinstance(q, Keep) and not q.drop:
        return atoms_of(q.of, names) + [(names.get(q.among.table, q.among.table), ())]
    raise TypeError(q)


def bag(rows: dict[str, list[tuple]]) -> dict[str, Counter]:
    return {t: Counter(map(repr, rs)) for t, rs in rows.items() if rs}
