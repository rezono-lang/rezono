"""Modules written in Rezono (docs/rezono/publication.md §2, §3, §5.1, §5.2): the compiler reads a module's JSON
form and lowers its kinds, slots and enums to the schema a LinkML file would hold. One fixture is written twice,
as schema/ and as a module (fixtures/rezono: kinds.yaml, and kinds.rezono with the form `rezono/` wrote of it,
kinds.json); everything this slice does not lower is refused at its line. Neutral names; no domain."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, compile_dir, text, violations
from rezono_compiler import facts, modules, pack, rezono_module, writer
from rezono_compiler.__main__ import main

HERE = Path(__file__).resolve().parent / "fixtures" / "rezono"
SHARED = FIXTURE.parent / "shared"
LABELS = ("gamma: gamma\ngamma.since: sinds\ngamma.note: notitie\ngamma.grade: graad\ndelta: delta\n"
          "delta.gamma: gamma\ndelta.alpha: alfa\ndelta.state: stand\ndelta.grade: graad\ngrade: graad\n"
          "grade.first: eerste\ngrade.second: tweede\ngrade.third: derde\n")
KINDS = {"module": "rezono/kinds.rezono", "form": "rezono/kinds.json", "layer": "facts"}


def add(path: Path, more: str) -> None:
    path.write_bytes(path.read_bytes() + more.encode("utf-8"))


def declare(d: Path, entries: list[dict]) -> None:
    meta = yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8"))
    meta["rezono"] = entries
    (d / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))


def unplaced(doc):
    """A bundle with each span reduced to its file: what is left when the lines and columns are not compared."""
    if isinstance(doc, dict):
        return {k: {"file": v["file"]} if k == "span" and isinstance(v, dict) else unplaced(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [unplaced(v) for v in doc]
    return doc


def written(tmp_path: Path, how: str) -> Path:
    """The pack `minimal` with the fixture's kinds, written as a schema file or as a module."""
    d = Path(shutil.copytree(FIXTURE, tmp_path / how / "minimal"))
    add(d / "labels" / "nl.yaml", LABELS)
    if how == "schema":
        shutil.copy(HERE / "kinds.yaml", d / "schema" / "kinds.yaml")
    else:
        (d / "rezono").mkdir()
        for f in ("kinds.rezono", "kinds.json"):
            shutil.copy(HERE / f, d / "rezono" / f)
        declare(d, [KINDS])
    return d


def test_a_module_gives_the_bundle_and_the_engine_of_the_schema_file_that_says_the_same(tmp_path):
    as_schema = compile_dir(written(tmp_path, "schema"), tmp_path / "out" / "schema")
    as_module = compile_dir(written(tmp_path, "module"), tmp_path / "out" / "module")
    assert sorted(as_schema) == sorted(as_module)
    assert [f for f in sorted(as_schema) if as_schema[f] != as_module[f]] == ["bundle/schema-bundle.json"]
    assert as_module["engine/tables.sql"] == as_schema["engine/tables.sql"]
    # The bundle differs in one thing only: where the module's text is, which is its file and the places in it.
    bundle = as_schema["bundle/schema-bundle.json"]
    b = json.loads(as_module["bundle/schema-bundle.json"])
    assert unplaced(b) == unplaced(json.loads(bundle.replace('"schema/kinds.yaml"', '"rezono/kinds.rezono"')))
    # A kind and a slot of the module are placed at their names in its text (MOD2), a sentence where its owner is.
    lines = (HERE / "kinds.rezono").read_text(encoding="utf-8").splitlines()
    placed = {e["stable_id"]: e["span"] for e in b["kinds"] + b["arrows"] + b["attributes"]
              if e["span"]["file"] == "rezono/kinds.rezono"}
    assert len(placed) == 9
    for stable, span in placed.items():
        assert lines[int(span["line"]) - 1][int(span["column"]) - 1:].startswith(re.split("[/#]", stable)[-1])
    assert all(e["sentence"]["span"] == e["span"] for e in b["arrows"] + b["attributes"])
    assert [(s["module"], s["file"]) for s in b["schemas"]] == [("kinds", "rezono/kinds.rezono"),
                                                                ("minimal", "schema/minimal.yaml")]
    assert {k["id"]: (k["module"], k["layer"], k["world"]) for k in b["kinds"]}["delta"] == ("kinds", "facts", "closed")
    assert {a["id"]: a["target"] for a in b["arrows"]} == {"beta.alpha": "alpha", "delta.alpha": "alpha",
                                                          "delta.gamma": "gamma"}


def test_an_arrow_to_a_kind_of_schema_is_checked_as_any_arrow(tmp_path):
    """A slot `T` without a row is a totality violation, `T?` without one is none, an arrow to no element a
    reference violation (§5.1, in the four states)."""
    d = written(tmp_path, "module")
    files = compile_dir(d, tmp_path / "out")
    (tmp_path / "facts.yaml").write_text("alpha: [{id: a, title: t}]\n"
                                         "gamma: [{id: g, note: n}, {id: h}]\n"
                                         "delta: [{id: d, gamma: g, alpha: z, grade: first}]\n")
    got = violations(files, facts.load(pack.read(d), tmp_path / "facts.yaml"))
    assert got == text({"gamma__note__totality": {("h",)}, "delta__alpha__reference": {("d", "z")}})


def test_a_writer_reads_the_classes_of_a_module_as_it_reads_a_schema_file(tmp_path):
    for how in ("schema", "module"):
        layout = writer.layout(written(tmp_path, how))
        assert layout.declared["delta"] == ["id", "gamma", "alpha", "state", "grade"]


def test_unbounded_lists_compile_like_written_linkml(tmp_path):
    oracle = Path(shutil.copytree(FIXTURE, tmp_path / "yaml" / "minimal"))
    source = Path(shutil.copytree(FIXTURE, tmp_path / "rezono" / "minimal"))
    (oracle / "schema/roles.yaml").write_text(
        """id: https://rezono.example/roles
name: roles
imports: [linkml:types, minimal]
default_range: string
annotations: {layer: facts}
enums:
  Capability:
    permissible_values: {read: {}, review: {}}
classes:
  Role:
    attributes:
      id: {identifier: true}
      capability: {range: Capability, multivalued: true}
      reviewers: {range: Alpha, multivalued: true, required: true}
""", encoding="utf-8",
    )
    module(source, [
        {"enum": "Capability", "world": "closed", "values": ["read", "review"]},
        {"kind": "Role", "world": "closed", "slots": [
            {"slot": "capability", "type": "Capability", "card": "*"},
            {"slot": "reviewers", "type": "Alpha", "card": "+"},
        ]},
    ], name="roles")

    records = {
        "alpha": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
        "role": [
            {"id": "absent", "reviewers": ["a"]},
            {"id": "empty", "capability": [], "reviewers": ["a"]},
            {"id": "both", "capability": ["read", "review"], "reviewers": ["a", "b"]},
            {"id": "missing", "capability": ["review"]},
            {"id": "required-empty", "reviewers": []},
            {"id": "refused", "capability": ["other"], "reviewers": ["z"]},
        ],
    }
    expected_rows = {
        "role__capability": {("both", "read"), ("both", "review"), ("missing", "review"), ("refused", "other")},
        "role__reviewers": {("absent", "a"), ("empty", "a"), ("both", "a"), ("both", "b"), ("refused", "z")},
    }
    expected_violations = {
        "role__reviewers__totality": {("missing", ""), ("required-empty", "")},
        "role__reviewers__reference": {("refused", "z")},
        "role__capability__value_range": {("refused", "other")},
    }
    for name, directory in (("yaml", oracle), ("rezono", source)):
        output = tmp_path / "compiled" / name
        assert main(["compile", str(directory), str(output)]) == 0
        files = {path.relative_to(output).as_posix(): path.read_text(encoding="utf-8")
                 for path in output.rglob("*") if path.is_file()}
        bundle = json.loads(files["bundle/schema-bundle.json"])
        capability = next(slot for slot in bundle["attributes"] if slot["id"] == "role.capability")
        reviewers = next(slot for slot in bundle["arrows"] if slot["id"] == "role.reviewers")
        assert capability["multivalued"] and not capability["required"]
        assert reviewers["multivalued"] and reviewers["required"] and reviewers["target"] == "alpha"
        for slot in (capability, reviewers):
            assert "minimum_cardinality" not in slot and "maximum_cardinality" not in slot
            assert slot["span"]["file"] == ("rezono/roles.rezono" if name == "rezono" else "schema/roles.yaml")
        rows = facts.rows_of(pack.read(directory), records)
        assert {rel: set(rows[rel]) for rel in expected_rows} == expected_rows
        assert violations(files, rows) == expected_violations


def test_compile_refuses_invalid_source_places(tmp_path, capsys):
    directory = written(tmp_path, "module")
    path = directory / "rezono/kinds.json"
    form = json.loads(path.read_bytes())
    places = form["spans"]
    first, *rest = places
    changes = [
        [], places[:-1], places + [places[-1]], list(reversed(places)), [places[1], *rest],
        [{}, *rest], [None, *rest], [dict(first, at="/decls/unknown"), *rest],
        [dict(first, text="unexpected"), *rest], [dict(first, line="0"), *rest],
        [dict(first, line="01"), *rest], [dict(first, start="١"), *rest],
        [dict(first, line=True), *rest], [dict(first, start=True), *rest],
        [dict(first, start=-1), *rest], [dict(first, start="-1"), *rest],
        [dict(first, end="0"), *rest],
    ]
    output = tmp_path / "out"
    for changed in changes:
        path.write_text(json.dumps(dict(form, spans=changed)), encoding="utf-8")
        assert main(["compile", str(directory), str(output)]) == 1, changed
        assert "rezono/kinds.json: spans" in capsys.readouterr().err
        assert not (output / "bundle/schema-bundle.json").exists()


def test_the_language_readers_places_are_accepted_in_canonical_order(tmp_path):
    # Produced by the language reader from rezono/test/module.rezono, including nested unless clauses and ranges.
    fixture = HERE.parents[3] / "contracts/fixtures/rezono-module/ModuleForm/valid/every-member.yaml"
    form = json.loads(fixture.read_bytes())
    assert list(rezono_module.place_pointers(form["module"])) == [p["at"] for p in form["spans"]]
    assert rezono_module.valid_places(form["module"], form["spans"])

    directory = written(tmp_path, "module")
    source = directory / "rezono/kinds.rezono"
    path = directory / "rezono/kinds.json"
    text = source.read_text(encoding="utf-8")
    prefix = "-- 🪶\n"
    source.write_text(prefix + text, encoding="utf-8")
    form = json.loads(path.read_bytes())
    for place in form["spans"]:
        place["line"] = str(1 + int(place["line"]))
        place["start"] = str(len(prefix) + int(place["start"]))
        place["end"] = place["start"]  # Zero-width spans are valid.
    path.write_text(json.dumps(form), encoding="utf-8")
    bundle = json.loads(compile_dir(directory, tmp_path / "out")["bundle/schema-bundle.json"])
    gamma = next(k for k in bundle["kinds"] if k["id"] == "gamma")
    assert source.read_text(encoding="utf-8").splitlines()[int(gamma["span"]["line"]) - 1][
        int(gamma["span"]["column"]) - 1:].startswith("Gamma")

    # The form reader accepts arbitrarily large decimal offsets. A position outside this source has no mark.
    gamma_place = next(p for p in form["spans"] if p["at"] == "/decls/1")
    gamma_place["start"] = gamma_place["end"] = "9" * 5000
    assert rezono_module.valid_places(form["module"], form["spans"])
    path.write_text(json.dumps(form), encoding="utf-8")
    assert ("classes", "Gamma") not in rezono_module.marks(source, path)


def test_a_changed_module_or_form_changes_the_definition_hash(tmp_path):
    d = written(tmp_path, "module")
    before = modules.pack_hash(d)
    assert {p.relative_to(d).as_posix() for p in modules.definition_files(d)} >= {"rezono/kinds.rezono",
                                                                               "rezono/kinds.json"}
    add(d / "rezono" / "kinds.rezono", "\n")
    after = modules.pack_hash(d)
    add(d / "rezono" / "kinds.json", " ")
    assert len({before, after, modules.pack_hash(d)}) == 3


# ---- a module of an imported pack ----

def lib(tmp_path: Path) -> Path:
    """The pack `shared` under a name a `pack` line can write, with a module whose kind has an arrow to a kind
    of its own schema/."""
    d = Path(shutil.copytree(SHARED, tmp_path / "packs" / "lib"))
    meta = yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8"))
    (d / "pack.yaml").write_bytes(yaml.safe_dump(dict(meta, name="lib"), sort_keys=False).encode("utf-8"))
    add(d / "labels" / "nl.yaml", "holder: houder\nholder.party: partij\n")
    shutil.copytree(FIXTURE / "messages", d / "messages")  # to compile on its own too
    module(d, [{"kind": "Holder", "world": "closed", "slots": [{"slot": "party", "type": "Party"}], "derived": []}],
           pack="lib", name="holder")
    return d


def test_a_module_of_an_imported_pack_is_read_as_its_schema_is(tmp_path):
    imported = lib(tmp_path)
    assert "holder" in pack.read(imported).kinds  # on its own
    d = Path(shutil.copytree(FIXTURE, tmp_path / "packs" / "main"))
    meta = yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8"))
    meta["imports"] = [{"name": "lib", "path": "../lib", "sha256": modules.pack_hash(imported)}]
    (d / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))
    b = json.loads(compile_dir(d, tmp_path / "out")["bundle/schema-bundle.json"])
    assert {"module": "lib:holder", "file": "rezono/holder.rezono", "pack": "lib", "name": "holder",
            "id": "https://rezono.org/rezono/lib/holder"} in b["schemas"]
    assert {k["id"]: k["module"] for k in b["kinds"]}["holder"] == "lib:holder"
    assert {a["id"]: (a["target"], a["required"]) for a in b["arrows"]}["holder.party"] == ("party", True)


def test_a_legacy_schema_imports_a_lowered_module_from_a_pinned_pack(tmp_path):
    imported = lib(tmp_path)
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "packs" / "main"))
    metadata = directory / "pack.yaml"
    meta = yaml.safe_load(metadata.read_bytes())
    meta["imports"] = [{"name": "lib", "path": "../lib", "sha256": modules.pack_hash(imported)}]
    metadata.write_bytes(yaml.safe_dump(meta).encode("utf-8"))
    source = directory / "schema/minimal.yaml"
    schema = yaml.safe_load(source.read_bytes())
    schema["imports"].append("lib:holder")
    schema["classes"]["Alpha"]["attributes"]["holder"] = {"range": "Holder"}
    source.write_bytes(yaml.safe_dump(schema).encode("utf-8"))
    add(directory / "labels/nl.yaml", "alpha.holder: houder\n")

    bundle = json.loads(compile_dir(directory, tmp_path / "out")["bundle/schema-bundle.json"])

    assert not (imported / "schema/holder.yaml").exists()
    assert any(s["module"] == "lib:holder" and s["file"] == "rezono/holder.rezono" for s in bundle["schemas"])
    assert {a["id"]: a["target"] for a in bundle["arrows"]}["alpha.holder"] == "holder"

    schema["imports"][-1] = "lib:missing"
    source.write_bytes(yaml.safe_dump(schema).encode("utf-8"))
    with pytest.raises(pack.CompileError, match="import 'lib:missing' is not a module"):
        pack.read(directory)

    relay = directory.with_name("relay")
    relay.mkdir()
    (relay / "pack.yaml").write_bytes(yaml.safe_dump({"name": "relay", "imports": meta["imports"]}).encode("utf-8"))
    meta["imports"] = [{"name": "relay", "path": "../relay", "sha256": modules.pack_hash(relay)}]
    metadata.write_bytes(yaml.safe_dump(meta).encode("utf-8"))
    schema["imports"][-1] = "lib:holder"
    source.write_bytes(yaml.safe_dump(schema).encode("utf-8"))
    with pytest.raises(pack.CompileError, match="import 'lib:holder' names no pack that minimal imports"):
        pack.read(directory)


def test_a_legacy_relative_import_stays_at_its_schema_directory(tmp_path):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    module(directory, [{"kind": "RootHolder", "world": "closed", "slots": [], "derived": []}], name="holder")
    (directory / "rezono/terms").mkdir()
    module(directory, [{"kind": "NestedHolder", "world": "closed", "slots": [], "derived": []}], name="terms/holder")
    source = directory / "schema/minimal.yaml"
    schema = yaml.safe_load(source.read_bytes())
    schema["imports"].extend(["holder", "terms/child"])
    schema["classes"]["Alpha"]["attributes"]["holder"] = {"range": "RootHolder"}
    source.write_bytes(yaml.safe_dump(schema).encode("utf-8"))
    (directory / "schema/terms").mkdir()
    (directory / "schema/terms/child.yaml").write_text(
        "id: https://rezono.example/child\nname: child\nimports: [linkml:types, holder]\n"
        "default_range: string\nannotations: {layer: facts}\nclasses:\n  Child:\n    attributes:\n"
        "      id: {identifier: true}\n      holder: {range: NestedHolder}\n", encoding="utf-8"
    )
    add(directory / "labels/nl.yaml",
        "alpha.holder: houder\nroot_holder: houder\nnested_holder: houder\nchild: kind\nchild.holder: houder\n")

    bundle = json.loads(compile_dir(directory, tmp_path / "out")["bundle/schema-bundle.json"])

    targets = {arrow["id"]: arrow["target"] for arrow in bundle["arrows"]}
    assert targets["alpha.holder"] == "root_holder"
    assert targets["child.holder"] == "nested_holder"


@pytest.mark.parametrize("pack_order", [("left", "right"), ("right", "left")])
def test_relative_imports_in_two_pinned_packs_keep_distinct_modules(tmp_path, pack_order):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    metadata = directory / "pack.yaml"
    meta = yaml.safe_load(metadata.read_bytes())
    root_schema = directory / "schema/minimal.yaml"
    schema = yaml.safe_load(root_schema.read_bytes())
    meta["imports"] = []
    for side in pack_order:
        identity = f"{side}pack"
        imported = tmp_path / identity
        (imported / "schema").mkdir(parents=True)
        (imported / "labels").mkdir()
        (imported / "labels/nl.yaml").write_bytes(f"{side}: {side}\n".encode("utf-8"))
        (imported / "pack.yaml").write_bytes(f"name: {identity}\nversion: '0'\ndefault_language: nl\n".encode("utf-8"))
        (imported / "schema/consumer.yaml").write_bytes(
            f"id: https://rezono.example/{identity}/consumer\nname: consumer\nimports: [linkml:types, holder]\n"
            "annotations: {layer: facts}\n".encode("utf-8")
        )
        kind = side.title()
        module(imported, [{"kind": kind, "world": "closed", "slots": [], "derived": []}], pack=identity, name="holder")
        meta["imports"].append({"name": identity, "path": f"../{identity}", "sha256": modules.pack_hash(imported)})
        schema["imports"].append(f"{identity}:consumer")
        schema["classes"]["Alpha"]["attributes"][side] = {"range": kind}
        add(directory / "labels/nl.yaml", f"alpha.{side}: {side}\n")
    metadata.write_bytes(yaml.safe_dump(meta).encode("utf-8"))
    root_schema.write_bytes(yaml.safe_dump(schema).encode("utf-8"))

    bundle = json.loads(compile_dir(directory, tmp_path / "out")["bundle/schema-bundle.json"])

    assert {a["id"]: a["target"] for a in bundle["arrows"] if a["id"].startswith("alpha.")} == {
        "alpha.left": "left", "alpha.right": "right",
    }
    assert {(v["module"], v["file"]) for v in bundle["schemas"] if v["module"].endswith(":holder")} == {
        ("leftpack:holder", "rezono/holder.rezono"), ("rightpack:holder", "rezono/holder.rezono"),
    }

    left = tmp_path / "leftpack"
    source = left / "schema/consumer.yaml"
    source.write_bytes(source.read_bytes().replace(b", holder]", b", rightpack:holder]"))
    with pytest.raises(pack.CompileError, match="not the pinned"):
        pack.read(directory)
    next(pin for pin in meta["imports"] if pin["name"] == "leftpack")["sha256"] = modules.pack_hash(left)
    metadata.write_bytes(yaml.safe_dump(meta).encode("utf-8"))
    with pytest.raises(pack.CompileError, match="import 'rightpack:holder' names no pack that leftpack imports"):
        pack.read(directory)


def test_a_pack_may_hold_modules_only(tmp_path):
    d = tmp_path / "only"
    (d / "labels").mkdir(parents=True)
    shutil.copytree(FIXTURE / "messages", d / "messages")
    (d / "pack.yaml").write_bytes(b'name: only\nversion: "0"\ndefault_language: nl\n')
    (d / "channels.yaml").write_bytes(b"kinds:\n  - {kind: eta, shape: rect}\n")
    (d / "labels" / "nl.yaml").write_bytes("eta: eta\neta.since: sinds\n".encode("utf-8"))
    module(d, [{"kind": "Eta", "world": "closed", "slots": [{"card": "?", "slot": "since", "type": "Date"}],
                "derived": []}], pack="only")
    assert {k: (kind.module, kind.layer) for k, kind in pack.read(d).kinds.items()} == {"eta": ("m", "facts")}


# ---- refused at its line ----

def module(d: Path, decls: list, pack: str = "minimal", use=(), rezono: str | None = "0", layer: str = "facts",
           name: str = "m") -> None:
    """A module as `rezono/` writes its form, with the places of a text laid out by hand: a `use` line on line
    3 and on, declaration i on line 10(i+1), its slots on the lines under it, its derived values from 5 lines
    under it and its `applies` 9 lines under it. The text holds only the header, the lines a refusal of a
    header line names."""
    def fixture_line(pointer: str) -> int:
        group, index, *rest = pointer[1:].split("/")
        if group == "use":
            return 3 + int(index)
        base = 10 * (1 + int(index))
        if rest[:1] == ["slots"]:
            return base + 1 + int(rest[1])
        if rest[:1] == ["derived"]:
            return base + 5 + int(rest[1])
        return base + 9 if rest[:1] == ["applies"] else base

    body = {"decls": decls, "pack": pack, "use": [{"use": u} for u in use]}
    if rezono is not None:
        body["rezono"] = rezono
    spans = [{"at": p, "line": str(fixture_line(p)), "start": "0", "end": "1"}
             for p in rezono_module.place_pointers(body)]
    (d / "rezono").mkdir(exist_ok=True)
    (d / "rezono" / f"{name}.json").write_bytes(json.dumps({"format": "rezono.module/1", "module": body,
                                                            "spans": spans},
                                                           sort_keys=True).encode("utf-8"))
    header = (f"rezono {rezono}\n" if rezono is not None else "") + f"pack {pack}\n"
    (d / "rezono" / f"{name}.rezono").write_bytes(header.encode("utf-8"))
    meta = yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8"))
    entry = {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": layer}
    declare(d, [e for e in meta.get("rezono") or [] if e["module"] != entry["module"]] + [entry])


def eta(**more) -> dict:
    return {"kind": "Eta", "world": "closed", "slots": [{"slot": "beta", "type": "Beta"}], "derived": []} | more


def slot(**s) -> dict:
    return eta(slots=[s])


@pytest.mark.parametrize("declaration", ["forward", "another_module", "none"])
def test_a_bool_slot_prefers_a_declared_kind(tmp_path, declaration):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    source = slot(slot="linked", type="Bool")
    target = eta(kind="Bool")
    if declaration == "forward":
        module(d, [source, target])
    else:
        module(d, [source])
        if declaration == "another_module":
            module(d, [target], name="target")
    linked = pack.read(d).slot("eta", "linked")
    classes = rezono_module.schema_classes(d, "rezono/m.rezono")
    assert classes["Eta"]["attributes"]["linked"]["range"] == ("boolean" if declaration == "none" else "Bool")
    if declaration == "none":
        assert not linked.arrow
        assert linked.sql_type == "BOOLEAN"
    else:
        assert linked.arrow
        assert linked.range == "bool"


def test_an_unknown_slot_type_lists_builtin_bool(tmp_path):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    module(d, [slot(slot="linked", type="Omega")])
    with pytest.raises(pack.CompileError, match="Built-in Bool"):
        pack.read(d)


BOOL = {"derived": "ok", "type": "Bool", "value": {"lit": "true"}}
REFUSALS = {
    "an open kind": ([eta(world="open")], 10, "an open kind is refused"),
    "a kind without a world": ([{k: v for k, v in eta().items() if k != "world"}], 10, "an open kind is refused"),
    "applies": ([eta(applies={"axis": "at", "slot": "beta"})], 19, "`applies` is not lowered yet"),
    "sealed at": ([eta(sealed="beta")], 10, "`sealed at` is not lowered yet"),
    "a derived value in a kind": ([eta(derived=[BOOL])], 15, "a derived value is not lowered yet"),
    "extend": ([{"extend": "Beta", "derived": [BOOL]}], 15, "a derived value is not lowered yet"),
    "a fact table": ([{"fact": "Beta", "columns": ["id"], "rows": [[{"lit": "b"}]]}], 10, "a fact table is not lowered"),
    "a fact row": ([{"fact": "beta", "id": "b", "set": []}], 10, "a fact row is not lowered"),
    "a rounding": ([{"rounding": "money", "mode": "half_even"}], 10, "a rounding is not lowered yet"),
    "a parameter": ([{"param": "p", "type": "Date"}], 10, "a parameter is not lowered yet"),
    "a check": ([{"check": "warn", "cond": {"lit": "true"}}], 10, "a check statement is not lowered yet"),
    "a reason": ([{"reason": "r", "text": '"r"'}], 10, "a reason declaration is not lowered"),
    "a slot named id": ([slot(slot="id", type="Text")], 11, "a slot named `id` is refused"),
    "an unknown slot suffix": ([slot(slot="many", type="Text", card="**")], 11, "a slot `Text**` is not lowered"),
    "an inverse": ([slot(slot="many", type="Beta", card="*", inverse="eta")], 11, "a slot with inverse is not lowered"),
    "world on a slot": ([slot(slot="note", type="Text", world="open")], 11, "a slot with world is not lowered"),
    "a DateTime slot": ([slot(slot="observed_at", type="DateTime")], 11, "DateTime is not Date, Text, or an enum or a kind of this pack"),
    "a Money slot": ([slot(slot="cost", type="Money<EUR>")], 11, "Money<EUR> is not Date, Text"),
    "a name the pack lacks": ([slot(slot="other", type="Omega")], 11, "Omega is not Date, Text"),
    "an open enum": ([{"enum": "Tone", "world": "open", "values": ["dim"]}], 10, "an open enum (`world open`) is refused"),
    "a name schema/ declares": ([eta(kind="Alpha")], 10, "Alpha is also declared by module minimal"),
    "a name twice": ([eta(), eta()], 20, "Eta is declared twice in this module"),
    "a slot twice": ([eta(slots=[{"slot": "since", "type": "Date"}, {"card": "?", "slot": "since", "type": "Text"}])],
                     12, "the slot since is written twice in kind Eta"),
    "a value twice": ([{"enum": "Tone", "world": "closed", "values": ["dim", "dim"]}], 10,
                      "the value dim is written twice in enum Tone"),
}


@pytest.mark.parametrize("decls, line, message", REFUSALS.values(), ids=REFUSALS)
def test_what_the_slice_does_not_lower_is_refused_at_its_line(tmp_path, decls, line, message):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    module(d, decls)
    with pytest.raises(pack.CompileError, match=re.escape(f"minimal/rezono/m.rezono:{line}: {message}")):
        pack.read(d)


@pytest.mark.parametrize("header, line, message", [
    ({"pack": "other"}, 2, "the `pack` line names other, not this pack, minimal"),
    ({"rezono": "1"}, 1, "the `rezono` line says 0, not 1"),
    ({"use": ["std.money"]}, 3, "a `use` line is not lowered"),
], ids=["another pack", "another language version", "use"])
def test_a_header_line_is_refused_at_its_line(tmp_path, header, line, message):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    module(d, [eta()], **header)
    with pytest.raises(pack.CompileError, match=re.escape(f"minimal/rezono/m.rezono:{line}: {message}")):
        pack.read(d)


@pytest.mark.parametrize("change, message", [
    (lambda d: (d / "rezono" / "stray.rezono").write_bytes(b"rezono 0\n"),
     "minimal/rezono/stray.rezono: pack.yaml names no module or form at this path"),
    (lambda d: (d / "rezono" / "m.json").unlink(), "form rezono/m.json is not a file"),
    (lambda d: (d / "rezono" / "m.json").write_bytes(b'{"format": "rezono.module/1"}'),
     "minimal/rezono/m.json: not the form of a module"),
    (lambda d: module(d, [eta()], layer="middle"), "layer must be one of"),
    (lambda d: declare(d, [{"module": "m.rezono", "form": "rezono/m.json", "layer": "facts"}]),
     "module is a path under rezono/"),
], ids=["a file pack.yaml does not name", "no form", "not a form", "no layer", "outside rezono/"])
def test_pack_yaml_names_each_module_with_its_form_and_layer(tmp_path, change, message):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    add(d / "labels" / "nl.yaml", "eta: eta\neta.beta: bèta\n")
    module(d, [eta()])
    pack.read(d)  # the module as written compiles
    change(d)
    with pytest.raises(pack.CompileError, match=re.escape(message)):
        pack.read(d)
