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


@pytest.mark.parametrize("source", [
    "not a valid Rezono declaration\n",
    "rezono 0\npack other\ndataset sample\n",
    "rezono 0\npack minimal\ndataset other\n",
    "rezono 1\npack minimal\ndataset sample\n",
    "rezono 0\npack minimal\ndataset sample\n  broken fact\n",
    "rezono 0\npack minimal\n",
    "rezono 0\npack minimal\ndataset sample\n  fact Alpha\n    | id |\n    | - |\n",
    'rezono 0\npack other\ndataset sample\n  fact Alpha\n    | id |\n    | "item" |\n',
    'rezono 0\npack minimal\ndataset other\n  fact Alpha\n    | id |\n    | "item" |\n',
])
def test_declared_dataset_refuses_invalid_source_with_unchanged_form(declared_dataset, tmp_path, capsys, source):
    root, form_path, form = declared_dataset
    form_path.write_text(json.dumps(form), encoding="utf-8")
    form_path.with_suffix(".rezono").write_text(source, encoding="utf-8")
    output = tmp_path / "compiled"

    assert main(["compile", str(root), str(output)]) == 1
    assert main(["check", str(root)]) == 1
    assert main(["facts", str(root), str(form_path)]) == 1
    assert not output.exists()
    assert capsys.readouterr().err.count("sample.rezono") == 3
    with pytest.raises(facts.LoadError, match=r"sample\.rezono"):
        scenarios.states(pack.read(root), root)


def test_declared_dataset_uses_authored_rows_and_locations(declared_dataset, tmp_path, capsys):
    root, form_path, form = declared_dataset
    form_path.write_text(json.dumps(form), encoding="utf-8")
    original_form = form_path.read_bytes()
    source = form_path.with_suffix(".rezono")
    text = (
        "rezono 0\npack minimal\ndataset sample\n"
        "  fact Alpha\n"
        "    | id | title | size |\n"
        '    | sample-item | "Authored title" | 8 |\n'
        "    | s1 | North | 3 |\n"
    )
    source.write_text(text, encoding="utf-8")
    output = tmp_path / "compiled"

    assert facts.files(root) == [form_path]
    assert main(["compile", str(root), str(output)]) == 0
    assert main(["check", str(root)]) == 0
    assert "sample.json 6 rows" in capsys.readouterr().out
    assert main(["facts", str(root), str(form_path)]) == 0
    assert json.loads(capsys.readouterr().out)["alpha__size"] == [
        {"insert": {"id": "s1", "v": 3}}, {"insert": {"id": "sample-item", "v": 8}}
    ]
    model = pack.read(root)
    assert scenarios.states(model, root)[0][1]["alpha__size"] == [("s1", 3), ("sample-item", 8)]
    entries = json.loads((output / "generated/sources.json").read_bytes())
    assert {entry["row"]["relation"] for entry in entries} == {"alpha", "alpha__title", "alpha__size"}
    for entry in entries:
        identifier = json.loads(entry["row"]["key"])[0]
        assert entry["sources"] == [
            {"kind": "pack", "name": "rezono/data/sample.rezono", "position": {"sample-item": "6", "s1": "7"}[identifier]}
        ]

    source.write_text(text.replace("| 8 |", "| 9 |"), encoding="utf-8")
    assert scenarios.states(model, root)[0][1]["alpha__size"] == [("s1", 3), ("sample-item", 9)]
    assert form_path.read_bytes() == original_form


class MissingOptionalFactState(Exception):
    pass


def test_lower_named_dataset(declared_dataset, tmp_path, capsys):
    root, form, submitted = declared_dataset
    form.write_text(json.dumps(submitted), encoding="utf-8")
    source = form.with_suffix(".rezono")
    authored = ('rezono 0\npack minimal\ndataset sample\n  fact Alpha\n'
                '    | id | title | size |\n'
                '    | a-one | "One" | n/a |\n    | a-two | "Two" | 8 |\n')
    model = pack.read(root)
    legacy = tmp_path / "sample.yaml"
    legacy.write_text(
        'alpha:\n  - {id: a-one, title: One}\n  - {id: a-two, title: Two, size: 8}\n', encoding="utf-8",
    )
    expected = facts.load(model, legacy)
    assert expected["alpha__size"] == [("a-two", 8)]

    source.write_text(authored.replace("| n/a |", "| 3 |"), encoding="utf-8")
    known = scenarios.states(model, root)[0][1]
    assert known["alpha__size"] == [("a-one", 3), ("a-two", 8)]
    source.write_text(authored, encoding="utf-8")
    status = main(["check", str(root)])
    report = capsys.readouterr()
    if status == 1 and "alpha[1].size: 'n/a' is not a BIGINT" in report.err:
        raise MissingOptionalFactState(report.err.strip())
    assert status == 0, report.err
    assert facts.load(model, form) == expected
    assert scenarios.states(model, root)[0][1] == expected
    assert form.read_bytes() == json.dumps(submitted).encode("utf-8")


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
