import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement scalar alias in rezono/src. Read decisions/language-slots.md. Waits for test_numeric_limits (shared module reader and printer).")
def test_scalar_alias():
    assert_reader_case("scalar_alias")
