"""One compiler-only prerequisite for a library dataset, independent of the Rezono reader."""

import json
from pathlib import Path

import pytest

from rezono_compiler import facts, pack


LIBRARY = Path(__file__).resolve().parents[3] / "examples/library"


def test_scalar_dataset_rows(tmp_path):
    table = {
        "fact": "Copy", "columns": ["barcode", "reference_only"],
        "rows": [[{"lit": "1001"}, {"lit": "false"}], [{"lit": "1003"}, {"lit": "true"}]],
    }
    form = {"format": "rezono.module/2", "spans": [], "module": {
        "rezono": "0", "pack": "library", "use": [], "decls": [{"dataset": "sample", "decls": [table]}],
    }}
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(form), encoding="utf-8")
    model = pack.read(LIBRARY)
    oracle = facts.load(model, LIBRARY / "facts/valid.yaml")
    actual = facts.load(model, path)
    for relation in ("copy", "copy__reference_only"):
        expected = [row for row in oracle[relation] if row[0] in {1001, 1003}]
        assert actual[relation] == expected
        assert all(type(row[0]) is int for row in actual[relation])
    assert all(type(value) is bool for _, value in actual["copy__reference_only"])
