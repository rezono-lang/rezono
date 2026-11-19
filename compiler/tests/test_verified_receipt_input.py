"""The protected admission input `verified_receipt` of decisions/scoped-completeness.md.

A pack declares it with the reserved signature and no clause. Only admission fills it, so a pack
may not derive it, and another signature under the same name is an ordinary relation without rules.
"""

import shutil
from pathlib import Path

import pytest
from rezono_compiler import pack as packs
from rezono_compiler.pack import CompileError

MINIMAL = Path(__file__).resolve().parent / "fixtures/minimal"
DECL = (".decl verified_receipt(receipt: symbol, source: symbol, scope: symbol, cut: symbol, "
        "inventory: symbol, content: symbol)\n")
COMPLETE = """.decl complete(source: symbol, scope: symbol, cut: symbol, receipt: symbol)
complete(s, sc, c, r) :- verified_receipt(r, s, sc, c, _, _).
"""
SCHEMA = """id: https://rezono.example/receipts
name: receipts
in_language: en
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Item:
    attributes:
      id: {identifier: true}
"""


def pack(tmp_path, name, rules):
    root = tmp_path / name
    root.mkdir()
    (root / "pack.yaml").write_text('name: receipts\nversion: "1"\ndefault_language: nl\n', encoding="utf-8")
    shutil.copytree(MINIMAL / "messages", root / "messages")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}]\n", encoding="utf-8")
    (root / "labels").mkdir()
    (root / "labels/nl.yaml").write_text("item: Item\n", encoding="utf-8")
    for folder, filename, content in (("schema", "receipts.yaml", SCHEMA), ("rules", "complete.dl", rules),
                                      ("facts", "items.yaml", "item: [{id: anchor}]\n")):
        (root / folder).mkdir()
        (root / folder / filename).write_text(content, encoding="utf-8")
    return root


def test_verified_receipt_is_a_protected_input(tmp_path):
    packs.read(pack(tmp_path, "declared", DECL + COMPLETE))

    derived = DECL + COMPLETE + 'verified_receipt("r", "s", "sc", "c", "i", "k") :- item("anchor").\n'
    with pytest.raises(CompileError, match="verified_receipt"):
        packs.read(pack(tmp_path, "derived", derived))

    other = DECL.replace(", content: symbol", "") + COMPLETE.replace("_, _)", "_)")
    with pytest.raises(CompileError, match="verified_receipt"):
        packs.read(pack(tmp_path, "other-signature", other))
