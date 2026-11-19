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


CLASH = """id: https://rezono.example/clash
name: clash
in_language: en
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Item:
    attributes:
      id: {identifier: true}
"""


def clash(tmp_path, name, schema, rules):
    root = pack(tmp_path, name, rules)
    (root / "schema/admitted.yaml").write_text(schema, encoding="utf-8")
    return root


@pytest.mark.parametrize("cls", ["VerifiedMember", "VerifiedReceipt", "VerifiedRound", "VerifiedRoundMember"])
def test_a_kind_may_not_take_a_protected_name(tmp_path, cls):
    # Counterexample of #816: the kind VerifiedMember made the table verified_member, which batch.epoch then
    # filled with the admitted rows (none without evidence), so every fact of the kind was lost and the
    # checker still said valid. The name is reserved, with or without rules that read it.
    table = "".join(f"_{c.lower()}" if c.isupper() else c for c in cls).lstrip("_")
    schema = CLASH + f"  {cls}:\n    attributes:\n      id: {{identifier: true}}\n"
    with pytest.raises(CompileError, match=f"{table} .*protected admission input.*reserved") as read_error:
        packs.read(clash(tmp_path, "read", schema, f".decl seen(x: symbol)\nseen(x) :- {table}(x).\n"))
    assert [d.code for d in read_error.value.diagnostics] == ["schema_table_protected"]
    with pytest.raises(CompileError, match=f"{table} .*reserved") as unread_error:
        packs.read(clash(tmp_path, "unread", schema, ".decl seen(x: symbol)\nseen(x) :- item(x).\n"))
    assert [d.code for d in unread_error.value.diagnostics] == ["schema_table_protected"]


def test_an_enum_may_not_take_a_protected_name(tmp_path):
    schema = CLASH + "enums:\n  VerifiedRound:\n    permissible_values:\n      low: {}\n"
    with pytest.raises(CompileError, match="verified_round .*reserved") as error:
        packs.read(clash(tmp_path, "enum", schema, ".decl seen(x: symbol)\nseen(x) :- verified_round(x).\n"))
    assert [d.code for d in error.value.diagnostics] == ["schema_table_protected"]
