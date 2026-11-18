import pytest

from model_parity import compare_input, kind, slot


def test_lower_explicit_identifier(tmp_path):
    decl = kind("Branch", slot("code", "Text", identifier=True))
    actual, oracle = compare_input(tmp_path, "library", decl)

    def identifiers(schema):
        attrs = schema["classes"]["Branch"]["attributes"]
        return [(key, attr.get("range", schema["default_range"])) for key, attr in attrs.items() if attr.get("identifier")]

    assert identifiers(actual) == identifiers(oracle)
