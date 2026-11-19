"""Close and broad mappings of a kind and its slots must lower to the public std-time schema's lists."""

import pytest

from model_parity import kind, lower_declarations, schema_file, slot


MAPPINGS = ("exact_mappings", "close_mappings", "broad_mappings")


def mappings(definition):
    return {name: definition.get(name, []) for name in MAPPINGS}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Admit closeMappings and broadMappings beside exactMappings in the module/2 contract "
           "(contracts/rezono-module.yaml) and lower them in compiler/rezono_compiler/rezono_metadata.py. "
           "Read decisions/language-metadata.md, section Close and broad mappings. No reader dependency.",
)
def test_lower_schema_mappings(tmp_path):
    oracle = schema_file("packs/std-time/schema/time.yaml")["classes"]["ReferencePoint"]
    declaration = kind(
        "ReferencePoint",
        slot("on_axis", "Axis", closeMappings=["time:hasTRS"]),
        slot("position", "Int", broadMappings=["time:numericPosition"]),
        slot("horizon", "Int", broadMappings=["time:numericDuration"], constraints=[{"minimum": "0"}]),
        closeMappings=["time:Instant"],
    )
    actual = lower_declarations(tmp_path, "std-time", [declaration], external=["Axis"])["classes"]["ReferencePoint"]
    assert mappings(actual) == mappings(oracle)
    for name in ("on_axis", "position", "horizon"):
        assert mappings(actual["attributes"][name]) == mappings(oracle["attributes"][name]), name
