# --- split_by ----------------------------------------------------------------------------------------------------

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

from .. import facts
from ..plan import Const, Covered, Element, Keep, OneValue, Plan, Scan, Union, Where
from .. import pack as packs

from .spec import CLASS_NAME, OperationError
from .model import Model, fact_files, resolve
from .text import (Edits, read_text, compose, pairs, get, scalar, line_start, line_end, content_end,
    pair_end, delete_pair, comment_start, delete_items)
from .rename import Rename, descendants, class_node, flow, delete_attribute, insert_pair, module_rel
from .state import text_of
from .migration import migration
from .move import loaded, class_label


@dataclass
class Split:
    kind: str
    slot: packs.Slot
    cases: dict[str, str]  # value as text -> new class name
    abstract: bool
    rules: dict[int, str] = field(default_factory=dict)  # index of a class rule of `kind` -> the case class it goes to


def case_text(v) -> str:
    """A value as the text a case names (W3: a whole number as decimal text)."""
    return text_of(v)


def plan_split(m: Model, op: dict) -> Split:
    p = m.pack
    mid, cname, k = resolve(m, op["kind"], m.classes, "class")
    name = op["slot"]
    what = f"split_by {cname}.{name}"
    kind = p.kinds[k]
    if name not in kind.slots:
        raise OperationError(f"{what}: {cname} declares no slot '{name}'")
    s = kind.slots[name]
    problems = []
    if s.arrow or s.multivalued:
        problems.append("the slot is not a single-valued attribute")
    subs = [d for d in descendants(p, k) if d != k]
    if subs:
        problems.append(f"{cname} has subkinds ({', '.join(subs)}); a record has one most specific kind")
    for other in p.kinds.values():
        for t in other.slots.values():
            if t.arrow and t.inlined and k in descendants(p, t.range):
                problems.append(f"{t.element} holds records of {cname} inline, where they have no section")
    taken = set(m.names.declared[mid])
    cases = {}
    for c in op["cases"]:
        new = str(c["kind"])
        if not CLASS_NAME.match(new) or new in taken:
            problems.append(f"'{new}' is not a free class name in module {mid}")
        value = case_text(c["value"])
        if s.enum and value not in p.enums[s.enum]:
            problems.append(f"'{value}' is not a value of {s.enum}")
        try:
            typed_case(s, value)
        except (ValueError, facts.LoadError):
            problems.append(f"'{value}' is not a {s.sql_type}")
        cases[value] = new
    for n, names in kind.unique_keys:
        if name in names:
            problems.append(f"the unique key {k}.{n} names it")
    for n, left, right in kind.path_equations:
        if name in left + right:
            problems.append(f"the path equation {k}.{n} names it")
    notes = get(class_node(m, mid, cname), "annotations")
    for tag in ("seal", "sealed_with", "invariants"):
        text = yaml.serialize(get(notes, tag)) if get(notes, tag) is not None else ""
        if re.search(rf"\b{re.escape(name)}\b", text):
            problems.append(f"the annotation {tag} of {k} names it")
    sp = Split(k, s, cases, bool(op.get("abstract")))
    for i, rule in enumerate(kind.rules):
        named = [c for part in (rule.pre, rule.post, rule.otherwise) for c in part if c.slot == name]
        if not named:
            continue
        only = rule.pre and len(rule.pre) == 1 and rule.pre[0].slot == name and not rule.otherwise
        facets = rule.pre[0].facets if only else {}
        value = facets.get("equals_string", facets.get("equals_number")) if len(facets) == 1 else None
        if only and len(named) == 1 and value is not None and case_text(value) in cases:
            sp.rules[i] = cases[case_text(value)]
        else:
            problems.append(f"the class rule {k}.{rule.name} uses {name} in another way than "
                            f"'{name} equals a case value' as its only precondition")
    if problems:
        raise OperationError(f"{what}: " + "; ".join(problems))
    return sp


def split_schema_edits(m: Model, sp: Split, edits: Edits):
    p = m.pack
    kind = p.kinds[sp.kind]
    rel = module_rel(m, kind.module)
    text = read_text(m.mods[kind.module].file)
    doc = compose(text, rel)
    classes = get(doc, "classes")
    if classes.flow_style:
        raise OperationError(f"{rel}: classes in flow style; split_by adds classes in block style only")
    key = next(k for k, _ in pairs(classes) if k.value == kind.cls)
    cnode = get(classes, kind.cls)
    delete_attribute(rel, text, cnode, sp.slot.name, edits)
    rules = get(cnode, "rules")
    moved = {i: loaded(n) for i, n in enumerate(rules.value)} if isinstance(rules, yaml.SequenceNode) else {}
    if sp.rules:
        if len(sp.rules) == len(rules.value):
            delete_pair(rel, text, cnode, next(k for k, v in pairs(cnode) if v is rules), edits)
        else:
            delete_items(rel, text, cnode, "rules", [rules.value[i] for i in sorted(sp.rules)], edits)
    if sp.abstract and not kind.abstract:
        insert_pair(rel, text, cnode, "abstract: true", edits)
    pad = " " * key.start_mark.column
    blocks = []
    for value, new in sp.cases.items():
        block = f"\n{pad}{new}:\n{pad}  is_a: {scalar(kind.cls)}\n"
        layer = get(get(cnode, "annotations"), "layer")
        if layer is not None:  # the layer of the class itself, when the module does not give it
            block += f"{pad}  annotations: {{layer: {flow(loaded(layer))}}}\n"
        mine = [{k_: v for k_, v in moved[i].items() if k_ != "preconditions"} for i in sorted(sp.rules)
                if sp.rules[i] == new]
        if mine:
            block += f"{pad}  rules:\n" + "".join(f"{pad}    - {flow(r)}\n" for r in mine)
        blocks.append(block)
    at = line_end(text, pair_end(text, key, cnode))
    lead = "\n" if at == len(text) and not text.endswith("\n") else ""
    edits.add(rel, at, at, lead + "".join(blocks))


def record_lines(text: str, rec, drop_key, start: int | None = None, flow: bool = False) -> str:
    """The full lines of a list item, with one pair taken out; from `start` when the comments above it come
    along. An item of a flow sequence becomes a block item."""
    if flow:
        start, end = rec.start_mark.index, rec.end_mark.index
    else:
        start = line_start(text, rec.start_mark.index) if start is None else start
        end = line_end(text, content_end(text, rec))
    tmp = Edits()
    if drop_key is not None:
        delete_pair("record", text, rec, drop_key, tmp)
    spans = tmp.by_file.get("record", {})
    out = Edits()
    for (a, b), (new, block) in spans.items():
        out.add("r", a - start, b - start, new, block)
    lines = out.apply("r", text[start:end])
    lines = f"  - {lines}" if flow else lines
    return lines if lines.endswith("\n") else lines + "\n"


def split_fact_edits(m: Model, sp: Split, names: dict[str, str], edits: Edits):
    """Each record of the split kind whose value has a case leaves its section for the section of that case,
    without the value; a value without a case goes (not abstract) or is a conflict (abstract)."""
    name = sp.slot.name
    for rel, f in fact_files(m):
        text = read_text(f)
        doc = compose(text, rel)
        for kn, records in pairs(doc):
            if kn.value != sp.kind or not isinstance(records, yaml.SequenceNode):
                continue
            going: dict[str, list] = {}
            left = []
            for i, rec in enumerate(records.value):
                vk = next((k for k, _ in pairs(rec) if k.value == name), None)
                v = loaded(get(rec, name)) if vk is not None else None
                if isinstance(v, list):  # a list gives a row per item: one value, or a conflict
                    if len({case_text(e) for e in v}) > 1:
                        raise OperationError(f"{rel}:{rec.start_mark.line + 1}: conflict, two values of {name}")
                    v = v[0] if v else None
                case = sp.cases.get(case_text(v)) if v is not None else None
                if case is not None:
                    lead = None if records.flow_style else comment_start(text, records, i, line_end(text, kn.end_mark.index))
                    going.setdefault(case, []).append(record_lines(text, rec, vk, lead, records.flow_style))
                    left.append(rec)
                elif sp.abstract:
                    raise OperationError(f"{rel}:{rec.start_mark.line + 1}: conflict, {sp.kind} "
                                         f"{'without ' + name if v is None else 'with ' + repr(v) + ', which has no case'}"
                                         f" cannot stay in an abstract kind")
                elif vk is not None:
                    delete_pair(rel, text, rec, vk, edits)
            if len(left) == len(records.value):
                delete_pair(rel, text, doc, kn, edits)
            else:
                delete_items(rel, text, doc, kn.value, left, edits, comments=True)
            if going:
                at = line_end(text, pair_end(text, kn, records))
                lead = "\n" if at == len(text) and not text.endswith("\n") else ""
                edits.add(rel, at, at, lead + "".join(f"{names[c]}:\n" + "".join(lines)
                                                     for c, lines in going.items() if lines))


def split_plan(sp: Split, names: dict[str, str]) -> Plan:
    """M of a split: each subkind (new name) holds the elements of the kind whose value is its case, one row per
    value row (the record with the value moves; a duplicate record without it stays); the slot's table goes, and
    a value row no subkind keeps is lost. An element with two values
    is a conflict, and so, in an abstract kind, is one without a case. M⁻¹: the slot's table from the subkinds,
    each element with its case's value; the subkind tables go."""
    t = sp.slot.table
    forward = {names[c]: Element(Keep(Where(Scan(t), v), Scan(sp.kind))) for v, c in sp.cases.items()}
    checks = [OneValue(sp.kind, t, sp.slot.name)]
    checks += [Covered(sp.kind, t, sp.slot.name, tuple(sp.cases))] if sp.abstract else []
    backward = {t: Union(tuple(Const(Scan(names[c]), typed_case(sp.slot, v)) for v, c in sp.cases.items()))}
    return Plan(forward=forward, gone={t}, backward=backward, back_gone=set(names.values()), checks=checks)


def typed_case(slot: packs.Slot, v: str):
    """A case value, as text, in the type of the slot, as the facts loader gives it (a date from ISO text)."""
    t = slot.sql_type
    raw = int(v) if t == "BIGINT" else {"true": True, "false": False}.get(v, v) if t == "BOOLEAN" else v
    return facts.typed(t, raw, f"the case {v!r}")


def split_label_edits(m: Model, sp: Split, names: dict[str, str], edits: Edits):
    """Each subkind gets the channel sign of its kind, right after it (a sign is per kind; a missing one warns)."""
    f = m.dir / "channels.yaml"
    if not f.exists():
        return
    text = read_text(f)
    seq = get(compose(text, "channels.yaml"), "kinds")
    rows = seq.value if isinstance(seq, yaml.SequenceNode) and not seq.flow_style else []
    for row in rows:
        k = get(row, "kind")
        if isinstance(k, yaml.ScalarNode) and k.value == sp.kind:
            shape = loaded(get(row, "shape"))
            lines = record_lines(text, row, None)
            pad = lines[:len(lines) - len(lines.lstrip(" "))]
            at = line_end(text, content_end(text, row))
            edits.add("channels.yaml", at, at, "".join(f"{pad}- {flow({'kind': names[c], 'shape': shape})}\n"
                                                       for c in sp.cases.values()))


def split_migration(m: Model, new: Model, sp: Split, names: dict, name: str) -> dict:
    """The whole functor, with one class derivation per subkind `where` the attribute has its value (the one
    Rezono extension; plain linkml-map refuses it); without `abstract` the kind keeps the elements without a case."""
    doc = migration(m, new, Rename(), name, False)
    cls = class_label(m, sp.kind)
    d = sp.slot.name
    kind = m.pack.kinds[sp.kind]
    base = doc["class_derivations"].pop(class_label(new, new.classes[(kind.module, kind.cls)]))
    quoted = lambda v: json.dumps(v) if sp.slot.sql_type in ("VARCHAR", "DATE") else v
    out = {}
    for label_, derivation in doc["class_derivations"].items():
        out[label_] = derivation
    if not sp.abstract:
        values = ", ".join(quoted(v) for v in sp.cases)
        out[cls] = base | {"where": f"{d} not in [{values}]"}
    for v, c in sp.cases.items():
        out[class_label(new, names[c])] = {"populated_from": cls, "where": f"{d} == {quoted(v)}",
                                           "slot_derivations": base["slot_derivations"]}
    doc["class_derivations"] = dict(sorted(out.items()))
    return doc


def split_inverse(m: Model, new: Model, sp: Split, names: dict, name: str) -> dict:
    """The inverse: the kind from itself (elements without a case) and from each subkind, the attribute set to
    the case's value; linkml-map takes a list of class derivations, so one class can have several."""
    doc = migration(m, new, Rename(), name, True)
    cls = class_label(m, sp.kind)
    base = doc["class_derivations"][cls]
    d = sp.slot.name
    derivations = [{"name": label_} | x for label_, x in sorted(doc["class_derivations"].items())
                   if not (sp.abstract and label_ == cls)]
    for v, c in sp.cases.items():
        value = typed_case(sp.slot, v)
        slots = dict(base["slot_derivations"]) | {d: {"value": text_of(value) if sp.slot.sql_type == "DATE" else value}}
        derivations.append({"name": cls, "populated_from": class_label(new, names[c]), "slot_derivations": slots})
    doc["class_derivations"] = derivations
    return doc
