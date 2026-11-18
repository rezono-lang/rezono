import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement bounded slot in rezono/src. Read decisions/language-slots.md. Waits for test_parent_kind (shared module reader and printer).")
def test_bounded_slot():
    assert_reader_case("bounded_slot")
