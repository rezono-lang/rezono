"""`sealed at` must lower to the seal annotation of the public subsidy schema."""

import pytest

from model_parity import kind, lower_declarations, schema_file, slot


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Lower the kind member sealed to the LinkML class annotation seal in compiler/rezono_compiler/rezono_kind.py "
           "instead of refusing it. Read docs/rezono/v0.md (sealed at, section 5a) and decisions/language-native-rules.md "
           "(Seal). Waits for test_lower_relationship_kind while it owns rezono_kind.py.",
)
def test_lower_time_policy(tmp_path):
    oracle = schema_file("examples/subsidy/schema/reference.yaml")["classes"]["LedgerPayment"]
    declaration = kind("LedgerPayment", slot("application", "Application"), slot("booked_on", "Date"),
                       slot("amount", "Cents"), sealed="booked_on")
    actual = lower_declarations(tmp_path, "subsidy", [declaration],
                                external=["Application", "Cents"])["classes"]["LedgerPayment"]
    assert actual["annotations"]["seal"] == oracle["annotations"]["seal"] == "booked_on"

    # Counter-case: without `sealed at` the kind has no seal.
    unsealed = kind("LedgerPayment", slot("booked_on", "Date"))
    actual = lower_declarations(tmp_path, "subsidy", [unsealed])["classes"]["LedgerPayment"]
    assert "seal" not in (actual.get("annotations") or {})
