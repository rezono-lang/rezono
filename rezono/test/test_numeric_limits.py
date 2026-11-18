import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement numeric limits in rezono/src. Read decisions/language-slots.md. Waits for test_slot_pattern (shared module reader and printer).")
def test_numeric_limits():
    assert_reader_case("numeric_limits")
