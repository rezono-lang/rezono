"""The protected admission relations beside verified_receipt, from decisions/admission-transport.md section 6.

A pack declares each with its reserved signature and no clause. Only admission fills them, so a pack may
not supply or derive one, and the reserved name with another signature is refused.
"""

import shutil
from pathlib import Path

import pytest
from rezono_compiler import pack as packs
from rezono_compiler.pack import CompileError

MINIMAL = Path(__file__).resolve().parent / "fixtures/minimal"
DECLS = {
    "verified_member": ".decl verified_member(receipt: symbol, member: symbol, part: number, value: symbol)\n",
    "verified_round": ".decl verified_round(round: symbol, run: symbol, cut: symbol, batch: symbol)\n",
    "verified_round_member": ".decl verified_round_member(round: symbol, step: symbol)\n",
}
USES = """.decl covered(value: symbol)
covered(v) :- verified_member(_, _, 0, v).
.decl chosen(run: symbol, step: symbol)
chosen(r, s) :- verified_round(o, r, _, _), verified_round_member(o, s).
"""
DERIVED = {
    "verified_member": 'verified_member("r", "[\\"a\\"]", 0, "a") :- item("anchor").\n',
    "verified_round": 'verified_round("o", "run", "cut", "batch") :- item("anchor").\n',
    "verified_round_member": 'verified_round_member("o", "step") :- item("anchor").\n',
}
OTHER = {
    "verified_member": ".decl verified_member(receipt: symbol, member: symbol, value: symbol)\n",
    "verified_round": ".decl verified_round(round: symbol, run: symbol, batch: symbol)\n",
    "verified_round_member": ".decl verified_round_member(round: symbol, step: symbol, position: number)\n",
}
SCHEMA = """id: https://rezono.example/admitted
name: admitted
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
    (root / "pack.yaml").write_text('name: admitted\nversion: "1"\ndefault_language: nl\n', encoding="utf-8")
    shutil.copytree(MINIMAL / "messages", root / "messages")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}]\n", encoding="utf-8")
    (root / "labels").mkdir()
    (root / "labels/nl.yaml").write_text("item: Item\n", encoding="utf-8")
    for folder, filename, content in (("schema", "admitted.yaml", SCHEMA), ("rules", "admitted.dl", rules),
                                      ("facts", "items.yaml", "item: [{id: anchor}]\n")):
        (root / folder).mkdir()
        (root / folder / filename).write_text(content, encoding="utf-8")
    return root


def test_admission_relations_are_protected_inputs(tmp_path):
    declared = "".join(DECLS.values())
    packs.read(pack(tmp_path, "declared", declared + USES))

    for name in DECLS:
        with pytest.raises(CompileError, match=name):
            packs.read(pack(tmp_path, f"derived-{name}", declared + USES + DERIVED[name]))
        other = "".join(OTHER[n] if n == name else d for n, d in DECLS.items())
        rules = USES if name != "verified_member" else USES.replace("_, _, 0, v", "_, _, v")
        if name == "verified_round":
            rules = rules.replace("verified_round(o, r, _, _)", "verified_round(o, r, _)")
        if name == "verified_round_member":
            rules = rules.replace("verified_round_member(o, s)", "verified_round_member(o, s, _)")
        with pytest.raises(CompileError, match=name):
            packs.read(pack(tmp_path, f"other-{name}", other + rules))

    # A name that only starts like the reserved ones stays an ordinary derived relation.
    packs.read(pack(tmp_path, "ordinary", '.decl verified_supply(item: symbol)\nverified_supply(i) :- item(i).\n'))
