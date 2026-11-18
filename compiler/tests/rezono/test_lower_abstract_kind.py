import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower abstract kind in compiler/rezono_compiler/rezono_module.py. Read decisions/language-kinds.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_abstract_kind(tmp_path):
    decl = kind("Person", slot("name", "Text"), abstract=True)
    actual, oracle = compare_input(tmp_path, "library", decl)
    assert actual["classes"]["Person"].get("abstract", False) == oracle["classes"]["Person"]["abstract"]
