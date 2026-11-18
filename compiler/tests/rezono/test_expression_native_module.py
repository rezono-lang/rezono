"""Exercise native dispatch and verified use through ordinary compilation."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from rezono_compiler import emit, modules, pack
from support import FIXTURE
from test_native_rule_pack_link import write_metadata


ROOT = Path(__file__).resolve().parents[3]


def author(directory, name, source, version):
    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.rezono"
    form = path.with_suffix(".json")
    path.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(path), str(form)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(form.read_bytes())["format"] == f"rezono.module/{version}"
    return {"module": f"rezono/{path.name}", "form": f"rezono/{form.name}", "layer": "facts"}


def compiled(directory):
    files = emit.compile_pack(pack.read(directory))
    return json.loads(files["ir/rules.json"]), json.loads(files["bundle/schema-bundle.json"])


def pin(directory):
    manifest = yaml.safe_load((directory / "pack.yaml").read_bytes())
    return {"name": manifest["name"], "path": f"../{directory.name}", "sha256": modules.pack_hash(directory)}


def test_native_module_dispatch(tmp_path):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    native = author(directory, "ours", """rezono 0
pack minimal
kind Panel world closed
  description "A neutral panel."
  title: Text
rule panel_present(panel: Panel) when panel in Panel
""", 3)
    pipe = author(directory, "legacy", """rezono 0
pack minimal
rules old_members
  | .decl old_present(item: symbol)
  | old_present(x) :- alpha(x).
""", 2)
    write_metadata(directory, rezono=[native, pipe])

    program, bundle = compiled(directory)
    assert [item["id"] for item in bundle["kinds"]].count("panel") == 1
    rules = {rule["head"]["relation"]: rule for rule in program["rules"]}
    assert len(program["rules"]) == len(rules) == 2
    assert {name: rule["body"][0]["relation"] for name, rule in rules.items()} == {
        "panel_present": "panel", "old_present": "alpha",
    }
    assert rules["panel_present"]["origin"] == {"file": "rezono/ours.rezono", "line": "6"}
    assert rules["old_present"]["origin"] == {"file": "rezono/legacy.rezono", "line": "5"}

    # Reading /3 must retain metadata whose syntax already required /2.
    errors = []
    loaded, _ = modules.load(directory, pack.read_meta(directory), errors)
    assert not errors
    [panel] = [module.sv.schema.classes["Panel"] for module in loaded if "Panel" in module.sv.schema.classes]
    assert panel.description == "A neutral panel."


def test_native_module_use(tmp_path):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    owner = Path(shutil.copytree(FIXTURE.parent / "shared", tmp_path / "shared"))
    native = author(directory, "ours", """rezono 0
pack minimal
use shared-terms as terms
rule catalogue_member(item: terms.Party) when item in terms.Party
""", 3)
    owner_pin = pin(owner)
    write_metadata(directory, rezono=[native], imports=[owner_pin])
    program, _ = compiled(directory)
    [rule] = program["rules"]
    assert rule["head"]["relation"] == "catalogue_member"
    assert rule["body"][0]["relation"] == "party"
    assert rule["origin"] == {"file": "rezono/ours.rezono", "line": "4"}

    write_metadata(directory, imports=[owner_pin | {"sha256": "0" * 64}])
    with pytest.raises(pack.CompileError, match="not the pinned"):
        compiled(directory)

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "pack.yaml").write_text("name: other-terms\nversion: 0.1.0\ndefault_language: nl\n", encoding="utf-8")
    (sibling / "schema").mkdir()
    (sibling / "schema/terms.yaml").write_text(
        "id: https://rezono.example/other-terms\nname: other_terms\nimports: [linkml:types]\n"
        "default_range: string\nannotations: {layer: facts}\n"
        "classes:\n  Parcel:\n    attributes:\n      id: {identifier: true}\n",
        encoding="utf-8",
    )
    unauthorized = author(owner, "borrowed", """rezono 0
pack shared-terms
use other-terms as other
rule borrowed(item: other.Parcel) when item in other.Parcel
""", 3)
    write_metadata(owner, rezono=[unauthorized])
    write_metadata(directory, imports=[pin(owner), pin(sibling)])
    with pytest.raises(pack.CompileError) as refused:
        compiled(directory)
    assert any(item.code == "R046" and item.where.endswith("/use/0") for item in refused.value.diagnostics)
