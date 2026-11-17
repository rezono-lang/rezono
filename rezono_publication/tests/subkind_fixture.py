"""A neutral definition with a kind tree, as one role's part of a publication holds it (RV-K26).

A schema bundle with only the members `rezono_publication.publication` reads (contracts/bundle.yaml): a Part is an
Item (`parent`), a Spare is a Part, and a Tool is an Item beside them. An item has a label and may sit inside
another item; a part may have a size; a holder keeps items. In Rezono an element of a subkind is a row of every
kind above it too (docs/compiler.md, Tables), so `p1` is a row of `item` and of `part`.

Two roles, each as the publisher's filter gives them (rezono_publisher.access): `WIDE` reads every element and
every relation in full; `NARROW` is granted the kind `part` and nothing above it, so it reads `p1`, `p2` and `s1`
as parts, their sizes, and no row of `item`, of an item's slots or of any other kind.
"""

BUNDLE = {
    "pack": {"id": "tree-fixture"},
    "kinds": [
        {"id": "item", "class": "Item", "world": "closed"},
        {"id": "part", "class": "Part", "parent": "item", "world": "closed"},
        {"id": "spare", "class": "Spare", "parent": "part", "world": "closed"},
        {"id": "tool", "class": "Tool", "parent": "item", "world": "closed"},
        {"id": "holder", "class": "Holder", "world": "closed"},
    ],
    "attributes": [
        {"id": "item.label", "kind": "item", "name": "label", "table": "item__label", "type": "text",
         "required": True, "multivalued": False, "world": "closed"},
        {"id": "part.size", "kind": "part", "name": "size", "table": "part__size", "type": "integer",
         "schema_type": "integer", "required": False, "multivalued": False, "world": "closed"},
    ],
    "arrows": [
        {"id": "item.inside", "kind": "item", "name": "inside", "table": "item__inside", "target": "item",
         "required": False, "multivalued": False, "world": "closed"},
        {"id": "holder.keeps", "kind": "holder", "name": "keeps", "table": "holder__keeps", "target": "item",
         "required": False, "multivalued": True, "world": "closed"},
    ],
    "relations": [{"id": "kept_part", "world": "closed", "columns": [{"name": "holder"}, {"name": "part"}]}],
}
TABLES = ["item", "part", "spare", "tool", "holder", "item__label", "part__size", "item__inside", "holder__keeps",
          "kept_part"]

SOURCE_A = {"kind": "pack", "name": "tree-fixture", "position": "facts/items.yaml:3"}
SOURCE_B = {"kind": "pack", "name": "tree-fixture", "position": "facts/parts.yaml:7"}

WIDE = {
    "rows": {
        "item": [("i1",), ("p1",), ("p2",), ("s1",), ("t1",)],
        "part": [("p1",), ("p2",), ("s1",)],
        "spare": [("s1",)],
        "tool": [("t1",)],
        "holder": [("h1",)],
        "item__label": [("i1", "crate"), ("p1", "hinge"), ("p2", "bolt"), ("s1", "washer"), ("t1", "wrench")],
        "part__size": [("p1", "3"), ("s1", "1")],
        "item__inside": [("p1", "i1"), ("p2", "p1"), ("s1", "p1")],
        "holder__keeps": [("h1", "i1"), ("h1", "p1"), ("h1", "s1")],
        "kept_part": [("h1", "p1"), ("h1", "s1")],
    },
    "full": set(TABLES),
    "sources": [
        {"row": {"relation": "item", "key": '["p1"]'}, "sources": [SOURCE_A]},
        {"row": {"relation": "part", "key": '["p1"]'}, "sources": [SOURCE_B, SOURCE_A]},
        {"row": {"relation": "item__label", "key": '["s1","washer"]'}, "sources": [SOURCE_A]},
    ],
}
NARROW = {
    "rows": {**{t: [] for t in TABLES}, "part": [("p1",), ("p2",), ("s1",)], "spare": [("s1",)],
             "part__size": [("p1", "3"), ("s1", "1")]},
    "full": {"part", "spare", "part__size"},
    "sources": [{"row": {"relation": "part", "key": '["p1"]'}, "sources": [SOURCE_B, SOURCE_A]}],
}
