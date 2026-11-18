"""Random packs and fact sets for property-based tests, plus an independent reference for the violation views.

The generator knows nothing of the compiler. It writes a pack (LinkML, pack.yaml, labels, messages, channels),
builds valid facts, optionally injects one error, and predicts the engine rows. `reference` computes the
violations from those rows with plain Python sets, following the semantics in docs/compiler.md.
"""

from __future__ import annotations

import datetime
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from urllib.parse import quote

import yaml
from hypothesis import strategies as st

LAYERS = ["source", "facts", "conclusions", "plan", "output", "observation"]
TYPES = ["string", "integer", "boolean", "date", "enum"]
ERRORS = ["totality", "functionality", "reference", "value_range", "identification", "unique", "path_equation",
          "cardinality", "pattern"]
# Patterns every generated plain string ('x', 'y', 'z') matches and the injected '9' misses.
PATTERNS = ["^[a-z]", r"^\D", "[a-z]$", r"^[x-z]\w*$"]
STRINGS = ["x", "y", "z"]
MESSAGES = Path(__file__).resolve().parent / "fixtures" / "minimal" / "messages" / "nl.mf2"


@dataclass
class GSlot:
    name: str
    kind: str
    required: bool
    arrow: bool = False
    range: str = ""  # target kind, or type
    inlined: bool = False
    enum: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    multivalued: bool = False
    min_card: int | None = None
    max_card: int | None = None
    patterns: list[str] = field(default_factory=list)
    constant: object = None

    @property
    def table(self):
        return f"{self.kind}__{self.name}"


@dataclass
class GKind:
    name: str
    parent: str | None
    identifier: bool
    layer: str
    module: str = "m0"
    slots: list[GSlot] = field(default_factory=list)
    keys: list[tuple[str, list[str]]] = field(default_factory=list)
    equations: list[tuple[str, list[str], list[str]]] = field(default_factory=list)


@dataclass
class Spec:
    kinds: dict[str, GKind]
    enums: dict[str, list[str]]

    def ancestors(self, k):
        out = []
        while k:
            out.append(k)
            k = self.kinds[k].parent
        return out

    def slot(self, k, name):
        return next(s for a in self.ancestors(k) for s in self.kinds[a].slots if s.name == name)

    def all_slots(self, k):
        return [s for a in self.ancestors(k) for s in self.kinds[a].slots]

    def sub(self, k, of):
        return of in self.ancestors(k)

    def refused(self) -> bool:
        """A path equation that steps over a multivalued arrow: the compiler must refuse the pack."""
        return any(self.slot(at, step).multivalued
                   for k, kind in self.kinds.items() for _, left, _ in kind.equations
                   for at, step in walk(self, k, left))


def draw_spec(draw) -> Spec:
    kinds: dict[str, GKind] = {}
    n = draw(st.integers(1, 6))
    for i in range(n):
        id_kinds = [k for k, v in kinds.items() if v.identifier]
        parent = draw(st.sampled_from(id_kinds)) if id_kinds and draw(st.booleans()) else None
        identifier = True if parent or i == 0 else draw(st.integers(0, 3)) > 0
        kinds[f"k{i}"] = GKind(f"k{i}", parent, identifier, draw(st.sampled_from(LAYERS)),
                               draw(st.sampled_from(["m0", "m1"])))
    enums = {f"e{i}": [f"v{j}" for j in range(draw(st.integers(1, 3)))] for i in range(draw(st.integers(1, 2)))}
    for k in kinds.values():
        for j in range(draw(st.integers(0, 3))):
            t = draw(st.sampled_from(TYPES))
            s = GSlot(f"{k.name}_a{j}", k.name, draw(st.booleans()), range=t)
            if t == "enum":
                s.enum = s.range = draw(st.sampled_from(sorted(enums)))
            if t == "integer" and draw(st.booleans()):
                s.minimum = draw(st.integers(-5, 5))
                s.maximum = s.minimum + draw(st.integers(0, 10)) if draw(st.booleans()) else None
            many(draw, s)
            if t == "string" and draw(st.booleans()):
                s.patterns = draw(st.lists(st.sampled_from(PATTERNS), min_size=1, max_size=2, unique=True))
            if t == "enum" and draw(st.integers(0, 2)) == 0:
                s.patterns = ["^v[0-9]$"]  # every generated enum value matches
            if not s.multivalued and t in ("string", "integer") and draw(st.integers(0, 3)) == 0:
                s.constant = "x" if t == "string" else (s.minimum if s.minimum is not None else 0)
            k.slots.append(s)
        for j in range(draw(st.integers(0, 2))):
            targets = sorted(kinds) if k.identifier else sorted(x for x, v in kinds.items() if v.identifier)
            target = draw(st.sampled_from(targets))
            s = GSlot(f"{k.name}_r{j}", k.name, draw(st.booleans()), arrow=True, range=target,
                      inlined=not kinds[target].identifier)
            many(draw, s)
            k.slots.append(s)
    inlined = {s.range for k in kinds.values() for s in k.slots if s.inlined}
    for k in kinds.values():
        if not k.identifier and k.name not in inlined:
            k.identifier = True
    spec = Spec(kinds, enums)
    rights, lefts = set(), set()
    for k in kinds.values():
        strings = [s for s in k.slots if s.range == "string" and not s.multivalued]
        for s in strings[:1]:  # a key slot gets unique values, so no pattern or constant
            s.patterns, s.constant = [], None
        if strings and draw(st.booleans()):
            arrows = [s.name for s in spec.all_slots(k.name) if s.arrow and not s.inlined and not s.multivalued]
            extra = [draw(st.sampled_from(arrows))] if arrows and draw(st.booleans()) else []
            k.keys.append((f"{k.name}_key", [strings[0].name] + extra))
        for r in [s for s in k.slots if s.arrow and not s.inlined and not s.multivalued]:
            if r.table in lefts or r.table in rights or not draw(st.booleans()):
                continue
            paths = candidate_paths(spec, k.name, r, rights | {r.table})
            if paths:
                left = draw(st.sampled_from(paths))
                k.equations.append((f"{k.name}_eq{len(k.equations)}", left, [r.name]))
                rights.add(r.table)
                kind = k.name
                for step in left:
                    s = spec.slot(kind, step)
                    lefts.add(s.table)
                    kind = s.range
    for k in kinds.values():  # a key must not contain a right arrow (its value is computed)
        k.keys = [(n, ns) for n, ns in k.keys if not any(spec.slot(k.name, x).table in rights for x in ns)]
    return spec


def walk(spec, kind, path):
    """(kind, step) along a path."""
    out = []
    for step in path:
        out.append((kind, step))
        kind = spec.slot(kind, step).range
    return out


def many(draw, s: GSlot) -> None:
    """Maybe make a slot multivalued, with a cardinality that any non-empty pool of values can meet."""
    if draw(st.integers(0, 2)) == 0:
        s.multivalued = True
        if draw(st.booleans()):
            s.min_card = draw(st.integers(0, 1))
            s.max_card = draw(st.sampled_from([None, 1, 2, 3]))


def candidate_paths(spec: Spec, kind: str, r: GSlot, banned: set) -> list[list[str]]:
    out, frontier = [], [([], kind)]
    for _ in range(3):
        nxt = []
        for path, at in frontier:
            for s in spec.all_slots(at):
                if s.arrow and s.table not in banned:  # a multivalued step makes the pack refused
                    p = path + [s.name]
                    nxt.append((p, s.range))
                    if spec.sub(s.range, r.range):
                        out.append(p)
        frontier = nxt
    return sorted(out)


# ---- writing the pack ----

def write_pack(spec: Spec, d: Path) -> None:
    classes = {}
    for k in spec.kinds.values():
        attrs = {"id": {"identifier": True}} if k.identifier and not k.parent else {}
        for s in k.slots:
            a = {"required": s.required, "range": s.range.upper() if s.arrow or s.enum else s.range}
            if s.inlined:
                a["inlined"] = True
            if s.minimum is not None:
                a["minimum_value"] = s.minimum
            if s.maximum is not None:
                a["maximum_value"] = s.maximum
            if s.multivalued:
                a["multivalued"] = True
            if s.min_card is not None:
                a["minimum_cardinality"] = s.min_card
            if s.max_card is not None:
                a["maximum_cardinality"] = s.max_card
            if s.patterns:
                a["pattern"] = s.patterns[0]
                if len(s.patterns) > 1:  # the second pattern comes from the slot's type
                    a["range"] = f"T_{k.name}_{s.name}".upper()
            if s.constant is not None:
                a["equals_string" if isinstance(s.constant, str) else "equals_number"] = s.constant
            attrs[s.name] = a
        c = {"attributes": attrs, "annotations": {"layer": k.layer}}
        if k.parent:
            c["is_a"] = k.parent.upper()
        if k.keys:
            c["unique_keys"] = {n: {"unique_key_slots": ns} for n, ns in k.keys}
        if k.equations:
            c["annotations"]["path_equations"] = [{"name": n, "left": ".".join(l), "right": ".".join(r)}
                                                  for n, l, r in k.equations]
        classes[k.name.upper()] = c
    types = {f"T_{k.name}_{s.name}".upper(): {"typeof": "string", "pattern": s.patterns[1]}
             for k in spec.kinds.values() for s in k.slots if len(s.patterns) > 1}
    (d / "schema").mkdir(parents=True)
    for m, other in (("m0", "m1"), ("m1", "m0")):  # two modules that import each other
        schema = {"id": f"https://rezono.example/generated/{m}", "name": f"generated_{m}", "in_language": "nl",
                  "imports": ["linkml:types", other], "default_range": "string",
                  "classes": {n: c for n, c in classes.items() if spec.kinds[n.lower()].module == m}}
        if m == "m0":
            schema["enums"] = {e.upper(): {"permissible_values": {v: {} for v in vs}} for e, vs in spec.enums.items()}
            schema["types"] = types
        (d / "schema" / f"{m}.yaml").write_text(yaml.safe_dump(schema, sort_keys=True))
    (d / "pack.yaml").write_text(yaml.safe_dump({"name": "generated", "version": "0", "default_language": "nl"}))
    (d / "channels.yaml").write_text(yaml.safe_dump({"kinds": [{"kind": k, "shape": "rect"} for k in spec.kinds]}))
    (d / "labels").mkdir()
    (d / "labels" / "nl.yaml").write_text(yaml.safe_dump({k: f"soort {k}" for k in spec.kinds}))
    (d / "messages").mkdir()
    shutil.copy(MESSAGES, d / "messages" / "nl.mf2")


def child_id(e: str, s: GSlot, n: int) -> str:
    base = f"{quote(e, safe='')}/{s.kind}.{s.name}"
    return f"{base}/{n}" if s.multivalued else base


# ---- facts ----

class State:
    """Elements and their values; an inlined child gets the id '<escaped parent id>/<kind>.<slot>'."""

    def __init__(self, spec):
        self.spec = spec
        self.kind: dict[str, str] = {}
        self.top: list[str] = []
        self.values: dict[str, dict[str, list]] = defaultdict(dict)
        self.duplicated: list[str] = []

    def elements_of(self, k):
        return sorted(e for e, ek in self.kind.items() if self.spec.sub(ek, k))

    def follow(self, e, path):
        at = {e}
        for step in path:
            at = {v for x in at for v in self.values[x].get(step, [])}
        return at

    def records(self) -> dict[str, list[dict]]:
        out = defaultdict(list)
        for e in self.top + self.duplicated:
            out[self.kind[e]].append({"id": e} | self.record(e))
        return dict(out)

    def record(self, e):
        rec = {}
        for name, vs in self.values[e].items():
            s = self.spec.slot(self.kind[e], name)
            vs = [self.record(v) if s.inlined else v for v in vs]
            rec[name] = vs if s.multivalued or len(vs) != 1 else vs[0]
        return rec

    def rows(self) -> dict[str, list[tuple]]:
        out = defaultdict(list)

        def emit(e):
            for a in self.spec.ancestors(self.kind[e]):
                out[a].append((e,))
            for name, vs in self.values[e].items():
                s = self.spec.slot(self.kind[e], name)
                for v in vs:
                    if s.inlined:
                        emit(v)
                    out[s.table].append((e, v))

        for e in self.top + self.duplicated:
            emit(e)
        return dict(out)


def draw_value(draw, spec, s, e, state):
    if s.constant is not None:
        return s.constant
    if s.arrow:
        return draw(st.sampled_from(state.elements_of(s.range)))
    if s.enum:
        return draw(st.sampled_from(spec.enums[s.enum]))
    if s.range == "integer":
        lo = -20 if s.minimum is None else s.minimum
        return draw(st.integers(lo, lo + 20 if s.maximum is None else s.maximum))
    if s.range == "boolean":
        return draw(st.booleans())
    if s.range == "date":
        return draw(st.dates(datetime.date(2000, 1, 1), datetime.date(2030, 12, 31)))
    keyed = any(s.name in ns for _, ns in spec.kinds[s.kind].keys)
    return f"u-{e}" if keyed else draw(st.sampled_from(STRINGS))


def pool(spec, s, state) -> list:
    """Distinct values a multivalued slot can take."""
    if s.arrow:
        return state.elements_of(s.range)
    if s.enum:
        return list(spec.enums[s.enum])
    if s.range == "integer":
        lo = -20 if s.minimum is None else s.minimum
        return list(range(lo, (lo + 20 if s.maximum is None else s.maximum) + 1))
    if s.range == "boolean":
        return [False, True]
    if s.range == "date":
        return [datetime.date(2020, 1, d) for d in range(1, 6)]
    return list(STRINGS)


def draw_state(draw, spec: Spec) -> State:
    state = State(spec)
    for k in spec.kinds.values():
        if k.identifier:
            for j in range(draw(st.integers(1, 3))):
                state.kind[f"{k.name}-{j}"] = k.name
                state.top.append(f"{k.name}-{j}")
    rights = {(k.name, r[0]) for k in spec.kinds.values() for _, _, r in k.equations}

    def fill(e):
        for s in spec.all_slots(state.kind[e]):
            if s.multivalued:
                lo = max(s.min_card or 0, 1 if s.required else 0)
                hi = 3 if s.max_card is None else s.max_card
                n = draw(st.integers(lo, max(lo, hi)))
                if n == 0:
                    continue
                if s.inlined:
                    children = [child_id(e, s, i) for i in range(1, n + 1)]
                    state.values[e][s.name] = children
                    for c in children:
                        state.kind[c] = s.range
                        fill(c)
                else:
                    options = pool(spec, s, state)
                    state.values[e][s.name] = draw(st.lists(st.sampled_from(options), min_size=min(n, len(options)),
                                                            max_size=min(n, len(options)), unique=True))
                continue
            if (s.kind, s.name) in rights or not (s.required or draw(st.booleans())):
                continue
            if s.inlined:
                child = child_id(e, s, 1)
                state.kind[child] = s.range
                state.values[e][s.name] = [child]
                fill(child)
            else:
                state.values[e][s.name] = [draw_value(draw, spec, s, e, state)]

    for e in list(state.top):
        fill(e)
    for k in spec.kinds.values():
        for _, left, (r,) in k.equations:
            s = spec.slot(k.name, r)
            for e in state.elements_of(k.name):
                ends = state.follow(e, left)
                if len(ends) == 1:
                    state.values[e][r] = sorted(ends)
                elif s.required or draw(st.booleans()):
                    state.values[e][r] = [draw_value(draw, spec, s, e, state)]
    return state


def inject(draw, spec: Spec, state: State, error: str):
    """Inject one error; return the (view, row) it must produce, or None if this state has no place for it."""
    els = sorted(state.kind)
    slots = [(e, s) for e in els for s in spec.all_slots(state.kind[e]) if s.name in state.values[e]]
    if error == "totality":
        c = [(e, s) for e, s in slots if s.required and not s.inlined]
        if not c:
            return None
        e, s = draw(st.sampled_from(c))
        del state.values[e][s.name]
        return f"{s.table}__totality", (e,)
    if error == "functionality":
        c = [(e, s, alt) for e, s in slots if not s.inlined and not s.multivalued
             for alt in [other(spec, s, state.values[e][s.name][0], state)] if alt is not None]
        if not c:
            return None
        e, s, alt = draw(st.sampled_from(c))
        state.values[e][s.name].append(alt)
        return f"{s.table}__functionality", (e, 2)
    if error == "reference":
        c = [(e, s) for e, s in slots if s.arrow and not s.inlined]
        if not c:
            return None
        e, s = draw(st.sampled_from(c))
        state.values[e][s.name] = ["missing"]
        return f"{s.table}__reference", (e, "missing")
    if error == "value_range":
        c = [(e, s, bad) for e, s in slots if not s.inlined for bad in
             (["not-a-value"] if s.enum else []) + ([s.maximum + 1] if s.maximum is not None else [])
             + ([s.minimum - 1] if s.minimum is not None else [])
             + (["y" if s.constant == "x" else s.constant + 1] if s.constant is not None and not s.enum else [])]
        if not c:
            return None
        e, s, bad = draw(st.sampled_from(c))
        state.values[e][s.name] = [bad]
        return f"{s.table}__value_range", (e, bad)
    if error == "identification":
        e = draw(st.sampled_from(state.top))
        state.duplicated.append(e)
        return f"{state.kind[e]}__identification", (e, 2)
    if error == "unique":
        c = [(k, n, ns, a, b) for k in spec.kinds.values() for n, ns in k.keys
             for a in state.elements_of(k.name) for b in state.elements_of(k.name)
             if a < b and all(x in state.values[a] and x in state.values[b] for x in ns)]
        if not c:
            return None
        k, n, ns, a, b = draw(st.sampled_from(c))
        for x in ns:
            state.values[b][x] = list(state.values[a][x])
        return f"{k.name}__{n}__unique", (b,)
    if error == "path_equation":
        c = [(k, n, e, end, o) for k in spec.kinds.values() for n, left, (r,) in k.equations
             for e in state.elements_of(k.name) for end in [state.follow(e, left)] if len(end) == 1
             for o in state.elements_of(spec.slot(k.name, r).range) if o not in end]
        if not c:
            return None
        k, n, e, end, o = draw(st.sampled_from(c))
        r = next(r for nn, _, (r,) in k.equations if nn == n)
        state.values[e][r] = [o]
        return f"{k.name}__{n}__path_equation", (e, next(iter(end)), o)
    if error == "cardinality":
        c = [(e, s) for e in els for s in spec.all_slots(state.kind[e]) if s.multivalued and not s.inlined
             and ((s.max_card is not None and len(pool(spec, s, state)) > s.max_card) or s.min_card == 1)]
        if not c:
            return None
        e, s = draw(st.sampled_from(c))
        if s.max_card is not None and len(pool(spec, s, state)) > s.max_card:
            state.values[e][s.name] = pool(spec, s, state)[:s.max_card + 1]
            return f"{s.table}__cardinality", (e, s.max_card + 1)
        state.values[e].pop(s.name, None)
        return f"{s.table}__cardinality", (e, 0)
    if error == "pattern":
        c = [(e, s) for e, s in slots if s.patterns]
        if not c:
            return None
        e, s = draw(st.sampled_from(c))
        state.values[e][s.name] = ["9"]
        return f"{s.table}__pattern", (e, "9")
    raise ValueError(error)


def other(spec, s, v, state):
    if s.arrow:
        return next((x for x in state.elements_of(s.range) if x != v), None)
    if s.enum:
        return next((x for x in spec.enums[s.enum] if x != v), None)
    if s.range == "integer":
        lo = -20 if s.minimum is None else s.minimum
        hi = lo + 20 if s.maximum is None else s.maximum
        return next((x for x in range(lo, hi + 1) if x != v), None)
    if s.range == "boolean":
        return not v
    if s.range == "date":
        return v + datetime.timedelta(days=1)
    return v + "-2"


# ---- the reference semantics ----

def reference(spec: Spec, rows: dict[str, list[tuple]]) -> dict[str, set[tuple]]:
    out = defaultdict(set)
    ids = {k: [r[0] for r in rows.get(k, [])] for k in spec.kinds}
    vals = {s.table: defaultdict(set) for k in spec.kinds.values() for s in k.slots}
    for t, m in vals.items():
        for i, v in rows.get(t, []):
            m[i].add(v)

    def follow(kind, e, path):
        at = {e}
        for step in path:
            s = spec.slot(kind, step)
            at, kind = {v for x in at for v in vals[s.table].get(x, ())}, s.range
        return at

    for k, kind in spec.kinds.items():
        own = set(ids[k])
        for i, n in Counter(ids[k]).items():
            if n > 1:
                out[f"{k}__identification"].add((i, n))
        if kind.parent:
            out[f"{k}__is_a__reference"] |= {(i,) for i in own - set(ids[kind.parent])}
        for s in kind.slots:
            if s.required:
                out[f"{s.table}__totality"] |= {(i,) for i in own - set(vals[s.table])}
            if not s.multivalued:
                out[f"{s.table}__functionality"] |= {(i, len(vs)) for i, vs in vals[s.table].items() if len(vs) > 1}
            for e in own:
                n = len(vals[s.table].get(e, ()))
                if (s.min_card is not None and n < s.min_card) or (s.max_card is not None and n > s.max_card):
                    out[f"{s.table}__cardinality"].add((e, n))
            for i, v in rows.get(s.table, []):
                if i not in own or (s.arrow and v not in set(ids[s.range])):
                    out[f"{s.table}__reference"].add((i, v))
                if (s.enum and v not in spec.enums[s.enum]) or (s.minimum is not None and v < s.minimum) \
                        or (s.maximum is not None and v > s.maximum) or (s.constant is not None and v != s.constant):
                    out[f"{s.table}__value_range"].add((i, v))
                if any(re.search(p, v) is None for p in s.patterns):
                    out[f"{s.table}__pattern"].add((i, v))
        for n, ns in kind.keys:
            owners = defaultdict(set)
            for e in own:
                for combo in product(*[sorted(vals[spec.slot(k, x).table].get(e, ()), key=repr) for x in ns]):
                    owners[combo].add(e)
            out[f"{k}__{n}__unique"] |= {(e,) for es in owners.values() if len(es) > 1 for e in es}
        for n, left, right in kind.equations:
            for e in own:
                out[f"{k}__{n}__path_equation"] |= {(e, a, b) for a in follow(k, e, left)
                                                    for b in follow(k, e, right) if a != b}
    return {v: rs for v, rs in out.items() if rs}
