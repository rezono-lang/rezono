import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower explicit identifier in compiler/rezono_compiler/rezono_module.py. Read decisions/language-kinds.md. Waits for test_library_boolean_slot (same lowering module); independent of the reader.",
)
def test_lower_explicit_identifier(tmp_path):
    decl = kind("Branch", slot("code", "Text", identifier=True))
    actual, oracle = compare_input(tmp_path, "library", decl)

    def identifiers(schema):
        attrs = schema["classes"]["Branch"]["attributes"]
        return [(key, attr.get("range", schema["default_range"])) for key, attr in attrs.items() if attr.get("identifier")]

    assert identifiers(actual) == identifiers(oracle)
