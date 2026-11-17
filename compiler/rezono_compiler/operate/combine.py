# --- combine -----------------------------------------------------------------------------------------------------

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from ..plan import Derived, Element, Follow, Keep, Once, OneSource, OneValue, Plan, Scan, Swap, Union
from .. import pack as packs

from .spec import OperationError
from .model import Model, fact_files, resolve
from .text import (Edits, read_text, compose, pairs, get, scalars, scalar, line_start, line_end,
    content_end, pair_end, delete_pair)
from .rename import (Rename, descendants, class_node, flow, insert_attribute, delete_attribute, insert_pair,
    module_rel)
from .state import text_of
from .migration import migration
from .drop import Drop, owned, path_through
from .move import slot_definition, loaded, class_label


@dataclass
class Combine:
    """Kind `kind` absorbs kind `absorb` across the single-valued arrow `via`: `kind.f -> absorb` (target) or
    `absorb.f -> kind` (source). With `key`, a new slot of `kind` keeps the absorbed identifier; without it the
    identifier is lost, unless it is derived (an inlined kind without one of its own: owner and f make it)."""
    kind: str
    absorb: str
    via: packs.Slot
    mode: str  # target or source
    key: str | None
    derived: bool
    slots: list  # the slots of `absorb` that land on `kind` (the arrow excluded)
    definitions: dict = field(default_factory=dict)  # slot name -> its definition as it lands
    key_definition: dict = field(default_factory=dict)
    unique_keys: list = field(default_factory=list)  # (name, definition) that move to `kind`
    rules: list = field(default_factory=list)  # class rules that move to `kind`, as loaded YAML

    @property
    def tables(self) -> set[str]:
        """The tables that go: the absorbed kind's, its slots' and the arrow's."""
        return {self.absorb, self.via.table} | {s.table for s in self.slots}


def plan_combine(m: Model, op: dict) -> Combine:
    p = m.pack
    _, cname, k = resolve(m, op["kind"], m.classes, "class")
    _, aname, a = resolve(m, op["absorb"], m.classes, "class")
    what = f"combine {cname} absorbs {aname}"
    if a == k:
        raise OperationError(f"{what}: a kind cannot absorb itself")
    r = re.match(r"^(?P<cls>.+)\.(?P<slot>[^.]+)$", str(op["via"]))
    if not r:
        raise OperationError(f"{what}: via {op['via']} is not <Class>.<slot>")
    _, vname, vk = resolve(m, r["cls"], m.classes, "class")
    f = p.kinds[vk].slots.get(r["slot"])
    if f is None or not f.arrow or f.multivalued:
        raise OperationError(f"{what}: via {op['via']} is not a single-valued arrow that {vname} declares")
    if vk == k and f.range == a:
        mode = "target"
    elif vk == a and f.range == k:
        mode = "source"
    else:
        raise OperationError(f"{what}: via {op['via']} is neither an arrow from {cname} to {aname} nor one from "
                             f"{aname} to {cname}")
    akind, kkind = p.kinds[a], p.kinds[k]
    problems = []
    if akind.parent is not None or descendants(p, a) != [a]:
        raise OperationError(f"{what}: {aname} has a parent or subkinds; not built yet")
    derived = akind.identifier is None
    key = op.get("key")
    if derived and not (mode == "target" and f.inlined):
        problems.append(f"{aname} has no identifier, so another slot holds it inline")
    if not derived and f.inlined:
        problems.append(f"{f.element} holds elements inline that have an identifier of their own; not built yet")
    if derived and key is not None:
        problems.append(f"{aname} has no identifier of its own (its ids are derived), so it takes no key")
    for other in p.kinds.values():
        for s in other.slots.values():
            if s.arrow and s.range == a and s.table != f.table:
                problems.append(f"the slot {s.element} has {aname} as its range")
    if not derived:
        for other in p.kinds.values():
            for s in other.slots.values():
                if s.arrow and s.inlined and any(k in p.ancestors(d) for d in descendants(p, s.range)):
                    problems.append(f"{s.element} holds records of {cname} inline; not built yet")
    lineage = set(descendants(p, k)) | set(p.ancestors(k))
    taken = {s.name for d in lineage for s in p.kinds[d].slots.values()} | {p.kinds[p.root(k)].identifier}
    anode = class_node(m, akind.module, akind.cls)
    order = [x.value for x, _ in pairs(get(anode, "attributes"))]
    order += [x.value for x in scalars(get(anode, "slots"))]
    slots = sorted((s for s in akind.slots.values() if s.table != f.table),
                   key=lambda s: (order.index(s.name) if s.name in order else len(order), s.name))
    for s in slots:
        if s.name in taken:
            problems.append(f"{cname}, an ancestor or a subkind already has a slot '{s.name}'")
        if s.arrow and s.inlined and owned(p, s) and not derived:
            problems.append(f"{s.element} holds elements inline whose ids would change owner; not built yet")
    if key is not None and (not packs.valid_name(str(key)) or key in taken or key in {s.name for s in slots}):
        problems.append(f"key '{key}' is not a free slot name of {cname}")
    notes = get(anode, "annotations")
    for tag in ("seal", "sealed_with", "invariants", "path_equations"):
        if get(notes, tag) is not None:
            problems.append(f"the annotation {tag} of {aname} does not move yet")
    ident = akind.identifier
    named = lambda names: [x for x in names if x == ident or (mode == "source" and x == f.name)]
    kkeys = {n for d in lineage for n, _ in p.kinds[d].unique_keys}
    cb = Combine(k, a, f, mode, key, derived, slots)
    for n, names in akind.unique_keys:
        if n in kkeys:
            problems.append(f"{cname} already has a unique key '{n}'")
        bad = [x for x in named(names) if not (x == ident and key is not None)]
        if bad:
            problems.append(f"the unique key {a}.{n} names {', '.join(bad)}, which does not move")
        d = loaded(get(get(anode, "unique_keys"), n)) or {}
        d["unique_key_slots"] = [key if x == ident else x for x in names]
        cb.unique_keys.append((n, d))
    rule_nodes = get(anode, "rules")
    for i, rule in enumerate(akind.rules):
        names = [c.slot for part in (rule.pre, rule.post, rule.otherwise) for c in part]
        if named(names):
            problems.append(f"the class rule {a}.{rule.name} names {', '.join(sorted(set(named(names))))}, which "
                            f"does not move")
        cb.rules.append(loaded(rule_nodes.value[i]))
    going = Drop(a, None, [f] + list(akind.slots.values()), {a})
    for c, ck in sorted(p.kinds.items()):
        if c == a:
            continue
        mine = lambda n: p.slot(c, n) is not None and p.slot(c, n).table == f.table
        for n, names in ck.unique_keys:
            if any(mine(x) for x in names):
                problems.append(f"the unique key {c}.{n} names {f.name}")
        for rule in ck.rules:
            if any(mine(x.slot) for part in (rule.pre, rule.post, rule.otherwise) for x in part):
                problems.append(f"the class rule {c}.{rule.name} names {f.name}")
        for n, left, right in ck.path_equations:
            if path_through(p, c, left, going) or path_through(p, c, right, going):
                problems.append(f"the path equation {c}.{n} runs through {f.element}")
        cnotes = get(class_node(m, ck.module, ck.cls), "annotations") if ck.module in m.local else None
        for tag in ("seal", "sealed_with", "invariants"):
            text = yaml.serialize(get(cnotes, tag)) if get(cnotes, tag) is not None else ""
            if mine(f.name) and re.search(rf"\b{re.escape(f.name)}\b", text):
                problems.append(f"the annotation {tag} of {c} names {f.name}")
    for s in slots:
        d = slot_definition(m, a, s.name)
        if not (mode == "target" and f.required):  # an element of the kind need not have an absorbed one
            d.pop("required", None)
            d.pop("minimum_cardinality", None)
        rng = d.get("range")
        if isinstance(rng, str) and m.names.owner(kkind.module, rng) != m.names.owner(akind.module, rng):
            problems.append(f"the range {rng} of {s.element} means another element in the module of {cname}")
        try:
            cb.definitions[s.name] = landed_world(p, d, s, k, op.get("world"), what)
        except OperationError as e:
            problems.append(str(e).removeprefix(f"{what}: "))
    if key is not None and not derived:
        d = slot_definition(m, a, ident)
        for x in ("identifier", "required", "annotations"):
            d.pop(x, None)
        cb.key_definition = d
    if problems:
        raise OperationError(f"{what}: " + "; ".join(sorted(set(problems))))
    return cb


def landed_world(p: packs.Pack, d: dict, s: packs.Slot, to: str, want: str | None, what: str) -> dict:
    """A slot definition as it lands on kind `to`, with the world annotation when the operation states a world
    the slot would not have by itself; a change of world without `world` is a conflict."""
    notes = dict(d.get("annotations") or {})
    own = notes.get("world")
    own = own.get("value") if isinstance(own, dict) else own
    after = "open" if own == "open" or p.kinds[to].world == "open" else "closed"
    if want is None and after != s.world:
        raise OperationError(f"{what}: conflict, {s.element} would change world from {s.world} to {after}; state "
                             f"the world it gets in 'world'")
    if want == "open" and after == "closed":
        notes["world"] = "open"
    elif want == "closed" and after == "open":
        if p.kinds[to].world == "open":
            raise OperationError(f"{what}: {to} is open, so a slot there cannot be closed")
        notes.pop("world", None)
    if notes:
        d["annotations"] = notes
    else:
        d.pop("annotations", None)
    return d


def append_entries(rel: str, text: str, node, entries: list[str], edits: Edits):
    """Add `key: value` entries after the last pair of a mapping node (block or flow) that has pairs."""
    if node.flow_style:
        at = pair_end(text, *node.value[-1])
        edits.add(rel, at, at, "".join(f", {e}" for e in entries))
        return
    at = line_end(text, pair_end(text, *node.value[-1]))
    lead = "\n" if at == len(text) and not text.endswith("\n") else ""
    pad = " " * node.value[0][0].start_mark.column
    edits.add(rel, at, at, lead + "".join(f"{pad}{e}\n" for e in entries))


def combine_schema_edits(m: Model, cb: Combine, edits: Edits):
    """The absorbed class goes; its slots (and the key) land on the kind, in place of the arrow when the kind had
    it as an attribute; its unique keys and class rules follow."""
    p = m.pack
    k, a = p.kinds[cb.kind], p.kinds[cb.absorb]
    entries = [f"{scalar(cb.key)}: {flow(cb.key_definition)}"] if cb.key else []
    entries += [f"{scalar(n)}: {flow(d)}" for n, d in cb.definitions.items()]
    for mid in m.local:
        rel = module_rel(m, mid)
        text = read_text(m.mods[mid].file)
        classes = get(compose(text, rel), "classes")
        if a.module == mid:
            delete_pair(rel, text, classes, next(x for x, _ in pairs(classes) if x.value == a.cls), edits)
        if k.module != mid:
            continue
        cnode = get(classes, k.cls)
        attrs = get(cnode, "attributes")
        fkey = [x for x, _ in pairs(attrs) if x.value == cb.via.name] if cb.mode == "target" else []
        if fkey and entries:  # the absorbed slots take the place of the arrow
            fv = get(attrs, cb.via.name)
            if attrs.flow_style:
                edits.add(rel, fkey[0].start_mark.index, pair_end(text, fkey[0], fv), ", ".join(entries))
            else:
                pad = " " * fkey[0].start_mark.column
                edits.add(rel, line_start(text, fkey[0].start_mark.index), line_end(text, pair_end(text, fkey[0], fv)),
                          "".join(f"{pad}{e}\n" for e in entries))
        else:
            if cb.mode == "target":
                delete_attribute(rel, text, cnode, cb.via.name, edits)
            if entries and isinstance(attrs, yaml.MappingNode) and attrs.value:
                append_entries(rel, text, attrs, entries, edits)
            elif entries and attrs is None and not cnode.flow_style and cnode.value:
                first = cnode.value[0][0]
                pad = " " * first.start_mark.column
                at = line_start(text, first.start_mark.index)
                edits.add(rel, at, at, f"{pad}attributes:\n" + "".join(f"{pad}  {e}\n" for e in entries))
            elif entries:
                insert_attribute(rel, text, cnode, ", ".join(entries), edits)
        uks = get(cnode, "unique_keys")
        if cb.unique_keys:
            lines = [f"{scalar(n)}: {flow(d)}" for n, d in cb.unique_keys]
            if isinstance(uks, yaml.MappingNode) and uks.value:
                append_entries(rel, text, uks, lines, edits)
            elif uks is None:
                insert_pair(rel, text, cnode, f"unique_keys: {{{', '.join(lines)}}}", edits)
            else:
                raise OperationError(f"{rel}: the unique keys of {k.cls} are not a mapping")
        rules = get(cnode, "rules")
        if cb.rules:
            if isinstance(rules, yaml.SequenceNode) and rules.value and rules.flow_style:
                at = content_end(text, rules.value[-1])
                edits.add(rel, at, at, "".join(f", {flow(x)}" for x in cb.rules))
            elif isinstance(rules, yaml.SequenceNode) and rules.value:
                last = rules.value[-1]
                ls = line_start(text, last.start_mark.index)  # the item's dash: on its line, or above it
                while not text[ls:last.start_mark.index].lstrip().startswith("-"):  # past comment and blank lines
                    ls = line_start(text, ls - 1)
                prefix = " " * (len(text[ls:]) - len(text[ls:].lstrip(" "))) + "- "
                at = line_end(text, content_end(text, last))
                lead = "\n" if at == len(text) and not text.endswith("\n") else ""
                edits.add(rel, at, at, lead + "".join(f"{prefix}{flow(x)}\n" for x in cb.rules))
            elif rules is None:
                insert_pair(rel, text, cnode, f"rules: [{', '.join(flow(x) for x in cb.rules)}]", edits)
            else:
                raise OperationError(f"{rel}: the rules of {k.cls} are not a list")


def flatten_in(p: packs.Pack, cb: Combine, rel: str, text: str, kind: str, rec, edits: Edits):
    """In a record of the kind (anywhere, also inline), the pairs of the inlined absorbed element take the place
    of the arrow's pair; the records it holds inline in turn are searched too."""
    if not isinstance(rec, yaml.MappingNode):
        return
    for kn, val in rec.value:
        s = p.slot(kind, kn.value)
        if s is None:
            continue
        if s.table == cb.via.table:
            if isinstance(val, yaml.SequenceNode) and len(val.value) > 1:
                raise OperationError(f"{rel}:{kn.start_mark.line + 1}: conflict, two values of {cb.via.element}")
            whole = val  # the text the pair spans
            if isinstance(val, yaml.SequenceNode):  # a one-element list is one value (an empty one none)
                val = val.value[0] if val.value else None
            entries = []
            for k2, v2 in pairs(val) if val is not None else []:
                if loaded(v2) is None:
                    continue
                piece = text[k2.start_mark.index:pair_end(text, k2, v2)]
                if "\n" in piece:
                    piece = f"{scalar(k2.value)}: {flow(loaded(v2))}"
                entries.append(piece)
            if not entries:
                delete_pair(rel, text, rec, kn, edits)
            elif rec.flow_style:
                edits.add(rel, kn.start_mark.index, pair_end(text, kn, whole), ", ".join(entries))
            else:
                edits.add(rel, kn.start_mark.index, pair_end(text, kn, whole),
                          ("\n" + " " * kn.start_mark.column).join(entries))
        elif s.arrow and s.inlined:
            tident = p.kinds[p.root(s.range)].identifier
            items = val.value if isinstance(val, yaml.SequenceNode) else [val]
            if s.multivalued and tident and isinstance(val, yaml.MappingNode) and get(val, tident) is None:
                items = [v for _, v in val.value]
            for item in items:
                flatten_in(p, cb, rel, text, s.range, item, edits)


def combine_fact_edits(m: Model, cb: Combine, edits: Edits):
    """Inlined (derived): the absorbed pairs replace the arrow's pair in place. With records of its own: per state
    (facts/ together, each diagnostic alone) their values go into the records of the kind they join, with the
    key, the arrow's pairs go and the absorbed section goes."""
    p = m.pack
    if cb.derived:
        for rel, f in fact_files(m):
            text = read_text(f)
            for kn, records in pairs(compose(text, rel)):
                if kn.value in p.kinds and isinstance(records, yaml.SequenceNode):
                    for rec in records.value:
                        flatten_in(p, cb, rel, text, kn.value, rec, edits)
        return
    khier = set(descendants(p, cb.kind))
    for rel, f in fact_files(m):
        if rel.startswith("scenarios/") and any(kn.value in khier | {cb.absorb}
                                                for kn, _ in pairs(compose(read_text(f), rel))):
            raise OperationError(f"{rel}: records of {cb.kind} or {cb.absorb} in a scenario; combine does not reach "
                                 f"scenarios yet")
    scopes = [[x for x in fact_files(m) if x[0].startswith("facts/")]]
    scopes += [[x] for x in fact_files(m) if x[0].startswith("diagnostics/")]
    fname, aid = cb.via.name, p.kinds[cb.absorb].identifier
    kid = p.kinds[p.root(cb.kind)].identifier
    for scope in scopes:
        texts = {rel: read_text(f) for rel, f in scope}
        xs, ys = {}, {}  # id as text -> [(rel, record node)]: two records of one element of the kind are fine
        # unless the combine touches it; two of an absorbed element are a conflict
        for rel, _ in scope:
            doc = compose(texts[rel], rel)
            for kn, records in pairs(doc):
                if kn.value == cb.absorb:
                    delete_pair(rel, texts[rel], doc, kn, edits)
                if kn.value not in khier | {cb.absorb} or not isinstance(records, yaml.SequenceNode):
                    continue
                out, ident = (ys, aid) if kn.value == cb.absorb else (xs, kid)
                for rec in records.value:
                    if not isinstance(rec, yaml.MappingNode):
                        continue
                    rid = text_of(loaded(get(rec, ident)))
                    if rid in out and out is ys:
                        raise OperationError(f"{rel}: conflict, two records of {kn.value} {rid}")
                    out.setdefault(rid, []).append((rel, rec))
                    fk = next((x for x, _ in rec.value if x.value == fname), None)
                    if cb.mode == "target" and out is xs and fk is not None:
                        delete_pair(rel, texts[rel], rec, fk, edits)
        links = []  # (x, y as text, the key value)
        for src, recs in sorted((xs if cb.mode == "target" else ys).items()):
            vs = [loaded(get(rec, fname)) for _, rec in recs if get(rec, fname) is not None]
            vs = [x for v in vs for x in (v if isinstance(v, list) else [v]) if x is not None]  # [x] is one value
            if len(vs) > 1:
                raise OperationError(f"{recs[0][0]}: conflict, {src} has more than one {fname}")
            v = vs[0] if vs else None
            rec = next((r for _, r in recs if get(r, fname) is not None), recs[0][1])  # the record with the arrow
            if v is not None:
                links.append((src, text_of(v), v) if cb.mode == "target" else (text_of(v), src, loaded(get(rec, aid))))
        seen: dict = {}
        for x, y, _ in links:
            seen.setdefault(y if cb.mode == "target" else x, []).append(x if cb.mode == "target" else y)
        for t, others in sorted(seen.items()):
            if len(others) > 1:
                raise OperationError(f"conflict, {t} is reached by {', '.join(sorted(others))} across {cb.via.element}")
        for x, y, v in links:
            if x not in xs:
                continue  # a dangling arrow: M(X) then holds rows the files cannot, which the check reports
            rel, rec = next(((r_, c) for r_, c in xs[x] if get(c, fname) is not None), xs[x][0])
            entries = [f"{scalar(cb.key)}: {flow(v)}"] if cb.key and y in ys else []  # a dangling arrow is lost
            if y in ys:
                entries += [f"{scalar(k2.value)}: {flow(loaded(v2))}" for k2, v2 in ys[y][0][1].value
                            if k2.value not in (aid, fname if cb.mode == "source" else None) and loaded(v2) is not None]
            for e in entries:
                insert_pair(rel, texts[rel], rec, e, edits)


def combine_plan(p: packs.Pack, cb: Combine, key_table: str | None) -> Plan:
    """M and M⁻¹ of a combine, in the old table names: the absorbed slot tables keep theirs (the table map then
    puts them on the kind), the key table has its new name. Forward, across the arrow each element of the kind
    takes the values of the absorbed element the arrow joins it to (k.f -> a: toward the arrow's source; a.f -> k:
    toward its target); with `key`, each arrow row whose absorbed element exists becomes a key row. An absorbed
    element and its arrow row come back from the key, or (a derived id) from any value it carries; otherwise they
    are lost, and so is a value no element of the kind takes. An element reached twice, or an arrow with two
    values, is a conflict. Backward, the absorbed elements again: from the key, or rebuilt from their owner and
    the arrow (a derived id) for each element of the kind that carries an absorbed value."""
    f, a, target = cb.via.table, cb.absorb, cb.mode == "target"
    back_ids = bool(cb.key or cb.derived)
    take = "source" if target else "target"  # the end of the arrow that is the kind's element

    def own(s):  # the absorbed values; with ids that come back, only those of an absorbed element (it comes too)
        return Keep(Scan(s.table), Scan(a)) if back_ids else Scan(s.table)
    forward = {s.table: Follow(own(s), Scan(f), take=take, per="each", single=True, what=f"{cb.via.element} {s.name}",
                               through=back_ids) for s in cb.slots}
    if cb.key:
        rows = Keep(Swap(Scan(f)), Scan(a)) if target else Keep(Scan(f), Scan(a))  # (y, x), y an absorbed element
        forward[key_table] = Swap(rows)
    checks = [OneValue(cb.kind if target else a, f, cb.via.name), OneSource(f, cb.via.element), Once(a, a)]
    if cb.key:
        key = Scan(key_table)
        backward = {s.table: Follow(Scan(s.table), key, take="target", per="each") for s in cb.slots}
        backward[a] = Element(Swap(key))
        backward[f] = key if target else Swap(key)
        back_gone = {key_table}
    elif cb.derived:
        carrying = Keep(Scan(cb.kind), Union(tuple(Scan(s.table) for s in cb.slots)))
        backward = {s.table: Derived(Scan(s.table), cb.via.element) for s in cb.slots}
        backward[a] = Derived(carrying, cb.via.element)
        backward[f] = Derived(carrying, cb.via.element, pair=True)
        back_gone = set()
    else:  # the identifiers go
        backward, back_gone = None, set()
    akind = p.kinds[a]
    pairs_ = (cb.kind, Scan(f), target)  # absorbed element -> the element of the kind
    carry = {(a, s.name): pairs_ for s in cb.slots} | {(a, n): pairs_ for n, _ in cb.unique_keys}
    carry |= {(a, r.name): pairs_ + (f"rule_{len(p.kinds[cb.kind].rules) + i}",) for i, r in enumerate(akind.rules, 1)}
    access = [{"table": s.table, "kind": a, "slot": s.name, "to": cb.kind, "range": s.range if s.arrow else None}
              for s in cb.slots]
    if cb.key:
        carry[(a, akind.identifier)] = pairs_ + (cb.key,)
        access.append({"table": a, "kind": a, "slot": akind.identifier, "to": cb.kind, "range": None,
                       "new": key_table})
    return Plan(forward=forward, gone={a, f}, backward=backward, back_gone=back_gone, checks=checks, carry=carry,
                access=access)


def combine_migration(m: Model, new: Model, cb: Combine, name: str) -> dict:
    """The whole functor: the kind takes each absorbed slot along a path through the inlined arrow (`f.b`, as
    linkml-map flattens), or across a to-one join with the absorbed records; the absorbed class goes."""
    doc = migration(m, new, Rename(), name, False)
    k = new.classes[(m.pack.kinds[cb.kind].module, m.pack.kinds[cb.kind].cls)]
    receivers = [doc["class_derivations"][class_label(new, x)] for x in descendants(new.pack, k)
                 if class_label(new, x) in doc["class_derivations"]]  # a subkind takes the slots too
    alias = class_label(m, cb.absorb)
    aid = m.pack.kinds[cb.absorb].identifier
    names = [s.name for s in cb.slots] + ([aid] if cb.key else [])
    if cb.derived:
        prefix = cb.via.name
    else:
        kid = m.pack.kinds[m.pack.root(cb.kind)].identifier
        keys = (cb.via.name, aid) if cb.mode == "target" else (kid, cb.via.name)
        for d in receivers:
            d["joins"] = {alias: {"alias": alias, "source_key": keys[0], "lookup_key": keys[1]}}
        prefix = alias
    for d in receivers:
        for n in names:
            d["slot_derivations"][cb.key if n == aid and cb.key else n] = {"expr": f"{prefix}.{n}"}
    return doc


def combine_inverse(m: Model, new: Model, cb: Combine, name: str) -> dict:
    """The inverse: the absorbed class again, from the kind; the arrow of the kind and its subkinds to it from the
    key, or (inlined) a nested class derivation that rebuilds the inlined element from the kind's own slots.
    linkml-map has no row condition, so with an optional arrow that derivation also gives an element of the kind
    without absorbed values an empty one; the compiler's own round trip is exact (docs/compiler.md, limits)."""
    doc = migration(m, new, Rename(), name, True)
    p = m.pack
    k_labels = [class_label(m, x) for x in descendants(p, cb.kind) if class_label(m, x) in doc["class_derivations"]]
    a_label = class_label(m, cb.absorb)
    k_now = new.pack.kinds[new.classes[(p.kinds[cb.kind].module, p.kinds[cb.kind].cls)]]
    source = class_label(new, k_now.name)
    absorbed = {s.name: {"populated_from": s.name} for s in cb.slots}
    aid = p.kinds[cb.absorb].identifier
    if cb.derived:
        doc["class_derivations"].pop(a_label, None)
        for k_label in k_labels:
            doc["class_derivations"][k_label]["slot_derivations"][cb.via.name] = {"class_derivations": [
                {"name": a_label, "populated_from": source, "slot_derivations": absorbed}]}
        return doc
    a = {"populated_from": source, "slot_derivations": {aid: {"populated_from": cb.key}} | absorbed}
    if cb.mode == "source":
        a["slot_derivations"][cb.via.name] = {"populated_from": p.kinds[p.root(cb.kind)].identifier}
    else:
        for k_label in k_labels:
            doc["class_derivations"][k_label]["slot_derivations"][cb.via.name] = {"populated_from": cb.key}
    doc["class_derivations"][a_label] = a
    return doc
