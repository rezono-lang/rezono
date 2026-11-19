# --- rename ----------------------------------------------------------------------------------------------------

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from .. import pack as packs
from .. import strict_yaml

from .spec import CONDITIONS, CLASS_NAME, OperationError
from .model import Model, resolve
from .text import (Edits, read_text, compose, pairs, get, scalars, walk, scalar, line_end, empty, pair_end,
    delete_pair, delete_items)


@dataclass
class Rename:
    """What a rename maps, in LinkML names (for the schema) and, once the new names are known, in engine names."""
    classes: dict[tuple[str, str], str] = field(default_factory=dict)  # (module, class) -> new class name
    enums: dict[tuple[str, str], str] = field(default_factory=dict)  # (module, enum) -> new enum name
    slot: tuple[str, str, str] | None = None  # (declaring engine kind, old name, new name)
    ident: tuple[str, str, str] | None = None  # (root engine kind, old identifier, new identifier)
    value: tuple[str, str, str] | None = None  # (engine enum, old value, new value)


def plan_rename(m: Model, op: dict) -> Rename:
    p, to = m.pack, op["to"]
    r = Rename()
    if op.get("kind") and not op.get("slot"):
        mid, cname, k = resolve(m, op["kind"], m.classes, "class")
        if not CLASS_NAME.match(to) or (mid, to) in m.classes or to in m.names.declared[mid]:
            raise OperationError(f"rename {cname}: '{to}' is not a free class name in module {mid}")
        r.classes[(mid, cname)] = to
    elif op.get("kind"):
        mid, cname, k = resolve(m, op["kind"], m.classes, "class")
        name = op["slot"]
        if not packs.valid_name(to) or to == "is_a":
            raise OperationError(f"rename {cname}.{name}: '{to}' is not a valid slot name")
        kind = p.kinds[k]
        taken = {s.name for d in descendants(p, k) for s in p.all_slots(d)} | {p.kinds[p.root(k)].identifier}
        if to in taken:
            raise OperationError(f"rename {cname}.{name}: {cname} or a subkind already has a slot '{to}'")
        if (name == kind.identifier and kind.parent is None) or name in kind.slots:
            if get(get(class_node(m, mid, cname), "attributes"), name) is None:
                shared_slot(m, mid, name)  # under slots:, maybe shared: it becomes an attribute of this class
            if name in kind.slots:
                r.slot = (k, name, to)
            else:
                r.ident = (k, name, to)
        else:
            raise OperationError(f"rename {cname}.{name}: {cname} declares no slot '{name}' (an inherited slot "
                                 f"is renamed on the kind that declares it)")
    elif op.get("value") is None:
        mid, ename, e = resolve(m, op["enum"], m.enums, "enum")
        if not CLASS_NAME.match(to) or (mid, to) in m.enums or to in m.names.declared[mid]:
            raise OperationError(f"rename {ename}: '{to}' is not a free enum name in module {mid}")
        r.enums[(mid, ename)] = to
    else:
        mid, ename, e = resolve(m, op["enum"], m.enums, "enum")
        value = str(op["value"])
        if value not in p.enums[e]:
            raise OperationError(f"rename {ename}.{value}: no such value")
        if to in p.enums[e] or not to:
            raise OperationError(f"rename {ename}.{value}: '{to}' is already a value or empty")
        for kind in p.kinds.values():  # no new violations: the new value must fit every pattern it meets
            for s in kind.slots.values():
                for pattern in (s.patterns if s.enum == e else []):
                    if not re.search(pattern, to):
                        raise OperationError(f"rename {ename}.{value}: conflict, '{to}' does not match the pattern "
                                             f"{pattern!r} of {s.element}")
        r.value = (e, value, to)
    return r


def descendants(p: packs.Pack, k: str) -> list[str]:
    return sorted(d for d in p.kinds if k in p.ancestors(d))


def class_node(m: Model, mid: str, cname: str):
    doc = compose(read_text(m.mods[mid].file), m.mods[mid].rel)
    return get(get(doc, "classes"), cname)


def schema_edits(m: Model, r: Rename, edits: Edits):
    p = m.pack
    for mid in m.local:
        mod = m.mods[mid]
        rel = module_rel(m, mid)
        doc = compose(read_text(mod.file), rel)
        for (owner, old), new in r.classes.items():
            if owner == mid:
                for k, _ in pairs(get(doc, "classes")):
                    if k.value == old:
                        edits.node(rel, k, scalar(new, k))
        for (owner, old), new in r.enums.items():
            if owner == mid:
                for k, _ in pairs(get(doc, "enums")):
                    if k.value == old:
                        edits.node(rel, k, scalar(new, k))
        for k, v in walk(doc):
            if k.value in ("range", "is_a", "default_range") and isinstance(v, yaml.ScalarNode):
                owner = m.names.owner(mid, v.value)
                new = r.classes.get((owner, v.value)) or r.enums.get((owner, v.value))
                if new:
                    edits.node(rel, v, scalar(new, v))
        if r.value:
            e, old, new = r.value
            for (owner, ename), x in m.enums.items():
                if owner == mid and x == e:
                    for k, _ in pairs(get(get(get(doc, "enums"), ename), "permissible_values")):
                        if k.value == old:
                            edits.node(rel, k, scalar(new, k))
            effective = {id(d): induced_range(m, mid, a.value, c.value)
                         for c, cn in pairs(get(doc, "classes")) for a, d in pairs(get(cn, "attributes"))}
            effective |= {id(d): induced_range(m, mid, a.value) for a, d in pairs(get(doc, "slots"))}
            for mapping in mappings(doc):  # a constant on a slot whose effective range is the enum
                rng = effective.get(id(mapping))  # a slot definition: its induced range (is_a, default_range)
                if rng is None and isinstance(get(mapping, "range"), yaml.ScalarNode):
                    rng = get(mapping, "range").value
                if rng is not None and m.names.resolve(mid, rng) == e:
                    value_edits(rel, mapping, old, new, edits)
        for cname, cnode in pairs(get(doc, "classes")):
            c = m.classes[(mid, cname.value)]
            if c not in p.kinds:
                continue
            for rule in (get(cnode, "rules").value if isinstance(get(cnode, "rules"), yaml.SequenceNode) else []):
                for part in CONDITIONS:
                    for sname, cond in pairs(get(get(rule, part), "slot_conditions")):
                        if refers(p, c, sname.value, r):
                            edits.node(rel, sname, scalar(slot_new(r), sname))
                        s = p.slot(c, sname.value)
                        if r.value and s is not None and s.enum == r.value[0]:
                            value_edits(rel, cond, r.value[1], r.value[2], edits)
            if not (r.slot or r.ident):
                continue
            for _, uk in pairs(get(cnode, "unique_keys")):
                for n in scalars(get(uk, "unique_key_slots")):
                    if refers(p, c, n.value, r):
                        edits.node(rel, n, scalar(slot_new(r), n))
            notes = get(cnode, "annotations")
            for tag in ("seal", "sealed_with"):  # each names a slot of its own class
                seal = get(notes, tag)
                seal = get(seal, "value") if isinstance(seal, yaml.MappingNode) else seal
                if isinstance(seal, yaml.ScalarNode) and refers(p, c, seal.value, r):
                    edits.node(rel, seal, scalar(slot_new(r), seal))
            eqs = get(notes, "path_equations")
            eqs = get(eqs, "value") if isinstance(eqs, yaml.MappingNode) else eqs
            for eq in (eqs.value if isinstance(eqs, yaml.SequenceNode) else []):
                for side in ("left", "right"):
                    n = get(eq, side)
                    if isinstance(n, yaml.ScalarNode):
                        steps, cur, changed = n.value.split("."), c, False
                        for i, step in enumerate(steps):
                            s = p.slot(cur, step) if cur else None
                            if refers(p, cur, step, r):
                                steps[i], changed = slot_new(r), True
                            cur = s.range if s is not None and s.arrow else None
                        if changed:
                            edits.node(rel, n, scalar(".".join(steps), n))
        for k, old, new in [x for x in (r.slot, r.ident) if x]:
            mid_k, cname_k = m.kind_of(k)
            if mid_k != mid:
                continue
            cnode = get(get(doc, "classes"), cname_k)
            names = [an for an, _ in pairs(get(cnode, "attributes")) if an.value == old]
            for an in names:
                edits.node(rel, an, scalar(new, an))
            if not names:
                localize(m, mid, rel, read_text(mod.file), cnode, old, new, edits)


def shared_slot(m: Model, mid: str, name: str) -> dict:
    """The definition of a slot that class module `mid` declares under the top-level `slots:` of itself or a
    module it imports, with its range made explicit (the declaring module's default_range otherwise)."""
    for owner in [mid] + [o for o in m.names.closures[mid] if o != mid]:
        doc = strict_yaml.read(m.mods[owner].file) or {}
        slots = doc.get("slots") or {}
        if name in slots:
            d = {k: v for k, v in (slots[name] or {}).items() if k not in ("domain", "domain_of")}
            if "range" not in d:  # the induced range: from the slot's is_a chain, else the default_range
                rng = induced_range(m, owner, name)
                if rng:
                    d["range"] = rng
            if "range" in d and owner != mid:
                where = m.names.owner(owner, d["range"])
                if where is not None and m.names.owner(mid, d["range"]) != where:
                    raise OperationError(f"slot {name}: its range {d['range']} means another class in module {mid}")
            return d
    raise OperationError(f"slot {name}: no declaration under slots: in module {mid} or its imports")


def flow(value) -> str:
    """A value as one line of flow YAML."""
    out = yaml.safe_dump(value, default_flow_style=True, width=10**6, sort_keys=False, allow_unicode=True)
    return out[:-len("\n...\n")] if out.endswith("\n...\n") else out.rstrip("\n")


def insert_attribute(rel: str, text: str, cnode, entry: str, edits: Edits):
    """Add the line `entry` (`name: {definition}`) to the attributes of a class node."""
    attrs = get(cnode, "attributes")
    if isinstance(attrs, yaml.MappingNode) and attrs.flow_style:
        at = attrs.start_mark.index + 1
        edits.add(rel, at, at, entry + (", " if attrs.value else ""))
    elif isinstance(attrs, yaml.MappingNode) and attrs.value:
        k = attrs.value[0][0]
        at = text.rfind("\n", 0, k.start_mark.index) + 1
        edits.add(rel, at, at, " " * k.start_mark.column + entry + "\n")
    elif attrs is not None and not empty(attrs):
        raise OperationError(f"{rel}: the attributes of the class are not a mapping")
    elif cnode.flow_style:
        at = cnode.start_mark.index + 1
        edits.add(rel, at, at, f"attributes: {{{entry}}}" + (", " if cnode.value else ""))
    elif isinstance(cnode, yaml.MappingNode) and cnode.value:
        k = cnode.value[0][0]
        at = text.rfind("\n", 0, k.start_mark.index) + 1
        pad = " " * k.start_mark.column
        edits.add(rel, at, at, f"{pad}attributes:\n{pad}  {entry}\n")
    else:
        raise OperationError(f"{rel}: an empty class cannot take an attribute yet")


def delete_attribute(rel: str, text: str, cnode, name: str, edits: Edits):
    """Remove attribute `name` from a class node (the whole `attributes:` when it was the only one), or take a
    shared slot out of the class's `slots:` list."""
    attrs = get(cnode, "attributes")
    keys = [k for k, _ in pairs(attrs) if k.value == name]
    if keys and len(attrs.value) == 1 and len(cnode.value) > 1:
        delete_pair(rel, text, cnode, next(k for k, v in pairs(cnode) if v is attrs), edits)
    elif keys:
        delete_pair(rel, text, attrs, keys[0], edits)
    else:
        listed = get(cnode, "slots")
        hit = [n for n in (listed.value if isinstance(listed, yaml.SequenceNode) else []) if n.value == name]
        if len(hit) != 1:
            raise OperationError(f"{rel}: slot {name} is not listed once under the slots: of its class")
        delete_items(rel, text, cnode, "slots", hit, edits)


def insert_pair(rel: str, text: str, rec, entry: str, edits: Edits):
    """Add `entry` (`key: value`) as the last pair of a record."""
    if rec.flow_style:
        at = pair_end(text, *rec.value[-1]) if rec.value else rec.start_mark.index + 1
        edits.add(rel, at, at, (", " if rec.value else "") + entry)
        return
    at = line_end(text, pair_end(text, *rec.value[-1]))
    lead = "\n" if at == len(text) and not text.endswith("\n") else ""
    edits.add(rel, at, at, lead + " " * rec.value[0][0].start_mark.column + entry + "\n")


def induced_range(m: Model, mid: str, slot: str, cls: str | None = None) -> str | None:
    """The range LinkML induces for a slot (of a class): its own, else along its is_a chain, else the
    default_range."""
    try:
        return m.mods[mid].sv.induced_slot(slot, cls).range
    except (ValueError, AttributeError):
        return None


def localize(m: Model, mid: str, rel: str, text: str, cnode, old: str, new: str, edits: Edits):
    """Give a class its own attribute `new` with the definition of the shared slot `old`, and take `old` out of
    its `slots:` list; the other classes that use `old` keep it (docs/compiler.md#what-moves-along)."""
    flow = yaml.safe_dump(shared_slot(m, mid, old), default_flow_style=True, width=10**6, sort_keys=False).strip()
    entry = f"{scalar(new)}: {flow}"
    listed = get(cnode, "slots")
    items = [n for n in (listed.value if isinstance(listed, yaml.SequenceNode) else [])]
    hit = [n for n in items if isinstance(n, yaml.ScalarNode) and n.value == old]
    if len(hit) != 1:
        raise OperationError(f"{rel}: slot {old} is not listed once under the slots: of its class")
    if listed.flow_style:
        rest = [text[n.start_mark.index:n.end_mark.index] for n in items if n is not hit[0]]
        edits.add(rel, listed.start_mark.index, listed.end_mark.index, "[" + ", ".join(rest) + "]")
    else:
        key = next(k for k, v in pairs(cnode) if v is listed)
        first = key if len(items) == 1 else hit[0]  # the last item goes with its key
        start = text.rfind("\n", 0, first.start_mark.index) + 1
        end = text.find("\n", hit[0].end_mark.index)
        edits.add(rel, start, len(text) if end < 0 else end + 1, "")
    attrs = get(cnode, "attributes")
    if isinstance(attrs, yaml.MappingNode) and attrs.flow_style:
        at = attrs.start_mark.index + 1
        edits.add(rel, at, at, entry + (", " if attrs.value else ""))
    elif isinstance(attrs, yaml.MappingNode) and attrs.value:
        k = attrs.value[0][0]
        at = text.rfind("\n", 0, k.start_mark.index) + 1
        edits.add(rel, at, at, " " * k.start_mark.column + entry + "\n")
    elif attrs is not None:
        raise OperationError(f"{rel}: the attributes of the class are not a mapping")
    elif cnode.flow_style:
        at = cnode.start_mark.index + 1
        edits.add(rel, at, at, f"attributes: {{{entry}}}, ")
    else:
        k = cnode.value[0][0]
        at = text.rfind("\n", 0, k.start_mark.index) + 1
        pad = " " * k.start_mark.column
        edits.add(rel, at, at, f"{pad}attributes:\n{pad}  {entry}\n")


def module_rel(m: Model, mid: str) -> str:
    try:
        return m.mods[mid].file.relative_to(m.dir).as_posix()
    except ValueError:
        raise OperationError(f"module {mid}: its file lies outside the pack") from None


def mappings(node):
    if isinstance(node, yaml.MappingNode):
        yield node
        for _, v in node.value:
            yield from mappings(v)
    elif isinstance(node, yaml.SequenceNode):
        for v in node.value:
            yield from mappings(v)


def value_edits(rel: str, mapping, old: str, new: str, edits: Edits):
    for key in ("equals_string", "equals_string_in", "ifabsent"):
        for n in scalars(get(mapping, key)):
            if n.value == old:
                edits.node(rel, n, scalar(new, n))
            elif key == "ifabsent" and n.value == f"string({old})":
                edits.node(rel, n, scalar(f"string({new})", n))


def refers(p: packs.Pack, kind: str | None, name: str, r: Rename) -> bool:
    """Whether slot `name`, seen from `kind`, is the renamed slot or identifier."""
    if kind is None or kind not in p.kinds:
        return False
    if r.slot:
        s = p.slot(kind, name)
        return s is not None and s.kind == r.slot[0] and name == r.slot[1]
    if r.ident:
        return p.root(kind) == r.ident[0] and name == r.ident[1] and p.slot(kind, name) is None
    return False


def slot_new(r: Rename) -> str:
    return (r.slot or r.ident)[2]
