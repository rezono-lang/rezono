import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower embedded reference in compiler/rezono_compiler/rezono_module.py. Read decisions/language-relations.md. Waits for test_lower_embedded_kind (same compiler lowering module).",
)
def test_lower_embedded_reference(tmp_path):
    decl = kind("Branch", slot("address", "Address", embedded=True))
    actual, oracle = compare_input(tmp_path, "library", decl, external=["Address"])
    assert actual["classes"]["Branch"]["attributes"]["address"] == oracle["classes"]["Branch"]["attributes"]["address"]
