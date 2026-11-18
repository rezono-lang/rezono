import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower bounded list in compiler/rezono_compiler/rezono_module.py. Read decisions/language-slots.md. Waits for test_lower_parent_kind (same compiler lowering module).",
)
def test_lower_bounded_list(tmp_path):
    decl = kind("Work", slot("authors", "Text", card="*", constraints=[{"cardinality": ["1", "3"]}]))
    actual, oracle = compare_input(tmp_path, "library", decl)
    authors = actual["classes"]["Work"]["attributes"]["authors"]
    expected = oracle["classes"]["Work"]["attributes"]["authors"]
    for field in ("multivalued", "minimum_cardinality", "maximum_cardinality"):
        assert authors.get(field) == expected[field]
