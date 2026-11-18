import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement scalar alias in rezono/src. Read decisions/language-slots.md. Waits for independent module reader and printer registrations. Use the file priority in docs/rezono/language-coverage.md.")
def test_scalar_alias():
    assert_reader_case("scalar_alias")
