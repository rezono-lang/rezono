# --- The linkml-map migration ----------------------------------------------------------------------------------

from __future__ import annotations

import json

import yaml

from .model import Model
from .rename import Rename


def migration(m_old: Model, m_new: Model, r: Rename, name: str, inverse: bool) -> dict:
    """A whole functor as a linkml-map TransformationSpecification: a derivation per class of the target with
    every slot it has (inherited ones and the identifier too), and per enum with every value, each
    `populated_from` its counterpart in the source. A class or enum name that more than one module declares
    is written `<module>#<Name>`."""
    classes = {(mid, old): (mid, new) for (mid, old), new in r.classes.items()}
    enums = {(mid, old): (mid, new) for (mid, old), new in r.enums.items()}
    slot = r.slot or r.ident  # (old engine kind, old name, new name)
    slot_kind = m_old.kind_of(slot[0]) if slot else None  # its (module, class); a slot rename keeps the class
    value = None
    if r.value:
        value = (next(k for k, v in m_old.enums.items() if v == r.value[0]), r.value[1], r.value[2])
    if inverse:
        classes, enums = {b: a for a, b in classes.items()}, {b: a for a, b in enums.items()}
        slot = slot and (slot[0], slot[2], slot[1])
        value = value and (value[0], value[2], value[1])
    back = {b: a for a, b in classes.items()}
    eback = {b: a for a, b in enums.items()}
    source, target = (m_new, m_old) if inverse else (m_old, m_new)

    def label(m: Model, key: tuple[str, str], table: dict) -> str:
        return key[1] if sum(1 for k in table if k[1] == key[1]) == 1 else f"{key[0]}#{key[1]}"

    def here(m: Model, engine: str) -> tuple[str, str]:
        return (m.pack.kinds[engine].module, m.pack.kinds[engine].cls)

    out_classes = {}
    for k, kind in sorted(target.pack.kinds.items(), key=lambda kv: (kv[1].cls, kv[1].module)):
        if kind.module not in target.local:
            continue
        key = (kind.module, kind.cls)
        root = target.pack.root(k)
        slots = [(target.pack.kinds[root].identifier, root)] if target.pack.kinds[root].identifier else []
        slots += [(s.name, s.kind) for s in target.pack.all_slots(k)]
        origin = source.classes.get(back.get(key, key))  # the source kind: only its own slots can be read
        have = set()
        if origin in source.pack.kinds:
            sroot = source.pack.root(origin)
            have = {s.name for s in source.pack.all_slots(origin)} | {source.pack.kinds[sroot].identifier}
        derivations = {}
        for n, owner in slots:
            renamed = slot is not None and back.get(here(target, owner), here(target, owner)) == slot_kind \
                and n == slot[2]
            if (slot[1] if renamed else n) in have:  # a slot that only a subkind had comes with the subkind
                derivations[n] = {"populated_from": slot[1] if renamed else n}
        out_classes[label(target, key, target.classes)] = {
            "populated_from": label(source, back.get(key, key), source.classes), "slot_derivations": derivations}
    out_enums = {}
    for (mid, ename), e in sorted(target.enums.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if mid not in target.local:
            continue
        origin = eback.get((mid, ename), (mid, ename))
        pvs = {}
        for v in target.pack.enums[e]:
            renamed = value is not None and origin == value[0] and v == value[2]
            pvs[v] = {"populated_from": value[1] if renamed else v}
        out_enums[label(target, (mid, ename), target.enums)] = {
            "populated_from": label(source, origin, source.enums), "permissible_value_derivations": pvs}
    doc = {"id": f"rezono:{m_old.meta['name']}/{name}", "source_schema": {"name": m_old.meta["name"]},
           "target_schema": {"name": m_old.meta["name"]}, "class_derivations": out_classes}
    if out_enums:
        doc["enum_derivations"] = out_enums
    return doc


def dump(doc) -> str:
    """YAML without anchors: a shared part is written out each time it occurs."""
    return yaml.safe_dump(json.loads(json.dumps(doc)), sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=100)
