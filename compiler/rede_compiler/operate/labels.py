# --- Labels and channels -------------------------------------------------------------------------------------

from __future__ import annotations

import yaml

from .model import Model
from .text import Edits, read_text, compose, pairs, get, scalars, scalar, delete_pair, delete_items
from .maps import Maps


def label_edits(m: Model, mp: Maps, edits: Edits, gone: set = frozenset()):
    """Rename the element ids of labels and channel rows; those of an element in `gone` go."""
    for f in sorted((m.dir / "labels").glob("*.yaml")):
        rel = f"labels/{f.name}"
        text = read_text(f)
        doc = compose(text, rel)
        for k, _ in pairs(doc):
            if k.value in gone:
                delete_pair(rel, text, doc, k, edits)
            elif k.value in mp.elements:
                edits.node(rel, k, scalar(mp.elements[k.value], k))
    f = m.dir / "channels.yaml"
    if f.exists():
        text = read_text(f)
        doc = compose(text, "channels.yaml")
        for section, field_ in (("kinds", "kind"), ("arrows", "arrow")):
            seq = get(doc, section)
            rows = seq.value if isinstance(seq, yaml.SequenceNode) else []
            going = [row for row in rows if isinstance(get(row, field_), yaml.ScalarNode) and get(row, field_).value in gone]
            delete_items("channels.yaml", text, doc, section, going, edits)
            for row in rows:
                n = get(row, field_)
                if isinstance(n, yaml.ScalarNode) and n.value in mp.elements:
                    edits.node("channels.yaml", n, scalar(mp.elements[n.value], n))
        flow_channel_edits(get(doc, "flows"), mp.elements, edits)


def flow_channel_edits(flows, names: dict[str, str], edits: Edits):
    """Rename typed Flow references while preserving bindings and source formatting."""
    def rows(node):
        return node.value if isinstance(node, yaml.SequenceNode) else []

    def rename(row, *fields):
        for name in fields:
            for node in scalars(get(row, name)):
                if node.value in names:
                    edits.node("channels.yaml", node, scalar(names[node.value], node))

    for flow in rows(flows):
        for node in rows(get(flow, "nodes")):
            rename(node, "kind", "label", "group")
            rename(get(node, "lane"), "slot")
        for edge in [*rows(get(flow, "edges")), get(flow, "routes")]:
            rename(edge, "arrow", "from_kinds", "to_kinds")
            if get(edge, "via") is not None:
                rename(edge, "via", "from", "to")
                rename(get(edge, "quantity"), "slot")
