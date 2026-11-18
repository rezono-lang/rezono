"""Compare an authored scalar fact table with the ordinary legacy record loader."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from rezono_compiler import facts, pack, scenarios
from rezono_compiler.__main__ import main


ROOT = Path(__file__).resolve().parents[3]


class MissingFactTableLowering(Exception):
    pass


@pytest.mark.xfail(strict=True, raises=MissingFactTableLowering,
                   reason="Admit the base fact table through the ordinary compiler and fact loader.")
def test_lower_fact_table(tmp_path, capsys):
    fixture = ROOT / "compiler/tests/fixtures/minimal"
    legacy = Path(shutil.copytree(fixture, tmp_path / "legacy"))
    candidate = Path(shutil.copytree(fixture, tmp_path / "candidate"))
    (legacy / "facts").mkdir()
    oracle = legacy / "facts/sample.yaml"
    oracle.write_text(
        'alpha:\n  - {id: a-one, title: One, size: 3}\n  - {id: a-two, title: Two, size: 8}\n',
        encoding="utf-8",
    )
    expected = facts.load(pack.read(legacy), oracle)
    assert expected["alpha__size"] == [("a-one", 3), ("a-two", 8)]
    assert main(["check", str(legacy)]) == 0
    capsys.readouterr()

    source = candidate / "rezono/sample.rezono"
    source.parent.mkdir()
    source.write_text(
        'rezono 0\npack minimal\nfact Alpha\n'
        '  | id | title | size |\n  | a-one | "One" | 3 |\n  | a-two | "Two" | 8 |\n',
        encoding="utf-8",
    )
    form = source.with_suffix(".json")
    subprocess.run([os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"),
                    str(source), str(form)], check=True)
    assert json.loads(form.read_bytes())["format"] == "rezono.module/1"
    with (candidate / "pack.yaml").open("a", encoding="utf-8") as stream:
        yaml.safe_dump({"rezono": [{"module": "rezono/sample.rezono", "form": "rezono/sample.json",
                                    "layer": "facts"}]}, stream)

    output = tmp_path / "compiled"
    status = main(["compile", str(candidate), str(output)])
    report = capsys.readouterr()
    if status == 1 and "sample.rezono:3: a fact table is not lowered yet" in report.err:
        raise MissingFactTableLowering(report.err.strip())
    assert status == 0, report.err
    assert main(["check", str(candidate)]) == 0
    assert facts.files(candidate) == [form]
    model = pack.read(candidate)
    assert facts.load(model, form) == expected
    assert scenarios.states(model, candidate)[0][1] == expected

    entries = json.loads((output / "generated/sources.json").read_bytes())
    assert {(entry["row"]["relation"], tuple(json.loads(entry["row"]["key"]))[:1])
            for entry in entries} == {
        (relation, row[:1]) for relation, relation_rows in expected.items() for row in relation_rows
    }
    for entry in entries:
        subject = json.loads(entry["row"]["key"])[0]
        assert entry["sources"] == [{
            "kind": "pack", "name": "rezono/sample.rezono", "position": {"a-one": "5", "a-two": "6"}[subject],
        }]
