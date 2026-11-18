import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower embedded kind in compiler/rezono_compiler/rezono_module.py. Read decisions/language-kinds.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_embedded_kind(tmp_path):
    decl = kind("Address", slot("street", "Text"), embedded=True)
    actual, oracle = compare_input(tmp_path, "library", decl)
    for schema in (actual, oracle):
        attrs = schema["classes"]["Address"]["attributes"]
        assert attrs["street"]["required"] is True
        assert not any(attr.get("identifier") for attr in attrs.values())
