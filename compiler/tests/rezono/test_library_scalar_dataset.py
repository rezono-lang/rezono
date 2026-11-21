"""One compiler-only prerequisite for a library dataset, independent of the Rezono reader."""

import json
from pathlib import Path

import pytest

from model_parity import legacy_file_bytes
from rezono_compiler import facts, pack


LIBRARY = Path(__file__).resolve().parents[3] / "examples/library"


def scalar_copy_form():
    table = {
        "fact": "Copy", "columns": ["barcode", "reference_only"],
        "rows": [[{"lit": "1001"}, {"lit": "false"}], [{"lit": "1003"}, {"lit": "true"}]],
    }
    return {"format": "rezono.module/2", "spans": [], "module": {
        "rezono": "0", "pack": "library", "use": [], "decls": [{"dataset": "sample", "decls": [table]}],
    }}


def test_scalar_dataset_rows(tmp_path):
    form = scalar_copy_form()
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(form), encoding="utf-8")
    legacy_valid = tmp_path / "valid.yaml"
    legacy_valid.write_bytes(legacy_file_bytes("examples/library/facts/valid.yaml"))
    model = pack.read(LIBRARY)
    oracle = facts.load(model, legacy_valid)
    actual = facts.load(model, path)
    for relation in ("copy", "copy__reference_only"):
        expected = [row for row in oracle[relation] if row[0] in {1001, 1003}]
        assert actual[relation] == expected
        assert all(type(row[0]) is int for row in actual[relation])
    assert all(type(value) is bool for _, value in actual["copy__reference_only"])


@pytest.mark.parametrize(("part", "field", "value", "message"), [
    ("module", "pack", "other", "names other, not this pack, library"),
    ("module", "pack", None, "module header"),
    ("module", "rezono", "999", "line says 0"),
    ("module", "rezono", None, "line says 0"),
    ("module", "use", [{"use": "std.money"}], "use` line is not lowered"),
    ("module", "use", {}, "module header"),
    ("module", "foreign", [], "module header"),
    ("form", "foreign", [], "module header"),
    ("form", "spans", {}, "module header"),
    ("form", "spans", None, "module header"),
])
def test_scalar_dataset_refuses_invalid_module_header(tmp_path, part, field, value, message):
    form = scalar_copy_form()
    header = form["module"] if part == "module" else form
    if value is None:
        del header[field]
    else:
        header[field] = value
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(form), encoding="utf-8")
    with pytest.raises(facts.LoadError, match=message):
        facts.load(pack.read(LIBRARY), path)
