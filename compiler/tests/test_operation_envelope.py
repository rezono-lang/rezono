"""The public OperationSet contract fixes the fields of a schema-change document."""

import pytest
import yaml

from rezono_compiler import operate


def write_change(tmp_path, **extra):
    doc = {"format": "rezono.operations/1", "pack": "sample",
           "operations": [{"op": "rename", "kind": "Point", "to": "Mark"}], **extra}
    path = tmp_path / "change.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def test_named_pack_and_one_rename_are_valid(tmp_path):
    assert operate.load(write_change(tmp_path))["operations"] == [
        {"op": "rename", "kind": "Point", "to": "Mark"}
    ]


def test_unrecognized_operation_set_field_is_refused(tmp_path):
    with pytest.raises(operate.OperationError, match="preview"):
        operate.load(write_change(tmp_path, preview=True))
