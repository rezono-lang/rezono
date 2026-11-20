"""A missing scalar depends on its declaration and the reader's verified snapshot."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from rezono_checker import access as checker_access, views
from rezono_publication import publication
from rezono_publisher import access, batch, forms, publish, store


SCHEMA = """id: https://rezono.example/cells
name: cells
in_language: nl
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Item:
    attributes:
      id: {identifier: true}
      scope: {required: true}
      optional_closed: {}
      optional_open: {annotations: {world: open}}
      required_closed: {required: true}
      required_open: {required: true, annotations: {world: open}}
      amount: {range: integer, minimum_value: -1, maximum_value: 9}
      tags: {multivalued: true}
"""

RULES = """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("complete_reader", "item", x) :- item(x).
may_read("scoped_reader", "item", x) :- item__scope(x, "shown").
"""

FACTS = """item:
  - {id: missing, scope: shown}
  - id: known
    scope: shown
    optional_closed: ""
    optional_open: ""
    required_closed: ""
    required_open: ""
    amount: 0
    tags: [a, b]
  - {id: private_item, scope: hidden, required_closed: private_value, required_open: private_value}
"""

# The only established absence is optional + closed + complete.
CELLS = [
    ("complete_reader", "optional_closed", {"$na": ""}),
    ("complete_reader", "optional_open", {"$unknown": ""}),
    ("complete_reader", "required_closed", {"$unknown": ""}),
    ("complete_reader", "required_open", {"$unknown": ""}),
    ("scoped_reader", "optional_closed", {"$unknown": "not_read_in_full"}),
    ("scoped_reader", "optional_open", {"$unknown": "not_read_in_full"}),
    ("scoped_reader", "required_closed", {"$unknown": "not_read_in_full"}),
    ("scoped_reader", "required_open", {"$unknown": "not_read_in_full"}),
]


@pytest.fixture(scope="module")
def cell_pack(tmp_path_factory):
    root = tmp_path_factory.mktemp("cells")
    minimal = Path(__file__).resolve().parents[3] / "compiler/tests/fixtures/minimal"
    shutil.copytree(minimal / "messages", root / "messages")
    (root / "pack.yaml").write_text('name: cells\nversion: "1"\ndefault_language: nl\n', encoding="utf-8")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}]\n", encoding="utf-8")
    for directory, filename, content in (("schema", "cells.yaml", SCHEMA), ("rules", "scope.dl", RULES),
                                          ("facts", "cells.yaml", FACTS)):
        (root / directory).mkdir()
        (root / directory / filename).write_text(content, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def publication_inputs(cell_pack):
    epoch = batch.epoch(cell_pack, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])
    bundle, rule_ir = json.loads(epoch.bundle), json.loads(epoch.rules)
    complete = {name: publish.snapshot(rows) for name, rows in epoch.rows.items()}
    scopes = {}
    for role in ("complete_reader", "scoped_reader"):
        readable, proofs, full = access.for_role(
            epoch.rows, epoch.kinds, epoch.parents, epoch.columns, rule_ir, epoch.witnesses, role)
        snapshots = {name: publish.snapshot(rows) for name, rows in readable.items()}
        verified, findings = checker_access.check_role(
            role, complete, snapshots, full, bundle, rule_ir,
            instances=epoch.witnesses, witnesses=proofs["witnesses"], claimed_evidence=full.evidence)
        assert findings == [] and verified == full
        form = publication.form({}, bundle, readable, full, proofs["witnesses"], [], role)
        encoded = forms.objects(form)
        _, decoded = forms.verify(encoded, form, readable, bundle, full)
        items = {r["$id"]: r for r in decoded["rows"] if r["$kind"] == "Item"}
        scopes[role] = items, verified, encoded["rows.json"]
    return bundle, scopes


@pytest.mark.parametrize("role,slot,expected", CELLS, ids=[f"{r}-{s}" for r, s, _ in CELLS])
def test_missing_scalar_in_the_verified_role_publication(publication_inputs, role, slot, expected):
    bundle, scopes = publication_inputs
    items, full, _ = scopes[role]
    declaration, = [a for a in bundle["attributes"] if a["name"] == slot]
    assert views.lacking(declaration["table"], declaration, not declaration["required"], full) == (
        "none" if "$na" in expected else "unknown")
    assert items["missing"][slot] == expected
    assert items["known"][slot] == ""


@pytest.mark.parametrize("role", ["complete_reader", "scoped_reader"])
def test_known_zero_empty_collection_and_role_membership(publication_inputs, role):
    _, scopes = publication_inputs
    items, _, encoded = scopes[role]
    assert items["known"]["amount"] == 0
    assert items["known"]["tags"] == ["a", "b"] and items["missing"]["tags"] == []
    if role == "scoped_reader":
        assert set(items) == {"known", "missing"}
        assert b"private_item" not in encoded and b"private_value" not in encoded
    else:
        assert set(items) == {"known", "missing", "private_item"}
        assert items["private_item"]["required_closed"] == "private_value"


def test_optional_cells_read_back_from_a_stored_valid_epoch(cell_pack, tmp_path):
    folder = shutil.copytree(cell_pack, tmp_path / "valid")
    facts = folder / "facts/cells.yaml"
    required = "id: missing, scope: shown, required_closed: set, required_open: set}"
    facts.write_text(FACTS.replace("id: missing, scope: shown}", required), encoding="utf-8")
    epoch = batch.epoch(folder, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])
    st = store.FileStore(tmp_path / "objects")
    roles = {"audit": "complete", "complete_reader": "may_read", "scoped_reader": "may_read"}
    manifest = publish.publish(epoch, st, roles, forms=True)
    for role in ("complete_reader", "scoped_reader"):
        key = forms.index_key(epoch.pack, manifest["id"], role)
        index = json.loads(st.get(key))
        [entry] = [obj for obj in index["objects"] if obj["name"] == "rows.json"]
        encoded = st.get(forms.key_of(entry["uri"]))
        assert hashlib.sha256(encoded).hexdigest() == entry["sha256"]
        items = {r["$id"]: r for r in json.loads(encoded)["$rows"] if r["$kind"] == "Item"}
        for reader, field, expected in CELLS:
            if reader == role and field.startswith("optional_"):
                assert items["missing"][field] == expected
        if role == "scoped_reader":
            assert "private_item" not in items and b"private_value" not in encoded
