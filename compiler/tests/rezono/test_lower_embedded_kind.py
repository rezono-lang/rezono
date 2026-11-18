import pytest

from model_parity import compare_input, kind, slot


def test_lower_embedded_kind(tmp_path):
    decl = kind("Address", slot("street", "Text"), embedded=True)
    actual, oracle = compare_input(tmp_path, "library", decl)
    for schema in (actual, oracle):
        attrs = schema["classes"]["Address"]["attributes"]
        assert attrs["street"]["required"] is True
        assert not any(attr.get("identifier") for attr in attrs.values())
