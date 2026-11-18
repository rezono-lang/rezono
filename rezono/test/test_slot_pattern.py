import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement slot pattern in rezono/src. Read decisions/language-slots.md. Waits for independent module reader and printer registrations. Use the file priority in docs/rezono/language-coverage.md.")
def test_slot_pattern():
    assert_reader_case("slot_pattern")
