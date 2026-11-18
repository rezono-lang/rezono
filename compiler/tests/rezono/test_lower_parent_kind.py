import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower parent kind in compiler/rezono_compiler/rezono_module.py. Read decisions/language-kinds.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_parent_kind(tmp_path):
    decl = kind("Staff", slot("branch", "Branch"), parent="Person")
    actual, oracle = compare_input(tmp_path, "library", decl, external=["Person", "Branch"])
    staff = actual["classes"]["Staff"]
    expected = oracle["classes"]["Staff"]
    assert staff.get("is_a") == expected["is_a"]
    assert staff["attributes"] == expected["attributes"]
