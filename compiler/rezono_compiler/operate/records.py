# --- Facts ---------------------------------------------------------------------------------------------------

from __future__ import annotations

import yaml

from .. import pack as packs

from .model import Model, fact_files
from .text import Edits, read_text, compose, pairs, get, scalars, scalar
from .maps import Maps


def fact_edits(m: Model, mp: Maps, ids: dict, edits: Edits):
    """Rename kinds, slots and enum values in the fact files, and map a reference to a derived id (an inlined
    element without an identifier of its own) through the id map `ids`."""
    p = m.pack
    for rel, f in fact_files(m):
        doc = compose(read_text(f), rel)
        for kn, records in pairs(doc):
            kind = kn.value
            if kind in mp.kinds:
                edits.node(rel, kn, scalar(mp.kinds[kind], kn))
            if kind in p.kinds and isinstance(records, yaml.SequenceNode):
                for rec in records.value:
                    record_edits(p, mp, ids, rel, kind, rec, edits)


def record_edits(p: packs.Pack, mp: Maps, ids: dict, rel: str, kind: str, rec, edits: Edits):
    if not isinstance(rec, yaml.MappingNode):
        return
    ident = p.kinds[p.root(kind)].identifier
    for kn, val in rec.value:
        name = kn.value
        if name == ident:
            new = mp.keys.get((p.root(kind), name))
            if new:
                edits.node(rel, kn, scalar(new, kn))
            continue
        s = p.slot(kind, name)
        if s is None:
            continue
        new = mp.keys.get((s.kind, name))
        if new:
            edits.node(rel, kn, scalar(new, kn))
        if s.enum in mp.values:
            for n in scalars(val):
                if n.tag == "tag:yaml.org,2002:str" and n.value in mp.values[s.enum]:
                    edits.node(rel, n, scalar(mp.values[s.enum][n.value], n))
        if s.arrow:  # a reference by id, also an item of an inlined list given as an id
            for n in scalars(val):
                if n.value in ids:
                    edits.node(rel, n, scalar(ids[n.value], n))
        if s.arrow and s.inlined:
            target = s.range
            tident = p.kinds[p.root(target)].identifier
            items = val.value if isinstance(val, yaml.SequenceNode) else [val]
            if (s.multivalued and tident and isinstance(val, yaml.MappingNode)
                    and get(val, tident) is None):  # the dictionary form: id -> rest of the record
                items = [v for _, v in val.value]
            for item in items:
                record_edits(p, mp, ids, rel, target, item, edits)
