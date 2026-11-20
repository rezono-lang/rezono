"""A module without a header, with only `schema <module>`, and with every default written out lowers to the same
LinkML schema (decisions/language-readable-rules.md, section 1, One lowering). The module forms are written by hand
from that decision; the expected header members are its table of defaults."""

import json

import pytest
from rezono_compiler import rezono_module

ZONE = {"kind": "Zone", "world": "closed", "slots": [{"slot": "name", "type": "Text"}], "derived": []}
DEFAULTS = {"id": "https://rezono.org/rezono/sample/zone", "name": "zone", "imports": ["linkml:types"],
            "default_range": "string", "annotations": {"layer": "facts"}}


def lowered(tmp_path, header: dict) -> tuple[dict | None, list]:
    form = {"format": "rezono.module/2", "module": {"rezono": "0", "pack": "sample", "use": [], **header,
                                                    "decls": [ZONE]}, "spans": []}
    declaration = rezono_module.Declared("rezono/zone.rezono", "rezono/zone.json", "facts")
    errors = []
    result = rezono_module.lower(tmp_path, declaration, form, "sample", {}, errors)
    return (result.schema if result is not None else None), errors


class MissingHeaderDefaults(AssertionError):
    """Two headers that differ only in written defaults lowered to different schemas."""


def test_lower_readable_header(tmp_path):
    full = {"schema": "zone", "iri": DEFAULTS["id"], "imports": ["linkml:types"], "defaultRange": "Text",
            "annotations": {"layer": "facts"}}
    schemas = {}
    for name, header in (("none", {}), ("schema", {"schema": "zone"}), ("full", full)):
        schema, errors = lowered(tmp_path / name, header)
        assert not errors and schema is not None, errors
        schemas[name] = {key: value for key, value in schema.items() if key not in ("classes", "enums")}
    # Counter-case: an iri that deviates from the default is kept.
    deviating, errors = lowered(tmp_path / "iri", {"schema": "zone", "iri": "https://rezono.example/zone"})
    assert not errors and deviating["id"] == "https://rezono.example/zone", errors
    if any(schema != DEFAULTS for schema in schemas.values()):
        raise MissingHeaderDefaults(json.dumps({"expected": DEFAULTS, "lowered": schemas}, indent=2))
