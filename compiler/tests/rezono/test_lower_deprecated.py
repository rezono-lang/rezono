"""A deprecated kind or enum must lower to its LinkML element with the note in `deprecated` and the date in the
annotation `deprecated_until` (decisions/language-deprecation.md, section Lowering). The module form is written
by hand from that decision, independently of the Rezono reader; the expected schema is written out below."""

import json

import pytest

from rezono_compiler import rezono_module

ZONE = {"kind": "Zone", "world": "closed", "slots": [{"slot": "name", "type": "Text"}], "derived": []}
MODE = {"enum": "Mode", "values": ["audit", "enforce"]}
ZONE_CLASS = {"attributes": {"id": {"identifier": True}, "name": {"range": "string", "required": True}}}
MODE_ENUM = {"permissible_values": {"audit": {}, "enforce": {}}}


def lowered(tmp_path, decls: list, form_format: str) -> tuple[dict | None, list]:
    form = {"format": form_format, "module": {"rezono": "0", "pack": "sample", "use": [], "decls": decls},
            "spans": []}
    declaration = rezono_module.Declared("rezono/zone.rezono", "rezono/zone.json", "facts")
    errors = []
    result = rezono_module.lower(tmp_path, declaration, form, "sample", {}, errors)
    return (result.schema if result is not None else None), errors


class MissingDeprecatedLowering(AssertionError):
    """The compiler refused a deprecated kind or enum, or lowered it otherwise than the decision gives."""


def test_lower_deprecated(tmp_path):
    # Counter-case: without the member the kind and the enum lower as before.
    plain, errors = lowered(tmp_path / "plain", [ZONE, MODE], "rezono.module/1")
    assert not errors and plain["classes"]["Zone"] == ZONE_CLASS and plain["enums"]["Mode"] == MODE_ENUM, errors

    decls = [ZONE | {"deprecated": {"note": "use ProviderZone", "until": "2027-07-01"}},
             MODE | {"deprecated": {"note": "use PolicyMode", "until": "2028-01-31"}}]
    schema, errors = lowered(tmp_path / "deprecated", decls, "rezono.module/2")
    expected = {
        "Zone": ZONE_CLASS | {"deprecated": "use ProviderZone", "annotations": {"deprecated_until": "2027-07-01"}},
        "Mode": MODE_ENUM | {"deprecated": "use PolicyMode", "annotations": {"deprecated_until": "2028-01-31"}},
    }
    actual = None if schema is None else {"Zone": schema["classes"].get("Zone"), "Mode": schema["enums"].get("Mode")}
    if errors or actual != expected:
        raise MissingDeprecatedLowering(json.dumps({"errors": errors, "lowered": actual}, indent=2))
