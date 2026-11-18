"""Compare lowering with the library schema, independently of the Rezono reader."""

from pathlib import Path

import pytest
import yaml

from rezono_compiler import rezono_module


LIBRARY = Path(__file__).resolve().parents[3] / "examples" / "library"


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
    schema = yaml.safe_load((LIBRARY / "schema/library.yaml").read_text(encoding="utf-8"))
    assert result.schema["classes"]["Copy"]["attributes"][name] == schema["classes"]["Copy"]["attributes"][name]
