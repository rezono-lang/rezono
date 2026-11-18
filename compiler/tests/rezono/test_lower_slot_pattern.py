import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower slot pattern in compiler/rezono_compiler/rezono_module.py. Read decisions/language-slots.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_slot_pattern(tmp_path):
    decl = kind("Address", slot("postcode", "Text", card="?", constraints=[{"pattern": "^[1-9][0-9]{3} ?[A-Z]{2}$"}]))
    actual, oracle = compare_input(tmp_path, "library", decl)
    postcode = actual["classes"]["Address"]["attributes"]["postcode"]
    expected = oracle["classes"]["Address"]["attributes"]["postcode"]
    assert postcode.get("pattern") == expected["pattern"]
    assert postcode.get("required", False) == expected.get("required", False)
