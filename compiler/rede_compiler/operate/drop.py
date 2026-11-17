# --- drop -------------------------------------------------------------------------------------------------------

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from ..plan import Keep, Owned, Plan, Scan
from .. import pack as packs

from .spec import OperationError
from .model import Model, fact_files, resolve
from .text import Edits, read_text, compose, pairs, get, line_end, pair_end, delete_pair, delete_items
from .rename import descendants, class_node, module_rel


@dataclass
class Drop:
    """What a drop removes, in engine names: the kind or the slot, the tables and the element ids that go."""
    kind: str
    slot: packs.Slot | None
    slots: list  # the slots whose tables go: the dropped slot, or every slot the dropped kind declares
    kinds: set[str] = field(default_factory=set)  # the dropped kind, if any
    elements: set[str] = field(default_factory=set)

    @property
    def tables(self) -> set[str]:
        return self.kinds | {s.table for s in self.slots}


def owned(p: packs.Pack, s: packs.Slot) -> bool:
    """An inlined slot whose elements have no identifier of their own: they live and go with their owner."""
    return s.arrow and s.inlined and p.kinds[p.root(s.range)].identifier is None


def plan_drop(m: Model, op: dict) -> Drop:
    """What goes: the kind (with every slot it declares) or the slot, and every kind without an identifier that no
    slot left can hold any more (its elements all went with their owners), recursively."""
    p = m.pack
    mid, cname, k = resolve(m, op["kind"], m.classes, "class")
    kind = p.kinds[k]
    what = f"{cname}.{op['slot']}" if op.get("slot") else cname
    if op.get("slot"):
        name = op["slot"]
        if name == p.kinds[p.root(k)].identifier:
            raise OperationError(f"drop {what}: an identifier cannot go")
        if name not in kind.slots:
            raise OperationError(f"drop {what}: {cname} declares no slot '{name}' (an inherited slot goes from the "
                                 f"kind that declares it)")
        d = Drop(k, kind.slots[name], [kind.slots[name]])
    else:
        d = Drop(k, None, list(kind.slots.values()), {k})
    grow = True
    while grow:
        grow = False
        tables = {s.table for s in d.slots}
        for c in sorted(p.kinds):
            if c in d.kinds or p.kinds[p.root(c)].identifier is not None:
                continue
            holders = [s for x in p.kinds.values() for s in x.slots.values()
                       if owned(p, s) and s.table not in tables and s.range in p.ancestors(c)]
            if not holders:
                d.kinds.add(c)
                d.slots += list(p.kinds[c].slots.values())
                grow = True
    return validate_drop(m, d, f"drop {what}")


def validate_drop(m: Model, d: Drop, what: str) -> Drop:
    """The common structural boundary of an omission: no dangling reference or surviving constraint."""
    p, problems = m.pack, []
    tables = {s.table for s in d.slots}
    for c in sorted(d.kinds):
        ck = p.kinds[c]
        if ck.module not in m.local:
            problems.append(f"{c} would go with it, but belongs to an imported pack")
        subs = [x for x in descendants(p, c) if x not in d.kinds]
        if subs:
            problems.append(f"{c} has subkinds ({', '.join(subs)}); drop those first")
        d.elements |= {c} | {f"{c}.{n}" for n, _ in ck.unique_keys} | {f"{c}.{n}" for n, _, _ in ck.path_equations}
    d.elements |= {s.element for s in d.slots}
    for other in p.kinds.values():
        for s in other.slots.values():
            if s.table not in tables and s.arrow and s.range in d.kinds:
                problems.append(f"the slot {s.element} stays and has {s.range} as its range")
    for s in d.slots:  # an inlined element with an identifier of its own would go with the record text, not in M
        if s.arrow and s.inlined and not owned(p, s):
            problems.append(f"{s.element} holds elements inline that have an identifier of their own; give them "
                            f"their own records first")
    gone = {x.name for x in d.slots}
    for c, ck in sorted(p.kinds.items()):
        if c in d.kinds:
            continue
        mine = lambda n: p.slot(c, n) is not None and p.slot(c, n).table in tables
        for n, names in ck.unique_keys:
            if any(mine(x) for x in names):
                problems.append(f"the unique key {c}.{n} names it")
        for n, left, right in ck.path_equations:
            if path_through(p, c, left, d) or path_through(p, c, right, d):
                problems.append(f"the path equation {c}.{n} runs through it")
        for rule in ck.rules:
            if any(mine(x.slot) for part in (rule.pre, rule.post, rule.otherwise) for x in part):
                problems.append(f"the class rule {c}.{rule.name} names it")
        notes = get(class_node(m, ck.module, ck.cls), "annotations") if ck.module in m.local else None
        for tag in ("seal", "sealed_with", "invariants"):
            text = yaml.serialize(get(notes, tag)) if get(notes, tag) is not None else ""
            if any(re.search(rf"\b{re.escape(x)}\b", text) for x in gone if mine(x)):
                problems.append(f"the annotation {tag} of {c} names it")
    if problems:
        raise OperationError(f"{what}: " + "; ".join(problems))
    return d


def path_through(p: packs.Pack, kind: str, steps: list[str], d: Drop) -> bool:
    cur = kind
    tables = {s.table for s in d.slots}
    for step in steps:
        s = p.slot(cur, step) if cur else None
        if s is None:
            return False
        if s.table in tables or (s.arrow and s.range in d.kinds):
            return True
        cur = s.range if s.arrow else None
    return False


def drop_schema_edits(m: Model, d: Drop, edits: Edits):
    p = m.pack
    for mid in m.local:
        rel = module_rel(m, mid)
        text = read_text(m.mods[mid].file)
        doc = compose(text, rel)
        classes = get(doc, "classes")
        for c in sorted(d.kinds):
            if p.kinds[c].module == mid:
                delete_pair(rel, text, classes, next(k for k, _ in pairs(classes) if k.value == p.kinds[c].cls), edits)
        if d.slot is None or d.kind in d.kinds or p.kinds[d.kind].module != mid:
            continue
        cnode = get(classes, p.kinds[d.kind].cls)
        attrs = get(cnode, "attributes")
        keys = [k for k, _ in pairs(attrs) if k.value == d.slot.name]
        if keys:
            delete_pair(rel, text, attrs, keys[0], edits)
            continue
        listed = get(cnode, "slots")  # a shared slot: only this class lets go of it
        hit = [n for n in (listed.value if isinstance(listed, yaml.SequenceNode) else []) if n.value == d.slot.name]
        if len(hit) != 1:
            raise OperationError(f"{rel}: slot {d.slot.name} is not listed once under the slots: of its class")
        delete_items(rel, text, cnode, "slots", hit, edits)


def drop_fact_edits(m: Model, d: Drop, edits: Edits):
    """A dropped kind's section goes from every fact file; a dropped slot goes from every record that has it."""
    p = m.pack
    for rel, f in fact_files(m):
        text = read_text(f)
        doc = compose(text, rel)
        for kn, records in pairs(doc):
            if kn.value in d.kinds:
                delete_pair(rel, text, doc, kn, edits)
            elif d.slot is not None and kn.value in p.kinds and isinstance(records, yaml.SequenceNode):
                for rec in records.value:
                    drop_slot_in(p, d.slot, rel, text, kn.value, rec, edits)
        if pairs(doc) and not doc.flow_style and all(kn.value in d.kinds for kn, _ in pairs(doc)):
            # AUD-C5: a fact file without records is {}, never a null document; its comments stay.
            # One operation may drop several kinds and slots of the same file (a select): the mapping once.
            if not edits.by_file.get(rel, {}).get((len(text), len(text)), ("", False))[0].endswith("{}\n"):
                tail = text[line_end(text, pair_end(text, *pairs(doc)[-1])):]
                edits.add(rel, len(text), len(text), ("\n" if tail and not tail.endswith("\n") else "") + "{}\n")


def drop_slot_in(p: packs.Pack, slot: packs.Slot, rel: str, text: str, kind: str, rec, edits: Edits):
    if not isinstance(rec, yaml.MappingNode):
        return
    for kn, val in rec.value:
        s = p.slot(kind, kn.value)
        if s is None:
            continue
        if s.table == slot.table:
            delete_pair(rel, text, rec, kn, edits)
        elif s.arrow and s.inlined:
            tident = p.kinds[p.root(s.range)].identifier
            items = val.value if isinstance(val, yaml.SequenceNode) else [val]
            if s.multivalued and tident and isinstance(val, yaml.MappingNode) and get(val, tident) is None:
                items = [v for _, v in val.value]
            for item in items:
                drop_slot_in(p, slot, rel, text, s.range, item, edits)


def drop_plan(p: packs.Pack, d: Drop) -> Plan:
    """M of a drop: the tables of the dropped element go; from every other table of a kind or slot, the rows of
    the elements that go: those of a dropped kind, and recursively those an element that goes, or the dropped
    slot, owns by a derived id. Never lossless, so no backward."""
    owning = tuple((s.table, p.root(s.kind), p.root(s.range), s.element) for kind in p.kinds.values()
                   for s in kind.slots.values() if owned(p, s))
    holders = (d.slot.table,) if d.slot is not None and owned(p, d.slot) else ()
    seed = d.kind if d.slot is None else None

    def keep(table: str, root: str):
        return Keep(Scan(table), Owned(root, seed, p.root(d.kind) if seed else None, holders, owning), drop=True)
    forward = {k: keep(k, p.root(k)) for k in p.kinds if k not in d.tables}
    forward |= {s.table: keep(s.table, p.root(s.kind)) for kind in p.kinds.values() for s in kind.slots.values()
                if s.table not in d.tables}
    return Plan(forward=forward, gone=set(d.tables))
