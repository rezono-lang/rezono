import pytest

from model_parity import compare_input


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower scalar alias in compiler/rezono_compiler/rezono_module.py. Read decisions/language-slots.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_scalar_alias(tmp_path):
    decl = {"type": "Cents", "base": "Int"}
    actual, oracle = compare_input(tmp_path, "projects", decl)
    assert actual.get("types", {}).get("Cents", {}).get("typeof") == oracle["types"]["Cents"]["typeof"]
