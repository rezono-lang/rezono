import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower composite key in compiler/rezono_compiler/rezono_module.py. Read decisions/language-keys.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_composite_key(tmp_path):
    decl = kind("Category", slot("name", "Text"), slot("parent", "Category", card="?"),
                keys=[{"unique": "name_within_parent", "slots": ["parent", "name"]}])
    actual, oracle = compare_input(tmp_path, "library", decl)
    assert actual["classes"]["Category"].get("unique_keys") == oracle["classes"]["Category"]["unique_keys"]
