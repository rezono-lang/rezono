"""A cited source in a dataset must publish the same row sources as the equivalent `.sources.yaml` sidecar."""

import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler.__main__ import main
from support import FIXTURE


ROWS = 'alpha:\n  - {id: a-one, title: One}\n  - {id: a-two, title: Two}\n'
SIDECAR = {
    "default": {"kind": "tool", "name": "Release notice inspection", "position": "L1"},
    "records": [{"of": {"kind": "alpha", "id": "a-one"}, "revision": "19.2.0"}],
}
FORM = {"format": "rezono.module/2", "spans": [], "module": {
    "rezono": "0", "pack": "minimal", "use": [], "decls": [{"dataset": "sample", "decls": [
        {"source": "notices", "fields": {"kind": "tool", "name": "Release notice inspection", "position": "L1"}},
        {"fact": "Alpha", "source": "notices", "columns": ["id", "title"], "sourceColumns": ["revision"], "rows": [
            [{"lit": "a-one"}, {"lit": '"One"'}, {"lit": '"19.2.0"'}],
            [{"lit": "a-two"}, {"lit": '"Two"'}, {"boundary": "omitted"}],
        ]},
    ]}],
}}
# Form-only input isolates the lowering from the source reader (test_fact_provenance).
TEXT = "rezono 0\npack minimal\ndataset sample\n"


def published(directory, tmp_path, capsys):
    output = tmp_path / "out" / directory.parent.name
    status = main(["compile", str(directory), str(output)])
    report = capsys.readouterr()
    assert status == 0, report.err
    entries = json.loads((output / "generated/sources.json").read_bytes())
    return {(entry["row"]["relation"], entry["row"]["key"]): entry["sources"] for entry in entries}


def test_lower_fact_provenance(tmp_path, capsys):
    legacy = Path(shutil.copytree(FIXTURE, tmp_path / "legacy" / "minimal"))
    (legacy / "facts").mkdir()
    (legacy / "facts/sample.yaml").write_text(ROWS, encoding="utf-8")
    (legacy / "facts/sample.sources.yaml").write_text(yaml.safe_dump(SIDECAR), encoding="utf-8")
    expected = published(legacy, tmp_path, capsys)
    one = expected[("alpha", '["a-one"]')]
    two = expected[("alpha", '["a-two"]')]
    assert one == [{"kind": "tool", "name": "Release notice inspection", "position": "L1", "revision": "19.2.0"}]
    # Counter-case: a row without its own source cell has the declaration's fields only.
    assert two == [{"kind": "tool", "name": "Release notice inspection", "position": "L1"}]

    candidate = Path(shutil.copytree(FIXTURE, tmp_path / "candidate" / "minimal"))
    (candidate / "rezono").mkdir()
    (candidate / "rezono/sample.rezono").write_text(TEXT, encoding="utf-8")
    (candidate / "rezono/sample.json").write_text(json.dumps(FORM), encoding="utf-8")
    with (candidate / "pack.yaml").open("a", encoding="utf-8") as stream:
        yaml.safe_dump({"rezono": [{"module": "rezono/sample.rezono", "form": "rezono/sample.json",
                                    "layer": "facts"}]}, stream)
    actual = published(candidate, tmp_path, capsys)
    assert {key: value for key, value in actual.items() if key[0] == "alpha"} == {
        key: value for key, value in expected.items() if key[0] == "alpha"}
