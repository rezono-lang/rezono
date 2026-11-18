"""The authored slot type must reach the schema bundle through the compile command.

The two spellings already occur in fixtures/rezono/kinds.rezono. The independent
kinds.yaml gives Date the date range and Text the string range.
"""

import json

import pytest

from rezono_compiler.__main__ import main
from test_rezono_module import written


def compiled_slots(directory, output):
    assert main(["compile", str(directory), str(output)]) == 0
    bundle = json.loads((output / "bundle/schema-bundle.json").read_bytes())
    return {
        slot["id"]: (slot["type"], slot["required"])
        for slot in bundle["attributes"]
        if slot["id"] in {"gamma.since", "gamma.note"}
    }


def test_authored_slot_types_in_the_original_bundle(tmp_path):
    directory = written(tmp_path, "module")
    assert compiled_slots(directory, tmp_path / "output") == {
        "gamma.since": ("date", False),
        "gamma.note": ("text", True),
    }


def test_compile_uses_the_authored_slot_type_after_an_edit(tmp_path):
    directory = written(tmp_path, "module")
    source = directory / "rezono/kinds.rezono"
    original = source.read_bytes()
    assert original.count(b"since: Date?") == 1
    source.write_bytes(original.replace(b"since: Date?", b"since: Text?"))

    # The edit preserves every source offset. The submitted JSON form still says Date.
    assert compiled_slots(directory, tmp_path / "output") == {
        "gamma.since": ("text", False),
        "gamma.note": ("text", True),
    }
