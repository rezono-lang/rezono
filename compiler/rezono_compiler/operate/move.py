# --- move -------------------------------------------------------------------------------------------------------

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

from .. import scenarios, strict_yaml
from ..plan import Follow, Keep, Plan, Scan
from .. import pack as packs

from .spec import OperationError
from .model import Model, fact_files, resolve
from .text import Edits, read_text, compose, pairs, get, scalar, delete_pair
from .rename import (descendants, class_node, shared_slot, flow, insert_attribute, delete_attribute,
    insert_pair, induced_range, module_rel)
from .datalog import access_kind_columns
from .state import text_of
from .drop import Drop, path_through


@dataclass
class Move:
    """Slot `slot` of kind `kind` goes to kind `to`: up (an ancestor), down (a descendant), or across the
    single-valued arrow `via`: toward its source (`to.f -> kind`) or toward its target (`kind.f -> to`)."""
    kind: str
    slot: packs.Slot
    to: str
    mode: str  # up, down, source, target
    via: packs.Slot | None = None
    definition: dict = field(default_factory=dict)  # the slot as it lands in `to`

    @property
    def table(self) -> str:
        return self.slot.table


def plan_move(m: Model, op: dict) -> Move:
    p = m.pack
    _, cname, k = resolve(m, op["kind"], m.classes, "class")
    _, tname, l = resolve(m, op["to"], m.classes, "class")
    name = op["slot"]
    what = f"move {cname}.{name} to {tname}"
    if name not in p.kinds[k].slots:
        raise OperationError(f"{what}: {cname} declares no slot '{name}' (an inherited slot moves from the kind "
                             f"that declares it; an identifier never moves)")
    s = p.kinds[k].slots[name]
    if l == k:
        raise OperationError(f"{what}: the slot is already there")
    via = None
    if op.get("via"):
        r = re.match(r"^(?P<cls>.+)\.(?P<slot>[^.]+)$", op["via"])
        _, vname, vk = resolve(m, r["cls"], m.classes, "class")
        f = p.slot(vk, r["slot"]) if r else None
        if f is None or not f.arrow or f.multivalued:
            raise OperationError(f"{what}: via {op['via']} is not a single-valued arrow")
        if f.table == s.table:
            raise OperationError(f"{what}: via {op['via']} is the slot itself")
        if vk == l and k in p.ancestors(f.range):
            mode = "source"  # to.f -> kind: Δ along f
        elif vk == k and l in p.ancestors(f.range):
            mode = "target"  # kind.f -> to
        else:
            raise OperationError(f"{what}: via {op['via']} is neither an arrow from {tname} to {cname} nor one "
                                 f"from {cname} to {tname}")
        via = f
        problems = []
        for x in (k, l):
            if p.kinds[p.root(x)].identifier is None:
                problems.append(f"{x} has no identifier of its own")
        for other in p.kinds.values():
            for t in other.slots.values():
                if t.arrow and t.inlined and any(x in p.ancestors(d) for x in (k, l)
                                                 for d in descendants(p, t.range)):
                    problems.append(f"{t.element} holds records of {p.root(k)} or {p.root(l)} inline")
        if s.arrow and s.inlined:
            problems.append("the slot holds elements inline, whose ids would change owner")
        if problems:
            raise OperationError(f"{what}: across an arrow, not built yet: " + "; ".join(sorted(set(problems))))
    elif l in p.ancestors(k):
        mode = "up"
    elif k in p.ancestors(l):
        mode = "down"
    else:
        raise OperationError(f"{what}: {tname} is neither an ancestor nor a descendant of {cname}; name the arrow "
                             f"in via")
    taken = [d for d in set(descendants(p, l)) | set(p.ancestors(l)) for t in p.kinds[d].slots.values()
             if t.name == name and t.table != s.table]
    if taken or name == p.kinds[p.root(l)].identifier:
        raise OperationError(f"{what}: {tname}, an ancestor or a subkind already has a slot '{name}'")
    mv = Move(k, s, l, mode, via)
    problems = []
    staying = [k] + [d for d in descendants(p, k) if l not in p.ancestors(d)] if mode == "down" else \
        ([] if mode == "up" else list(p.kinds))
    for c in sorted(p.kinds):
        ck = p.kinds[c]
        mine = lambda n: p.slot(c, n) is not None and p.slot(c, n).table == s.table
        for n, names in ck.unique_keys:
            if any(mine(x) for x in names):
                problems.append(f"the unique key {c}.{n} names it")
        for rule in ck.rules:
            if any(mine(x.slot) for part in (rule.pre, rule.post, rule.otherwise) for x in part) and c in staying:
                problems.append(f"the class rule {c}.{rule.name} names it")
        for n, left, right in ck.path_equations:
            if mode != "up" and (path_through(p, c, left, Drop(k, s, [s])) or path_through(p, c, right, Drop(k, s, [s]))):
                problems.append(f"the path equation {c}.{n} runs through it")
        notes = get(class_node(m, ck.module, ck.cls), "annotations") if ck.module in m.local else None
        for tag in ("seal", "sealed_with", "invariants"):
            text = yaml.serialize(get(notes, tag)) if get(notes, tag) is not None else ""
            if mine(name) and re.search(rf"\b{re.escape(name)}\b", text):
                problems.append(f"the annotation {tag} of {c} names it")
    if p.kinds[l].module not in m.local:
        problems.append(f"{tname} belongs to an imported pack")
    if problems:
        raise OperationError(f"{what}: " + "; ".join(sorted(set(problems))))
    mv.definition = moved_definition(m, mv, op, what)
    return mv


def slot_definition(m: Model, k: str, name: str) -> dict:
    """The definition of slot `name` of kind `k` as written: its attribute, or the shared slot, with an explicit
    range when the module's default_range gave it one."""
    kind = m.pack.kinds[k]
    doc = strict_yaml.read(m.mods[kind.module].file) or {}
    attrs = ((doc.get("classes") or {}).get(kind.cls) or {}).get("attributes") or {}
    if name in attrs:
        d = dict(attrs[name] or {})
        if "range" not in d and induced_range(m, kind.module, name, kind.cls):
            d["range"] = induced_range(m, kind.module, name, kind.cls)
        return d
    return shared_slot(m, kind.module, name)


def moved_definition(m: Model, mv: Move, op: dict, what: str) -> dict:
    """The slot as it lands: its own constraints, `required` only where it still holds by construction, and the
    world annotation when the operation states a world the slot would not have by itself."""
    p = m.pack
    d = slot_definition(m, mv.kind, mv.slot.name)
    if mv.mode == "target" or (mv.mode == "source" and not mv.via.required):
        d.pop("required", None)
    notes = dict(d.get("annotations") or {})
    own = notes.get("world")
    own = own.get("value") if isinstance(own, dict) else own
    after = "open" if own == "open" or p.kinds[mv.to].world == "open" else "closed"
    want = op.get("world")
    if want is None and after != mv.slot.world:
        raise OperationError(f"{what}: conflict, the slot would change world from {mv.slot.world} to {after}; "
                             f"state the world it gets in 'world'")
    if want == "open" and after == "closed":
        notes["world"] = "open"
    elif want == "closed" and after == "open":
        if p.kinds[mv.to].world == "open":
            raise OperationError(f"{what}: {mv.to} is open, so a slot there cannot be closed")
        notes.pop("world", None)
    if notes:
        d["annotations"] = notes
    else:
        d.pop("annotations", None)
    return d


def move_schema_edits(m: Model, mv: Move, edits: Edits):
    p = m.pack
    k, l = p.kinds[mv.kind], p.kinds[mv.to]
    entry = f"{scalar(mv.slot.name)}: {flow(mv.definition)}"
    for mid in m.local:
        rel = module_rel(m, mid)
        text = read_text(m.mods[mid].file)
        classes = get(compose(text, rel), "classes")
        if k.module == mid:
            delete_attribute(rel, text, get(classes, k.cls), mv.slot.name, edits)
        if l.module == mid:
            insert_attribute(rel, text, get(classes, l.cls), entry, edits)


def slot_in(p: packs.Pack, table: str, rel: str, text: str, kind: str, rec, edits: Edits, where):
    """Delete the pair of the slot with engine table `table` from a record and the records it holds inline,
    where `where(kind of the record)` holds."""
    if not isinstance(rec, yaml.MappingNode):
        return
    for kn, val in rec.value:
        s = p.slot(kind, kn.value)
        if s is None:
            continue
        if s.table == table and where(kind):
            delete_pair(rel, text, rec, kn, edits)
        elif s.arrow and s.inlined:
            tident = p.kinds[p.root(s.range)].identifier
            items = val.value if isinstance(val, yaml.SequenceNode) else [val]
            if s.multivalued and tident and isinstance(val, yaml.MappingNode) and get(val, tident) is None:
                items = [v for _, v in val.value]
            for item in items:
                slot_in(p, table, rel, text, s.range, item, edits, where)


def loaded(node):
    return strict_yaml.load(yaml.serialize(node))


def move_fact_edits(m: Model, mv: Move, edits: Edits):
    """down: the values of records that are not in `to` go. Across an arrow: the values leave the records of
    `kind` and land in the records of `to`, per state (facts/ together, each diagnostic alone)."""
    p = m.pack
    if mv.mode == "up":
        return
    if mv.mode == "down":
        keep = set(descendants(p, mv.to))
        for rel, f in fact_files(m):
            text = read_text(f)
            doc = compose(text, rel)
            for kn, records in pairs(doc):
                if kn.value in p.kinds and isinstance(records, yaml.SequenceNode):
                    for rec in records.value:
                        slot_in(p, mv.table, rel, text, kn.value, rec, edits, lambda c: c not in keep)
        return
    khier, lhier = set(descendants(p, mv.kind)), set(descendants(p, mv.to))
    for rel, f in fact_files(m):
        if rel.startswith("scenarios/") and any(kn.value in khier | lhier for kn, _ in pairs(compose(read_text(f), rel))):
            raise OperationError(f"{rel}: records of {mv.kind} or {mv.to} in a scenario; a move across an arrow "
                                 f"does not reach scenarios yet")
    scopes = [[x for x in fact_files(m) if x[0].startswith("facts/")]]
    scopes += [[x] for x in fact_files(m) if x[0].startswith("diagnostics/")]
    a, fname = mv.slot.name, mv.via.name
    ident = lambda c: p.kinds[p.root(c)].identifier
    for scope in scopes:
        xs, ys = {}, {}  # id -> (rel, text, record node, value of a or of f)
        texts = {rel: read_text(f) for rel, f in scope}
        for rel, _ in scope:
            doc = compose(texts[rel], rel)
            for kn, records in pairs(doc):
                for hier, out, key in ((khier, xs, a if mv.mode == "source" else (a, fname)), (lhier, ys, fname)):
                    if kn.value not in hier or not isinstance(records, yaml.SequenceNode):
                        continue
                    for rec in records.value:
                        if not isinstance(rec, yaml.MappingNode):
                            continue
                        rid = text_of(loaded(get(rec, ident(kn.value))))
                        if rid in out:
                            raise OperationError(f"{rel}: conflict, two records of {kn.value} {rid}")
                        if mv.mode == "target" and hier is khier:
                            val = (loaded(get(rec, a)) if get(rec, a) is not None else None,
                                   loaded(get(rec, fname)) if get(rec, fname) is not None else None)
                        else:
                            key1 = a if hier is khier else fname
                            val = loaded(get(rec, key1)) if get(rec, key1) is not None else None
                        out[rid] = (rel, kn.value, rec, val)
                        if hier is khier and get(rec, a) is not None:
                            delete_pair(rel, texts[rel], rec, next(k for k, _ in rec.value if k.value == a), edits)
        if mv.mode == "source":  # to.f -> kind: y gets the value of f(y)
            for y, (rel, kind, rec, fx) in sorted(ys.items()):
                if isinstance(fx, list):
                    raise OperationError(f"{rel}: conflict, {kind} {y} has more than one {fname}")
                x = xs.get(text_of(fx)) if fx is not None else None
                if x is not None and x[3] is not None:
                    insert_pair(rel, texts[rel], rec, f"{scalar(a)}: {flow(x[3])}", edits)
        else:  # kind.f -> to: y gets the one value its sources share
            by_y: dict = {}
            for x, (rel, kind, rec, (v, fy)) in sorted(xs.items()):
                if isinstance(fy, list):
                    raise OperationError(f"{rel}: conflict, {kind} {x} has more than one {fname}")
                if fy is not None:
                    by_y.setdefault(text_of(fy), []).append((x, v))
            for y, sources in sorted(by_y.items()):
                values = {json.dumps(sorted(json.dumps(e, sort_keys=True, default=str) for e in v)
                                     if isinstance(v, list) else v, sort_keys=True, default=str) for _, v in sources}
                if len(values) > 1:
                    raise OperationError(f"conflict: {', '.join(x for x, _ in sources)} share {fname} {y} but differ "
                                         f"in {a}")
                if y in ys and sources[0][1] is not None:
                    rel, _, rec, _ = ys[y]
                    insert_pair(rel, texts[rel], rec, f"{scalar(a)}: {flow(sources[0][1])}", edits)


def move_plan(mv: Move) -> Plan:
    """M and M⁻¹ of a move, in the old table names (the moved rows stay under the old slot table, which the
    table map then renames). Up: the rows as they are. Down: the rows of elements in `to`. Across the arrow:
    toward its source (to.f -> kind) each element of `to` takes the values of the one its arrow reaches, and
    back each element of `kind` takes those of the first that reaches it (by id); toward its target
    (kind.f -> to) an element of `to` takes the values its sources share, and back each source those of its
    target. The arrow's rows count only from elements of the kind on its side (it may be inherited)."""
    t = mv.table
    if mv.mode == "up":
        return Plan(backward={}, carry={(mv.kind, mv.slot.name): (mv.to, None, False)})
    if mv.mode == "down":
        return Plan(forward={t: Keep(Scan(t), Scan(mv.to))}, backward={},
                    carry={(mv.kind, mv.slot.name): (mv.to, Scan(mv.to), False)})
    side = mv.to if mv.mode == "source" else mv.kind
    link = Keep(Scan(mv.via.table), Scan(side)) if mv.via.kind != side else Scan(mv.via.table)
    what = f"{mv.via.element} {mv.slot.name}"
    if mv.mode == "source":
        forward = Follow(Scan(t), link, take="source", per="each", single=True, what=what)
        backward = Follow(Scan(t), link, take="target", per="first")
    else:
        forward = Follow(Scan(t), link, take="target", per="shared", single=True, what=what)
        backward = Follow(Scan(t), link, take="source", per="each")
    return Plan(forward={t: forward}, backward={t: backward},
                carry={(mv.kind, mv.slot.name): (mv.to, link, mv.mode == "source")})


def grants(m: Model, rows: dict[str, list[tuple]]) -> dict | None:
    """Per element as granted, (kind, id), the roles that may read it in this state: the rows of
    `may_read(role, kind, id)`. None when the rules declare no may_read. A may_read without the access relation signature
    blocks: who reads what cannot be told, so the check fails closed."""
    p = m.pack
    cols = access_kind_columns(m)
    if "may_read" not in cols:
        return None
    if cols["may_read"] is None:
        raise OperationError("rules: may_read is declared without the access relation signature (role, kind, id), so who reads a "
                             "moved value cannot be told; the move blocks (declare may_read(role: symbol, kind: "
                             "symbol, id: symbol))")
    from .. import batch
    from .. import rules as ir
    prog = ir.load(p.rules)
    if prog.calc_inputs():
        raise OperationError("rules: checking read rights with calculation inputs requires checked phase execution")
    con = batch.connect(prog, scenarios.rule_rows(p, prog, rows))
    try:
        batch.compute(con, prog)
        may = batch.read(con, prog, ["may_read"]).get("may_read", [])
    finally:
        con.close()
    by: dict = {}
    for role, kind, x in may:
        by.setdefault((kind, text_of(x)), set()).add(role)
    return by


def row_readers(p: packs.Pack, by: dict, kind: str, x, value_kind: str | None = None, v=None) -> set:
    """The roles that may read a row (x, v) of a slot of `kind` (O7, O8): every element in it is readable as the
    kind its column has in the schema. A right on a kind holds for its subkinds, never the reverse, so (kind, x)
    is readable through a right on `kind` or on one of its ancestors; the value, when it is an element, likewise
    as `value_kind`."""
    out = set().union(*(by.get((k, text_of(x)), set()) for k in p.ancestors(kind)))
    if value_kind is not None:
        out &= set().union(*(by.get((k, text_of(v)), set()) for k in p.ancestors(value_kind)))
    return out


def class_label(m: Model, k: str) -> str:
    kind = m.pack.kinds[k]
    return kind.cls if sum(1 for key in m.classes if key[1] == kind.cls) == 1 else f"{kind.module}#{kind.cls}"


def across(doc: dict, m: Model, target: str, other: str, a: str, source_key: str, lookup_key: str):
    """A slot derivation over a join (linkml-map `joins`, to-one): `target` and each of its subkinds take `a` from
    the `other` record whose `lookup_key` equals their own `source_key`."""
    alias = class_label(m, other)
    for k in [target] + [d for d in descendants(m.pack, target) if d != target]:  # a subkind takes the value too
        d = doc["class_derivations"].get(class_label(m, k))
        if d is not None:
            d["joins"] = {alias: {"alias": alias, "source_key": source_key, "lookup_key": lookup_key}}
            d["slot_derivations"][a] = {"expr": f"{alias}.{a}"}
