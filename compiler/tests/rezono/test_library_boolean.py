"""Compare lowering with the library schema, independently of the Rezono reader."""

import pytest

from model_parity import schema_file
from rezono_compiler import rezono_module


def test_library_boolean_slot(tmp_path):
    name = "reference_only"
    slot = {"slot": name, "type": "Bool"}
    kind = {"kind": "Copy", "world": "closed", "slots": [slot], "derived": []}
    form = {
        "format": "rezono.module/1",
        "module": {"rezono": "0", "pack": "library", "use": [], "decls": [kind]},
        "spans": [],
    }
    declaration = rezono_module.Declared("rezono/library.rezono", "rezono/library.json", "facts")
    errors = []
    result = rezono_module.lower(tmp_path, declaration, form, "library", {}, errors)
    assert not errors, errors
    schema = schema_file("examples/library/schema/library.yaml")
    assert result.schema["classes"]["Copy"]["attributes"][name] == schema["classes"]["Copy"]["attributes"][name]
