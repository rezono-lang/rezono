# --- Engine maps: old engine name -> new, for kinds, tables, elements and rule predicates ---------------------

from __future__ import annotations

from dataclasses import dataclass, field

from .spec import PARAMETERS, OperationError
from .model import Model
from .rename import Rename


@dataclass
class Maps:
    kinds: dict[str, str] = field(default_factory=dict)
    enums: dict[str, str] = field(default_factory=dict)
    tables: dict[str, str] = field(default_factory=dict)  # every engine table, also unchanged ones
    elements: dict[str, str] = field(default_factory=dict)  # changed element ids only
    predicates: dict[str, str] = field(default_factory=dict)  # changed rule predicates (tables, parameters)
    keys: dict[tuple[str, str], str] = field(default_factory=dict)  # (old kind, old slot or identifier) -> new
    values: dict[str, dict[str, str]] = field(default_factory=dict)  # old engine enum -> {old value: new}


def engine_maps(m: Model, r: Rename, new_classes: dict, new_enums: dict, gone: set = frozenset()) -> Maps:
    """Old engine name -> new for everything that stays; `gone` holds the engine kinds and tables that go."""
    p, out = m.pack, Maps()
    for key, old in m.classes.items():
        if old in gone:
            continue
        new = new_classes.get((key[0], r.classes.get(key, key[1])))
        if new is None:
            raise OperationError(f"class {key[1]}: lost in the rename")
        out.kinds[old] = new
    for key, old in m.enums.items():
        out.enums[old] = new_enums[(key[0], r.enums.get(key, key[1]))]
    for k, kind in p.kinds.items():
        if k in gone:
            continue
        nk = out.kinds[k]
        out.tables[k] = nk
        if nk != k:
            out.elements[k] = nk
        for s in kind.slots.values():
            if s.table in gone:
                continue
            name = r.slot[2] if r.slot and (k, s.name) == r.slot[:2] else s.name
            out.tables[s.table] = f"{nk}__{name}"
            if (nk, name) != (k, s.name):
                out.elements[s.element] = f"{nk}.{name}"
                out.keys[(k, s.name)] = name
            for b in PARAMETERS:
                out.predicates[f"{s.table}__{b}"] = f"{nk}__{name}__{b}"
        for n, _ in kind.unique_keys:
            out.elements[f"{k}.{n}"] = f"{nk}.{n}"
        for n, _, _ in kind.path_equations:
            out.elements[f"{k}.{n}"] = f"{nk}.{n}"
    if r.ident:
        out.keys[(r.ident[0], r.ident[1])] = r.ident[2]
    for e, values in p.enums.items():
        ne = out.enums[e]
        out.tables[e] = ne
        out.elements[e] = ne
        vmap = {v: (r.value[2] if r.value and (e, v) == r.value[:2] else v) for v in values}
        if any(a != b for a, b in vmap.items()):
            out.values[e] = {a: b for a, b in vmap.items() if a != b}
        for v, nv in vmap.items():
            out.elements[f"{e}.{v}"] = f"{ne}.{nv}"
    out.predicates.update(out.tables)
    out.elements = {a: b for a, b in out.elements.items() if a != b}
    out.predicates = {a: b for a, b in out.predicates.items() if a != b}
    out.kinds = {a: b for a, b in out.kinds.items() if a != b}
    return out
