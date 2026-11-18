"""Discover declared data modules through the compiler entry point used by publication."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import facts, pack, scenarios
from rezono_compiler.__main__ import main


def test_named_dataset_discovery(tmp_path):
    source = tmp_path / "rezono"
    source.mkdir()
    manifest = []
    for name in ("valid", "errors", "schema", "unlisted"):
        decls = [] if name == "schema" else [{"dataset": name, "decls": []}]
        form = {"format": "rezono.module/2", "spans": [], "module": {
            "rezono": "0", "pack": "library", "use": [], "decls": decls,
        }}
        (source / f"{name}.json").write_text(json.dumps(form), encoding="utf-8")
        text = "rezono 0\npack library\n"
        if decls:
            text += f"dataset {name}\n"
        (source / f"{name}.rezono").write_text(text, encoding="utf-8")
        if name != "unlisted":
            manifest.append({"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "facts"})
    meta = {"name": "library", "version": "0.1.0", "imports": [], "rezono": manifest}
    (tmp_path / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    assert sorted(facts.files(tmp_path)) == [source / "errors.json", source / "valid.json"]

    path = source / "valid.json"
    wrong = json.loads(path.read_bytes())
    wrong["module"]["decls"][0]["dataset"] = "alternate"
    path.write_text(json.dumps(wrong), encoding="utf-8")
    (source / "valid.rezono").write_text("rezono 0\npack library\ndataset alternate\n", encoding="utf-8")
    with pytest.raises(facts.LoadError) as caught:
        facts.files(tmp_path)
    assert "valid" in str(caught.value) and "alternate" in str(caught.value)


@pytest.fixture
def declared_dataset(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "minimal"
    root = Path(shutil.copytree(fixture, tmp_path / "minimal"))
    directory = root / "rezono" / "data"
    directory.mkdir(parents=True)
    (directory / "sample.rezono").write_text(
        "rezono 0\npack minimal\ndataset sample\n", encoding="utf-8"
    )
    metadata = root / "pack.yaml"
    with metadata.open("a", encoding="utf-8") as stream:
        yaml.safe_dump({"rezono": [{"module": "rezono/data/sample.rezono",
                                    "form": "rezono/data/sample.json", "layer": "facts"}]}, stream)
    tables = [
        {"fact": "Alpha", "columns": ["id", "title", "size"],
         "rows": [[{"lit": "sample-item"}, {"lit": '"Sample title"'}, {"lit": "7"}]]},
        {"fact": "Alpha", "columns": ["id", "title"],
         "rows": [[{"lit": "other-item"}, {"lit": '"Other title"'}]]},
    ]
    form = {"format": "rezono.module/2", "spans": [], "module": {
        "rezono": "0", "pack": "minimal", "use": [], "decls": [{"dataset": "sample", "decls": tables}],
    }}
    return root, directory / "sample.json", form


def test_declared_dataset_compiles_and_checks_with_typed_rows(declared_dataset, tmp_path, capsys):
    root, form_path, form = declared_dataset
    form_path.write_text(json.dumps(form), encoding="utf-8")
    output = tmp_path / "compiled"

    assert facts.files(root) == [form_path]
    assert main(["compile", str(root), str(output)]) == 0
    assert main(["check", str(root)]) == 0
    assert "2 kinds; sample.json 5 rows" in capsys.readouterr().out
    assert main(["facts", str(root), str(form_path)]) == 0
    assert json.loads(capsys.readouterr().out)["alpha__size"] == [{"insert": {"id": "sample-item", "v": 7}}]
    assert scenarios.states(pack.read(root), root)[0][1]["alpha__size"] == [("sample-item", 7)]

    entries = json.loads((output / "generated/sources.json").read_bytes())
    names = {
        ("alpha", '["sample-item"]'): 0,
        ("alpha__title", '["sample-item","Sample title"]'): 0,
        ("alpha__size", '["sample-item","7"]'): 0,
        ("alpha", '["other-item"]'): 1,
        ("alpha__title", '["other-item","Other title"]'): 1,
    }
    name = "rezono/data/sample.json"
    assert len(entries) == len(names)
    for entry in entries:
        row = entry["row"]
        index = names[(row["relation"], row["key"])]
        assert entry["sources"] == [
            {"kind": "pack", "name": name, "position": f"{name}#/module/decls/0/decls/{index}/rows/0"}
        ]


@pytest.mark.parametrize("fault", ["future_format", "mixed", "invalid_cell", "theory"])
def test_declared_dataset_rejects_invalid_forms(declared_dataset, tmp_path, capsys, fault):
    root, form_path, form = declared_dataset
    if fault == "future_format":
        form["format"] = "rezono.module/999"
    elif fault == "mixed":
        form["module"]["decls"].append({"kind": "Unexpected"})
    elif fault == "invalid_cell":
        form["module"]["decls"][0]["decls"][0]["rows"][0][2]["lit"] = "true"
    else:
        with (root / "pack.yaml").open("a", encoding="utf-8") as stream:
            stream.write("theory: true\n")
    form_path.write_text(json.dumps(form), encoding="utf-8")

    output = tmp_path / "compiled"
    assert main(["compile", str(root), str(output)]) == 1
    assert main(["check", str(root)]) == 1
    assert not output.exists()
    assert "sample.json" in capsys.readouterr().err
