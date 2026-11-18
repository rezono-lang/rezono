import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower numeric limits in compiler/rezono_compiler/rezono_module.py. Read decisions/language-slots.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_numeric_limits(tmp_path):
    decl = kind("Task", slot("estimate", "Int", card="?", constraints=[{"minimum": "1"}, {"maximum": "200"}]))
    actual, oracle = compare_input(tmp_path, "projects", decl)
    estimate = actual["classes"]["Task"]["attributes"]["estimate"]
    expected = oracle["classes"]["Task"]["attributes"]["estimate"]
    for field in ("range", "minimum_value", "maximum_value"):
        assert estimate.get(field) == expected[field]
    assert estimate.get("required", False) == expected.get("required", False)
