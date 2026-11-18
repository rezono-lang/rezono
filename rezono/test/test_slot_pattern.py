import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement slot pattern in rezono/src. Read decisions/language-slots.md. Waits for test_bounded_slot (shared module reader and printer).")
def test_slot_pattern():
    assert_reader_case("slot_pattern")
