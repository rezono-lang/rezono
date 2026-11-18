"""An authored legacy pack is the oracle for a mixed pack's linked rule program."""

import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, modules, pack
from support import FIXTURE


def write_legacy(directory, stem, source):
    rules = directory / "rules"
    rules.mkdir(exist_ok=True)
    (rules / f"{stem}.dl").write_text(source, encoding="utf-8", newline="\n")


def write_native(directory, stem, source, uses, declaration, positions):
    """Record the authored tree and locate its explicitly listed nodes in the source."""
    forms = directory / "rezono"
    forms.mkdir(exist_ok=True)
    lines = source.splitlines(keepends=True)
    spans = []
    for pointer, line, fragment, after in positions:
        start = lines[line - 1].index(fragment, after)
        offset = sum(map(len, lines[:line - 1])) + start
        spans.append({"at": pointer, "line": str(line), "start": str(offset), "end": str(offset + len(fragment))})
    form = {
        "format": "rezono.module/3",
        "module": {"rezono": "0", "pack": lines[1].split()[1], "use": uses, "decls": [declaration]},
        "spans": spans,
    }
    (forms / f"{stem}.rezono").write_text(source, encoding="utf-8", newline="\n")
    (forms / f"{stem}.json").write_text(json.dumps(form, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return {"module": f"rezono/{stem}.rezono", "form": f"rezono/{stem}.json", "layer": "facts"}


def write_metadata(directory, **changes):
    path = directory / "pack.yaml"
    metadata = yaml.safe_load(path.read_text(encoding="utf-8"))
    metadata.update(changes)
    path.write_text(yaml.safe_dump(metadata), encoding="utf-8", newline="\n")


def write_native_extension(directory, stem, kind):
    body = f"x in {kind}.id"
    return write_native(
        directory, stem, f"rezono 0\npack minimal\nuse shared-terms as terms\nrule terms.listed(x) when {body}\n",
        [{"use": "shared-terms", "as": "terms"}],
        {"rule": "terms.listed", "args": [{"path": ["x"]}],
         "when": {"in": [{"path": ["x"]}, {"dot": [{"kind": kind}, "id"]}]}},
        [
            ("/decls/0", 4, "terms.listed", 0),
            ("/decls/0/args/0", 4, "x", 0),
            ("/decls/0/when", 4, body, 0),
            ("/decls/0/when/in/0", 4, "x", 25),
            ("/decls/0/when/in/1", 4, f"{kind}.id", 0),
            ("/decls/0/when/in/1/dot/0", 4, kind, 0),
            ("/use/0", 3, "shared-terms", 0),
        ],
    )


def compile_fixture(root, *, mixed):
    consumer = root / "minimal"
    owner = root / "shared"
    shutil.copytree(FIXTURE, consumer)
    shutil.copytree(FIXTURE.parent / "shared", owner)
    write_legacy(consumer, "middle", 'listed(x) :- alpha__title(x, "A").\n')
    if mixed:
        signature = write_native(
            owner, "core", "rezono 0\npack shared-terms\nrule listed(item: Text) extend\n", [],
            {"rule": "listed", "columns": [{"name": "item", "type": "Text"}], "options": [{"extend": True}]},
            [("/decls/0", 3, "listed", 0), ("/decls/0/columns/0", 3, "item", 0), ("/decls/0/options/0", 3, "extend", 0)],
        )
        write_metadata(owner, rezono=[signature])
        last = write_native_extension(consumer, "z_items", "Beta")
        first = write_native_extension(consumer, "a_items", "Alpha")
        write_metadata(consumer, rezono=[last, first])
    else:
        write_legacy(owner, "core", "// @extend\n.decl listed(item: symbol)\n")
        write_legacy(consumer, "z_items", "listed(x) :- beta(x).\n")
        write_legacy(consumer, "a_items", "listed(x) :- alpha(x).\n")
    pin = {"name": "shared-terms", "path": "../shared", "sha256": modules.pack_hash(owner)}
    write_metadata(consumer, imports=[pin])
    return consumer, owner, pin


def compile_pack(directory):
    return emit.compile_pack(pack.read(directory))


def rule_program(artifacts):
    document = json.loads(artifacts["ir/rules.json"])
    origins = [rule.pop("origin") for rule in document["rules"]]
    return document, origins


def test_native_rule_pack_link(tmp_path):
    legacy, _, _ = compile_fixture(tmp_path / "legacy", mixed=False)
    expected, _ = rule_program(compile_pack(legacy))
    assert [(rule["id"], rule["body"][0]["relation"]) for rule in expected["rules"]] == [
        ("listed_1", "alpha"), ("listed_2", "alpha__title"), ("listed_3", "beta"),
    ]
    [signature] = [relation for relation in expected["relations"] if relation["role"] == "derived"]
    assert (signature["name"], signature["key"], signature["module"], signature["extend"]) == (
        "listed", [{"name": "item", "type": "string"}], "import_shared_terms_core", True,
    )

    mixed, owner, pin = compile_fixture(tmp_path / "mixed", mixed=True)
    artifacts = compile_pack(mixed)
    actual, origins = rule_program(artifacts)
    assert actual == expected
    assert origins == [
        {"file": "rezono/a_items.rezono", "line": "4"},
        {"file": "rules/middle.dl", "line": "1"},
        {"file": "rezono/z_items.rezono", "line": "4"},
    ]
    assert compile_pack(mixed) == artifacts

    form = owner / "rezono/core.json"
    original = form.read_bytes()
    form.write_bytes(original + b"\n")
    with pytest.raises(pack.CompileError, match="not the pinned"):
        compile_pack(mixed)
    form.write_bytes(original)

    write_metadata(mixed, imports=[])
    with pytest.raises(pack.CompileError) as missing:
        compile_pack(mixed)
    assert "R046" in {item.code for item in missing.value.diagnostics}
    write_metadata(mixed, imports=[pin])

    # An extension may supply a clause. A second typed signature would claim ownership.
    duplicate = write_native(
        mixed, "extra", "rezono 0\npack minimal\nrule listed(item: Text) when item in Alpha.id\n", [],
        {"rule": "listed", "columns": [{"name": "item", "type": "Text"}],
         "when": {"in": [{"path": ["item"]}, {"dot": [{"kind": "Alpha"}, "id"]}]}},
        [
            ("/decls/0", 3, "listed", 0),
            ("/decls/0/columns/0", 3, "item", 0),
            ("/decls/0/when", 3, "item in Alpha.id", 0),
            ("/decls/0/when/in/0", 3, "item", 24),
            ("/decls/0/when/in/1", 3, "Alpha.id", 0),
            ("/decls/0/when/in/1/dot/0", 3, "Alpha", 0),
        ],
    )
    metadata = yaml.safe_load((mixed / "pack.yaml").read_text(encoding="utf-8"))
    write_metadata(mixed, rezono=[*metadata["rezono"], duplicate])
    with pytest.raises(pack.CompileError) as competing:
        compile_pack(mixed)
    assert "R040" in {item.code for item in competing.value.diagnostics}
